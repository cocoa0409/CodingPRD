"""Media-value valuation and retainer billing — dual-variant and combinatorial calculations."""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    setup_campaign_with_media_list,
    create_coverage,
    setup_open_period,
    setup_period_with_approved_entries,
    log_time_entry,
    close_period_current_version,
    TEST_USERS,
)

AM = TEST_USERS["account_manager_headers"]
MS = TEST_USERS["media_specialist_headers"]


# =========================================================================== #
# dual_variant_calc / media_value_estimated_vs_verified_on_coverage
# =========================================================================== #

def test_coverage_estimated_haircut_then_verified_full_value(api):
    """PRD §3.9: "The **estimated** variant, computed at logging and stored as
    `estimated_media_value_cents`, applies a provisional haircut: it multiplies the raw
    value by 0.8 and rounds half-up to whole cents. The **verified** variant, computed at
    verification and stored as `media_value_cents`, applies no haircut: it rounds the full
    raw value half-up to whole cents."

    ENTERPRISE / NATIONAL(MUV 2_000_000 -> reach 3.0) / DA 80 (auth 1.8) / POSITIVE(1.0)
    / FEATURE(1.0): raw = 500000*3.0*1.8*1.0*1.0*1.5 = 4050000.
    estimated = round(4050000*0.8) = 3240000; verified = 4050000.

    Design: Difficulty/dual_variant_calc/media_value_estimated_vs_verified_on_coverage
    """
    scn = setup_campaign_with_media_list(
        client_overrides={"account_tier": "ENTERPRISE"},
        outlet_overrides={"tier": "NATIONAL", "monthly_unique_visitors": 2000000, "domain_authority": 80},
    )
    cov = create_coverage(
        scn["campaign"]["id"], scn["journalist"]["id"],
        sentiment="POSITIVE", prominence="FEATURE",
    )
    assert cov["estimated_media_value_cents"] == 3240000, \
        f"estimated should be 3240000, got {cov['estimated_media_value_cents']}"

    verified = validate_success(api.verify_coverage(cov["id"], MS))
    assert verified["media_value_cents"] == 4050000, \
        f"verified media_value_cents should be 4050000, got {verified['media_value_cents']}"
    assert verified["status"] == "VERIFIED"


def test_coverage_estimated_value_fixed_at_logging_independent_of_verify(api):
    """PRD §3.9: "The **estimated** variant, computed at logging and stored as
    `estimated_media_value_cents`, applies a provisional haircut: it multiplies the raw
    value by 0.8 and rounds half-up to whole cents."

    The estimated value (3240000) is fixed at logging and remains so on the same row
    after verification, while the verified field carries the un-haircut value (4050000).

    Design: Difficulty/dual_variant_calc/media_value_estimated_vs_verified_on_coverage
    """
    scn = setup_campaign_with_media_list(
        client_overrides={"account_tier": "ENTERPRISE"},
        outlet_overrides={"tier": "NATIONAL", "monthly_unique_visitors": 2000000, "domain_authority": 80},
    )
    cov = create_coverage(
        scn["campaign"]["id"], scn["journalist"]["id"],
        sentiment="POSITIVE", prominence="FEATURE",
    )
    validate_success(api.verify_coverage(cov["id"], MS))
    fetched = validate_success(api.get_coverage(cov["id"], MS))
    assert fetched["estimated_media_value_cents"] == 3240000, \
        "estimated value must remain the logging-time 3240000 after verify"
    assert fetched["media_value_cents"] == 4050000


# =========================================================================== #
# dual_variant_calc / retainer_billing_provisional_vs_final_on_period
# combinatorial_formula / retainer_billing_round_order_divergence_mode_b
# =========================================================================== #

def test_retainer_provisional_round_then_sum_diverges_from_final(api):
    """PRD §3.11: "The **provisional** total, recomputed live as `provisional_total_cents`
    whenever a time entry is logged, approved, or voided, includes entries in `SUBMITTED` or
    `APPROVED` status, and it rounds each entry's real overage amount half-up to whole cents
    and then sums those rounded per-entry amounts."
    PRD §3.11: "The **final** total, computed once when the period is closed and stored as
    `final_total_cents`, includes only entries in `APPROVED` status, and it sums the real
    overage amounts across those approved entries first and rounds the single sum half-up to
    whole cents at the end."

    cap=10, rate=333; entries 10.0h, 0.5h, 0.5h, 0.5h (3 overage entries of 0.5h each).
    provisional = round(166.5)*3 = 167*3 = 501; final = round(499.5) = 500.

    Design: Difficulty/dual_variant_calc/retainer_billing_provisional_vs_final_on_period
    """
    client, period, _ = setup_period_with_approved_entries(
        monthly_hours_cap=10, overage_rate_cents=333,
        hours_list=[10.0, 0.5, 0.5, 0.5], period_month="2026-03",
    )
    assert period["provisional_total_cents"] == 501, \
        f"provisional should be 501, got {period['provisional_total_cents']}"

    closed = close_period_current_version(period["id"])
    assert closed["final_total_cents"] == 500, \
        f"final should be 500, got {closed['final_total_cents']}"
    assert closed["status"] == "CLOSED"


def test_retainer_round_order_one_cent_gap_provisional_vs_final(api):
    """PRD §3.11: "The **provisional** total, recomputed live as `provisional_total_cents`
    whenever a time entry is logged, approved, or voided, includes entries in `SUBMITTED` or
    `APPROVED` status, and it rounds each entry's real overage amount half-up to whole cents
    and then sums those rounded per-entry amounts."
    PRD §3.11: "The **final** total, computed once when the period is closed and stored as
    `final_total_cents`, includes only entries in `APPROVED` status, and it sums the real
    overage amounts across those approved entries first and rounds the single sum half-up to
    whole cents at the end."

    The same APPROVED set (cap=10, rate=333, three 0.5h overage entries) yields
    provisional_total_cents=501 (167*3) but final_total_cents=500 (round(499.5)); the
    1-cent gap is purely the rounding-order axis.

    Design: Difficulty/combinatorial_formula/retainer_billing_round_order_divergence_mode_b
    """
    client, period, _ = setup_period_with_approved_entries(
        monthly_hours_cap=10, overage_rate_cents=333,
        hours_list=[10.0, 0.5, 0.5, 0.5], period_month="2026-04",
        logger_headers=MS,
    )
    assert period["provisional_total_cents"] == 501
    closed = close_period_current_version(period["id"])
    assert closed["final_total_cents"] == 500
    assert closed["provisional_total_cents"] == 501, \
        "provisional stays 501 even after the final is computed at close"


def test_provisional_includes_submitted_entries_live(api):
    """PRD §3.11: "The **provisional** total, recomputed live as `provisional_total_cents`
    whenever a time entry is logged, approved, or voided, includes entries in `SUBMITTED` or
    `APPROVED` status, and it rounds each entry's real overage amount half-up to whole cents
    and then sums those rounded per-entry amounts."

    With one in-cap 10.0h entry and three SUBMITTED 0.5h overage entries (cap=10, rate=333),
    the live provisional total is the round-per-entry sum 167*3 = 501 before any approval.

    Design: Difficulty/dual_variant_calc/retainer_billing_provisional_vs_final_on_period
    """
    client, period = setup_open_period(
        monthly_hours_cap=10, overage_rate_cents=333, period_month="2026-12")
    log_time_entry(period["id"], 10.0, work_type="STRATEGY")
    log_time_entry(period["id"], 0.5, work_type="WRITING")
    log_time_entry(period["id"], 0.5, work_type="WRITING")
    log_time_entry(period["id"], 0.5, work_type="WRITING")

    fetched = get_success_data(api.get_retainer_period(period["id"], AM))
    assert fetched["provisional_total_cents"] == 501, \
        f"live provisional (round-then-sum over SUBMITTED) should be 501, got {fetched['provisional_total_cents']}"
    assert fetched["final_total_cents"] is None, "final_total_cents is null until the period is CLOSED"


def test_final_total_null_until_close_then_sum_then_round(api):
    """PRD §3.11: "A new period opens in `OPEN` with `hours_consumed` zero and `version` 1; its
    `status` is `OPEN` or `CLOSED`, and `final_total_cents` is null until the period is
    closed."
    PRD §3.11: "The **final** total, computed once when the period is closed and stored as
    `final_total_cents`, includes only entries in `APPROVED` status, and it sums the real
    overage amounts across those approved entries first and rounds the single sum half-up to
    whole cents at the end."

    final_total_cents is null while OPEN; after close (cap=10, rate=333, three approved 0.5h
    overage entries) it is round(499.5) = 500, one cent below the provisional 501.

    Design: Difficulty/combinatorial_formula/retainer_billing_round_order_divergence_mode_b
    """
    client, period, _ = setup_period_with_approved_entries(
        monthly_hours_cap=10, overage_rate_cents=333,
        hours_list=[10.0, 0.5, 0.5, 0.5], period_month="2027-01",
    )
    assert period["final_total_cents"] is None, "final_total_cents must be null while OPEN"
    closed = close_period_current_version(period["id"])
    assert closed["status"] == "CLOSED"
    assert closed["final_total_cents"] == 500, \
        f"sum-then-round final should be 500, got {closed['final_total_cents']}"


# =========================================================================== #
# combinatorial_formula / media_value_nested_min_and_tier_selection_mode_a
# =========================================================================== #

def test_media_value_reach_clamped_and_tier_selected(api):
    """PRD §3.9: "Multiply by a reach factor equal to one plus the outlet's
    `monthly_unique_visitors` divided by one million, but cap that reach factor at 3.0 —
    that is, use the smaller of the computed reach factor and 3.0."

    STANDARD / REGIONAL(200000 base) / MUV 2_500_000 (reach uncapped 3.5 -> clamp 3.0) /
    DA 50 (auth 1.5) / NEUTRAL(0.5) / MENTION(0.6):
    raw = 200000*3.0*1.5*0.5*0.6*1.0 = 270000.

    Design: Difficulty/combinatorial_formula/media_value_nested_min_and_tier_selection_mode_a
    """
    scn = setup_campaign_with_media_list(
        client_overrides={"account_tier": "STANDARD"},
        campaign_overrides={"objective": "AWARENESS", "target_beat": "CONSUMER"},
        outlet_overrides={"tier": "REGIONAL", "monthly_unique_visitors": 2500000, "domain_authority": 50},
        journalist_overrides={"beat": "CONSUMER"},
    )
    cov = create_coverage(
        scn["campaign"]["id"], scn["journalist"]["id"],
        sentiment="NEUTRAL", prominence="MENTION",
    )
    verified = validate_success(api.verify_coverage(cov["id"], MS))
    assert verified["media_value_cents"] == 270000, \
        f"clamped reach should give 270000, got {verified['media_value_cents']}"
    assert verified["status"] == "VERIFIED"


def test_media_value_clamp_caps_below_uncapped_product(api):
    """PRD §3.9: "Multiply by a reach factor equal to one plus the outlet's
    `monthly_unique_visitors` divided by one million, but cap that reach factor at 3.0 —
    that is, use the smaller of the computed reach factor and 3.0."

    With reach clamped to 3.0 the verified value is 270000; an unclamped reach of 3.5 would
    have produced 315000, so the clamp strictly lowers the figure.

    Design: Difficulty/combinatorial_formula/media_value_nested_min_and_tier_selection_mode_a
    """
    scn = setup_campaign_with_media_list(
        client_overrides={"account_tier": "STANDARD"},
        outlet_overrides={"tier": "REGIONAL", "monthly_unique_visitors": 2500000, "domain_authority": 50},
    )
    cov = create_coverage(
        scn["campaign"]["id"], scn["journalist"]["id"],
        sentiment="NEUTRAL", prominence="MENTION",
    )
    verified = validate_success(api.verify_coverage(cov["id"], MS))
    assert verified["media_value_cents"] == 270000
    assert verified["media_value_cents"] != 315000, "reach must be clamped, not uncapped 3.5"
