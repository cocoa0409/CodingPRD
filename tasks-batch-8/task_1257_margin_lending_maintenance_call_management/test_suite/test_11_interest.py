"""Interest accrual: tier selection, pinned rounding, monthly post, summary."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_rate_tier,
    create_rate_tier_payload,
    deposit,
    get_account,
    run_sweep,
    set_clock,
    setup_debit_account_with_tiers,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_interest_tier_selects_highest_qualifying_level(api):
    """PRD §3.9: "the applicable tier is the one whose effective window covers
    the clock date and whose `tier_level` is the greatest among those with
    `min_balance_cents` at or below the debit, and the day's `amount_cents` is
    the debit times the tier's `annual_rate_bps` divided by ten thousand and by
    360, rounded half up to whole cents."

    Design: Corner/calculations/interest_tier_selects_highest_qualifying_level
    """
    # Debit exactly 3000000 (deposit 3500000, buy 650 at 10000 = 6500000).
    # Deposit 3500000 clears the §3.4 opening-order gate (equity' 3500000 >=
    # Reg T initial' 3250000 and >= house' 3250000) while leaving the pinned
    # debit target intact.
    # Qualifies tier1 (min 0) and tier2 (min 2500000); tier2 (1100bps) wins.
    ctx = setup_debit_account_with_tiers(3_500_000, 650)
    run_sweep()
    entries_resp = api_client.list_interest_entries(
        ctx["account_id"], TEST_USERS["supervisor_headers"]
    )
    entries, _meta = validate_paginated(entries_resp)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["entry_type"] == "DAILY_ACCRUAL"
    # round_half_up(3000000 * 1100 / 10000 / 360) = round_half_up(916.67) = 917
    assert entry["amount_cents"] == 917
    assert entry["rate_bps_applied"] == 1100
    assert entry["debit_balance_snapshot_cents"] == 3_000_000
    assert entry["posted"] is False


def test_interest_per_day_rounding_pinned(api):
    """PRD §2.4: "Rounding, where a rule requires it, is always "round half up"
    to whole cents, and it is applied at exactly three pinned points and
    nowhere else: ... each daily interest accrual is rounded before the month's
    accruals are summed into a monthly posting ..."
    PRD §3.9: "the day's `amount_cents` is the debit times the tier's
    `annual_rate_bps` divided by ten thousand and by 360, rounded half up to
    whole cents."

    Design: Difficulty/combinatorial_formula/interest_accrual_mode_b_per_day_rounding_pinned
    """
    # Debit exactly 12000001 (deposit 13999999, buy 2600 at 10000 = 26000000)
    # at tier3 950bps: per-day = round_half_up(12000001*950/10000/360) = 3167.
    # Deposit 13999999 clears the §3.4 opening-order gate (equity' 13999999 >=
    # Reg T initial' 13000000 and >= house' 13000000).
    ctx = setup_debit_account_with_tiers(
        13_999_999, 2_600, tiers=((3, 10_000_000, 950),)
    )
    account_id = ctx["account_id"]
    run_sweep()  # 2026-05-01 accrual
    for day in ("2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05"):
        set_clock(f"{day}T00:00:00Z")
        run_sweep()
    summary = validate_success(
        api_client.get_interest_summary(account_id, TEST_USERS["supervisor_headers"])
    )
    # 5 * 3167 = 15835; a sum-then-round order would give 15833.
    assert summary["month_to_date_accrued_cents"] == 15_835


def test_interest_provisional_vs_posted_diverge_on_midmonth_balance_change(api):
    """PRD §3.9: "a `provisional_month_estimate_cents` equal to the
    month-to-date accrual plus the remaining days of the month times the
    current daily accrual (an estimate that assumes the debit stays constant
    and therefore diverges from posted actuals when the debit changes
    mid-month), and `posted_month_total_cents`, the chronological sum of the
    rounded daily accruals actually recorded for the last posted month."

    Design: Difficulty/dual_variant_calc/interest_provisional_vs_posted_diverge_on_midmonth_balance_change
    """
    # Debit 12000000 for May 1-10 (tier3 950bps -> 3167/day), then deposit
    # 2000000 on May 10 -> debit 10000000 (still tier3 -> 2639/day... wait:
    # 10000000 qualifies tier3 (min 10000000): 10000000*950/10000/360 = 2638.89
    # -> 2639).
    ctx = setup_debit_account_with_tiers(12_000_000, 2_400)
    account_id = ctx["account_id"]
    customer_id = ctx["customer"]["id"]
    run_sweep()  # May 1 accrual
    for d in range(2, 11):
        set_clock(f"2026-05-{d:02d}T00:00:00Z")
        run_sweep()
    # On 2026-05-10 after 10 accruals: mtd = 31670; provisional = 31670 +
    # 21*3167 = 98177.
    summary = validate_success(
        api_client.get_interest_summary(account_id, TEST_USERS["supervisor_headers"])
    )
    assert summary["month_to_date_accrued_cents"] == 31_670
    assert summary["provisional_month_estimate_cents"] == 98_177

    # Mid-month balance change: debit drops from 12000000 to 10000000.
    deposit(account_id, customer_id, 2_000_000)
    for d in range(11, 32):
        set_clock(f"2026-05-{d:02d}T00:00:00Z")
        run_sweep()
    set_clock("2026-06-01T00:00:00Z")
    run_sweep()
    summary = validate_success(
        api_client.get_interest_summary(account_id, TEST_USERS["supervisor_headers"])
    )
    # Posted May total: 10*3167 + 21*2639 = 31670 + 55419 = 87089.
    assert summary["posted_month_total_cents"] == 87_089
    assert summary["posted_month_total_cents"] != 98_177


def test_monthly_post_debits_cash_and_marks_dailies_posted(api):
    """PRD §3.9: "On the first sweep whose calendar month differs from the last
    posted month, a `MONTHLY_POST` entry is written whose amount is the sum of
    that month's already-rounded daily accruals; the included dailies flip
    `posted` to true, the `MONTHLY_POST` records the posting date in
    `accrual_date`, and its amount is debited from `cash_balance_cents` — a
    debit that feeds the same sweep's call evaluation."

    Design: Corner/endpoints/monthly_post_debits_cash_and_marks_dailies_posted
    """
    # Debit 3000000 constant from May 29 through May 31 (tier2 1100bps -> 917).
    # Deposit 3500000 clears the §3.4 opening-order gate (equity' 3500000 >=
    # Reg T initial' 3250000 and >= house' 3250000).
    ctx = setup_debit_account_with_tiers(
        3_500_000, 650, tiers=((1, 0, 1200), (2, 2_500_000, 1100))
    )
    account_id = ctx["account_id"]
    set_clock("2026-05-29T00:00:00Z")
    # Deposit and buy AFTER moving the clock so accruals cover May 29-31.
    # (fixtures placed the position at the default clock; cash is unchanged.)
    run_sweep()
    set_clock("2026-05-30T00:00:00Z")
    run_sweep()
    set_clock("2026-05-31T00:00:00Z")
    run_sweep()
    set_clock("2026-06-01T00:00:00Z")
    sweep_result = run_sweep()
    assert sweep_result["interest_posts_created"] == 1

    posts_resp = api_client.list_interest_entries(
        account_id, TEST_USERS["supervisor_headers"], params={"entry_type": "MONTHLY_POST"}
    )
    posts, _ = validate_paginated(posts_resp)
    assert len(posts) == 1
    # 3 * 917 = 2751 (May 29, 30, 31 accruals).
    assert posts[0]["amount_cents"] == 2_751

    account = get_account(account_id)
    assert account["cash_balance_cents"] == -3_002_751

    dailies_resp = api_client.list_interest_entries(
        account_id, TEST_USERS["supervisor_headers"], params={"entry_type": "DAILY_ACCRUAL"}
    )
    dailies, _ = validate_paginated(dailies_resp)
    may_dailies = [e for e in dailies if e["accrual_date"].startswith("2026-05")]
    assert len(may_dailies) == 3
    assert all(e["posted"] is True for e in may_dailies)


def test_rate_tier_closed_window_overlap_forbidden(api):
    """PRD §3.9: "Two tiers of the same `tier_level` may not share any calendar
    date; back-to-back windows are allowed, and an overlapping submission is
    rejected with `ERR_RATE_TIER_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/rate_tier_closed_window_overlap_forbidden_back_to_back_allowed
    """
    create_rate_tier(
        tier_level=1,
        min_balance_cents=0,
        annual_rate_bps=1200,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    # Overlapping: 2026-06-01..2027-05-31 shares dates with 2026-01-01..12-31.
    resp = api_client.create_rate_tier(
        create_rate_tier_payload(
            tier_level=1,
            min_balance_cents=0,
            annual_rate_bps=1150,
            effective_from="2026-06-01",
            effective_to="2027-05-31",
        ),
        TEST_USERS["supervisor_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_RATE_TIER_OVERLAP)


def test_rate_tier_back_to_back_window_allowed(api):
    """PRD §3.9: "Two tiers of the same `tier_level` may not share any calendar
    date; back-to-back windows are allowed, and an overlapping submission is
    rejected with `ERR_RATE_TIER_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/rate_tier_closed_window_overlap_forbidden_back_to_back_allowed
    """
    create_rate_tier(
        tier_level=1,
        min_balance_cents=0,
        annual_rate_bps=1200,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    # Back-to-back: 2027-01-01 shares no calendar date with ...2026-12-31.
    resp = api_client.create_rate_tier(
        create_rate_tier_payload(
            tier_level=1,
            min_balance_cents=0,
            annual_rate_bps=1150,
            effective_from="2027-01-01",
            effective_to=None,
        ),
        TEST_USERS["supervisor_headers"],
    )
    tier = validate_success(resp, expected_status=201)
    assert tier["effective_from"] == "2027-01-01"
    assert tier["effective_to"] is None
