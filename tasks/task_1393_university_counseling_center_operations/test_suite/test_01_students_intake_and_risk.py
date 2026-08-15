"""Student registration, intake assessment creation, and risk banding."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_intake_assessment,
    assert_student,
    create_counselor,
    create_intake,
    create_student,
    is_valid_uuid,
    make_triage_screener_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

FD = TEST_USERS["front_desk_headers"]


def _fd():
    return FD


class TestStudentCreation:

    def test_student_creation_defaults_applied(self):
        """PRD section 3.1: "New students start with `booking_posture`
        initialized to `CLEAR` and a `no_show_strike_count` of zero, and their
        `strike_reset_anchor` defaults to the epoch (1970-01-01T00:00:00Z)
        until a director reset moves it."

        Design: Corner/entities/student_creation_defaults_applied
        """
        resp = api_client.create_student(
            {
                "student_number": "E100",
                "full_name": "Default Stud",
                "enrollment_status": "ENROLLED",
                "funding_model": "STUDENT_FEE",
            },
            _fd(),
        )
        data = validate_success(resp, expected_status=201)
        assert_student(data)
        assert data["booking_posture"] == "CLEAR", \
            f"new student posture must be CLEAR, got {data['booking_posture']}"
        assert data["no_show_strike_count"] == 0
        assert data["strike_reset_anchor"] == "1970-01-01T00:00:00Z", \
            f"strike_reset_anchor must default to the epoch, got {data['strike_reset_anchor']}"
        assert isinstance(data["version"], int)
        assert is_valid_uuid(data["id"])

    def test_student_get_not_found_returns_404(self):
        """PRD section 2.8: "Existence — every identifier in the URL path and
        every foreign key in the payload must resolve to an existing entity
        (`ERR_NOT_FOUND`)."

        Design: Corner/entities/student_get_not_found_returns_404
        """
        resp = api_client.get_student(NON_EXISTENT_UUID, _fd())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_student_duplicate_student_number_rejected(self):
        """PRD section 3.1: "The `student_number` is unique across all
        students and immutable after creation; a colliding registration is
        rejected with `ERR_DUPLICATE`."

        Design: Corner/entities/student_duplicate_student_number_rejected
        """
        create_student("DUP1", "First")
        resp = api_client.create_student(
            {
                "student_number": "DUP1",
                "full_name": "Second",
                "enrollment_status": "ENROLLED",
                "funding_model": "INSURANCE",
            },
            _fd(),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)

    def test_student_missing_required_field_rejected(self):
        """PRD section 2.8: "Request shape — required body fields must be
        present and well-typed, enum values must be in range, and scores must
        lie within their declared bounds (`ERR_INVALID_REQUEST`)."
        PRD section 3.1: registration supplies "the institution-issued
        `student_number`, the student's `full_name`, their `enrollment_status`
        ... and their `funding_model`".

        Design: Corner/entities/student_missing_required_field_rejected
        """
        resp = api_client.create_student(
            {
                "student_number": "E600",
                "full_name": "Missing Field",
                "enrollment_status": "ENROLLED",
            },
            _fd(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_student_list_pagination_envelope(self):
        """PRD section 2.3: "Paginated list responses include the following
        fields in the `meta` object of the response envelope: `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/student_list_pagination_envelope
        """
        for n in ("E701", "E702", "E703"):
            create_student(n, "Page Stud")
        resp = api_client.list_students(_fd(), params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 2, f"limit=2 must return 2 rows, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0


class TestIntakeAssessmentCreation:

    def test_intake_assessment_is_append_only_and_scored(self):
        """PRD section 2.4: "an IntakeAssessment, a GroupEnrollment, an
        OutcomeMeasure, and a ClinicalNote each carry only `id` and
        `created_at`. Both `updated_at` and `version` are absent from these
        four resources".
        PRD section 3.3: "The composite `risk_points` begin with a base equal
        to the sum of the two instrument totals."

        Design: Corner/entities/intake_assessment_immutable_no_update_endpoint
        """
        counselor = create_counselor(license_id="LIC-E4",
                                     specialties=["TRIAGE"], weekly_capacity=10,
                                     max_risk_points=500)
        student = create_student("E400", "Immut Stud")
        resp = api_client.create_intake_assessment(
            {
                "student_id": student["id"],
                "screener_id": counselor["id"],
                "phq9_score": 5,
                "gad7_score": 5,
                "ideation_flag": False,
                "recent_attempt_flag": False,
            },
            make_triage_screener_headers(counselor["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert_intake_assessment(data)
        assert data["risk_points"] == 10, \
            f"5+5 with no flags must score 10, got {data['risk_points']}"
        assert data["risk_band"] == "LOW"
        assert data["disposition"] == "PENDING"

    def test_intake_phq9_out_of_range_rejected(self):
        """PRD section 3.3: "the two instrument totals `phq9_score` (an
        integer between 0 and 27 inclusive) and `gad7_score` (between 0 and 21
        inclusive — out-of-range scores are rejected with
        `ERR_INVALID_REQUEST`)".

        Design: Corner/entities/intake_phq9_out_of_range_rejected
        """
        counselor = create_counselor(license_id="LIC-E5",
                                     specialties=["TRIAGE"], weekly_capacity=10,
                                     max_risk_points=500)
        student = create_student("E500", "Range Stud")
        resp = api_client.create_intake_assessment(
            {
                "student_id": student["id"],
                "screener_id": counselor["id"],
                "phq9_score": 28,
                "gad7_score": 5,
                "ideation_flag": False,
                "recent_attempt_flag": False,
            },
            make_triage_screener_headers(counselor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestRiskScoringVariants:

    def test_screening_variant_attempt_multiplier_skips_ideation_bonus(self):
        """PRD section 3.3: "If the student reports a recent attempt, that
        base is tripled. Otherwise — only when no recent attempt is reported —
        an endorsed ideation flag adds fifteen points to the base."

        With phq9=10, gad7=8 and both flags set the screening variant computes
        (10+8)*3 = 54 -> HIGH; the ideation bonus is skipped by the
        otherwise-branch.

        Design: Difficulty/dual_variant_calc/risk_score_screening_vs_audit_variant_divergence
        """
        counselor = create_counselor(license_id="LIC-1",
                                     specialties=["TRIAGE"], weekly_capacity=10,
                                     max_risk_points=500)
        student = create_student("S100", "Case One")
        resp = api_client.create_intake_assessment(
            {
                "student_id": student["id"],
                "screener_id": counselor["id"],
                "phq9_score": 10,
                "gad7_score": 8,
                "ideation_flag": True,
                "recent_attempt_flag": True,
            },
            make_triage_screener_headers(counselor["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["risk_points"] == 54, \
            f"screening variant must yield (10+8)*3 = 54, got {data['risk_points']}"
        assert data["risk_band"] == "HIGH", \
            f"54 points must band HIGH (35 <= 54 < 60), got {data['risk_band']}"

    def test_persisted_record_never_reflects_audit_variant(self):
        """PRD section 3.9: "the audit variant is used only for this what-if
        reporting and is never persisted."
        PRD section 3.3: "Risk scoring happens at creation and is immutable
        thereafter."

        The audit variant would compute (10+8+15)*3 = 99 -> CRITICAL for the
        same inputs; the stored record must show the screening variant's 54 /
        HIGH on every subsequent read.

        Design: Difficulty/dual_variant_calc/risk_score_screening_vs_audit_variant_divergence
        """
        counselor = create_counselor(license_id="LIC-1",
                                     specialties=["TRIAGE"], weekly_capacity=10,
                                     max_risk_points=500)
        student = create_student("S100", "Case One")
        created = create_intake(student["id"], counselor["id"],
                                phq9=10, gad7=8, ideation=True, attempt=True)
        assert created["risk_points"] != 99, \
            "audit-variant points (99) must never be persisted"
        assert created["risk_band"] != "CRITICAL"
        # Re-read via GET and via the list endpoint: the value is immutable.
        reread = validate_success(api_client.get_intake_assessment(
            created["id"], make_triage_screener_headers(counselor["id"])))
        assert reread["risk_points"] == 54
        assert reread["risk_band"] == "HIGH"
        listed, _meta = validate_paginated(api_client.list_intake_assessments(
            make_triage_screener_headers(counselor["id"]),
            params={"student_id": student["id"]}))
        assert listed[0]["risk_points"] == 54
        assert listed[0]["risk_band"] == "HIGH"


class TestRiskBandBoundary:

    def test_risk_points_59_bands_high(self):
        """PRD section 3.3: "Banding compares the post-cap points against
        inclusive lower edges: at least sixty points is `CRITICAL`; at least
        thirty-five (but fewer than sixty) is `HIGH`; at least fifteen (but
        fewer than thirty-five) is `MODERATE`; anything lower is `LOW`."

        27+17 = 44 base plus the 15-point ideation bonus lands exactly 59,
        one below the CRITICAL edge.

        Design: Difficulty/boundary_precision_check/risk_band_critical_min_inclusive_edge
        """
        counselor = create_counselor(license_id="LIC-11",
                                     specialties=["TRIAGE"], weekly_capacity=10,
                                     max_risk_points=1000)
        student = create_student("S1159", "Edge59")
        data = create_intake(student["id"], counselor["id"],
                             phq9=27, gad7=17, ideation=True, attempt=False)
        assert data["risk_points"] == 59, \
            f"44 base + 15 ideation must be 59, got {data['risk_points']}"
        assert data["risk_band"] == "HIGH", \
            f"59 is below the inclusive CRITICAL edge, got {data['risk_band']}"

    def test_risk_points_60_bands_critical(self):
        """PRD section 3.3: "Banding compares the post-cap points against
        inclusive lower edges: at least sixty points is `CRITICAL`; at least
        thirty-five (but fewer than sixty) is `HIGH`; at least fifteen (but
        fewer than thirty-five) is `MODERATE`; anything lower is `LOW`."

        (15+5) tripled by the recent-attempt multiplier lands exactly on 60,
        the inclusive CRITICAL edge.

        Design: Difficulty/boundary_precision_check/risk_band_critical_min_inclusive_edge
        """
        counselor = create_counselor(license_id="LIC-11",
                                     specialties=["TRIAGE"], weekly_capacity=10,
                                     max_risk_points=1000)
        student = create_student("S1160", "Edge60")
        data = create_intake(student["id"], counselor["id"],
                             phq9=15, gad7=5, ideation=False, attempt=True)
        assert data["risk_points"] == 60, \
            f"(15+5)*3 must be 60, got {data['risk_points']}"
        assert data["risk_band"] == "CRITICAL", \
            f"60 meets the inclusive CRITICAL edge, got {data['risk_band']}"
