"""Endpoint behaviour and the error contract.

Two families of claims live here. The first is behavioural: the source-selection
action, the clearance-chart snapshot read, the delivery-package link and the
rights sweep must each land every side effect and every derived count the PRD
declares for them. The second is the refusal contract: each not-found identifier
must be reachable from its own resource, the authentication ladder must answer in
its three distinct ways, the E&O review gates must be distinguishable from one
another, and the two posture errors must never be interchanged.
"""
from test_helpers import (
    ARCHIVE_RESEARCHER,
    CLEARANCE_SUPERVISOR,
    LEGAL_COUNSEL,
    NON_EXISTENT_UUID,
    PRODUCTION_ADMIN,
    REVIEWING_COUNSEL,
    add_source_candidate,
    assert_asset_dimensions,
    assert_clearance_chart,
    assert_delivery_package,
    assert_posture,
    build_user_headers,
    clear_asset_via_fair_use,
    create_and_execute_license,
    create_archive,
    create_archive_with_rate_card,
    create_asset,
    create_asset_with_selected_source,
    create_delivery_package_payload,
    create_eo_review_payload,
    create_music_asset,
    create_production,
    create_production_in_clearance,
    create_subject_release,
    get_asset,
    get_chart,
    get_delivery_package,
    get_license,
    get_production,
    make_rights_holder_rep_headers,
    open_delivery_package,
    open_eo_application,
    pin_chart,
    pin_clearance_chart_payload,
    run_sweep,
    select_source_payload,
    set_clock,
    state_payload,
    submit_eo_application,
    validate_error,
    validate_paginated,
    validate_success,
)

# Headers carrying no identity at all, for the priority-1 authentication probe.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}

# A twelve-month term on the standard card: a 45-second or 60-second asset bills two
# thirty-second units in tier 2, so 60000 * 2 * 1.25 * 1.15 * 1.50 * 1.00 * 1.00.
TWELVE_MONTH_TERM = {
    "term_months": 12,
    "term_start_date": "2026-08-15",
    "term_end_date": "2027-08-15",
}
TWELVE_MONTH_FEE_CENTS = 258750


# ─── Setup helpers ───────────────────────────────────────────────────────────


def _setup_three_candidate_asset(api):
    """One 45-second footage asset traced to two archives with three candidates.

    Two candidates are `AVAILABLE` (one at each archive) and the third, at the first
    archive, is `ELEMENT_MISSING`, so the selection ranking has a genuine loser.
    """
    production = create_production_in_clearance(api, title="Source Swap")
    archive_a = create_archive(api, name="Pathe Vault", holder_type="FILM_ARCHIVE")
    archive_b = create_archive(api, name="Getty Reels", holder_type="NEWS_ARCHIVE")
    asset = create_asset(api, production["id"], title="Bridge collapse",
                         timecode_in_seconds=0, timecode_out_seconds=45)
    first = add_source_candidate(api, asset["id"], archive_a["id"],
                                availability_status="AVAILABLE",
                                quoted_rate_per_30s_cents=55000, provenance_confidence=80)
    second = add_source_candidate(api, asset["id"], archive_b["id"],
                                  availability_status="AVAILABLE",
                                  quoted_rate_per_30s_cents=48000, provenance_confidence=65)
    missing = add_source_candidate(api, asset["id"], archive_a["id"],
                                  availability_status="ELEMENT_MISSING",
                                  quoted_rate_per_30s_cents=30000, provenance_confidence=20)
    return {
        "production": production,
        "archive_a": archive_a,
        "archive_b": archive_b,
        "asset": asset,
        "first": first,
        "second": second,
        "missing": missing,
    }


def _setup_unavailable_only_asset(api):
    """One footage asset whose only traced elements are missing or of unclear title."""
    production = create_production_in_clearance(api, title="No Element")
    archive = create_archive(api, name="Pathe Vault", holder_type="FILM_ARCHIVE")
    asset = create_asset(api, production["id"], title="Lost reel",
                         timecode_in_seconds=0, timecode_out_seconds=45)
    missing = add_source_candidate(api, asset["id"], archive["id"],
                                  availability_status="ELEMENT_MISSING")
    unclear = add_source_candidate(api, asset["id"], archive["id"],
                                  availability_status="RIGHTS_UNCLEAR")
    return {"production": production, "archive": archive, "asset": asset,
            "missing": missing, "unclear": unclear}


def _candidate_rows(api, asset_id, params=None):
    merged = {"limit": 100}
    merged.update(params or {})
    rows, meta = validate_paginated(
        api.list_asset_source_candidates(asset_id, ARCHIVE_RESEARCHER, params=merged))
    return rows, meta


def _selection_status(api, asset_id, candidate_id):
    rows, _meta = _candidate_rows(api, asset_id)
    matches = [row for row in rows if row["id"] == candidate_id]
    assert matches, f"candidate {candidate_id} missing from the asset's collection"
    return matches[0]["selection_status"]


def _setup_mixed_basis_chart(api):
    """A four-asset production pinned into one chart with three different bases.

    The assets are created in a fixed order so the pin's `created_at` ordering is
    observable: a MUSIC cue holding only its MASTER leg, a licensed shot, a shot
    cleared on an accepted fair-use analysis, and a second licensed shot.
    """
    production = create_production_in_clearance(api, title="Mixed Basis")
    archive, card = create_archive_with_rate_card(api)

    music = create_music_asset(api, production["id"], title="End credits cue",
                               timecode_in_seconds=0, timecode_out_seconds=60,
                               usage_purpose="ILLUSTRATIVE_BACKGROUND")
    master = create_and_execute_license(api, production["id"], music["id"], archive["id"],
                                       rights_leg="MASTER", **TWELVE_MONTH_TERM)

    licensed_one, _c2 = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Rooftop pan")
    license_one = create_and_execute_license(
        api, production["id"], licensed_one["id"], archive["id"], **TWELVE_MONTH_TERM)

    fair_use_asset = create_asset(api, production["id"], title="Protest march")
    analysis, letter = clear_asset_via_fair_use(api, fair_use_asset["id"])

    licensed_two, _c4 = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Harbour dusk")
    license_two = create_and_execute_license(
        api, production["id"], licensed_two["id"], archive["id"], **TWELVE_MONTH_TERM)

    order = [music, licensed_one, fair_use_asset, licensed_two]
    versions_at_pin = {asset["id"]: get_asset(api, asset["id"])["version"] for asset in order}
    chart = pin_chart(api, production["id"], "mixed v1")
    return {
        "production": production,
        "archive": archive,
        "rate_card": card,
        "order": [asset["id"] for asset in order],
        "music": music,
        "licensed_one": licensed_one,
        "fair_use_asset": fair_use_asset,
        "licensed_two": licensed_two,
        "master_license": master,
        "license_one": license_one,
        "license_two": license_two,
        "analysis": analysis,
        "letter": letter,
        "versions_at_pin": versions_at_pin,
        "chart": chart,
    }


def _setup_delivery_ready_charts(api):
    """A production whose MUSIC cue holds both legs, plus a second production's chart."""
    first = create_production_in_clearance(api, title="Cue Sheet Ready")
    archive, _card = create_archive_with_rate_card(
        api, archive_overrides={"name": "Harmony Masters", "holder_type": "RECORD_LABEL"})

    music = create_music_asset(api, first["id"], title="Title theme",
                               timecode_in_seconds=0, timecode_out_seconds=60,
                               usage_purpose="ILLUSTRATIVE_BACKGROUND")
    create_and_execute_license(api, first["id"], music["id"], archive["id"],
                               rights_leg="MASTER", **TWELVE_MONTH_TERM)
    create_and_execute_license(api, first["id"], music["id"], archive["id"],
                               rights_leg="PUBLISHING", **TWELVE_MONTH_TERM)

    footage, _candidate = create_asset_with_selected_source(
        api, first["id"], archive["id"], title="Studio session")
    create_and_execute_license(api, first["id"], footage["id"], archive["id"],
                               **TWELVE_MONTH_TERM)

    first_chart = pin_chart(api, first["id"], "delivery v1")

    second = create_production_in_clearance(api, title="Other Film",
                                            delivery_deadline_date="2027-09-30")
    second_chart = pin_chart(api, second["id"], "other v1")
    return {
        "first": first,
        "second": second,
        "archive": archive,
        "music": music,
        "footage": footage,
        "first_chart": first_chart,
        "second_chart": second_chart,
    }


def _setup_three_licence_sweep(api):
    """Three ACTIVE footage licences whose terms end four months, one year and two
    years out, with the clock then moved to 2027-07-01 so one sweep separates them."""
    set_clock(api, "2026-08-20T00:00:00Z")
    production = create_production_in_clearance(api, title="Three Fates")
    archive, _card = create_archive_with_rate_card(api)

    short_asset, _c1 = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Short term shot")
    short_license = create_and_execute_license(
        api, production["id"], short_asset["id"], archive["id"],
        term_months=4, term_start_date="2026-08-15", term_end_date="2026-12-15")

    mid_asset, _c2 = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Mid term shot")
    mid_license = create_and_execute_license(
        api, production["id"], mid_asset["id"], archive["id"], **TWELVE_MONTH_TERM)

    long_asset, _c3 = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Long term shot")
    long_license = create_and_execute_license(
        api, production["id"], long_asset["id"], archive["id"],
        term_months=24, term_start_date="2026-08-15", term_end_date="2028-08-15")

    activation_report = run_sweep(api, production["id"])
    set_clock(api, "2027-07-01T00:00:00Z")
    return {
        "production": production,
        "archive": archive,
        "short_asset": short_asset,
        "mid_asset": mid_asset,
        "long_asset": long_asset,
        "short_license": short_license,
        "mid_license": mid_license,
        "long_license": long_license,
        "activation_report": activation_report,
    }


def _seed_production(api):
    """One real production, so a 404 probe cannot be answered by an empty store."""
    return create_production(api, title="Reachability")


def _setup_submitted_eo_application(api):
    """A SUBMITTED application on an asset-free production, so posture is OPEN and the
    chart carries no pinned rows and therefore no pinned opinion letters."""
    production = create_production_in_clearance(api, title="Review Ladder")
    chart = pin_chart(api, production["id"], "v1")
    application = open_eo_application(api, production["id"], chart["id"],
                                      coverage_limit_cents=1000000, retention_cents=100000)
    application = submit_eo_application(api, application["id"])
    return production, chart, application


def _read_eo_application(api, application_id):
    return validate_success(api.get_eo_application(application_id, CLEARANCE_SUPERVISOR))


def _setup_depicted_asset_production(api):
    """A production whose single 45-second shot names an identifiable person.

    The shot is UNCLEARED and its depiction is PENDING, so one open asset out of one
    puts the production's posture at BLOCKED.
    """
    production = create_production_in_clearance(api, title="Two Postures")
    archive, _card = create_archive_with_rate_card(api)
    asset, _candidate = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Doorway interview",
        depiction_subject_key="reyes-marta")
    return production, archive, asset


def _send_release_for(api, production_id, asset_id):
    """Paper a negotiated-approval release for the depicted person and send it out."""
    release = create_subject_release(
        api, production_id, "reyes-marta", asset_id=asset_id,
        release_type="SUBJECT_RELEASE", approval_rights="ROUGH_CUT_APPROVAL",
        depiction_from_date="2026-03-01", depiction_to_date="2026-03-31")
    return validate_success(
        api.set_subject_release_state(release["id"], state_payload("SENT"), PRODUCTION_ADMIN))


# ─── Source selection: promotion and demotion ────────────────────────────────


def test_select_source_promotes_the_chosen_candidate_and_leaves_the_others_alone(api):
    """The first selection sets one candidate SELECTED and bumps the asset once.

    PRD §3.2: "On success the chosen candidate's `selection_status` becomes
    `SELECTED`, any candidate that was previously `SELECTED` is demoted to
    `REJECTED`, the asset's `selected_source_candidate_id` is set to the chosen
    candidate, and the asset's `version` increments."

    Design: Corner/endpoints/select_source_promotes_one_candidate_and_demotes_the_previous_winner
    """
    scenario = _setup_three_candidate_asset(api)
    asset_id = scenario["asset"]["id"]
    version_before = get_asset(api, asset_id)["version"]

    returned = validate_success(
        api.select_source(asset_id, select_source_payload(scenario["first"]["id"]),
                          ARCHIVE_RESEARCHER))
    assert returned["selected_source_candidate_id"] == scenario["first"]["id"]

    settled = get_asset(api, asset_id)
    assert settled["selected_source_candidate_id"] == scenario["first"]["id"]
    assert settled["version"] == version_before + 1

    assert _selection_status(api, asset_id, scenario["first"]["id"]) == "SELECTED"
    # PRD §3.2: a new candidate's selection_status reads NOT_SELECTED, and only the
    # previous winner is demoted — the untouched rows keep that initial value.
    assert _selection_status(api, asset_id, scenario["second"]["id"]) == "NOT_SELECTED"
    assert _selection_status(api, asset_id, scenario["missing"]["id"]) == "NOT_SELECTED"

    # Dimension A is the output of the clearance rollup, which selection does not run.
    assert_asset_dimensions(settled, "UNCLEARED", rights_basis="UNDETERMINED")


def test_re_selecting_a_source_demotes_the_previous_winner_to_rejected(api):
    """The second selection promotes the new candidate and demotes the old one.

    PRD §3.2: "On success the chosen candidate's `selection_status` becomes
    `SELECTED`, any candidate that was previously `SELECTED` is demoted to
    `REJECTED`, the asset's `selected_source_candidate_id` is set to the chosen
    candidate, and the asset's `version` increments."

    Design: Corner/endpoints/select_source_promotes_one_candidate_and_demotes_the_previous_winner
    """
    scenario = _setup_three_candidate_asset(api)
    asset_id = scenario["asset"]["id"]
    validate_success(
        api.select_source(asset_id, select_source_payload(scenario["first"]["id"]),
                          ARCHIVE_RESEARCHER))
    version_before_swap = get_asset(api, asset_id)["version"]

    returned = validate_success(
        api.select_source(asset_id, select_source_payload(scenario["second"]["id"]),
                          CLEARANCE_SUPERVISOR))
    assert returned["selected_source_candidate_id"] == scenario["second"]["id"]

    settled = get_asset(api, asset_id)
    assert settled["selected_source_candidate_id"] == scenario["second"]["id"]
    assert settled["version"] == version_before_swap + 1

    assert _selection_status(api, asset_id, scenario["second"]["id"]) == "SELECTED"
    # The demoted candidate reads REJECTED, never back to NOT_SELECTED.
    assert _selection_status(api, asset_id, scenario["first"]["id"]) == "REJECTED"
    assert _selection_status(api, asset_id, scenario["missing"]["id"]) == "NOT_SELECTED"


def test_selection_status_filter_and_the_archive_side_view_report_the_demotion(api):
    """Exactly one candidate reads REJECTED, and the holder's own view is unchanged.

    PRD §2.3: "Source-candidate collections — whether read through the owning asset
    or through the holding archive — accept `availability_status` and
    `selection_status`."

    Design: Corner/endpoints/select_source_promotes_one_candidate_and_demotes_the_previous_winner
    """
    scenario = _setup_three_candidate_asset(api)
    asset_id = scenario["asset"]["id"]
    validate_success(
        api.select_source(asset_id, select_source_payload(scenario["first"]["id"]),
                          ARCHIVE_RESEARCHER))
    validate_success(
        api.select_source(asset_id, select_source_payload(scenario["second"]["id"]),
                          CLEARANCE_SUPERVISOR))

    rejected, rejected_meta = _candidate_rows(api, asset_id,
                                              {"selection_status": "REJECTED"})
    assert rejected_meta["total_count"] == 1
    assert [row["id"] for row in rejected] == [scenario["first"]["id"]]

    selected, selected_meta = _candidate_rows(api, asset_id,
                                              {"selection_status": "SELECTED"})
    assert selected_meta["total_count"] == 1
    assert [row["id"] for row in selected] == [scenario["second"]["id"]]

    # PRD §4: the archive-side collection lists every candidate naming this archive as
    # the holding institution, which selection does not change.
    holder_rows, holder_meta = validate_paginated(
        api.list_archive_source_candidates(scenario["archive_a"]["id"], ARCHIVE_RESEARCHER,
                                           params={"limit": 100}))
    assert holder_meta["total_count"] == 2
    assert {row["id"] for row in holder_rows} == {scenario["first"]["id"],
                                                  scenario["missing"]["id"]}


# ─── Source selection: the availability gate ─────────────────────────────────


def test_select_source_refused_when_no_candidate_of_the_asset_is_available(api):
    """With two candidates present but neither AVAILABLE the selection is refused.

    PRD §3.2: "If no candidate of the asset has `availability_status` of `AVAILABLE`,
    the selection is refused outright with `ERR_NO_AVAILABLE_SOURCE` — an asset whose
    only traced elements are missing, withdrawn or of unclear provenance cannot be
    sourced."

    Design: Corner/endpoints/select_source_refused_when_every_candidate_is_unavailable
    """
    scenario = _setup_unavailable_only_asset(api)
    asset_id = scenario["asset"]["id"]
    version_before = get_asset(api, asset_id)["version"]

    validate_error(
        api.select_source(asset_id, select_source_payload(scenario["missing"]["id"]),
                          ARCHIVE_RESEARCHER),
        "ERR_NO_AVAILABLE_SOURCE")

    settled = get_asset(api, asset_id)
    assert settled["selected_source_candidate_id"] is None
    assert settled["version"] == version_before
    assert _selection_status(api, asset_id, scenario["missing"]["id"]) == "NOT_SELECTED"
    assert _selection_status(api, asset_id, scenario["unclear"]["id"]) == "NOT_SELECTED"


def test_adding_an_available_candidate_makes_the_selection_succeed(api):
    """The gate reads the candidate set, so one AVAILABLE row opens the action.

    PRD §3.2: "If no candidate of the asset has `availability_status` of `AVAILABLE`,
    the selection is refused outright with `ERR_NO_AVAILABLE_SOURCE` — an asset whose
    only traced elements are missing, withdrawn or of unclear provenance cannot be
    sourced."

    Design: Corner/endpoints/select_source_refused_when_every_candidate_is_unavailable
    """
    scenario = _setup_unavailable_only_asset(api)
    asset_id = scenario["asset"]["id"]
    validate_error(
        api.select_source(asset_id, select_source_payload(scenario["missing"]["id"]),
                          ARCHIVE_RESEARCHER),
        "ERR_NO_AVAILABLE_SOURCE")

    available = add_source_candidate(api, asset_id, scenario["archive"]["id"],
                                     availability_status="AVAILABLE")
    version_before = get_asset(api, asset_id)["version"]

    returned = validate_success(
        api.select_source(asset_id, select_source_payload(available["id"]),
                          ARCHIVE_RESEARCHER))
    assert returned["selected_source_candidate_id"] == available["id"]

    settled = get_asset(api, asset_id)
    assert settled["selected_source_candidate_id"] == available["id"]
    assert settled["version"] == version_before + 1
    assert _selection_status(api, asset_id, available["id"]) == "SELECTED"
    assert _selection_status(api, asset_id, scenario["missing"]["id"]) == "NOT_SELECTED"
    assert _selection_status(api, asset_id, scenario["unclear"]["id"]) == "NOT_SELECTED"


def test_select_source_reports_an_unknown_candidate_id_as_not_found(api):
    """A candidate id that was never minted answers with the candidate's own 404.

    PRD §3.2: "The request names a single `source_candidate_id`; a candidate id that
    does not exist, or that belongs to some other asset, is answered with
    `ERR_SOURCE_CANDIDATE_NOT_FOUND`."

    Design: Corner/endpoints/select_source_refused_when_every_candidate_is_unavailable
    """
    production = create_production_in_clearance(api, title="No Element")
    archive = create_archive(api, name="Pathe Vault", holder_type="FILM_ARCHIVE")
    asset = create_asset(api, production["id"], title="Lost reel")
    # An AVAILABLE candidate exists, so the availability gate cannot be what fires.
    available = add_source_candidate(api, asset["id"], archive["id"],
                                     availability_status="AVAILABLE")
    version_before = get_asset(api, asset["id"])["version"]

    validate_error(
        api.select_source(asset["id"], select_source_payload(NON_EXISTENT_UUID),
                          ARCHIVE_RESEARCHER),
        "ERR_SOURCE_CANDIDATE_NOT_FOUND")

    settled = get_asset(api, asset["id"])
    assert settled["selected_source_candidate_id"] is None
    assert settled["version"] == version_before
    assert _selection_status(api, asset["id"], available["id"]) == "NOT_SELECTED"


# ─── The clearance chart snapshot read ───────────────────────────────────────


def test_chart_read_returns_one_pinned_row_per_asset_in_created_at_order(api):
    """The snapshot walks the production's assets oldest first, one row each.

    PRD §3.7: "The pin walks the production's assets in ascending `created_at` order
    and writes one object into `pinned_rows` per asset, recording that asset's
    `asset_id`, the `asset_version` current at pin time, and the asset's
    `rights_basis`, `licensing_status`, `depiction_status`, its `covered_legs` and
    the `license_ids` behind them."

    Design: Corner/endpoints/chart_read_returns_the_ordered_snapshot_with_its_derived_counts
    """
    scenario = _setup_mixed_basis_chart(api)

    chart = get_chart(api, scenario["chart"]["id"], LEGAL_COUNSEL)
    assert_clearance_chart(chart)
    assert chart["status"] == "PINNED"
    assert chart["pinned_row_count"] == 4
    assert [row["asset_id"] for row in chart["pinned_rows"]] == scenario["order"]

    # PRD §2.8 rule 4: one open asset out of four gives four, which is less than or
    # equal to four, so a production that may still pin sits at RESTRICTED.
    production = get_production(api, scenario["production"]["id"])
    assert_posture(production, "RESTRICTED")
    assert production["committed_fee_cents"] == 3 * TWELVE_MONTH_FEE_CENTS


def test_each_pinned_row_freezes_the_assets_basis_legs_and_version(api):
    """Every row carries the basis, status, covered legs and pin-time asset version.

    PRD §3.7: "The pin walks the production's assets in ascending `created_at` order
    and writes one object into `pinned_rows` per asset, recording that asset's
    `asset_id`, the `asset_version` current at pin time, and the asset's
    `rights_basis`, `licensing_status`, `depiction_status`, its `covered_legs` and
    the `license_ids` behind them."

    Design: Corner/endpoints/chart_read_returns_the_ordered_snapshot_with_its_derived_counts
    """
    scenario = _setup_mixed_basis_chart(api)
    chart = get_chart(api, scenario["chart"]["id"], LEGAL_COUNSEL)
    rows = {row["asset_id"]: row for row in chart["pinned_rows"]}

    # PRD §3.1: a music asset holding only its MASTER leg has a non-empty but
    # incomplete covered set and is therefore PARTIALLY_CLEARED, never CLEARED.
    music_row = rows[scenario["music"]["id"]]
    assert music_row["licensing_status"] == "PARTIALLY_CLEARED"
    assert music_row["rights_basis"] == "UNDETERMINED"
    assert list(music_row["covered_legs"]) == ["MASTER"]
    assert list(music_row["license_ids"]) == [scenario["master_license"]["id"]]

    licensed_row = rows[scenario["licensed_one"]["id"]]
    assert licensed_row["licensing_status"] == "CLEARED"
    assert licensed_row["rights_basis"] == "LICENSED"
    assert list(licensed_row["covered_legs"]) == ["FOOTAGE"]
    assert list(licensed_row["license_ids"]) == [scenario["license_one"]["id"]]

    # PRD §3.1: licences are the only source of covered legs, so a fair-use row has none.
    fair_use_row = rows[scenario["fair_use_asset"]["id"]]
    assert fair_use_row["licensing_status"] == "CLEARED"
    assert fair_use_row["rights_basis"] == "FAIR_USE"
    assert list(fair_use_row["covered_legs"]) == []
    assert list(fair_use_row["license_ids"]) == []

    second_licensed_row = rows[scenario["licensed_two"]["id"]]
    assert second_licensed_row["licensing_status"] == "CLEARED"
    assert second_licensed_row["rights_basis"] == "LICENSED"
    assert list(second_licensed_row["license_ids"]) == [scenario["license_two"]["id"]]

    for asset_id, version in scenario["versions_at_pin"].items():
        assert rows[asset_id]["asset_version"] == version
        # PRD §3.1: depiction_status initialises to NOT_REQUIRED where no identifiable
        # person is named, and nothing in this scenario moves dimension B.
        assert rows[asset_id]["depiction_status"] == "NOT_REQUIRED"


def test_chart_music_leg_gap_count_counts_the_music_row_missing_a_leg(api):
    """The one MUSIC row lacking its PUBLISHING leg gives a gap count of one.

    PRD §3.7: "`music_leg_gap_count` counts the pinned rows whose asset is of type
    `MUSIC` and whose covered legs do not include both `MASTER` and `PUBLISHING`; it
    is the machine-checkable statement "the cue sheet is incomplete"."

    Design: Corner/endpoints/chart_read_returns_the_ordered_snapshot_with_its_derived_counts
    """
    scenario = _setup_mixed_basis_chart(api)

    chart = get_chart(api, scenario["chart"]["id"], LEGAL_COUNSEL)
    assert chart["music_leg_gap_count"] == 1
    # The three footage rows are not MUSIC and therefore cannot contribute a gap.
    music_rows = [row for row in chart["pinned_rows"]
                  if row["asset_id"] == scenario["music"]["id"]]
    assert len(music_rows) == 1
    assert "PUBLISHING" not in list(music_rows[0]["covered_legs"])


def test_chart_pinned_opinion_letter_ids_collect_only_the_fair_use_backing(api):
    """The chart lists the ISSUED letter behind its FAIR_USE row and nothing else.

    PRD §3.7: "`pinned_opinion_letter_ids` collects the id of every opinion letter in
    `ISSUED` that backs a pinned row whose `rights_basis` is `FAIR_USE`, ordered by
    the letters' own `created_at` ascending — this is the list that later constrains
    who may review the application."

    Design: Corner/endpoints/chart_read_returns_the_ordered_snapshot_with_its_derived_counts
    """
    scenario = _setup_mixed_basis_chart(api)

    chart = get_chart(api, scenario["chart"]["id"], LEGAL_COUNSEL)
    assert list(chart["pinned_opinion_letter_ids"]) == [scenario["letter"]["id"]]
    fair_use_rows = [row for row in chart["pinned_rows"]
                     if row["rights_basis"] == "FAIR_USE"]
    assert [row["asset_id"] for row in fair_use_rows] == [scenario["fair_use_asset"]["id"]]


# ─── The delivery package's link to its chart ────────────────────────────────


def test_delivery_package_creation_copies_the_three_counts_off_its_chart(api):
    """The package derives its cue-sheet, rights-chart and gap counts from the chart.

    PRD §3.8: "From the chart the server derives `cue_sheet_row_count` as the number
    of pinned rows whose asset is of type `MUSIC`, `rights_chart_row_count` as the
    chart's total pinned row count across all asset types, and `music_leg_gap_count`
    copied straight from the chart. A new package lands in `DRAFT` with
    `suspension_reason` null and `production_id` taken from the path."

    Design: Corner/endpoints/delivery_package_creation_copies_the_chart_counts_it_links_to
    """
    scenario = _setup_delivery_ready_charts(api)
    chart = get_chart(api, scenario["first_chart"]["id"])
    assert chart["pinned_row_count"] == 2
    assert chart["music_leg_gap_count"] == 0

    package = open_delivery_package(api, scenario["first"]["id"], chart["id"],
                                    distributor_name="Northgate Films",
                                    window_class="ALL_MEDIA_WINDOW")
    assert_delivery_package(package)
    assert package["status"] == "DRAFT"
    assert package["clearance_chart_id"] == chart["id"]
    assert package["production_id"] == scenario["first"]["id"]
    assert package["rights_chart_row_count"] == 2
    assert package["cue_sheet_row_count"] == 1
    assert package["music_leg_gap_count"] == 0
    assert package["suspension_reason"] is None

    persisted = get_delivery_package(api, package["id"])
    assert persisted["rights_chart_row_count"] == 2
    assert persisted["cue_sheet_row_count"] == 1
    assert persisted["music_leg_gap_count"] == 0

    # The MUSIC cue holds both required legs, which is why the gap count is zero.
    assert_asset_dimensions(get_asset(api, scenario["music"]["id"]), "CLEARED",
                            rights_basis="LICENSED")

    rows, meta = validate_paginated(
        api.list_delivery_packages(PRODUCTION_ADMIN,
                                   params={"production_id": scenario["first"]["id"],
                                           "limit": 100}))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [package["id"]]


def test_delivery_package_refuses_a_chart_belonging_to_another_production(api):
    """A chart of a different production is a 422 mismatch, not a 404.

    PRD §3.8: "The chart must belong to the addressed production, failing which the
    answer is `ERR_CHART_PRODUCTION_MISMATCH`."

    Design: Corner/endpoints/delivery_package_creation_copies_the_chart_counts_it_links_to
    """
    scenario = _setup_delivery_ready_charts(api)
    foreign_chart = scenario["second_chart"]

    validate_error(
        api.create_delivery_package(
            scenario["first"]["id"],
            create_delivery_package_payload(foreign_chart["id"],
                                            distributor_name="Northgate Films",
                                            window_class="ALL_MEDIA_WINDOW"),
            PRODUCTION_ADMIN),
        "ERR_CHART_PRODUCTION_MISMATCH")

    # The chart exists and reads back fine, so the refusal is about ownership.
    assert get_chart(api, foreign_chart["id"])["id"] == foreign_chart["id"]
    _rows, meta = validate_paginated(
        api.list_delivery_packages(PRODUCTION_ADMIN,
                                   params={"production_id": scenario["first"]["id"],
                                           "limit": 100}))
    assert meta["total_count"] == 0


# ─── The rights sweep as one bulk pass ──────────────────────────────────────


def test_rights_sweep_activation_step_reports_every_started_licence(api):
    """The first sweep activates all three executed licences and moves no money.

    PRD §3.8: "Every licence of the production in `EXECUTED` whose `term_start_date`
    falls on or before the clock's date moves `EXECUTED → ACTIVE`, incrementing its
    `version`. Because both `EXECUTED` and `ACTIVE` are inside the summed set of
    §2.9, this step moves no money."

    Design: Corner/endpoints/rights_sweep_reports_per_license_outcomes_in_one_bulk_pass
    """
    scenario = _setup_three_licence_sweep(api)
    report = scenario["activation_report"]

    assert report["sweep_epoch"] == 1
    assert list(report["activated_license_ids"]) == [scenario["short_license"]["id"],
                                                     scenario["mid_license"]["id"],
                                                     scenario["long_license"]["id"]]
    assert list(report["expired_license_ids"]) == []
    assert list(report["expiring_license_ids"]) == []
    assert list(report["lapsed_asset_ids"]) == []
    # 258750 + 258750 + 310500, untouched by an activation-only pass.
    assert report["committed_fee_cents"] == 828000
    assert report["production_posture"] == "OPEN"

    for key in ("short_license", "mid_license", "long_license"):
        assert get_license(api, scenario[key]["id"])["status"] == "ACTIVE"


def test_rights_sweep_reports_three_different_per_licence_outcomes(api):
    """One pass expires one licence, flags a second EXPIRING and leaves a third ACTIVE.

    PRD §3.8: "The sweep answers with a report of exactly what it did: `sweep_epoch`
    for the epoch just reached, `activated_license_ids`, `expired_license_ids` and
    `expiring_license_ids` for the three licence steps, `lapsed_asset_ids` for the
    assets that lost coverage, `suspended_delivery_package_ids` and
    `remediated_eo_application_ids` for hops (c) and (d), plus the resulting
    `production_posture` and `committed_fee_cents`."

    Design: Corner/endpoints/rights_sweep_reports_per_license_outcomes_in_one_bulk_pass
    """
    scenario = _setup_three_licence_sweep(api)

    report = run_sweep(api, scenario["production"]["id"])

    assert report["sweep_epoch"] == 2
    assert list(report["expired_license_ids"]) == [scenario["short_license"]["id"]]
    assert list(report["expiring_license_ids"]) == [scenario["mid_license"]["id"]]
    assert list(report["activated_license_ids"]) == []

    # PRD §3.8 step three: a licence exactly 45 whole days from its end date sits
    # inside the 0-to-60-day warning window, while one two years out does not.
    assert get_license(api, scenario["short_license"]["id"])["status"] == "EXPIRED"
    assert get_license(api, scenario["mid_license"]["id"])["status"] == "EXPIRING"
    assert get_license(api, scenario["long_license"]["id"])["status"] == "ACTIVE"

    every_id = (list(report["expired_license_ids"])
                + list(report["expiring_license_ids"])
                + list(report["activated_license_ids"]))
    assert len(every_id) == len(set(every_id))
    assert scenario["long_license"]["id"] not in every_id


def test_rights_sweep_lapses_only_the_asset_that_lost_its_coverage(api):
    """The expired licence's asset lapses; the EXPIRING and ACTIVE ones stay cleared.

    PRD §3.8: "The clearance rollup runs for every asset touched by steps one through
    three, which is where a licence's expiry becomes an asset's loss of coverage: an
    asset whose covered-leg set has emptied moves `CLEARED → LAPSED` with
    `lapse_count` raised by one, while a music asset that lost one leg while the other
    stayed live moves `CLEARED → PARTIALLY_CLEARED`, also raising `lapse_count` by one
    and resetting `rights_basis` to `UNDETERMINED`; both moves adjust
    `cleared_asset_count` down and `open_asset_count` up and flip pinning charts to
    `STALE`."

    Design: Corner/endpoints/rights_sweep_reports_per_license_outcomes_in_one_bulk_pass
    """
    scenario = _setup_three_licence_sweep(api)

    report = run_sweep(api, scenario["production"]["id"])

    assert list(report["lapsed_asset_ids"]) == [scenario["short_asset"]["id"]]
    assert_asset_dimensions(get_asset(api, scenario["short_asset"]["id"]), "LAPSED",
                            rights_basis="UNDETERMINED", lapse_count=1)
    # An EXPIRING licence still contributes coverage, so its asset is untouched.
    assert_asset_dimensions(get_asset(api, scenario["mid_asset"]["id"]), "CLEARED",
                            rights_basis="LICENSED", lapse_count=0)
    assert_asset_dimensions(get_asset(api, scenario["long_asset"]["id"]), "CLEARED",
                            rights_basis="LICENSED", lapse_count=0)

    production = get_production(api, scenario["production"]["id"])
    assert production["asset_count"] == 3
    assert production["cleared_asset_count"] == 2
    assert production["open_asset_count"] == 1


def test_rights_sweep_debits_only_the_expired_licence_and_blocks_the_posture(api):
    """The ledger loses exactly the expired fee and the lapse forces BLOCKED.

    PRD §3.8: "Every licence in `ACTIVE` or `EXPIRING` whose `term_end_date` is on or
    before the clock's date — recall the half-open term of §2.11, so a clock date
    equal to `term_end_date` has already expired — moves to `EXPIRED`, the
    production's `committed_fee_cents` is debited by that licence's
    `executed_fee_cents`, and its `version` increments."

    Design: Corner/endpoints/rights_sweep_reports_per_license_outcomes_in_one_bulk_pass
    """
    scenario = _setup_three_licence_sweep(api)

    report = run_sweep(api, scenario["production"]["id"])

    # 828000 less the expired licence's 258750, with the other two fees untouched.
    assert report["committed_fee_cents"] == 569250
    # PRD §2.8 rule 2: one LAPSED asset outranks any amount of good coverage.
    assert report["production_posture"] == "BLOCKED"
    assert list(report["suspended_delivery_package_ids"]) == []
    assert list(report["remediated_eo_application_ids"]) == []

    production = get_production(api, scenario["production"]["id"])
    assert production["committed_fee_cents"] == 569250
    assert_posture(production, "BLOCKED")
    assert production["sweep_epoch"] == 2


# ─── Every not-found identifier off its own resource ────────────────────────


def test_unknown_production_id_answers_production_not_found(api):
    """A production id that was never minted answers with the production's own code.

    PRD §2.5: "Each entity has its own not-found code: `ERR_PRODUCTION_NOT_FOUND`,
    `ERR_ARCHIVE_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`,
    `ERR_SOURCE_CANDIDATE_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`,
    `ERR_FAIR_USE_ANALYSIS_NOT_FOUND`, `ERR_OPINION_LETTER_NOT_FOUND`,
    `ERR_SUBJECT_RELEASE_NOT_FOUND`, `ERR_CLEARANCE_CHART_NOT_FOUND`,
    `ERR_EO_APPLICATION_NOT_FOUND`, `ERR_DELIVERY_PACKAGE_NOT_FOUND`, each returned
    with HTTP 404."

    Design: Corner/errors/every_not_found_error_id_is_reachable_from_its_own_resource
    """
    production = _seed_production(api)

    validate_error(api.get_production(NON_EXISTENT_UUID, PRODUCTION_ADMIN),
                   "ERR_PRODUCTION_NOT_FOUND")
    # The 404 is id-specific rather than endpoint-wide.
    assert validate_success(
        api.get_production(production["id"], PRODUCTION_ADMIN))["id"] == production["id"]


def test_unknown_archive_id_answers_archive_not_found(api):
    """An archive id that was never minted answers with the archive's own code.

    PRD §2.5: "Each entity has its own not-found code: `ERR_PRODUCTION_NOT_FOUND`,
    `ERR_ARCHIVE_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`,
    `ERR_SOURCE_CANDIDATE_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`,
    `ERR_FAIR_USE_ANALYSIS_NOT_FOUND`, `ERR_OPINION_LETTER_NOT_FOUND`,
    `ERR_SUBJECT_RELEASE_NOT_FOUND`, `ERR_CLEARANCE_CHART_NOT_FOUND`,
    `ERR_EO_APPLICATION_NOT_FOUND`, `ERR_DELIVERY_PACKAGE_NOT_FOUND`, each returned
    with HTTP 404."

    Design: Corner/errors/every_not_found_error_id_is_reachable_from_its_own_resource
    """
    _seed_production(api)

    validate_error(api.get_archive(NON_EXISTENT_UUID, ARCHIVE_RESEARCHER),
                   "ERR_ARCHIVE_NOT_FOUND")


def test_unknown_fair_use_analysis_id_answers_fair_use_analysis_not_found(api):
    """An analysis id that was never minted answers with the analysis's own code.

    PRD §2.5: "Each entity has its own not-found code: `ERR_PRODUCTION_NOT_FOUND`,
    `ERR_ARCHIVE_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`,
    `ERR_SOURCE_CANDIDATE_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`,
    `ERR_FAIR_USE_ANALYSIS_NOT_FOUND`, `ERR_OPINION_LETTER_NOT_FOUND`,
    `ERR_SUBJECT_RELEASE_NOT_FOUND`, `ERR_CLEARANCE_CHART_NOT_FOUND`,
    `ERR_EO_APPLICATION_NOT_FOUND`, `ERR_DELIVERY_PACKAGE_NOT_FOUND`, each returned
    with HTTP 404."

    Design: Corner/errors/every_not_found_error_id_is_reachable_from_its_own_resource
    """
    _seed_production(api)

    validate_error(api.get_fair_use_analysis(NON_EXISTENT_UUID, LEGAL_COUNSEL),
                   "ERR_FAIR_USE_ANALYSIS_NOT_FOUND")


def test_unknown_opinion_letter_id_answers_not_found_before_any_transition_check(api):
    """The path resource is resolved before the state machine is consulted.

    PRD §2.12: "Every resource named by a path parameter exists — otherwise the
    entity's own not-found code. Applies to every operation with an `{id}` in its
    path."

    Design: Corner/errors/every_not_found_error_id_is_reachable_from_its_own_resource
    """
    _seed_production(api)

    validate_error(
        api.set_opinion_letter_state(NON_EXISTENT_UUID, state_payload("ISSUED"),
                                     LEGAL_COUNSEL),
        "ERR_OPINION_LETTER_NOT_FOUND")


def test_unknown_subject_release_id_answers_subject_release_not_found(api):
    """A release id that was never minted answers with the release's own code.

    PRD §2.5: "Each entity has its own not-found code: `ERR_PRODUCTION_NOT_FOUND`,
    `ERR_ARCHIVE_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`,
    `ERR_SOURCE_CANDIDATE_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`,
    `ERR_FAIR_USE_ANALYSIS_NOT_FOUND`, `ERR_OPINION_LETTER_NOT_FOUND`,
    `ERR_SUBJECT_RELEASE_NOT_FOUND`, `ERR_CLEARANCE_CHART_NOT_FOUND`,
    `ERR_EO_APPLICATION_NOT_FOUND`, `ERR_DELIVERY_PACKAGE_NOT_FOUND`, each returned
    with HTTP 404."

    Design: Corner/errors/every_not_found_error_id_is_reachable_from_its_own_resource
    """
    _seed_production(api)

    validate_error(api.get_subject_release(NON_EXISTENT_UUID, PRODUCTION_ADMIN),
                   "ERR_SUBJECT_RELEASE_NOT_FOUND")


def test_unknown_clearance_chart_id_answers_clearance_chart_not_found(api):
    """A chart id that was never minted answers with the chart's own code.

    PRD §2.5: "Each entity has its own not-found code: `ERR_PRODUCTION_NOT_FOUND`,
    `ERR_ARCHIVE_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`,
    `ERR_SOURCE_CANDIDATE_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`,
    `ERR_FAIR_USE_ANALYSIS_NOT_FOUND`, `ERR_OPINION_LETTER_NOT_FOUND`,
    `ERR_SUBJECT_RELEASE_NOT_FOUND`, `ERR_CLEARANCE_CHART_NOT_FOUND`,
    `ERR_EO_APPLICATION_NOT_FOUND`, `ERR_DELIVERY_PACKAGE_NOT_FOUND`, each returned
    with HTTP 404."

    Design: Corner/errors/every_not_found_error_id_is_reachable_from_its_own_resource
    """
    _seed_production(api)

    validate_error(api.get_clearance_chart(NON_EXISTENT_UUID, CLEARANCE_SUPERVISOR),
                   "ERR_CLEARANCE_CHART_NOT_FOUND")


def test_unknown_eo_application_id_answers_eo_application_not_found(api):
    """An application id that was never minted answers with the application's own code.

    PRD §2.5: "Each entity has its own not-found code: `ERR_PRODUCTION_NOT_FOUND`,
    `ERR_ARCHIVE_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`,
    `ERR_SOURCE_CANDIDATE_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`,
    `ERR_FAIR_USE_ANALYSIS_NOT_FOUND`, `ERR_OPINION_LETTER_NOT_FOUND`,
    `ERR_SUBJECT_RELEASE_NOT_FOUND`, `ERR_CLEARANCE_CHART_NOT_FOUND`,
    `ERR_EO_APPLICATION_NOT_FOUND`, `ERR_DELIVERY_PACKAGE_NOT_FOUND`, each returned
    with HTTP 404."

    Design: Corner/errors/every_not_found_error_id_is_reachable_from_its_own_resource
    """
    _seed_production(api)

    validate_error(api.get_eo_application(NON_EXISTENT_UUID, PRODUCTION_ADMIN),
                   "ERR_EO_APPLICATION_NOT_FOUND")


def test_unknown_delivery_package_id_answers_delivery_package_not_found(api):
    """A package id that was never minted answers with the package's own code.

    PRD §2.5: "Each entity has its own not-found code: `ERR_PRODUCTION_NOT_FOUND`,
    `ERR_ARCHIVE_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`,
    `ERR_SOURCE_CANDIDATE_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`,
    `ERR_FAIR_USE_ANALYSIS_NOT_FOUND`, `ERR_OPINION_LETTER_NOT_FOUND`,
    `ERR_SUBJECT_RELEASE_NOT_FOUND`, `ERR_CLEARANCE_CHART_NOT_FOUND`,
    `ERR_EO_APPLICATION_NOT_FOUND`, `ERR_DELIVERY_PACKAGE_NOT_FOUND`, each returned
    with HTTP 404."

    Design: Corner/errors/every_not_found_error_id_is_reachable_from_its_own_resource
    """
    _seed_production(api)

    validate_error(api.get_delivery_package(NON_EXISTENT_UUID, PRODUCTION_ADMIN),
                   "ERR_DELIVERY_PACKAGE_NOT_FOUND")


# ─── The authentication and authorization ladder ────────────────────────────


def test_absent_identity_headers_are_unauthenticated(api):
    """A request carrying neither identity header is refused before anything else.

    PRD §2.1: "If either header is absent, present but empty, or if `X-User-Role`
    names anything other than one of the five roles below, the request is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs."

    Design: Corner/errors/wrong_role_and_missing_headers_return_unauthorized_or_unauthenticated
    """
    production = _seed_production(api)

    validate_error(api.get_production(production["id"], NO_AUTH_HEADERS),
                   "ERR_UNAUTHENTICATED")


def test_absent_identity_headers_outrank_a_bogus_path_id(api):
    """Authentication is answered before the path resource is ever looked up.

    PRD §2.1: "If either header is absent, present but empty, or if `X-User-Role`
    names anything other than one of the five roles below, the request is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs."

    Design: Corner/errors/wrong_role_and_missing_headers_return_unauthorized_or_unauthenticated
    """
    _seed_production(api)

    # A non-existent production id would be a 404 for an authenticated caller.
    validate_error(api.get_production(NON_EXISTENT_UUID, NO_AUTH_HEADERS),
                   "ERR_UNAUTHENTICATED")


def test_an_undeclared_role_name_is_unauthenticated_rather_than_unauthorized(api):
    """A role name outside the five declared roles is a 401, not a 403.

    PRD §2.1: "If either header is absent, present but empty, or if `X-User-Role`
    names anything other than one of the five roles below, the request is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs."

    Design: Corner/errors/wrong_role_and_missing_headers_return_unauthorized_or_unauthenticated
    """
    production = _seed_production(api)

    validate_error(
        api.get_production(production["id"], build_user_headers("outsider-9", "Producer")),
        "ERR_UNAUTHENTICATED")


def test_a_declared_role_off_the_reads_role_list_is_unauthorized(api):
    """A RightsHolderRep is a real role but cannot read a production.

    PRD §2.1: "A request that authenticates successfully but whose role does not
    appear in the target operation's authorized-role list is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/errors/wrong_role_and_missing_headers_return_unauthorized_or_unauthenticated
    """
    production = _seed_production(api)
    archive = create_archive(api, name="Pathe Vault", holder_type="FILM_ARCHIVE")

    # PRD §4: GET /productions/{id} authorizes ProductionAdmin, ClearanceSupervisor,
    # ArchiveResearcher and LegalCounsel — RightsHolderRep is absent from that list.
    validate_error(
        api.get_production(production["id"],
                           make_rights_holder_rep_headers(archive["id"])),
        "ERR_UNAUTHORIZED")


def test_a_declared_role_off_a_state_endpoints_role_list_is_unauthorized(api):
    """Archive suspension is a ClearanceSupervisor act and refuses the researcher.

    PRD §2.1: "A request that authenticates successfully but whose role does not
    appear in the target operation's authorized-role list is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/errors/wrong_role_and_missing_headers_return_unauthorized_or_unauthenticated
    """
    _seed_production(api)
    archive = create_archive(api, name="Pathe Vault", holder_type="FILM_ARCHIVE")

    validate_error(
        api.set_archive_state(archive["id"],
                              state_payload("SUSPENDED", reason="Chain of title dispute"),
                              ARCHIVE_RESEARCHER),
        "ERR_UNAUTHORIZED")

    # The refused transition left the holder untouched.
    assert validate_success(
        api.get_archive(archive["id"], ARCHIVE_RESEARCHER))["status"] == "ACTIVE"


# ─── The E&O review gates ───────────────────────────────────────────────────


def test_legal_review_recorded_by_a_supervisor_is_a_review_type_role_mismatch(api):
    """The LEGAL branch belongs to counsel, so a supervisor's LEGAL review is refused.

    PRD §3.7: "Third, the branch must match the acting role: `LEGAL` may only be
    recorded by `LegalCounsel` and `UNDERWRITING` only by a `ClearanceSupervisor`, and
    any other pairing is refused with `ERR_REVIEW_TYPE_ROLE_MISMATCH` (HTTP 403)."

    Design: Corner/errors/eo_review_gates_cover_role_type_duplicate_and_incomplete_reviews
    """
    _production, _chart, application = _setup_submitted_eo_application(api)

    validate_error(
        api.create_eo_review(application["id"],
                             create_eo_review_payload("LEGAL", "PASS",
                                                      notes="Clearance chart reviewed."),
                             CLEARANCE_SUPERVISOR),
        "ERR_REVIEW_TYPE_ROLE_MISMATCH")

    settled = _read_eo_application(api, application["id"])
    assert settled["status"] == "SUBMITTED"
    assert settled["legal_review_status"] == "PENDING"
    assert settled["underwriting_review_status"] == "PENDING"


def test_the_first_accepted_review_moves_the_application_into_review(api):
    """A LegalCounsel LEGAL review passes one branch and forks the status.

    PRD §3.7: "An accepted review sets its dimension to `PASSED` or `FAILED` according
    to the `outcome`, stamps the acting `X-User-ID` into `legal_reviewer_user_id` or
    `underwriting_reviewer_user_id`, and increments the application's `version`. The
    first review of either type also moves the application `SUBMITTED → IN_REVIEW`."

    Design: Corner/errors/eo_review_gates_cover_role_type_duplicate_and_incomplete_reviews
    """
    _production, _chart, application = _setup_submitted_eo_application(api)

    returned = validate_success(
        api.create_eo_review(application["id"],
                             create_eo_review_payload("LEGAL", "PASS",
                                                      notes="Clearance chart reviewed."),
                             REVIEWING_COUNSEL))
    assert returned["status"] == "IN_REVIEW"
    assert returned["legal_review_status"] == "PASSED"
    assert returned["underwriting_review_status"] == "PENDING"

    settled = _read_eo_application(api, application["id"])
    assert settled["status"] == "IN_REVIEW"
    assert settled["legal_review_status"] == "PASSED"
    assert settled["underwriting_review_status"] == "PENDING"
    assert settled["legal_reviewer_user_id"] == REVIEWING_COUNSEL["X-User-ID"]
    assert settled["version"] == application["version"] + 1


def test_binding_with_one_branch_still_pending_reports_reviews_incomplete(api):
    """A bind request from IN_REVIEW takes the specific code, not the generic one.

    PRD §3.7: "A request to bind from any status other than `CLEARED_TO_BIND` or
    `REMEDIATION_REQUIRED` is refused with `ERR_REVIEWS_INCOMPLETE` (HTTP 409) rather
    than the generic invalid-transition code, because the substantive complaint is
    always that both review branches have not yet passed."

    Design: Corner/errors/eo_review_gates_cover_role_type_duplicate_and_incomplete_reviews
    """
    _production, _chart, application = _setup_submitted_eo_application(api)
    validate_success(
        api.create_eo_review(application["id"], create_eo_review_payload("LEGAL", "PASS"),
                             REVIEWING_COUNSEL))

    validate_error(
        api.set_eo_application_state(application["id"],
                                     state_payload("BOUND", policy_number="EO-2026-778"),
                                     PRODUCTION_ADMIN),
        "ERR_REVIEWS_INCOMPLETE")

    settled = _read_eo_application(api, application["id"])
    assert settled["status"] == "IN_REVIEW"
    assert settled["policy_number"] is None
    assert settled["underwriting_review_status"] == "PENDING"


def test_recording_the_same_review_type_twice_is_refused_and_changes_nothing(api):
    """A second LEGAL review cannot overwrite the first, not even with a FAIL.

    PRD §3.7: "Second, the addressed dimension must still be `PENDING`; recording the
    same `review_type` twice is refused with `ERR_REVIEW_ALREADY_RECORDED` (HTTP
    409)."

    Design: Corner/errors/eo_review_gates_cover_role_type_duplicate_and_incomplete_reviews
    """
    _production, _chart, application = _setup_submitted_eo_application(api)
    validate_success(
        api.create_eo_review(application["id"], create_eo_review_payload("LEGAL", "PASS"),
                             REVIEWING_COUNSEL))

    validate_error(
        api.create_eo_review(application["id"],
                             create_eo_review_payload("LEGAL", "FAIL",
                                                      notes="Second bite."),
                             REVIEWING_COUNSEL),
        "ERR_REVIEW_ALREADY_RECORDED")

    settled = _read_eo_application(api, application["id"])
    assert settled["legal_review_status"] == "PASSED"
    assert settled["status"] == "IN_REVIEW"


def test_underwriting_review_recorded_by_counsel_is_a_review_type_role_mismatch(api):
    """The UNDERWRITING branch belongs to the supervisor, so counsel is refused.

    PRD §3.7: "Third, the branch must match the acting role: `LEGAL` may only be
    recorded by `LegalCounsel` and `UNDERWRITING` only by a `ClearanceSupervisor`, and
    any other pairing is refused with `ERR_REVIEW_TYPE_ROLE_MISMATCH` (HTTP 403)."

    Design: Corner/errors/eo_review_gates_cover_role_type_duplicate_and_incomplete_reviews
    """
    _production, _chart, application = _setup_submitted_eo_application(api)
    validate_success(
        api.create_eo_review(application["id"], create_eo_review_payload("LEGAL", "PASS"),
                             REVIEWING_COUNSEL))

    # A second, distinct counsel operator, so no segregation-of-duties rule is in play.
    validate_error(
        api.create_eo_review(application["id"],
                             create_eo_review_payload("UNDERWRITING", "PASS",
                                                      notes="Rated and accepted."),
                             LEGAL_COUNSEL),
        "ERR_REVIEW_TYPE_ROLE_MISMATCH")

    settled = _read_eo_application(api, application["id"])
    assert settled["underwriting_review_status"] == "PENDING"
    assert settled["status"] == "IN_REVIEW"


def test_both_branches_passing_joins_at_cleared_to_bind_and_then_binds(api):
    """The second passing branch joins the fork and the policy binds at the rated price.

    PRD §3.7: "When both `legal_review_status` and `underwriting_review_status` read
    `PASSED`, the application moves `IN_REVIEW → CLEARED_TO_BIND`: no premium
    adjustment occurs and the application remains bindable at the rated price."

    Design: Corner/errors/eo_review_gates_cover_role_type_duplicate_and_incomplete_reviews
    """
    _production, _chart, application = _setup_submitted_eo_application(api)
    # Base 12500 on a coverage limit of 1000000, no rateable pinned rows and a
    # retention credit of 30000, so PRD §3.7's minimum premium of 25000 applies.
    assert application["premium_cents"] == 25000

    validate_success(
        api.create_eo_review(application["id"], create_eo_review_payload("LEGAL", "PASS"),
                             REVIEWING_COUNSEL))
    joined = validate_success(
        api.create_eo_review(application["id"],
                             create_eo_review_payload("UNDERWRITING", "PASS",
                                                      notes="Rated and accepted."),
                             CLEARANCE_SUPERVISOR))
    assert joined["status"] == "CLEARED_TO_BIND"
    assert joined["legal_review_status"] == "PASSED"
    assert joined["underwriting_review_status"] == "PASSED"
    assert joined["premium_cents"] == 25000

    bound = validate_success(
        api.set_eo_application_state(application["id"],
                                     state_payload("BOUND", policy_number="EO-2026-778"),
                                     PRODUCTION_ADMIN))
    assert bound["status"] == "BOUND"
    assert bound["policy_number"] == "EO-2026-778"

    settled = _read_eo_application(api, application["id"])
    assert settled["status"] == "BOUND"
    assert settled["policy_number"] == "EO-2026-778"
    assert settled["premium_cents"] == 25000


# ─── The two posture gates ──────────────────────────────────────────────────


def test_a_blocked_posture_refuses_the_chart_pin(api):
    """One open asset out of one blocks the production and the pin with it.

    PRD §3.7: "A production whose `version` has moved since the client read it is
    refused with `ERR_STALE_PRODUCTION_VERSION` (HTTP 412), and a production whose
    `posture` is `BLOCKED` is refused with `ERR_PRODUCTION_POSTURE_BLOCKED`; a
    `RESTRICTED` production may still pin."

    Design: Corner/errors/posture_gates_report_blocked_and_restricted_distinctly
    """
    production, _archive, _asset = _setup_depicted_asset_production(api)
    current = get_production(api, production["id"])
    assert_posture(current, "BLOCKED")

    validate_error(
        api.pin_clearance_chart(production["id"],
                                pin_clearance_chart_payload(current["version"],
                                                            "too early"),
                                CLEARANCE_SUPERVISOR),
        "ERR_PRODUCTION_POSTURE_BLOCKED")

    charts, meta = validate_paginated(
        api.list_production_clearance_charts(production["id"], CLEARANCE_SUPERVISOR,
                                             params={"limit": 100}))
    assert meta["total_count"] == 0
    assert charts == []


def test_a_restricted_posture_still_permits_the_same_chart_pin(api):
    """With the licence executed and only a depiction pending, the pin succeeds.

    PRD §3.7: "A production whose `version` has moved since the client read it is
    refused with `ERR_STALE_PRODUCTION_VERSION` (HTTP 412), and a production whose
    `posture` is `BLOCKED` is refused with `ERR_PRODUCTION_POSTURE_BLOCKED`; a
    `RESTRICTED` production may still pin."

    Design: Corner/errors/posture_gates_report_blocked_and_restricted_distinctly
    """
    production, archive, asset = _setup_depicted_asset_production(api)
    create_and_execute_license(api, production["id"], asset["id"], archive["id"],
                               **TWELVE_MONTH_TERM)
    _send_release_for(api, production["id"], asset["id"])

    # PRD §2.8 rule 4: zero open assets multiplied by four is zero, which is less than
    # or equal to the single-asset total, so the pending depiction leaves RESTRICTED.
    assert_posture(get_production(api, production["id"]), "RESTRICTED")

    chart = pin_chart(api, production["id"], "restricted pin")
    assert chart["status"] == "PINNED"
    assert chart["pinned_row_count"] == 1
    assert chart["pinned_rows"][0]["asset_id"] == asset["id"]
    assert chart["pinned_rows"][0]["licensing_status"] == "CLEARED"
    assert chart["pinned_rows"][0]["depiction_status"] == "PENDING"


def test_locking_a_restricted_production_reports_the_restricted_code(api):
    """The LOCKED move demands posture exactly OPEN and names RESTRICTED as the reason.

    PRD §3.1: "The move `CLEARANCE → LOCKED` is reserved to a `ClearanceSupervisor`
    and demands two things: `posture` must be exactly `OPEN` (a `RESTRICTED`
    production is refused with `ERR_PRODUCTION_POSTURE_RESTRICTED` and a `BLOCKED` one
    with `ERR_PRODUCTION_POSTURE_BLOCKED`), and at least one E&O application of the
    production must be in `BOUND`, failing which the answer is `ERR_EO_NOT_BOUND`."

    Design: Corner/errors/posture_gates_report_blocked_and_restricted_distinctly
    """
    production, archive, asset = _setup_depicted_asset_production(api)
    create_and_execute_license(api, production["id"], asset["id"], archive["id"],
                               **TWELVE_MONTH_TERM)
    _send_release_for(api, production["id"], asset["id"])
    pin_chart(api, production["id"], "restricted pin")
    assert_posture(get_production(api, production["id"]), "RESTRICTED")

    # No E&O application exists at all, yet the posture rung answers first.
    validate_error(
        api.set_production_state(production["id"], state_payload("LOCKED"),
                                 CLEARANCE_SUPERVISOR),
        "ERR_PRODUCTION_POSTURE_RESTRICTED")

    settled = get_production(api, production["id"])
    assert settled["status"] == "CLEARANCE"
    assert settled["committed_fee_cents"] == TWELVE_MONTH_FEE_CENTS
    assert_posture(settled, "RESTRICTED")


def test_a_depicted_asset_stays_pending_while_its_release_is_only_sent(api):
    """Dimension B opens at PENDING and sending the paper out does not settle it.

    PRD §3.1: "Its `depiction_status` initialises to `PENDING` when
    `depiction_subject_key` is non-null at creation and to `NOT_REQUIRED` otherwise."

    Design: Corner/errors/posture_gates_report_blocked_and_restricted_distinctly
    """
    production, _archive, asset = _setup_depicted_asset_production(api)
    assert get_asset(api, asset["id"])["depiction_status"] == "PENDING"

    release = _send_release_for(api, production["id"], asset["id"])
    assert release["status"] == "SENT"

    # PRD §3.6 settles dimension B only on signing, refusal or an approval decision.
    assert get_asset(api, asset["id"])["depiction_status"] == "PENDING"
