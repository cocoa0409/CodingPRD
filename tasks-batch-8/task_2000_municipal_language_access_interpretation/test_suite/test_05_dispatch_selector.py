"""Dispatch selector: eligibility, buffered overlap, ranking, empty pool."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    BUSINESS_START_ISO,
    assert_interpretation_request,
    create_assigned_request,
    create_department,
    create_interpreter,
    create_request,
    get_department,
    get_interpreter,
    make_liaison_headers,
    set_clock,
    setup_interpretation_workspace,
    sign_confidentiality_now,
    validate_error,
    validate_paginated,
    validate_success,
)

COORDINATOR = TEST_USERS["coordinator_headers"]


class TestBufferedInPersonOverlap:
    def _overlap_workspace(self):
        set_clock("2026-08-01T06:00:00Z")
        ws = setup_interpretation_workspace(
            dept_budget=1_000_000, ceiling_cents=1_000_000, tier="CERTIFIED",
            modalities=("IN_PERSON",), interpreter_name="Ina Person")
        session_a = create_assigned_request(
            ws["department"]["id"], modality="IN_PERSON",
            scheduled_start="2026-08-01T10:00:00Z", scheduled_duration_minutes=120)
        return ws, session_a

    def test_buffered_overlap_unfulfilled_then_exact_buffer_end_assigned(self, api):
        """PRD §3.6: "freedom from buffered in-person conflicts, meaning that
        when the request is `IN_PERSON`, none of the candidate's `ASSIGNED`
        in-person sessions may interleave — a conflict exists when the new
        session's start is earlier than an existing session's end plus a
        thirty-minute buffer while that existing session's start minus thirty
        minutes is earlier than the new session's end, with a session's end
        defined as its `scheduled_start` plus its `scheduled_duration_minutes`"

        Design: Difficulty/resource_temporal_overlap/in_person_buffered_overlap_excludes_sole_candidate
        """
        ws, session_a = self._overlap_workspace()
        interpreter_id = ws["interpreter"]["id"]
        assert session_a["interpreter_id"] == interpreter_id
        assert session_a["estimated_cost_cents"] == 16300, (
            "120 in-person minutes x 100c x 1.15 + 2500c travel"
        )

        # Existing session occupies [10:00, 12:00); buffered window is
        # [09:30, 12:30). A 12:15 start interleaves; a 12:30 start does not.
        overlapping = create_request(
            ws["department"]["id"], modality="IN_PERSON",
            scheduled_start="2026-08-01T12:15:00Z", scheduled_duration_minutes=45)
        assert overlapping["status"] == "UNFULFILLED"
        assert overlapping["interpreter_id"] is None
        assert overlapping["estimated_cost_cents"] is None

        at_buffer_end = create_request(
            ws["department"]["id"], modality="IN_PERSON",
            scheduled_start="2026-08-01T12:30:00Z", scheduled_duration_minutes=45)
        assert at_buffer_end["status"] == "ASSIGNED", (
            "12:30 equals the buffer end; the strict-inequality rule admits it"
        )
        assert at_buffer_end["interpreter_id"] == interpreter_id

    def test_unfulfilled_request_costs_compliance_points(self, api):
        """PRD §3.6: "When the pool is empty the request is instead born
        `UNFULFILLED` — still a successful creation, returning the new record
        with `interpreter_id` and `estimated_cost_cents` null — and a 50-point
        compliance event is recorded against the department, timed at the
        request's `created_at`."

        Design: Difficulty/resource_temporal_overlap/in_person_buffered_overlap_excludes_sole_candidate
        """
        ws, session_a = self._overlap_workspace()
        create_request(ws["department"]["id"], modality="IN_PERSON",
                       scheduled_start="2026-08-01T12:15:00Z",
                       scheduled_duration_minutes=45)
        dept = get_department(ws["department"]["id"])
        assert dept["compliance_score"] == 950, (
            "exactly one -50 unfulfilled-service event (the 12:15 request)"
        )


class TestDispatchRanking:
    def test_dispatch_tie_break_earliest_created_at(self, api):
        """PRD §3.6: "Eligible candidates are ranked by `minutes_current_month`
        ascending, then `created_at` ascending, then `full_name` ascending, and
        the first-ranked candidate is selected."

        Design: Corner/complexity_layers/dispatch_tie_break_earliest_created_at
        """
        dept = create_department(name="Dept Tie", service_area_code="SA-C40")
        ws = setup_interpretation_workspace(
            dept_budget=1_000_000, ceiling_cents=500000, tier="REGISTERED",
            interpreter_name="Zed First")
        first = ws["interpreter"]
        set_clock("2026-08-01T00:01:00Z")
        second = create_interpreter(
            ws["contract"]["id"], full_name="Aaron Second", tier="REGISTERED")
        # Both candidates have zero minutes banked; the earlier-created one
        # must win the tie-break regardless of name order.
        request = create_assigned_request(
            dept["id"], modality="PHONE", scheduled_duration_minutes=30,
            scheduled_start=BUSINESS_START_ISO)
        assert request["interpreter_id"] == first["id"], (
            f"earliest created_at must beat {second['full_name']!r}"
        )
        assert request["estimated_cost_cents"] == 1500, (
            "30 phone minutes x 50c with a REGISTERED 1.0 multiplier"
        )


class TestEmptyPoolFallback:
    def test_dispatch_empty_pool_unfulfilled_with_penalty(
            self, api, coordinator_headers):
        """PRD §3.6: "When the pool is empty the request is instead born
        `UNFULFILLED` — still a successful creation, returning the new record
        with `interpreter_id` and `estimated_cost_cents` null — and a 50-point
        compliance event is recorded against the department, timed at the
        request's `created_at`."
        PRD §3.1: "The final score then derives `posture`: at least 800 is
        `GOOD_STANDING`, 600 through 799 is `WATCH`, and below 600 is
        `NONCOMPLIANT`."

        Design: Corner/complexity_layers/dispatch_empty_pool_unfulfilled_with_penalty
        """
        dept = create_department(name="Dept Empty", service_area_code="SA-C41",
                                 annual_budget_cents=100000)
        resp = api.create_interpretation_request(
            {"department_id": dept["id"], "language_code": "fr",
             "modality": "PHONE", "encounter_setting": "GENERAL",
             "scheduled_duration_minutes": 30},
            make_liaison_headers(dept["id"]),
        )
        request = validate_success(resp, 201)
        assert_interpretation_request(request)
        assert request["status"] == "UNFULFILLED"
        assert request["interpreter_id"] is None
        assert request["estimated_cost_cents"] is None
        dept_after = get_department(dept["id"])
        assert dept_after["compliance_score"] == 950
        assert dept_after["posture"] == "GOOD_STANDING"


class TestConfidentialityEligibility:
    def test_confidentiality_expired_excluded_then_resign_restores(self, api):
        """PRD §3.6: "The eligible pool contains every interpreter who meets all
        of the following: `ACTIVE` status; a confidentiality signature stamped
        no earlier than 365 days before the current logical time; coverage of
        the requested language; service of the requested modality"
        PRD §3.5: "passing `confidentiality_signed` as true stamps
        `confidentiality_signed_at` with the current logical time, and true is
        the only accepted value (anything else is `ERR_VALIDATION`). A signature
        remains current for 365 days from its timestamp."

        Design: Corner/complexity_layers/confidentiality_expired_excluded_then_resign_restores
        """
        set_clock("2025-01-01T00:00:00Z")
        ws = setup_interpretation_workspace(
            dept_budget=1_000_000, ceiling_cents=500000, tier="CERTIFIED",
            interpreter_name="TTL Tessa")
        dept_id = ws["department"]["id"]
        interpreter_id = ws["interpreter"]["id"]
        # Signed 2025-01-01; at 2026-08-01 the signature is over 365 days old.
        set_clock("2026-08-01T00:00:00Z")

        stale = create_request(dept_id, modality="PHONE",
                               scheduled_duration_minutes=30,
                               scheduled_start=None)
        assert stale["status"] == "UNFULFILLED", (
            "a stale signature excludes the sole candidate from the pool"
        )

        sign_confidentiality_now(interpreter_id)
        restored = create_request(dept_id, modality="PHONE",
                                  scheduled_duration_minutes=30,
                                  scheduled_start=None)
        assert restored["status"] == "ASSIGNED"
        assert restored["interpreter_id"] == interpreter_id
        assert get_department(dept_id)["compliance_score"] == 950, (
            "exactly one unfulfilled event was recorded"
        )


class TestCourtTierEligibility:
    def test_court_setting_requires_certified_pool(self, api):
        """PRD §3.6: "the tier rule — `CERTIFIED` for `COURT` or `MEDICAL`
        settings, any tier for `GENERAL`"

        Design: Corner/complexity_layers/court_setting_requires_certified_pool
        """
        ws = setup_interpretation_workspace(
            dept_budget=1_000_000, ceiling_cents=500000, tier="REGISTERED",
            modalities=("IN_PERSON",), interpreter_name="Reg Court")
        request = create_request(
            ws["department"]["id"], modality="IN_PERSON",
            encounter_setting="COURT", scheduled_start="2026-08-02T10:00:00Z",
            scheduled_duration_minutes=60)
        assert request["status"] == "UNFULFILLED", (
            "a REGISTERED-only pool cannot serve a COURT request"
        )
        interpreter = get_interpreter(ws["interpreter"]["id"])
        assert interpreter["status"] == "ACTIVE"
        assert interpreter["minutes_current_month"] == 0


class TestValidationOrderingSafetyBeforeTemporal:
    def test_court_setting_error_wins_over_past_schedule(self, api):
        """PRD §2.10: "Incoming writes are checked against an ordered cascade,
        and an earlier failure masks every later check."
        PRD §2.10: "Compliance and safety gates, in this order." including "a
        `COURT` setting must be in person (`ERR_SETTING_REQUIRES_IN_PERSON`)"
        PRD §2.10: "A `scheduled_start` in the past is `ERR_SCHEDULE_IN_PAST`"

        Design: Difficulty/priority_pair_validation_conflict/request_create_setting_safety_beats_schedule_temporal
        """
        dept = create_department(name="Dept Courts", service_area_code="SA-9")
        # Both violations hold: COURT with PHONE, and a past scheduled_start.
        resp = api.create_interpretation_request(
            {"department_id": dept["id"], "language_code": "es",
             "modality": "PHONE", "encounter_setting": "COURT",
             "scheduled_start": "2026-07-01T10:00:00Z",
             "scheduled_duration_minutes": 30},
            make_liaison_headers(dept["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SETTING_REQUIRES_IN_PERSON.value)

    def test_rejected_request_not_persisted(self, api, coordinator_headers):
        """PRD §3.6: "Court work must be face to face: a `COURT` setting paired
        with any modality other than `IN_PERSON` is rejected with
        `ERR_SETTING_REQUIRES_IN_PERSON`."

        Design: Difficulty/priority_pair_validation_conflict/request_create_setting_safety_beats_schedule_temporal
        """
        dept = create_department(name="Dept Courts", service_area_code="SA-9")
        resp = api.create_interpretation_request(
            {"department_id": dept["id"], "language_code": "es",
             "modality": "PHONE", "encounter_setting": "COURT",
             "scheduled_start": "2026-07-01T10:00:00Z",
             "scheduled_duration_minutes": 30},
            make_liaison_headers(dept["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SETTING_REQUIRES_IN_PERSON.value)
        _, meta = validate_paginated(api.list_interpretation_requests(
            coordinator_headers, params={"department_id": dept["id"]}))
        assert meta["total_count"] == 0


class TestTemporalRules:
    def test_schedule_in_past_rejected(self, api, coordinator_headers):
        """PRD §3.6: "No session may begin in the past relative to the logical
        clock (`ERR_SCHEDULE_IN_PAST`), and an in-person session needs at least
        two hours of lead time (`ERR_LEAD_TIME_INSUFFICIENT`)."

        Design: Corner/validations/schedule_in_past_rejected
        """
        dept = create_department(name="Dept Past", service_area_code="SA-C18",
                                 annual_budget_cents=100000)
        # Startup logical clock is 2026-08-01T00:00:00Z (PRD §2.5).
        resp = api.create_interpretation_request(
            {"department_id": dept["id"], "language_code": "es",
             "modality": "PHONE", "encounter_setting": "GENERAL",
             "scheduled_start": "2026-07-31T23:00:00Z",
             "scheduled_duration_minutes": 30},
            make_liaison_headers(dept["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_IN_PAST.value)
        _, meta = validate_paginated(api.list_interpretation_requests(
            coordinator_headers, params={"department_id": dept["id"]}))
        assert meta["total_count"] == 0

    def test_in_person_lead_time_rejected(self, api, coordinator_headers):
        """PRD §3.6: "No session may begin in the past relative to the logical
        clock (`ERR_SCHEDULE_IN_PAST`), and an in-person session needs at least
        two hours of lead time (`ERR_LEAD_TIME_INSUFFICIENT`)."

        Design: Corner/validations/in_person_lead_time_rejected
        """
        set_clock("2026-08-01T06:00:00Z")
        dept = create_department(name="Dept Lead", service_area_code="SA-C19",
                                 annual_budget_cents=100000)
        resp = api.create_interpretation_request(
            {"department_id": dept["id"], "language_code": "es",
             "modality": "IN_PERSON", "encounter_setting": "GENERAL",
             "scheduled_start": "2026-08-01T06:45:00Z",
             "scheduled_duration_minutes": 60},
            make_liaison_headers(dept["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LEAD_TIME_INSUFFICIENT.value)
        _, meta = validate_paginated(api.list_interpretation_requests(
            coordinator_headers, params={"department_id": dept["id"]}))
        assert meta["total_count"] == 0


class TestRequestShape:
    def test_create_request_invalid_enum_modality_returns_invalid_request(
            self, api):
        """PRD §2.10: "Required fields are present, types match, enum values are
        valid, and numeric ranges hold (counts at least zero; populations,
        encounter totals, word counts, and minute declarations strictly positive;
        `period_start` earlier than `period_end`); computed or system fields
        supplied as input are refused — all as `ERR_VALIDATION`."
        PRD §3.6: "the `modality` (`PHONE`, `VIDEO`, or `IN_PERSON`)"

        Design: Corner/entities/create_request_invalid_enum_modality_returns_invalid_request
        """
        dept = create_department(name="Dept Enum", service_area_code="SA-C4",
                                 annual_budget_cents=100000)
        resp = api.create_interpretation_request(
            {"department_id": dept["id"], "language_code": "es",
             "modality": "SMOKE_SIGNAL", "encounter_setting": "GENERAL",
             "scheduled_duration_minutes": 30},
            make_liaison_headers(dept["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
