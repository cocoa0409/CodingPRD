"""Derived figures read at their declared boundaries: recognition tiers, the
banded insurance premium, the storage-fee ladder, candidate-set filtering, the
tax-exempt split, and the honorarium remainder."""

import pytest

from test_helpers import (
    CALL_MANAGER,
    FINANCE_A,
    create_sale_payload,
    assert_same_instant,
    create_sponsor_payload,
    fixtures,
    make_artist_headers,
    validate_paginated,
    validate_success,
)

# ─── Recognition tiers ────────────────────────────────

CONTRIBUTIONS_AND_TIERS = [
    (249999, "NONE"),
    (250000, "BRONZE"),
    (999999, "BRONZE"),
    (1000000, "SILVER"),
    (5000000, "PRESENTING"),
]

# ─── Insurance premium bands ──────────────────────────

CAPPED_WORKS = [
    {
        "title": "Cap Line A", "medium_category": "PAINTING",
        "width_cm": 90.0, "height_cm": 60.0, "depth_cm": 4.0, "weight_kg": 6.0,
        "declared_value_cents": 5000000,
    },
    {
        "title": "Cap Line B", "medium_category": "PHOTOGRAPHY",
        "width_cm": 100.0, "height_cm": 70.0, "depth_cm": 4.0, "weight_kg": 5.0,
        "declared_value_cents": 5000000,
    },
]

ONE_CAPPED_WORK_INSURED = 5000000
TWO_CAPPED_WORKS_INSURED = 10000000
PREMIUM_FLOOR_CENTS = 25000
# 50 units at 350 cents.
RAW_PREMIUM_AT_FIFTY_UNITS = 17500
# 50 units at 350 plus 50 units at 275.
PREMIUM_AT_HUNDRED_UNITS = 31250
PER_ARTWORK_CEILING_WOULD_GIVE = 35000

# ─── Storage-fee ladder ───────────────────────────────

UNCLAIMED_WORKS = [
    {
        "title": "Ridge Line", "medium_category": "PAINTING",
        "width_cm": 90.0, "height_cm": 60.0, "depth_cm": 4.0, "weight_kg": 6.0,
        "declared_value_cents": 400000,
    },
    {
        "title": "Pocket Study", "medium_category": "PHOTOGRAPHY",
        "width_cm": 30.0, "height_cm": 20.0, "depth_cm": 2.0, "weight_kg": 1.0,
        "declared_value_cents": 5000,
    },
]

CLAIM_DEADLINE_AT = "2027-01-12T00:00:00Z"
DEADLINE_PLUS_TWO_DAYS = "2027-01-14T00:00:00Z"
DEADLINE_PLUS_THIRTY_ONE_DAYS = "2027-02-12T00:00:00Z"

DAILY_STORAGE_CENTS = 1500
# The small work's fee is pinned by half of its declared value.
SMALL_WORK_FEE_CAP_CENTS = 2500
FIRST_SWEEP_TOTAL_CENTS = 3000
SECOND_SWEEP_TOTAL_CENTS = 7000
THIRD_SWEEP_TOTAL_CENTS = 50500
LARGE_WORK_FEE_AT_DAY_THIRTY_TWO = 48000

# ─── Candidate-set filtering ──────────────────────────

LOW_SCORING_WORK = {
    "title": "Ridge Line", "medium_category": "PAINTING",
    "width_cm": 90.0, "height_cm": 60.0, "depth_cm": 4.0, "weight_kg": 6.0,
    "declared_value_cents": 400000,
}
HIGH_SCORING_WORK = {
    "title": "Salt Flat", "medium_category": "PHOTOGRAPHY",
    "width_cm": 100.0, "height_cm": 70.0, "depth_cm": 4.0, "weight_kg": 5.0,
    "declared_value_cents": 300000,
}
LOW_CERTIFIED_MEAN = 7.25
HIGH_CERTIFIED_MEAN = 9.00

# ─── Tax-exempt split ─────────────────────────────────

SALE_PRICE_CENTS = 250000
EXEMPT_COMMISSION_CENTS = 87500
EXEMPT_PAYABLE_CENTS = 162500
TAX_INCLUSIVE_PAYABLE_CENTS = 149425

# ─── Honorarium remainder ─────────────────────────────

HONORARIUM_CENTS = 50000
HUNDRED_MINUTES = 100
THREE_EQUAL_SITTINGS = [
    ("2026-10-06T09:00:00Z", "2026-10-06T10:40:00Z"),
    ("2026-10-07T09:00:00Z", "2026-10-07T10:40:00Z"),
    ("2026-10-08T09:00:00Z", "2026-10-08T10:40:00Z"),
]
THREE_WAY_SHARES = [16667, 16667, 16666]


def test_every_recognition_floor_is_inclusive_at_the_exact_cent(api):
    """PRD §3.8: "The `recognition_tier` is derived from the contribution against
    four inclusive floors: a contribution of at least 5,000,000 cents is
    `PRESENTING`; at least 2,500,000 is `GOLD`; at least 1,000,000 is `SILVER`; at
    least 250,000 is `BRONZE`; anything below that is `NONE`. Every floor is
    inclusive, so 999,999 cents is `BRONZE` while exactly 1,000,000 is `SILVER`."

    Design: Corner/calculations/sponsor_recognition_tier_constants_at_every_inclusive_floor
    """
    fixtures.set_clock(fixtures.CLOCK_CALL_OPEN)
    exhibition = fixtures.create_exhibition()

    for contribution, expected_tier in CONTRIBUTIONS_AND_TIERS:
        sponsor = validate_success(
            api.create_sponsor(
                create_sponsor_payload(
                    exhibition["id"], name=f"Sponsor at {contribution}",
                    contribution_cents=contribution,
                    purchase_award_budget_cents=0,
                ),
                CALL_MANAGER,
            ),
            201,
        )
        assert sponsor["contribution_cents"] == contribution
        assert sponsor["recognition_tier"] == expected_tier
        assert sponsor["purchase_award_committed_cents"] == 0

    _, meta = validate_paginated(
        api.list_sponsors(
            CALL_MANAGER,
            params={
                "exhibition_id": exhibition["id"],
                "recognition_tier": "BRONZE",
            },
        )
    )
    assert meta["total_count"] == 2, "the floor cent and the cent below the next"


def test_the_premium_bands_are_allocated_once_over_the_aggregate(api):
    """PRD §3.7: "The resulting unit count is then allocated across three bands:
    the first 50 units at 350 cents each, the next 150 units (units 51 through
    200) at 275 cents each, and every unit beyond 200 at 190 cents each."

    Design: Corner/calculations/insurance_premium_tiered_rates_straddle_the_first_two_tiers
    """
    ctx = fixtures.setup_installation_show(works=CAPPED_WORKS)
    exhibition_id = ctx["exhibition"]["id"]
    first, second = ctx["acceptance_result"]["accepted_artwork_ids"]

    fixtures.file_condition_report(first, "INTAKE", "A")
    after_first = fixtures.read_exhibition(exhibition_id)
    assert after_first["insured_value_total_cents"] == ONE_CAPPED_WORK_INSURED
    assert after_first["insurance_premium_cents"] == PREMIUM_FLOOR_CENTS, (
        "fifty units at 350 cents raise a raw premium of 17,500, below the floor"
    )
    assert RAW_PREMIUM_AT_FIFTY_UNITS < PREMIUM_FLOOR_CENTS

    fixtures.file_condition_report(second, "INTAKE", "A")
    after_second = fixtures.read_exhibition(exhibition_id)
    assert after_second["insured_value_total_cents"] == TWO_CAPPED_WORKS_INSURED
    assert after_second["insurance_premium_cents"] == PREMIUM_AT_HUNDRED_UNITS
    assert after_second["insurance_premium_cents"] != (
        PER_ARTWORK_CEILING_WOULD_GIVE
    ), "rounding the unit count per artwork instead would charge 35,000"


def test_the_storage_ladder_starts_on_the_deadline_day_caps_then_forfeits(api):
    """PRD §3.10: "For each work in scope, the number of overdue days is the whole
    number of 86,400-second days elapsed since `claim_deadline_at`, truncated
    downward, **plus one** — the deadline day itself counts as day one, so a sweep
    run at exactly `claim_deadline_at` already accrues one day. The work's
    `storage_fee_cents` is then the lesser of two figures: 1,500 cents multiplied
    by the overdue-day count, and half of the work's `declared_value_cents`
    truncated downward."

    PRD §3.10: "When the overdue-day count exceeds a grace period of 30 days —
    strictly greater than 30, so day 31 is the first forfeiting day — the work
    moves `RETURN_PENDING → UNCLAIMED_FORFEIT` and the council takes title."

    Design: Corner/calculations/unclaimed_storage_accrual_day_one_at_deadline_then_cap_then_forfeit
    """
    ctx = fixtures.setup_on_view_show(works=UNCLAIMED_WORKS)
    exhibition_id = ctx["exhibition"]["id"]
    large, small = ctx["accepted_artwork_ids"]

    fixtures.close_show(exhibition_id)
    for artwork_id in (large, small):
        waiting = fixtures.read_artwork(artwork_id)
        assert waiting["status"] == "RETURN_PENDING"
        assert_same_instant(waiting["claim_deadline_at"], CLAIM_DEADLINE_AT)
    closed = fixtures.read_exhibition(exhibition_id)
    assert closed["insured_value_total_cents"] == 0
    assert closed["insurance_premium_cents"] == 0

    fixtures.set_clock(CLAIM_DEADLINE_AT)
    first_sweep = fixtures.run_unclaimed_sweep(exhibition_id)
    assert first_sweep["storage_fee_total_cents"] == FIRST_SWEEP_TOTAL_CENTS
    assert first_sweep["forfeited_artwork_ids"] == []
    assert_same_instant(first_sweep["swept_at"], CLAIM_DEADLINE_AT)
    for artwork_id in (large, small):
        assert fixtures.read_artwork(artwork_id)["storage_fee_cents"] == (
            DAILY_STORAGE_CENTS
        ), "a sweep at exactly the deadline already accrues day one"

    fixtures.set_clock(DEADLINE_PLUS_TWO_DAYS)
    second_sweep = fixtures.run_unclaimed_sweep(exhibition_id)
    assert second_sweep["storage_fee_total_cents"] == SECOND_SWEEP_TOTAL_CENTS
    assert fixtures.read_artwork(large)["storage_fee_cents"] == (
        DAILY_STORAGE_CENTS * 3
    )
    assert fixtures.read_artwork(small)["storage_fee_cents"] == (
        SMALL_WORK_FEE_CAP_CENTS
    ), "half of a 5,000-cent declared value pins the small work"

    fixtures.set_clock(DEADLINE_PLUS_THIRTY_ONE_DAYS)
    third_sweep = fixtures.run_unclaimed_sweep(exhibition_id)
    assert third_sweep["storage_fee_total_cents"] == THIRD_SWEEP_TOTAL_CENTS
    assert sorted(third_sweep["forfeited_artwork_ids"]) == sorted([large, small])
    assert fixtures.read_artwork(large)["storage_fee_cents"] == (
        LARGE_WORK_FEE_AT_DAY_THIRTY_TWO
    )
    assert fixtures.read_artwork(small)["storage_fee_cents"] == (
        SMALL_WORK_FEE_CAP_CENTS
    )
    for artwork_id in (large, small):
        assert fixtures.read_artwork(artwork_id)["status"] == "UNCLAIMED_FORFEIT"

    artist = fixtures.read_artist(ctx["artist"]["id"])
    assert artist["unclaimed_forfeit_count"] == 2
    assert artist["payout_hold"] is True

    fourth_sweep = fixtures.run_unclaimed_sweep(exhibition_id)
    assert fourth_sweep["swept_artwork_ids"] == [], (
        "a forfeited work is outside the sweep's input set"
    )
    assert fourth_sweep["storage_fee_total_cents"] == 0


def test_a_withdrawn_entrys_work_never_enters_the_candidate_set(api):
    """PRD §3.6: "The candidate set is every artwork of the exhibition whose
    `status` is `SHORTLISTED` **and** whose owning entry's `status` is
    `SUBMITTED`. Works belonging to a withdrawn entry, works already `DECLINED`,
    and works whose entry never cleared its fee are all outside the set."

    Design: Corner/calculations/acceptance_list_input_set_excludes_withdrawn_entry_works
    """
    exhibition = fixtures.open_call()
    artist_a = fixtures.register_artist(
        legal_name="Ana Ruiz", member_status="MEMBER"
    )
    artist_b = fixtures.register_artist(
        legal_name="Bo Nakamura", member_status="MEMBER"
    )
    _, works_a = fixtures.setup_submitted_entry(
        exhibition["id"], artist_a, [LOW_SCORING_WORK]
    )
    entry_b, works_b = fixtures.setup_submitted_entry(
        exhibition["id"], artist_b, [HIGH_SCORING_WORK]
    )

    juror = fixtures.invite_and_confirm_juror(
        expertise_categories=["PAINTING", "PHOTOGRAPHY", "SCULPTURE"]
    )
    jury_round, juror = fixtures.setup_open_round(exhibition["id"], juror=juror)
    fixtures.submit_score(jury_round["id"], juror, works_a[0]["id"], 7, 7, 8)
    fixtures.submit_score(jury_round["id"], juror, works_b[0]["id"], 9, 9, 9)
    fixtures.set_round_status(jury_round["id"], "SCORING_COMPLETE")

    assert fixtures.read_artwork(works_a[0]["id"])[
        "certified_mean_score"
    ] == pytest.approx(LOW_CERTIFIED_MEAN, abs=0.01)
    assert fixtures.read_artwork(works_b[0]["id"])[
        "certified_mean_score"
    ] == pytest.approx(HIGH_CERTIFIED_MEAN, abs=0.01)
    fixtures.set_round_status(jury_round["id"], "CLOSED")

    withdrawn = validate_success(
        api.withdraw_entry(entry_b["id"], make_artist_headers(artist_b["id"]))
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert fixtures.read_artwork(works_b[0]["id"])["status"] == "WITHDRAWN"

    result = fixtures.run_acceptance_list(exhibition["id"])
    assert result["accepted_artwork_ids"] == [works_a[0]["id"]]
    assert result["accepted_count"] == 1
    assert result["waitlisted_count"] == 0
    assert result["declined_count"] == 0, (
        "the top-scoring work appears in no list at all"
    )
    assert result["exhibition_status"] == "RESULTS_PUBLISHED"

    orphan = fixtures.read_artwork(works_b[0]["id"])
    assert orphan["status"] == "WITHDRAWN", "not DECLINED"
    assert orphan["certified_mean_score"] == pytest.approx(
        HIGH_CERTIFIED_MEAN, abs=0.01
    )
    assert fixtures.read_exhibition(exhibition["id"])["accepted_count"] == 1


def test_a_tax_exempt_sale_taxes_nothing_and_commissions_the_whole_price(api):
    """PRD §3.9: "When `tax_exempt` is true, `taxable_base_cents` is the whole
    `sale_price_cents` and `sales_tax_cents` is 0."

    Design: Corner/calculations/tax_exempt_sale_zeroes_tax_and_commissions_the_full_price
    """
    ctx = fixtures.setup_on_view_show()
    artwork_id = ctx["accepted_artwork_ids"][0]

    sale = validate_success(
        api.create_sale(
            create_sale_payload(
                artwork_id, buyer_name="Museum Trust",
                buyer_region_code="CA-SF", tax_exempt=True,
            ),
            FINANCE_A,
        ),
        201,
    )

    assert sale["sale_type"] == "GALLERY_SALE"
    assert sale["tax_exempt"] is True
    assert sale["taxable_base_cents"] == SALE_PRICE_CENTS, (
        "no division by one plus the tax rate"
    )
    assert sale["sales_tax_cents"] == 0
    assert sale["commission_cents"] == EXEMPT_COMMISSION_CENTS
    assert sale["artist_payable_cents"] == EXEMPT_PAYABLE_CENTS
    assert sale["artist_payable_cents"] > TAX_INCLUSIVE_PAYABLE_CENTS, (
        "the exempt artist nets more than the tax-inclusive variant on the same "
        "headline price"
    )
    assert sale["buyer_total_cents"] == SALE_PRICE_CENTS

    exhibition = fixtures.read_exhibition(ctx["exhibition"]["id"])
    assert exhibition["sales_gross_cents"] == SALE_PRICE_CENTS
    assert exhibition["commission_total_cents"] == EXEMPT_COMMISSION_CENTS
    assert exhibition["sales_tax_total_cents"] == 0
    assert exhibition["artist_payable_total_cents"] == EXEMPT_PAYABLE_CENTS

    artwork = fixtures.read_artwork(artwork_id)
    assert artwork["status"] == "SOLD"
    assert artwork["sold_price_cents"] == SALE_PRICE_CENTS


def test_fifty_thousand_over_three_equal_sittings_splits_the_two_spare_cents(api):
    """PRD §3.4: "A juror paid 50,000 cents across three equal 100-minute sessions
    therefore receives 16,667, 16,667 and 16,666 cents, summing to exactly
    50,000."

    Design: Corner/calculations/honorarium_remainder_cents_spread_over_three_equal_sessions
    """
    exhibition = fixtures.open_call()
    fixtures.enter_jurying(exhibition["id"])
    juror = fixtures.invite_and_confirm_juror(honorarium_cents=HONORARIUM_CENTS)
    jury_round = fixtures.create_jury_round(exhibition["id"], quorum_required=1)

    sittings = [
        fixtures.book_session(jury_round["id"], juror, start, end)
        for start, end in THREE_EQUAL_SITTINGS
    ]
    for sitting in sittings:
        assert sitting["session_minutes"] == HUNDRED_MINUTES

    shares = [
        fixtures.read_assignment(sitting["id"])["honorarium_share_cents"]
        for sitting in sittings
    ]
    assert shares == THREE_WAY_SHARES, (
        "the two remainder cents land on the two earliest created_at rows"
    )
    assert sum(shares) == HONORARIUM_CENTS

    assert fixtures.read_juror(juror["id"])["honorarium_committed_cents"] == (
        HONORARIUM_CENTS
    )
    assert fixtures.read_exhibition(exhibition["id"])[
        "jury_cost_committed_cents"
    ] == HONORARIUM_CENTS
