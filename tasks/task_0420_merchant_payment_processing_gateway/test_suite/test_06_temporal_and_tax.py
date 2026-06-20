"""Time-gated windows (funding maturity, evidence window, payout schedule) and the 1099-K
threshold calculation.

Covers difficulty queue (resource_temporal_overlap funding/evidence windows,
boundary_precision_check tax threshold) and corner tax/payout-temporal instances.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    set_clock, advance_clock,
    create_flat_plan, create_approved_merchant, create_captured_charge,
    open_and_settle_batch, setup_funded_merchant, setup_acknowledged_dispute,
    make_merchant_user_headers,
    TEST_USERS,
)

OPERATOR = TEST_USERS["platform_operator_headers"]


def test_fund_before_maturity_rejected(api):
    """PRD §3.7: "Funding is permitted only while the batch's `batch_status` is `SETTLED` and
    only once the clock's date has reached or passed the batch's `business_date` plus the
    merchant's `funding_delay_days`; an attempt to fund before that maturity is rejected with
    `ERR_FUNDING_DATE_NOT_REACHED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/funding_window_closed_lower_bound_on_batch
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="MEDIUM")
    version = merchant["version"]
    create_captured_charge(merchant["id"], auth_amount_cents=10000)
    batch, _ = open_and_settle_batch(merchant["id"], version, business_date="2026-01-01")
    # MEDIUM funds T+2 (2026-01-03). At 2026-01-02 the window is not yet open.
    set_clock("2026-01-02T00:00:00Z")
    resp = api.fund_batch(batch["id"], {}, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_FUNDING_DATE_NOT_REACHED)


def test_fund_at_maturity_boundary_succeeds(api):
    """PRD §3.7: "only once the clock's date has reached or passed the batch's `business_date`
    plus the merchant's `funding_delay_days`".
    PRD §3.7: "Funding the batch advances it from `SETTLED` to the terminal `FUNDED`."

    Design: Difficulty/resource_temporal_overlap/funding_window_closed_lower_bound_on_batch
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="MEDIUM")
    version = merchant["version"]
    create_captured_charge(merchant["id"], auth_amount_cents=10000)
    batch, _ = open_and_settle_batch(merchant["id"], version, business_date="2026-01-01")
    set_clock("2026-01-03T00:00:00Z")  # T+2, boundary inclusive
    funded = validate_success(api.fund_batch(batch["id"], {}, OPERATOR))
    assert funded["batch_status"] == "FUNDED"


def test_represent_past_evidence_due_at_rejected(api):
    """PRD §3.6: "only while the current clock is at or before `evidence_due_at` (a submission
    after the deadline is rejected with `ERR_EVIDENCE_WINDOW_CLOSED`, HTTP 422)".

    Design: Difficulty/resource_temporal_overlap/evidence_window_closed_upper_bound_on_dispute
    """
    # Dispute opened at 2026-01-01 -> evidence_due_at = 2026-01-15 (+14d), acknowledged; advance past it.
    base = setup_acknowledged_dispute(
        disputed_amount_cents=10000, fund=False,
        clock="2026-01-01", business_date="2026-01-01",
    )
    set_clock("2026-01-16T00:00:00Z")
    headers = make_merchant_user_headers(base["merchant_id"])
    resp = api.represent_dispute(base["dispute"]["id"], {}, headers)
    validate_error(resp, ApiErrorId.ERR_EVIDENCE_WINDOW_CLOSED)


def test_represent_within_evidence_window_succeeds(api):
    """PRD §3.6: "From `UNDER_REVIEW`, the merchant submits representment evidence, moving the
    dispute to `REPRESENTED` and incrementing `representment_round` by one; representment is
    permitted only while the dispute is `UNDER_REVIEW`, only while the current clock is at or
    before `evidence_due_at`".

    Design: Difficulty/resource_temporal_overlap/evidence_window_closed_upper_bound_on_dispute
    """
    base = setup_acknowledged_dispute(
        disputed_amount_cents=10000, fund=False,
        clock="2026-01-01", business_date="2026-01-01",
    )
    # Clock still at 2026-01-01, well within the 14-day window.
    headers = make_merchant_user_headers(base["merchant_id"])
    represented = validate_success(api.represent_dispute(base["dispute"]["id"], {}, headers))
    assert represented["dispute_status"] == "REPRESENTED"


def test_tax_1099k_gross_exactly_at_threshold_not_reportable(api):
    """PRD §3.11: "the `reportable` flag is true exactly when `gross_amount_cents` strictly
    exceeds the reporting threshold of 250000 cents. The comparison is strict: a gross of
    exactly 250000 cents is not reportable, while 250001 cents is."

    Design: Difficulty/boundary_precision_check/tax_1099k_reporting_threshold_strict_greater
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_flat_plan(flat_pct_bps=0, flat_fixed_cents=0)
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    version = merchant["version"]
    create_captured_charge(merchant["id"], auth_amount_cents=250000)
    open_and_settle_batch(merchant["id"], version, business_date="2026-06-01")
    form = validate_success(api.generate_tax_1099k(merchant["id"], {"tax_year": 2026}, OPERATOR), expected_status=201)
    assert form["gross_amount_cents"] == 250000
    assert form["reportable"] is False, "gross of exactly 250000 must NOT be reportable"


def test_tax_1099k_gross_one_over_threshold_reportable(api):
    """PRD §3.11: "The comparison is strict: a gross of exactly 250000 cents is not reportable,
    while 250001 cents is."

    Design: Difficulty/boundary_precision_check/tax_1099k_reporting_threshold_strict_greater
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_flat_plan(flat_pct_bps=0, flat_fixed_cents=0)
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    version = merchant["version"]
    create_captured_charge(merchant["id"], auth_amount_cents=250001)
    open_and_settle_batch(merchant["id"], version, business_date="2026-06-01")
    form = validate_success(api.generate_tax_1099k(merchant["id"], {"tax_year": 2026}, OPERATOR), expected_status=201)
    assert form["gross_amount_cents"] == 250001
    assert form["reportable"] is True, "gross of 250001 must be reportable"


# --- Corner: tax aggregation and payout temporal ---

def test_tax_1099k_sums_settled_captures_pre_fee(api):
    """PRD §3.11: "The `gross_amount_cents` is the sum of `captured_amount_cents` over that
    included set, the `transaction_count` is the number of charges in the included set".
    PRD §3.11: "The 1099-K gross is a threshold calculation over settled captures, with no
    netting of refunds, fees, or chargebacks."

    Design: Corner/Calculations/corner_tax_1099k_transaction_count_and_gross
    """
    set_clock("2026-05-01T00:00:00Z")
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(
        fee_plan_id=plan["id"], assigned_risk_band="LOW",
        merchant_overrides={"requested_monthly_volume_cents": 500000},
    )
    version = merchant["version"]
    create_captured_charge(merchant["id"], auth_amount_cents=100000)
    create_captured_charge(merchant["id"], auth_amount_cents=50000)
    open_and_settle_batch(merchant["id"], version, business_date="2026-05-01")
    form = validate_success(api.generate_tax_1099k(merchant["id"], {"tax_year": 2026}, OPERATOR), expected_status=201)
    assert form["gross_amount_cents"] == 150000
    assert form["transaction_count"] == 2
    assert form["reportable"] is False


def test_mark_payout_paid_before_scheduled_date_rejected(api):
    """PRD §3.10: "it is permitted only while the payout is `REQUESTED` and only once the
    clock's date has reached or passed the payout's `scheduled_for` date, with an early attempt
    rejected by `ERR_PAYOUT_DATE_NOT_REACHED` (HTTP 409)."

    Design: Corner/Validations/corner_payout_marked_paid_before_scheduled_date
    """
    base = setup_funded_merchant(assigned_risk_band="LOW", auth_amount_cents=10000,
                                 fund_date="2026-01-03")
    headers = make_merchant_user_headers(base["merchant_id"])
    payout = validate_success(api.create_payout(base["merchant_id"], {"amount_cents": 5000, "scheduled_for": "2026-01-05"}, headers), expected_status=201)
    set_clock("2026-01-04T00:00:00Z")  # before scheduled_for
    resp = api.mark_payout_paid(payout["id"], {}, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_PAYOUT_DATE_NOT_REACHED)


def test_mark_payout_paid_posts_no_further_ledger_entry(api):
    """PRD §3.10: "Marking it paid drives `payout_status` from `REQUESTED` to the terminal
    `PAID`".
    PRD §3.10: "Marking paid posts no ledger entry, because the funds were already debited at
    request time."

    Design: Corner/Endpoints/corner_payout_mark_paid_no_balance_change
    """
    base = setup_funded_merchant(assigned_risk_band="LOW", auth_amount_cents=10000,
                                 fund_date="2026-01-03")
    headers = make_merchant_user_headers(base["merchant_id"])
    payout = validate_success(api.create_payout(base["merchant_id"], {"amount_cents": 5000, "scheduled_for": "2026-01-05"}, headers), expected_status=201)
    before = validate_success(api.get_merchant(base["merchant_id"], OPERATOR))["available_balance_cents"]
    set_clock("2026-01-05T00:00:00Z")
    paid = validate_success(api.mark_payout_paid(payout["id"], {}, OPERATOR))
    assert paid["payout_status"] == "PAID"
    after = validate_success(api.get_merchant(base["merchant_id"], OPERATOR))["available_balance_cents"]
    assert after == before, "mark-paid must not change the available balance"
