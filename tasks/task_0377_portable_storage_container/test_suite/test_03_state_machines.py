"""State-machine transition tests (valid, invalid, terminal lockdown) and the
business-rule error families (PRD §3.2, §3.5)."""
from test_helpers import (
    validate_success, validate_error,
    create_rental_agreement_payload, create_protection_plan_payload,
    create_move_order_payload, reserve_payload, payment_payload,
    TEST_USERS, make_customer_headers,
)
from test_helpers import fixtures as F

PA = TEST_USERS["platform_admin_headers"]
DO = TEST_USERS["dispatch_operator_headers"]
BC = TEST_USERS["billing_clerk_headers"]


def test_hold_from_quoted_invalid_state(api):
    """PRD §3.5: "it advances `lifecycle_status` from `ACTIVE` to `ON_HOLD` and is permitted
    only when the agreement is `ACTIVE`."

    Design: Corner/state_machines/hold_from_quoted_returns_invalid_state
    """
    F.create_container_model(size_code="C16")
    depot = F.create_depot()
    F.create_depot_inventory(depot["id"], size_code="C16", total_units=1)
    cust = F.create_customer(email="qh@x.com")
    ag = validate_success(api.create_rental_agreement(
        create_rental_agreement_payload(cust["id"], depot["id"], size_code="C16"), DO), 201)

    res = api.hold_agreement(ag["id"], make_customer_headers(cust["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_cancel_from_cancelled_terminal_lockdown(api):
    """PRD §3.2: "A `QUOTED` or `RESERVED` agreement may be cancelled by its owning
    `Customer`. Cancelling moves `lifecycle_status` to `CANCELLED`."

    Design: Corner/state_machines/cancel_from_cancelled_terminal_lockdown
    """
    F.create_container_model(size_code="C16")
    depot = F.create_depot()
    F.create_depot_inventory(depot["id"], size_code="C16", total_units=1)
    cust = F.create_customer(email="cc@x.com")
    cust_headers = make_customer_headers(cust["id"])
    ag = validate_success(api.create_rental_agreement(
        create_rental_agreement_payload(cust["id"], depot["id"], size_code="C16"), DO), 201)
    validate_success(api.cancel_agreement(ag["id"], cust_headers), 200)

    res = api.cancel_agreement(ag["id"], cust_headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_successful_closeout_full_lifecycle(api):
    """PRD §3.5: "Closing advances `lifecycle_status` from `CLOSING` to `CLOSED` ... On a
    successful close, the container advances `RETURNED → RELEASED`, the inventory row's
    `committed_units` is decremented by 1 and `available_units` recomputed (restoring the
    pool), and the customer's `open_balance_cents` is recomputed."

    Design: Corner/state_machines/successful_closeout_full_lifecycle
    """
    world, ag, unit = F.setup_closing_unit_returned(tier_code="NONE")

    close_res = api.close_agreement(ag["id"], BC)
    closed = validate_success(close_res, 200)
    assert closed["lifecycle_status"] == "CLOSED"

    unit_after = validate_success(api.get_container_unit(unit["id"], DO), 200)
    assert unit_after["status"] == "RELEASED"

    inv = validate_success(api.get_depot_inventory(world["inventory"]["id"], DO), 200)
    assert inv["committed_units"] == 0
    assert inv["available_units"] == 1


def test_error_inventory_row_missing_on_reserve(api):
    """PRD §3.2: "the matching `DepotInventory` row for the agreement's `depot_id` and
    `size_code` must exist, or the request fails with `ERR_INVENTORY_ROW_MISSING`."

    Design: Corner/validations/error_inventory_row_missing_on_reserve
    """
    F.set_clock()
    F.create_container_model(size_code="C12", cubic_feet=600, monthly_rate_cents=14900,
                             delivery_fee_cents=7900, footprint_sqft=120)
    F.create_container_model(size_code="C16")
    depot = F.create_depot()
    F.create_depot_inventory(depot["id"], size_code="C16", total_units=1)  # only C16 stocked
    cust = F.create_customer(email="im@x.com")
    ag = validate_success(api.create_rental_agreement(
        create_rental_agreement_payload(cust["id"], depot["id"], size_code="C12"), DO), 201)

    res = api.reserve_agreement(ag["id"], reserve_payload(ag["version"]), DO)
    validate_error(res, "ERR_INVENTORY_ROW_MISSING")


def test_error_declared_value_over_cap_on_reserve(api):
    """PRD §3.2: "the declared value must fit the selected tier: `declared_value_cents` must
    be at or below the selected `ProtectionPlan`'s `coverage_cap_cents`, otherwise the
    reserve is rejected with `ERR_DECLARED_VALUE_OVER_CAP`."

    Design: Corner/validations/error_declared_value_over_cap_on_reserve
    """
    F.set_clock()
    F.create_container_model(size_code="C16")
    F.create_protection_plan(tier_code="BASIC", base_premium_cents=1000, rate_bps=50,
                             min_premium_cents=1500, coverage_cap_cents=5000000)
    depot = F.create_depot()
    F.create_depot_inventory(depot["id"], size_code="C16", total_units=1)
    cust = F.create_customer(email="ov@x.com")
    ag = validate_success(api.create_rental_agreement(
        create_rental_agreement_payload(
            cust["id"], depot["id"], size_code="C16",
            protection_tier_code="BASIC", declared_value_cents=9000000), DO), 201)

    res = api.reserve_agreement(ag["id"], reserve_payload(ag["version"]), DO)
    validate_error(res, "ERR_DECLARED_VALUE_OVER_CAP")


def test_error_open_logistics_on_request_closeout(api):
    """PRD §3.5: "it is blocked while logistics are still open: if any move order for the
    agreement is `SCHEDULED` or `IN_TRANSIT`, or any delivery job for the agreement is
    `SCHEDULED`, the request is rejected with `ERR_OPEN_LOGISTICS`."

    Design: Corner/validations/error_open_logistics_on_request_closeout
    """
    world, ag, unit = F.setup_active_agreement(tier_code="NONE", with_truck=True)
    F.schedule_move(world, ag, unit, destination_state_code="CA", distance_miles=30)

    res = api.request_closeout(ag["id"], make_customer_headers(world["customer"]["id"]))
    validate_error(res, "ERR_OPEN_LOGISTICS")


def test_error_billing_not_current_on_hold(api):
    """PRD §3.5: "an agreement whose `billing_status` is `PAST_DUE` or `DELINQUENT` cannot
    be placed on hold, and such a request is rejected with `ERR_BILLING_NOT_CURRENT`; only
    an agreement whose `billing_status` is `CURRENT` may go on hold."

    Design: Corner/validations/error_billing_not_current_on_hold
    """
    world, ag, unit = F.setup_past_due_agreement(tier_code="NONE")
    assert ag["billing_status"] == "PAST_DUE"
    assert ag["lifecycle_status"] == "ACTIVE"

    res = api.hold_agreement(ag["id"], make_customer_headers(world["customer"]["id"]))
    validate_error(res, "ERR_BILLING_NOT_CURRENT")


def test_error_outstanding_balance_on_close(api):
    """PRD §3.5: "The fiscal gate uses the final balance variant of §3.8: if
    `balance_due_cents` computed under the final variant is greater than 0, the close is
    rejected with `ERR_OUTSTANDING_BALANCE`".

    Design: Corner/validations/error_outstanding_balance_on_close
    """
    world, ag, unit = F.setup_active_agreement(tier_code="NONE")
    cust_id = world["customer"]["id"]
    F.request_closeout(ag, cust_id)          # CLOSING, balance still 19171 (unpaid)
    F.return_unit(unit["id"])                # RETURNED

    res = api.close_agreement(ag["id"], BC)
    validate_error(res, "ERR_OUTSTANDING_BALANCE")
