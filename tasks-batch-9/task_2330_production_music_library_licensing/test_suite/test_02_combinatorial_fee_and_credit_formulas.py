"""Two formulas whose interacting inputs and pinned rounding order decide the money.

The licence fee multiplies a base rate by media, scale, term and exclusivity
factors and then picks a discount band out of the resulting basis, so one
renegotiated term or scale moves both the product and the band. Cue-sheet
crediting rounds once per cue before summing, and turns the summed credits into
a writer's amount in two separate roundings.
"""

import pytest

from test_helpers import (
    LICENSING_AGENT,
    Deal,
    accept_sync_request,
    assert_cents_equal,
    assert_credits_equal,
    assert_ok,
    assert_quote_figures,
    assert_same_instant,
    assert_single_ledger_entry,
    assert_status,
    issue_per_use_license,
    ledger_entries,
    new_cataloged_work,
    new_cue_sheet,
    new_licensee,
    new_tier,
    quote_sync_request,
    read_composition,
    read_cue_sheet,
    read_licensee,
    register_cue_sheet,
    review_sync_request,
    submit_sync_request,
)
from test_helpers import factories as build

# ---------------------------------------------------------------------------
# The fee matrix: one BROADCAST_TV tier renegotiated three times
# ---------------------------------------------------------------------------


def _broadcast_tv_request_under_review(api) -> Deal:
    """A catalogued work, a BROADCAST_TV tier at 300000 and a request in UNDER_REVIEW.

    The request asks for NATIONAL distribution over 12 months with no add-ons,
    no rush and no exclusivity, so every later quote in the walk differs from
    this one only in the factor the licensee revised.
    """
    work = new_cataloged_work(
        api,
        composer_overrides={"display_name": "Rhea Sandoval", "pro_affiliation": "ASCAP"},
        agreement_overrides={
            "sync_fee_share_pct": 40.00,
            "exclusivity": "EXCLUSIVE",
            "holdback_days": 0,
        },
        title="Steel Meridian",
        duration_sec=210,
        tempo_bpm=124,
        genre="CINEMATIC",
        mood_tags=["EPIC"],
        instrumentation=["BRASS", "PERCUSSION"],
    )
    tier = new_tier(
        api,
        code="BTV-STD",
        media_type="BROADCAST_TV",
        allowed_scales=["LOCAL", "NATIONAL", "WORLDWIDE"],
        base_rate_cents=300000,
        min_term_months=1,
        max_term_months=120,
        per_use_eligible=True,
        blanket_eligible=False,
    )
    licensee = new_licensee(
        api,
        legal_name="Cascade Media Group",
        licensee_type="AGENCY",
        credit_limit_cents=10000000,
    )
    deal = Deal(work, tier, licensee)
    submit_sync_request(
        api,
        deal,
        media_type="BROADCAST_TV",
        distribution_scale="NATIONAL",
        requested_term_start="2026-09-01T00:00:00Z",
        requested_term_months=12,
        exclusive_requested=False,
        custom_edit_requested=False,
        stems_requested=False,
        alternate_lengths_sec=[],
        rush_requested=False,
    )
    review_sync_request(api, deal)
    return deal


_REVISION_WALK = (
    ("extend to two years", {"revised_term_months": 24}),
    ("go worldwide", {"revised_distribution_scale": "WORLDWIDE"}),
    ("add exclusivity", {"revised_exclusive_requested": True}),
)


def _quote_walk(api, deal: Deal):
    """Quote, then renegotiate the term, the scale and exclusivity in turn.

    Returns the four quote snapshots in the order they were produced. The clock
    is never advanced, so no quote in the walk can go stale.
    """
    quotes = [quote_sync_request(api, deal, 14).sync_request]
    for revision_note, revised in _REVISION_WALK:
        assert_ok(
            api.request_sync_revision(
                deal.sync_request_id,
                build.revision_payload(revision_note, **revised),
                deal.licensee_headers,
            )
        )
        quotes.append(quote_sync_request(api, deal, 14).sync_request)
    return quotes


class TestLicenceFeeMatrix:
    def test_quote_prices_the_base_rate_by_the_media_scale_and_term_factors(self, api):
        """PRD §3.4: "First, the core is the tier's `base_rate_cents` multiplied by the
        media factor for the requested `media_type` — 1.30 for `BROADCAST_TV`, 1.75 for
        `ONLINE_AD`, 2.20 for `FILM`, 0.85 for `CORPORATE`, 1.40 for `GAME` — then by the
        scale factor for the requested `distribution_scale` — 0.60 for `LOCAL`, 1.00 for
        `NATIONAL`, 1.90 for `WORLDWIDE` — then by the term factor, which is 0.70 for a
        term of at most 3 months, 1.00 for a term from 4 through 12 months, 1.45 for a
        term from 13 through 36 months and 1.90 for a term from 37 through 120 months,
        then by 1.65 when `exclusive_requested` is true and by nothing otherwise, and
        finally by 1.20 when `rush_requested` is true and by nothing otherwise."

        Design: Difficulty/combinatorial_formula/fee_matrix_media_scale_term_exclusivity_with_tier_discount
        """
        deal = _broadcast_tv_request_under_review(api)
        quotes = _quote_walk(api, deal)

        # 300000 * 1.30 * 1.00 * 1.00, a basis below 500000, so no discount.
        assert_quote_figures(quotes[0], 390000, 0.00, 390000)
        # The same product with the 13-36 month term factor 1.45 instead of 1.00.
        assert_quote_figures(quotes[1], 565500, 5.00, 537225)

    def test_requote_after_a_scale_revision_reprices_at_the_worldwide_factor(self, api):
        """PRD §3.4: "Re-quoting from `REVISION_REQUESTED` recomputes the fee from the
        revised term, scale and exclusivity and replaces the reservation on the licensee
        — the old quoted amount comes off and the new one goes on."

        Design: Difficulty/combinatorial_formula/fee_matrix_media_scale_term_exclusivity_with_tier_discount
        """
        deal = _broadcast_tv_request_under_review(api)
        quotes = _quote_walk(api, deal)

        # 300000 * 1.30 * 1.90 * 1.45, still inside the 5.00 band.
        assert_quote_figures(quotes[2], 1074450, 5.00, 1020727)
        assert_cents_equal(
            quotes[2]["quoted_fee_cents"] - quotes[1]["quoted_fee_cents"],
            483502,
            "fee lifted by the worldwide revision",
        )
        assert_status(quotes[2], "QUOTED")

    def test_exclusive_core_is_rounded_once_before_the_discount_is_taken(self, api):
        """PRD §3.4: "That whole product is rounded half up to a whole number of cents
        exactly once, before anything is added to it."

        Design: Difficulty/combinatorial_formula/fee_matrix_media_scale_term_exclusivity_with_tier_discount
        """
        deal = _broadcast_tv_request_under_review(api)
        quotes = _quote_walk(api, deal)

        # 300000 * 1.30 * 1.90 * 1.45 * 1.65 is 1772842.50, rounded up to 1772843
        # before the 10.00 discount of 177284 is subtracted.
        assert_quote_figures(quotes[3], 1772843, 10.00, 1595559)
        assert quotes[3]["quoted_fee_cents"] != 1595558, (
            "collapsing the core rounding into the discount rounding loses a cent"
        )

    def test_three_revisions_leave_only_the_live_quote_reserved(self, api):
        """PRD §3.4: "The transition increments `revision_round` by 1, applies whichever
        revised terms were supplied to the request, clears `quoted_fee_cents`,
        `quoted_spend_basis_cents`, `quoted_discount_pct` and `quote_expires_at` to null,
        and releases the licensee's reservation."

        Design: Difficulty/combinatorial_formula/fee_matrix_media_scale_term_exclusivity_with_tier_discount
        """
        deal = _broadcast_tv_request_under_review(api)
        _quote_walk(api, deal)

        request = assert_ok(api.get_sync_request(deal.sync_request_id, LICENSING_AGENT))
        assert request["revision_round"] == 3
        assert_status(request, "QUOTED")
        assert request["distribution_scale"] == "WORLDWIDE"
        assert request["requested_term_months"] == 24
        assert request["exclusive_requested"] is True

        licensee = read_licensee(api, deal.licensee_id)
        assert_cents_equal(licensee["reserved_spend_cents"], 1595559, "reserved_spend_cents")
        assert_cents_equal(licensee["committed_spend_cents"], 0, "committed_spend_cents")
        assert_cents_equal(licensee["credit_available_cents"], 8404441, "credit_available_cents")


# ---------------------------------------------------------------------------
# Cue crediting: three cues on one work, rounded per cue then summed
# ---------------------------------------------------------------------------

_THREE_CUES = (("THEME", 45), ("FEATURE", 45), ("BACKGROUND", 45))


def _collected_three_cue_sheet(api):
    """A per-use licence on one work carrying a COLLECTED sheet of three cues.

    The composer is affiliated with BMI on a 50.00 writer share, and all three
    cues sit on the same work at 45 seconds on a NETWORK sheet.
    """
    work = new_cataloged_work(
        api,
        composer_overrides={"display_name": "Talia Marsh", "pro_affiliation": "BMI"},
        agreement_overrides={
            "writer_share_pct": 50.00,
            "publisher_share_pct": 50.00,
            "sync_fee_share_pct": 40.00,
        },
        title="Copper Field",
        duration_sec=190,
        tempo_bpm=112,
        genre="FOLK",
        mood_tags=["HOPEFUL", "CALM"],
        instrumentation=["GUITAR", "PIANO"],
    )
    tier = new_tier(
        api,
        code="BTV-STD",
        media_type="BROADCAST_TV",
        allowed_scales=["LOCAL", "NATIONAL", "WORLDWIDE"],
        base_rate_cents=300000,
    )
    licensee = new_licensee(
        api,
        legal_name="Beacon Television",
        licensee_type="BROADCASTER",
        credit_limit_cents=5000000,
    )
    deal = Deal(work, tier, licensee)
    submit_sync_request(
        api,
        deal,
        media_type="BROADCAST_TV",
        distribution_scale="NATIONAL",
        requested_term_start="2026-09-01T00:00:00Z",
        requested_term_months=12,
        exclusive_requested=False,
        rush_requested=False,
    )
    review_sync_request(api, deal)
    quote_sync_request(api, deal, 14)
    accept_sync_request(api, deal)
    issue_per_use_license(api, deal)

    sheet = new_cue_sheet(
        api,
        [
            build.cue(deal.composition_id, usage_type, duration_sec)
            for usage_type, duration_sec in _THREE_CUES
        ],
        license_id=deal.license_id,
        production_title="Copper Field Documentary",
        broadcast_date="2026-08-01T00:00:00Z",
        market_tier="NETWORK",
    )
    return deal, sheet


class TestCueSheetCreditRounding:
    @pytest.mark.parametrize("position,usage_type,duration_sec,credits", [
        (0, "THEME", 45, 1.50),
        (1, "FEATURE", 45, 0.98),
        (2, "BACKGROUND", 45, 0.53),
    ])
    def test_each_cue_is_rounded_on_its_own_usage_and_market_weight(
        self, api, position, usage_type, duration_sec, credits
    ):
        """PRD §3.7: "For each cue, in array order, the credit figure is the cue's
        `duration_sec` divided by 30, multiplied by the usage weight for its `usage_type`
        — 1.00 for `THEME`, 0.65 for `FEATURE`, 0.35 for `BACKGROUND`, 0.10 for `LOGO` —
        multiplied by the market weight for the sheet's `market_tier` — 1.00 for
        `NETWORK`, 0.65 for `CABLE`, 0.40 for `LOCAL`, 0.25 for `DIGITAL` — and rounded
        half up to 2 decimals."

        Design: Difficulty/combinatorial_formula/cue_credit_round_per_cue_then_sum_and_two_step_writer_rounding
        """
        deal, sheet = _collected_three_cue_sheet(api)

        breakdown = sheet["cue_credit_breakdown"]
        assert len(breakdown) == 3, "cue_credit_breakdown mirrors the cues array"
        element = breakdown[position]
        assert element["composition_id"] == deal.composition_id
        assert element["usage_type"] == usage_type
        assert element["duration_sec"] == duration_sec
        assert_credits_equal(element["credits"], credits, f"{usage_type} credits")
        assert sheet["total_seconds"] == 135

    def test_sheet_total_sums_the_already_rounded_per_cue_credits(self, api):
        """PRD §3.7: "`total_credits` is the sum of those already-rounded per-cue figures
        — never a rounding of the unrounded sum, which can differ by a cent of credit."

        Design: Difficulty/combinatorial_formula/cue_credit_round_per_cue_then_sum_and_two_step_writer_rounding
        """
        deal, sheet = _collected_three_cue_sheet(api)

        # 1.50 + 0.98 + 0.53; rounding 1.5 + 0.975 + 0.525 instead would give 3.00.
        assert_credits_equal(sheet["total_credits"], 3.01, "total_credits")
        assert sheet["total_credits"] != pytest.approx(3.00, abs=0.001), (
            "summing the unrounded per-cue credits loses a cent of credit"
        )
        assert_credits_equal(
            sheet["credits_by_composition"][deal.composition_id],
            3.01,
            "credits_by_composition",
        )

    def test_registration_ledgers_the_writer_amount_in_two_roundings(self, api):
        """PRD §3.7: "Then multiply the gross amount by the governing agreement's
        `writer_share_pct`, divide by 100, and round half up again — that is the writer's
        amount, and it is the amount of the single ledger entry with the performance
        origin appended for that composer."

        Design: Difficulty/combinatorial_formula/cue_credit_round_per_cue_then_sum_and_two_step_writer_rounding
        """
        deal, sheet = _collected_three_cue_sheet(api)
        register_cue_sheet(api, sheet["id"], "BMI-2026-0007")

        # 3.01 credits at 1250 cents rounds to a gross of 3763, and half of 3763
        # rounds to 1882; collapsing the two roundings would give 1881.
        entry = assert_single_ledger_entry(
            ledger_entries(api, deal.work.composer_id),
            "PERFORMANCE",
            1882,
            source_ref_id=sheet["id"],
        )
        assert entry["amount_cents"] != 1881, (
            "collapsing the credits-to-cents and cents-to-writer roundings loses a cent"
        )
        assert entry["composer_id"] == deal.work.composer_id

    def test_registration_recognizes_the_accrual_but_collects_no_society_cash(
        self, api, clock_origin
    ):
        """PRD §3.7: "Every such entry has its accrual instant set to the clock and its
        cash instant left null, because society money has not been collected yet."

        Design: Difficulty/combinatorial_formula/cue_credit_round_per_cue_then_sum_and_two_step_writer_rounding
        """
        deal, sheet = _collected_three_cue_sheet(api)
        register_cue_sheet(api, sheet["id"], "BMI-2026-0007")

        entry = assert_single_ledger_entry(
            ledger_entries(api, deal.work.composer_id),
            "PERFORMANCE",
            1882,
            source_ref_id=sheet["id"],
        )
        assert_same_instant(entry["accrual_recognized_at"], clock_origin)
        assert entry["cash_recognized_at"] is None

    def test_registration_raises_lifetime_credits_by_the_sheet_total(self, api):
        """PRD §3.7: "Registration records `society_reference` and `registered_at`,
        increments `registration_round` by 1, and raises `lifetime_performance_credits`
        on every work the sheet cites."

        Design: Difficulty/combinatorial_formula/cue_credit_round_per_cue_then_sum_and_two_step_writer_rounding
        """
        deal, sheet = _collected_three_cue_sheet(api)
        registered = register_cue_sheet(api, sheet["id"], "BMI-2026-0007")

        assert_status(registered, "REGISTERED")
        assert registered["registration_round"] == 1
        assert registered["society_reference"] == "BMI-2026-0007"

        reread = read_cue_sheet(api, sheet["id"])
        assert_credits_equal(reread["total_credits"], 3.01, "total_credits")

        composition = read_composition(api, deal.composition_id)
        assert_credits_equal(
            composition["lifetime_performance_credits"], 3.01, "lifetime_performance_credits"
        )
