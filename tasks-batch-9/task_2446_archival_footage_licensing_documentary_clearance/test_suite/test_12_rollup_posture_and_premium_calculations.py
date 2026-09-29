"""Computed state: the clearance rollup's input set, the posture ratio test, the
E&O depiction surcharge, the minimum-premium floor and the sweep's epoch counter.

Every scenario below builds its state through the documented endpoints and then
re-reads each entity the calculation is supposed to have moved.
"""
from test_helpers import (
    CLEARANCE_SUPERVISOR,
    assert_asset_dimensions,
    assert_clearance_chart,
    assert_eo_application,
    assert_license_money_ledger,
    assert_posture,
    assert_production_counters,
    create_and_execute_license,
    create_archive_with_rate_card,
    create_asset_with_selected_source,
    create_license,
    create_music_asset,
    create_production_in_clearance,
    create_subject_release,
    drive_subject_release,
    execute_license,
    get_asset,
    get_license,
    get_production,
    open_eo_application,
    pin_chart,
    quote_license,
    run_sweep,
    set_clock,
    submit_eo_application,
)

# The standard card of the PRD §3.3 worked example.
STANDARD_CARD = {
    "base_rate_per_30s_cents": 60000,
    "minimum_fee_cents": 150000,
    "festival_minimum_fee_cents": 40000,
    "effective_from_date": "2026-01-01",
}

# A 45-second BROADCAST / WORLD / 12-month ALL_MEDIA_WINDOW deal on that card:
# 60000 * 2 units * 1.25 tier * 1.15 broadcast * 1.50 world * 1.00 term * 1.00
# window = 258750, which clears the all-media floor of 150000.
TWELVE_MONTH_TERM = {
    "term_months": 12,
    "term_start_date": "2026-08-15",
    "term_end_date": "2027-08-15",
}
TWELVE_MONTH_FEE_CENTS = 258750


def _setup_two_leg_music_scenario(api):
    """One 60-second MUSIC asset and the two holders of its MASTER and PUBLISHING legs.

    Both cards price a thirty-second unit at 10000 cents, so a 60-second cue bills
    two units in duration tier 2: 10000 * 2 * 1.25 * 1.15 broadcast * 1.00
    domestic * 1.00 term * 1.00 window = 28750 cents on each leg.
    """
    card = {
        "base_rate_per_30s_cents": 10000,
        "minimum_fee_cents": 20000,
        "festival_minimum_fee_cents": 10000,
        "effective_from_date": "2026-01-01",
    }
    production = create_production_in_clearance(
        api, title="Two Legs", delivery_deadline_date="2027-06-30")
    label, _label_card = create_archive_with_rate_card(
        api, archive_overrides={"name": "Harmony Masters", "holder_type": "RECORD_LABEL"},
        card_overrides=card)
    publisher, _publisher_card = create_archive_with_rate_card(
        api, archive_overrides={"name": "Ash Grove Music", "holder_type": "MUSIC_PUBLISHER"},
        card_overrides=card)
    # A MUSIC asset needs no selected source: the source rule is scoped to FOOTAGE legs.
    asset = create_music_asset(
        api, production["id"], title="Main title cue",
        timecode_in_seconds=0, timecode_out_seconds=60,
        usage_purpose="ILLUSTRATIVE_BACKGROUND")
    return production, label, publisher, asset


def _open_music_leg(api, production, asset, archive, rights_leg):
    return create_license(
        api, production["id"], asset["id"], archive["id"], rights_leg=rights_leg,
        media="BROADCAST", territory="DOMESTIC", window_class="ALL_MEDIA_WINDOW",
        **TWELVE_MONTH_TERM)


def _setup_four_footage_asset_production(api):
    """A production carrying four byte-identical 45-second footage assets.

    Each asset is traced to the one ACTIVE archive and has that AVAILABLE candidate
    SELECTED, so each can carry a FOOTAGE licence.
    """
    production = create_production_in_clearance(
        api, title="Quarter Cleared", delivery_deadline_date="2027-06-30")
    archive, _card = create_archive_with_rate_card(
        api, archive_overrides={"name": "Pathe Vault", "holder_type": "FILM_ARCHIVE"},
        card_overrides=STANDARD_CARD)
    assets = []
    for title in ("Shot one", "Shot two", "Shot three", "Shot four"):
        asset, _candidate = create_asset_with_selected_source(
            api, production["id"], archive["id"], title=title,
            timecode_in_seconds=0, timecode_out_seconds=45)
        assets.append(asset)
    return production, archive, assets


def _clear_footage_asset(api, production, archive, asset):
    """Take one footage asset to CLEARED through DRAFT → QUOTED → EXECUTED."""
    return create_and_execute_license(
        api, production["id"], asset["id"], archive["id"],
        rights_leg="FOOTAGE", media="BROADCAST", territory="WORLD",
        window_class="ALL_MEDIA_WINDOW", **TWELVE_MONTH_TERM)


def _open_all_four_negotiations(api, production, archive, assets):
    """Open a DRAFT licence on every asset, so all four are open and IN_NEGOTIATION."""
    return [
        create_license(api, production["id"], asset["id"], archive["id"],
                       rights_leg="FOOTAGE", media="BROADCAST", territory="WORLD",
                       window_class="ALL_MEDIA_WINDOW", **TWELVE_MONTH_TERM)
        for asset in assets
    ]


def _execute_open_licence(api, archive, license_row):
    """Take one already-drafted licence QUOTED → EXECUTED, clearing its asset."""
    quote_license(api, license_row["id"], archive["id"])
    return execute_license(api, license_row["id"])


def _setup_depiction_surcharge_scenario(api, approval_rights):
    """One CLEARED footage asset whose depiction is settled by a signed release.

    The release is taken all the way to a settled depiction: with a negotiated
    approval the signature leaves the asset PENDING and the granted approval is
    what reaches OBTAINED, while a release granting no approval settles the
    question on signature alone.
    """
    production = create_production_in_clearance(
        api, title="Surcharged", delivery_deadline_date="2027-06-30")
    archive, _card = create_archive_with_rate_card(
        api, archive_overrides={"name": "Pathe Vault", "holder_type": "FILM_ARCHIVE"},
        card_overrides=STANDARD_CARD)
    asset, _candidate = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Interview cutaway",
        timecode_in_seconds=0, timecode_out_seconds=45,
        depiction_subject_key="walsh-eileen")
    license_row = create_and_execute_license(
        api, production["id"], asset["id"], archive["id"],
        rights_leg="FOOTAGE", media="BROADCAST", territory="WORLD",
        window_class="ALL_MEDIA_WINDOW", **TWELVE_MONTH_TERM)

    release = create_subject_release(
        api, production["id"], "walsh-eileen", release_type="DEPICTION_AGREEMENT",
        asset_id=asset["id"], approval_rights=approval_rights,
        depiction_from_date="2026-03-01", depiction_to_date="2026-03-31")
    drive_subject_release(api, release["id"], "SENT")
    release = drive_subject_release(api, release["id"], "SIGNED")
    if approval_rights != "NONE":
        release = drive_subject_release(api, release["id"], "APPROVAL_GRANTED",
                                       cut_reference="rough-cut-3")

    # The chart is pinned only once the depiction is settled, because every release
    # event advanced the asset's version.
    chart = pin_chart(api, production["id"], chart_label="v1")
    application = open_eo_application(api, production["id"], chart["id"],
                                      coverage_limit_cents=4000000,
                                      retention_cents=100000)
    return {
        "production": production,
        "asset": asset,
        "license": license_row,
        "release": release,
        "chart": chart,
        "application": application,
    }


def _setup_swept_production(api):
    """A production whose single licence was executed before the clock reached its term.

    The clock sits at 2026-08-20, five days into a term running 2026-08-15 to
    2027-08-15, so the first sweep has exactly one activation to perform and
    nothing to expire or flag.
    """
    set_clock(api, "2026-08-20T00:00:00Z")
    production = create_production_in_clearance(
        api, title="Twice Swept", delivery_deadline_date="2027-06-30")
    archive, _card = create_archive_with_rate_card(
        api, archive_overrides={"name": "Pathe Vault", "holder_type": "FILM_ARCHIVE"},
        card_overrides=STANDARD_CARD)
    asset, _candidate = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Quarry blast",
        timecode_in_seconds=0, timecode_out_seconds=45)
    license_row = _clear_footage_asset(api, production, archive, asset)
    return production, asset, license_row


# ─── The clearance rollup's covered-leg input set ────────────────────────────


def test_covered_legs_are_drawn_only_from_executed_active_or_expiring_licences(api):
    """A DRAFT leg never enters the covered set; only execution completes the pair.

    PRD §3.1: "The *covered* legs are the distinct `rights_leg` values of the
    asset's licences whose `status` is `EXECUTED`, `ACTIVE` or `EXPIRING`; licences
    in `EXPIRED`, `TERMINATED` or `LAPSED` contribute nothing to coverage." The
    boundary this walks is also pinned: "a music asset holding only its `MASTER`
    leg has a non-empty but incomplete covered set and is therefore
    `PARTIALLY_CLEARED`, never `CLEARED`."

    Design: Corner/calculations/rollup_counts_only_legs_in_the_pinned_license_status_set
    """
    production, label, publisher, asset = _setup_two_leg_music_scenario(api)

    # A DRAFT MASTER licence: no covered leg yet, so the asset is merely negotiating.
    master = _open_music_leg(api, production, asset, label, "MASTER")
    assert master["status"] == "DRAFT"
    assert master["rate_card_fee_cents"] == 28750
    assert_asset_dimensions(get_asset(api, asset["id"]), "IN_NEGOTIATION",
                            rights_basis="UNDETERMINED", lapse_count=0)

    # Executing it covers MASTER only — a non-empty but incomplete required set.
    quote_license(api, master["id"], label["id"], 28750)
    execute_license(api, master["id"])
    assert_asset_dimensions(get_asset(api, asset["id"]), "PARTIALLY_CLEARED",
                            rights_basis="UNDETERMINED", lapse_count=0)
    settled = get_production(api, production["id"])
    assert_production_counters(settled, asset_count=1, cleared_asset_count=0,
                               open_asset_count=1)
    assert_posture(settled, "BLOCKED")

    # A DRAFT PUBLISHING leg still contributes nothing to coverage.
    publishing = _open_music_leg(api, production, asset, publisher, "PUBLISHING")
    assert publishing["status"] == "DRAFT"
    assert publishing["rate_card_fee_cents"] == 28750
    assert_asset_dimensions(get_asset(api, asset["id"]), "PARTIALLY_CLEARED",
                            rights_basis="UNDETERMINED")

    # Executing the second leg makes the covered set a superset of the required pair.
    quote_license(api, publishing["id"], publisher["id"], 28750)
    execute_license(api, publishing["id"])
    assert_asset_dimensions(get_asset(api, asset["id"]), "CLEARED",
                            rights_basis="LICENSED", lapse_count=0)

    settled = get_production(api, production["id"])
    assert_production_counters(settled, asset_count=1, cleared_asset_count=1,
                               open_asset_count=0)
    assert_posture(settled, "OPEN")
    assert settled["committed_fee_cents"] == 57500
    assert_license_money_ledger(api, production["id"], CLEARANCE_SUPERVISOR)

    # Neither holder demands most-favored-nations parity, so no top-up ran.
    for license_id in (master["id"], publishing["id"]):
        persisted = get_license(api, license_id)
        assert persisted["status"] == "EXECUTED"
        assert persisted["executed_fee_cents"] == 28750
        assert persisted["mfn_requested"] is False
        assert persisted["mfn_topup_cents"] == 0
        assert persisted["mfn_benchmark_fee_cents"] == 0


# ─── The posture ratio test walked from both sides ───────────────────────────


def test_posture_is_blocked_while_more_than_a_quarter_of_the_assets_are_open(api):
    """Four open of four and two open of four both fail the integer ratio test.

    PRD §2.8: "Otherwise, if the number of open assets multiplied by four is less
    than or equal to the total asset count, posture is `RESTRICTED`. In other
    words, a production stays merely restricted while at least three quarters of
    its assets are non-open: one open asset out of four gives four, which is less
    than or equal to four, so the posture is `RESTRICTED`, whereas two open assets
    out of four gives eight, which is not less than or equal to four, so the
    posture is `BLOCKED`."

    Design: Corner/calculations/posture_walks_blocked_to_restricted_to_open_across_the_seventy_five_percent_test
    """
    production, archive, assets = _setup_four_footage_asset_production(api)

    # All four assets open: 4 * 4 = 16, which is not less than or equal to 4.
    settled = get_production(api, production["id"])
    assert_production_counters(settled, asset_count=4, cleared_asset_count=0,
                               open_asset_count=4)
    assert_posture(settled, "BLOCKED")

    licences = _open_all_four_negotiations(api, production, archive, assets)
    settled = get_production(api, production["id"])
    assert_production_counters(settled, asset_count=4, cleared_asset_count=0,
                               open_asset_count=4)
    assert_posture(settled, "BLOCKED")

    # Three open of four: 3 * 4 = 12 > 4.
    _execute_open_licence(api, archive, licences[0])
    settled = get_production(api, production["id"])
    assert_production_counters(settled, asset_count=4, cleared_asset_count=1,
                               open_asset_count=3)
    assert_posture(settled, "BLOCKED")

    # Two open of four: 2 * 4 = 8 > 4, the case the PRD names explicitly.
    _execute_open_licence(api, archive, licences[1])
    settled = get_production(api, production["id"])
    assert_production_counters(settled, asset_count=4, cleared_asset_count=2,
                               open_asset_count=2)
    assert_posture(settled, "BLOCKED")


def test_posture_is_restricted_at_the_inclusive_one_open_of_four_edge(api):
    """One open asset out of four gives four, which is less than or equal to four.

    PRD §2.8: "Otherwise, if the number of open assets multiplied by four is less
    than or equal to the total asset count, posture is `RESTRICTED`. In other
    words, a production stays merely restricted while at least three quarters of
    its assets are non-open: one open asset out of four gives four, which is less
    than or equal to four, so the posture is `RESTRICTED`, whereas two open assets
    out of four gives eight, which is not less than or equal to four, so the
    posture is `BLOCKED`."

    Design: Corner/calculations/posture_walks_blocked_to_restricted_to_open_across_the_seventy_five_percent_test
    """
    production, archive, assets = _setup_four_footage_asset_production(api)

    for asset in assets[:3]:
        _clear_footage_asset(api, production, archive, asset)

    settled = get_production(api, production["id"])
    assert_production_counters(settled, asset_count=4, cleared_asset_count=3,
                               open_asset_count=1)
    assert_posture(settled, "RESTRICTED")
    assert_asset_dimensions(get_asset(api, assets[3]["id"]), "UNCLEARED",
                            rights_basis="UNDETERMINED")
    assert settled["committed_fee_cents"] == 3 * TWELVE_MONTH_FEE_CENTS
    assert_license_money_ledger(api, production["id"], CLEARANCE_SUPERVISOR)


def test_posture_reaches_open_when_no_asset_is_open_and_none_is_pending(api):
    """Zero open assets with no pending depiction settles the posture at OPEN.

    PRD §2.8: "Otherwise, if the number of open assets is zero and the number of
    assets with `depiction_status` of `PENDING` is also zero, posture is `OPEN`."

    Design: Corner/calculations/posture_walks_blocked_to_restricted_to_open_across_the_seventy_five_percent_test
    """
    production, archive, assets = _setup_four_footage_asset_production(api)

    for asset in assets:
        _clear_footage_asset(api, production, archive, asset)

    settled = get_production(api, production["id"])
    assert_production_counters(settled, asset_count=4, cleared_asset_count=4,
                               open_asset_count=0)
    assert_posture(settled, "OPEN")
    for asset in assets:
        # No asset declared a depiction subject, so dimension B is NOT_REQUIRED.
        assert_asset_dimensions(get_asset(api, asset["id"]), "CLEARED",
                                depiction_status="NOT_REQUIRED",
                                rights_basis="LICENSED")
    assert settled["committed_fee_cents"] == 4 * TWELVE_MONTH_FEE_CENTS
    assert settled["committed_fee_cents"] == 1035000
    assert_license_money_ledger(api, production["id"], CLEARANCE_SUPERVISOR)


# ─── The E&O depiction surcharge ─────────────────────────────────────────────


def test_signed_release_with_approval_rights_adds_the_depiction_surcharge(api):
    """A LICENSED row carrying a negotiated approval rates at 0.018, not 0.010.

    PRD §3.7: "A depiction surcharge of a further 0.008 is added to that row's
    weight when the row's `depiction_status` is `OBTAINED` *and* there exists a
    subject release naming that row's asset whose `status` is `SIGNED` or
    `APPROVAL_GRANTED` and whose `approval_rights` is something other than `NONE`;
    a negotiated approval is an ongoing exposure, so it is rated."

    Design: Corner/calculations/eo_premium_applies_the_depiction_surcharge_to_a_signed_release_row
    """
    scenario = _setup_depiction_surcharge_scenario(api, "ROUGH_CUT_APPROVAL")
    production = scenario["production"]

    assert scenario["release"]["status"] == "APPROVAL_GRANTED"
    assert scenario["release"]["approval_rights"] == "ROUGH_CUT_APPROVAL"
    assert_asset_dimensions(get_asset(api, scenario["asset"]["id"]), "CLEARED",
                            depiction_status="OBTAINED", rights_basis="LICENSED")
    assert_posture(get_production(api, production["id"]), "OPEN")

    chart = scenario["chart"]
    assert_clearance_chart(chart)
    assert chart["pinned_row_count"] == 1
    row = chart["pinned_rows"][0]
    assert row["asset_id"] == scenario["asset"]["id"]
    assert row["licensing_status"] == "CLEARED"
    assert row["rights_basis"] == "LICENSED"
    assert row["depiction_status"] == "OBTAINED"

    submitted = submit_eo_application(api, scenario["application"]["id"])

    assert_eo_application(submitted)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["legal_review_status"] == "PENDING"
    assert submitted["underwriting_review_status"] == "PENDING"
    # base round_half_up(4000000 * 0.0125) = 50000; the single row's weight is
    # 0.010 LICENSED + 0.008 depiction, so its loading is
    # round_half_up(4000000 * 0.018) = 72000; the retention credit is
    # round_half_up(100000 * 0.30) = 30000.
    assert submitted["premium_cents"] == 92000
    # 60000 is what the same row rates without the depiction surcharge.
    assert submitted["premium_cents"] != 60000


def test_signed_release_granting_no_approval_leaves_the_row_unsurcharged(api):
    """The same OBTAINED depiction rates at a bare 0.010 when no approval was granted.

    PRD §3.7: "A depiction surcharge of a further 0.008 is added to that row's
    weight when the row's `depiction_status` is `OBTAINED` *and* there exists a
    subject release naming that row's asset whose `status` is `SIGNED` or
    `APPROVAL_GRANTED` and whose `approval_rights` is something other than `NONE`;
    a negotiated approval is an ongoing exposure, so it is rated."

    Design: Corner/calculations/eo_premium_applies_the_depiction_surcharge_to_a_signed_release_row
    """
    scenario = _setup_depiction_surcharge_scenario(api, "NONE")

    # PRD §3.6: where approval_rights is NONE, signing moves dimension B
    # PENDING → OBTAINED on its own.
    assert scenario["release"]["status"] == "SIGNED"
    assert scenario["release"]["approval_rights"] == "NONE"
    assert_asset_dimensions(get_asset(api, scenario["asset"]["id"]), "CLEARED",
                            depiction_status="OBTAINED", rights_basis="LICENSED")

    submitted = submit_eo_application(api, scenario["application"]["id"])

    assert_eo_application(submitted)
    assert submitted["status"] == "SUBMITTED"
    # base 50000 + round_half_up(4000000 * 0.010) = 40000 - credit 30000.
    assert submitted["premium_cents"] == 60000
    assert submitted["premium_cents"] != 92000


# ─── The minimum premium floor ───────────────────────────────────────────────


def test_negative_rated_premium_is_floored_at_the_minimum_premium(api):
    """The smallest legal coverage with the largest legal retention rates at 25000.

    PRD §3.7: "Finally, `premium_cents` is the base premium plus the loading total
    minus the retention credit, floored at a minimum premium of 25000 cents: where
    the arithmetic yields less than 25000, the stored premium is 25000."

    Design: Corner/calculations/eo_premium_falls_back_to_the_minimum_premium_constant
    """
    production = create_production_in_clearance(
        api, title="Floor Premium", delivery_deadline_date="2027-06-30")
    # A production with no assets at all has posture OPEN, so the chart may be pinned.
    chart = pin_chart(api, production["id"], chart_label="empty v1")
    assert chart["pinned_row_count"] == 0
    assert chart["pinned_rows"] == []

    application = open_eo_application(api, production["id"], chart["id"],
                                      coverage_limit_cents=100000,
                                      retention_cents=99999)
    assert application["status"] == "DRAFT"
    assert application["coverage_limit_cents"] == 100000
    assert application["retention_cents"] == 99999

    submitted = submit_eo_application(api, application["id"])

    assert_eo_application(submitted)
    assert submitted["status"] == "SUBMITTED"
    # base round_half_up(100000 * 0.0125) = 1250, no rateable rows, credit
    # round_half_up(99999 * 0.30) = 30000, so the arithmetic yields -28750.
    assert submitted["premium_cents"] == 25000
    assert submitted["premium_cents"] > 0
    assert submitted["premium_cents"] != 1250


# ─── Sweep idempotence at a fixed clock instant ──────────────────────────────


def test_second_sweep_changes_nothing_but_still_advances_the_epoch(api):
    """Replaying the sweep at the same instant reports empty lists and epoch two.

    PRD §3.8: "Apart from `sweep_epoch`, which advances on every call, a sweep is
    idempotent at a fixed clock instant: running it twice without moving the clock
    produces no further state change and empty id lists on the second run."

    Design: Corner/calculations/second_sweep_is_a_no_op_that_still_advances_the_epoch
    """
    production, asset, license_row = _setup_swept_production(api)

    first = run_sweep(api, production["id"])

    assert first["sweep_epoch"] == 1
    assert first["activated_license_ids"] == [license_row["id"]]
    assert first["expired_license_ids"] == []
    assert first["expiring_license_ids"] == []
    assert first["lapsed_asset_ids"] == []
    assert first["suspended_delivery_package_ids"] == []
    assert first["remediated_eo_application_ids"] == []
    assert first["production_posture"] == "OPEN"
    assert first["committed_fee_cents"] == TWELVE_MONTH_FEE_CENTS

    activated = get_license(api, license_row["id"])
    assert activated["status"] == "ACTIVE"
    version_after_first_sweep = activated["version"]

    second = run_sweep(api, production["id"])

    assert second["sweep_epoch"] == 2
    assert second["activated_license_ids"] == []
    assert second["expired_license_ids"] == []
    assert second["expiring_license_ids"] == []
    assert second["lapsed_asset_ids"] == []
    assert second["suspended_delivery_package_ids"] == []
    assert second["remediated_eo_application_ids"] == []
    assert second["production_posture"] == "OPEN"

    replayed = get_license(api, license_row["id"])
    assert replayed["status"] == "ACTIVE"
    assert replayed["version"] == version_after_first_sweep
    assert replayed["executed_fee_cents"] == TWELVE_MONTH_FEE_CENTS

    # Activation moves a licence within the summed set of PRD §2.9, so no money moved.
    settled = get_production(api, production["id"])
    assert settled["sweep_epoch"] == 2
    assert settled["committed_fee_cents"] == TWELVE_MONTH_FEE_CENTS
    assert_posture(settled, "OPEN")
    assert_production_counters(settled, asset_count=1, cleared_asset_count=1,
                              open_asset_count=0)
    assert_asset_dimensions(get_asset(api, asset["id"]), "CLEARED",
                            rights_basis="LICENSED", lapse_count=0)
    assert_license_money_ledger(api, production["id"], CLEARANCE_SUPERVISOR)
