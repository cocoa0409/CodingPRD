"""Fee and commission calculations: season-vs-daily fee divergence, provisional
vs final commission, and the market fee/voucher ledgers.

Covers Difficulty rules dual_variant_calc and combinatorial_formula, plus the
corner calculation claims that share the same fixtures.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data, make_vendor_headers,
    TEST_USERS,
    create_market, create_booth, create_active_vendor, create_open_market_day,
    create_market_day, reserve_season_assignment, reserve_daily_assignment,
    booth_version, create_booth_assignment_payload,
    setup_open_day_with_batch, submit_redemption, reconcile_redemption,
    setup_reconciled_redemption, setup_submitted_sales_report,
)

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc
# ---------------------------------------------------------------------------
def test_season_fee_on_corner_booth_locks_75000(api):
    """PRD 3.4: "a SEASON assignment uses the market's season_fee_cents as its
    base, one flat charge covering every market day in the season window" and
    "a CORNER booth uses 150" with "the locked fee_charged_cents is the base
    multiplied by the size multiplier, divided by 100, and rounded half up to
    whole cents." 50000*150/100 = 75000.

    Design: Difficulty/dual_variant_calc/assignment_fee_season_vs_daily_diverge
    """
    market = create_market()
    booth = create_booth(market["id"], label="A-12", grid_row=1, grid_col=12,
                        size_class="CORNER")
    vendor = create_active_vendor(market["id"], product_category="PRODUCE")
    create_open_market_day(market["id"], market_date="2026-06-06")

    asg = reserve_season_assignment(market["id"], booth["id"], vendor["id"])
    assert asg["assignment_type"] == "SEASON"
    assert asg["status"] == "RESERVED"
    assert asg["fee_charged_cents"] == 75000, (
        f"SEASON CORNER fee should be 50000*150/100=75000, got {asg['fee_charged_cents']}"
    )


def test_daily_fee_diverges_from_season_on_same_corner_booth(api):
    """PRD 3.4: "a DAILY assignment uses the market's daily_fee_cents as its base,
    charged for the single day" and a CORNER booth "uses 150", with the fee being
    "the base multiplied by the size multiplier, divided by 100, and rounded half
    up". 4000*150/100 = 6000, divergent from the SEASON charge of 75000.

    Design: Difficulty/dual_variant_calc/assignment_fee_season_vs_daily_diverge
    """
    market = create_market()
    booth = create_booth(market["id"], label="A-13", grid_row=1, grid_col=13,
                        size_class="CORNER")
    vendor = create_active_vendor(market["id"], product_category="PRODUCE")
    day = create_open_market_day(market["id"], market_date="2026-06-06")

    asg = reserve_daily_assignment(market["id"], booth["id"], vendor["id"], day["id"])
    assert asg["assignment_type"] == "DAILY"
    assert asg["status"] == "RESERVED"
    assert asg["fee_charged_cents"] == 6000, (
        f"DAILY CORNER fee should be 4000*150/100=6000, got {asg['fee_charged_cents']}"
    )


def test_provisional_commission_taken_on_full_gross(api):
    """PRD 3.8: "The provisional commission, computed at submission, is taken on
    the vendor's full self-reported gross: it is gross_sales_cents multiplied by
    the market's commission_bps and divided by 10000, rounded half up to whole
    cents." 30000*700/10000 = 2100.

    Design: Difficulty/dual_variant_calc/commission_provisional_vs_final_diverge
    """
    base = setup_submitted_sales_report(gross_sales_cents=30000, tokens_accepted=50)
    sr = get_success_data(api.get_sales_report(base["sales_report"]["id"], ADMIN))
    assert sr["status"] == "SUBMITTED"
    assert sr["commission_cents"] == 2100, (
        f"provisional commission should be 30000*700/10000=2100, got {sr['commission_cents']}"
    )


def test_final_commission_recomputed_on_verified_sales(api):
    """PRD 3.8: "takes the verified sales as the lesser of gross_sales_cents and
    those token-backed sales, and sets the final commission_cents to the verified
    sales multiplied by commission_bps and divided by 10000, rounded half up to
    whole cents." 40 tokens * 200 = 8000 verified, 8000*700/10000 = 560, divergent
    from provisional 2100.

    Design: Difficulty/dual_variant_calc/commission_provisional_vs_final_diverge
    """
    # Build a vendor+day with 40 RECONCILED tokens then a submitted sales report
    # (gross 30000, tokens_accepted 50) on the same vendor+day.
    market = create_market()
    booth = create_booth(market["id"], label="B-01", grid_row=0, grid_col=1, size_class="SINGLE")
    vendor = create_active_vendor(market["id"], product_category="CRAFTS")
    day = create_open_market_day(market["id"], market_date="2026-06-06")
    asg = reserve_daily_assignment(market["id"], booth["id"], vendor["id"], day["id"])
    vh = make_vendor_headers(vendor["id"])
    ci = get_success_data(api.create_check_in(
        {"market_id": market["id"], "booth_assignment_id": asg["id"],
         "market_day_id": day["id"]}, vh))
    ci = get_success_data(api.arrive_check_in(ci["id"], vh))
    batch = get_success_data(api.create_voucher_batch(
        {"market_id": market["id"], "market_day_id": day["id"], "tokens_issued": 100}, MANAGER))
    red = submit_redemption(market["id"], batch["id"], vendor["id"], day["id"], 40)
    reconcile_redemption(red["id"])
    sr = get_success_data(api.create_sales_report(
        {"market_id": market["id"], "check_in_id": ci["id"],
         "gross_sales_cents": 30000, "tokens_accepted": 50}, vh))
    sr = get_success_data(api.submit_sales_report(sr["id"], {}, vh))
    assert sr["commission_cents"] == 2100, "provisional sanity check"

    reconciled = validate_success(api.reconcile_sales_report(sr["id"], MANAGER), 200)
    assert reconciled["status"] == "RECONCILED"
    assert reconciled["reconciled_token_count"] == 40
    assert reconciled["commission_cents"] == 560, (
        f"final commission should be min(30000,8000)*700/10000=560, "
        f"got {reconciled['commission_cents']}"
    )


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula
# ---------------------------------------------------------------------------
def test_voucher_liability_aggregates_reconciled_tokens(api):
    """PRD 3.7: "the market liability is then the market's voucher_face_value_cents
    multiplied by the total of tokens_redeemed summed over every batch under the
    market, less the cash already reimbursed to vendors to date" and a batch's
    tokens_redeemed is "the lesser of its tokens_issued and the sum of token_count
    across that batch's reconciled redemptions". Two RECONCILED redemptions 40+30
    = 70 under a 100-token batch give liability 200*70 = 14000.

    Design: Difficulty/combinatorial_formula/voucher_liability_nested_min_branch
    """
    market = create_market()
    day = create_open_market_day(market["id"], market_date="2026-06-06")
    v1 = get_success_data(api.create_vendor(
        {"market_id": market["id"], "legal_name": "V1", "contact_email": "v1@x.com"}, ADMIN))
    v2 = get_success_data(api.create_vendor(
        {"market_id": market["id"], "legal_name": "V2", "contact_email": "v2@x.com"}, ADMIN))
    batch = get_success_data(api.create_voucher_batch(
        {"market_id": market["id"], "market_day_id": day["id"], "tokens_issued": 100}, MANAGER))
    r1 = submit_redemption(market["id"], batch["id"], v1["id"], day["id"], 40)
    r2 = submit_redemption(market["id"], batch["id"], v2["id"], day["id"], 30)
    reconcile_redemption(r1["id"])

    r2_done = validate_success(api.reconcile_voucher_redemption(r2["id"], MANAGER), 200)
    assert r2_done["reimbursed_cents"] == 6000, "30 tokens * 200 face = 6000"

    batch_after = get_success_data(api.get_voucher_batch(batch["id"], ADMIN))
    assert batch_after["tokens_redeemed"] == 70

    market_after = get_success_data(api.get_market(market["id"], ADMIN))
    assert market_after["voucher_liability_cents"] == 14000, (
        f"liability should be 200*(40+30)=14000, got {market_after['voucher_liability_cents']}"
    )


def test_voucher_liability_excludes_unreconciled_redemption(api):
    """PRD 3.7: a batch's tokens_redeemed is "the lesser of its tokens_issued and
    the sum of token_count across that batch's reconciled redemptions" — only
    RECONCILED redemptions enter the sum. With one RECONCILED 40 and one still
    SUBMITTED 30, tokens_redeemed=40 and liability 200*40=8000 (the 30 is excluded).

    Design: Difficulty/combinatorial_formula/voucher_liability_nested_min_branch
    """
    market = create_market()
    day = create_open_market_day(market["id"], market_date="2026-06-06")
    v1 = get_success_data(api.create_vendor(
        {"market_id": market["id"], "legal_name": "V1", "contact_email": "v1@x.com"}, ADMIN))
    v2 = get_success_data(api.create_vendor(
        {"market_id": market["id"], "legal_name": "V2", "contact_email": "v2@x.com"}, ADMIN))
    batch = get_success_data(api.create_voucher_batch(
        {"market_id": market["id"], "market_day_id": day["id"], "tokens_issued": 100}, MANAGER))
    r1 = submit_redemption(market["id"], batch["id"], v1["id"], day["id"], 40)
    submit_redemption(market["id"], batch["id"], v2["id"], day["id"], 30)  # left SUBMITTED
    reconcile_redemption(r1["id"])

    batch_after = get_success_data(api.get_voucher_batch(batch["id"], ADMIN))
    assert batch_after["tokens_redeemed"] == 40, "only the RECONCILED redemption counts"
    market_after = get_success_data(api.get_market(market["id"], ADMIN))
    assert market_after["voucher_liability_cents"] == 8000


def test_market_fee_ledger_sums_reserved_active_assignments(api):
    """PRD 2.9: "total_fees_collected_cents, is the sum over every booth assignment
    currently in RESERVED or ACTIVE status of that assignment's fee_charged_cents
    less its fee_refunded_cents". One SEASON CORNER (75000) plus one DAILY DOUBLE
    (4000*180/100=7200) gives 82200.

    Design: Difficulty/combinatorial_formula/market_fee_ledger_pinned_eval_order
    """
    market = create_market()
    booth_c = create_booth(market["id"], label="C-1", grid_row=0, grid_col=1, size_class="CORNER")
    booth_d = create_booth(market["id"], label="D-1", grid_row=0, grid_col=2, size_class="DOUBLE")
    v1 = create_active_vendor(market["id"], "CRAFTS", "V1", "v1@x.com")
    v2 = create_active_vendor(market["id"], "FLOWERS", "V2", "v2@x.com")
    day = create_open_market_day(market["id"], market_date="2026-06-06")

    asg_season = reserve_season_assignment(market["id"], booth_c["id"], v1["id"])
    assert asg_season["fee_charged_cents"] == 75000

    asg_daily = reserve_daily_assignment(market["id"], booth_d["id"], v2["id"], day["id"])
    assert asg_daily["fee_charged_cents"] == 7200, "DAILY DOUBLE: 4000*180/100=7200"

    market_after = get_success_data(api.get_market(market["id"], ADMIN))
    assert market_after["total_fees_collected_cents"] == 82200, (
        f"ledger should be 75000+7200=82200, got {market_after['total_fees_collected_cents']}"
    )


def test_market_fee_ledger_counts_only_reserved_after_locking_fee(api):
    """PRD 2.9: "the assignment's fee_charged_cents and fee_refunded_cents are
    locked first, in isolation, and only then is the market aggregate recomputed
    from the now-final per-row values" and the ledger is "the sum over every booth
    assignment currently in RESERVED or ACTIVE status". A single RESERVED SEASON
    CORNER (75000) yields a ledger of exactly 75000 — its own locked fee.

    Design: Difficulty/combinatorial_formula/market_fee_ledger_pinned_eval_order
    """
    market = create_market()
    booth = create_booth(market["id"], label="C-2", grid_row=0, grid_col=3, size_class="CORNER")
    vendor = create_active_vendor(market["id"], product_category="CRAFTS")

    asg = reserve_season_assignment(market["id"], booth["id"], vendor["id"])
    assert asg["status"] == "RESERVED"
    assert asg["fee_charged_cents"] == 75000

    market_after = get_success_data(api.get_market(market["id"], ADMIN))
    assert market_after["total_fees_collected_cents"] == 75000


# ---------------------------------------------------------------------------
# Corner: calculations section
# ---------------------------------------------------------------------------
def test_season_fee_double_multiplier(api):
    """PRD 3.4: "a DOUBLE booth uses 180" and "a SEASON assignment uses the
    market's season_fee_cents as its base ... the locked fee_charged_cents is the
    base multiplied by the size multiplier, divided by 100, and rounded half up".
    50000*180/100 = 90000.

    Design: Corner/calculations/season_fee_double_multiplier_correct
    """
    market = create_market()
    booth = create_booth(market["id"], label="D-1", grid_row=0, grid_col=1, size_class="DOUBLE")
    vendor = create_active_vendor(market["id"], product_category="CRAFTS")

    asg = reserve_season_assignment(market["id"], booth["id"], vendor["id"])
    assert asg["fee_charged_cents"] == 90000

    market_after = get_success_data(api.get_market(market["id"], ADMIN))
    assert market_after["total_fees_collected_cents"] == 90000


def test_final_commission_caps_at_gross_when_tokens_exceed_sales(api):
    """PRD 3.8: "takes the verified sales as the lesser of gross_sales_cents and
    those token-backed sales". With 200 tokens*200=40000 token-backed exceeding
    gross 30000, verified = min(30000, 40000) = 30000, so final commission equals
    provisional 2100.

    Design: Corner/calculations/final_commission_caps_at_gross_when_tokens_exceed_sales
    """
    market = create_market()
    booth = create_booth(market["id"], label="S-1", grid_row=0, grid_col=1, size_class="SINGLE")
    vendor = create_active_vendor(market["id"], product_category="CRAFTS")
    day = create_open_market_day(market["id"], market_date="2026-06-06")
    asg = reserve_daily_assignment(market["id"], booth["id"], vendor["id"], day["id"])
    vh = make_vendor_headers(vendor["id"])
    ci = get_success_data(api.create_check_in(
        {"market_id": market["id"], "booth_assignment_id": asg["id"],
         "market_day_id": day["id"]}, vh))
    ci = get_success_data(api.arrive_check_in(ci["id"], vh))
    batch = get_success_data(api.create_voucher_batch(
        {"market_id": market["id"], "market_day_id": day["id"], "tokens_issued": 200}, MANAGER))
    red = submit_redemption(market["id"], batch["id"], vendor["id"], day["id"], 200)
    reconcile_redemption(red["id"])
    sr = get_success_data(api.create_sales_report(
        {"market_id": market["id"], "check_in_id": ci["id"],
         "gross_sales_cents": 30000, "tokens_accepted": 200}, vh))
    sr = get_success_data(api.submit_sales_report(sr["id"], {}, vh))

    reconciled = validate_success(api.reconcile_sales_report(sr["id"], MANAGER), 200)
    assert reconciled["reconciled_token_count"] == 200
    assert reconciled["commission_cents"] == 2100, (
        "verified capped at gross 30000, so 30000*700/10000=2100"
    )


def test_reconcile_redemption_locks_reimbursement(api):
    """PRD 3.7: "A successful reconcile locks reimbursed_cents as this redemption's
    token_count multiplied by the market's voucher_face_value_cents, then recomputes
    the batch's tokens_redeemed". 30 tokens * 200 = 6000.

    Design: Corner/endpoints/reconcile_redemption_locks_reimbursement
    """
    base = setup_open_day_with_batch(tokens_issued=100)
    red = submit_redemption(base["market"]["id"], base["batch"]["id"],
                            base["vendor"]["id"], base["day"]["id"], 30)

    reconciled = validate_success(api.reconcile_voucher_redemption(red["id"], MANAGER), 200)
    assert reconciled["status"] == "RECONCILED"
    assert reconciled["reimbursed_cents"] == 6000

    batch_after = get_success_data(api.get_voucher_batch(base["batch"]["id"], ADMIN))
    assert batch_after["tokens_redeemed"] == 30
