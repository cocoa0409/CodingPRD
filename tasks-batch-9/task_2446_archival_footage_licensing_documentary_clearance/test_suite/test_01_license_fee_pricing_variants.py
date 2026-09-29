"""Rate-card pricing: the window-class variant switch and the single terminal round.

Both scenarios below price a licence at creation against exactly one asset and
exactly one rate card, and both turn on where the rounding happens rather than on
which numbers go in.
"""
from test_helpers import (
    assert_license,
    create_archive_with_rate_card,
    create_asset_with_selected_source,
    create_license,
    create_production_in_clearance,
    get_asset,
    get_license,
    get_production,
    make_rights_holder_rep_headers,
)


def _setup_window_variant_scenario(api):
    """Two byte-identical 45-second footage assets at one archive on one ACTIVE card.

    The card is the PRD §3.3 worked example: base 60000 cents per thirty-second
    unit, an all-media floor of 150000, a festival floor of 40000 and every
    multiplier left at its declared default.
    """
    production = create_production_in_clearance(
        api, title="Reel Histories", delivery_deadline_date="2027-06-30")
    archive, card = create_archive_with_rate_card(
        api,
        archive_overrides={"name": "Pathe Vault", "holder_type": "FILM_ARCHIVE"},
        card_overrides={
            "base_rate_per_30s_cents": 60000,
            "minimum_fee_cents": 150000,
            "festival_minimum_fee_cents": 40000,
            "effective_from_date": "2026-01-01",
        })
    asset_a, _candidate_a = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Bus boycott exterior",
        timecode_in_seconds=0, timecode_out_seconds=45)
    asset_b, _candidate_b = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Courthouse steps",
        timecode_in_seconds=100, timecode_out_seconds=145)
    return production, archive, card, asset_a, asset_b


def _setup_odd_base_rate_scenario(api):
    """One 45-second footage asset against a card whose base rate is the odd 33333.

    Both fee floors are 1000, far below any product the six factors can yield, so
    no floor comparison can mask the arithmetic.
    """
    production = create_production_in_clearance(
        api, title="Odd Rate Study", delivery_deadline_date="2028-01-31")
    archive, card = create_archive_with_rate_card(
        api,
        archive_overrides={"name": "Kinolibrary", "holder_type": "NEWS_ARCHIVE"},
        card_overrides={
            "base_rate_per_30s_cents": 33333,
            "minimum_fee_cents": 1000,
            "festival_minimum_fee_cents": 1000,
            "effective_from_date": "2026-01-01",
        })
    asset, _candidate = create_asset_with_selected_source(
        api, production["id"], archive["id"],
        candidate_overrides={"provenance_confidence": 80},
        title="Dockyard strike", timecode_in_seconds=5, timecode_out_seconds=50)
    return production, archive, card, asset


def _open_odd_rate_licence(api, production, archive, asset):
    """The STREAMING / WORLD / FESTIVAL_ONLY / 18-month deal on the odd-rate card."""
    return create_license(
        api, production["id"], asset["id"], archive["id"],
        rights_leg="FOOTAGE", media="STREAMING", territory="WORLD",
        window_class="FESTIVAL_ONLY", term_months=18,
        term_start_date="2026-09-01", term_end_date="2028-03-01")


# ─── The window-class variant on the money path ──────────────────────────────


def test_all_media_window_licence_prices_at_the_full_six_factor_product(api):
    """An ALL_MEDIA_WINDOW licence takes the all-media window multiplier and floor.

    PRD §3.3: "A licence whose `window_class` is `ALL_MEDIA_WINDOW` uses
    `all_media_window_multiplier` as its window multiplier and `minimum_fee_cents`
    as its fee floor." The worked example pins the figure: "Under
    `ALL_MEDIA_WINDOW` the window multiplier of 1.00 yields 362250 cents, which
    clears the all-media floor of 150000."

    Design: Difficulty/dual_variant_calc/license_fee_festival_versus_all_media_window_variant
    """
    production, archive, card, asset_a, _asset_b = _setup_window_variant_scenario(api)

    created = create_license(
        api, production["id"], asset_a["id"], archive["id"],
        window_class="ALL_MEDIA_WINDOW", media="BROADCAST", territory="WORLD",
        term_months=36, term_start_date="2026-08-15", term_end_date="2029-08-15")

    assert_license(created)
    assert created["window_class"] == "ALL_MEDIA_WINDOW"
    assert created["billable_units"] == 2
    assert created["rate_card_fee_cents"] == 362250
    assert created["rate_card_id"] == card["id"]

    persisted = get_license(api, created["id"])
    assert persisted["rate_card_fee_cents"] == 362250
    # The rounded product clears the all-media floor, so the floor is not the answer.
    assert persisted["rate_card_fee_cents"] > 150000


def test_festival_only_licence_prices_at_the_festival_multiplier_and_floor(api):
    """A FESTIVAL_ONLY licence takes 0.35 and the festival floor, rounding once.

    PRD §3.3: "A licence whose `window_class` is `FESTIVAL_ONLY` — a film cleared
    only for festival exhibition — uses `festival_window_multiplier` as its window
    multiplier and `festival_minimum_fee_cents` as its fee floor." The worked
    example pins the rounding: "Under `FESTIVAL_ONLY` the window multiplier of
    0.35 yields a raw product of 126787.5, which rounds half up to 126788 cents
    and clears the festival floor of 40000."

    Design: Difficulty/dual_variant_calc/license_fee_festival_versus_all_media_window_variant
    """
    production, archive, _card, _asset_a, asset_b = _setup_window_variant_scenario(api)

    created = create_license(
        api, production["id"], asset_b["id"], archive["id"],
        window_class="FESTIVAL_ONLY", media="BROADCAST", territory="WORLD",
        term_months=36, term_start_date="2026-08-15", term_end_date="2029-08-15")

    assert_license(created)
    assert created["window_class"] == "FESTIVAL_ONLY"
    assert created["billable_units"] == 2
    # 126787.5 rounded half up exactly once — never truncated to 126787.
    assert created["rate_card_fee_cents"] == 126788
    assert created["rate_card_fee_cents"] != 126787

    persisted = get_license(api, created["id"],
                            make_rights_holder_rep_headers(archive["id"]))
    assert persisted["rate_card_fee_cents"] == 126788
    # The rounded product clears the festival floor, so the floor is not the answer.
    assert persisted["rate_card_fee_cents"] > 40000


def test_window_class_alone_diverges_the_two_fees_by_235462_cents(api):
    """Identical duration, media, territory and term diverge purely on the window.

    PRD §3.3: "The same asset, media, territory and term therefore differ by
    235462 cents purely on the window sold."

    Design: Difficulty/dual_variant_calc/license_fee_festival_versus_all_media_window_variant
    """
    production, archive, _card, asset_a, asset_b = _setup_window_variant_scenario(api)

    all_media = create_license(
        api, production["id"], asset_a["id"], archive["id"],
        window_class="ALL_MEDIA_WINDOW", media="BROADCAST", territory="WORLD",
        term_months=36, term_start_date="2026-08-15", term_end_date="2029-08-15")
    festival = create_license(
        api, production["id"], asset_b["id"], archive["id"],
        window_class="FESTIVAL_ONLY", media="BROADCAST", territory="WORLD",
        term_months=36, term_start_date="2026-08-15", term_end_date="2029-08-15")

    # Both assets are 45 seconds long, so both bill two thirty-second units.
    assert get_asset(api, asset_a["id"])["duration_seconds"] == 45
    assert get_asset(api, asset_b["id"])["duration_seconds"] == 45
    assert all_media["billable_units"] == 2
    assert festival["billable_units"] == 2

    assert all_media["rate_card_fee_cents"] == 362250
    assert festival["rate_card_fee_cents"] == 126788
    assert all_media["rate_card_fee_cents"] - festival["rate_card_fee_cents"] == 235462

    # PRD §3.3 initialises current_proposed_fee_cents to that same rate-card figure,
    # so the standing proposal before any negotiation is the list price.
    assert all_media["current_proposed_fee_cents"] == 362250
    assert festival["current_proposed_fee_cents"] == 126788
    assert all_media["status"] == "DRAFT"
    assert festival["status"] == "DRAFT"


# ─── The six-factor product with a single terminal round ─────────────────────


def test_six_factor_product_is_rounded_half_up_exactly_once(api):
    """The six factors are held at full precision and rounded once, yielding 68249.

    PRD §3.3: "The raw fee is the product of six quantities held at full precision
    throughout: `base_rate_per_30s_cents`, the billable unit count, the duration
    tier's rate multiplier, the media multiplier, the territory multiplier, the
    term factor, and the window multiplier. That product is rounded half up to an
    integer number of cents exactly once, and only then is `rate_card_fee_cents`
    taken as the larger of that rounded product and the window's fee floor."

    Design: Difficulty/combinatorial_formula/license_fee_six_factor_product_rounds_once_at_the_end
    """
    production, archive, _card, asset = _setup_odd_base_rate_scenario(api)

    created = _open_odd_rate_licence(api, production, archive, asset)

    assert_license(created)
    assert get_asset(api, asset["id"])["duration_seconds"] == 45
    assert created["billable_units"] == 2
    # 33333 * 2 * 1.25 * 1.30 * 1.50 * 1.20 * 0.35 = 68249.3175, rounded once.
    assert created["rate_card_fee_cents"] == 68249
    # 68250 is what rounding after each individual factor produces.
    assert created["rate_card_fee_cents"] != 68250

    persisted = get_license(api, created["id"])
    assert persisted["rate_card_fee_cents"] == 68249


def test_rounded_product_beats_the_floor_and_becomes_the_standing_proposal(api):
    """The rounded product, not the 1000-cent festival floor, is stamped and proposed.

    PRD §3.3: "It then runs the rate-card pricing described below and stamps the
    result onto `rate_card_fee_cents`, initialises `current_proposed_fee_cents` to
    that same rate-card figure so that the standing proposal before any
    negotiation is the list price, sets `round_count` to zero, sets
    `mfn_topup_cents` and `mfn_benchmark_fee_cents` to zero, and leaves
    `executed_fee_cents` and `termination_reason` null."

    Design: Difficulty/combinatorial_formula/license_fee_six_factor_product_rounds_once_at_the_end
    """
    production, archive, _card, asset = _setup_odd_base_rate_scenario(api)

    created = _open_odd_rate_licence(api, production, archive, asset)

    assert created["status"] == "DRAFT"
    assert created["rate_card_fee_cents"] == 68249
    assert created["current_proposed_fee_cents"] == 68249
    assert created["round_count"] == 0
    assert created["mfn_topup_cents"] == 0
    assert created["mfn_benchmark_fee_cents"] == 0
    assert created["executed_fee_cents"] is None
    assert created["termination_reason"] is None
    # The floor of 1000 never enters: the rounded product is the larger figure.
    assert created["rate_card_fee_cents"] > 1000

    persisted = get_license(api, created["id"],
                            make_rights_holder_rep_headers(archive["id"]))
    assert persisted["rate_card_fee_cents"] == 68249
    assert persisted["current_proposed_fee_cents"] == 68249
    assert persisted["status"] == "DRAFT"


def test_drafting_the_priced_licence_moves_the_asset_into_negotiation(api):
    """The single rounded fee lands on a DRAFT licence that opens the negotiation.

    PRD §3.3: "Creation then runs the clearance rollup, which moves the asset's
    dimension A from `UNCLEARED → IN_NEGOTIATION` because a licence for the asset
    now exists in `DRAFT`, followed by the posture recomputation; the asset's
    `version` and the production's `version` each increment by one."

    Design: Difficulty/combinatorial_formula/license_fee_six_factor_product_rounds_once_at_the_end
    """
    production, archive, _card, asset = _setup_odd_base_rate_scenario(api)
    asset_version_before = get_asset(api, asset["id"])["version"]
    production_version_before = get_production(api, production["id"])["version"]

    created = _open_odd_rate_licence(api, production, archive, asset)

    assert created["rate_card_fee_cents"] == 68249

    settled_asset = get_asset(api, asset["id"])
    assert settled_asset["licensing_status"] == "IN_NEGOTIATION"
    assert settled_asset["rights_basis"] == "UNDETERMINED"
    assert settled_asset["version"] == asset_version_before + 1

    settled_production = get_production(api, production["id"])
    assert settled_production["version"] == production_version_before + 1
    # A DRAFT licence has a null executed_fee_cents, so it is outside the summed
    # set of PRD §2.9 and the money ledger has not moved.
    assert created["executed_fee_cents"] is None
    assert settled_production["committed_fee_cents"] == 0
