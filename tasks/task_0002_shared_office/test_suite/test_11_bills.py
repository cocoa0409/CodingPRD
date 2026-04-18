"""Bill lifecycle, consolidation, tax, late-fee, and void tests.

Covers PRD §3.7 (issue / pay / void), §2.9 (sum-then-round tax; non-compounding
late fee), and §2.11 (consolidation and period-scoped uniqueness).
"""

import pytest

from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    THRESHOLDS,
    advance_clock_to,
    assert_bill,
    assert_bill_sum_then_round_tax,
    assert_bill_totals_consistent,
    create_resource,
    find_draft_bill_for_tenant,
    get_bill,
    get_reservation,
    issue_bill_as_officer,
    pay_bill_as_clerk,
    run_full_reservation_lifecycle,
    run_sweep,
    setup_tenant_member_badge,
    validate_error,
    validate_success,
    void_bill_as_admin,
)


def test_completed_reservation_creates_draft_bill(api, admin_headers):
    """PRD §2.11: "Reservations that complete or no-show, visitors that leave
    with a positive overstay fee, and leases that finalize a termination
    penalty all consolidate onto the tenant's current `DRAFT` `Bill` for the
    tenant's current billing period. If no `DRAFT` bill exists at the moment of
    consolidation, the server creates one before appending the line."

    Claim: completing a reservation produces a DRAFT bill with matching
    subtotal and reservation.bill_id pointing at it.
    """
    tenant, _lease, member, badge = setup_tenant_member_badge(billing_plan="HOURLY")
    ws = create_resource(kind="WORKSTATION", code="WS-BILL-1", hourly_rate_cents=800)
    advance_clock_to("2026-10-01T07:00:00.000Z")
    reservation = run_full_reservation_lifecycle(
        tenant, member, ws, badge,
        "2026-10-01T09:00:00.000Z", "2026-10-01T10:00:00.000Z",
    )
    assert reservation["status"] == "COMPLETED"
    assert reservation["bill_id"] is not None
    bill = get_bill(reservation["bill_id"])
    assert_bill(bill)
    assert bill["status"] == "DRAFT"
    assert bill["subtotal_cents"] == reservation["final_fee_cents"]


def test_bill_tax_sum_then_round(api, admin_headers):
    """PRD §2.9: "Tax is computed **sum-then-round**: tax is applied once to the
    sum of a bill's line amounts, not per line." PRD §3.7: "`tax_cents` is the
    product of `subtotal_cents` and a tax rate of 8.25% (that is, 0.0825),
    rounded half-up to the nearest integer cent."

    Claim: tax_cents == round_half_up(subtotal_cents * 0.0825) on a populated
    DRAFT bill.
    """
    tenant, _lease, member, badge = setup_tenant_member_badge(billing_plan="HOURLY")
    ws = create_resource(kind="WORKSTATION", code="WS-TAX-1", hourly_rate_cents=800)
    advance_clock_to("2026-10-02T07:00:00.000Z")
    reservation = run_full_reservation_lifecycle(
        tenant, member, ws, badge,
        "2026-10-02T09:00:00.000Z", "2026-10-02T10:00:00.000Z",
    )
    bill = get_bill(reservation["bill_id"])
    assert_bill_sum_then_round_tax(bill, tax_rate=0.0825)
    assert_bill_totals_consistent(bill)


def test_issue_draft_bill(api, admin_headers, billing_officer_headers):
    """PRD §3.7: "A `BillingOfficer` issues a DRAFT bill by transitioning it
    from `DRAFT` to `ISSUED`."
    PRD §3.7: "On success, `issued_at` is stamped with the current clock and
    `due_at` is set to exactly 14 days after `issued_at`."

    Claim: issue on a DRAFT bill with lines → ISSUED, issued_at + due_at set.
    """
    tenant, _lease, member, badge = setup_tenant_member_badge(billing_plan="HOURLY")
    ws = create_resource(kind="WORKSTATION", code="WS-ISS-1", hourly_rate_cents=800)
    advance_clock_to("2026-10-03T07:00:00.000Z")
    reservation = run_full_reservation_lifecycle(
        tenant, member, ws, badge,
        "2026-10-03T09:00:00.000Z", "2026-10-03T10:00:00.000Z",
    )
    bill = get_bill(reservation["bill_id"])
    res = api.issue_bill(bill["id"], billing_officer_headers)
    issued = validate_success(res, expected_status=200)
    assert issued["status"] == "ISSUED"
    assert issued["issued_at"] is not None
    assert issued["due_at"] is not None


def test_pay_issued_bill(api, admin_headers, billing_officer_headers, payment_clerk_headers):
    """PRD §3.7: "Payment is performed by a `PaymentClerk`, transitioning the
    bill from either `ISSUED` or `OVERDUE` to `PAID`. The `paid_at` is stamped with
    the current clock, `Tenant.outstanding_balance_cents` is recomputed (the
    paid bill no longer contributes to the sum)."

    Claim: /pay on ISSUED bill → PAID with paid_at populated.
    """
    tenant, _lease, member, badge = setup_tenant_member_badge(billing_plan="HOURLY")
    ws = create_resource(kind="WORKSTATION", code="WS-PAY-1", hourly_rate_cents=800)
    advance_clock_to("2026-10-04T07:00:00.000Z")
    reservation = run_full_reservation_lifecycle(
        tenant, member, ws, badge,
        "2026-10-04T09:00:00.000Z", "2026-10-04T10:00:00.000Z",
    )
    bill = get_bill(reservation["bill_id"])
    issued = issue_bill_as_officer(bill)
    res = api.pay_bill(issued["id"], payment_clerk_headers)
    paid = validate_success(res, expected_status=200)
    assert paid["status"] == "PAID"
    assert paid["paid_at"] is not None


def test_void_draft_bill_clears_reservation_bill_id(api, admin_headers):
    """PRD §3.7: "A `PlatformAdmin` may void a DRAFT bill by transitioning it
    from `DRAFT` to `VOIDED`. The cascade clears `bill_id` on every
    `Reservation` and every `Visitor` linked to this bill, which allows those
    entries to re-consolidate onto the next DRAFT bill of the same tenant."

    Claim: /void on DRAFT bill → VOIDED; linked reservation's bill_id cleared.
    """
    tenant, _lease, member, badge = setup_tenant_member_badge(billing_plan="HOURLY")
    ws = create_resource(kind="WORKSTATION", code="WS-VOID-1", hourly_rate_cents=800)
    advance_clock_to("2026-10-05T07:00:00.000Z")
    reservation = run_full_reservation_lifecycle(
        tenant, member, ws, badge,
        "2026-10-05T09:00:00.000Z", "2026-10-05T10:00:00.000Z",
    )
    bill_id = reservation["bill_id"]
    res = api.void_bill(bill_id, admin_headers)
    voided = validate_success(res, expected_status=200)
    assert voided["status"] == "VOIDED"
    post = get_reservation(reservation["id"])
    assert post.get("bill_id") is None, (
        "PRD §3.7: voiding a DRAFT bill must clear bill_id on its linked reservations"
    )


def test_void_issued_bill_rejected(api, admin_headers, billing_officer_headers):
    """PRD §3.7: "Voiding is available only from `DRAFT`; an `ISSUED`, `OVERDUE`, or
    `PAID` bill cannot be voided."

    Claim: /void on ISSUED bill → ERR_INVALID_BILL_STATE (409).
    """
    tenant, _lease, member, badge = setup_tenant_member_badge(billing_plan="HOURLY")
    ws = create_resource(kind="WORKSTATION", code="WS-VOID-2", hourly_rate_cents=800)
    advance_clock_to("2026-10-06T07:00:00.000Z")
    reservation = run_full_reservation_lifecycle(
        tenant, member, ws, badge,
        "2026-10-06T09:00:00.000Z", "2026-10-06T10:00:00.000Z",
    )
    bill = get_bill(reservation["bill_id"])
    issue_bill_as_officer(bill)
    res = api.void_bill(bill["id"], admin_headers)
    validate_error(res, "ERR_INVALID_BILL_STATE", expected_status=409)


def test_pay_nonexistent_bill_returns_not_found(api, admin_headers, payment_clerk_headers):
    """PRD §2.7: "Path parameters are resolved strictly left-to-right."
    PRD §2.8: "path parameters that do not resolve yield `ERR_NOT_FOUND`."

    Claim: /pay on non-existent bill id → ERR_NOT_FOUND (404).
    """
    res = api.pay_bill("00000000-0000-4000-8000-000000000000", payment_clerk_headers)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_overdue_week_threshold_strict_floor(api, admin_headers, billing_officer_headers):
    """PRD §3.7: "The late-fee formula counts the number of strictly-full
    weeks past the due date: the number of weeks is the floor of the number of
    seconds between the current clock and `due_at`, divided by seven days. At
    exactly the seven-day mark, the count becomes 1; at six days 23 hours the
    count is still 0 and the late fee is therefore 0."

    Claim: at 6d23h59m past due_at → weeks_past_due == 0 → late_fee_cents == 0;
    at exactly 7d0h past due_at → weeks_past_due == 1 → late_fee_cents is
    round_half_up((subtotal + tax) * 0.015 * 1).
    """
    tenant, _lease, member, badge = setup_tenant_member_badge(billing_plan="HOURLY")
    ws = create_resource(kind="WORKSTATION", code="WS-LATE-1", hourly_rate_cents=10_000)
    advance_clock_to("2026-10-07T07:00:00.000Z")
    reservation = run_full_reservation_lifecycle(
        tenant, member, ws, badge,
        "2026-10-07T09:00:00.000Z", "2026-10-07T10:00:00.000Z",
    )
    bill = get_bill(reservation["bill_id"])
    # Pin the clock at a known time and issue.
    advance_clock_to("2026-10-07T12:00:00.000Z")
    issued = issue_bill_as_officer(bill)
    # issued_at = 2026-10-07T12:00Z, due_at = 2026-10-21T12:00Z (issued + 14d).
    # Advance to 2026-10-28T11:59Z: 6d 23h 59m past due_at.
    advance_clock_to("2026-10-28T11:59:00.000Z")
    run_sweep()
    first = get_bill(bill["id"])
    assert first["status"] == "OVERDUE", (
        "PRD §3.7 sweep must promote ISSUED → OVERDUE at/after due_at."
    )
    assert first["late_fee_cents"] == 0, (
        "PRD §3.7: at 6d23h59m past due_at, weeks_past_due is still 0 → late_fee_cents=0."
    )
    # Now advance to exactly 7d past due_at.
    advance_clock_to("2026-10-28T12:00:00.000Z")
    run_sweep()
    second = get_bill(bill["id"])
    from test_helpers import round_half_up

    expected_late = round_half_up(
        (second["subtotal_cents"] + second["tax_cents"]) * 0.015 * 1
    )
    assert second["late_fee_cents"] == expected_late, (
        "PRD §3.7: at exactly 7d past due_at, late_fee_cents = round_half_up("
        "(subtotal + tax) * 0.015 * 1)"
    )
