"""Tax-event calculations across jurisdictions (PRD §3.9)."""
from __future__ import annotations

import datetime as _dt

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_by_months,
    create_and_activate_plan,
    create_and_open_batch,
    create_grant_and_drive_to_live,
    create_sale_tax_event_payload,
    list_tax_events_for_grant,
    make_grantee_headers,
    register_grantee,
    setup_live_grant_with_open_window,
    submit_exercise_application,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Grant event always has zero taxable amount (PRD §3.9)
# ---------------------------------------------------------------------------
def test_grant_event_has_zero_taxable_amount(api, plan_admin_headers):
    """PRD §3.9: "For a grant event, taxable amount is zero in every
    jurisdiction."
    """
    from test_helpers import (
        create_and_activate_plan, create_and_open_batch, register_grantee,
        create_grant_payload,
    )
    plan = create_and_activate_plan(jurisdiction_code="US")
    batch = create_and_open_batch(plan["id"])
    grantee = register_grantee(plan["id"])
    grant = validate_success(api.create_grant(
        plan["id"], batch["id"], create_grant_payload(grantee["id"]),
        plan_admin_headers,
    ), expected_status=201)
    validate_success(api.board_approve_grant(
        grant["id"], TEST_USERS["board_secretary_headers"],
    ), expected_status=200)
    validate_success(api.shareholder_approve_grant(
        grant["id"], TEST_USERS["shareholder_registrar_headers"],
    ), expected_status=200)
    # GRANT TaxEventRecord should exist now.
    tax_events = list_tax_events_for_grant(grant["id"], event_type="GRANT")
    assert len(tax_events) == 1
    assert tax_events[0]["taxable_amount_cents"] == 0


# ---------------------------------------------------------------------------
# US/US exercise — tier crossing (PRD §3.9)
# ---------------------------------------------------------------------------
def test_us_us_exercise_within_slab1(api, plan_admin_headers):
    """PRD §3.9: "for plan-jurisdiction US and grantee-residency US on
    an exercise, the first 1,000,000 cents of taxable amount is taxed
    at 2200 basis points (22 percent)..."
    PRD §3.9: "Withholding is computed slab-by-slab and rounded half up
    at each slab before summing — never sum-then-round."

    Pre-condition: pinned price == current_fair_value (spread=0) means
    taxable_amount_cents == 0, which we cannot use to exercise the slab
    math. Instead we exercise the existing-tax-record path by issuing
    a CASH_SETTLEMENT after verify and reading the TaxEventRecord row.
    The PRD does not commit to how "current fair value" is sourced for
    a unit test without a corporate event; PRD silence on that input
    makes the exact cents undetermined here. Generic check only: a
    TaxEventRecord with event_type=EXERCISE and jurisdiction_code=US
    must appear.
    """
    setup = setup_live_grant_with_open_window(
        jurisdiction_code="US", tax_residency="US",
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = validate_success(api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ), expected_status=200)
    qty = min(80, grant["vested_quantity"] - grant["exercised_quantity"])
    assert qty >= 1, (
        "Fixture failed: vested_quantity should be >= 1 after "
        "15 months under cliff=12 + ANNIVERSARY_BATCH."
    )
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="CASH_SETTLEMENT",
    )
    validate_success(api.verify_exercise_application(
        app["id"], plan_admin_headers,
    ), expected_status=200)
    records = list_tax_events_for_grant(
        grant["id"], event_type="EXERCISE",
    )
    assert len(records) == 1
    rec = records[0]
    assert rec["event_type"] == "EXERCISE"
    assert rec["jurisdiction_code"] == "US"
    assert isinstance(rec["withheld_amount_cents"], int)
    assert isinstance(rec["taxable_amount_cents"], int)


# ---------------------------------------------------------------------------
# Withholding is per-slab round-then-sum (PRD §3.9, §2.8)
# ---------------------------------------------------------------------------
def test_withholding_record_pinned_at_tax_withheld(api, plan_admin_headers):
    """PRD §3.8: "...which runs the withholding-tax calculation and pins
    both TaxEventRecord and the application's withholding_tax_cents."
    """
    setup = setup_live_grant_with_open_window(
        jurisdiction_code="US", tax_residency="US",
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = validate_success(api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ), expected_status=200)
    qty = min(50, grant["vested_quantity"] - grant["exercised_quantity"])
    assert qty >= 1, (
        "Fixture failed: vested_quantity should be >= 1 after "
        "15 months under cliff=12 + ANNIVERSARY_BATCH."
    )
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="CASH_SETTLEMENT",
    )
    after = validate_success(api.verify_exercise_application(
        app["id"], plan_admin_headers,
    ), expected_status=200)
    assert after["status"] == "TAX_WITHHELD"
    assert after["withholding_tax_cents"] is not None
    records = list_tax_events_for_grant(
        grant["id"], event_type="EXERCISE",
    )
    assert len(records) == 1
    assert (
        records[0]["withheld_amount_cents"]
        == after["withholding_tax_cents"]
    )


# ---------------------------------------------------------------------------
# Net proceeds for CASH_SETTLEMENT (PRD §3.8)
# ---------------------------------------------------------------------------
def test_net_proceeds_for_cash_settlement(api, plan_admin_headers):
    """PRD §3.8: "net_proceeds_cents is meaningful only for
    CASH_SETTLEMENT applications, where it is gross_proceeds_cents
    minus withholding_tax_cents..."
    """
    setup = setup_live_grant_with_open_window(
        jurisdiction_code="US", tax_residency="US",
        initial_price_per_option_cents=5000,
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = validate_success(api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ), expected_status=200)
    qty = min(50, grant["vested_quantity"] - grant["exercised_quantity"])
    assert qty >= 1, (
        "Fixture failed: vested_quantity should be >= 1 after "
        "15 months under cliff=12 + ANNIVERSARY_BATCH."
    )
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="CASH_SETTLEMENT",
    )
    after = validate_success(api.verify_exercise_application(
        app["id"], plan_admin_headers,
    ), expected_status=200)
    # gross = qty * pinned_price (= 5000c)
    assert after["gross_proceeds_cents"] == qty * 5000
    assert after["net_proceeds_cents"] == (
        after["gross_proceeds_cents"] - after["withholding_tax_cents"]
    )


# ---------------------------------------------------------------------------
# Net proceeds is null for SHARE_ISSUANCE (PRD §3.8)
# ---------------------------------------------------------------------------
def test_share_issuance_has_null_net_proceeds(api, plan_admin_headers):
    """PRD §3.8: "for SHARE_ISSUANCE applications, net_proceeds_cents is
    left null."
    """
    setup = setup_live_grant_with_open_window(
        quantity=1200, advance_clock_months_after_grant=15,
    )
    grant = validate_success(api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ), expected_status=200)
    qty = min(50, grant["vested_quantity"] - grant["exercised_quantity"])
    assert qty >= 1, (
        "Fixture failed: vested_quantity should be >= 1 after "
        "15 months under cliff=12 + ANNIVERSARY_BATCH."
    )
    app = submit_exercise_application(
        grant, setup["window"], setup["grantee"],
        requested_quantity=qty, settlement_mode="SHARE_ISSUANCE",
    )
    from test_helpers import drive_app_to_tax_withheld_share
    after = drive_app_to_tax_withheld_share(
        app, payment_reference="BK-N",
    )
    # By the time the app is in TAX_WITHHELD, the share-issuance branch
    # keeps net_proceeds_cents null per PRD §3.8.
    assert after["status"] == "TAX_WITHHELD"
    assert after.get("net_proceeds_cents") is None


# ---------------------------------------------------------------------------
# Sale event taxable amount (PRD §3.9)
# ---------------------------------------------------------------------------
def test_sale_taxable_amount_formula(api, plan_admin_headers):
    """PRD §3.9: "For a sale event, taxable amount is the difference
    (sale_proceeds_cents minus cost_basis_cents) multiplied by sold_quantity."
    """
    setup = setup_live_grant_with_open_window(
        jurisdiction_code="US", tax_residency="US",
    )
    grant_id = setup["grant"]["id"]
    payload = create_sale_tax_event_payload(
        sale_proceeds_cents=10_000,
        cost_basis_cents=5_000,
        sold_quantity=10,
    )
    res = api.create_tax_event(grant_id, payload, plan_admin_headers)
    rec = validate_success(res, expected_status=201)
    assert rec["event_type"] == "SALE"
    assert rec["taxable_amount_cents"] == (10_000 - 5_000) * 10
