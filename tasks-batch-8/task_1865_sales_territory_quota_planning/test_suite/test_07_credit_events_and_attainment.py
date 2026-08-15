"""Booking credit: communication gate, split remainder, date validation,
uncovered/unassigned rejections, reversal semantics, and attainment rollup."""
import pytest

from test_helpers import (
    ADMIN,
    ZERO_RAMP_MULTIPLIERS,
    ApiErrorId,
    apply_allocation,
    communicate_plan,
    create_account,
    create_allocation,
    create_assignment,
    create_credit_event_payload,
    create_geo_rule,
    create_ramp_schedule,
    create_rep,
    get_assignment,
    get_submission,
    get_territory,
    post_booking,
    set_clock,
    setup_allocated_leaf,
    setup_change_apply_scenario,
    setup_communicated_leaf,
    setup_open_plan,
    setup_reconciled_leaf,
    submit,
    validate_error,
    validate_paginated,
    validate_success,
    walk_to_communicated,
)


def test_booking_before_communication_rejected(api):
    """PRD: "credit events, change requests, and disputes all refuse to exist
    before this point, failing with `ERR_PLAN_NOT_COMMUNICATED`."

    A booking against a RECONCILED-but-not-COMMUNICATED plan fails.

    Design: Difficulty/cross_entity_state_dependency/credit_event_requires_communicated_plan
    """
    base = setup_reconciled_leaf(label="FY27-X2", with_rep=True,
                                 with_account=True)
    set_clock("2027-06-05T00:00:00Z")
    validate_error(api.create_credit_event(
        create_credit_event_payload(base["plan"]["id"], base["acc"]["id"],
                                    5000, "2027-06-05"), ADMIN),
        ApiErrorId.ERR_PLAN_NOT_COMMUNICATED, 409)


def test_booking_after_communication_splits_to_sole_rep(api):
    """PRD: "credit events, change requests, and disputes all refuse to exist
    before this point, failing with `ERR_PLAN_NOT_COMMUNICATED`."
    PRD: "each credited rep receives one `BOOKING` credit event whose amount is
    the floor of the total divided by the number of credited reps, with the
    leftover cents distributed one at a time in assignment creation order, so
    the created events sum back to the requested total exactly."

    After communicate, the identical booking posts one BOOKING event of 5000
    to the sole eligible rep and the assignment's attainment becomes 5000.

    Design: Difficulty/cross_entity_state_dependency/credit_event_requires_communicated_plan
    """
    base = setup_reconciled_leaf(label="FY27-X2B", with_rep=True,
                                 with_account=True)
    set_clock("2027-06-05T00:00:00Z")
    validate_error(api.create_credit_event(
        create_credit_event_payload(base["plan"]["id"], base["acc"]["id"],
                                    5000, "2027-06-05"), ADMIN),
        ApiErrorId.ERR_PLAN_NOT_COMMUNICATED, 409)

    communicate_plan(base["plan"]["id"])
    events = validate_success(api.create_credit_event(
        create_credit_event_payload(base["plan"]["id"], base["acc"]["id"],
                                    5000, "2027-06-05"), ADMIN), 201)
    assert isinstance(events, list) and len(events) == 1
    evt = events[0]
    assert evt["rep_id"] == base["rep"]["id"]
    assert evt["event_type"] == "BOOKING"
    assert evt["status"] == "POSTED"
    assert evt["amount_cents"] == 5000
    assert evt["source_change_request_id"] is None
    assert evt["parent_credit_event_id"] is None
    assert get_assignment(base["asg"]["id"])["attainment_cents"] == 5000


def test_booking_split_remainder_to_earliest_assignment(api):
    """PRD: "The request's `amount_cents` is the pre-split total: each credited
    rep receives one `BOOKING` credit event whose amount is the floor of the
    total divided by the number of credited reps, with the leftover cents
    distributed one at a time in assignment creation order, so the created
    events sum back to the requested total exactly."

    99999 over two eligible reps splits 50000 / 49999, the remainder cent going
    to the assignment with the earlier creation timestamp.

    Design: Corner/calculations/booking_split_remainder_to_earliest_assignment
    """
    base = setup_allocated_leaf(label="FY27-SPLIT")
    plan_id = base["plan"]["id"]
    r1 = create_rep(full_name="R1")
    r2 = create_rep(full_name="R2")
    a1 = create_assignment(plan_id, r1["id"], base["t"]["id"])
    a2 = create_assignment(plan_id, r2["id"], base["t"]["id"])
    create_geo_rule(plan_id, base["t"]["id"])
    acc = create_account(plan_id, name="A")
    walk_to_communicated(plan_id)
    set_clock("2027-06-05T00:00:00Z")

    events = validate_success(api.create_credit_event(
        create_credit_event_payload(plan_id, acc["id"], 99999, "2027-06-05"),
        ADMIN), 201)
    assert len(events) == 2
    by_rep = {e["rep_id"]: e["amount_cents"] for e in events}
    assert by_rep[r1["id"]] == 50000, \
        "earlier-created assignment takes the remainder cent"
    assert by_rep[r2["id"]] == 49999
    assert sum(by_rep.values()) == 99999
    assert get_assignment(a1["id"])["attainment_cents"] == 50000
    assert get_assignment(a2["id"])["attainment_cents"] == 49999


def test_credit_to_unassigned_account_rejected(api):
    """PRD: "The account must be assigned: posting against an account whose
    `assigned_territory_id` is null fails with `ERR_ACCOUNT_UNASSIGNED`."

    Design: Corner/validations/credit_to_unassigned_account_rejected
    """
    base = setup_open_plan(label="FY27-UA")
    plan_id = base["plan"]["id"]
    acc = create_account(plan_id, name="A", country_code="BR")  # no rule matches
    assert acc["assigned_territory_id"] is None
    walk_to_communicated(plan_id)
    set_clock("2027-06-05T00:00:00Z")
    validate_error(api.create_credit_event(
        create_credit_event_payload(plan_id, acc["id"], 5000, "2027-06-05"),
        ADMIN), ApiErrorId.ERR_ACCOUNT_UNASSIGNED, 409)


def test_credit_to_uncovered_territory_rejected(api):
    """PRD: "The credited set is every rep holding an `ACTIVE` assignment on the
    account's assigned territory whose window covers the booking date —
    `effective_from` on or before the booking date, and either no
    `effective_to` or an `effective_to` strictly after it. An empty credited
    set fails with `ERR_TERRITORY_UNCOVERED`."

    The account's territory carries zero ACTIVE assignments covering the
    booking date, so no rep can be credited.

    Design: Corner/validations/credit_to_uncovered_territory_rejected
    """
    base = setup_open_plan(label="FY27-UC")
    plan_id = base["plan"]["id"]
    create_geo_rule(plan_id, base["t"]["id"])
    acc = create_account(plan_id, name="A")
    walk_to_communicated(plan_id)
    set_clock("2027-06-05T00:00:00Z")
    validate_error(api.create_credit_event(
        create_credit_event_payload(plan_id, acc["id"], 5000, "2027-06-05"),
        ADMIN), ApiErrorId.ERR_TERRITORY_UNCOVERED, 409)


def test_credit_booking_date_validation_rejected(api):
    """PRD: "The booking date must lie inside the plan year — outside it the
    post fails with `ERR_DATE_OUT_OF_PLAN_YEAR` — and must not lie after the
    current logical date, since a future-dated booking is
    `ERR_INVALID_REQUEST`"

    With the logical clock at 2027-06-01: 2026-06-01 precedes the plan year
    (422), and 2027-08-01 lies after the current logical date (400).

    Design: Corner/validations/credit_booking_date_validation_rejected
    """
    base = setup_communicated_leaf(label="FY27-DATES", with_rep=True,
                                   with_account=True,
                                   clock="2027-06-01T00:00:00Z")
    plan_id = base["plan"]["id"]
    validate_error(api.create_credit_event(
        create_credit_event_payload(plan_id, base["acc"]["id"], 5000,
                                    "2026-06-01"), ADMIN),
        ApiErrorId.ERR_DATE_OUT_OF_PLAN_YEAR, 422)
    validate_error(api.create_credit_event(
        create_credit_event_payload(plan_id, base["acc"]["id"], 5000,
                                    "2027-08-01"), ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_credit_reverse_no_cascade_and_terminal(api):
    """PRD: "Reversing a `BOOKING` never reverses or alters any `TRANSFER_OUT`
    or `TRANSFER_IN` events derived from it — transfer events are independent
    from the moment they are created."
    PRD: "an administrator may reverse a `POSTED` event, moving it to
    `REVERSED`, terminal; the reversed event drops out of every attainment
    rollup, and attainment cents and percentages recompute for the credited
    rep's assignments in the plan."

    After the mid-year move produced transfers of -8516 / +8516 from the July
    booking of 12000, reversing that booking leaves the transfers POSTED: the
    old rep's attainment drops to -8516 (the transfer outlives its source) and
    a second reverse is an invalid transition.

    Design: Corner/state_machines/credit_reverse_no_cascade_and_terminal
    """
    ns = setup_change_apply_scenario(
        label="FY27", target=480000, tf_potential=600, tt_potential=200,
        account_potential=288000, effective_date="2027-07-10",
        bookings=[("2027-07-15", 12000)], clock_final="2027-07-25T00:00:00Z",
        apply=True)
    evt = ns["events"][0]
    assert len(ns["events"]) == 1

    reversed_evt = validate_success(api.reverse_credit_event(evt["id"], ADMIN),
                                    200)
    assert reversed_evt["status"] == "REVERSED"

    old = get_assignment(ns["asg_old"]["id"])
    new = get_assignment(ns["asg_new"]["id"])
    assert old["attainment_cents"] == -8516, \
        "12000 excluded, TRANSFER_OUT -8516 still counts"
    assert new["attainment_cents"] == 8516

    transfers, _ = validate_paginated(api.list_credit_events(
        ADMIN, params={"source_change_request_id": ns["cr"]["id"]}))
    assert len(transfers) == 2
    assert all(e["status"] == "POSTED" for e in transfers)

    validate_error(api.reverse_credit_event(evt["id"], ADMIN),
                   ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)


def test_derived_field_attainment_recompute_on_reverse(api):
    """PRD: "Its `attainment_cents` is the signed sum of `amount_cents` over
    the rep's `POSTED` events in the assignment's plan — `BOOKING` and
    `TRANSFER_IN` amounts positive, `TRANSFER_OUT` amounts negative, `REVERSED`
    events excluded entirely — starting from a default of zero."
    PRD: "The denominator is the assignment's `final_quota_cents` once the plan
    is `RECONCILED`, `COMMUNICATED`, or `LOCKED`, and its `ramped_quota_cents`
    before that; the percentage is null whenever the denominator is null or
    zero"

    Posting 5000 moves attainment 0 -> 5000 with pct 5.00 against the final
    99996; reversing returns attainment to 0 with pct 0.00.

    Design: Corner/cross_cutting_complexity_layers/derived_field_attainment_recompute_on_reverse
    """
    base = setup_communicated_leaf(label="FY27-ROLL", with_rep=True,
                                   with_account=True,
                                   clock="2027-06-05T00:00:00Z")
    plan_id = base["plan"]["id"]
    asg_id = base["asg"]["id"]
    assert get_assignment(asg_id)["attainment_cents"] == 0

    events = post_booking(plan_id, base["acc"]["id"], 5000, "2027-06-05")
    after_post = get_assignment(asg_id)
    assert after_post["attainment_cents"] == 5000
    assert after_post["final_quota_cents"] == 99996, \
        "fully-ramped final share: 12 x round_half_up(100000/12)"
    assert after_post["attainment_pct"] == pytest.approx(5.00, abs=0.005)

    reversed_evt = validate_success(
        api.reverse_credit_event(events[0]["id"], ADMIN), 200)
    assert reversed_evt["status"] == "REVERSED"
    after_reverse = get_assignment(asg_id)
    assert after_reverse["attainment_cents"] == 0
    assert after_reverse["attainment_pct"] == pytest.approx(0.00, abs=0.005)


def test_attainment_pct_null_on_zero_denominator(api):
    """PRD: "The denominator is the assignment's `final_quota_cents` once the
    plan is `RECONCILED`, `COMMUNICATED`, or `LOCKED`, and its
    `ramped_quota_cents` before that; the percentage is null whenever the
    denominator is null or zero"

    An all-zero ramp schedule drives the rep's final quota to 0; attainment
    5000 against the zero denominator yields attainment_pct null, not an error
    and not infinity.

    Design: Corner/calculations/attainment_pct_null_on_zero_denominator
    """
    base = setup_allocated_leaf(label="FY27-ZERO")
    plan_id = base["plan"]["id"]
    ramp = create_ramp_schedule(multipliers=list(ZERO_RAMP_MULTIPLIERS),
                                name="Zero")
    rep = create_rep(hire_date="2027-01-10")
    asg = create_assignment(plan_id, rep["id"], base["t"]["id"],
                            ramp_schedule_id=ramp["id"])
    assert asg["base_quota_cents"] == 100000
    assert asg["ramped_quota_cents"] == 0
    create_geo_rule(plan_id, base["t"]["id"])
    acc = create_account(plan_id, name="A")
    walk_to_communicated(plan_id)
    set_clock("2027-06-05T00:00:00Z")

    after_recon = get_assignment(asg["id"])
    assert after_recon["final_quota_cents"] == 0, \
        "ramp over the 100000 final share with all-zero multipliers"

    post_booking(plan_id, acc["id"], 5000, "2027-06-05")
    final = get_assignment(asg["id"])
    assert final["attainment_cents"] == 5000
    assert final["attainment_pct"] is None


def test_immediate_read_after_write_consistency(api):
    """PRD: "In all cases the scope's own `assigned_quota_cents` becomes
    exactly the pool" — the quota written by an allocation apply is readable on
    the very next GET.
    PRD: "The server stamps `submitted_by_rep_id` from the `X-User-ID` header."
    — a created submission reads back SUBMITTED with the stamping from the
    header.

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    base = setup_open_plan(label="FY27-IMM")
    plan_id = base["plan"]["id"]
    rep = create_rep()
    create_assignment(plan_id, rep["id"], base["t"]["id"])

    alloc = create_allocation(plan_id, base["t"]["id"], 100000)
    apply_allocation(alloc["id"], plan_id)
    t_after = get_territory(base["t"]["id"])
    assert t_after["assigned_quota_cents"] == 100000, \
        "no reconciliation lag: the next read observes the apply"

    sub = submit(plan_id, base["t"]["id"], 90000, rep["id"])
    fetched = get_submission(sub["id"])
    assert fetched["status"] == "SUBMITTED"
    assert fetched["submitted_by_rep_id"] == rep["id"]
