"""Validation-priority conflicts, cross-entity state dependencies, scheduling
overlap/double-booking, and single-rule business validations.

Queue A (Difficulty): priority_pair_validation_conflict,
cross_entity_state_dependency, resource_temporal_overlap.
Queue B (Corner): validations section.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_delivered_order, set_clock,
    create_fee_schedule, create_account, create_vehicle, create_inspector,
    create_draft_order, create_dispatched_order, create_reported_order,
    offer_assignment, offer_and_accept,
    create_report_for, make_account_holder_headers, make_inspector_headers,
    TEST_USERS,
)

OPS = TEST_USERS["ops_admin_headers"]


# ===========================================================================
# priority_pair_validation_conflict — state vs fiscal on deliver (Queue A)
# ===========================================================================
def test_deliver_draft_unpaid_order_state_error_wins(api):
    """PRD §2.9: "the target resource being in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`); and then the domain-specific
    business rules described in Section 3, which sit below these in priority."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_deliver_cancelled_unpaid
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2014, make="BMW", model="328i")
    order = create_draft_order(acct, veh, fs, rush_tier="NONE")  # DRAFT + UNPAID

    res = api.deliver_order(order["id"], OPS)
    validate_error(res, "ERR_INVALID_STATE")


def test_deliver_draft_unpaid_order_returns_409(api):
    """PRD §3.7: "Delivery requires the order to be in `REPORTED` workflow
    status."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_deliver_cancelled_unpaid
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2014, make="BMW", model="328i")
    order = create_draft_order(acct, veh, fs, rush_tier="NONE")

    res = api.deliver_order(order["id"], OPS)
    assert res.status_code == 409
    validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# priority_pair_validation_conflict — ownership vs state cancel (Queue A)
# ===========================================================================
def test_non_owner_cancel_delivered_order_ownership_error_wins(api):
    """PRD §2.9: "resource ownership for ownership-scoped mutations
    (`ERR_NOT_RESOURCE_OWNER`); (5) request-body well-formedness ...; (7) the
    target resource being in a state from which the requested transition is
    defined (`ERR_INVALID_STATE`)."

    Design: Difficulty/priority_pair_validation_conflict/ownership_vs_state_cancel_other_account_delivered
    """
    ctx = setup_delivered_order(
        account_overrides={"account_type": "INDIVIDUAL", "net_terms_days": 0},
        inspector_overrides={"certified_tiers": ["STANDARD"]},
        order_overrides={"rush_tier": "NONE"},
        pay=True,
    )
    order = ctx["delivered_order"]
    other = create_account(account_type="INDIVIDUAL", net_terms_days=0)

    res = api.cancel_order(order["id"], make_account_holder_headers(other["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


def test_non_owner_cancel_delivered_order_returns_403(api):
    """PRD §2.1: "Ownership violations - for example, an `AccountHolder`
    attempting to cancel another account's order, or an `Inspector` accepting a
    peer's offered assignment - are rejected with `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/ownership_vs_state_cancel_other_account_delivered
    """
    ctx = setup_delivered_order(
        account_overrides={"account_type": "INDIVIDUAL", "net_terms_days": 0},
        inspector_overrides={"certified_tiers": ["STANDARD"]},
        order_overrides={"rush_tier": "NONE"},
        pay=True,
    )
    order = ctx["delivered_order"]
    other = create_account(account_type="INDIVIDUAL", net_terms_days=0)

    res = api.cancel_order(order["id"], make_account_holder_headers(other["id"]))
    assert res.status_code == 403
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


# ===========================================================================
# cross_entity_state_dependency — deliver blocked w/o VIN report (Queue A)
# ===========================================================================
def test_deliver_vin_history_order_without_vin_report_rejected(api):
    """PRD §3.7: "If the order was placed with `include_vin_history` set to true,
    a compiled `VinReport` must exist for the order, otherwise delivery is
    refused with `ERR_VIN_REPORT_MISSING`."

    Design: Difficulty/cross_entity_state_dependency/deliver_blocked_until_vin_report_compiled
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2012, make="Dodge", model="Charger")
    insp = create_inspector(certified_tiers=["STANDARD"])
    order, asg, report = create_reported_order(
        acct, veh, fs, insp, order_overrides={"include_vin_history": True, "rush_tier": "NONE"})
    # PAID but no VinReport compiled
    validate_success(api.pay_order(order["id"], make_account_holder_headers(acct["id"])), 200)

    res = api.deliver_order(order["id"], OPS)
    validate_error(res, "ERR_VIN_REPORT_MISSING")


def test_deliver_vin_history_order_without_vin_report_returns_409(api):
    """PRD §5 (error catalogue) names `ERR_VIN_REPORT_MISSING` at HTTP 409, and
    PRD §3.7: "otherwise delivery is refused with `ERR_VIN_REPORT_MISSING`."

    Design: Difficulty/cross_entity_state_dependency/deliver_blocked_until_vin_report_compiled
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2012, make="Dodge", model="Charger")
    insp = create_inspector(certified_tiers=["STANDARD"])
    order, asg, report = create_reported_order(
        acct, veh, fs, insp, order_overrides={"include_vin_history": True, "rush_tier": "NONE"})
    validate_success(api.pay_order(order["id"], make_account_holder_headers(acct["id"])), 200)

    res = api.deliver_order(order["id"], OPS)
    assert res.status_code == 409


# ===========================================================================
# cross_entity_state_dependency — report needs accepted assignment (Queue A)
# ===========================================================================
def test_report_create_without_accepted_assignment_rejected(api):
    """PRD §3.5: "Creating a report requires that an `ACCEPTED` assignment exists
    for the order, otherwise the create is rejected with
    `ERR_NO_ACCEPTED_ASSIGNMENT`."

    Design: Difficulty/cross_entity_state_dependency/report_create_blocked_without_accepted_assignment
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2015, make="Hyundai", model="Sonata")
    insp = create_inspector(certified_tiers=["STANDARD"])
    order = create_draft_order(acct, veh, fs, rush_tier="NONE")
    asg = offer_assignment(order, insp)  # OFFERED, never accepted

    res = api.create_report({
        "order_id": order["id"], "assignment_id": asg["id"],
        "odometer_reading": 10000, "points_total": 100, "points_failed": 5, "road_test_done": True,
    }, make_inspector_headers(insp["id"]))
    validate_error(res, "ERR_NO_ACCEPTED_ASSIGNMENT")


def test_report_create_without_accepted_assignment_returns_409(api):
    """PRD §5 (error catalogue) names `ERR_NO_ACCEPTED_ASSIGNMENT` at HTTP 409,
    and PRD §3.5: "otherwise the create is rejected with
    `ERR_NO_ACCEPTED_ASSIGNMENT`."

    Design: Difficulty/cross_entity_state_dependency/report_create_blocked_without_accepted_assignment
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2015, make="Hyundai", model="Sonata")
    insp = create_inspector(certified_tiers=["STANDARD"])
    order = create_draft_order(acct, veh, fs, rush_tier="NONE")
    asg = offer_assignment(order, insp)

    res = api.create_report({
        "order_id": order["id"], "assignment_id": asg["id"],
        "odometer_reading": 10000, "points_total": 100, "points_failed": 5, "road_test_done": True,
    }, make_inspector_headers(insp["id"]))
    assert res.status_code == 409


# ===========================================================================
# resource_temporal_overlap — inspector window overlap half-open (Queue A)
# ===========================================================================
def test_inspector_window_overlap_rejected(api):
    """PRD §3.4: "The new window must not overlap the `[window_start,
    window_end)` window of any other `ACCEPTED` assignment held by the same
    inspector. Because the interval is half-open, two windows that merely touch
    at an endpoint - where one window's end equals the next window's start - do
    not collide. A genuine overlap is rejected with `ERR_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/inspector_window_overlap_half_open
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh_a = create_vehicle(year=2013, make="Ford", model="F150")
    veh_b = create_vehicle(year=2013, make="Ford", model="F250")
    insp = create_inspector(certified_tiers=["STANDARD"], max_daily_jobs=5)

    order_a = create_draft_order(acct, veh_a, fs, rush_tier="NONE")
    _, order_a = offer_and_accept(order_a, insp,
                                  window_start="2026-06-02T09:00:00Z",
                                  window_end="2026-06-02T11:00:00Z")
    order_b = create_draft_order(acct, veh_b, fs, rush_tier="NONE")
    asg_b = offer_assignment(order_b, insp,
                             window_start="2026-06-02T10:00:00Z",
                             window_end="2026-06-02T12:00:00Z")  # overlaps [09,11)

    res = api.accept_assignment(asg_b["id"], make_inspector_headers(insp["id"]))
    validate_error(res, "ERR_WINDOW_OVERLAP")


def test_inspector_touching_windows_do_not_collide(api):
    """PRD §3.4: "two windows that merely touch at an endpoint - where one
    window's end equals the next window's start - do not collide."

    Design: Difficulty/resource_temporal_overlap/inspector_window_overlap_half_open
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh_a = create_vehicle(year=2013, make="Ford", model="F150")
    veh_b = create_vehicle(year=2013, make="Ford", model="F250")
    insp = create_inspector(certified_tiers=["STANDARD"], max_daily_jobs=5)

    order_a = create_draft_order(acct, veh_a, fs, rush_tier="NONE")
    _, order_a = offer_and_accept(order_a, insp,
                                  window_start="2026-06-02T09:00:00Z",
                                  window_end="2026-06-02T11:00:00Z")
    order_b = create_draft_order(acct, veh_b, fs, rush_tier="NONE")
    asg_b = offer_assignment(order_b, insp,
                             window_start="2026-06-02T11:00:00Z",  # touches a.end
                             window_end="2026-06-02T13:00:00Z")

    accepted = validate_success(api.accept_assignment(asg_b["id"], make_inspector_headers(insp["id"])), 200)
    assert accepted["status"] == "ACCEPTED"


# ===========================================================================
# resource_temporal_overlap — vehicle double-booked closed interval (Queue A)
# ===========================================================================
def test_vehicle_touching_windows_double_booked(api):
    """PRD §3.4: "The same vehicle (the order's `vehicle_id`) must not have
    another `ACCEPTED` assignment whose window collides under closed-interval
    semantics, where touching endpoints *do* collide - the same car cannot be
    present at two back-to-back appointments. A collision here is rejected with
    `ERR_VEHICLE_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/vehicle_double_booked_closed_interval_touching
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2006, make="Chevy", model="Corvette")
    insp1 = create_inspector(certified_tiers=["STANDARD"], max_daily_jobs=5)
    insp2 = create_inspector(certified_tiers=["STANDARD"], max_daily_jobs=5)

    order_a = create_draft_order(acct, veh, fs, rush_tier="NONE")
    _, order_a = offer_and_accept(order_a, insp1,
                                  window_start="2026-06-02T09:00:00Z",
                                  window_end="2026-06-02T11:00:00Z")
    order_b = create_draft_order(acct, veh, fs, rush_tier="NONE")
    asg_b = offer_assignment(order_b, insp2,
                             window_start="2026-06-02T11:00:00Z",  # touches a.end -> collides for vehicle
                             window_end="2026-06-02T13:00:00Z")

    res = api.accept_assignment(asg_b["id"], make_inspector_headers(insp2["id"]))
    validate_error(res, "ERR_VEHICLE_DOUBLE_BOOKED")


def test_vehicle_double_booked_returns_409(api):
    """PRD §5 (error catalogue) names `ERR_VEHICLE_DOUBLE_BOOKED` at HTTP 409,
    and PRD §3.4: "A collision here is rejected with
    `ERR_VEHICLE_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/vehicle_double_booked_closed_interval_touching
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2006, make="Chevy", model="Corvette")
    insp1 = create_inspector(certified_tiers=["STANDARD"], max_daily_jobs=5)
    insp2 = create_inspector(certified_tiers=["STANDARD"], max_daily_jobs=5)

    order_a = create_draft_order(acct, veh, fs, rush_tier="NONE")
    _, order_a = offer_and_accept(order_a, insp1,
                                  window_start="2026-06-02T09:00:00Z",
                                  window_end="2026-06-02T11:00:00Z")
    order_b = create_draft_order(acct, veh, fs, rush_tier="NONE")
    asg_b = offer_assignment(order_b, insp2,
                             window_start="2026-06-02T11:00:00Z",
                             window_end="2026-06-02T13:00:00Z")

    res = api.accept_assignment(asg_b["id"], make_inspector_headers(insp2["id"]))
    assert res.status_code == 409


# ===========================================================================
# Queue B — validations corner instances
# ===========================================================================
def test_create_order_on_suspended_account_rejected(api):
    """PRD §3.2: "Creation is refused with `ERR_ACCOUNT_SUSPENDED` if the
    ordering account is not `ACTIVE`."

    Design: Corner/validations/create_order_on_suspended_account_rejected
    """
    from test_helpers import create_order_payload
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2015, make="Chevy", model="Malibu")
    validate_success(api.suspend_account(acct["id"], OPS), 200)

    res = api.create_order(
        create_order_payload(acct["id"], veh["id"], fs["id"], rush_tier="NONE"),
        make_account_holder_headers(acct["id"]))
    validate_error(res, "ERR_ACCOUNT_SUSPENDED")


def test_invoice_individual_account_not_eligible(api):
    """PRD §3.3: "Invoicing is permitted only when the account's `net_terms_days`
    is greater than zero; an attempt to invoice an account with zero net terms is
    rejected with `ERR_INVOICE_NOT_ELIGIBLE`."

    Design: Corner/validations/invoice_individual_account_not_eligible
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2006, make="Chevy", model="Malibu")
    order = create_draft_order(acct, veh, fs, rush_tier="NONE")

    res = api.invoice_order(order["id"], OPS)
    validate_error(res, "ERR_INVOICE_NOT_ELIGIBLE")


def test_fail_report_without_critical_photo_rejected(api):
    """PRD §3.5: "submission of a report whose computed outcome would be `FAIL` is
    refused with `ERR_CRITICAL_PHOTO_REQUIRED` unless at least one critical photo
    is attached."

    Design: Corner/validations/fail_report_without_critical_photo_rejected
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2008, make="Chevy", model="Impala")
    insp = create_inspector(certified_tiers=["STANDARD"])
    order, asg = create_dispatched_order(acct, veh, fs, insp)
    report = create_report_for(order, asg, points_total=100, points_failed=60, road_test_done=False)

    res = api.submit_report(report["id"], make_inspector_headers(insp["id"]))
    validate_error(res, "ERR_CRITICAL_PHOTO_REQUIRED")


def test_tier_not_certified_on_accept_rejected(api):
    """PRD §3.4: "The order's fee-schedule `tier_code` must appear in the
    inspector's `certified_tiers`, otherwise the acceptance is refused with
    `ERR_TIER_NOT_CERTIFIED`."

    Design: Corner/validations/tier_not_certified_on_accept_rejected
    """
    fs = create_fee_schedule(tier_code="HEAVY_DUTY", base_fee_cents=40000,
                             vin_history_fee_cents=5000, per_mile_dispatch_cents=200)
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2014, make="Ram", model="3500")
    insp = create_inspector(certified_tiers=["STANDARD"])
    order = create_draft_order(acct, veh, fs, rush_tier="NONE")
    asg = offer_assignment(order, insp)

    res = api.accept_assignment(asg["id"], make_inspector_headers(insp["id"]))
    validate_error(res, "ERR_TIER_NOT_CERTIFIED")


def test_offline_inspector_accept_rejected(api):
    """PRD §3.4: "The inspector's `status` must be `AVAILABLE`, otherwise the
    acceptance is refused with `ERR_INSPECTOR_OFFLINE`."

    Design: Corner/validations/offline_inspector_accept_rejected
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2013, make="Ford", model="Taurus")
    insp = create_inspector(certified_tiers=["STANDARD"])
    order = create_draft_order(acct, veh, fs, rush_tier="NONE")
    asg = offer_assignment(order, insp)
    insp_h = make_inspector_headers(insp["id"])
    validate_success(api.set_inspector_status(insp["id"], {"status": "OFFLINE"}, insp_h), 200)

    res = api.accept_assignment(asg["id"], insp_h)
    validate_error(res, "ERR_INSPECTOR_OFFLINE")


def test_empty_report_submit_rejected(api):
    """PRD §3.5: "It first requires `points_total` to be at least 1, otherwise it
    is refused with `ERR_EMPTY_REPORT`."

    Design: Corner/validations/empty_report_submit_rejected
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2000, make="Honda", model="Accord")
    insp = create_inspector(certified_tiers=["STANDARD"])
    order, asg = create_dispatched_order(acct, veh, fs, insp)
    report = create_report_for(order, asg, odometer_reading=100000,
                               points_total=0, points_failed=0, road_test_done=False)

    res = api.submit_report(report["id"], make_inspector_headers(insp["id"]))
    validate_error(res, "ERR_EMPTY_REPORT")


def test_daily_cap_exceeded_second_accept_rejected(api):
    """PRD §3.4: "Finally, the inspector's count of `ACCEPTED` assignments whose
    `window_start` falls on the same UTC calendar date as the new window must be
    strictly below `max_daily_jobs`; reaching the cap rejects the acceptance with
    `ERR_DAILY_CAP_EXCEEDED`."

    Design: Corner/validations/daily_cap_exceeded_third_accept_rejected
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh_a = create_vehicle(year=2018, make="Ford", model="F150")
    veh_b = create_vehicle(year=2018, make="Ford", model="F250")
    insp = create_inspector(certified_tiers=["STANDARD"], max_daily_jobs=1)

    order_a = create_draft_order(acct, veh_a, fs, rush_tier="NONE")
    offer_and_accept(order_a, insp,
                     window_start="2026-06-02T09:00:00Z", window_end="2026-06-02T10:00:00Z")
    order_b = create_draft_order(acct, veh_b, fs, rush_tier="NONE")
    asg_b = offer_assignment(order_b, insp,
                             window_start="2026-06-02T12:00:00Z", window_end="2026-06-02T13:00:00Z")

    res = api.accept_assignment(asg_b["id"], make_inspector_headers(insp["id"]))
    validate_error(res, "ERR_DAILY_CAP_EXCEEDED")


def test_deliver_unpaid_reported_order_payment_required(api):
    """PRD §3.7: "It requires the order's `payment_status` to be either `PAID` or
    `INVOICED`, otherwise it is refused with `ERR_PAYMENT_REQUIRED`."

    Design: Corner/validations/deliver_unpaid_reported_order_payment_required
    """
    fs = create_fee_schedule()
    acct = create_account(account_type="INDIVIDUAL", net_terms_days=0)
    veh = create_vehicle(year=2013, make="Ram", model="1500")
    insp = create_inspector(certified_tiers=["STANDARD"])
    order, asg, report = create_reported_order(acct, veh, fs, insp,
                                               order_overrides={"rush_tier": "NONE"})
    # REPORTED but UNPAID, no vin history -> only fiscal rule fails

    res = api.deliver_order(order["id"], OPS)
    validate_error(res, "ERR_PAYMENT_REQUIRED")
