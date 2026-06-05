"""Swap negotiation (cyclic) and time-off lifecycle.

Covers Difficulty: non_linear_state_machine (swap PROPOSED<->COUNTERED loop),
cross_entity_state_dependency (time-off approval blocked by overlapping assignment).
Covers Corner state_machines: swap counter unauthorized, swap approve reassigns,
time-off deny-then-approve.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_manager_headers, make_worker_headers, set_clock, setup_location,
    setup_worker, setup_pay_period, create_posted_shift, assign_worker,
    setup_swap_proposed, add_time_off,
)


M = make_manager_headers()


def test_swap_counter_then_repropose_cycles_back_to_proposed(api):
    """PRD §3.12: "the counterparty may counter by offering one of their own
    assignments back, supplying counter_assignment_id ... it records
    counter_assignment_id and moves the swap to COUNTERED."
    PRD §3.12: "From COUNTERED, the initiator may repropose — permitted only from
    COUNTERED, only by the initiator (the worker of from_assignment_id, else
    ERR_UNAUTHORIZED) — which clears counter_assignment_id and returns the swap to
    PROPOSED, continuing the revision loop."

    Counter (PROPOSED->COUNTERED) records counter_assignment_id; repropose
    (COUNTERED->PROPOSED) clears it -> swap is back to PROPOSED with no counter.

    Design: Difficulty/non_linear_state_machine/swap_cyclic_proposed_countered_proposed_loop
    """
    loc, pp, wa, wb, a_a, a_b, swap = setup_swap_proposed(api=api)
    get_success_data(api.counter_swap(loc["id"], swap["id"],
                                      {"counter_assignment_id": a_b["id"]},
                                      make_worker_headers(wb["id"])))
    data = get_success_data(api.repropose_swap(loc["id"], swap["id"],
                                               make_worker_headers(wa["id"])))
    assert data["status"] == "PROPOSED"
    assert data["counter_assignment_id"] is None, "repropose must clear counter_assignment_id"


def test_swap_counter_records_counter_assignment_and_moves_to_countered(api):
    """PRD §3.12: "the counterparty may counter by offering one of their own
    assignments back, supplying counter_assignment_id. Countering is permitted only
    from PROPOSED (otherwise ERR_INVALID_SWAP_STATE), only by the counterparty whose
    X-User-ID equals to_worker_id (else ERR_UNAUTHORIZED), and only when the offered
    counter assignment belongs to the acting worker and is itself in SCHEDULED or
    CONFIRMED (otherwise ERR_INVALID_ASSIGNMENT_STATE); it records
    counter_assignment_id and moves the swap to COUNTERED."

    First half of the cycle: counter moves PROPOSED->COUNTERED and stamps the
    counterparty's assignment id as counter_assignment_id.

    Design: Difficulty/non_linear_state_machine/swap_cyclic_proposed_countered_proposed_loop
    """
    loc, pp, wa, wb, a_a, a_b, swap = setup_swap_proposed(api=api)
    data = get_success_data(api.counter_swap(loc["id"], swap["id"],
                                             {"counter_assignment_id": a_b["id"]},
                                             make_worker_headers(wb["id"])))
    assert data["status"] == "COUNTERED"
    assert data["counter_assignment_id"] == a_b["id"]


def test_swap_counter_by_non_to_worker_unauthorized(api):
    """PRD §3.12: "Countering is permitted only from PROPOSED (otherwise
    ERR_INVALID_SWAP_STATE), only by the counterparty whose X-User-ID equals
    to_worker_id (else ERR_UNAUTHORIZED)."

    A third worker (neither initiator nor to_worker) attempting to counter ->
    ERR_UNAUTHORIZED.

    Design: Corner/state_machines/swap_counter_by_non_to_worker_returns_unauthorized
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    wa = setup_worker(api, loc["id"], full_name="WA", email="wa@x.com", base_hourly_rate_cents=2000)
    wb = setup_worker(api, loc["id"], full_name="WB", email="wb@x.com", base_hourly_rate_cents=2000)
    wc = setup_worker(api, loc["id"], full_name="WC", email="wc@x.com", base_hourly_rate_cents=2000)
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    sa = create_posted_shift(api, loc["id"], start_utc="2026-06-05T09:00:00Z",
                             end_utc="2026-06-05T13:00:00Z", headcount_required=1)
    a_a = assign_worker(api, loc["id"], sa["id"], wa["id"])
    sc = create_posted_shift(api, loc["id"], start_utc="2026-06-06T09:00:00Z",
                             end_utc="2026-06-06T13:00:00Z", headcount_required=1)
    a_c = assign_worker(api, loc["id"], sc["id"], wc["id"])
    swap = get_success_data(api.create_swap(loc["id"],
                                            {"from_assignment_id": a_a["id"], "to_worker_id": wb["id"]},
                                            make_worker_headers(wa["id"])))
    resp = api.counter_swap(loc["id"], swap["id"], {"counter_assignment_id": a_c["id"]},
                            make_worker_headers(wc["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_swap_approve_reassigns_from_assignment_worker(api):
    """PRD §3.12: "Approval drives a cross-entity cascade: the from-assignment's
    worker_id is reassigned to the to_worker_id and its source is set to SWAP."
    PRD §3.12: "Acceptance moves the swap to ACCEPTED and is permitted from either
    PROPOSED or COUNTERED (otherwise ERR_INVALID_SWAP_STATE); when accepting from
    PROPOSED the acting worker must be the counterparty (to_worker_id)."

    After WB accepts and the manager approves a one-way swap, the from_assignment's
    worker_id is reassigned from WA to WB and the swap is MANAGER_APPROVED.

    Design: Corner/state_machines/swap_approve_reassigns_worker
    """
    loc, pp, wa, wb, a_a, a_b, swap = setup_swap_proposed(api=api)
    get_success_data(api.accept_swap(loc["id"], swap["id"], make_worker_headers(wb["id"])))
    swap_data = get_success_data(api.approve_swap(loc["id"], swap["id"], M))
    assert swap_data["status"] == "MANAGER_APPROVED"
    asg = get_success_data(api.get_assignment(a_a["id"], M))
    assert asg["worker_id"] == wb["id"], "from_assignment must be reassigned to to_worker"


def test_timeoff_deny_then_approve_rejected(api):
    """PRD §3.2: "Approval is permitted only from PENDING (otherwise
    ERR_INVALID_TIME_OFF_STATE)."
    PRD §3.2: "Denial moves a PENDING request to DENIED."

    A DENIED (terminal) time-off request cannot be approved -> ERR_INVALID_TIME_OFF_STATE.

    Design: Corner/state_machines/timeoff_deny_then_approve_returns_invalid_time_off_state
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    to = add_time_off(api, worker["id"], start_utc="2026-06-10T00:00:00Z",
                      end_utc="2026-06-11T00:00:00Z", reason="x")
    get_success_data(api.deny_time_off(loc["id"], to["id"], M))
    resp = api.approve_time_off(loc["id"], to["id"], M)
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_OFF_STATE.value)


def test_timeoff_approve_blocked_by_overlapping_assignment(api):
    """PRD §3.2: "Approval is permitted only from PENDING (otherwise
    ERR_INVALID_TIME_OFF_STATE) and additionally requires that no SCHEDULED or
    CONFIRMED assignment for that worker overlaps the requested half-open window; if
    one does, approval is rejected with ERR_TIME_OFF_CONFLICTS_ASSIGNMENT."

    A PENDING time-off window that overlaps the worker's existing SCHEDULED
    assignment is rejected on approval -> ERR_TIME_OFF_CONFLICTS_ASSIGNMENT.

    Design: Difficulty/cross_entity_state_dependency/timeoff_approve_blocked_by_overlapping_assignment
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-03T09:00:00Z",
                            end_utc="2026-06-03T13:00:00Z", headcount_required=1)
    assign_worker(api, loc["id"], s["id"], worker["id"])
    to = add_time_off(api, worker["id"], start_utc="2026-06-03T00:00:00Z",
                      end_utc="2026-06-04T00:00:00Z", reason="vacation")
    resp = api.approve_time_off(loc["id"], to["id"], M)
    validate_error(resp, ApiErrorId.ERR_TIME_OFF_CONFLICTS_ASSIGNMENT.value)


def test_timeoff_approve_succeeds_without_overlap(api):
    """PRD §3.2: "Approval is permitted only from PENDING (otherwise
    ERR_INVALID_TIME_OFF_STATE) and additionally requires that no SCHEDULED or
    CONFIRMED assignment for that worker overlaps the requested half-open window; if
    one does, approval is rejected with ERR_TIME_OFF_CONFLICTS_ASSIGNMENT."
    PRD §3.2: "Once approved, the request moves to APPROVED."

    Boundary partner: a PENDING time-off window with no overlapping assignment
    approves cleanly to APPROVED.

    Design: Difficulty/cross_entity_state_dependency/timeoff_approve_blocked_by_overlapping_assignment
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-03T09:00:00Z",
                            end_utc="2026-06-03T13:00:00Z", headcount_required=1)
    assign_worker(api, loc["id"], s["id"], worker["id"])
    # Time-off window on a different day, no overlap with the 06-03 assignment.
    to = add_time_off(api, worker["id"], start_utc="2026-06-10T00:00:00Z",
                      end_utc="2026-06-11T00:00:00Z", reason="vacation")
    data = get_success_data(api.approve_time_off(loc["id"], to["id"], M))
    assert data["status"] == "APPROVED"
