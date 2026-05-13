"""Exercise application lifecycle: submit, verify, pay, settle, reject,
cancel (PRD §3.8)."""
from __future__ import annotations

import datetime as _dt

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_by_seconds,
    assert_exercise_application,
    create_exercise_application_payload,
    drive_app_to_tax_withheld_cash,
    drive_app_to_tax_withheld_share,
    get_tip_price_version,
    make_grantee_headers,
    pay_application_payload,
    settle_app_cash,
    settle_app_share,
    settle_application_cash_payload,
    settle_application_share_payload,
    setup_live_grant_with_open_window,
    submit_exercise_application,
    validate_error,
    validate_success,
)


def _qty_within_vested(grant: dict, default: int = 50) -> int:
    """Return a quantity that is within vested - exercised; falls back
    to `default` if no vested options yet."""
    avail = grant.get("vested_quantity", 0) - grant.get("exercised_quantity", 0)
    return min(default, max(avail, 1))


def test_submit_application_in_submitted(api, plan_admin_headers):
    """PRD §3.8: "The new application is created with status SUBMITTED..."
    """
    setup = setup_live_grant_with_open_window(
        cliff_months=12, vesting_total_months=48, vesting_period_months=3,
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = validate_success(api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ), expected_status=200)
    qty = _qty_within_vested(grant, default=50)
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="SHARE_ISSUANCE",
    )
    assert_exercise_application(app)
    assert app["status"] == "SUBMITTED"


def test_submit_rejected_on_stale_price_version(api, plan_admin_headers):
    """PRD §3.8: "The submitted pinned_price_version_id must equal the
    current tip of the batch's price-version chain at submission
    instant; if a corporate-event repricing has bumped the chain since
    the grantee last read, the submission is rejected with
    ERR_STALE_PRICE_VERSION."
    """
    from test_helpers import create_stock_split
    setup = setup_live_grant_with_open_window(
        quantity=1200, advance_clock_months_after_grant=15,
    )
    plan = setup["plan"]
    grant = setup["grant"]
    # Bump the chain.
    create_stock_split(
        plan["id"], plan["current_clock_ts"], numerator=2, denominator=1,
    )
    # Submit with the OLD pinned id (which was the tip at sign-agreement).
    res = api.create_exercise_application(
        grant["id"],
        create_exercise_application_payload(
            window_id=setup["window"]["id"],
            pinned_price_version_id=grant["pinned_price_version_id"],
            requested_quantity=10,
            settlement_mode="SHARE_ISSUANCE",
        ),
        make_grantee_headers(setup["grantee"]["hr_employee_id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_PRICE_VERSION.value)


def test_verify_cash_cascades_to_tax_withheld(api, plan_admin_headers):
    """PRD §3.8: "For CASH_SETTLEMENT applications, verification cascades
    immediately into the ELIGIBILITY_VERIFIED → TAX_WITHHELD transition,
    which runs the withholding-tax calculation and pins both
    TaxEventRecord and the application's withholding_tax_cents."
    """
    setup = setup_live_grant_with_open_window(
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = validate_success(api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ), expected_status=200)
    qty = _qty_within_vested(grant, default=80)
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="CASH_SETTLEMENT",
    )
    after = drive_app_to_tax_withheld_cash(app)
    assert after["status"] == "TAX_WITHHELD"
    assert isinstance(after.get("withholding_tax_cents"), int)


def test_verify_share_requires_pay_for_tax_withheld(api, plan_admin_headers):
    """PRD §3.8: "For SHARE_ISSUANCE applications, the administrator
    must first record payment by supplying a non-empty payment_reference
    ... which transitions the application from ELIGIBILITY_VERIFIED to
    PAYMENT_RECEIVED ... Immediately after PAYMENT_RECEIVED, the system
    auto-transitions to TAX_WITHHELD..."
    """
    setup = setup_live_grant_with_open_window(
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = validate_success(api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ), expected_status=200)
    qty = _qty_within_vested(grant, default=80)
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="SHARE_ISSUANCE",
    )
    after = drive_app_to_tax_withheld_share(app, payment_reference="BK-1")
    assert after["status"] == "TAX_WITHHELD"


def test_pay_on_cash_settlement_rejected(api, plan_admin_headers):
    """PRD §3.8: "Invoking the payment-record capability on a
    CASH_SETTLEMENT application yields ERR_INVALID_REQUEST because the
    cash branch skips that transition entirely."
    """
    setup = setup_live_grant_with_open_window(
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = validate_success(api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ), expected_status=200)
    qty = _qty_within_vested(grant, default=50)
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="CASH_SETTLEMENT",
    )
    # CASH cascades on verify directly to TAX_WITHHELD — calling /pay
    # is an invalid request.
    drive_app_to_tax_withheld_cash(app)
    res = api.pay_exercise_application(
        app["id"], pay_application_payload("BK-X"), plan_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_settle_share_requires_share_registry_reference(api,
                                                        plan_admin_headers):
    """PRD §3.8: "For SHARE_ISSUANCE, the settlement request must carry
    a share_registry_reference (otherwise ERR_INVALID_REQUEST)..."
    """
    setup = setup_live_grant_with_open_window(
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = validate_success(api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ), expected_status=200)
    qty = _qty_within_vested(grant, default=50)
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="SHARE_ISSUANCE",
    )
    drive_app_to_tax_withheld_share(app, payment_reference="BK-2")
    # Settle without share_registry_reference.
    res = api.settle_exercise_application(
        app["id"], {}, plan_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_settle_cash_requires_payment_reference(api, plan_admin_headers):
    """PRD §3.8: "for CASH_SETTLEMENT, it must carry a payment_reference
    (otherwise ERR_INVALID_REQUEST)."
    """
    setup = setup_live_grant_with_open_window(
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = validate_success(api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ), expected_status=200)
    qty = _qty_within_vested(grant, default=50)
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="CASH_SETTLEMENT",
    )
    drive_app_to_tax_withheld_cash(app)
    res = api.settle_exercise_application(
        app["id"], {}, plan_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_settle_share_increases_exercised_and_drops_pool(api,
                                                         plan_admin_headers):
    """PRD §3.8: "Settlement increases Grant.exercised_quantity by
    requested_quantity, decreases plan.pool_reserved_options by the same
    amount..."
    """
    setup = setup_live_grant_with_open_window(
        quantity=1200, advance_clock_months_after_grant=15,
    )
    plan = setup["plan"]
    grant_before = validate_success(api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ), expected_status=200)
    plan_before = validate_success(api.get_option_plan(
        plan["id"], plan_admin_headers,
    ), expected_status=200)
    qty = _qty_within_vested(grant_before, default=50)
    app = submit_exercise_application(
        grant_before, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="SHARE_ISSUANCE",
    )
    drive_app_to_tax_withheld_share(app, payment_reference="BK-3")
    settle_app_share(app["id"], "SR-X")
    grant_after = validate_success(api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ), expected_status=200)
    plan_after = validate_success(api.get_option_plan(
        plan["id"], plan_admin_headers,
    ), expected_status=200)
    assert (
        grant_after["exercised_quantity"]
        == grant_before["exercised_quantity"] + qty
    )
    assert (
        plan_after["pool_reserved_options"]
        == plan_before["pool_reserved_options"] - qty
    )


def test_gross_proceeds_equals_qty_times_pinned_price(api,
                                                     plan_admin_headers):
    """PRD §3.8: "gross_proceeds_cents is always requested_quantity
    multiplied by the pinned version's price_per_option_cents — a single
    multiplication, no per-line rounding."
    """
    setup = setup_live_grant_with_open_window(
        initial_price_per_option_cents=5000,
        quantity=1200,
        advance_clock_months_after_grant=15,
    )
    grant = validate_success(api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ), expected_status=200)
    qty = _qty_within_vested(grant, default=50)
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="SHARE_ISSUANCE",
    )
    after = drive_app_to_tax_withheld_share(app, payment_reference="BK-4")
    assert after["gross_proceeds_cents"] == qty * 5000


def test_cancel_application_by_grantee(api, plan_admin_headers):
    """PRD §3.8: "The grantee may cancel their own SUBMITTED application
    themselves..."
    """
    setup = setup_live_grant_with_open_window(
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = validate_success(api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ), expected_status=200)
    qty = _qty_within_vested(grant, default=30)
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="SHARE_ISSUANCE",
    )
    cancel = validate_success(api.cancel_exercise_application(
        app["id"], make_grantee_headers(setup["grantee"]["hr_employee_id"]),
    ), expected_status=200)
    assert cancel["status"] == "CANCELLED"


def test_reject_application_from_submitted(api, plan_admin_headers):
    """PRD §3.8: "an administrator may reject a SUBMITTED or
    ELIGIBILITY_VERIFIED application with an optional reason field."
    """
    setup = setup_live_grant_with_open_window(
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = validate_success(api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ), expected_status=200)
    qty = _qty_within_vested(grant, default=30)
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="SHARE_ISSUANCE",
    )
    res = api.reject_exercise_application(
        app["id"], plan_admin_headers, {"reason": "test reject"},
    )
    after = validate_success(res, expected_status=200)
    assert after["status"] == "REJECTED"


def test_submitted_application_can_be_rejected(api, plan_admin_headers):
    """PRD §3.8: "an administrator may reject a SUBMITTED or
    ELIGIBILITY_VERIFIED application..." Confirms /reject succeeds on
    SUBMITTED with no payload at all (reason is optional).
    """
    setup = setup_live_grant_with_open_window(
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = validate_success(api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ), expected_status=200)
    qty = _qty_within_vested(grant, default=20)
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="SHARE_ISSUANCE",
    )
    res = api.reject_exercise_application(app["id"], plan_admin_headers, {})
    after = validate_success(res, expected_status=200)
    assert after["status"] == "REJECTED"
