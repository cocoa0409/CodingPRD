"""Validation tests: uniqueness, billing/budget period overlap, referential billing
prerequisites, shutoff eligibility, pending-bill blocking, reconnect balance — plus the
resource_temporal_overlap depth instances."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    fixtures as fx,
    ApiErrorId, TEST_USERS,
)

ADMIN = TEST_USERS["billing_admin_headers"]
CS = TEST_USERS["customer_service_headers"]
FT = TEST_USERS["field_tech_headers"]


# ===========================================================================
# Queue B — validations
# ===========================================================================
def test_duplicate_rate_schedule_code_returns_duplicate(api):
    """PRD 3.1: "A rate schedule is created with a unique code (for example RES-1, unique
    across all rate schedules, a duplicate rejected with ERR_DUPLICATE)".

    Design: Corner/validations/duplicate_rate_schedule_code_returns_duplicate
    """
    fx.create_rate_schedule(code="RES-DUP")
    resp = api.create_rate_schedule(
        {"code": "RES-DUP", "customer_class": "RESIDENTIAL", "fixed_customer_charge_cents": 9999,
         "distribution_rate_cents_per_therm": 20, "btu_factor": 1.025, "minimum_bill_cents": 0},
        headers=ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)


def test_duplicate_meter_serial_returns_duplicate(api):
    """PRD 3.2: "A premise meter is then registered under the account with a unique serial_no
    (a duplicate serial rejected with ERR_DUPLICATE)".

    Design: Corner/validations/duplicate_meter_serial_no_returns_duplicate
    """
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    fx.register_meter(acct["id"], install_index=1000, serial_no="MX-DUP")
    resp = api.create_meter(acct["id"], {"serial_no": "MX-DUP", "uom": "CCF", "install_index": 2000},
                            headers=FT)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)


def test_duplicate_bill_per_account_service_month_returns_duplicate(api):
    """PRD 3.5: "at most one non-corrected bill may exist per (account_id, service_month), a
    duplicate rejected with ERR_DUPLICATE".

    Design: Corner/validations/duplicate_bill_per_account_service_month_returns_duplicate
    """
    rs, acct, meter, read, draft = fx.setup_draft_bill(service_month="2026-02")
    resp = api.create_bill(acct["id"], {"service_month": "2026-02", "to_read_id": read["id"]},
                           headers=ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)


def test_bill_issue_without_pga_returns_pga_not_found(api):
    """PRD 3.5: "a PGA schedule must exist for the bill's (customer_class, service_month)
    pairing, absent which the issue is rejected with ERR_PGA_NOT_FOUND".

    Design: Corner/validations/bill_issue_without_pga_returns_pga_not_found
    """
    # Draft bill for 2026-05 with NO PGA schedule for that month.
    rs, acct, meter, read, draft = fx.setup_draft_bill(
        service_month="2026-05", read_date="2026-05-28T00:00:00.000Z",
        create_pga=False, clock_utc="2026-05-15T00:00:00.000Z")
    resp = api.issue_bill(acct["id"], draft["id"],
                          {"expected_account_version": fx.account_version(acct["id"])}, headers=ADMIN)
    validate_error(resp, ApiErrorId.ERR_PGA_NOT_FOUND.value)


def test_shutoff_notice_below_threshold_returns_not_shutoff_eligible(api):
    """PRD 3.9: "The notice is permitted only when the account is shutoff-eligible — meaning
    past_due_cents is at least 7,500 cents and the moratorium is not in effect — and is
    otherwise rejected with ERR_NOT_SHUTOFF_ELIGIBLE."

    Design: Corner/validations/shutoff_notice_below_threshold_returns_not_shutoff_eligible
    """
    fx.set_clock("2026-02-15T00:00:00.000Z", False)
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])  # no bills -> past_due 0
    resp = api.shutoff_notice(acct["id"], headers=CS)
    validate_error(resp, ApiErrorId.ERR_NOT_SHUTOFF_ELIGIBLE.value)


def test_meter_remove_with_pending_draft_bill_blocked(api):
    """PRD 3.2: "A meter in SET status may be removed only when no DRAFT bill references an
    unconsumed read on that meter; an attempt to remove a SET meter while such a draft is
    outstanding is rejected with ERR_VALIDATION_PENDING_BILLS."

    Design: Corner/validations/meter_remove_with_pending_draft_bill_returns_validation_pending_bills
    """
    rs, acct, meter, read, draft = fx.setup_draft_bill(service_month="2026-02")
    resp = api.remove_meter(meter["id"], headers=FT)
    validate_error(resp, ApiErrorId.ERR_VALIDATION_PENDING_BILLS.value)


def test_reconnect_with_balance_due_returns_balance_due(api):
    """PRD 3.10: "the account's past_due_cents must be exactly 0, else the reconnect is
    rejected with ERR_RECONNECT_BALANCE_DUE".

    Design: Corner/validations/reconnect_with_balance_due_returns_reconnect_balance_due
    """
    acct, meter, bill = fx.setup_disconnected_account(past_due_amount=7500)
    # Do NOT pay off the bill -> past_due remains. Provide a HELD deposit so the only blocker
    # is the balance.
    fx.create_held_deposit(acct["id"], reason="RECONNECT")
    rec = fx.get_success_data(api.create_service_order(
        {"account_id": acct["id"], "order_type": "RECONNECT", "premise_meter_id": meter["id"],
         "scheduled_date": "2026-04-01T00:00:00.000Z"}, headers=FT))
    fx.get_success_data(api.dispatch_service_order(rec["id"], headers=FT))
    resp = api.complete_service_order(rec["id"], {}, headers=FT)
    validate_error(resp, ApiErrorId.ERR_RECONNECT_BALANCE_DUE.value)


def test_bill_issue_with_non_newer_closing_read_returns_read_required(api):
    """PRD 3.5: "the closing read named by to_read_id must be a POSTED ACTUAL or ESTIMATED
    read that is newer than the opening read, absent which the issue is rejected with
    ERR_READ_REQUIRED."

    Design: Corner/validations/bill_issue_with_non_newer_closing_read_returns_read_required
    """
    rs, acct, meter = fx.setup_account_with_set_meter()
    fx.create_pga_schedule(effective_month="2026-02", customer_class="RESIDENTIAL",
                           commodity_rate_cents_per_therm=40, supplier_refund_cents_per_therm=5)
    read = fx.post_read(meter["id"], 1100, "2026-02-28T00:00:00.000Z")
    # from_read and to_read both point at the same read -> to_read is NOT newer.
    draft = fx.create_bill(acct["id"], "2026-02", read["id"], from_read_id=read["id"])
    resp = api.issue_bill(acct["id"], draft["id"],
                          {"expected_account_version": fx.account_version(acct["id"])}, headers=ADMIN)
    validate_error(resp, ApiErrorId.ERR_READ_REQUIRED.value)


# ===========================================================================
# Queue A — resource_temporal_overlap
# ===========================================================================
def test_billing_period_overlap_closed_interval_rejected(api):
    """PRD 3.6: "A new bill's read-date window runs from the opening read's read_date to the
    closing read's read_date and is treated as a closed interval: two windows that merely
    touch at an endpoint are considered to overlap. If the new window overlaps any existing
    non-void, non-corrected bill window on the same meter, the create is rejected with
    ERR_BILLING_PERIOD_OVERLAP".

    Design: Difficulty/resource_temporal_overlap/bill_billing_period_overlap_closed_interval
    """
    fx.set_clock("2026-03-20T00:00:00.000Z", False)
    rs = fx.create_rate_schedule()
    fx.create_pga_schedule(effective_month="2026-02", customer_class="RESIDENTIAL",
                           commodity_rate_cents_per_therm=40, supplier_refund_cents_per_therm=5)
    fx.create_pga_schedule(effective_month="2026-03", customer_class="RESIDENTIAL",
                           commodity_rate_cents_per_therm=40, supplier_refund_cents_per_therm=5)
    acct = fx.create_account(rs["id"])
    meter = fx.register_meter(acct["id"], install_index=1000)
    fx.set_meter(acct["id"], meter["id"], completed_index=1000)
    r1 = fx.post_read(meter["id"], 1000, "2026-01-15T00:00:00.000Z")
    r2 = fx.post_read(meter["id"], 1100, "2026-02-15T00:00:00.000Z")
    r3 = fx.post_read(meter["id"], 1200, "2026-03-15T00:00:00.000Z")
    bill1 = fx.create_bill(acct["id"], "2026-02", r2["id"], from_read_id=r1["id"])
    fx.issue_bill(acct["id"], bill1["id"])
    # Window [r2=2026-02-15, r3=2026-03-15] touches bill1's window at 2026-02-15 -> overlap.
    resp = api.create_bill(acct["id"], {"service_month": "2026-03", "to_read_id": r3["id"],
                                        "from_read_id": r2["id"]}, headers=ADMIN)
    validate_error(resp, ApiErrorId.ERR_BILLING_PERIOD_OVERLAP.value)


def test_billing_period_non_overlapping_window_allowed(api):
    """PRD 3.6: "If the new window overlaps any existing non-void, non-corrected bill window on
    the same meter, the create is rejected with ERR_BILLING_PERIOD_OVERLAP". A genuinely
    disjoint window (no shared endpoint) is accepted.

    Design: Difficulty/resource_temporal_overlap/bill_billing_period_overlap_closed_interval
    """
    fx.set_clock("2026-03-20T00:00:00.000Z", False)
    rs = fx.create_rate_schedule()
    fx.create_pga_schedule(effective_month="2026-02", customer_class="RESIDENTIAL",
                           commodity_rate_cents_per_therm=40, supplier_refund_cents_per_therm=5)
    fx.create_pga_schedule(effective_month="2026-03", customer_class="RESIDENTIAL",
                           commodity_rate_cents_per_therm=40, supplier_refund_cents_per_therm=5)
    acct = fx.create_account(rs["id"])
    meter = fx.register_meter(acct["id"], install_index=1000)
    fx.set_meter(acct["id"], meter["id"], completed_index=1000)
    r1 = fx.post_read(meter["id"], 1000, "2026-01-15T00:00:00.000Z")
    r2 = fx.post_read(meter["id"], 1100, "2026-02-10T00:00:00.000Z")
    r3 = fx.post_read(meter["id"], 1150, "2026-02-20T00:00:00.000Z")
    r4 = fx.post_read(meter["id"], 1200, "2026-03-15T00:00:00.000Z")
    bill1 = fx.create_bill(acct["id"], "2026-02", r2["id"], from_read_id=r1["id"])
    fx.issue_bill(acct["id"], bill1["id"])
    # Window [r3=2026-02-20, r4=2026-03-15] is strictly after bill1's [01-15, 02-10] -> no overlap.
    resp = api.create_bill(acct["id"], {"service_month": "2026-03", "to_read_id": r4["id"],
                                        "from_read_id": r3["id"]}, headers=ADMIN)
    validate_success(resp, 201)


def test_budget_plan_coverage_window_overlap_half_open_rejected(api):
    """PRD 3.7: "The coverage window runs from anchor_month and spans twelve months as a
    half-open interval: a plan whose anchor_month is exactly the month at which a prior plan's
    window ends does not collide, but any genuine overlap with an existing ACTIVE plan window
    on the same account is rejected with ERR_BUDGET_PERIOD_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/budget_plan_coverage_window_overlap_half_open
    """
    fx.set_clock("2026-02-15T00:00:00.000Z", False)
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    fx.enroll_budget_plan(acct["id"], anchor_month="2026-01", projected_annual_cents=96000)
    # New plan anchored 2026-06 falls inside [2026-01, 2027-01) -> overlap.
    resp = api.create_budget_plan(
        acct["id"], {"anchor_month": "2026-06", "projected_annual_cents": 96000,
                     "expected_account_version": fx.account_version(acct["id"])}, headers=ADMIN)
    validate_error(resp, ApiErrorId.ERR_BUDGET_PERIOD_OVERLAP.value)


def test_budget_plan_adjacent_window_allowed(api):
    """PRD 3.7: "a plan whose anchor_month is exactly the month at which a prior plan's window
    ends does not collide".

    Design: Difficulty/resource_temporal_overlap/budget_plan_coverage_window_overlap_half_open
    """
    fx.set_clock("2026-02-15T00:00:00.000Z", False)
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    fx.enroll_budget_plan(acct["id"], anchor_month="2026-01", projected_annual_cents=96000)
    # New plan anchored exactly 2027-01 (the end month of [2026-01, 2027-01)) -> no collision.
    resp = api.create_budget_plan(
        acct["id"], {"anchor_month": "2027-01", "projected_annual_cents": 96000,
                     "expected_account_version": fx.account_version(acct["id"])}, headers=ADMIN)
    validate_success(resp, 201)
