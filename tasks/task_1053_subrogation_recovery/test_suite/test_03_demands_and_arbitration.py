"""Demands, the response window, and intercompany arbitration: honored responses,
open-window overlap, eligibility/disputed gating, filing-window deadlines, the cyclic
round machine, and hearing-docket buffer conflicts."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    record_response_payload, create_demand_payload, create_arbitration_payload,
    set_clock_payload, schedule_hearing_payload, file_round_payload,
    setup_demand_issued_claim, setup_disputed_demand_claim, setup_filed_arbitration,
    setup_two_filed_arbitrations_same_adverse,
)
from test_helpers import TEST_USERS

SPECIALIST = TEST_USERS["specialist_headers"]
SYSTEM = TEST_USERS["system_headers"]
READER = TEST_USERS["reader_headers"]


def test_record_response_honored_moves_demand_to_honored(api):
    """PRD §3.3: "Recording `HONORED` sets the demand's `outcome` and moves it from
    `ISSUED` to `HONORED`."

    Design: Corner/state_machines/demand_record_response_honored_valid_transition
    """
    ctx = setup_demand_issued_claim(api)
    resp = api.record_response(ctx["demand"]["id"], record_response_payload("HONORED"), SPECIALIST)
    demand = validate_success(resp)
    assert demand["status"] == "HONORED"
    assert demand["outcome"] == "HONORED"


def test_second_demand_while_window_open_rejected(api):
    """PRD §3.3: "A demand may be issued only if there is no existing demand for the
    claim that is still in `ISSUED` status with an open response window; attempting to
    issue while a prior demand's window is still open is rejected with
    `ERR_DEMAND_WINDOW_OPEN`."

    Design: Difficulty/resource_temporal_overlap/demand_window_overlap_half_open
    """
    ctx = setup_demand_issued_claim(api, amount_demanded_cents=3_000_000)
    resp = api.create_demand(ctx["claim"]["id"], create_demand_payload(2_900_000), SPECIALIST)
    validate_error(resp, "ERR_DEMAND_WINDOW_OPEN", 409)


def test_open_window_overlap_leaves_single_demand(api):
    """PRD §3.3: "A demand may be issued only if there is no existing demand for the
    claim that is still in `ISSUED` status with an open response window; attempting to
    issue while a prior demand's window is still open is rejected with
    `ERR_DEMAND_WINDOW_OPEN`."

    Design: Difficulty/resource_temporal_overlap/demand_window_overlap_half_open
    """
    ctx = setup_demand_issued_claim(api, amount_demanded_cents=3_000_000)
    api.create_demand(ctx["claim"]["id"], create_demand_payload(2_900_000), SPECIALIST)
    data, meta = validate_paginated(api.list_demands(READER, params={"claim_id": ctx["claim"]["id"]}))
    assert meta["total_count"] == 1, "the rejected second demand must not have been created"


def test_file_arbitration_without_disputed_demand_rejected(api):
    """PRD §3.4: "Filing requires that the adverse party's `is_arbitration_eligible` be
    true — otherwise `ERR_ADVERSE_NOT_ARBITRABLE` — and that at least one demand on the
    claim is in `DISPUTED` status — otherwise `ERR_DEMAND_NOT_DISPUTED`."

    Design: Corner/errors/file_arbitration_without_disputed_demand_returns_error
    """
    ctx = setup_demand_issued_claim(api)  # demand left ISSUED, not disputed
    resp = api.create_arbitration(ctx["claim"]["id"], create_arbitration_payload("AF"), SPECIALIST)
    validate_error(resp, "ERR_DEMAND_NOT_DISPUTED", 409)


def test_file_arbitration_after_window_closed_rejected(api):
    """PRD §3.4: "Filing must occur while the clock is before that disputed demand's
    `arbitration_window_due_at`; a filing at or after that instant is rejected with
    `ERR_ARBITRATION_WINDOW_CLOSED`."

    Design: Corner/errors/file_arbitration_after_window_closed_returns_error
    """
    # Demand disputed at default clock 2026-07-01 -> window due 2026-08-30; advance past it.
    ctx = setup_disputed_demand_claim(api)
    validate_success(api.set_clock(set_clock_payload("2026-09-15T00:00:00Z"), SYSTEM))
    resp = api.create_arbitration(ctx["claim"]["id"], create_arbitration_payload("AF"), SPECIALIST)
    validate_error(resp, "ERR_ARBITRATION_WINDOW_CLOSED", 409)


def test_file_arbitration_ineligible_adverse_rejected(api):
    """PRD §3.4: "Filing requires that the adverse party's `is_arbitration_eligible` be
    true — otherwise `ERR_ADVERSE_NOT_ARBITRABLE`".

    Design: Difficulty/cross_entity_state_dependency/arbitration_filing_depends_on_adverse_eligibility
    """
    ctx = setup_disputed_demand_claim(api, is_arbitration_eligible=False)
    resp = api.create_arbitration(ctx["claim"]["id"], create_arbitration_payload("AF"), SPECIALIST)
    validate_error(resp, "ERR_ADVERSE_NOT_ARBITRABLE", 409)


def test_file_arbitration_ineligible_leaves_claim_in_demand_issued(api):
    """PRD §3.4: "When a demand is disputed, the specialist may escalate the claim into
    intercompany arbitration, moving the claim from `DEMAND_ISSUED` to `ARBITRATION`."

    Design: Difficulty/cross_entity_state_dependency/arbitration_filing_depends_on_adverse_eligibility
    """
    ctx = setup_disputed_demand_claim(api, is_arbitration_eligible=False)
    api.create_arbitration(ctx["claim"]["id"], create_arbitration_payload("AF"), SPECIALIST)
    claim = validate_success(api.get_claim(ctx["claim"]["id"], READER))
    assert claim["status"] == "DEMAND_ISSUED", "a rejected filing must not advance the claim"


def test_ineligible_takes_precedence_over_closed_window(api):
    """PRD §2.11: "(8) referential arbitration eligibility checks
    (`ERR_ADVERSE_NOT_ARBITRABLE` / `ERR_DEMAND_NOT_DISPUTED`); (9) temporal deadline
    and window checks (`ERR_STATUTE_EXPIRED` / `ERR_ARBITRATION_WINDOW_CLOSED` /
    `ERR_DEMAND_WINDOW_OPEN` / `ERR_HEARING_WINDOW_CONFLICT`)".
    PRD §2.11: "Lower-numbered checks take precedence".

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_file_arbitration
    """
    ctx = setup_disputed_demand_claim(api, is_arbitration_eligible=False)
    validate_success(api.set_clock(set_clock_payload("2026-09-15T00:00:00Z"), SYSTEM))
    resp = api.create_arbitration(ctx["claim"]["id"], create_arbitration_payload("AF"), SPECIALIST)
    validate_error(resp, "ERR_ADVERSE_NOT_ARBITRABLE", 409)


def test_referential_error_reported_not_window_error(api):
    """PRD §2.11: "(8) referential arbitration eligibility checks
    (`ERR_ADVERSE_NOT_ARBITRABLE` / `ERR_DEMAND_NOT_DISPUTED`); (9) temporal deadline
    and window checks (`ERR_STATUTE_EXPIRED` / `ERR_ARBITRATION_WINDOW_CLOSED` /
    `ERR_DEMAND_WINDOW_OPEN` / `ERR_HEARING_WINDOW_CONFLICT`)".
    PRD §2.11: "Lower-numbered checks take precedence".

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_file_arbitration
    """
    ctx = setup_disputed_demand_claim(api, is_arbitration_eligible=False)
    validate_success(api.set_clock(set_clock_payload("2026-09-15T00:00:00Z"), SYSTEM))
    resp = api.create_arbitration(ctx["claim"]["id"], create_arbitration_payload("AF"), SPECIALIST)
    err = resp.json()["data"]["error_id"]
    assert err == "ERR_ADVERSE_NOT_ARBITRABLE", (
        f"referential check (p8) must pre-empt the window check (p9), got {err}"
    )


def test_first_round_moves_awaiting_to_response_filed(api):
    """PRD §3.4: "From `AWAITING_RESPONSE`, filing a round moves the arbitration to
    `RESPONSE_FILED`; from `RESPONSE_FILED`, filing a rebuttal round moves it back to
    `AWAITING_RESPONSE`, opening the next round — the two states toggle for as many
    rounds as the parties exchange."

    Design: Difficulty/non_linear_state_machine/arbitration_cyclic_response_rounds
    """
    ctx = setup_filed_arbitration(api)
    arb_id = ctx["arbitration"]["id"]
    validate_success(api.schedule_hearing(
        arb_id, schedule_hearing_payload("2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"), SPECIALIST))
    arb = validate_success(api.file_round(arb_id, file_round_payload("adverse response"), SPECIALIST))
    assert arb["status"] == "RESPONSE_FILED"
    assert arb["round_count"] == 1


def test_two_rounds_cycle_back_to_awaiting_response(api):
    """PRD §3.4: "From `AWAITING_RESPONSE`, filing a round moves the arbitration to
    `RESPONSE_FILED`; from `RESPONSE_FILED`, filing a rebuttal round moves it back to
    `AWAITING_RESPONSE`, opening the next round — the two states toggle for as many
    rounds as the parties exchange."

    Design: Difficulty/non_linear_state_machine/arbitration_cyclic_response_rounds
    """
    ctx = setup_filed_arbitration(api)
    arb_id = ctx["arbitration"]["id"]
    validate_success(api.schedule_hearing(
        arb_id, schedule_hearing_payload("2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"), SPECIALIST))
    validate_success(api.file_round(arb_id, file_round_payload("adverse response"), SPECIALIST))
    arb = validate_success(api.file_round(arb_id, file_round_payload("our rebuttal"), SPECIALIST))
    assert arb["round_count"] == 2
    assert arb["status"] == "AWAITING_RESPONSE"


def test_hearing_within_buffer_of_adverse_docket_rejected(api):
    """PRD §3.4: "no other arbitration tied to the *same adverse party* (reached
    through its claim) may already hold a hearing window within 7 days of the requested
    `[hearing_start, hearing_end]` span; a conflict within that 7-day buffer is rejected
    with `ERR_HEARING_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/hearing_buffer_overlap_adverse_docket
    """
    ctx = setup_two_filed_arbitrations_same_adverse(api)
    validate_success(api.schedule_hearing(
        ctx["arbitration1"]["id"],
        schedule_hearing_payload("2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"), SPECIALIST))
    resp = api.schedule_hearing(
        ctx["arbitration2"]["id"],
        schedule_hearing_payload("2026-08-05T00:00:00Z", "2026-08-06T00:00:00Z"), SPECIALIST)
    validate_error(resp, "ERR_HEARING_WINDOW_CONFLICT", 409)


def test_hearing_conflict_leaves_second_arbitration_filed(api):
    """PRD §3.4: "Scheduling the hearing moves the arbitration from `FILED` to
    `AWAITING_RESPONSE`; the specialist supplies `hearing_start` and `hearing_end`,
    which are recorded on the arbitration."

    Design: Difficulty/resource_temporal_overlap/hearing_buffer_overlap_adverse_docket
    """
    ctx = setup_two_filed_arbitrations_same_adverse(api)
    validate_success(api.schedule_hearing(
        ctx["arbitration1"]["id"],
        schedule_hearing_payload("2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"), SPECIALIST))
    api.schedule_hearing(
        ctx["arbitration2"]["id"],
        schedule_hearing_payload("2026-08-05T00:00:00Z", "2026-08-06T00:00:00Z"), SPECIALIST)
    arb2 = validate_success(api.get_arbitration(ctx["arbitration2"]["id"], READER))
    assert arb2["status"] == "FILED", "a conflicting hearing must not advance the arbitration"
