"""State-machine preconditions, invalid/valid transitions, terminal lockdown,
and shift side effects.

Covers corner queue B section: state_machines.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_campaign, add_prize_tier, add_seller,
    setup_active_catalog, setup_active_pledge, setup_active_event,
    place_simple_order, place_and_pay_order, create_pledge,
    add_volunteer, add_shift, book_shift,
    close_campaign, reconcile_campaign, disburse_campaign,
    TEST_USERS,
)

ADMIN = TEST_USERS["campaign_admin_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


def test_activate_without_seller_returns_invalid_state(api, admin_headers):
    """PRD §3.1: "Activation is permitted only when the campaign has at least one
    `Seller` on its roster, and either has at least one `PrizeTier` defined or
    is of type `EVENT` (events need no prize tiers). If those preconditions
    are not met, the activation is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/activate_without_seller_returns_invalid_state
    """
    camp = create_campaign(campaign_type="CATALOG")
    add_prize_tier(camp["id"], label="T1", threshold_cents=5000)  # tier but no seller
    res = api.activate_campaign(camp["id"], admin_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_confirm_order_before_paid_returns_invalid_state(api, admin_headers):
    """PRD §3.4: "confirming an order moves `fulfillment_status` from `PLACED` to
    `CONFIRMED`; it is permitted only when the campaign is `ACTIVE` and the
    order is already `PAID`"

    Design: Corner/state_machines/confirm_order_before_paid_returns_invalid_state
    """
    camp, seller, product = setup_active_catalog()
    order = place_simple_order(camp["id"], seller["id"], product["id"], 2)  # PENDING
    res = api.confirm_order(order["id"], admin_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_cancel_already_cancelled_pledge_returns_invalid_state(api, admin_headers):
    """PRD §3.5: "Cancelling a pledge moves it to `CANCELLED` from either
    `PROMISED` or `RECORDED` with no money effect"

    Design: Corner/state_machines/cancel_already_cancelled_pledge_returns_invalid_state
    """
    camp, seller = setup_active_pledge()
    pledge = create_pledge(camp["id"], seller["id"], per_unit_cents=0, flat_cents=2000)
    validate_success(api.cancel_pledge(pledge["id"], admin_headers), 200)
    res = api.cancel_pledge(pledge["id"], admin_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_disburse_from_disbursed_terminal_returns_invalid_state(api):
    """PRD §3.7: "After reconciliation, the `Treasurer` disburses the campaign,
    moving the posture from `RECONCILED` to `DISBURSED`, which is terminal.
    Disbursement requires the campaign to currently be `RECONCILED` (otherwise
    `ERR_INVALID_STATE`, which also bars a second disbursement)"

    Design: Corner/state_machines/disburse_from_disbursed_terminal_returns_invalid_state
    """
    closed = close_campaign(setup_active_pledge()[0]["id"])
    reconciled = reconcile_campaign(closed["id"], closed["version"])
    disbursed = disburse_campaign(closed["id"], reconciled["version"])
    res = api_client.disburse_campaign(
        closed["id"], {"expected_campaign_version": disbursed["version"]}, TREASURER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_reconcile_before_close_returns_invalid_state(api):
    """PRD §3.7: "Reconciliation requires the campaign to currently be `CLOSED`
    (otherwise `ERR_INVALID_STATE`)"

    Design: Corner/state_machines/reconcile_before_close_returns_invalid_state
    """
    camp, _ = setup_active_pledge()
    active = validate_success(api_client.get_campaign(camp["id"], TREASURER), 200)
    res = api_client.reconcile_campaign(
        camp["id"], {"expected_campaign_version": active["version"]}, TREASURER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_cancel_paid_order_returns_paid_order_not_cancellable(api, admin_headers):
    """PRD §3.4: "A cancel is allowed only when the order is not `PAID`: an
    attempt to cancel an order whose `payment_status` is `PAID` is refused
    with `ERR_PAID_ORDER_NOT_CANCELLABLE`, the caller being directed to refund
    it instead."

    Design: Corner/state_machines/cancel_paid_order_returns_paid_order_not_cancellable
    """
    camp, seller, product = setup_active_catalog()
    order = place_and_pay_order(camp["id"], seller["id"], product["id"], 2)
    res = api.cancel_order(order["id"], admin_headers)
    validate_error(res, "ERR_PAID_ORDER_NOT_CANCELLABLE", expected_status=409)


def test_deliver_allowed_after_campaign_closed(api, admin_headers):
    """PRD §3.4: "Delivering an order moves `fulfillment_status` from `CONFIRMED`
    to `DELIVERED`; it is permitted when the order is `PAID` and the campaign
    posture is either `ACTIVE` or `CLOSED`"

    Design: Corner/state_machines/deliver_allowed_after_campaign_closed
    """
    camp, seller, product = setup_active_catalog()
    order = place_and_pay_order(camp["id"], seller["id"], product["id"], 2)
    validate_success(api.confirm_order(order["id"], admin_headers), 200)
    validate_success(api.close_campaign(camp["id"], admin_headers), 200)
    delivered = validate_success(api.deliver_order(order["id"], admin_headers), 200)
    assert delivered["fulfillment_status"] == "DELIVERED"


def test_close_cascade_cancels_open_shift(api, admin_headers):
    """PRD §3.2: "every `VolunteerShift` still `OPEN` is moved to `CANCELLED`."

    Design: Corner/state_machines/close_cascade_open_shift_cancelled
    """
    camp, _ = setup_active_event()
    shift = add_shift(camp["id"], "2026-04-10T09:00:00Z", "2026-04-10T11:00:00Z",
                      role_label="CHECK_IN")
    validate_success(api.close_campaign(camp["id"], admin_headers), 200)
    after = validate_success(api.get_shift(shift["id"], admin_headers), 200)
    assert after["status"] == "CANCELLED", "an OPEN shift must be cancelled on close"


def test_release_booked_shift_recomputes_committed_minutes(api, admin_headers):
    """PRD §3.9: "Releasing a shift moves it from `BOOKED` to `RELEASED` and
    recomputes the volunteer's `committed_minutes` so this shift no longer
    counts."

    Design: Corner/state_machines/release_booked_shift_recomputes_committed_minutes
    """
    camp, _ = setup_active_event()
    volunteer = add_volunteer(camp["id"])
    shift = add_shift(camp["id"], "2026-04-10T09:00:00Z", "2026-04-10T12:00:00Z",
                      role_label="GRILL")
    book_shift(shift["id"], volunteer["id"])
    booked_vol = validate_success(api.get_volunteer(volunteer["id"], admin_headers), 200)
    assert booked_vol["committed_minutes"] == 180

    released = validate_success(api.release_shift(shift["id"], admin_headers), 200)
    assert released["status"] == "RELEASED"
    after = validate_success(api.get_volunteer(volunteer["id"], admin_headers), 200)
    assert after["committed_minutes"] == 0, \
        "releasing the only booked shift drops committed_minutes to 0"
