"""Interviews (state gate, buffer overlap, conclude), evidence (seal/exclude), SoD."""
from test_helpers import (
    ApiErrorId,
    activate_assignment,
    add_conducted_interview,
    create_evidence_payload,
    create_interview_payload,
    create_triage_payload,
    make_intake_headers,
    make_investigator_headers,
    propose_assignment_auto,
    screen_clear,
    setup_case_triaged,
    setup_case_under_investigation,
    setup_standard_staff,
    create_case,
    create_staff,
    triage_case,
    validate_error,
    validate_success,
    api_client,
)


class TestInterviewCaseStateGate:
    """Difficulty: interview_gated_by_case_state (2 tests)."""

    def test_interview_on_assigned_case_rejected(self, api):
        """PRD §3.5: "the case to be `UNDER_INVESTIGATION`, otherwise
        `ERR_CASE_NOT_UNDER_INVESTIGATION`".

        Design: Difficulty/cross_entity_state_dependency/interview_gated_by_case_state
        """
        ctx = setup_case_triaged()
        staff = ctx["staff"]
        a1 = propose_assignment_auto(ctx["case"]["id"], ctx["case"]["version"], staff["h_int"])
        screen_clear(a1["id"], staff["h_int"])
        # Case is ASSIGNED (assignment CLEARED but not activated)
        resp = api.create_interview(create_interview_payload(
            ctx["case"]["id"], scheduled_start="2026-08-05T10:00:00Z",
            scheduled_end="2026-08-05T11:00:00Z",
        ), staff["h_inv"])
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_UNDER_INVESTIGATION)

    def test_interview_succeeds_after_activation(self, api):
        """PRD §3.5: "Scheduling an interview is an `Investigator` operation and
        requires ... the case to be `UNDER_INVESTIGATION`" and "A created interview
        is `SCHEDULED`, with its `investigator_id` set to the caller."

        Design: Difficulty/cross_entity_state_dependency/interview_gated_by_case_state
        """
        ctx = setup_case_under_investigation()
        staff = ctx["staff"]
        resp = api.create_interview(create_interview_payload(
            ctx["case"]["id"], scheduled_start="2026-08-05T10:00:00Z",
            scheduled_end="2026-08-05T11:00:00Z",
        ), staff["h_inv"])
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SCHEDULED"
        assert data["investigator_id"] == staff["s_inv"]["id"]


class TestInterviewBuffer:
    """Difficulty: interview_buffer_half_open_semantics (2 tests)."""

    def _setup_with_first_interview(self, api):
        ctx = setup_case_under_investigation()
        staff = ctx["staff"]
        resp = api.create_interview(create_interview_payload(
            ctx["case"]["id"], interviewee_identifier="w-1",
            scheduled_start="2026-08-05T10:00:00Z", scheduled_end="2026-08-05T11:00:00Z",
        ), staff["h_inv"])
        validate_success(resp, expected_status=201)
        return ctx

    def test_exactly_15_minute_gap_allowed(self, api):
        """PRD §3.5: "the new interval must leave a gap of at least 15 minutes to
        every other `SCHEDULED` or `CONDUCTED` interview of the same investigator".

        Design: Difficulty/resource_temporal_overlap/interview_buffer_half_open_semantics
        """
        ctx = self._setup_with_first_interview(api)
        staff = ctx["staff"]
        resp = api.create_interview(create_interview_payload(
            ctx["case"]["id"], interviewee_role="SUBJECT", interviewee_identifier="s-1",
            scheduled_start="2026-08-05T11:15:00Z", scheduled_end="2026-08-05T12:00:00Z",
        ), staff["h_inv"])
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SCHEDULED", "gap of exactly 15 minutes satisfies >= 15 rule"

    def test_14_minute_gap_rejected(self, api):
        """PRD §3.5: "a violation is rejected with `ERR_INTERVIEW_OVERLAP`".

        Design: Difficulty/resource_temporal_overlap/interview_buffer_half_open_semantics
        """
        ctx = self._setup_with_first_interview(api)
        staff = ctx["staff"]
        resp = api.create_interview(create_interview_payload(
            ctx["case"]["id"], interviewee_role="REPORTER", interviewee_identifier="r-1",
            scheduled_start="2026-08-05T11:14:00Z", scheduled_end="2026-08-05T11:45:00Z",
        ), staff["h_inv"])
        validate_error(resp, ApiErrorId.ERR_INTERVIEW_OVERLAP)


class TestInterviewValidation:
    def test_end_before_start_returns_invalid_interval(self, api):
        """PRD §3.5: "the end must be strictly later than the start or the request
        fails with `ERR_INVALID_INTERVAL`".

        Design: Corner/validations/invalid_interval_interview_end_before_start
        """
        ctx = setup_case_under_investigation()
        staff = ctx["staff"]
        resp = api.create_interview(create_interview_payload(
            ctx["case"]["id"], scheduled_start="2026-08-05T11:00:00Z",
            scheduled_end="2026-08-05T10:00:00Z",
        ), staff["h_inv"])
        validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL)

    def test_conclude_conducted_without_summary_rejected(self, api):
        """PRD §3.5: "an `outcome` of `CONDUCTED`, which requires a `summary` of at
        least 50 characters (otherwise `ERR_INVALID_REQUEST`)".

        Design: Corner/errors/conclude_conducted_without_summary_rejected
        """
        ctx = setup_case_under_investigation()
        staff = ctx["staff"]
        resp = api.create_interview(create_interview_payload(ctx["case"]["id"]), staff["h_inv"])
        iv = validate_success(resp, expected_status=201)
        resp2 = api.conclude_interview(iv["id"], {"outcome": "CONDUCTED"}, staff["h_inv"])
        validate_error(resp2, ApiErrorId.ERR_INVALID_REQUEST)

    def test_conclude_twice_returns_not_scheduled(self, api):
        """PRD §3.5: "concluding from any other state fails with
        `ERR_INTERVIEW_NOT_SCHEDULED`".

        Design: Corner/state_machines/interview_conclude_twice_returns_not_scheduled
        """
        ctx = setup_case_under_investigation()
        staff = ctx["staff"]
        conducted = add_conducted_interview(ctx)
        resp = api.conclude_interview(conducted["id"], {"outcome": "NO_SHOW"}, staff["h_inv"])
        validate_error(resp, ApiErrorId.ERR_INTERVIEW_NOT_SCHEDULED)

    def test_conducted_stamps_conducted_at(self, api):
        """PRD §3.5: "The owning investigator may conclude with an `outcome` of
        `CONDUCTED`, which requires a `summary` of at least 50 characters
        (otherwise `ERR_INVALID_REQUEST`) and stamps `conducted_at` from the
        logical clock".

        Design: Corner/state_machines/interview_conclude_twice_returns_not_scheduled
        """
        ctx = setup_case_under_investigation()
        conducted = add_conducted_interview(ctx)
        assert conducted["status"] == "CONDUCTED"
        assert conducted["conducted_at"] == "2026-08-01T00:00:00Z"


class TestNonAssignedInvestigator:
    def test_other_investigator_cannot_schedule_interview(self, api):
        """PRD §3.5: "requires the caller to be the case's `assigned_investigator_id`
        — anyone else is refused with `ERR_NOT_ASSIGNED_INVESTIGATOR`".

        Design: Corner/errors/non_assigned_investigator_cannot_interview
        """
        ctx = setup_case_under_investigation()
        other = create_staff("Ivy Other", "other@corp.example", ["INVESTIGATION"])
        resp = api.create_interview(create_interview_payload(ctx["case"]["id"]),
                                    make_investigator_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_INVESTIGATOR)


class TestCapabilityGate:
    def test_capability_missing_returns_403(self, api):
        """PRD §2.1: "the referenced staff member must have `employment_status` equal
        to `ACTIVE` and must carry the `INTAKE` element in `capabilities`, otherwise
        the request fails with `ERR_CAPABILITY_MISSING` (HTTP 403)."

        Design: Corner/errors/capability_missing_returns_403
        """
        s_inv = create_staff("Ian Vest", "investigator@corp.example", ["INVESTIGATION"])
        case, _ = create_case()
        resp = api.triage_case(case["id"], create_triage_payload(), make_intake_headers(s_inv["id"]))
        validate_error(resp, ApiErrorId.ERR_CAPABILITY_MISSING)


class TestEvidenceLifecycle:
    def test_seal_then_exclude_terminal_path(self, api):
        """PRD §3.5: "The seal records `sealed_by_id` and moves the item to `SEALED`"
        and "Exclusion records `excluded_by_id` and moves the item to `EXCLUDED`,
        its terminal state."

        Design: Corner/state_machines/evidence_seal_exclude_terminal_path
        """
        ctx = setup_case_under_investigation()
        staff = ctx["staff"]
        resp = api.create_evidence_item(create_evidence_payload(ctx["case"]["id"]), staff["h_inv"])
        ev = validate_success(resp, expected_status=201)
        resp2 = api.seal_evidence(ev["id"], staff["h_int"])
        sealed = validate_success(resp2)
        assert sealed["status"] == "SEALED"
        assert sealed["sealed_by_id"] == staff["s_int"]["id"]
        resp3 = api.exclude_evidence(ev["id"],
                                     {"exclusion_reason": "Obtained outside the records retention scope."},
                                     staff["h_off"])
        excluded = validate_success(resp3)
        assert excluded["status"] == "EXCLUDED"

    def test_seal_excluded_item_rejected(self, api):
        """PRD §3.5: "sealing an item in any other state fails with
        `ERR_EVIDENCE_NOT_PRESERVED`".

        Design: Corner/state_machines/evidence_seal_exclude_terminal_path
        """
        ctx = setup_case_under_investigation()
        staff = ctx["staff"]
        ev = validate_success(api.create_evidence_item(
            create_evidence_payload(ctx["case"]["id"]), staff["h_inv"]), expected_status=201)
        api.seal_evidence(ev["id"], staff["h_int"])
        api.exclude_evidence(ev["id"],
                             {"exclusion_reason": "Obtained outside the records retention scope."},
                             staff["h_off"])
        resp = api.seal_evidence(ev["id"], staff["h_off"])
        validate_error(resp, ApiErrorId.ERR_EVIDENCE_NOT_PRESERVED)

    def test_exclude_twice_rejected(self, api):
        """PRD §3.5: "a `ComplianceOfficer` may exclude an item that is `PRESERVED`
        or `SEALED` (otherwise `ERR_EVIDENCE_NOT_EXCLUDABLE`)".

        Design: Corner/errors/exclude_already_excluded_evidence_rejected
        """
        ctx = setup_case_under_investigation()
        staff = ctx["staff"]
        ev = validate_success(api.create_evidence_item(
            create_evidence_payload(ctx["case"]["id"], evidence_type="PHOTO",
                                    description="Warehouse floor photo",
                                    checksum="d" * 64),
            staff["h_inv"]), expected_status=201)
        api.exclude_evidence(ev["id"],
                             {"exclusion_reason": "Obtained outside the records retention scope."},
                             staff["h_off"])
        resp = api.exclude_evidence(ev["id"],
                                    {"exclusion_reason": "Second exclusion attempt on terminal item."},
                                    staff["h_off"])
        validate_error(resp, ApiErrorId.ERR_EVIDENCE_NOT_EXCLUDABLE)
