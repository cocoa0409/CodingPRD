"""Multi-term formulas whose evaluation granularity and ordering are pinned."""

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    INTERNATIONAL_SCOUT_HEADERS,
    ApiClient,
    assert_money,
    assert_pool_ledger_identity,
    assert_status,
    fixtures,
)

# ---------------------------------------------------------------------------
# Instance 1 — per-category rounding before summation
# ---------------------------------------------------------------------------

_HAMMERHEADS_AFFILIATE = {
    "name": "Jupiter Hammerheads",
    "level": "SINGLE_A",
    "market_city": "Jupiter",
    "meal_stipend_cents_per_day": 2600,
}

_HAMMERHEADS_AGREEMENT = {
    "term_start_date": "2026-01-01",
    "term_end_date": "2026-12-31",
    "facility_standard_tier": "TIER_2",
    "club_reimbursement_cap_cents": 5000000,
    "minimum_active_players": 0,
    "housing_expense_cents": 1200003,
    "meal_expense_cents": 640005,
    "travel_expense_cents": 355007,
    "upkeep_expense_cents": 480009,
}


def _hammerheads_draft_agreement(api: ApiClient) -> dict:
    affiliate = fixtures.create_affiliate(
        api, COMPLIANCE_OFFICER_HEADERS, **_HAMMERHEADS_AFFILIATE
    )
    agreement = fixtures.create_agreement(api, affiliate["id"], **_HAMMERHEADS_AGREEMENT)
    return {"affiliate_id": affiliate["id"], "agreement_id": agreement["id"]}


def test_each_category_line_is_rounded_before_the_four_lines_are_added(api):
    """Two of the four products end in exactly a quarter cent.

    "The per-category club line is therefore the gross figure for that category
    multiplied by that category's club share, rounded half-up to a whole number
    of cents. This per-line rounding happens before any addition: the
    obligation is the sum of the four rounded lines, and never the rounding of
    a sum of exact products."

    Design: Difficulty/combinatorial_formula/expense_allocation_rounds_per_category_then_sums
    """
    bundle = _hammerheads_draft_agreement(api)

    submitted = fixtures.submit_agreement(api, bundle["agreement_id"], bundle["affiliate_id"])

    assert_money(
        submitted["provisional_club_obligation_cents"],
        1759014,
        "provisional_club_obligation_cents",
    )
    assert submitted["provisional_club_obligation_cents"] != 1759015, (
        "1759015 is the figure produced by rounding the summed exact products "
        "1759014.50 instead of rounding each category line first"
    )
    assert_money(submitted["affiliate_overflow_cents"], 0, "affiliate_overflow_cents")


def test_the_four_rounded_lines_reconcile_to_the_provisional_obligation(api):
    """Housing 900002, meals 384003, travel 355007 and upkeep 120002.

    "The provisional computation, which runs on submission of the licence,
    reads the four declared figures `housing_expense_cents`,
    `meal_expense_cents`, `travel_expense_cents` and `upkeep_expense_cents`."

    Design: Difficulty/combinatorial_formula/expense_allocation_rounds_per_category_then_sums
    """
    bundle = _hammerheads_draft_agreement(api)

    submitted = fixtures.submit_agreement(api, bundle["agreement_id"], bundle["affiliate_id"])

    # 1200003 * 0.75 == 900002.25 -> 900002 and 480009 * 0.25 == 120002.25 -> 120002.
    assert_money(
        submitted["provisional_club_obligation_cents"],
        900002 + 384003 + 355007 + 120002,
        "provisional obligation as the sum of the four rounded lines",
    )
    assert_status(submitted, "SUBMITTED", "AffiliationAgreement")
    assert submitted["posture"] == "FROZEN", (
        f"a submitted licence stays FROZEN until activation, got {submitted['posture']}"
    )


# ---------------------------------------------------------------------------
# Instance 2 — the taxable overage is measured before the forfeit
# ---------------------------------------------------------------------------


def _academy_pool_with_first_signing_approved(api: ApiClient) -> dict:
    """An academy, a 5000000 pool, and a first signing approved at 5000000."""
    club = fixtures.licensed_academy(
        api,
        affiliate_overrides={
            "name": "Boca Chica Academy",
            "market_city": "Boca Chica",
            "meal_stipend_cents_per_day": 2500,
            "housing_beds": 40,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_3",
            "club_reimbursement_cap_cents": 100000,
            "minimum_active_players": 0,
        },
    )
    pool = fixtures.create_pool(api, season_year=2026, base_pool_cents=5000000, trade_adjustment_cents=0)
    first_player = fixtures.create_player(
        api,
        INTERNATIONAL_SCOUT_HEADERS,
        full_name="Elian Reyes",
        origin="INTERNATIONAL_FA",
        signed_date="2026-01-15",
    )
    second_player = fixtures.create_player(
        api,
        INTERNATIONAL_SCOUT_HEADERS,
        full_name="Yoel Castro",
        origin="INTERNATIONAL_FA",
        signed_date="2026-01-15",
    )
    first_signing = fixtures.create_signing(
        api, pool["id"], first_player["id"], club["affiliate_id"], bonus_cents=5000000
    )
    approved_first = fixtures.dispose_signing(api, first_signing["id"], "APPROVE")
    return {
        "affiliate_id": club["affiliate_id"],
        "pool_id": pool["id"],
        "first_signing": approved_first,
        "first_signing_id": first_signing["id"],
        "second_player_id": second_player["id"],
    }


def test_the_tier_three_forfeit_does_not_enlarge_the_taxable_overage(api):
    """The overage is measured against the pre-forfeit effective pool.

    "Third, and only after the tax has been computed, the third-tier forfeit is
    applied. `tier3_breach` is set true when the total overage is strictly
    above 1000000 cents *and* the prior overage was at most 1000000 cents —
    that is, when this particular approval is the one that crossed the second
    ceiling — and on such a breach 250000 cents is added to the pool's
    `forfeited_cents`."

    Design: Difficulty/combinatorial_formula/signing_pool_charge_evaluation_order_pinned_before_forfeit
    """
    bundle = _academy_pool_with_first_signing_approved(api)

    assert_money(
        bundle["first_signing"]["overage_tax_cents"], 0, "first signing overage_tax_cents"
    )
    assert bundle["first_signing"]["tier3_breach"] is False, (
        "an approval that exactly exhausts the pool has not breached the third tier"
    )
    pool_after_first = fixtures.read_pool(api, bundle["pool_id"])
    assert_money(pool_after_first["allocated_cents"], 5000000, "allocated_cents")
    assert_status(pool_after_first, "OPEN", "SigningPool")

    second_signing = fixtures.create_signing(
        api,
        bundle["pool_id"],
        bundle["second_player_id"],
        bundle["affiliate_id"],
        bonus_cents=1200000,
    )
    approved = fixtures.dispose_signing(api, second_signing["id"], "APPROVE")

    # 500000 * 0.75 + 500000 * 1.00 + 200000 * 1.00 == 375000 + 500000 + 200000.
    assert_money(approved["overage_tax_cents"], 375000 + 500000 + 200000, "overage_tax_cents")
    assert approved["overage_tax_cents"] != 1325000, (
        "1325000 is the tax produced when the 250000 forfeit is subtracted from "
        "the pool before the overage is measured"
    )
    assert approved["tier3_breach"] is True, (
        "an approval taking the total overage from 0 to 1200000 crosses the second ceiling"
    )
    assert_money(approved["pool_charge_cents"], 1200000, "pool_charge_cents")


def test_the_pool_ledger_recomputes_with_the_post_forfeit_effective_figure(api):
    """The forfeit lands in the ledger even though it stayed out of the tax.

    "Fourth, the pool's ledger is recomputed with the post-forfeit figure:
    `effective_pool_cents` becomes the base allotment plus the trade adjustment
    minus the now-updated `forfeited_cents`; `allocated_cents` becomes the new
    allocated figure; `remaining_cents` becomes the effective pool minus the
    allocated amount, which may be negative; and the pool's status becomes
    `HARD_CAPPED` when the allocated amount is strictly greater than the
    effective pool, or stays `OPEN` otherwise."

    Design: Difficulty/combinatorial_formula/signing_pool_charge_evaluation_order_pinned_before_forfeit
    """
    bundle = _academy_pool_with_first_signing_approved(api)

    second_signing = fixtures.create_signing(
        api,
        bundle["pool_id"],
        bundle["second_player_id"],
        bundle["affiliate_id"],
        bonus_cents=1200000,
    )
    fixtures.dispose_signing(api, second_signing["id"], "APPROVE")

    pool = fixtures.read_pool(api, bundle["pool_id"])
    assert_money(pool["forfeited_cents"], 250000, "forfeited_cents")
    assert_money(pool["effective_pool_cents"], 4750000, "effective_pool_cents")
    assert_money(pool["allocated_cents"], 6200000, "allocated_cents")
    assert_money(pool["remaining_cents"], -1450000, "remaining_cents")
    assert_money(pool["overage_tax_accrued_cents"], 1075000, "overage_tax_accrued_cents")
    assert_status(pool, "HARD_CAPPED", "SigningPool")
    assert_pool_ledger_identity(pool)
