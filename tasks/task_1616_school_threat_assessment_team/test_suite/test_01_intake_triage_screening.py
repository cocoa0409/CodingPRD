"""Report intake, school configuration, triage, and the initial screening."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_threat_case,
    create_case,
    create_case_payload,
    create_school,
    create_school_payload,
    get_case,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_threat_assessor_headers,
    screening_payload,
    triage_payload,
    triage_case,
    validate_error,
    validate_paginated,
    validate_success,
)

TA1 = make_threat_assessor_headers("ta_1")
TEST_USERS_IC = TEST_USERS["intake_coordinator_headers"]
TEST_USERS_TL = TEST_USERS["team_lead_headers"]
TEST_USERS_DA = TEST_USERS["district_admin_headers"]


class TestSchoolConfiguration:
    def test_school_creation_applies_retention_days_default(self, api):
        """PRD: "When `retention_days` is omitted it defaults to 365; a
        supplied value shorter than 30 days is invalid."

        Design: Corner/entities/school_creation_applies_retention_days_default
        """
        school = validate_success(
            api.create_school(create_school_payload(
                name="Default ES", school_code="DEF", enrollment_count=300),
                TEST_USERS_DA),
            201,
        )
        assert school["retention_days"] == 365, (
            f"omitted retention_days must default to 365, got {school['retention_days']}"
        )

    def test_school_duplicate_code_rejected(self, api):
        """PRD: "The `school_code` is unique across the district and
        case-sensitive: a second school carrying a code byte-identical to an
        existing one is rejected with `ERR_DUPLICATE_SCHOOL_CODE`."

        Design: Corner/entities/school_duplicate_code_rejected
        """
        create_school(name="First", school_code="DUP", enrollment_count=100)
        resp = api.create_school(
            create_school_payload(name="Second", school_code="DUP",
                                  enrollment_count=200),
            TEST_USERS_DA,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SCHOOL_CODE)


class TestCaseIntake:
    def test_create_case_returns_intake_initial_state(self, api):
        """PRD: "The new case opens in `INTAKE` status, and the system writes a
        `CASE_CREATED` audit event."
        PRD: "The case's `screening_score` is the count of factors that are
        true, an integer from zero to six, and the `screening_outcome` is
        `SUBSTANTIVE` when the score is at least three and `NON_SUBSTANTIVE`
        otherwise; both fields are null until a screening is recorded."
        PRD: "It stamps `finalized_at`, copies the assessment's `risk_level`
        onto the case (where `risk_level` was null until the first
        finalization), increments the case's `version` by one, and writes
        `ASSESSMENT_FINALIZED`."

        Design: Corner/entities/create_case_returns_initial_state_and_system_fields
        """
        school = create_school(name="Init HS", school_code="INI")
        case = validate_success(
            api.create_case(
                create_case_payload(school["id"], subject_alias="STU-INI",
                                    summary="initial state check"),
                TEST_USERS_IC),
            201,
        )
        assert_threat_case(case)
        assert case["status"] == "INTAKE"
        assert case["triage_priority"] is None
        assert case["screening_score"] is None
        assert case["screening_outcome"] is None
        assert case["risk_level"] is None
        assert case["monitoring_cadence_days"] is None
        assert case["escalation_flag"] is False
        assert case["consecutive_missed_count"] == 0
        assert case["removal_type"] is None
        assert case["closed_at"] is None
        assert case["retention_purge_after"] is None
        assert case["purged_at"] is None
        assert is_valid_uuid(case["id"])
        assert is_iso8601_timestamp(case["created_at"])
        assert isinstance(case["version"], int)

    def test_create_case_missing_school_id_rejected(self, api):
        """PRD: "Third, the request body's schema is validated — required
        fields present, types correct, enum values among their declared sets,
        and non-empty constraints on required strings and arrays such as
        `conditions`, `decline_reason`, `denial_reason`, and `summary`; any
        failure here is `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_case_missing_school_id_returns_invalid_request
        """
        resp = api.create_case(
            {"subject_alias": "STU-X", "reporter_channel": "TIP_LINE",
             "summary": "no school"},
            TEST_USERS_IC,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_case_invalid_reporter_channel_rejected(self, api):
        """PRD: "The intake call names the enrolling school via `school_id` —
        an unknown school yields `ERR_SCHOOL_NOT_FOUND` — along with the
        pseudonymous `subject_alias`, the `reporter_channel` (`TIP_LINE` or
        `STAFF_REFERRAL`), and a free-text `summary` of the reported concern."
        PRD: "Third, the request body's schema is validated — required fields
        present, types correct, enum values among their declared sets, and
        non-empty constraints on required strings and arrays such as
        `conditions`, `decline_reason`, `denial_reason`, and `summary`; any
        failure here is `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_case_invalid_reporter_channel_returns_invalid_request
        """
        school = create_school(name="Enum HS", school_code="ENU")
        resp = api.create_case(
            create_case_payload(school["id"], subject_alias="STU-E",
                                reporter_channel="PARENT_HOTLINE",
                                summary="bad enum"),
            TEST_USERS_IC,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_case_ignores_client_supplied_system_fields(self, api):
        """PRD: "The new case opens in `INTAKE` status, and the system writes a
        `CASE_CREATED` audit event."
        PRD: "The case's `screening_score` is the count of factors that are
        true, an integer from zero to six, and the `screening_outcome` is
        `SUBSTANTIVE` when the score is at least three and `NON_SUBSTANTIVE`
        otherwise; both fields are null until a screening is recorded."
        PRD: "It stamps `finalized_at`, copies the assessment's `risk_level`
        onto the case (where `risk_level` was null until the first
        finalization), increments the case's `version` by one, and writes
        `ASSESSMENT_FINALIZED`."

        Design: Corner/entities/create_case_with_computed_field_input_ignored
        """
        school = create_school(name="Ignore HS", school_code="IGN")
        payload = create_case_payload(school["id"], subject_alias="STU-IGN",
                                      summary="computed fields ignored")
        payload["screening_score"] = 6
        payload["risk_level"] = "IMMINENT"
        payload["status"] = "PLAN_ACTIVE"
        case = validate_success(api.create_case(payload, TEST_USERS_IC), 201)
        assert case["status"] == "INTAKE", (
            "client-supplied status must not override the initial state"
        )
        assert case["screening_score"] is None, (
            "screening_score is null until a screening is recorded"
        )
        assert case["risk_level"] is None, (
            "risk_level is null until the first finalization"
        )

    def test_get_case_unknown_id_returns_case_not_found(self, api):
        """PRD: "Fourth, path identifiers are resolved left to right, and the
        first identifier that does not correspond to an existing resource
        produces a 404: `ERR_CASE_NOT_FOUND` when the missing resource is a
        threat case (whether referenced in the path or through a body
        `case_id`), `ERR_SCHOOL_NOT_FOUND` when a body `school_id` references
        a school that does not exist, `ERR_CONDITION_NOT_FOUND` when a
        `conditionIndex` path segment falls outside the referenced plan's
        `conditions` array, and `ERR_NOT_FOUND` for any other missing path
        resource."

        Design: Corner/entities/get_case_with_unknown_id_returns_case_not_found
        """
        resp = api.get_case(NON_EXISTENT_UUID, TEST_USERS_TL)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND)


class TestTriage:
    def test_triage_emergent_autocreates_urgent_le_referral(self, api):
        """PRD: "An `EMERGENT` triage additionally fires an automatic cascade:
        the system creates a law-enforcement referral to the agency named
        `DISTRICT_SRT` at `URGENT` urgency, already in `SENT` status with
        `auto_created` set to true and its deadline computed at creation, and
        records `REFERRAL_AUTO_CREATED` in the audit trail."
        PRD: "Its response deadline `sla_due_at` is computed at the send
        instant — 72 hours later for an `URGENT` referral, 240 hours later for
        a `ROUTINE` one."

        Design: Corner/state_machines/triage_emergent_autocreates_urgent_le_referral
        """
        from datetime import datetime, timedelta

        school = create_school(name="Emerg HS", school_code="EMG")
        case_a = create_case(school["id"], subject_alias="STU-EM1",
                             summary="emergent")
        case_b = create_case(school["id"], subject_alias="STU-EM2",
                             summary="routine")

        triaged_a = triage_case(case_a["id"], priority="EMERGENT",
                                notes="credible and imminent")
        assert triaged_a["status"] == "TRIAGED"
        assert triaged_a["triage_priority"] == "EMERGENT"

        referrals, meta = validate_paginated(api.list_case_referrals(
            case_a["id"], TEST_USERS_TL, params={"referral_type": "LAW_ENFORCEMENT"}))
        assert meta["total_count"] == 1
        auto_ref = referrals[0]
        assert auto_ref["auto_created"] is True
        assert auto_ref["urgency"] == "URGENT"
        assert auto_ref["status"] == "SENT"
        assert auto_ref["agency_name"] == "DISTRICT_SRT"
        sent_at = datetime.fromisoformat(auto_ref["created_at"].replace("Z", "+00:00"))
        sla_due = datetime.fromisoformat(auto_ref["sla_due_at"].replace("Z", "+00:00"))
        assert sla_due == sent_at + timedelta(hours=72), (
            f"sla_due_at must be the send instant plus 72 hours: "
            f"{auto_ref['created_at']} -> {auto_ref['sla_due_at']}"
        )
        events, events_meta = validate_paginated(api.list_case_audit_events(
            case_a["id"], TEST_USERS_TL, params={"action": "REFERRAL_AUTO_CREATED"}))
        assert events_meta["total_count"] == 1
        assert events[0]["action"] == "REFERRAL_AUTO_CREATED"

        triage_case(case_b["id"], priority="ROUTINE", notes="standard")
        _refs_b, meta_b = validate_paginated(api.list_case_referrals(
            case_b["id"], TEST_USERS_TL))
        assert meta_b["total_count"] == 0, (
            "ROUTINE triage must not auto-create any referral"
        )

    def test_triage_twice_returns_not_in_intake(self, api):
        """PRD: "It is valid only while the case is in `INTAKE`; any other
        state draws `ERR_CASE_NOT_IN_INTAKE`."

        Design: Corner/state_machines/triage_twice_returns_not_in_intake
        """
        school = create_school(name="Twice HS", school_code="TWC")
        case = create_case(school["id"], subject_alias="STU-T",
                           summary="triage twice")
        triage_case(case["id"], priority="ROUTINE", notes="first")

        resp = api.triage_case(case["id"],
                               triage_payload(triage_priority="URGENT",
                                              triage_notes="second"),
                               TEST_USERS_IC)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_IN_INTAKE)
        after = get_case(case["id"])
        assert after["status"] == "TRIAGED"
        assert after["triage_priority"] == "ROUTINE", (
            "a rejected second triage must not move the recorded priority"
        )


class TestScreening:
    def test_screening_score_three_is_substantive(self, api):
        """PRD: "The case's `screening_score` is the count of factors that are
        true, an integer from zero to six, and the `screening_outcome` is
        `SUBSTANTIVE` when the score is at least three and `NON_SUBSTANTIVE`
        otherwise; both fields are null until a screening is recorded."
        PRD: "A `SUBSTANTIVE` screening moves the case from `TRIAGED` to
        `UNDER_ASSESSMENT`, opening the full assessment workflow."

        Design: Difficulty/boundary_precision_check/screening_score_exactly_three_substantive
        """
        school = create_school(name="Boundary ES", school_code="BES",
                               enrollment_count=400)
        case = create_case(school["id"], subject_alias="STU-B1",
                           summary="boundary 3")
        triage_case(case["id"])

        screened = validate_success(
            api.record_screening(case["id"], screening_payload(3), TA1), 200)
        assert screened["screening_score"] == 3
        assert screened["screening_outcome"] == "SUBSTANTIVE", (
            "a score of exactly three meets the at-least-three threshold"
        )
        assert screened["status"] == "UNDER_ASSESSMENT"
        assert screened["closed_at"] is None

    def test_screening_score_two_closes_no_threat(self, api):
        """PRD: "The case's `screening_score` is the count of factors that are
        true, an integer from zero to six, and the `screening_outcome` is
        `SUBSTANTIVE` when the score is at least three and `NON_SUBSTANTIVE`
        otherwise; both fields are null until a screening is recorded."
        PRD: "A `NON_SUBSTANTIVE` screening moves the case from `TRIAGED` to
        `CLOSED_NO_THREAT`, stamps `closed_at` with the current logical time,
        and computes `retention_purge_after` as the closure calendar date plus
        the school's `retention_days`."

        Design: Difficulty/boundary_precision_check/screening_score_exactly_three_substantive
        """
        school = create_school(name="Boundary ES 2", school_code="BES2",
                               enrollment_count=400)
        case = create_case(school["id"], subject_alias="STU-B2",
                           summary="boundary 2")
        triage_case(case["id"])

        screened = validate_success(
            api.record_screening(case["id"], screening_payload(2), TA1), 200)
        assert screened["screening_score"] == 2
        assert screened["screening_outcome"] == "NON_SUBSTANTIVE", (
            "a score of two falls below the at-least-three threshold"
        )
        assert screened["status"] == "CLOSED_NO_THREAT"
        assert screened["closed_at"] is not None
        assert screened["retention_purge_after"] == "2027-08-01", (
            "closure on 2026-08-01 plus the 365-day default retention window"
        )

    def test_screening_on_intake_case_returns_not_triaged(self, api):
        """PRD: "Once a case is `TRIAGED`, a `ThreatAssessor` records the
        structured initial screening; attempting it in any other case state is
        rejected with `ERR_CASE_NOT_TRIAGED`."

        Design: Corner/state_machines/screening_on_intake_case_returns_not_triaged
        """
        school = create_school(name="Seq HS", school_code="SEQ")
        case = create_case(school["id"], subject_alias="STU-SEQ",
                           summary="skip triage")
        resp = api.record_screening(case["id"], screening_payload(3), TA1)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_TRIAGED)
        after = get_case(case["id"])
        assert after["status"] == "INTAKE"
        assert after["screening_score"] is None
