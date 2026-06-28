"""Order parallel axes, dispute cyclic loop, resolve/cancel cascades, and
balance-conservation invariants.

Queue A (Difficulty): non_linear_state_machine, transitive_cascade,
compensating_invariant.
Queue B (Corner): state_machines + cross_cutting_concerns sections.
"""
from test_helpers import (
    validate_success,
    setup_delivered_order, setup_dispute, set_clock,
    create_fee_schedule, create_account, create_vehicle, create_inspector,
    create_draft_order, create_dispatched_order, create_reported_order,
    offer_assignment, offer_and_accept, compile_vin_report, pay_order, invoice_order,
    deliver_order, create_report_for, submit_report,
    make_account_holder_headers, make_inspector_headers,
    assert_refund_conservation,
    TEST_USERS,
)

OPS = TEST_USERS["ops_admin_headers"]


# ===========================================================================
# non_linear_state_machine — order parallel axes (Queue A)
# ===========================================================================
def test_pay_draft_order_advances_payment_axis_only(api):
    """PRD §2.6: "The two axes do not gate each other except where Section 3
    explicitly says so; an order can be paid while still in `DRAFT`, or delivered
    while invoiced."

    Design: Difficulty/non_linear_state_machine/order_parallel_workflow_and_payment_axes
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2017, make="VW", model="Jetta")
    order = create_draft_order(acct, veh, fs, rush_tier="NONE")

    paid = validate_success(api.pay_order(order["id"], make_account_holder_headers(acct["id"])), 200)
    assert paid["payment_status"] == "PAID"
    assert paid["workflow_status"] == "DRAFT"


def test_pay_draft_order_leaves_workflow_draft(api):
    """PRD §3.3: "The prepaid path, used by individual buyers, is the account
    paying its own order, moving `payment_status` from `UNPAID` to `PAID`; this
    is allowed only while the payment status is `UNPAID` and the order is not
    `CANCELLED`."

    Design: Difficulty/non_linear_state_machine/order_parallel_workflow_and_payment_axes
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle()
    order = create_draft_order(acct, veh, fs, rush_tier="NONE")
    assert order["workflow_status"] == "DRAFT"
    assert order["payment_status"] == "UNPAID"

    paid = validate_success(api.pay_order(order["id"], make_account_holder_headers(acct["id"])), 200)
    assert paid["workflow_status"] == "DRAFT"


# ===========================================================================
# non_linear_state_machine — dispute cyclic NEEDS_INFO loop (Queue A)
# ===========================================================================
def _delivered_with_dispute(reason="LATE_DELIVERY", claimed=1000):
    ctx = setup_delivered_order(
        account_overrides={"account_type": "INDIVIDUAL", "net_terms_days": 0},
        inspector_overrides={"certified_tiers": ["STANDARD"]},
        order_overrides={"rush_tier": "NONE"},
        pay=True,
    )
    dispute = setup_dispute(reason, claimed, ctx["account"]["id"],
                            ctx["delivered_order"], ctx["report"], start_review=True)
    return ctx, dispute


def test_dispute_needs_info_returns_to_open(api):
    """PRD §3.8: "The filing account then supplies the requested information,
    moving a `NEEDS_INFO` dispute back to `OPEN` for another review round."

    Design: Difficulty/non_linear_state_machine/dispute_cyclic_needs_info_loop
    """
    ctx, dispute = _delivered_with_dispute()
    validate_success(api.request_info_dispute(dispute["id"], OPS), 200)
    supplied = validate_success(
        api.supply_info_dispute(dispute["id"], make_account_holder_headers(ctx["account"]["id"])), 200)
    assert supplied["status"] == "OPEN"


def test_dispute_request_info_moves_to_needs_info(api):
    """PRD §3.8: "From `UNDER_REVIEW`, operations may request additional
    information, moving it to `NEEDS_INFO`."

    Design: Difficulty/non_linear_state_machine/dispute_cyclic_needs_info_loop
    """
    ctx, dispute = _delivered_with_dispute()
    needs_info = validate_success(api.request_info_dispute(dispute["id"], OPS), 200)
    assert needs_info["status"] == "NEEDS_INFO"


# ===========================================================================
# transitive_cascade — dispute resolve refund chain depth 3 (Queue A)
# ===========================================================================
def _missed_defect_on_time_dispute():
    ctx = setup_delivered_order(
        fee_overrides={"tier_code": "PREMIUM", "base_fee_cents": 25000,
                       "vin_history_fee_cents": 4000, "per_mile_dispatch_cents": 150},
        account_overrides={"account_type": "DEALER", "net_terms_days": 30, "rush_discount_pct": 0.10},
        inspector_overrides={"certified_tiers": ["PREMIUM"]},
        order_overrides={"include_vin_history": True, "rush_tier": "EXPRESS"},
        asg_overrides={"dispatch_miles": 40},
        ordered_at="2026-06-01T00:00:00Z",
        delivered_at="2026-06-02T12:00:00Z",
        pay=True,
    )
    dispute = setup_dispute("MISSED_DEFECT", 30000, ctx["account"]["id"],
                            ctx["delivered_order"], ctx["report"], start_review=True)
    return ctx, dispute


def test_resolve_refund_flips_payment_to_refunded(api):
    """PRD §3.8: "The order's `refunded_cents` increases by the `approved_cents`.
    If the order's `payment_status` was `PAID` and the approved amount is greater
    than 0, the payment status moves to `REFUNDED`."

    Design: Difficulty/transitive_cascade/dispute_resolve_refund_chain_depth3
    """
    ctx, dispute = _missed_defect_on_time_dispute()
    resolved = validate_success(api.resolve_dispute(dispute["id"], OPS), 200)
    assert resolved["approved_cents"] == 20650
    order = validate_success(api.get_order(ctx["delivered_order"]["id"], OPS), 200)
    assert order["refunded_cents"] == 20650
    assert order["payment_status"] == "REFUNDED"


def test_resolve_missed_defect_amends_linked_report(api):
    """PRD §3.8: "when the reason is `MISSED_DEFECT`, the linked report is flagged
    for re-authoring by moving its `status` from `SUBMITTED` to `AMENDED`, while
    the order remains `DELIVERED`."

    Design: Difficulty/transitive_cascade/dispute_resolve_refund_chain_depth3
    """
    ctx, dispute = _missed_defect_on_time_dispute()
    validate_success(api.resolve_dispute(dispute["id"], OPS), 200)
    report = validate_success(api.get_report(ctx["report"]["id"], OPS), 200)
    assert report["status"] == "AMENDED"


# ===========================================================================
# transitive_cascade — cancel dispatched releases assignment depth 2 (Queue A)
# ===========================================================================
def test_cancel_dispatched_order_releases_assignment(api):
    """PRD §3.2: "Cancelling a `DISPATCHED` order also cascades the order's
    accepted assignment to `RELEASED`, freeing the inspector's slot."

    Design: Difficulty/transitive_cascade/order_cancel_releases_assignment_depth2
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2016, make="Acura", model="Legend")
    insp = create_inspector(certified_tiers=["STANDARD"])
    order, asg = create_dispatched_order(acct, veh, fs, insp)

    cancelled = validate_success(
        api.cancel_order(order["id"], make_account_holder_headers(acct["id"])), 200)
    assert cancelled["workflow_status"] == "CANCELLED"
    asg_after = validate_success(api.get_assignment(asg["id"], OPS), 200)
    assert asg_after["status"] == "RELEASED"


def test_cancel_dispatched_order_sets_workflow_cancelled(api):
    """PRD §3.2: "An `AccountHolder` may cancel its own order only while it is in
    `DRAFT` or `DISPATCHED` workflow status, transitioning it to `CANCELLED`."

    Design: Difficulty/transitive_cascade/order_cancel_releases_assignment_depth2
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle()
    insp = create_inspector(certified_tiers=["STANDARD"])
    order, asg = create_dispatched_order(acct, veh, fs, insp)

    cancelled = validate_success(
        api.cancel_order(order["id"], make_account_holder_headers(acct["id"])), 200)
    assert cancelled["workflow_status"] == "CANCELLED"


# ===========================================================================
# compensating_invariant — invoice then late deliver (Queue A)
# ===========================================================================
def test_invoice_then_late_deliver_trues_up_outstanding_balance(api):
    """PRD §3.7: "If the order's payment status is `INVOICED`, the account's
    `outstanding_balance_cents` is adjusted by the difference between the final
    fee and the previously booked estimated fee, so a late credit reduces the
    account's outstanding balance accordingly."

    Design: Difficulty/compensating_invariant/invoice_then_late_deliver_outstanding_equals_fee_total
    """
    ctx = setup_delivered_order(
        fee_overrides={"tier_code": "PREMIUM", "base_fee_cents": 25000,
                       "vin_history_fee_cents": 4000, "per_mile_dispatch_cents": 150},
        account_overrides={"account_type": "DEALER", "net_terms_days": 30, "rush_discount_pct": 0.10},
        inspector_overrides={"certified_tiers": ["PREMIUM"]},
        order_overrides={"include_vin_history": True, "rush_tier": "EXPRESS"},
        asg_overrides={"dispatch_miles": 40},
        ordered_at="2026-06-01T00:00:00Z",
        delivered_at="2026-06-05T00:00:00Z",  # late
        invoice=True, pay=False,
    )
    order = ctx["delivered_order"]
    assert order["fee_total_cents"] == 35000
    assert order["estimated_fee_cents"] == 41300
    acct = validate_success(api.get_account(ctx["account"]["id"], OPS), 200)
    assert acct["outstanding_balance_cents"] == 35000


def test_invoice_adds_estimated_fee_to_outstanding_balance(api):
    """PRD §3.3: "When an order is invoiced, the account's
    `outstanding_balance_cents` increases by that order's current
    `estimated_fee_cents`; the balance is later trued up to the final fee at
    delivery."

    Design: Difficulty/compensating_invariant/invoice_then_late_deliver_outstanding_equals_fee_total
    """
    set_clock("2026-06-01T00:00:00Z")
    fs = create_fee_schedule(tier_code="PREMIUM", base_fee_cents=25000,
                             vin_history_fee_cents=4000, per_mile_dispatch_cents=150)
    acct = create_account(account_type="DEALER", net_terms_days=30, rush_discount_pct=0.10)
    veh = create_vehicle()
    insp = create_inspector(certified_tiers=["PREMIUM"])
    order, asg = create_dispatched_order(acct, veh, fs, insp,
                                         order_overrides={"include_vin_history": True, "rush_tier": "EXPRESS"},
                                         asg_overrides={"dispatch_miles": 40})
    assert order["estimated_fee_cents"] == 41300
    invoice_order(order)
    acct_after = validate_success(api.get_account(acct["id"], OPS), 200)
    assert acct_after["outstanding_balance_cents"] == 41300


# ===========================================================================
# compensating_invariant — accept then release conserves slot count (Queue A)
# ===========================================================================
def test_release_frees_slot_so_fresh_accept_succeeds_at_cap(api):
    """PRD §3.4: "An accepted assignment can be released by operations, moving it
    to `RELEASED` and freeing the inspector's slot for overlap and daily-cap
    re-eligibility."

    Design: Difficulty/compensating_invariant/accept_then_release_conserves_inspector_slot_count
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh_a = create_vehicle(year=2008, make="Porsche", model="911")
    veh_b = create_vehicle(year=2008, make="Porsche", model="Boxster")
    insp = create_inspector(certified_tiers=["STANDARD"], max_daily_jobs=1)

    order_a = create_draft_order(acct, veh_a, fs, rush_tier="NONE")
    asg_a, order_a = offer_and_accept(order_a, insp,
                                      window_start="2026-06-02T09:00:00Z",
                                      window_end="2026-06-02T10:00:00Z")
    validate_success(api.release_assignment(asg_a["id"], OPS), 200)

    order_b = create_draft_order(acct, veh_b, fs, rush_tier="NONE")
    asg_b = offer_assignment(order_b, insp,
                             window_start="2026-06-02T11:00:00Z",
                             window_end="2026-06-02T12:00:00Z")
    accepted = validate_success(api.accept_assignment(asg_b["id"], make_inspector_headers(insp["id"])), 200)
    assert accepted["status"] == "ACCEPTED"
    order_b_after = validate_success(api.get_order(order_b["id"], OPS), 200)
    assert order_b_after["workflow_status"] == "DISPATCHED"


def test_released_assignment_status_is_released(api):
    """PRD §3.4: "Release is permitted only while the order is `DISPATCHED` or
    `CANCELLED`; once the order has progressed to `IN_PROGRESS` the assignment
    can no longer be released."

    Design: Difficulty/compensating_invariant/accept_then_release_conserves_inspector_slot_count
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2008, make="Porsche", model="911")
    insp = create_inspector(certified_tiers=["STANDARD"], max_daily_jobs=1)
    order = create_draft_order(acct, veh, fs, rush_tier="NONE")
    asg, order = offer_and_accept(order, insp,
                                  window_start="2026-06-02T09:00:00Z",
                                  window_end="2026-06-02T10:00:00Z")

    released = validate_success(api.release_assignment(asg["id"], OPS), 200)
    assert released["status"] == "RELEASED"


# ===========================================================================
# Queue B — state_machines corner instances
# ===========================================================================
def test_cancel_already_cancelled_order_rejected(api):
    """PRD §3.2: "attempting to cancel from any other state is rejected as an
    invalid state transition."

    Design: Corner/state_machines/cancel_already_cancelled_order_invalid_state
    """
    from test_helpers import validate_error
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2010, make="Nissan", model="370Z")
    order = create_draft_order(acct, veh, fs, rush_tier="NONE")
    ah = make_account_holder_headers(acct["id"])
    validate_success(api.cancel_order(order["id"], ah), 200)

    res = api.cancel_order(order["id"], ah)
    validate_error(res, "ERR_INVALID_STATE")


def test_accept_declined_assignment_rejected(api):
    """PRD §3.4: "Declining an `OFFERED` assignment moves it to `DECLINED`, a
    terminal state, and has no further effect."

    Design: Corner/state_machines/accept_already_declined_assignment_invalid_state
    """
    from test_helpers import validate_error
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2010, make="Audi", model="A4")
    insp = create_inspector(certified_tiers=["STANDARD"])
    order = create_draft_order(acct, veh, fs, rush_tier="NONE")
    asg = offer_assignment(order, insp)
    insp_h = make_inspector_headers(insp["id"])
    validate_success(api.decline_assignment(asg["id"], insp_h), 200)

    res = api.accept_assignment(asg["id"], insp_h)
    validate_error(res, "ERR_INVALID_STATE")


def test_start_review_on_resolved_dispute_rejected(api):
    """PRD §3.8: "a successful resolution moves the dispute to the terminal
    `RESOLVED` state."

    Design: Corner/state_machines/resolved_dispute_terminal_lockdown
    """
    from test_helpers import validate_error
    ctx = setup_delivered_order(
        account_overrides={"account_type": "INDIVIDUAL", "net_terms_days": 0},
        inspector_overrides={"certified_tiers": ["STANDARD"]},
        order_overrides={"rush_tier": "NONE"},
        pay=True,
    )
    dispute = setup_dispute("WRONG_VEHICLE", 15000, ctx["account"]["id"],
                            ctx["delivered_order"], ctx["report"], start_review=True)
    validate_success(api.resolve_dispute(dispute["id"], OPS), 200)

    res = api.start_review_dispute(dispute["id"], OPS)
    validate_error(res, "ERR_INVALID_STATE")


def test_wrong_vehicle_full_refund_side_effect(api):
    """PRD §3.8: "for `WRONG_VEHICLE` it is the full `fee_total_cents`."

    Design: Corner/state_machines/wrong_vehicle_full_refund_resolution_side_effect
    """
    ctx = setup_delivered_order(
        fee_overrides={"tier_code": "STANDARD", "base_fee_cents": 15000,
                       "vin_history_fee_cents": 3000, "per_mile_dispatch_cents": 100},
        account_overrides={"account_type": "INDIVIDUAL", "net_terms_days": 0},
        inspector_overrides={"certified_tiers": ["STANDARD"]},
        order_overrides={"rush_tier": "NONE"},
        asg_overrides={"dispatch_miles": 0},
        pay=True,
    )
    order = ctx["delivered_order"]
    assert order["fee_total_cents"] == 15000
    dispute = setup_dispute("WRONG_VEHICLE", 15000, ctx["account"]["id"], order, ctx["report"])

    resolved = validate_success(api.resolve_dispute(dispute["id"], OPS), 200)
    assert resolved["approved_cents"] == 15000
    order_after = validate_success(api.get_order(order["id"], OPS), 200)
    assert order_after["refunded_cents"] == 15000
    assert order_after["payment_status"] == "REFUNDED"
    assert_refund_conservation(order_after)


def test_amend_resubmit_recomputes_outcome(api):
    """PRD §3.5: "A fresh submission from `AMENDED` recomputes `condition_score`
    and `outcome` from the amended values and returns the report to `SUBMITTED`
    and the order to `REPORTED`."

    Design: Corner/state_machines/report_amend_resubmit_recomputes_outcome
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2012, make="Nissan", model="Frontier")
    insp = create_inspector(certified_tiers=["STANDARD"])
    order, asg, report = create_reported_order(
        acct, veh, fs, insp, report_overrides={"points_total": 100, "points_failed": 5, "road_test_done": False})
    insp_h = make_inspector_headers(insp["id"])
    validate_success(api.amend_report(report["id"], {"points_failed": 40}, insp_h), 200)

    resubmitted = validate_success(api.submit_report(report["id"], insp_h), 200)
    assert resubmitted["condition_score"] == 60.0
    assert resubmitted["outcome"] == "CONDITIONAL"
    assert resubmitted["status"] == "SUBMITTED"
    order_after = validate_success(api.get_order(order["id"], OPS), 200)
    assert order_after["workflow_status"] == "REPORTED"


def test_amend_after_delivery_locked(api):
    """PRD §3.5: "A report may not be amended once the order is `DELIVERED`,
    except through dispute resolution; an amend attempt after delivery is
    rejected with `ERR_REPORT_LOCKED`."

    Design: Corner/state_machines/report_amend_after_delivery_locked
    """
    from test_helpers import validate_error
    ctx = setup_delivered_order(
        account_overrides={"account_type": "INDIVIDUAL", "net_terms_days": 0},
        inspector_overrides={"certified_tiers": ["STANDARD"]},
        order_overrides={"rush_tier": "NONE"},
        pay=True,
    )
    insp_h = make_inspector_headers(ctx["inspector"]["id"])
    res = api.amend_report(ctx["report"]["id"], {"points_failed": 20}, insp_h)
    validate_error(res, "ERR_REPORT_LOCKED")


# ===========================================================================
# Queue B — cross_cutting_concerns (OCC) corner instances
# ===========================================================================
def test_occ_stale_order_version_rejected(api):
    """PRD §2.7: "If `expected_order_version` does not equal the order's current
    `version` at the moment the offer is processed, the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_concerns/occ_stale_order_version_rejected
    """
    from test_helpers import validate_error
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2017, make="Chevy", model="Malibu")
    insp = create_inspector(certified_tiers=["STANDARD"])
    order = create_draft_order(acct, veh, fs, rush_tier="NONE")
    stale_version = order["version"]
    # first offer succeeds and bumps order version
    offer_assignment(order, insp, expected_order_version=stale_version)

    res = api.create_assignment({
        "order_id": order["id"], "inspector_id": insp["id"],
        "window_start": "2026-06-03T09:00:00Z", "window_end": "2026-06-03T11:00:00Z",
        "dispatch_miles": 10, "expected_order_version": stale_version,
    }, OPS)
    validate_error(res, "ERR_STALE_VERSION")


def test_occ_order_version_increments_on_each_mutation(api):
    """PRD §2.6: "When that happens, every affected resource has its `updated_at`
    refreshed and its `version` incremented (for resources that carry those
    fields)." PRD §3.4: "When all checks pass, the assignment moves to `ACCEPTED`
    and cascades the order from `DRAFT` to `DISPATCHED`, incrementing the order's
    `version`."

    Design: Corner/cross_cutting_concerns/occ_version_increments_on_each_mutation
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2017, make="Chevy", model="Malibu")
    insp = create_inspector(certified_tiers=["STANDARD"])
    order = create_draft_order(acct, veh, fs, rush_tier="NONE")
    assert order["version"] == 1
    asg = offer_assignment(order, insp)

    accepted = validate_success(api.accept_assignment(asg["id"], make_inspector_headers(insp["id"])), 200)
    assert accepted["status"] == "ACCEPTED"
    order_after = validate_success(api.get_order(order["id"], OPS), 200)
    assert order_after["workflow_status"] == "DISPATCHED"
    assert order_after["version"] == 3


# ===========================================================================
# Queue B — consistency_model corner instance
# ===========================================================================
def test_estimated_fee_returned_in_create_response(api):
    """PRD §3.2: "The forward-looking quote, `estimated_fee_cents`, is computed
    at creation assuming the order will be delivered on time."

    Design: Corner/consistency_model/immediate_visibility_estimated_fee_in_create_response
    """
    fs = create_fee_schedule(tier_code="STANDARD", base_fee_cents=15000,
                             vin_history_fee_cents=3000, per_mile_dispatch_cents=100)
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2017, make="Chevy", model="Malibu")
    from test_helpers import create_order_payload, make_account_holder_headers
    res = api.create_order(
        create_order_payload(acct["id"], veh["id"], fs["id"], rush_tier="NONE"),
        make_account_holder_headers(acct["id"]))
    created = validate_success(res, 201)
    assert created["estimated_fee_cents"] == 15000
