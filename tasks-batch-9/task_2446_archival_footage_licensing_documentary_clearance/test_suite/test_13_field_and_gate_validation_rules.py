"""Field-level and gate-level refusals: leg pairing, source selection, term shape,
body-reference ordering, the window claim, rate-card resolution, the coverage bounds,
the renewal arithmetic and the parent production's willingness to take new work.

Every refusal below is paired with the observable post-state it must leave behind,
and where the same rule has an accepting side that side is exercised too.
"""
from test_helpers import (
    ARCHIVE_RESEARCHER,
    CLEARANCE_SUPERVISOR,
    LEGAL_COUNSEL,
    LEGAL_COUNSEL_USER_ID,
    NON_EXISTENT_UUID,
    PRODUCTION_ADMIN,
    REVIEWING_COUNSEL,
    add_source_candidate,
    assert_asset_dimensions,
    assert_delivery_package,
    assert_eo_application,
    assert_fair_use_analysis,
    assert_license,
    assert_posture,
    assert_production_counters,
    create_archive_with_rate_card,
    create_asset,
    create_asset_payload,
    create_asset_with_selected_source,
    create_eo_application_payload,
    create_fair_use_analysis,
    create_license,
    create_license_payload,
    create_production,
    create_production_in_clearance,
    create_subject_release_payload,
    drive_fair_use_analysis,
    drive_production,
    execute_license,
    get_asset,
    get_delivery_package,
    get_license,
    get_production,
    get_success_data,
    issue_opinion_letter,
    list_all,
    open_delivery_package,
    pin_chart,
    quote_license,
    renew_license_payload,
    run_sweep,
    select_source,
    set_clock,
    state_payload,
    validate_delivery_package,
    validate_error,
    validate_success,
)

# The standard card of the PRD §3.3 worked example.
STANDARD_CARD = {
    "base_rate_per_30s_cents": 60000,
    "minimum_fee_cents": 150000,
    "festival_minimum_fee_cents": 40000,
    "effective_from_date": "2026-01-01",
}

# A 45-second BROADCAST / WORLD / 12-month deal on that card prices at
# 60000 * 2 * 1.25 * 1.15 * 1.50 * 1.00 = 258750 under the all-media window and
# at 0.35 of that — 90562.5, rounded half up to 90563 — under the festival window.
TWELVE_MONTH_TERM = {
    "term_months": 12,
    "term_start_date": "2026-08-15",
    "term_end_date": "2027-08-15",
}
ALL_MEDIA_FEE_CENTS = 258750
FESTIVAL_FEE_CENTS = 90563

WORLD_BROADCAST = {"media": "BROADCAST", "territory": "WORLD"}


def _licence_payload(production, asset, archive, **overrides):
    """A licence body over the standard 12-month BROADCAST / WORLD deal."""
    body = dict(WORLD_BROADCAST)
    body.update(TWELVE_MONTH_TERM)
    body["rights_leg"] = "FOOTAGE"
    body["window_class"] = "ALL_MEDIA_WINDOW"
    body.update(overrides)
    return create_license_payload(production["id"], asset["id"], archive["id"], **body)


def _licences_of(api, production):
    return list_all(api.list_licenses, CLEARANCE_SUPERVISOR,
                    {"production_id": production["id"]})


def _candidates_of(api, asset):
    return get_success_data(
        api.list_asset_source_candidates(asset["id"], ARCHIVE_RESEARCHER,
                                         params={"limit": 100}))


def _setup_priceable_footage_asset(api, title, card_overrides=None):
    """A CLEARANCE production with one 45-second footage asset ready to be licensed.

    The asset's only source candidate is `AVAILABLE` and `SELECTED` at the one
    `ACTIVE` archive, which holds a single `ACTIVE` rate card.
    """
    production = create_production_in_clearance(
        api, title=title, delivery_deadline_date="2027-06-30")
    archive, card = create_archive_with_rate_card(
        api, archive_overrides={"name": "Pathe Vault", "holder_type": "FILM_ARCHIVE"},
        card_overrides=card_overrides or STANDARD_CARD)
    asset, _candidate = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Tram depot",
        timecode_in_seconds=0, timecode_out_seconds=45)
    return production, archive, card, asset


def _setup_exact_threshold_analysis(api):
    """A SUBMITTED fair-use analysis scoring exactly 0.6000 with an ISSUED letter.

    The asset is used for `CRITICAL_COMMENTARY`, so the transformative weighting
    applies: four factor scores of 60 give
    0.60*0.45 + 0.60*0.10 + 0.60*0.15 + 0.60*0.30 = 0.6000 exactly.
    """
    production = create_production_in_clearance(
        api, title="Exact Sixty", delivery_deadline_date="2027-06-30")
    asset = create_asset(api, production["id"], title="Newsreel excerpt",
                         timecode_in_seconds=0, timecode_out_seconds=45,
                         usage_purpose="CRITICAL_COMMENTARY")
    analysis = create_fair_use_analysis(
        api, asset["id"], transformative_score=60, nature_score=60,
        amount_used_score=60, market_harm_score=60)
    drive_fair_use_analysis(api, analysis["id"], "SUBMITTED")
    letter = issue_opinion_letter(api, analysis["id"], LEGAL_COUNSEL,
                                 counsel_firm="Marsh & Keel LLP",
                                 letter_reference="OL-4471", risk_rating="LOW")
    return production, asset, analysis, letter


def _setup_leg_pairing_scenario(api):
    """One MUSIC asset and one ARCHIVAL_FOOTAGE asset, both with a SELECTED source.

    Selecting a source on both assets keeps the source-selection rule out of the
    way, so a mismatched leg is decided purely on the parent asset's type.
    """
    production = create_production_in_clearance(
        api, title="Wrong Leg", delivery_deadline_date="2027-06-30")
    archive, _card = create_archive_with_rate_card(
        api, archive_overrides={"name": "Pathe Vault", "holder_type": "FILM_ARCHIVE"},
        card_overrides=STANDARD_CARD)
    music, _music_candidate = create_asset_with_selected_source(
        api, production["id"], archive["id"], asset_type="MUSIC", title="Bridge cue",
        timecode_in_seconds=0, timecode_out_seconds=45,
        usage_purpose="ILLUSTRATIVE_BACKGROUND")
    footage, _footage_candidate = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Harbour pan",
        timecode_in_seconds=0, timecode_out_seconds=45)
    return production, archive, music, footage


def _setup_two_archive_scenario(api):
    """Two ACTIVE archives, each with an ACTIVE card, and a candidate at archive A only.

    The candidate is left `NOT_SELECTED` so that both halves of the source rule can
    be walked from the same fixture.
    """
    production = create_production_in_clearance(
        api, title="Source Mismatch", delivery_deadline_date="2027-06-30")
    archive_a, card_a = create_archive_with_rate_card(
        api, archive_overrides={"name": "Pathe Vault", "holder_type": "FILM_ARCHIVE"},
        card_overrides=STANDARD_CARD)
    archive_b, card_b = create_archive_with_rate_card(
        api, archive_overrides={"name": "Kinolibrary", "holder_type": "NEWS_ARCHIVE"},
        card_overrides=STANDARD_CARD)
    asset = create_asset(api, production["id"], title="Dockyard strike",
                         timecode_in_seconds=0, timecode_out_seconds=45)
    candidate = add_source_candidate(api, asset["id"], archive_a["id"],
                                     availability_status="AVAILABLE")
    return production, archive_a, card_a, archive_b, card_b, asset, candidate


def _setup_mixed_window_delivery_scenario(api):
    """Two CLEARED footage assets, one licensed all-media and one festival-only.

    Posture is `OPEN` and one chart is pinned over both rows, so the posture check,
    the two chart-currency checks and the cue-sheet check are all satisfied and the
    window claim is the only rule left standing.
    """
    production = create_production_in_clearance(
        api, title="Window Mix", delivery_deadline_date="2027-06-30")
    archive, _card = create_archive_with_rate_card(
        api, archive_overrides={"name": "Pathe Vault", "holder_type": "FILM_ARCHIVE"},
        card_overrides=STANDARD_CARD)

    licences = {}
    for label, title, window in (("all_media", "Crowd wide", "ALL_MEDIA_WINDOW"),
                                 ("festival", "Rally tight", "FESTIVAL_ONLY")):
        asset, _candidate = create_asset_with_selected_source(
            api, production["id"], archive["id"], title=title,
            timecode_in_seconds=0, timecode_out_seconds=45)
        licence = create_license(api, production["id"], asset["id"], archive["id"],
                                 rights_leg="FOOTAGE", window_class=window,
                                 **WORLD_BROADCAST, **TWELVE_MONTH_TERM)
        quote_license(api, licence["id"], archive["id"])
        licences[label] = execute_license(api, licence["id"])

    chart = pin_chart(api, production["id"], chart_label="delivery v1")
    all_media_package = open_delivery_package(api, production["id"], chart["id"],
                                              distributor_name="Northgate Films",
                                              window_class="ALL_MEDIA_WINDOW")
    festival_package = open_delivery_package(api, production["id"], chart["id"],
                                             distributor_name="Fest Circuit Co",
                                             window_class="FESTIVAL_ONLY")
    return {
        "production": production,
        "archive": archive,
        "licences": licences,
        "chart": chart,
        "all_media_package": all_media_package,
        "festival_package": festival_package,
    }


def _setup_chart_without_assets(api):
    """A CLEARANCE production with no assets and one PINNED chart over zero rows."""
    production = create_production_in_clearance(
        api, title="Thin Cover", delivery_deadline_date="2027-06-30")
    chart = pin_chart(api, production["id"], chart_label="v1")
    return production, chart


def _setup_renewable_active_licence(api):
    """An ACTIVE 12-month licence with the clock parked 45 days from its term end.

    The licence is executed at 2026-08-20 and activated by a sweep, and the clock
    then moves to 2027-07-01, which is 45 whole days before 2027-08-15.
    """
    set_clock(api, "2026-08-20T00:00:00Z")
    production, archive, _card, asset = _setup_priceable_footage_asset(
        api, "Empty Renewal")
    licence = create_license(api, production["id"], asset["id"], archive["id"],
                             rights_leg="FOOTAGE", window_class="ALL_MEDIA_WINDOW",
                             **WORLD_BROADCAST, **TWELVE_MONTH_TERM)
    quote_license(api, licence["id"], archive["id"], ALL_MEDIA_FEE_CENTS)
    execute_license(api, licence["id"])
    run_sweep(api, production["id"])
    set_clock(api, "2027-07-01T00:00:00Z")
    return production, archive, asset, get_license(api, licence["id"])


def _setup_abandoned_production(api):
    """A production that took one asset in DEVELOPMENT and was then ABANDONED.

    No licence was ever opened, so abandonment itself is unobstructed.
    """
    production = create_production(api, title="Shelved Film",
                                   delivery_deadline_date="2027-06-30")
    assert production["status"] == "DEVELOPMENT"
    asset = create_asset(api, production["id"], title="Pre-clearance shot",
                         timecode_in_seconds=0, timecode_out_seconds=45)
    abandoned = drive_production(api, production["id"], "ABANDONED", PRODUCTION_ADMIN,
                                 reason="Funding withdrawn")
    return abandoned, asset


# ─── The fair-use acceptance gates at the inclusive score edge ────────────────


def test_fair_use_acceptance_passes_at_a_score_of_exactly_the_threshold(api):
    """An analysis scoring 0.6000 with an ISSUED letter clears the asset on FAIR_USE.

    PRD §3.5: "The threshold is inclusive at the boundary: a score of exactly
    0.6000 is acceptable." The letter gate is what makes the score gate reachable:
    "only once at least one opinion letter on the analysis is in `ISSUED` does the
    score gate apply, refusing a `strength_score` below 0.6000 with
    `ERR_FAIR_USE_SCORE_INSUFFICIENT` (HTTP 422)."

    Design: Corner/validations/fair_use_acceptance_at_the_exact_score_threshold_passes_every_gate
    """
    production, asset, analysis, letter = _setup_exact_threshold_analysis(api)

    assert_fair_use_analysis(analysis)
    assert analysis["weighting_variant"] == "TRANSFORMATIVE_WEIGHTED"
    assert analysis["strength_score"] == 0.6
    assert letter["status"] == "ISSUED"
    assert letter["issued_by_user_id"] == LEGAL_COUNSEL_USER_ID

    accepted = drive_fair_use_analysis(
        api, analysis["id"], "ACCEPTED", REVIEWING_COUNSEL,
        decision_rationale="Four-factor analysis supports the use.")

    assert accepted["status"] == "ACCEPTED"
    assert accepted["decision_rationale"] == "Four-factor analysis supports the use."
    assert accepted["strength_score"] == 0.6

    # PRD §3.5: acceptance is what clears the asset, with no licence in existence.
    assert_asset_dimensions(get_asset(api, asset["id"]), "CLEARED",
                            rights_basis="FAIR_USE", lapse_count=0)
    assert _licences_of(api, production) == []

    settled = get_production(api, production["id"])
    assert_production_counters(settled, asset_count=1, cleared_asset_count=1,
                               open_asset_count=0)
    assert_posture(settled, "OPEN")
    assert settled["committed_fee_cents"] == 0


# ─── The leg-pairing conditional, both directions ────────────────────────────


def test_mismatched_rights_leg_is_refused_from_either_asset_type(api):
    """A FOOTAGE leg on a MUSIC asset and a MASTER leg on footage share one error id.

    PRD §3.3: "The leg must match the asset type — `MUSIC` takes `MASTER` or
    `PUBLISHING`, `ARCHIVAL_FOOTAGE` takes `FOOTAGE`, and any other pairing yields
    `ERR_MUSIC_LEG_REQUIRED`."

    Design: Corner/validations/music_leg_requirement_is_conditional_on_the_asset_type
    """
    production, archive, music, footage = _setup_leg_pairing_scenario(api)

    footage_leg_on_music = api.create_license(
        _licence_payload(production, music, archive, rights_leg="FOOTAGE"),
        CLEARANCE_SUPERVISOR)
    validate_error(footage_leg_on_music, "ERR_MUSIC_LEG_REQUIRED", 422)

    master_leg_on_footage = api.create_license(
        _licence_payload(production, footage, archive, rights_leg="MASTER"),
        CLEARANCE_SUPERVISOR)
    validate_error(master_leg_on_footage, "ERR_MUSIC_LEG_REQUIRED", 422)

    # Neither refusal opened a negotiation on either asset.
    assert _licences_of(api, production) == []
    assert_asset_dimensions(get_asset(api, music["id"]), "UNCLEARED",
                            rights_basis="UNDETERMINED")
    assert_asset_dimensions(get_asset(api, footage["id"]), "UNCLEARED",
                            rights_basis="UNDETERMINED")

    settled = get_production(api, production["id"])
    assert_production_counters(settled, asset_count=2, cleared_asset_count=0,
                               open_asset_count=2)
    assert settled["committed_fee_cents"] == 0


def test_matching_rights_leg_is_accepted_for_each_asset_type(api):
    """A MASTER leg on the MUSIC asset and a FOOTAGE leg on the footage asset pass.

    PRD §2.12 rung 36: "A `MUSIC` asset takes a `rights_leg` of `MASTER` or
    `PUBLISHING`, and an `ARCHIVAL_FOOTAGE` asset takes `FOOTAGE` — otherwise
    `ERR_MUSIC_LEG_REQUIRED`. Applies to licence creation."

    Design: Corner/validations/music_leg_requirement_is_conditional_on_the_asset_type
    """
    production, archive, music, footage = _setup_leg_pairing_scenario(api)

    master = create_license(api, production["id"], music["id"], archive["id"],
                            rights_leg="MASTER", window_class="ALL_MEDIA_WINDOW",
                            **WORLD_BROADCAST, **TWELVE_MONTH_TERM)
    footage_licence = create_license(api, production["id"], footage["id"],
                                     archive["id"], rights_leg="FOOTAGE",
                                     window_class="ALL_MEDIA_WINDOW",
                                     **WORLD_BROADCAST, **TWELVE_MONTH_TERM)

    assert_license(master)
    assert master["rights_leg"] == "MASTER"
    assert master["status"] == "DRAFT"
    assert master["rate_card_fee_cents"] == ALL_MEDIA_FEE_CENTS
    assert_license(footage_licence)
    assert footage_licence["rights_leg"] == "FOOTAGE"
    assert footage_licence["rate_card_fee_cents"] == ALL_MEDIA_FEE_CENTS

    assert_asset_dimensions(get_asset(api, music["id"]), "IN_NEGOTIATION",
                            rights_basis="UNDETERMINED")
    assert_asset_dimensions(get_asset(api, footage["id"]), "IN_NEGOTIATION",
                            rights_basis="UNDETERMINED")
    # Both licences are DRAFT, so nothing has been committed.
    assert get_production(api, production["id"])["committed_fee_cents"] == 0


# ─── The two halves of the source-selection rule ─────────────────────────────


def test_footage_licence_without_any_selected_candidate_is_refused(api):
    """A FOOTAGE leg on an asset whose only candidate is NOT_SELECTED is refused.

    PRD §3.3: "The source-selection check comes next: for a `FOOTAGE` leg the asset
    must have exactly one source candidate in `SELECTED`, and the licence's
    `archive_id` must equal that candidate's `archive_id`, since licensing footage
    from an institution other than the one whose print was chosen is meaningless —
    either failure yields `ERR_NO_SELECTED_SOURCE`."

    Design: Corner/validations/footage_license_needs_a_selected_source_from_the_named_archive
    """
    production, archive_a, _card_a, _archive_b, _card_b, asset, candidate = (
        _setup_two_archive_scenario(api))

    refused = api.create_license(_licence_payload(production, asset, archive_a),
                                 CLEARANCE_SUPERVISOR)
    validate_error(refused, "ERR_NO_SELECTED_SOURCE", 409)

    assert _licences_of(api, production) == []
    settled_asset = get_asset(api, asset["id"])
    assert settled_asset["selected_source_candidate_id"] is None
    assert_asset_dimensions(settled_asset, "UNCLEARED", rights_basis="UNDETERMINED")

    candidates = _candidates_of(api, asset)
    assert len(candidates) == 1
    assert candidates[0]["id"] == candidate["id"]
    assert candidates[0]["selection_status"] == "NOT_SELECTED"


def test_footage_licence_naming_an_archive_other_than_the_selected_one_is_refused(api):
    """With the print chosen at archive A, a licence naming archive B is refused.

    PRD §2.12 rung 13: "For a `FOOTAGE` leg, the asset has exactly one source
    candidate in `SELECTED` and the licence's `archive_id` equals that candidate's
    `archive_id` — otherwise `ERR_NO_SELECTED_SOURCE`. Applies to licence creation."

    Design: Corner/validations/footage_license_needs_a_selected_source_from_the_named_archive
    """
    production, archive_a, card_a, archive_b, card_b, asset, candidate = (
        _setup_two_archive_scenario(api))

    select_source(api, asset["id"], candidate["id"])

    # Archive B is ACTIVE and holds its own ACTIVE card, so only the identity of the
    # selected candidate's archive can be deciding this.
    assert card_b["status"] == "ACTIVE"
    wrong_archive = api.create_license(_licence_payload(production, asset, archive_b),
                                       CLEARANCE_SUPERVISOR)
    validate_error(wrong_archive, "ERR_NO_SELECTED_SOURCE", 409)
    assert _licences_of(api, production) == []

    accepted = create_license(api, production["id"], asset["id"], archive_a["id"],
                              rights_leg="FOOTAGE", window_class="ALL_MEDIA_WINDOW",
                              **WORLD_BROADCAST, **TWELVE_MONTH_TERM)

    assert_license(accepted)
    assert accepted["archive_id"] == archive_a["id"]
    assert accepted["rate_card_id"] == card_a["id"]
    assert accepted["rate_card_fee_cents"] == ALL_MEDIA_FEE_CENTS

    settled_asset = get_asset(api, asset["id"])
    assert settled_asset["selected_source_candidate_id"] == candidate["id"]
    assert_asset_dimensions(settled_asset, "IN_NEGOTIATION",
                            rights_basis="UNDETERMINED")
    candidates = _candidates_of(api, asset)
    assert len(candidates) == 1
    assert candidates[0]["selection_status"] == "SELECTED"


# ─── The two halves of the term-shape rule ───────────────────────────────────


def test_term_start_not_strictly_earlier_than_term_end_is_refused(api):
    """An inverted range and a zero-length range both fail the strict inequality.

    PRD §3.3: "The term dates must be coherent, with `term_start_date` earlier than
    `term_end_date` and `term_months` consistent with the whole-month span between
    them, failing which the answer is `ERR_TERM_DATES_INVALID`."

    Design: Corner/validations/term_dates_inverted_or_month_span_inconsistent_rejected
    """
    production, archive, _card, asset = _setup_priceable_footage_asset(api, "Bad Dates")

    inverted = api.create_license(
        _licence_payload(production, asset, archive, term_months=12,
                         term_start_date="2027-08-15", term_end_date="2026-08-15"),
        CLEARANCE_SUPERVISOR)
    validate_error(inverted, "ERR_TERM_DATES_INVALID", 422)

    zero_length = api.create_license(
        _licence_payload(production, asset, archive, term_months=12,
                         term_start_date="2026-08-15", term_end_date="2026-08-15"),
        CLEARANCE_SUPERVISOR)
    validate_error(zero_length, "ERR_TERM_DATES_INVALID", 422)

    assert _licences_of(api, production) == []
    assert_asset_dimensions(get_asset(api, asset["id"]), "UNCLEARED",
                            rights_basis="UNDETERMINED")
    assert get_production(api, production["id"])["committed_fee_cents"] == 0


def test_term_months_disagreeing_with_the_whole_month_span_is_refused(api):
    """A well-ordered 12-month range declared as 24 months is refused, then accepted at 12.

    PRD §2.12 rung 37: "`term_start_date` is earlier than `term_end_date` and
    `term_months` is consistent with the whole-month span between them — otherwise
    `ERR_TERM_DATES_INVALID`. Applies to licence creation."

    Design: Corner/validations/term_dates_inverted_or_month_span_inconsistent_rejected
    """
    production, archive, _card, asset = _setup_priceable_footage_asset(api, "Bad Dates")

    # 2026-08-15 to 2027-08-15 is a span of 12 whole months, not 24.
    inconsistent = api.create_license(
        _licence_payload(production, asset, archive, term_months=24,
                         term_start_date="2026-08-15", term_end_date="2027-08-15"),
        CLEARANCE_SUPERVISOR)
    validate_error(inconsistent, "ERR_TERM_DATES_INVALID", 422)
    assert _licences_of(api, production) == []
    assert_asset_dimensions(get_asset(api, asset["id"]), "UNCLEARED",
                            rights_basis="UNDETERMINED")

    accepted = create_license(api, production["id"], asset["id"], archive["id"],
                              rights_leg="FOOTAGE", window_class="ALL_MEDIA_WINDOW",
                              **WORLD_BROADCAST, **TWELVE_MONTH_TERM)

    assert accepted["term_months"] == 12
    assert accepted["term_start_date"] == "2026-08-15"
    assert accepted["term_end_date"] == "2027-08-15"
    assert accepted["rate_card_fee_cents"] == ALL_MEDIA_FEE_CENTS
    assert_asset_dimensions(get_asset(api, asset["id"]), "IN_NEGOTIATION",
                            rights_basis="UNDETERMINED")


# ─── Body reference resolution outranks the term shape ───────────────────────


def test_unresolvable_archive_id_outranks_the_inverted_term_dates(api):
    """A licence naming a missing archive with an inverted term answers 404, not 422.

    PRD §2.12 rung 6: "Every foreign key supplied in the body resolves, checked left
    to right in declaration order — otherwise the referenced entity's not-found
    code." PRD §2.5 fixes the declaration order: "Licence creation declares
    `production_id`, then `asset_id`, then `archive_id`, so a request naming a bad
    production and a bad archive reports `ERR_PRODUCTION_NOT_FOUND`." Rung 6 sits
    above rung 37, "`term_start_date` is earlier than `term_end_date` and
    `term_months` is consistent with the whole-month span between them — otherwise
    `ERR_TERM_DATES_INVALID`."

    Design: Corner/validations/unknown_archive_id_outranks_the_inverted_term_dates
    """
    production, _archive, _card, asset = _setup_priceable_footage_asset(
        api, "Ghost Archive")
    version_before = get_production(api, production["id"])["version"]

    payload = create_license_payload(
        production["id"], asset["id"], NON_EXISTENT_UUID, rights_leg="FOOTAGE",
        window_class="ALL_MEDIA_WINDOW", term_months=12,
        term_start_date="2027-08-15", term_end_date="2026-08-15", **WORLD_BROADCAST)

    response = api.create_license(payload, CLEARANCE_SUPERVISOR)

    # The real production_id and asset_id resolve, so the archive is the leftmost
    # unresolvable body reference and it decides the answer.
    validate_error(response, "ERR_ARCHIVE_NOT_FOUND", 404)

    assert _licences_of(api, production) == []
    settled = get_production(api, production["id"])
    assert settled["version"] == version_before
    assert settled["committed_fee_cents"] == 0
    assert_asset_dimensions(get_asset(api, asset["id"]), "UNCLEARED",
                            rights_basis="UNDETERMINED")


# ─── The package window claim as an aggregate over live licences ─────────────


def test_all_media_package_is_refused_when_one_licence_is_festival_only(api):
    """One FESTIVAL_ONLY licence anywhere in the production defeats an all-media package.

    PRD §3.8: "And the window must be covered: when the package's `window_class` is
    `ALL_MEDIA_WINDOW`, every licence of the production whose `status` is
    `EXECUTED`, `ACTIVE` or `EXPIRING` must itself carry a `window_class` of
    `ALL_MEDIA_WINDOW`, because an all-media delivery may not rest on a
    festival-only licence; a shortfall is refused with
    `ERR_WINDOW_CLASS_INSUFFICIENT` (HTTP 409)."

    Design: Corner/validations/all_media_package_resting_on_a_festival_only_license_refused
    """
    scenario = _setup_mixed_window_delivery_scenario(api)
    production = scenario["production"]
    package = scenario["all_media_package"]

    # Both assets are CLEARED and posture is OPEN, so the posture check, the two
    # chart-currency checks and the cue-sheet check are all satisfied.
    settled = get_production(api, production["id"])
    assert_posture(settled, "OPEN")
    assert_production_counters(settled, asset_count=2, cleared_asset_count=2,
                               open_asset_count=0)
    assert scenario["chart"]["status"] == "PINNED"
    assert scenario["chart"]["music_leg_gap_count"] == 0

    response = api.set_delivery_package_state(package["id"], state_payload("VALIDATED"),
                                              CLEARANCE_SUPERVISOR)
    validate_error(response, "ERR_WINDOW_CLASS_INSUFFICIENT", 409)

    unchanged = get_delivery_package(api, package["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["version"] == package["version"]

    assert scenario["licences"]["all_media"]["rate_card_fee_cents"] == ALL_MEDIA_FEE_CENTS
    assert scenario["licences"]["festival"]["rate_card_fee_cents"] == FESTIVAL_FEE_CENTS
    assert settled["committed_fee_cents"] == ALL_MEDIA_FEE_CENTS + FESTIVAL_FEE_CENTS
    assert settled["committed_fee_cents"] == 349313


def test_festival_only_package_validates_on_the_very_same_chart(api):
    """The narrower window claim imposes no coverage requirement at all.

    PRD §3.8: "A package buying only the `FESTIVAL_ONLY` window imposes no such
    requirement. On success the three row counts are re-stamped from the chart and
    the package's `version` increments."

    Design: Corner/validations/all_media_package_resting_on_a_festival_only_license_refused
    """
    scenario = _setup_mixed_window_delivery_scenario(api)
    package = scenario["festival_package"]

    assert package["clearance_chart_id"] == scenario["chart"]["id"]
    assert package["window_class"] == "FESTIVAL_ONLY"
    assert scenario["licences"]["festival"]["window_class"] == "FESTIVAL_ONLY"

    validated = validate_delivery_package(api, package["id"])

    assert_delivery_package(validated)
    assert validated["status"] == "VALIDATED"
    assert validated["version"] == package["version"] + 1
    # The chart pins two footage rows and no music row.
    assert validated["rights_chart_row_count"] == 2
    assert validated["cue_sheet_row_count"] == 0
    assert validated["music_leg_gap_count"] == 0

    persisted = get_delivery_package(api, package["id"])
    assert persisted["status"] == "VALIDATED"
    # The all-media package alongside it was never touched.
    assert get_delivery_package(api, scenario["all_media_package"]["id"])["status"] == (
        "DRAFT")


# ─── Rate-card resolution precedes pricing ──────────────────────────────────


def test_card_effective_after_the_term_start_leaves_the_licence_unpriceable(api):
    """A card effective 2027-01-01 cannot price a term starting 2026-08-15.

    PRD §3.3: "Then the archive must be `ACTIVE` (`ERR_ARCHIVE_SUSPENDED`), the
    asset must belong to the named production (`ERR_ASSET_PRODUCTION_MISMATCH`),
    and the archive must have exactly one rate card in `ACTIVE` whose
    `effective_from_date` falls on or before the licence's `term_start_date`
    (`ERR_NO_ACTIVE_RATE_CARD`)."

    Design: Corner/validations/rate_card_effective_after_term_start_leaves_no_active_card
    """
    late_card = dict(STANDARD_CARD, effective_from_date="2027-01-01")
    production, archive, card, asset = _setup_priceable_footage_asset(
        api, "Late Card", card_overrides=late_card)
    assert card["status"] == "ACTIVE"
    assert card["effective_from_date"] == "2027-01-01"

    too_early = api.create_license(
        _licence_payload(production, asset, archive, term_months=12,
                         term_start_date="2026-08-15", term_end_date="2027-08-15"),
        CLEARANCE_SUPERVISOR)
    validate_error(too_early, "ERR_NO_ACTIVE_RATE_CARD", 422)

    assert _licences_of(api, production) == []
    assert_asset_dimensions(get_asset(api, asset["id"]), "UNCLEARED",
                            rights_basis="UNDETERMINED")

    # A term that begins after the card is effective resolves that same card.
    accepted = create_license(api, production["id"], asset["id"], archive["id"],
                              rights_leg="FOOTAGE", window_class="ALL_MEDIA_WINDOW",
                              term_months=12, term_start_date="2027-02-01",
                              term_end_date="2028-02-01", **WORLD_BROADCAST)

    assert_license(accepted)
    assert accepted["rate_card_id"] == card["id"]
    assert accepted["rate_card_fee_cents"] == ALL_MEDIA_FEE_CENTS
    assert_asset_dimensions(get_asset(api, asset["id"]), "IN_NEGOTIATION",
                            rights_basis="UNDETERMINED")


# ─── The two coverage bounds under one error id ─────────────────────────────


def test_coverage_limit_below_the_floor_is_refused_and_the_floor_itself_is_accepted(api):
    """99999 cents of cover is refused; the floor of 100000 cents is accepted.

    PRD §3.7: "The coverage figures must be commercially sane:
    `coverage_limit_cents` must be at least 100000 cents, and `retention_cents`
    must be zero or greater and strictly less than `coverage_limit_cents`; a
    violation of either is refused with `ERR_COVERAGE_LIMIT_INVALID` (HTTP 422)."

    Design: Corner/validations/coverage_limit_below_the_floor_and_retention_at_the_limit_rejected
    """
    production, chart = _setup_chart_without_assets(api)

    below_floor = api.create_eo_application(
        production["id"],
        create_eo_application_payload(chart["id"], coverage_limit_cents=99999,
                                      retention_cents=1000),
        PRODUCTION_ADMIN)
    validate_error(below_floor, "ERR_COVERAGE_LIMIT_INVALID", 422)

    at_floor = api.create_eo_application(
        production["id"],
        create_eo_application_payload(chart["id"], coverage_limit_cents=100000,
                                      retention_cents=0),
        PRODUCTION_ADMIN)
    created = validate_success(at_floor, 201)

    assert_eo_application(created)
    assert created["status"] == "DRAFT"
    assert created["coverage_limit_cents"] == 100000
    assert created["retention_cents"] == 0
    assert created["legal_review_status"] == "PENDING"
    assert created["underwriting_review_status"] == "PENDING"
    assert created["premium_cents"] is None
    assert created["policy_number"] is None
    assert created["production_id"] == production["id"]

    applications = list_all(api.list_eo_applications, CLEARANCE_SUPERVISOR,
                            {"production_id": production["id"]})
    assert len(applications) == 1
    assert applications[0]["id"] == created["id"]


def test_retention_equal_to_the_coverage_limit_is_refused(api):
    """Retention must be strictly below the limit, so equality is refused.

    PRD §2.12 rung 43: "`coverage_limit_cents` is at least 100000 and
    `retention_cents` is strictly less than `coverage_limit_cents` — otherwise
    `ERR_COVERAGE_LIMIT_INVALID`. Applies to E&O application creation."

    Design: Corner/validations/coverage_limit_below_the_floor_and_retention_at_the_limit_rejected
    """
    production, chart = _setup_chart_without_assets(api)

    equal_retention = api.create_eo_application(
        production["id"],
        create_eo_application_payload(chart["id"], coverage_limit_cents=500000,
                                      retention_cents=500000),
        PRODUCTION_ADMIN)
    validate_error(equal_retention, "ERR_COVERAGE_LIMIT_INVALID", 422)
    assert list_all(api.list_eo_applications, CLEARANCE_SUPERVISOR,
                    {"production_id": production["id"]}) == []

    # One cent below the limit satisfies the strict inequality.
    just_below = api.create_eo_application(
        production["id"],
        create_eo_application_payload(chart["id"], coverage_limit_cents=500000,
                                      retention_cents=499999),
        PRODUCTION_ADMIN)
    created = validate_success(just_below, 201)

    assert_eo_application(created)
    assert created["status"] == "DRAFT"
    assert created["coverage_limit_cents"] == 500000
    assert created["retention_cents"] == 499999
    assert created["premium_cents"] is None

    applications = list_all(api.list_eo_applications, CLEARANCE_SUPERVISOR,
                            {"production_id": production["id"]})
    assert len(applications) == 1


# ─── The renewal arithmetic inside an open renewal window ────────────────────


def test_renewal_of_zero_additional_months_is_refused_inside_the_window(api):
    """A temporally legal renewal that extends nothing is refused, not silently ignored.

    PRD §3.8: "the renewal window must be open, meaning the whole-day distance from
    the clock's date to `term_end_date` is between 0 and 60 inclusive, and a licence
    more than 60 whole days from its end date is refused with
    `ERR_OUTSIDE_RENEWAL_WINDOW` (HTTP 409); and `additional_term_months` must be at
    least 1, with zero, a negative value or an absent field refused as
    `ERR_INVALID_RENEWAL_TERM` (HTTP 422)."

    Design: Corner/validations/renewal_inside_the_window_with_zero_additional_months_rejected
    """
    production, _archive, asset, licence = _setup_renewable_active_licence(api)

    # The licence is renewable and the clock sits 45 whole days before 2027-08-15,
    # so the status check and the renewal-window check are both satisfied.
    assert licence["status"] == "ACTIVE"
    assert licence["term_end_date"] == "2027-08-15"

    response = api.renew_license(licence["id"], renew_license_payload(0),
                                 CLEARANCE_SUPERVISOR)
    validate_error(response, "ERR_INVALID_RENEWAL_TERM", 422)

    unchanged = get_license(api, licence["id"])
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["term_end_date"] == "2027-08-15"
    assert unchanged["term_months"] == 12
    assert unchanged["executed_fee_cents"] == ALL_MEDIA_FEE_CENTS
    assert unchanged["version"] == licence["version"]

    # A refused renewal touches no ledger.
    settled = get_production(api, production["id"])
    assert settled["committed_fee_cents"] == ALL_MEDIA_FEE_CENTS
    assert_asset_dimensions(get_asset(api, asset["id"]), "CLEARED",
                            rights_basis="LICENSED", lapse_count=0)


# ─── A terminal production accepts no new clearance work ─────────────────────


def test_abandoned_production_refuses_new_assets_and_releases(api):
    """The same POSTs that were accepted in DEVELOPMENT are refused after abandonment.

    PRD §2.12 rung 11: "The parent production accepts new clearance work, meaning
    its `status` is `DEVELOPMENT` or `CLEARANCE` — otherwise
    `ERR_PRODUCTION_NOT_IN_CLEARANCE`. A `LOCKED`, `DELIVERED` or `ABANDONED`
    production accepts no new assets, licences, releases or fair-use analyses.
    Applies to asset creation, licence creation, subject-release creation and
    fair-use-analysis creation."

    Design: Corner/validations/asset_creation_under_an_abandoned_production_rejected
    """
    production, asset = _setup_abandoned_production(api)

    assert production["status"] == "ABANDONED"
    # The first asset was accepted while the production was still in DEVELOPMENT.
    assert asset["production_id"] == production["id"]

    refused_asset = api.create_asset(
        production["id"],
        create_asset_payload(title="Too late", timecode_in_seconds=0,
                             timecode_out_seconds=30),
        ARCHIVE_RESEARCHER)
    validate_error(refused_asset, "ERR_PRODUCTION_NOT_IN_CLEARANCE", 409)

    refused_release = api.create_subject_release(
        production["id"],
        create_subject_release_payload("doyle-frank", release_type="SUBJECT_RELEASE",
                                       depiction_from_date="2026-03-01",
                                       depiction_to_date="2026-03-31"),
        PRODUCTION_ADMIN)
    validate_error(refused_release, "ERR_PRODUCTION_NOT_IN_CLEARANCE", 409)

    settled = get_production(api, production["id"])
    assert settled["status"] == "ABANDONED"
    assert settled["asset_count"] == 1

    assets = list_all(api.list_assets, CLEARANCE_SUPERVISOR,
                      {"production_id": production["id"]})
    assert len(assets) == 1
    assert assets[0]["id"] == asset["id"]

    releases = list_all(api.list_subject_releases, PRODUCTION_ADMIN,
                        {"production_id": production["id"]})
    assert releases == []
