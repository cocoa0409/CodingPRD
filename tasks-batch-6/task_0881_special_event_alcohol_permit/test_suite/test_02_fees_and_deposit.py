"""Permit-fee estimation and reconciliation, the deposit, and the ledger.

Difficulty: dual_variant_calc (fee), combinatorial_formula (round-then-sum fee).
Corner: ledger_entries_created_on_submit, deposit_refund_clean_full_close.
"""
from test_helpers import (
    validate_success, ApiErrorId, find_ledger_entry, fixtures,
)
from test_helpers.test_users import TEST_USERS
from test_helpers import create_report_payload

APPLICANT = TEST_USERS["applicant_headers"]
CLERK = TEST_USERS["clerk_headers"]


def test_submit_estimated_fee_rounds_each_line_then_sums(api):
    """PRD §3.3: "The attendance line is the attendance multiplied by a per-attendee
    surcharge of 37.5 cents, rounded half-up. The sales line is the sales figure
    multiplied by a surcharge rate of 0.0125 (one and a quarter percent), rounded half-up."
    PRD §2.6: "each line item is individually rounded to whole cents using the
    round-half-up convention, and only the already-rounded line items are summed; the
    sum itself is not rounded again."

    attendance 151 -> round(151*37.5)=5663; sales 250050 -> round(250050*0.0125)=3126;
    base 5000; total 13789 (sum-then-round would give 13788).

    Design: Difficulty/combinatorial_formula/permit_fee_round_then_sum
    """
    ctx = fixtures.create_draft_with_documents(api)
    resp = api.submit_application(ctx["application"]["id"], APPLICANT)
    data = validate_success(resp)
    assert data["permit_fee_cents"] == 13789
    assert data["fee_basis"] == "ESTIMATED"


def test_submit_assesses_flat_deposit_and_balance(api):
    """PRD §3.3: "is a flat 20,000 cents, written to `deposit_cents`."
    PRD §3.3: "It recomputes `balance_due_cents` as the signed sum of every ledger entry".

    fee 13789 + deposit 20000 => balance_due 33789.

    Design: Difficulty/combinatorial_formula/permit_fee_round_then_sum
    """
    ctx = fixtures.create_draft_with_documents(api)
    resp = api.submit_application(ctx["application"]["id"], APPLICANT)
    data = validate_success(resp)
    assert data["deposit_cents"] == 20000
    assert data["balance_due_cents"] == 33789


def test_submit_posts_fee_and_deposit_ledger_entries(api):
    """PRD §3.3: "Submission then posts two ledger entries against the application: a
    `FEE` entry for the computed permit fee and a `DEPOSIT` entry for the deposit, both
    as positive debits."

    Design: Corner/endpoints/ledger_entries_created_on_submit
    """
    ctx = fixtures.create_submitted_application(api)
    entries = fixtures.list_ledger_entries(api, ctx["application"]["id"])
    fee = find_ledger_entry(entries, "FEE", 13789)
    deposit = find_ledger_entry(entries, "DEPOSIT", 20000)
    assert fee is not None, f"expected FEE +13789 in {entries}"
    assert deposit is not None, f"expected DEPOSIT +20000 in {entries}"


def test_report_reconciles_fee_to_actuals(api):
    """PRD §3.9: "The permit fee is recomputed with the identical three-line formula
    from §3.3, but the reconciled variant substitutes the report's actuals —
    `actual_attendance` for attendance and `gross_sales_cents` for sales. The recomputed
    amount is written to the report's `reconciled_fee_cents` and to the application's
    `permit_fee_cents`, and `fee_basis` becomes `RECONCILED`."
    PRD §3.9: "Filing creates the report in `FILED` status and cascades the application
    from `PERMIT_ISSUED` to `EVENT_COMPLETE`."

    actual 200 -> round(200*37.5)=7500; sales 300000 -> round(300000*0.0125)=3750;
    base 5000; reconciled fee 16250.

    Design: Difficulty/dual_variant_calc/fee_estimate_vs_reconcile
    """
    ctx = fixtures.drive_to_event_complete(
        api, report_overrides={"actual_attendance": 200, "gross_sales_cents": 300000,
                               "incident_count": 0})
    app = ctx["application"]
    assert app["fee_basis"] == "RECONCILED"
    assert app["permit_fee_cents"] == 16250
    assert app["status"] == "EVENT_COMPLETE"
    assert ctx["report"]["reconciled_fee_cents"] == 16250


def test_reconciliation_posts_fee_adjustment_delta(api):
    """PRD §3.9: "A `FEE_ADJUSTMENT` ledger entry is posted for the difference between
    the reconciled fee and the previous `permit_fee_cents` (which may be negative), and
    `balance_due_cents` is recomputed."

    reconciled 16250 - estimated 13789 = 2461; balance (paid to 0 pre-report) becomes 2461.

    Design: Difficulty/dual_variant_calc/fee_estimate_vs_reconcile
    """
    ctx = fixtures.drive_to_event_complete(
        api, report_overrides={"actual_attendance": 200, "gross_sales_cents": 300000,
                               "incident_count": 0})
    app_id = ctx["application"]["id"]
    entries = fixtures.list_ledger_entries(api, app_id)
    adjustment = find_ledger_entry(entries, "FEE_ADJUSTMENT", 2461)
    assert adjustment is not None, f"expected FEE_ADJUSTMENT +2461 in {entries}"
    assert ctx["application"]["balance_due_cents"] == 2461


def test_close_refunds_full_deposit_on_clean_event(api):
    """PRD §3.9: "When the refunded amount is positive, the system appends a
    `DEPOSIT_REFUND` ledger entry carrying the negative of the refunded portion".
    PRD §3.9: "The application's `deposit_status` becomes `REFUNDED` when the full deposit
    is refunded and `FORFEITED` otherwise, the report's `status` advances to `ACCEPTED`,
    `balance_due_cents` is recomputed, and the application is `CLOSED`."

    Clean event (incident_count 0, no UPHELD violations) => full 20000 refunded.

    Design: Corner/calculations/deposit_refund_clean_full_close
    """
    ctx = fixtures.drive_to_event_complete(api)  # report actuals equal estimates -> zero delta
    app_id = ctx["application"]["id"]
    resp = api.close_application(app_id, CLERK)
    data = validate_success(resp)
    assert data["status"] == "CLOSED"
    assert data["deposit_status"] == "REFUNDED"
    report = validate_success(api.get_report(ctx["report"]["id"], CLERK))
    assert report["status"] == "ACCEPTED"
    entries = fixtures.list_ledger_entries(api, app_id)
    refund = find_ledger_entry(entries, "DEPOSIT_REFUND", -20000)
    assert refund is not None, f"expected DEPOSIT_REFUND -20000 in {entries}"
