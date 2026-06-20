"""Optimistic concurrency, derived-field reconciliation, finalization cascade, threshold
reset, and immediate-consistency tests."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    fixtures as fx,
    ApiErrorId, TEST_USERS,
)

ADMIN = TEST_USERS["billing_admin_headers"]
CS = TEST_USERS["customer_service_headers"]
FT = TEST_USERS["field_tech_headers"]


def test_stale_account_version_on_bill_issue_rejected(api):
    """PRD 2.7: "If another writer has advanced the account's version since the client last
    read it — for example, another bill was issued, or a shutoff or reconnect completed, each
    of which bumps Account.version — the issue is rejected with ERR_STALE_ACCOUNT_VERSION
    (HTTP 412)".

    Design: Corner/errors/error_stale_account_version_triggerable
    """
    rs, acct, meter, read, draft = fx.setup_draft_bill()
    stale_v = fx.account_version(acct["id"])
    # Intervening write: create a budget plan with the captured version, which bumps the
    # account version, leaving stale_v out of date for the subsequent issue.
    fx.enroll_budget_plan(acct["id"], anchor_month="2026-02", projected_annual_cents=96000,
                          expected_account_version=stale_v)
    resp = api.issue_bill(acct["id"], draft["id"], {"expected_account_version": stale_v}, headers=ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value)


def test_account_version_increments_on_bill_issue(api):
    """PRD 3.5: "On a successful issue the system stamps due_date ..., sets the closing read's
    bill_id and marks the reads in the window consumed, and bumps Account.version by one."

    Design: Corner/cross_cutting_complexity_layers/occ_account_version_increments_on_bill_issue
    """
    rs, acct, meter, read, draft = fx.setup_draft_bill()
    v_before = fx.account_version(acct["id"])
    issued = validate_success(
        api.issue_bill(acct["id"], draft["id"], {"expected_account_version": v_before}, headers=ADMIN),
        200)
    assert issued["status"] == "ISSUED", f"got {issued['status']}"
    v_after = fx.account_version(acct["id"])
    assert v_after == v_before + 1, f"expected {v_before + 1}, got {v_after}"


def test_stale_account_version_on_budget_enroll_rejected(api):
    """PRD 2.7: "The second guarded operation is creating a budget plan: the enrollment request
    must likewise carry expected_account_version equal to the account's current version, and an
    older value (meaning an intervening enrollment or billing mutation has advanced the
    account) is rejected with ERR_STALE_ACCOUNT_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_budget_enroll_stale_version_conflict
    """
    rs, acct, meter, read, draft = fx.setup_draft_bill()
    stale_v = fx.account_version(acct["id"])
    # Issue the bill with the captured version, bumping the account version.
    fx.issue_bill(acct["id"], draft["id"], expected_account_version=stale_v)
    # Now enroll a budget plan with the now-stale version.
    resp = api.create_budget_plan(
        acct["id"], {"anchor_month": "2026-03", "projected_annual_cents": 96000,
                     "expected_account_version": stale_v}, headers=ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value)


def test_balance_cents_reconciles_after_payment(api):
    """PRD 3.9: "balance_cents is the sum of amount_due_cents across issued bills minus the sum
    of amount_cents across posted payments (positive means owed by the customer)."

    Design: Corner/cross_cutting_complexity_layers/derived_balance_cents_reconciles_after_payment
    """
    rs, acct, meter, read, issued = fx.setup_issued_bill()
    before = fx.get_account(acct["id"])
    assert before["balance_cents"] == 6326, f"got {before['balance_cents']}"
    fx.pay_off_bill(acct["id"], issued["id"], amount_cents=4000, posted_date="2026-03-01T00:00:00.000Z")
    after = fx.get_account(acct["id"])
    assert after["balance_cents"] == 2326, f"expected 2326, got {after['balance_cents']}"


def test_consecutive_ontime_resets_on_late_payment(api):
    """PRD 3.12: "When a bill reaches PAID, the account's consecutive_ontime_payments is
    incremented by one if the last allocating payment was on-time, and reset to 0 if it was
    late."

    Design: Corner/cross_cutting_complexity_layers/consecutive_ontime_resets_on_late_payment
    """
    rs, acct, meter, read, issued = fx.setup_issued_bill(read_date="2026-02-14T00:00:00.000Z")
    fx.inject_ontime_count(acct["id"], 5)
    # due_date = issue clock 2026-02-15 + 21 days -> 2026-03-08; pay LATE on 2026-03-20.
    pay = fx.pay_off_bill(acct["id"], issued["id"], amount_cents=6326,
                          posted_date="2026-03-20T00:00:00.000Z")
    assert pay["on_time"] is False, f"got {pay['on_time']}"
    bill = fx.get_success_data(api.get_bill(issued["id"], headers=ADMIN))
    assert bill["status"] == "PAID", f"got {bill['status']}"
    after = fx.get_account(acct["id"])
    assert after["consecutive_ontime_payments"] == 0, (
        f"late payment must reset to 0, got {after['consecutive_ontime_payments']}")


def test_final_bill_cascade_applies_deposit_and_trues_up_budget(api):
    """PRD 3.10: "Finalization cascades across the account's open instruments: any HELD deposit
    is applied against the balance and any remainder is refunded, and any ACTIVE budget plan is
    trued up." PRD 3.10: "A BillingAdmin issues the final bill, moving the account
    DISCONNECTED -> FINALED (a terminal status)".

    Design: Corner/cross_cutting_complexity_layers/cascade_final_bill_applies_deposit_and_trues_up_budget
    """
    # Build a DISCONNECTED account with an ACTIVE budget plan (one bill issued under it) and a
    # HELD reconnect deposit, then finalize.
    fx.set_clock("2026-02-15T00:00:00.000Z", False)
    rs = fx.create_rate_schedule(fixed_customer_charge_cents=7500, distribution_rate_cents_per_therm=0)
    acct = fx.create_account(rs["id"])
    fx.create_pga_schedule(effective_month="2026-02", customer_class="RESIDENTIAL",
                           commodity_rate_cents_per_therm=0, supplier_refund_cents_per_therm=0)
    meter = fx.register_meter(acct["id"], install_index=1000)
    fx.set_meter(acct["id"], meter["id"], completed_index=1000)
    read = fx.post_read(meter["id"], 1000, "2026-02-20T00:00:00.000Z")
    plan = fx.enroll_budget_plan(acct["id"], anchor_month="2026-02", projected_annual_cents=96000)
    bill = fx.create_bill(acct["id"], "2026-02", read["id"])
    fx.issue_bill(acct["id"], bill["id"])
    fx.set_clock("2026-04-01T00:00:00.000Z", False)
    fx.get_success_data(api.shutoff_notice(acct["id"], headers=CS))
    shut = fx.find_shutoff_order(acct["id"])
    fx.get_success_data(api.dispatch_service_order(shut["id"], headers=FT))
    fx.get_success_data(api.complete_service_order(shut["id"], {"completed_index": 1000}, headers=FT))
    dep = fx.create_held_deposit(acct["id"], reason="RECONNECT")
    resp = api.final_bill(acct["id"], headers=ADMIN)
    data = validate_success(resp, 200)
    assert data["service_status"] == "FINALED", f"got {data['service_status']}"
    dep_after = fx.get_success_data(api.list_deposits(acct["id"], headers=ADMIN))
    dep_status = next(d["status"] for d in dep_after if d["id"] == dep["id"])
    assert dep_status == "APPLIED", f"expected deposit APPLIED, got {dep_status}"
    plan_after = fx.get_success_data(api.list_budget_plans(acct["id"], headers=ADMIN))
    plan_status = next(p["status"] for p in plan_after if p["id"] == plan["id"])
    assert plan_status == "TRUED_UP", f"expected plan TRUED_UP, got {plan_status}"


def test_immediate_consistency_issue_response_carries_charges(api):
    """PRD 3.5: "Issuing a draft bill advances it DRAFT -> ISSUED and is where the cyclic charge
    is assembled." PRD 3.5: "On a successful issue the system stamps due_date as the clock's
    present date plus the payment term of twenty-one days".

    Design: Corner/consistency_model/immediate_consistency_issue_reflects_charges_in_same_response
    """
    rs, acct, meter, read, draft = fx.setup_draft_bill()
    resp = api.issue_bill(acct["id"], draft["id"],
                          {"expected_account_version": fx.account_version(acct["id"])}, headers=ADMIN)
    data = validate_success(resp, 200)
    assert data["status"] == "ISSUED", f"got {data['status']}"
    assert data["amount_due_cents"] == 6326, f"got {data['amount_due_cents']}"
    assert data["due_date"] is not None, "issue response must carry a stamped due_date"
