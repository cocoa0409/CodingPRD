"""SurveyCycle posture machine: initial state, terminal lockdown, the cyclic
FIELDING/RECONCILIATION loop, and the clock gates (PRD §2.4, §2.7, §3.3–§3.5).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_cycle,
    create_cycle_payload,
    get_case,
    get_cycle,
    get_success_data,
    import_cases,
    import_discharges,
    make_cycle,
    make_program,
    make_provider,
    make_steward_headers,
    make_unit,
    make_vendor,
    make_vendor_headers,
    record_response,
    set_clock,
    setup_cycle_in_state,
    setup_program,
    setup_published_cycle,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]

ADMIN_CASE_BUDGET = 100


class TestCycleInitialState:
    def test_cycle_initial_state_draft(self, api):
        """PRD §3.3: "A new cycle starts in `DRAFT` with all derived counters at
        zero, a null `response_rate`, `publication_eligible` false, and every
        scored and published snapshot field null."

        Design: Corner/state_machines/cycle_initial_state_draft
        """
        program = make_program(name="P-SM1")
        res = api.create_cycle(create_cycle_payload(program["id"]),
                               ADMIN)
        cycle = validate_success(res, 201)
        assert_cycle(cycle)
        assert cycle["status"] == "DRAFT"
        assert cycle["sampled_count"] == 0
        assert cycle["completed_responses"] == 0
        assert cycle["eligible_denominator"] == 0
        assert cycle["response_rate"] is None
        assert cycle["publication_eligible"] is False

    def test_cycle_snapshot_fields_null_at_creation(self, api):
        """PRD §3.3: "A new cycle starts in `DRAFT` with all derived counters at
        zero, a null `response_rate`, `publication_eligible` false, and every
        scored and published snapshot field null."

        Design: Corner/state_machines/cycle_initial_state_draft
        """
        program = make_program(name="P-SM1B")
        cycle = make_cycle(program["id"], label="Q1", cycle_index=1)
        assert cycle["status"] == "DRAFT"
        for field in ("scored_raw_composite_pcts",
                      "scored_adjusted_composite_pcts", "scored_unit_breakdown",
                      "scored_provider_breakdown", "scored_response_rate",
                      "scored_completed_responses", "published_star_rating",
                      "published_at"):
            assert cycle[field] is None, f"{field} must be null at creation"
        assert cycle["response_rate"] is None
        assert cycle["publication_eligible"] is False


class TestTerminalLockdown:
    def _published_and_voided_cycles(self, api):
        prog_ctx = setup_program(name="P-SM2")
        published = setup_published_cycle(
            prog_ctx, 1, "Q1", topbox_count=25, low_count=0)["cycle"]
        c2 = make_cycle(prog_ctx["program"]["id"], label="Q2", cycle_index=2,
                        discharge_window_start="2026-07-01",
                        discharge_window_end="2026-07-31",
                        fielding_start_date="2026-09-01",
                        fielding_end_date="2026-09-30")
        voided = get_success_data(api.void_cycle(
            c2["id"], ADMIN))
        assert voided["status"] == "VOIDED"
        return published, voided

    def test_cycle_terminal_lockdown(self, api):
        """PRD §3.5: "Whole cycles can be voided too. From any state except the
        terminal `PUBLISHED` or an already-`VOIDED` cycle
        (`ERR_INVALID_STATE`), a `ProgramAdmin` voids the cycle."
        PRD §3.3: "Opening sampling moves the cycle from `DRAFT` to
        `SAMPLING_OPEN`. The cycle must currently be `DRAFT` (otherwise
        `ERR_INVALID_STATE`)"

        Design: Corner/state_machines/cycle_terminal_lockdown
        """
        published, voided = self._published_and_voided_cycles(api)
        admin = ADMIN

        res_void = api.void_cycle(published["id"], admin)
        validate_error(res_void, ApiErrorId.ERR_INVALID_STATE)
        res_open = api.open_sampling(voided["id"], admin)
        validate_error(res_open, ApiErrorId.ERR_INVALID_STATE)

        assert get_cycle(published["id"])["status"] == "PUBLISHED"
        assert get_cycle(voided["id"])["status"] == "VOIDED"

    def test_terminal_cycles_keep_their_status(self, api):
        """PRD §3.6: "Both `PUBLISHED` and `VOIDED` are terminal for a cycle."
        PRD §3.5: "Whole cycles can be voided too. From any state except the
        terminal `PUBLISHED` or an already-`VOIDED` cycle
        (`ERR_INVALID_STATE`), a `ProgramAdmin` voids the cycle."

        Design: Corner/state_machines/cycle_terminal_lockdown
        """
        published, voided = self._published_and_voided_cycles(api)
        admin = ADMIN
        # A second void on the already-VOIDED cycle is rejected too.
        validate_error(api.void_cycle(voided["id"], admin),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.void_cycle(published["id"], admin),
                       ApiErrorId.ERR_INVALID_STATE)
        assert get_cycle(published["id"])["status"] == "PUBLISHED"
        assert get_cycle(voided["id"])["status"] == "VOIDED"


class TestFieldingReconciliationReopenLoop:
    def test_cycle_fielding_reconciliation_reopen_loop(self, api):
        """PRD §3.5: "Reopening is the cyclic loop back: from `RECONCILIATION`
        to `FIELDING`; the cycle must be `RECONCILIATION`
        (`ERR_CYCLE_NOT_RECONCILING`), and the logical clock's date must still
        be on or before `fielding_end_date` (`ERR_REOPEN_WINDOW_EXPIRED`).
        Every `NONRESPONSE` case turns back to `IN_FIELD`, and a cycle may
        swing between `FIELDING` and `RECONCILIATION` more than once within
        its window."
        PRD §3.5: "Every case still `IN_FIELD` transitions to `NONRESPONSE`."

        Design: Difficulty/non_linear_state_machine/cycle_fielding_reconciliation_reopen_loop
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-NL1"), "FIELDING", discharge_count=1)
        case_id = ctx["case_ids"][0]
        cycle_id = ctx["cycle"]["id"]
        set_clock("2026-08-31T00:00:00Z")

        closed = validate_success(api.close_fielding(
            cycle_id, ADMIN),
            200)
        assert closed["status"] == "RECONCILIATION"
        assert get_case(case_id)["status"] == "NONRESPONSE"

        reopened = validate_success(api.reopen_fielding(
            cycle_id, ADMIN),
            200)
        assert reopened["status"] == "FIELDING"
        assert get_case(case_id)["status"] == "IN_FIELD"

        response = record_response(case_id, ctx["vendor"]["id"])
        assert response["status"] == "ACCEPTED"
        assert get_case(case_id)["status"] == "RESPONDED"

    def test_reopen_readmits_intake_after_reconciliation(self, api):
        """PRD §3.5: "Reopening is the cyclic loop back: from `RECONCILIATION`
        to `FIELDING`; ... Every `NONRESPONSE` case turns back to `IN_FIELD`,
        and a cycle may swing between `FIELDING` and `RECONCILIATION` more than
        once within its window."
        PRD §3.4: "While the cycle is `FIELDING`, a `VendorOperator` submits
        survey responses."

        Design: Difficulty/non_linear_state_machine/cycle_fielding_reconciliation_reopen_loop
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-NL1B"), "FIELDING", discharge_count=1)
        case_id = ctx["case_ids"][0]
        cycle_id = ctx["cycle"]["id"]
        admin = ADMIN
        set_clock("2026-08-31T00:00:00Z")
        get_success_data(api.close_fielding(cycle_id, admin))
        assert get_cycle(cycle_id)["status"] == "RECONCILIATION"
        assert get_case(case_id)["status"] == "NONRESPONSE"

        get_success_data(api.reopen_fielding(cycle_id, admin))
        assert get_cycle(cycle_id)["status"] == "FIELDING"
        assert get_case(case_id)["status"] == "IN_FIELD"

        response = record_response(case_id, ctx["vendor"]["id"])
        assert response["status"] == "ACCEPTED"
        assert response["is_late"] is False  # clock date == fielding_end_date
        assert get_case(case_id)["status"] == "RESPONDED"


class TestUnadjudicatedResponsesBlockScoring:
    def test_unadjudicated_responses_block_scoring(self, api):
        """PRD §3.6: "Beginning scoring moves the cycle from `RECONCILIATION`
        to `SCORING`; the cycle must be `RECONCILIATION`
        (`ERR_CYCLE_NOT_RECONCILING`). It is blocked while any response of the
        cycle remains `PENDING_REVIEW` (`ERR_UNADJUDICATED_RESPONSES`) — every
        late response must be adjudicated first."
        PRD §3.5: "a `decision` of `EXCLUDE` moves it to `EXCLUDED`, leaving
        the counter untouched."

        Design: Corner/validations/unadjudicated_responses_block_scoring
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V12"), "FIELDING", discharge_count=1)
        case_id = ctx["case_ids"][0]
        cycle_id = ctx["cycle"]["id"]
        admin = ADMIN

        set_clock("2026-09-05T00:00:00Z")
        late = record_response(case_id, ctx["vendor"]["id"])
        assert late["status"] == "PENDING_REVIEW"
        get_success_data(api.close_fielding(cycle_id, admin))

        blocked = api.begin_scoring(cycle_id, admin)
        validate_error(blocked, ApiErrorId.ERR_UNADJUDICATED_RESPONSES)

        get_success_data(api.adjudicate_response(
            late["id"], {"decision": "EXCLUDE"}, make_steward_headers()))
        scored = validate_success(api.begin_scoring(cycle_id, admin), 200)
        assert scored["status"] == "SCORING"
        assert scored["scored_completed_responses"] == 0

    def test_scoring_succeeds_once_pending_review_cleared(self, api):
        """PRD §3.6: "It is blocked while any response of the cycle remains
        `PENDING_REVIEW` (`ERR_UNADJUDICATED_RESPONSES`) — every late response
        must be adjudicated first."
        PRD §3.6: "Beginning scoring freezes the analytical snapshot"

        Design: Corner/validations/unadjudicated_responses_block_scoring
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V12B"), "FIELDING", discharge_count=1)
        case_id = ctx["case_ids"][0]
        cycle_id = ctx["cycle"]["id"]
        admin = ADMIN

        set_clock("2026-09-05T00:00:00Z")
        late = record_response(case_id, ctx["vendor"]["id"], score=3)
        get_success_data(api.close_fielding(cycle_id, admin))
        validate_error(api.begin_scoring(cycle_id, admin),
                       ApiErrorId.ERR_UNADJUDICATED_RESPONSES)
        assert get_cycle(cycle_id)["status"] == "RECONCILIATION"

        get_success_data(api.adjudicate_response(
            late["id"], {"decision": "EXCLUDE"}, make_steward_headers()))
        scored = validate_success(api.begin_scoring(cycle_id, admin), 200)
        assert scored["status"] == "SCORING"
        assert scored["scored_completed_responses"] == 0


class TestFieldingClockGates:
    def test_close_fielding_before_window_end(self, api):
        """PRD §3.5: "When the fielding window has run its course, a
        `ProgramAdmin` closes fielding, moving the cycle from `FIELDING` to
        `RECONCILIATION`; the cycle must be `FIELDING`
        (`ERR_CYCLE_NOT_FIELDING`), and the logical clock's date must be on or
        after `fielding_end_date` (`ERR_FIELDING_WINDOW_NOT_CLOSED`)."

        Design: Corner/validations/close_fielding_before_window_end
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V13"), "FIELDING", discharge_count=1)
        admin = ADMIN
        # Clock untouched: still the 2026-08-01 default, before 2026-08-31.
        res = api.close_fielding(ctx["cycle"]["id"], admin)
        validate_error(res, ApiErrorId.ERR_FIELDING_WINDOW_NOT_CLOSED)
        assert get_cycle(ctx["cycle"]["id"])["status"] == "FIELDING"

    def test_close_fielding_rejected_and_cycle_stays_fielding(self, api):
        """PRD §3.5: "the cycle must be `FIELDING` (`ERR_CYCLE_NOT_FIELDING`),
        and the logical clock's date must be on or after `fielding_end_date`
        (`ERR_FIELDING_WINDOW_NOT_CLOSED`)."
        PRD §2.4: "At startup, before any explicit set, the logical clock reads
        exactly `2026-08-01T00:00:00Z`; it must never fall back to the host
        wall clock."

        Design: Corner/validations/close_fielding_before_window_end
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V13B"), "FIELDING", discharge_count=1)
        admin = ADMIN
        set_clock("2026-08-30T00:00:00Z")  # one day before fielding_end_date
        validate_error(api.close_fielding(ctx["cycle"]["id"], admin),
                       ApiErrorId.ERR_FIELDING_WINDOW_NOT_CLOSED)
        assert get_cycle(ctx["cycle"]["id"])["status"] == "FIELDING"
        # And at exactly fielding_end_date the gate opens (boundary inclusive).
        set_clock("2026-08-31T00:00:00Z")
        closed = validate_success(
            api.close_fielding(ctx["cycle"]["id"], admin), 200)
        assert closed["status"] == "RECONCILIATION"

    def test_reopen_after_window_expired(self, api):
        """PRD §3.5: "Reopening is the cyclic loop back: from `RECONCILIATION`
        to `FIELDING`; the cycle must be `RECONCILIATION`
        (`ERR_CYCLE_NOT_RECONCILING`), and the logical clock's date must still
        be on or before `fielding_end_date` (`ERR_REOPEN_WINDOW_EXPIRED`)."

        Design: Corner/validations/reopen_after_window_expired
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V14"), "FIELDING", discharge_count=1)
        admin = ADMIN
        cycle_id = ctx["cycle"]["id"]
        set_clock("2026-08-31T00:00:00Z")
        get_success_data(api.close_fielding(cycle_id, admin))
        set_clock("2026-09-01T00:00:00Z")

        res = api.reopen_fielding(cycle_id, admin)
        validate_error(res, ApiErrorId.ERR_REOPEN_WINDOW_EXPIRED)
        assert get_cycle(cycle_id)["status"] == "RECONCILIATION"

    def test_reopen_window_expired_is_time_boxed(self, api):
        """PRD §3.5: "the cycle must be `RECONCILIATION`
        (`ERR_CYCLE_NOT_RECONCILING`), and the logical clock's date must still
        be on or before `fielding_end_date` (`ERR_REOPEN_WINDOW_EXPIRED`).
        Every `NONRESPONSE` case turns back to `IN_FIELD`, and a cycle may
        swing between `FIELDING` and `RECONCILIATION` more than once within
        its window."

        Design: Corner/validations/reopen_after_window_expired
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V14B"), "FIELDING", discharge_count=1)
        admin = ADMIN
        cycle_id = ctx["cycle"]["id"]
        set_clock("2026-08-31T00:00:00Z")
        get_success_data(api.close_fielding(cycle_id, admin))
        # At exactly fielding_end_date reopening is allowed (date-level
        # boundary, inclusive, per PRD §3.5) ...
        reopened = validate_success(api.reopen_fielding(cycle_id, admin), 200)
        assert reopened["status"] == "FIELDING"
        # ... and one day past it the loop is closed.
        get_success_data(api.close_fielding(cycle_id, admin))
        set_clock("2026-09-01T00:00:00Z")
        validate_error(api.reopen_fielding(cycle_id, admin),
                       ApiErrorId.ERR_REOPEN_WINDOW_EXPIRED)
        assert get_cycle(cycle_id)["status"] == "RECONCILIATION"
