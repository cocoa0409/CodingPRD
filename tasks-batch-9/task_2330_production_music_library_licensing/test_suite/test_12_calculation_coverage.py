"""Every named calculation of the contract, exercised at its declared corners.

The licence fee walks the full factor matrix and the discount ladder; the
relevance model is scored facet by facet with the availability and recency
multipliers; the claim exposure ladder is pinned at its confidence bands and its
statutory ceiling; the blanket pool is computed per cadence period with its
overage increment, its administration retention and its largest-remainder
distribution; and the statement sweep turns a signed ledger into withholding,
net payable and a paid statement.
"""

import pytest

from test_helpers import (
    ACCOUNTANT_ONE,
    CATALOG_ADMIN,
    LICENSING_AGENT,
    RIGHTS_MANAGER,
    Deal,
    Work,
    accept_usage_report,
    advance_clock,
    assert_allocation,
    assert_cents_equal,
    assert_composer_money,
    assert_composition_axes,
    assert_created,
    assert_credit_exposure,
    assert_credits_equal,
    assert_declared_error,
    assert_ok,
    assert_page,
    assert_pool_conserves_cents,
    assert_quote_figures,
    assert_same_instant,
    assert_single_ledger_entry,
    assert_statement_figures,
    assert_status,
    composer_version,
    ledger_entries,
    make_accountant_headers,
    new_active_blanket,
    new_cataloged_work,
    new_fingerprint_match,
    new_licensee,
    new_noticed_claim,
    new_registered_cue_sheet,
    new_tier,
    notice_claim,
    open_usage_report,
    put_default_search_profile,
    quote_sync_request,
    read_blanket_agreement,
    read_claim,
    read_composer,
    read_composition,
    read_licensee,
    read_usage_report,
    review_sync_request,
    select_ledger_entries,
    submit_sync_request,
    submit_usage_report,
)
from test_helpers import factories as build
from test_helpers.constants import CLOCK_ORIGIN

# ---------------------------------------------------------------------------
# Shared setup helpers, all built through the declared endpoints
# ---------------------------------------------------------------------------


def _add_composition(api, owner: Work, **overrides) -> dict:
    """Another work under the same composer and the same governing agreement."""
    return assert_created(
        api.create_composition(
            build.composition_payload(owner.composer_id, owner.agreement_id, **overrides),
            CATALOG_ADMIN,
        )
    )


def _catalog(api, composition_id: str) -> dict:
    return assert_ok(api.catalog_composition(composition_id, None, CATALOG_ADMIN))


def _request_under_review(api, work: Work, tier: dict, licensee: dict, **overrides) -> Deal:
    """A sync request raised against the work and tier, taken under review."""
    deal = Deal(work, tier, licensee)
    submit_sync_request(api, deal, **overrides)
    return review_sync_request(api, deal)


def _quoted_request(api, work: Work, tier: dict, licensee: dict, **overrides) -> dict:
    """The same request carried to QUOTED with a 14-day quote."""
    deal = _request_under_review(api, work, tier, licensee, **overrides)
    quote_sync_request(api, deal, quote_valid_days=14)
    return deal.sync_request


def _search(api, params, headers=LICENSING_AGENT):
    """Run the facet search and return (rows, meta)."""
    return assert_page(api.search_compositions(params, headers))


def _relevance(row) -> float:
    return row["relevance_score"]


# The four-facet query used against the tagging of the works below: two moods,
# one genre, two instruments and a tempo 10 bpm away from the best match.
_FULL_FACET_QUERY = {
    "mood_tags": "EPIC,DARK",
    "genre": "CINEMATIC",
    "instrumentation": "STRINGS,BRASS",
    "tempo_bpm": 120,
}

_STORM_FRONT_FACETS = {
    "duration_sec": 200,
    "tempo_bpm": 130,
    "genre": "CINEMATIC",
    "mood_tags": ["EPIC", "DARK", "TENSE"],
    "instrumentation": ["STRINGS", "BRASS", "PERCUSSION"],
}

_QUIET_PIANO_FACETS = {
    "duration_sec": 150,
    "tempo_bpm": 118,
    "genre": "JAZZ",
    "mood_tags": ["CALM"],
    "instrumentation": ["PIANO"],
}


# ---------------------------------------------------------------------------
# The licence fee: the full factor matrix, the add-ons and the discount ladder
# ---------------------------------------------------------------------------


def _two_corner_quotes(api):
    """One work, two tiers and two quotes at opposite corners of the rate card.

    The first asks for `ONLINE_AD` at `WORLDWIDE` over 24 months with
    exclusivity, rush, a custom edit, stems and two alternate lengths; the
    second asks for `GAME` at `LOCAL` over 3 months with no add-ons at all.
    """
    work = new_cataloged_work(
        api,
        composer_overrides={"display_name": "Nadia Okoro", "pro_affiliation": "ASCAP"},
        agreement_overrides={"sync_fee_share_pct": 40.00},
        title="Harbour Lights",
        duration_sec=180,
        tempo_bpm=130,
        genre="CINEMATIC",
        mood_tags=["EPIC"],
        instrumentation=["STRINGS"],
    )
    online_tier = new_tier(
        api,
        code="ONLINE-STD",
        media_type="ONLINE_AD",
        allowed_scales=["LOCAL", "NATIONAL", "WORLDWIDE"],
        base_rate_cents=250000,
    )
    game_tier = new_tier(
        api,
        code="GAME-STD",
        media_type="GAME",
        allowed_scales=["LOCAL", "NATIONAL"],
        base_rate_cents=210000,
    )
    licensee = new_licensee(
        api,
        legal_name="Northwind Pictures",
        licensee_type="PRODUCTION_COMPANY",
        credit_limit_cents=5000000,
    )

    widest = _quoted_request(
        api,
        work,
        online_tier,
        licensee,
        media_type="ONLINE_AD",
        distribution_scale="WORLDWIDE",
        requested_term_start="2026-09-01T00:00:00Z",
        requested_term_months=24,
        exclusive_requested=True,
        custom_edit_requested=True,
        stems_requested=True,
        alternate_lengths_sec=[15, 60],
        rush_requested=True,
    )
    narrowest = _quoted_request(
        api,
        work,
        game_tier,
        licensee,
        media_type="GAME",
        distribution_scale="LOCAL",
        requested_term_start="2026-09-01T00:00:00Z",
        requested_term_months=3,
    )
    return {"work": work, "licensee": licensee, "widest": widest, "narrowest": narrowest}


class TestLicenseFeeFactorMatrix:
    def test_worldwide_exclusive_rush_quote_rounds_the_factor_product_once(self, api):
        """PRD §3.4: "First, the core is the tier's `base_rate_cents` multiplied by the
        media factor for the requested `media_type` — 1.30 for `BROADCAST_TV`, 1.75 for
        `ONLINE_AD`, 2.20 for `FILM`, 0.85 for `CORPORATE`, 1.40 for `GAME` — then by
        the scale factor for the requested `distribution_scale` — 0.60 for `LOCAL`, 1.00
        for `NATIONAL`, 1.90 for `WORLDWIDE` — then by the term factor, which is 0.70
        for a term of at most 3 months, 1.00 for a term from 4 through 12 months, 1.45
        for a term from 13 through 36 months and 1.90 for a term from 37 through 120
        months, then by 1.65 when `exclusive_requested` is true and by nothing otherwise,
        and finally by 1.20 when `rush_requested` is true and by nothing otherwise."

        Design: Corner/calculations/license_fee_full_factor_matrix_with_addons_and_short_term_floor
        """
        ground = _two_corner_quotes(api)

        # 250000 x 1.75 x 1.90 x 1.45 x 1.65 x 1.20 = 2386518.75 -> 2386519,
        # plus 45000 + 30000 + 2 x 12000 = 99000 of flat add-ons.
        assert_quote_figures(ground["widest"], 2485519, 10.00, 2236967)

    def test_local_three_month_quote_takes_the_zero_discount_band(self, api):
        """PRD §3.4: "Third, the volume discount is chosen from a spend basis: the basis
        is the licensee's `committed_spend_cents` observed at this moment plus this
        deal's own pre-discount amount, and the rate is 0.00 while the basis is below
        500000 cents, 5.00 from 500000 through 1499999 cents, 10.00 from 1500000 through
        2999999 cents, and 15.00 at 3000000 cents or above."

        Design: Corner/calculations/license_fee_full_factor_matrix_with_addons_and_short_term_floor
        """
        ground = _two_corner_quotes(api)

        # 210000 x 1.40 x 0.60 x 0.70 = 123480 exactly, and the basis stays below
        # the first discount band because no licence has been issued yet.
        assert_quote_figures(ground["narrowest"], 123480, 0.00, 123480)


# ---------------------------------------------------------------------------
# The relevance model
# ---------------------------------------------------------------------------


def _three_scored_works(api):
    """Two works tagged at 2026-08-01 and one identical work tagged at 2026-11-01.

    Work C is driven to `RESTRICTED` by a takedown notice, work D is left
    `INGESTED`, and work A is created after the clock has moved on so that A is
    brand new while B and C are 92 days old.
    """
    put_default_search_profile(
        api,
        weight_mood=40,
        weight_genre=25,
        weight_instrumentation=20,
        weight_tempo=15,
        tempo_tolerance_bpm=20,
        restricted_availability_factor=0.60,
    )
    work_b = new_cataloged_work(
        api,
        composer_overrides={"display_name": "Nadia Okoro", "pro_affiliation": "ASCAP"},
        title="Quiet Piano Room",
        **_QUIET_PIANO_FACETS,
    )
    work_c_id = _catalog(
        api, _add_composition(api, work_b, title="Storm Front", **_STORM_FRONT_FACETS)["id"]
    )["id"]
    work_d_id = _add_composition(
        api,
        work_b,
        title="Unfinished Sketch",
        duration_sec=90,
        tempo_bpm=130,
        genre="CINEMATIC",
        mood_tags=["EPIC", "DARK"],
        instrumentation=["STRINGS", "BRASS"],
    )["id"]
    new_noticed_claim(
        api,
        work_c_id,
        source_platform="UGC_VIDEO",
        source_reference="vid-70001",
        matched_seconds=120,
        confidence_pct=96.0,
    )

    advance_clock(api, "2026-11-01T00:00:00Z")
    work_a_id = _catalog(
        api,
        _add_composition(api, work_b, title="Storm Front Reprise", **_STORM_FRONT_FACETS)["id"],
    )["id"]
    return {
        "work_a_id": work_a_id,
        "work_b_id": work_b.composition_id,
        "work_c_id": work_c_id,
        "work_d_id": work_d_id,
    }


class TestFacetRankingWithRecencyBoost:
    def test_recent_available_work_outranks_its_restricted_twin(self, api):
        """PRD §3.3: "The `relevance_score` is the weighted figure multiplied by the
        availability factor and then by the recency factor, rounded half up to 2 decimals
        exactly once at the very end; because of the recency lift, a score above 100.00
        is legitimate and must not be clamped."

        Design: Corner/calculations/search_full_facet_ranking_with_recency_boost
        """
        ground = _three_scored_works(api)

        rows, meta = _search(api, _FULL_FACET_QUERY)

        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert [row["id"] for row in rows] == [
            ground["work_a_id"],
            ground["work_c_id"],
            ground["work_b_id"],
        ]
        # weighted 92.50 for the two identically tagged works, 13.50 for the work
        # that only matches on tempo.
        assert _relevance(rows[0]) == pytest.approx(101.75, abs=0.01)
        assert _relevance(rows[1]) == pytest.approx(55.50, abs=0.01)
        assert _relevance(rows[2]) == pytest.approx(13.50, abs=0.01)
        assert rows[1]["availability_status"] == "RESTRICTED"

    def test_plain_read_of_a_scored_work_reports_no_relevance(self, api):
        """PRD §3.2: "A fifth figure, `relevance_score`, exists only inside a
        facet-search response: on a single-work read and in every plain list, it is null."

        Design: Corner/calculations/search_full_facet_ranking_with_recency_boost
        """
        ground = _three_scored_works(api)

        rows, _meta = _search(api, _FULL_FACET_QUERY)
        assert _relevance(rows[0]) is not None

        assert read_composition(api, ground["work_a_id"])["relevance_score"] is None


def _two_identically_tagged_works(api):
    """One `AVAILABLE` work and one `RESTRICTED` twin, both created at the origin."""
    put_default_search_profile(
        api,
        weight_mood=40,
        weight_genre=25,
        weight_instrumentation=20,
        weight_tempo=15,
        tempo_tolerance_bpm=20,
        restricted_availability_factor=0.60,
    )
    work_a = new_cataloged_work(
        api,
        composer_overrides={"display_name": "Nadia Okoro", "pro_affiliation": "ASCAP"},
        title="Storm Front",
        **_STORM_FRONT_FACETS,
    )
    work_c_id = _catalog(
        api, _add_composition(api, work_a, title="Storm Front Alt", **_STORM_FRONT_FACETS)["id"]
    )["id"]
    new_noticed_claim(
        api,
        work_c_id,
        source_platform="UGC_VIDEO",
        source_reference="vid-70002",
        matched_seconds=120,
        confidence_pct=96.0,
    )
    return {"work_a_id": work_a.composition_id, "work_c_id": work_c_id}


class TestRecencyBoostBoundary:
    @pytest.mark.parametrize(
        "search_instant, available_score, restricted_score",
        [
            ("2026-10-30T00:00:00Z", 101.75, 61.05),
            ("2026-10-31T00:00:00Z", 92.50, 55.50),
        ],
    )
    def test_boost_survives_the_ninetieth_day_and_lapses_on_the_ninety_first(
        self, api, search_instant, available_score, restricted_score
    ):
        """PRD §3.3: "The recency factor is 1.10 when the difference between the current
        logical clock and the work's `created_at` is at most 90 days, and 1.00 otherwise
        — new deliveries get a deliberate three-month lift into the top of the results."

        Design: Corner/calculations/recency_boost_ninety_day_boundary_precision
        """
        ground = _two_identically_tagged_works(api)
        advance_clock(api, search_instant)

        rows, meta = _search(api, _FULL_FACET_QUERY)

        assert meta["total_count"] == 2
        assert [row["id"] for row in rows] == [ground["work_a_id"], ground["work_c_id"]]
        assert _relevance(rows[0]) == pytest.approx(available_score, abs=0.01)
        assert _relevance(rows[1]) == pytest.approx(restricted_score, abs=0.01)


def _four_status_combinations(api):
    """Four identically tagged works in four different status combinations."""
    put_default_search_profile(
        api,
        weight_mood=40,
        weight_genre=25,
        weight_instrumentation=20,
        weight_tempo=15,
        tempo_tolerance_bpm=20,
    )
    facets = {
        "duration_sec": 200,
        "tempo_bpm": 130,
        "genre": "CINEMATIC",
        "mood_tags": ["EPIC", "DARK"],
        "instrumentation": ["STRINGS", "BRASS"],
    }
    work_a = new_cataloged_work(
        api,
        composer_overrides={"display_name": "Nadia Okoro", "pro_affiliation": "ASCAP"},
        title="Storm Front",
        **facets,
    )
    work_d_id = _add_composition(api, work_a, title="Storm Front Sketch", **facets)["id"]
    work_e_id = _catalog(
        api, _add_composition(api, work_a, title="Storm Front Retired", **facets)["id"]
    )["id"]
    assert_ok(
        api.retire_composition(work_e_id, {"reason": "client pulled the master"}, CATALOG_ADMIN)
    )

    work_f = new_cataloged_work(
        api,
        composer_overrides={"display_name": "Tomas Reyes", "pro_affiliation": "BMI"},
        title="Storm Front Withdrawn",
        **facets,
    )
    assert_ok(
        api.terminate_agreement(
            work_f.agreement_id,
            {"reason": "composer bought out of the catalogue"},
            RIGHTS_MANAGER,
        )
    )
    return {
        "work_a_id": work_a.composition_id,
        "work_d_id": work_d_id,
        "work_e_id": work_e_id,
        "work_f_id": work_f.composition_id,
    }


class TestSearchEligiblePool:
    def test_only_the_cataloged_and_available_work_is_scored(self, api):
        """PRD §3.3: "The eligible pool is every composition whose `catalog_status` is
        `CATALOGED` and whose `availability_status` is `AVAILABLE` or `RESTRICTED`;
        everything else is invisible to search."

        Design: Corner/calculations/search_eligible_pool_excludes_ingested_retired_and_withdrawn_works
        """
        ground = _four_status_combinations(api)

        rows, meta = _search(
            api,
            {
                "mood_tags": "EPIC",
                "genre": "CINEMATIC",
                "instrumentation": "STRINGS",
                "tempo_bpm": 130,
            },
        )

        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [ground["work_a_id"]]
        # every facet matches exactly, so the weighted figure is 100.00 and only
        # the recency lift remains.
        assert _relevance(rows[0]) == pytest.approx(110.00, abs=0.01)

        returned = {row["id"] for row in rows}
        assert ground["work_d_id"] not in returned
        assert ground["work_e_id"] not in returned
        assert ground["work_f_id"] not in returned

        # the withdrawn work is still CATALOGED, so the catalogue axis alone would
        # have leaked it into the pool.
        assert_composition_axes(
            read_composition(api, ground["work_f_id"]), "CATALOGED", "WITHDRAWN"
        )
        assert_composition_axes(read_composition(api, ground["work_e_id"]), "RETIRED", "WITHDRAWN")


def _two_works_scored_after_the_boost_window(api):
    """An exactly matching work and a tempo-only match, both past the boost window."""
    put_default_search_profile(
        api,
        weight_mood=40,
        weight_genre=25,
        weight_instrumentation=20,
        weight_tempo=15,
        tempo_tolerance_bpm=20,
        restricted_availability_factor=0.60,
    )
    work_a = new_cataloged_work(
        api,
        composer_overrides={"display_name": "Nadia Okoro", "pro_affiliation": "ASCAP"},
        title="Storm Front",
        **_STORM_FRONT_FACETS,
    )
    work_b_id = _catalog(
        api, _add_composition(api, work_a, title="Quiet Piano Room", **_QUIET_PIANO_FACETS)["id"]
    )["id"]
    advance_clock(api, "2026-11-01T00:00:00Z")
    return {"work_a_id": work_a.composition_id, "work_b_id": work_b_id}


class TestSearchProfileRescoring:
    def test_weighted_figure_sums_each_supplied_facet_weight_times_its_match(self, api):
        """PRD §3.3: "Only facets the caller actually supplied take part: the weighted
        figure is 100 multiplied by the sum, over the supplied facets only, of each
        facet's weight times its match, divided by the sum of the weights of those same
        supplied facets — so absent facets are dropped and the remaining weights are
        renormalized rather than diluted."

        Design: Corner/calculations/search_profile_weight_change_rescores_and_flips_ranking
        """
        ground = _two_works_scored_after_the_boost_window(api)

        rows, _meta = _search(api, _FULL_FACET_QUERY)

        assert [row["id"] for row in rows] == [ground["work_a_id"], ground["work_b_id"]]
        # 40 + 25 + 20 + 15 x 0.5 for the matching work, 15 x 0.9 for the other.
        assert _relevance(rows[0]) == pytest.approx(92.50, abs=0.01)
        assert _relevance(rows[1]) == pytest.approx(13.50, abs=0.01)

    def test_replacing_the_profile_rescores_the_next_search_and_flips_the_ranking(self, api):
        """PRD §3.3: "Weights are read from the profile at request time, so changing the
        profile re-scores every subsequent search."

        Design: Corner/calculations/search_profile_weight_change_rescores_and_flips_ranking
        """
        ground = _two_works_scored_after_the_boost_window(api)

        put_default_search_profile(
            api,
            weight_mood=0,
            weight_genre=0,
            weight_instrumentation=0,
            weight_tempo=100,
            tempo_tolerance_bpm=20,
            restricted_availability_factor=0.60,
        )
        rows, _meta = _search(api, _FULL_FACET_QUERY)

        assert [row["id"] for row in rows] == [ground["work_b_id"], ground["work_a_id"]]
        assert _relevance(rows[0]) == pytest.approx(90.00, abs=0.01)
        assert _relevance(rows[1]) == pytest.approx(50.00, abs=0.01)

        profile = assert_ok(api.get_search_profile(LICENSING_AGENT))
        assert profile["weight_tempo"] == 100
        assert profile["weight_mood"] == 0
        assert profile["version"] == 2


# ---------------------------------------------------------------------------
# Claim exposure: confidence bands, the statutory ceiling and the floor
# ---------------------------------------------------------------------------


def _claimed_detection(api, **match_overrides):
    """A catalogued work with one detection turned into a claim in `DETECTED`."""
    work = new_cataloged_work(
        api,
        composer_overrides={"display_name": "Nadia Okoro", "pro_affiliation": "ASCAP"},
        agreement_overrides={"sync_fee_share_pct": 40.00},
        title="Harbour Lights",
        duration_sec=180,
        tempo_bpm=130,
        genre="CINEMATIC",
        mood_tags=["EPIC"],
        instrumentation=["STRINGS"],
    )
    match = new_fingerprint_match(api, work.composition_id, **match_overrides)
    claim = assert_created(
        api.create_infringement_claim({"fingerprint_match_id": match["id"]}, RIGHTS_MANAGER)
    )
    return work, match, claim


class TestInfringementStatutoryExposure:
    @pytest.mark.parametrize(
        "confidence_pct, statutory_amount_cents",
        [(85.0, 90000), (84.9, 60000)],
    )
    def test_confidence_bands_are_closed_on_their_lower_bound(
        self, api, confidence_pct, statutory_amount_cents
    ):
        """PRD §3.8: "The confidence factor is 1.00 when `confidence_pct` is at least
        95.0, 0.75 when it is from 85.0 through 94.9, and 0.50 when it is from 70.0
        through 84.9; the bands are closed on their lower bound, so a confidence of
        exactly 85.0 belongs to the 0.75 band while 84.9 belongs to the 0.50 band."

        Design: Corner/calculations/claim_confidence_band_boundary_and_statutory_cap
        """
        _work, _match, claim = _claimed_detection(
            api,
            source_platform="UGC_VIDEO",
            source_reference="vid-1",
            matched_seconds=120,
            confidence_pct=confidence_pct,
        )

        # 120 seconds x 1000 cents = 120000 before the confidence factor.
        assert_cents_equal(
            claim["statutory_amount_cents"], statutory_amount_cents, "statutory_amount_cents"
        )

    def test_statutory_ceiling_caps_the_theatrical_exposure_after_the_rounding(self, api):
        """PRD §3.8: "The ceiling is applied after that rounding, so a capped claim
        reports exactly 15000000 cents."

        Design: Corner/calculations/claim_confidence_band_boundary_and_statutory_cap
        """
        _work, _match, claim = _claimed_detection(
            api,
            source_platform="THEATRICAL",
            source_reference="reel-3",
            matched_seconds=2000,
            confidence_pct=99.0,
        )

        # 2000 seconds x 9000 cents x 1.00 = 18000000 before the ceiling.
        assert_cents_equal(claim["statutory_amount_cents"], 15000000, "statutory_amount_cents")

    @pytest.mark.parametrize(
        "source_platform, matched_seconds, confidence_pct, settlement_floor_cents",
        [
            ("UGC_VIDEO", 120, 85.0, 27000),
            ("UGC_VIDEO", 120, 84.9, 18000),
            ("THEATRICAL", 2000, 99.0, 4500000),
        ],
    )
    def test_settlement_floor_is_thirty_percent_of_the_statutory_amount(
        self, api, source_platform, matched_seconds, confidence_pct, settlement_floor_cents
    ):
        """PRD §3.8: "`settlement_floor_cents`, the lowest negotiated amount the library
        will accept, is `statutory_amount_cents` multiplied by 30.00 percent divided by
        100 and rounded half up."

        Design: Corner/calculations/claim_confidence_band_boundary_and_statutory_cap
        """
        _work, _match, claim = _claimed_detection(
            api,
            source_platform=source_platform,
            source_reference=f"ref-{matched_seconds}-{confidence_pct}",
            matched_seconds=matched_seconds,
            confidence_pct=confidence_pct,
        )

        assert_cents_equal(
            claim["settlement_floor_cents"], settlement_floor_cents, "settlement_floor_cents"
        )

    def test_detection_below_seventy_confidence_never_becomes_a_claim(self, api):
        """PRD §3.8: "The match's `confidence_pct` must be at least 70.0, and a lower
        confidence is refused with `ERR_CONFIDENCE_BELOW_CLAIM_THRESHOLD`."

        Design: Corner/calculations/claim_confidence_band_boundary_and_statutory_cap
        """
        work = new_cataloged_work(
            api,
            composer_overrides={"display_name": "Nadia Okoro", "pro_affiliation": "ASCAP"},
            title="Harbour Lights",
        )
        match = new_fingerprint_match(
            api,
            work.composition_id,
            source_platform="UGC_VIDEO",
            source_reference="vid-4",
            matched_seconds=100,
            confidence_pct=69.9,
        )

        assert_declared_error(
            api.create_infringement_claim({"fingerprint_match_id": match["id"]}, RIGHTS_MANAGER),
            "ERR_CONFIDENCE_BELOW_CLAIM_THRESHOLD",
        )

        _rows, meta = assert_page(
            api.list_infringement_claims({"fingerprint_match_id": match["id"]}, RIGHTS_MANAGER)
        )
        assert meta["total_count"] == 0


class TestNegotiatedSettlementShare:
    def test_settlement_at_the_floor_ledgers_the_composer_sync_share(self, api):
        """PRD §3.8: "`composer_share_cents` is computed as `settlement_amount_cents`
        multiplied by the governing agreement's `sync_fee_share_pct` divided by 100 and
        rounded half up, and exactly one ledger entry with the settlement origin is
        appended for that amount, with its accrual instant set to the clock and its cash
        instant set to the clock when `payment_received` is true and left null otherwise."

        Design: Corner/calculations/claim_confidence_band_boundary_and_statutory_cap
        """
        work, _match, claim = _claimed_detection(
            api,
            source_platform="THEATRICAL",
            source_reference="reel-3",
            matched_seconds=2000,
            confidence_pct=99.0,
        )
        notice_claim(api, claim["id"])
        settled = assert_ok(
            api.settle_claim(
                claim["id"],
                {
                    "settlement_basis": "NEGOTIATED",
                    "payment_received": True,
                    "negotiated_amount_cents": 4500000,
                },
                RIGHTS_MANAGER,
            )
        )

        assert_status(settled, "SETTLED")
        assert_cents_equal(settled["settlement_amount_cents"], 4500000, "settlement_amount_cents")
        assert settled["settlement_basis"] == "NEGOTIATED"
        assert settled["settlement_collected"] is True
        # 4500000 x 40.00 / 100 of a sync-fee share.
        assert_cents_equal(settled["composer_share_cents"], 1800000, "composer_share_cents")

        entries = ledger_entries(api, work.composer_id)
        assert len(entries) == 1
        entry = assert_single_ledger_entry(entries, "SETTLEMENT", 1800000, claim["id"])
        assert_same_instant(entry["cash_recognized_at"], CLOCK_ORIGIN)
        assert_composer_money(
            read_composer(api, work.composer_id), accrued_unpaid_cents=1800000
        )
        assert_cents_equal(
            read_claim(api, claim["id"])["settlement_floor_cents"],
            4500000,
            "settlement_floor_cents",
        )


# ---------------------------------------------------------------------------
# The blanket pool: cadence fraction, overage increment, largest remainder
# ---------------------------------------------------------------------------


def _monthly_pool_over_two_periods(api):
    """A MONTHLY blanket whose first period sits on the cap and second crosses it.

    The August report carries 135 seconds on work A and 30 seconds on work B; the
    September report carries a single 60-second cue on work A, which takes the
    year-to-date minutes one minute past the three-minute cap.
    """
    work_a = new_cataloged_work(
        api,
        composer_overrides={"display_name": "Nadia Okoro", "pro_affiliation": "ASCAP"},
        agreement_overrides={
            "writer_share_pct": 50.00,
            "publisher_share_pct": 50.00,
            "sync_fee_share_pct": 40.00,
            "blanket_opt_in": True,
        },
        title="Harbour Lights",
        duration_sec=180,
        tempo_bpm=130,
        genre="CINEMATIC",
        mood_tags=["EPIC"],
        instrumentation=["STRINGS"],
    )
    work_b_id = _catalog(
        api,
        _add_composition(
            api,
            work_a,
            title="Slow Tide",
            duration_sec=120,
            tempo_bpm=90,
            genre="CLASSICAL",
            mood_tags=["CALM"],
            instrumentation=["PIANO"],
        )["id"],
    )["id"]
    licensee = new_licensee(
        api,
        legal_name="Meridian Broadcasting",
        licensee_type="BROADCASTER",
        credit_limit_cents=5000000,
    )
    blanket = new_active_blanket(
        api,
        licensee,
        coverage_start="2026-08-01T00:00:00Z",
        coverage_end="2027-08-01T00:00:00Z",
        annual_fee_cents=4800000,
        reporting_cadence="MONTHLY",
        usage_cap_minutes=3,
        pool_share_pct=25.00,
    )

    open_usage_report(
        api, blanket, period_start="2026-08-01T00:00:00Z", period_end="2026-08-31T00:00:00Z"
    )
    new_registered_cue_sheet(
        api,
        [
            build.cue(work_a.composition_id, "THEME", 45),
            build.cue(work_a.composition_id, "FEATURE", 45),
            build.cue(work_a.composition_id, "BACKGROUND", 45),
        ],
        usage_report_id=blanket.usage_report_id,
        society_reference="ASCAP-A-1",
        production_title="Coastal Nights S01E01",
        broadcast_date="2026-08-10T00:00:00Z",
        market_tier="NETWORK",
    )
    new_registered_cue_sheet(
        api,
        [build.cue(work_b_id, "FEATURE", 30)],
        usage_report_id=blanket.usage_report_id,
        society_reference="ASCAP-B-1",
        production_title="Coastal Nights S01E02",
        broadcast_date="2026-08-17T00:00:00Z",
        market_tier="NETWORK",
    )
    submit_usage_report(api, blanket)
    accept_usage_report(api, blanket)
    report_one = blanket.usage_report

    open_usage_report(
        api, blanket, period_start="2026-09-01T00:00:00Z", period_end="2026-09-30T00:00:00Z"
    )
    new_registered_cue_sheet(
        api,
        [build.cue(work_a.composition_id, "FEATURE", 60)],
        usage_report_id=blanket.usage_report_id,
        society_reference="ASCAP-A-2",
        production_title="Coastal Nights S01E03",
        broadcast_date="2026-09-07T00:00:00Z",
        market_tier="NETWORK",
    )
    submit_usage_report(api, blanket)
    accept_usage_report(api, blanket)
    report_two = blanket.usage_report

    return {
        "work_a": work_a,
        "work_b_id": work_b_id,
        "blanket": blanket,
        "report_one": report_one,
        "report_two": report_two,
    }


class TestMonthlyPoolAndOverageIncrement:
    def test_reported_minutes_are_ceilinged_once_per_report(self, api):
        """PRD §3.6: "`reported_minutes_total` is the sum of those sheets'
        `total_seconds` divided by 60 and rounded **up** to a whole minute; because the
        ceiling is applied once per report, partial minutes never carry from one period
        into the next."

        Design: Corner/calculations/blanket_overage_crossing_folds_increment_into_the_second_pool
        """
        ground = _monthly_pool_over_two_periods(api)

        # 135 + 30 = 165 seconds becomes 3 minutes, and the next period's 60
        # seconds becomes 1 minute rather than continuing the partial minute.
        assert ground["report_one"]["reported_minutes_total"] == 3
        assert_credits_equal(
            ground["report_one"]["reported_credits_total"], 3.66, "reported_credits_total"
        )
        assert ground["report_two"]["reported_minutes_total"] == 1

    def test_usage_exactly_at_the_cap_is_not_over_it(self, api):
        """PRD §3.6: "**Step three**: because year-to-date minutes changed,
        `overage_minutes` is recomputed as `reported_minutes_ytd` less
        `usage_cap_minutes`, floored at 0 — usage exactly at the cap is not over it — and
        `overage_cents` as `overage_minutes` multiplied by the overage rate of 4.50
        dollars per minute, that is 450 cents per reported minute."

        Design: Corner/calculations/blanket_overage_crossing_folds_increment_into_the_second_pool
        """
        work_a = new_cataloged_work(
            api,
            composer_overrides={"display_name": "Nadia Okoro", "pro_affiliation": "ASCAP"},
            title="Harbour Lights",
        )
        licensee = new_licensee(
            api, legal_name="Meridian Broadcasting", licensee_type="BROADCASTER"
        )
        blanket = new_active_blanket(
            api,
            licensee,
            coverage_start="2026-08-01T00:00:00Z",
            coverage_end="2027-08-01T00:00:00Z",
            annual_fee_cents=4800000,
            reporting_cadence="MONTHLY",
            usage_cap_minutes=3,
            pool_share_pct=25.00,
        )
        open_usage_report(
            api, blanket, period_start="2026-08-01T00:00:00Z", period_end="2026-08-31T00:00:00Z"
        )
        new_registered_cue_sheet(
            api,
            [
                build.cue(work_a.composition_id, "THEME", 45),
                build.cue(work_a.composition_id, "FEATURE", 45),
                build.cue(work_a.composition_id, "BACKGROUND", 45),
            ],
            usage_report_id=blanket.usage_report_id,
            society_reference="ASCAP-A-1",
            market_tier="NETWORK",
        )
        new_registered_cue_sheet(
            api,
            [build.cue(work_a.composition_id, "FEATURE", 30)],
            usage_report_id=blanket.usage_report_id,
            society_reference="ASCAP-A-2",
            market_tier="NETWORK",
        )
        submit_usage_report(api, blanket)
        accept_usage_report(api, blanket)

        at_cap = read_blanket_agreement(api, blanket.agreement_id)
        assert at_cap["reported_minutes_ytd"] == 3
        assert at_cap["overage_minutes"] == 0
        assert_cents_equal(at_cap["overage_cents"], 0, "overage_cents")

        open_usage_report(
            api, blanket, period_start="2026-09-01T00:00:00Z", period_end="2026-09-30T00:00:00Z"
        )
        new_registered_cue_sheet(
            api,
            [build.cue(work_a.composition_id, "FEATURE", 60)],
            usage_report_id=blanket.usage_report_id,
            society_reference="ASCAP-A-3",
            market_tier="NETWORK",
        )
        submit_usage_report(api, blanket)
        accept_usage_report(api, blanket)

        over_cap = read_blanket_agreement(api, blanket.agreement_id)
        assert over_cap["reported_minutes_ytd"] == 4
        assert over_cap["overage_minutes"] == 1
        assert_cents_equal(over_cap["overage_cents"], 450, "overage_cents")

    def test_first_period_pool_retains_fifteen_percent_before_distribution(self, api):
        """PRD §3.6: "`pool_admin_fee_cents` is `pool_cents` multiplied by the
        administration retention of 15.00 percent divided by 100, rounded half up."

        Design: Corner/calculations/blanket_overage_crossing_folds_increment_into_the_second_pool
        """
        ground = _monthly_pool_over_two_periods(api)
        report = read_usage_report(api, ground["report_one"]["id"])

        # 4800000 x 25.00 / 100 x 1/12 with no overage increment.
        assert_cents_equal(report["pool_cents"], 100000, "pool_cents")
        assert_cents_equal(report["pool_admin_fee_cents"], 15000, "pool_admin_fee_cents")
        assert_cents_equal(report["pool_distributable_cents"], 85000, "pool_distributable_cents")
        assert_pool_conserves_cents(report)
        assert_allocation(report, ground["work_a"].composition_id, 3.01, 69905)
        assert_allocation(report, ground["work_b_id"], 0.65, 15095)

    def test_second_period_pool_folds_in_the_overage_increment(self, api):
        """PRD §3.6: "`pool_cents` is the sum of two separately rounded terms: the
        agreement's `annual_fee_cents` multiplied by `pool_share_pct`, divided by 100,
        multiplied by the cadence fraction, rounded half up; plus the overage increment
        multiplied by `pool_share_pct` divided by 100, rounded half up."

        Design: Corner/calculations/blanket_overage_crossing_folds_increment_into_the_second_pool
        """
        ground = _monthly_pool_over_two_periods(api)
        report = read_usage_report(api, ground["report_two"]["id"])

        # 100000 for the cadence share plus round_half_up(450 x 25 / 100) = 113.
        assert_cents_equal(report["pool_cents"], 100113, "pool_cents")
        assert_cents_equal(report["pool_admin_fee_cents"], 15017, "pool_admin_fee_cents")
        assert_cents_equal(report["pool_distributable_cents"], 85096, "pool_distributable_cents")
        assert_pool_conserves_cents(report)
        assert [item["composition_id"] for item in report["pool_allocations"]] == [
            ground["work_a"].composition_id
        ]
        assert_allocation(report, ground["work_a"].composition_id, 1.30, 85096)

        agreement = read_blanket_agreement(api, ground["blanket"].agreement_id)
        assert_cents_equal(agreement["pool_admin_fee_cents"], 30017, "cumulative admin fee")
        assert_cents_equal(agreement["pool_distributed_cents"], 170096, "pool_distributed_cents")

    def test_one_pool_entry_per_allocation_carries_the_writer_share(self, api):
        """PRD §3.6: "**Step five**: because allocations exist, one ledger entry with the
        blanket-pool origin is appended per allocation, for the composer of that
        allocation's work, whose amount is the allocation multiplied by the governing
        agreement's `writer_share_pct` divided by 100 and rounded half up, pointing at
        this report, with both its accrual and cash instants set to the clock; each
        append raises that composer's `accrued_unpaid_cents`, and the entries are
        appended in `pool_allocations` order."

        Design: Corner/calculations/blanket_overage_crossing_folds_increment_into_the_second_pool
        """
        ground = _monthly_pool_over_two_periods(api)
        entries = ledger_entries(api, ground["work_a"].composer_id)

        assert [(entry["source_type"], entry["amount_cents"]) for entry in entries] == [
            ("PERFORMANCE", 1882),
            ("PERFORMANCE", 407),
            ("BLANKET_POOL", 34953),
            ("BLANKET_POOL", 7548),
            ("PERFORMANCE", 813),
            ("BLANKET_POOL", 42548),
        ]
        for entry in entries:
            if entry["source_type"] == "BLANKET_POOL":
                assert_same_instant(entry["cash_recognized_at"], CLOCK_ORIGIN)
        assert entries[2]["source_ref_id"] == ground["report_one"]["id"]
        assert entries[5]["source_ref_id"] == ground["report_two"]["id"]
        assert_composer_money(
            read_composer(api, ground["work_a"].composer_id), accrued_unpaid_cents=88151
        )


def _quarterly_pool_across_two_composers(api):
    """A QUARTERLY blanket whose single period credits two differently split works."""
    work_a = new_cataloged_work(
        api,
        composer_overrides={"display_name": "Nadia Okoro", "pro_affiliation": "ASCAP"},
        agreement_overrides={
            "writer_share_pct": 50.00,
            "publisher_share_pct": 50.00,
            "sync_fee_share_pct": 40.00,
            "blanket_opt_in": True,
        },
        title="Harbour Lights",
        duration_sec=180,
        tempo_bpm=130,
        genre="CINEMATIC",
        mood_tags=["EPIC"],
        instrumentation=["STRINGS"],
    )
    work_b = new_cataloged_work(
        api,
        composer_overrides={"display_name": "Tomas Reyes", "pro_affiliation": "BMI"},
        agreement_overrides={
            "writer_share_pct": 70.00,
            "publisher_share_pct": 30.00,
            "sync_fee_share_pct": 35.00,
            "blanket_opt_in": True,
        },
        title="Slow Tide",
        duration_sec=120,
        tempo_bpm=90,
        genre="CLASSICAL",
        mood_tags=["CALM"],
        instrumentation=["PIANO"],
    )
    licensee = new_licensee(
        api,
        legal_name="Meridian Broadcasting",
        licensee_type="BROADCASTER",
        credit_limit_cents=5000000,
    )
    blanket = new_active_blanket(
        api,
        licensee,
        coverage_start="2026-08-01T00:00:00Z",
        coverage_end="2027-08-01T00:00:00Z",
        annual_fee_cents=4800000,
        reporting_cadence="QUARTERLY",
        usage_cap_minutes=3,
        pool_share_pct=25.00,
    )
    open_usage_report(
        api, blanket, period_start="2026-08-01T00:00:00Z", period_end="2026-10-31T00:00:00Z"
    )
    new_registered_cue_sheet(
        api,
        [
            build.cue(work_a.composition_id, "THEME", 45),
            build.cue(work_a.composition_id, "FEATURE", 45),
            build.cue(work_a.composition_id, "BACKGROUND", 45),
        ],
        usage_report_id=blanket.usage_report_id,
        society_reference="ASCAP-Q-1",
        production_title="Quarterly Reel A",
        broadcast_date="2026-08-20T00:00:00Z",
        market_tier="NETWORK",
    )
    new_registered_cue_sheet(
        api,
        [build.cue(work_b.composition_id, "FEATURE", 30)],
        usage_report_id=blanket.usage_report_id,
        society_reference="BMI-Q-1",
        production_title="Quarterly Reel B",
        broadcast_date="2026-09-20T00:00:00Z",
        market_tier="NETWORK",
    )
    submit_usage_report(api, blanket)
    accept_usage_report(api, blanket)
    return {"work_a": work_a, "work_b": work_b, "blanket": blanket}


class TestQuarterlyPoolLargestRemainder:
    def test_residual_cent_goes_to_the_work_with_the_most_credits(self, api):
        """PRD §3.6: "The remainder is `pool_distributable_cents` less the sum of the
        floor shares, and exactly that many works — taken in order of credits
        descending, then `created_at` ascending, then `id` ascending — each receive
        exactly one additional cent."

        Design: Corner/calculations/quarterly_pool_largest_remainder_conserves_every_cent
        """
        ground = _quarterly_pool_across_two_composers(api)
        report = read_usage_report(api, ground["blanket"].usage_report_id)

        # 4800000 x 25.00 / 100 x 1/4 for the quarterly cadence fraction.
        assert_cents_equal(report["pool_cents"], 300000, "pool_cents")
        assert_cents_equal(report["pool_admin_fee_cents"], 45000, "pool_admin_fee_cents")
        assert_cents_equal(report["pool_distributable_cents"], 255000, "pool_distributable_cents")
        assert report["reported_minutes_total"] == 3
        assert_credits_equal(report["reported_credits_total"], 3.66, "reported_credits_total")

        # floors 209713 + 45286 = 254999, so one cent is left to hand out.
        assert [item["composition_id"] for item in report["pool_allocations"]] == [
            ground["work_a"].composition_id,
            ground["work_b"].composition_id,
        ]
        assert_allocation(report, ground["work_a"].composition_id, 3.01, 209714)
        assert_allocation(report, ground["work_b"].composition_id, 0.65, 45286)
        assert_pool_conserves_cents(report)

    def test_each_pool_entry_reads_its_own_governing_agreement_writer_share(self, api):
        """PRD §3.6: "**Step five**: because allocations exist, one ledger entry with the
        blanket-pool origin is appended per allocation, for the composer of that
        allocation's work, whose amount is the allocation multiplied by the governing
        agreement's `writer_share_pct` divided by 100 and rounded half up, pointing at
        this report, with both its accrual and cash instants set to the clock; each
        append raises that composer's `accrued_unpaid_cents`, and the entries are
        appended in `pool_allocations` order."

        Design: Corner/calculations/quarterly_pool_largest_remainder_conserves_every_cent
        """
        ground = _quarterly_pool_across_two_composers(api)
        report_id = ground["blanket"].usage_report_id

        # 209714 at 50.00 percent and 45286 at 70.00 percent.
        assert_single_ledger_entry(
            ledger_entries(api, ground["work_a"].composer_id), "BLANKET_POOL", 104857, report_id
        )
        second = ledger_entries(api, ground["work_b"].composer_id)
        assert [(entry["source_type"], entry["amount_cents"]) for entry in second] == [
            ("PERFORMANCE", 569),
            ("BLANKET_POOL", 31700),
        ]
        assert_composer_money(
            read_composer(api, ground["work_a"].composer_id), accrued_unpaid_cents=106739
        )
        assert_composer_money(
            read_composer(api, ground["work_b"].composer_id), accrued_unpaid_cents=32269
        )


# ---------------------------------------------------------------------------
# The statement sweep
# ---------------------------------------------------------------------------


def _ledger_with_a_society_reversal(api):
    """A ledger holding a performance amount, its reversal and two adjustments.

    The society rejects the filed cue sheet, which appends the compensating
    performance-reversal entry; two manual adjustments then join it, all four
    recognized inside the August window the statement sweeps.
    """
    work = new_cataloged_work(
        api,
        composer_overrides={"display_name": "Ivo Brandt", "pro_affiliation": "BMI"},
        agreement_overrides={"writer_share_pct": 50.00, "publisher_share_pct": 50.00},
        title="Night Freight",
        duration_sec=150,
    )
    licensee = new_licensee(
        api, legal_name="Meridian Broadcasting", licensee_type="BROADCASTER"
    )
    blanket = new_active_blanket(api, licensee)
    open_usage_report(
        api, blanket, period_start="2026-08-01T00:00:00Z", period_end="2026-08-31T00:00:00Z"
    )
    sheet = new_registered_cue_sheet(
        api,
        [build.cue(work.composition_id, "THEME", 45)],
        usage_report_id=blanket.usage_report_id,
        society_reference="BMI-2026-0001",
        production_title="Night Freight Promo",
        broadcast_date="2026-08-10T00:00:00Z",
        market_tier="NETWORK",
    )
    assert_ok(
        api.record_society_decision(
            sheet["id"],
            {"decision": "REJECT", "rejection_reason": "filed twice by the same agent"},
            RIGHTS_MANAGER,
        )
    )
    for amount_cents, memo in ((40000, "library bonus"), (25000, "catalogue placement")):
        assert_created(
            api.create_royalty_ledger_entry(
                build.ledger_entry_payload(work.composer_id, amount_cents, memo=memo),
                ACCOUNTANT_ONE,
            )
        )
    return {"work": work, "cue_sheet": sheet}


def _draft_statement_over_august(api, composer_id):
    return assert_created(
        api.create_royalty_statement(
            build.statement_payload(
                composer_id,
                composer_version(api, composer_id),
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-08-31T00:00:00Z",
                basis="ACCRUAL",
            ),
            ACCOUNTANT_ONE,
        )
    )


class TestStatementSweepWithSocietyReversal:
    def test_reversal_entry_is_swept_as_a_line_and_subtracted_from_gross(self, api):
        """PRD §3.9: "`gross_cents` is the sum of the swept `amount_cents`, so reversal
        entries reduce it."

        Design: Corner/calculations/statement_sweep_with_reversal_reduces_gross_and_withholding
        """
        ground = _ledger_with_a_society_reversal(api)
        composer_id = ground["work"].composer_id
        statement = _draft_statement_over_august(api, composer_id)

        # 938 + 40000 + 25000 - 938, with all four entries counted as lines.
        assert_cents_equal(statement["gross_cents"], 65000, "gross_cents")
        assert statement["line_count"] == 4

        reversals = select_ledger_entries(
            ledger_entries(api, composer_id), source_type="PERFORMANCE_REVERSAL"
        )
        assert len(reversals) == 1
        assert_cents_equal(reversals[0]["amount_cents"], -938, "reversal amount_cents")
        assert reversals[0]["statement_id"] == statement["id"]
        assert reversals[0]["source_ref_id"] == ground["cue_sheet"]["id"]

    def test_withholding_is_rounded_once_on_the_post_recoupment_base(self, api):
        """PRD §3.9: "`withholding_cents` is the post-recoupment base — `gross_cents`
        less `recouped_cents` — multiplied by the composer's `tax_withholding_pct` and
        rounded half up exactly once."

        Design: Corner/calculations/statement_sweep_with_reversal_reduces_gross_and_withholding
        """
        ground = _ledger_with_a_society_reversal(api)
        statement = _draft_statement_over_august(api, ground["work"].composer_id)

        # no advance to recoup, so the base is the whole 65000 at 0.30.
        assert_statement_figures(
            statement,
            gross_cents=65000,
            recouped_cents=0,
            withholding_cents=19500,
            net_payable_cents=45500,
            payout_status="PAYABLE",
            line_count=4,
        )

    def test_payment_by_a_second_accountant_moves_the_lifetime_paid_figure(self, api):
        """PRD §3.9: "Payment then moves `FINALIZED → PAID`, taking a
        `payment_reference` recorded on the statement alongside `paid_by_user_id` and
        `paid_at`, and raising the composer's `lifetime_paid_cents` by
        `net_payable_cents`."

        Design: Corner/calculations/statement_sweep_with_reversal_reduces_gross_and_withholding
        """
        ground = _ledger_with_a_society_reversal(api)
        composer_id = ground["work"].composer_id
        statement = _draft_statement_over_august(api, composer_id)

        finalized = assert_ok(
            api.finalize_royalty_statement(
                statement["id"], None, make_accountant_headers("acct-alpha")
            )
        )
        assert_status(finalized, "FINALIZED")
        assert finalized["finalized_by_user_id"] == "acct-alpha"

        paid = assert_ok(
            api.pay_royalty_statement(
                statement["id"],
                {"payment_reference": "WIRE-2026-08-0001"},
                make_accountant_headers("acct-beta"),
            )
        )
        assert_status(paid, "PAID")
        assert paid["paid_by_user_id"] == "acct-beta"
        assert paid["payment_reference"] == "WIRE-2026-08-0001"
        assert_same_instant(paid["paid_at"], CLOCK_ORIGIN)

        settled_composer = read_composer(api, composer_id)
        assert_composer_money(
            settled_composer, accrued_unpaid_cents=0, lifetime_paid_cents=45500
        )
        assert settled_composer["latest_statement_period_end"].startswith("2026-08-31")


# ---------------------------------------------------------------------------
# Licensee credit exposure and the quoting gate
# ---------------------------------------------------------------------------


def _two_quotes_filling_the_limit(api):
    """A licensee whose 492000 limit is filled to the cent by two reservations."""
    work = new_cataloged_work(
        api,
        composer_overrides={"display_name": "Nadia Okoro", "pro_affiliation": "ASCAP"},
        agreement_overrides={"sync_fee_share_pct": 40.00},
        title="Harbour Lights",
        duration_sec=180,
        tempo_bpm=130,
        genre="CINEMATIC",
        mood_tags=["EPIC"],
        instrumentation=["STRINGS"],
    )
    broadcast_tier = new_tier(
        api,
        code="BTV-STD",
        media_type="BROADCAST_TV",
        allowed_scales=["LOCAL", "NATIONAL", "WORLDWIDE"],
        base_rate_cents=300000,
    )
    corporate_tier = new_tier(
        api,
        code="CORP-LOW",
        media_type="CORPORATE",
        allowed_scales=["LOCAL", "NATIONAL"],
        base_rate_cents=200000,
    )
    licensee = new_licensee(
        api,
        legal_name="Meridian Broadcasting",
        licensee_type="BROADCASTER",
        credit_limit_cents=492000,
    )
    first = _quoted_request(
        api,
        work,
        broadcast_tier,
        licensee,
        media_type="BROADCAST_TV",
        distribution_scale="NATIONAL",
        requested_term_start="2026-09-01T00:00:00Z",
        requested_term_months=12,
    )
    second = _quoted_request(
        api,
        work,
        corporate_tier,
        licensee,
        media_type="CORPORATE",
        distribution_scale="LOCAL",
        requested_term_start="2026-09-01T00:00:00Z",
        requested_term_months=12,
    )
    return {
        "work": work,
        "broadcast_tier": broadcast_tier,
        "licensee": licensee,
        "first": first,
        "second": second,
    }


class TestCreditLimitGateOnQuoting:
    def test_reserved_spend_is_the_sum_of_the_standing_quoted_fees(self, api):
        """PRD §3.4: "`reserved_spend_cents` is the sum of `quoted_fee_cents` over this
        licensee's sync requests in `QUOTED`, `ACCEPTED` or `EDIT_IN_PROGRESS` that have
        not yet produced a licence."

        Design: Corner/calculations/credit_limit_gate_allows_equality_then_refuses_the_next_quote
        """
        ground = _two_quotes_filling_the_limit(api)

        # 300000 x 1.30 and 200000 x 0.85 x 0.60, both below the first discount band.
        assert_cents_equal(ground["first"]["quoted_fee_cents"], 390000, "first quoted_fee_cents")
        assert_cents_equal(ground["second"]["quoted_fee_cents"], 102000, "second quoted_fee_cents")
        assert_credit_exposure(read_licensee(api, ground["licensee"]["id"]), 0, 492000, 0)

    def test_quote_beyond_the_limit_is_refused_and_leaves_no_reservation(self, api):
        """PRD §3.4: "Before it does so, the credit gate applies: committed plus reserved
        plus this quote's fee must not exceed `credit_limit_cents`, with equality
        allowed, or the quote is refused with `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Corner/calculations/credit_limit_gate_allows_equality_then_refuses_the_next_quote
        """
        ground = _two_quotes_filling_the_limit(api)
        third = _request_under_review(
            api,
            ground["work"],
            ground["broadcast_tier"],
            ground["licensee"],
            media_type="BROADCAST_TV",
            distribution_scale="NATIONAL",
            requested_term_start="2026-09-01T00:00:00Z",
            requested_term_months=12,
        )

        assert_declared_error(
            api.quote_sync_request(third.sync_request_id, build.quote_payload(14), LICENSING_AGENT),
            "ERR_CREDIT_LIMIT_EXCEEDED",
        )

        refused = assert_ok(api.get_sync_request(third.sync_request_id, LICENSING_AGENT))
        assert_status(refused, "UNDER_REVIEW")
        assert refused["quoted_fee_cents"] is None
        assert refused["quoted_spend_basis_cents"] is None
        assert refused["quoted_discount_pct"] is None
        assert refused["quote_expires_at"] is None
        assert_credit_exposure(read_licensee(api, ground["licensee"]["id"]), 0, 492000, 0)
