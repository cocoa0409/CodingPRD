"""Validation precedence: when two checks fail, the higher-precedence error surfaces.

PRD §2.7 fixes a deterministic ordering and states it is observable. Covers
Difficulty: priority_pair_validation_conflict.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_manager_headers, set_clock, setup_location, setup_worker,
    setup_pay_period, create_posted_shift, create_draft_shift, assign_worker,
    setup_worker_with_strikes,
)


M = make_manager_headers()


def test_invalid_shift_state_preempts_guardrail(api):
    """PRD §2.7: "Only then are state-machine preconditions evaluated (the per-entity
    invalid-state errors), followed by the pay-period-open check (ERR_PAY_PERIOD_LOCKED),
    then the optimistic-concurrency version check on award (ERR_STALE_SHIFT_VERSION),
    then same-location referential integrity (ERR_CROSS_LOCATION)."
    PRD §2.7: "This ordering is observable: a request that violates two rules surfaces
    the higher-precedence error."

    Assigning to a DRAFT (un-posted) shift whose cost would also bust a 1-cent
    guardrail returns the state error, because the lower-precedence fiscal check never
    runs -> ERR_INVALID_SHIFT_STATE.

    Design: Difficulty/priority_pair_validation_conflict/invalid_shift_state_beats_guardrail
    """
    set_clock(api, "2026-05-30T00:00:00Z")
    loc = setup_location(api, overtime_cost_guardrail_cents=1,
                         predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    # Shift created but NOT posted -> DRAFT.
    s = create_draft_shift(api, loc["id"], start_utc="2026-06-02T09:00:00Z",
                           end_utc="2026-06-02T17:00:00Z", headcount_required=1)
    resp = api.create_assignment(loc["id"], {"shift_id": s["id"], "worker_id": worker["id"]}, M)
    validate_error(resp, ApiErrorId.ERR_INVALID_SHIFT_STATE.value)


def test_guardrail_alone_fires_on_posted_shift(api):
    """PRD §2.7: "the overtime cost guardrail (ERR_OVERTIME_GUARDRAIL_EXCEEDED)."
    PRD §3.10: "If the projected total computed with the new assignment included would
    be strictly greater than the location's overtime_cost_guardrail_cents, the
    assignment is refused with ERR_OVERTIME_GUARDRAIL_EXCEEDED."

    Control for the precedence pair: with the shift correctly OPEN, the same 1-cent
    guardrail is the only failing check, so the guardrail error surfaces. This
    confirms the guardrail is the strictly lower-precedence check pre-empted above.

    Design: Difficulty/priority_pair_validation_conflict/invalid_shift_state_beats_guardrail
    """
    set_clock(api, "2026-05-30T00:00:00Z")
    loc = setup_location(api, overtime_cost_guardrail_cents=1,
                         predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-02T09:00:00Z",
                            end_utc="2026-06-02T17:00:00Z", headcount_required=1)
    resp = api.create_assignment(loc["id"], {"shift_id": s["id"], "worker_id": worker["id"]}, M)
    validate_error(resp, ApiErrorId.ERR_OVERTIME_GUARDRAIL_EXCEEDED.value)


def test_worker_suspended_preempts_fully_staffed(api):
    """PRD §2.7: "worker-not-suspended (ERR_WORKER_SUSPENDED) is checked before
    worker-availability (ERR_WORKER_UNAVAILABLE), which is checked before the minor
    hour-cap (ERR_MINOR_HOUR_CAP_EXCEEDED), which is checked before the over-staffing
    guard (ERR_SHIFT_FULLY_STAFFED), which is checked before the overtime cost
    guardrail (ERR_OVERTIME_GUARDRAIL_EXCEEDED)."
    PRD §2.7: "This ordering is observable: a request that violates two rules surfaces
    the higher-precedence error."

    A SUSPENDED worker assigned to an already-full single-seat shift returns the
    suspended error, since the safety check outranks the staffing-capacity check ->
    ERR_WORKER_SUSPENDED.

    Design: Difficulty/priority_pair_validation_conflict/worker_suspended_beats_fully_staffed
    """
    loc, suspended, pp = setup_worker_with_strikes(3, worker_overrides=dict(
        full_name="WS", email="ws@x.com", base_hourly_rate_cents=2000), api=api)
    assert suspended["status"] == "SUSPENDED"
    # A fresh worker fills the single seat of a new shift.
    filler = setup_worker(api, loc["id"], full_name="WX", email="wx@x.com",
                          base_hourly_rate_cents=2000)
    sfull = create_posted_shift(api, loc["id"], start_utc="2026-06-06T09:00:00Z",
                                end_utc="2026-06-06T13:00:00Z", headcount_required=1)
    assign_worker(api, loc["id"], sfull["id"], filler["id"])
    resp = api.create_assignment(loc["id"], {"shift_id": sfull["id"], "worker_id": suspended["id"]}, M)
    validate_error(resp, ApiErrorId.ERR_WORKER_SUSPENDED.value)


def test_fully_staffed_alone_fires_for_active_worker(api):
    """PRD §2.7: "the over-staffing guard (ERR_SHIFT_FULLY_STAFFED)."
    PRD §3.9: "A shift already at its required headcount cannot take another worker —
    assigning or awarding when the filled count already equals the required count is
    rejected with ERR_SHIFT_FULLY_STAFFED."

    Control for the precedence pair: assigning an ACTIVE (not-suspended) worker to an
    already-full single-seat shift fails only the over-staffing guard, so
    ERR_SHIFT_FULLY_STAFFED surfaces. This confirms it is the strictly lower-precedence
    check pre-empted above.

    Design: Difficulty/priority_pair_validation_conflict/worker_suspended_beats_fully_staffed
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    filler = setup_worker(api, loc["id"], full_name="WX", email="wx@x.com",
                          base_hourly_rate_cents=2000)
    other = setup_worker(api, loc["id"], full_name="WY", email="wy@x.com",
                         base_hourly_rate_cents=2000)
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    sfull = create_posted_shift(api, loc["id"], start_utc="2026-06-06T09:00:00Z",
                                end_utc="2026-06-06T13:00:00Z", headcount_required=1)
    assign_worker(api, loc["id"], sfull["id"], filler["id"])
    resp = api.create_assignment(loc["id"], {"shift_id": sfull["id"], "worker_id": other["id"]}, M)
    validate_error(resp, ApiErrorId.ERR_SHIFT_FULLY_STAFFED.value)
