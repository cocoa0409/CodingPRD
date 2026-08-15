"""Hierarchical existence validation and immutable reference data (PRD §2.4, §2.6, §3.3)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_benchmark_cut_point,
    create_benchmark_cut_point_payload,
    create_district,
    create_school,
    enroll_student,
    setup_district_school,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORD = TEST_USERS["district_coordinator_headers"]
REGISTRAR = TEST_USERS["school_registrar_headers"]
LEAD = TEST_USERS["team_lead_headers"]


class TestNestedExistence:
    def test_missing_window_returns_window_not_found(self, api):
        """PRD §2.4: "The request is rejected immediately with the 404 error
        corresponding to the first identifier that does not resolve —
        `ERR_DISTRICT_NOT_FOUND`, `ERR_SCHOOL_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`,
        `ERR_WINDOW_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_MOVEMENT_NOT_FOUND`,
        `ERR_MEETING_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`,
        `ERR_CATALOG_NOT_FOUND`, or `ERR_INTERVENTIONIST_NOT_FOUND` — before any
        state or business rule is consulted."

        Design: Corner/entities/screening_window_not_found_returns_404
        """
        district, school = setup_district_school(api)
        resp = api.get_screening_window(district["id"], school["id"],
                                        NON_EXISTENT_UUID, COORD)
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_FOUND, 404)

    def test_student_not_found_under_wrong_school(self, api):
        """PRD §2.4: "Every resource in the system hangs off a district. For any
        endpoint whose path contains multiple resource identifiers, existence is
        validated in a strict left-to-right order: `districtId` first, then
        `schoolId`, then the next-level identifier (`studentId`, `meetingId`, or
        `windowId`), and finally the leaf identifier (`planId`, `probeId`, or
        `referralId`)."
        PRD §2.4: "The request is rejected immediately with the 404 error
        corresponding to the first identifier that does not resolve"

        Design: Corner/entities/student_not_found_under_wrong_school
        """
        district = create_district(api, name="D")
        school_a = create_school(api, district["id"], name="A",
                                 grade_span_low=0, grade_span_high=5)
        school_b = create_school(api, district["id"], name="B",
                                 grade_span_low=0, grade_span_high=5)
        student = enroll_student(api, district["id"], school_a["id"],
                                 full_name="X", grade_level=1)

        # The student's id resolves under its owning school...
        ok = api.get_student(district["id"], school_a["id"], student["id"], LEAD)
        validate_success(ok, 200)
        # ...but not under a different school in the same district.
        resp = api.get_student(district["id"], school_b["id"], student["id"], LEAD)
        validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_FOUND, 404)


class TestBenchmarkCutPoints:
    def test_cut_point_is_immutable_reference_data(self, api):
        """PRD §2.6: "Resources that are immutable or append-only after creation
        carry only `id` and `created_at`; both `updated_at` and `version` are
        absent from them. This applies to benchmark cut points (immutable
        reference data — a correction creates a new cut point rather than editing
        the old one), to screening scores (append-only — a correction supersedes
        the old row with a new one), to progress probes (append-only
        measurements), and to intervention sessions."

        Design: Corner/entities/benchmark_cut_point_immutability
        """
        district, school = setup_district_school(api)
        resp = api.create_benchmark_cut_point(
            district["id"], school["id"],
            create_benchmark_cut_point_payload(window_kind="FALL", grade_level=3,
                                               subject="READING",
                                               tier2_max_score=100,
                                               tier3_max_score=70),
            COORD)
        cut = validate_success(resp, 201)
        assert_benchmark_cut_point(cut)
        assert "updated_at" not in cut, "immutable resource must not carry updated_at"
        assert "version" not in cut, "immutable resource must not carry version"

        listed = validate_success(api.list_benchmark_cut_points(
            district["id"], school["id"], COORD))
        assert isinstance(listed, list) and len(listed) == 1
        assert "updated_at" not in listed[0] and "version" not in listed[0]

    def test_cut_point_requires_tier3_strictly_below_tier2(self, api):
        """PRD §3.3: "The `tier3_max_score` must be strictly less than the
        `tier2_max_score`; a definition that violates this is rejected with
        `ERR_INVALID_CUT_POINT` (HTTP 400)."

        Design: Corner/entities/invalid_cut_point_ordering_rejected
        """
        district, school = setup_district_school(api)
        # Equal thresholds violate strict ordering.
        resp = api.create_benchmark_cut_point(
            district["id"], school["id"],
            create_benchmark_cut_point_payload(tier2_max_score=100,
                                               tier3_max_score=100),
            COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_CUT_POINT, 400)
        # Inverted thresholds violate it too.
        resp2 = api.create_benchmark_cut_point(
            district["id"], school["id"],
            create_benchmark_cut_point_payload(tier2_max_score=70,
                                               tier3_max_score=100),
            COORD)
        validate_error(resp2, ApiErrorId.ERR_INVALID_CUT_POINT, 400)
