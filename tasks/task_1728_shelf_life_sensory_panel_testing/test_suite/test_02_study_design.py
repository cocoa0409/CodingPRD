"""Study design rules: creation defaults, ACCELERATED well-formedness, arm and
time-point structure gates, role denials, OCC-guarded update, clock default."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_arm,
    add_time_point,
    assert_study,
    create_client,
    create_draft_study,
    create_panelist_payload,
    get_study,
    get_success_data,
    make_client_headers,
    make_panelist_headers,
    update_study_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

LD = TEST_USERS["lab_director_headers"]
SCI = TEST_USERS["scientist_headers"]
PC = TEST_USERS["coordinator_headers"]
AN = TEST_USERS["analyst_headers"]
QA = TEST_USERS["qa_headers"]


class TestStudyCreation:
    def test_study_creation_system_owned_fields(self, api):
        """PRD §3.2: "A new study is born in `DRAFT` with `reserved_hours_escrow` at zero, `consumed_hours` at zero, `earliest_failure_day_equiv` null — nothing has tripped yet — and `actual_start_utc` null until activation."
        PRD §3.2: "Two fields carry defaults: `reference_temp_c`, the ambient control temperature used by Q10 projection, defaults to 20; and `q10_factor` defaults to 2.0."

        Design: Corner/entities/study_creation_system_owned_fields
        """
        client = create_client()
        study = validate_success(api.create_study(
            {"client_id": client["id"], "product_name": "Wraps",
             "study_type": "REAL_TIME", "storage_temp_c": 4,
             "target_shelf_life_days": 21, "sensory_fail_threshold": 5.5,
             "min_detectable_difference": 2.5,
             "planned_start_utc": "2026-08-01T00:00:00Z"}, SCI), 201)
        assert_study(study)
        assert study["status"] == "DRAFT"
        assert study["actual_start_utc"] is None
        assert study["reserved_hours_escrow"] == 0
        assert study["consumed_hours"] == 0
        assert study["earliest_failure_day_equiv"] is None
        assert study["reference_temp_c"] == 20, "reference_temp_c defaults to 20"
        assert study["q10_factor"] == 2.0, "q10_factor defaults to 2.0"

    def test_accelerated_study_requires_q10_and_elevated_temp(self, api):
        """PRD §3.2: "An `ACCELERATED` study is only well-formed when its `q10_factor` is strictly greater than 1.0 and its `storage_temp_c` exceeds its `reference_temp_c`; otherwise creation fails with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/accelerated_study_requires_q10_and_elevated_temp
        """
        client = create_client()
        base = {"client_id": client["id"], "study_type": "ACCELERATED",
                "reference_temp_c": 20, "target_shelf_life_days": 30,
                "sensory_fail_threshold": 6.0, "min_detectable_difference": 3.0,
                "planned_start_utc": "2026-08-01T00:00:00Z"}
        # q10_factor not strictly greater than 1.0
        resp1 = api.create_study(
            {**base, "product_name": "Bad A", "storage_temp_c": 40,
             "q10_factor": 0.5}, SCI)
        validate_error(resp1, ApiErrorId.ERR_INVALID_REQUEST, 400)
        # storage_temp_c does not exceed reference_temp_c
        resp2 = api.create_study(
            {**base, "product_name": "Bad B", "storage_temp_c": 15,
             "q10_factor": 2.0}, SCI)
        validate_error(resp2, ApiErrorId.ERR_INVALID_REQUEST, 400)

        _rows, meta = validate_paginated(api.list_studies(SCI))
        assert meta["total_count"] == 0, "rejected creations must persist nothing"


class TestStudyStructure:
    def test_control_arm_and_variant_uniqueness(self, api):
        """PRD §3.2: "the same variant may not appear twice within one study (`ERR_DUPLICATE_ARM_VARIANT`); and at most one arm per study may be flagged as the control — a second control arm is rejected with `ERR_CONTROL_ARM_EXISTS`."

        Design: Corner/validations/control_arm_and_variant_uniqueness
        """
        client = create_client()
        study = create_draft_study(client["id"])
        add_arm(study["id"], "STANDARD_FILM", is_control=True)

        resp1 = api.create_study_arm(
            {"study_id": study["id"], "packaging_variant": "MAP",
             "is_control": True}, SCI)
        validate_error(resp1, ApiErrorId.ERR_CONTROL_ARM_EXISTS, 409)

        resp2 = api.create_study_arm(
            {"study_id": study["id"], "packaging_variant": "STANDARD_FILM",
             "is_control": False}, SCI)
        validate_error(resp2, ApiErrorId.ERR_DUPLICATE_ARM_VARIANT, 409)

        _rows, meta = validate_paginated(
            api.list_study_arms(SCI, params={"study_id": study["id"]}))
        assert meta["total_count"] == 1, "study still has exactly one arm"

    def test_duplicate_time_point_day_rejected(self, api):
        """PRD §3.2: "**Sampling time points** are added with a `day_index` — the study day of the pull, zero or greater — unique within the study (else `ERR_DUPLICATE_TIME_POINT_DAY`)."

        Design: Corner/validations/duplicate_time_point_day_rejected
        """
        client = create_client()
        study_a = create_draft_study(client["id"], product_name="A")
        add_time_point(study_a["id"], 0)
        study_b = create_draft_study(client["id"], product_name="B")

        resp = api.create_time_point(
            {"study_id": study_a["id"], "day_index": 0}, SCI)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_TIME_POINT_DAY, 409)

        ok = validate_success(api.create_time_point(
            {"study_id": study_b["id"], "day_index": 0}, SCI), 201)
        assert ok["study_id"] == study_b["id"], "uniqueness is per-study"

    def test_submit_design_structure_gates(self, api):
        """PRD §3.2: "Submission enforces its four checks in order: the study must currently be `DRAFT` (else `ERR_INVALID_STUDY_STATE`); at least one arm must exist (else `ERR_NO_ARMS_DEFINED`); exactly one arm must be flagged `is_control` (else `ERR_NO_CONTROL_ARM`); and at least one sampling time point must exist (else `ERR_NO_TIME_POINTS`)."

        Design: Corner/validations/submit_design_structure_gates
        """
        client = create_client()
        study = create_draft_study(client["id"])

        validate_error(api.submit_design(study["id"], SCI),
                       ApiErrorId.ERR_NO_ARMS_DEFINED, 409)

        add_arm(study["id"], "MAP", is_control=False)
        validate_error(api.submit_design(study["id"], SCI),
                       ApiErrorId.ERR_NO_CONTROL_ARM, 409)

        add_arm(study["id"], "STANDARD_FILM", is_control=True)
        validate_error(api.submit_design(study["id"], SCI),
                       ApiErrorId.ERR_NO_TIME_POINTS, 409)

        add_time_point(study["id"], 0)
        submitted = validate_success(api.submit_design(study["id"], SCI))
        assert submitted["status"] == "DESIGN_REVIEW"


class TestRoleMatrix:
    def test_role_matrix_exclusive_denials(self, api):
        """PRD §2.1: "Access to specific operations is restricted by role as enumerated in §4; an authenticated user attempting an operation outside their role, or violating an entity-backed ownership rule, is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §2.6: "Every request is validated against an ordered ladder of checks, and the first rung that fails determines the error returned."

        Design: Corner/rbac/role_matrix_exclusive_denials
        """
        client = create_client()
        study = create_draft_study(client["id"])
        panelist = get_success_data(api.create_panelist(
            create_panelist_payload(), PC))

        # SensoryScientist on the LabDirector-exclusive approve-design
        validate_error(api.approve_design(study["id"], SCI),
                       ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        # LabAnalyst on the Panelist-exclusive attribute-scores; the role gate
        # (rung 2) precedes existence (rung 3), so a bogus assignment id still 403s
        validate_error(api.create_score(
            {"assignment_id": "11111111-2222-4333-8444-555555555555",
             "attribute": "OVERALL", "score": 5}, AN),
            ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        # QAOfficer on the PanelCoordinator-exclusive panelist registration
        validate_error(api.create_panelist(
            {"full_name": "Sneaky", "email": "sneaky@lab.example.com",
             "qualified_attributes": ["OVERALL"]}, QA),
            ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        # Panelist on the LabAnalyst-exclusive lab-test-results
        validate_error(api.create_lab_result(
            {"study_id": study["id"],
             "arm_id": "11111111-2222-4333-8444-555555555555",
             "time_point_id": "11111111-2222-4333-8444-555555555555",
             "test_type": "PH", "measured_value": 4.0},
            make_panelist_headers(panelist["id"])),
            ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        # Client on the LabDirector-exclusive chamber registration
        validate_error(api.create_chamber(
            {"chamber_code": "CH-X", "temp_c": 20, "capacity_units": 5},
            make_client_headers(client["id"])),
            ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


class TestOptimisticConcurrency:
    def test_occ_stale_version_on_study_update(self, api):
        """PRD §2.7: "Because every mutation of the study — any field update, any transition, any cascade that touches the study — advances `Study.version` by 1, an `expected_study_version` that no longer matches the study's current `version` means the client's design view is stale, and the update is rejected with `ERR_STALE_STUDY_VERSION` (HTTP 412)."
        PRD §3.2: "While a study remains in `DRAFT`, the scientist may revise its design fields"

        Design: Corner/cross_cutting_layers/occ_stale_version_on_study_update
        """
        client = create_client()
        study = create_draft_study(client["id"])
        observed_version = study["version"]

        updated = validate_success(api.update_study(
            study["id"],
            update_study_payload(observed_version, product_name="Teriyaki v2"),
            SCI))
        assert updated["version"] == observed_version + 1, (
            "a successful update increments Study.version by exactly 1")
        assert updated["product_name"] == "Teriyaki v2"

        resp = api.update_study(
            study["id"],
            update_study_payload(observed_version, product_name="Teriyaki v3"),
            SCI)
        validate_error(resp, ApiErrorId.ERR_STALE_STUDY_VERSION, 412)

        current = get_study(study["id"])
        assert current["product_name"] == "Teriyaki v2", (
            "the rejected write must apply nothing")
        assert current["version"] == observed_version + 1


class TestLogicalClock:
    def test_clock_default_is_2026_08_01(self, api):
        """PRD §2.4: "Before any operator has set it, the logical clock reads exactly `2026-08-01T00:00:00Z`."
        PRD §3.2: "On success the study captures `actual_start_utc` from the logical clock"

        Design: Corner/cross_cutting_layers/clock_default_is_2026_08_01
        """
        # NOTE: no set_clock call anywhere in this chain — the default rules.
        client = create_client(topup_hours=100)
        study = create_draft_study(client["id"])
        add_arm(study["id"], "STANDARD_FILM", is_control=True)
        add_time_point(study["id"], 0)
        get_success_data(api.submit_design(study["id"], SCI))
        get_success_data(api.approve_design(study["id"], LD))

        activated = validate_success(api.activate_study(study["id"], SCI))
        assert activated["status"] == "IN_PROGRESS"
        actual = datetime.fromisoformat(
            activated["actual_start_utc"].replace("Z", "+00:00"))
        assert actual == datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc), (
            f"actual_start_utc must be the pinned default clock, got "
            f"{activated['actual_start_utc']}")
