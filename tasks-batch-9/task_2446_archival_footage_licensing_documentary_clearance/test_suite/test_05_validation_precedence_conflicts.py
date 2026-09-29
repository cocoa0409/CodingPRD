"""Precedence conflicts: one request that violates two rungs of the PRD §2.12 ladder.

PRD §2.12: "When a single request violates more than one rule, exactly one error is
returned, and which one is determined by a fixed global precedence rather than by the
order the implementation happens to evaluate checks." Each pair below arms both
violations in the same request, then removes the higher-ranked one so the lower-ranked
error can surface — which is what proves the ordering rather than a lucky evaluation
order.
"""
from typing import Any, Dict

from test_helpers import (
    CLEARANCE_SUPERVISOR,
    add_source_candidate,
    create_and_execute_license,
    create_archive_with_rate_card,
    create_asset_with_selected_source,
    create_license_payload,
    create_production_in_clearance,
    drive_production,
    get_asset,
    get_chart,
    get_delivery_package,
    get_production,
    open_delivery_package,
    pin_chart,
    select_source,
    setup_bound_eo_production,
    setup_licensed_footage_production,
    setup_music_asset_with_master_leg_only,
    state_payload,
    validate_error,
    validate_paginated,
)

# The overlapping term sits strictly inside the live licence's 2026-08-15 .. 2029-08-15
# term, on the same asset, leg, media and territory, so PRD §3.3's overlap rule bites.
_OVERLAPPING_TERM = {
    "rights_leg": "FOOTAGE",
    "media": "BROADCAST",
    "territory": "WORLD",
    "window_class": "ALL_MEDIA_WINDOW",
    "term_months": 12,
    "term_start_date": "2027-01-01",
    "term_end_date": "2028-01-01",
}

# A term starting exactly on the live licence's term_end_date. PRD §2.11 makes the term
# a half-open interval, so this term does not overlap and no fiscal rule is armed.
_ADJACENT_TERM = {
    "rights_leg": "FOOTAGE",
    "media": "BROADCAST",
    "territory": "WORLD",
    "window_class": "ALL_MEDIA_WINDOW",
    "term_months": 12,
    "term_start_date": "2029-08-15",
    "term_end_date": "2030-08-15",
}


def _licenses_of_asset(api, asset_id: str):
    rows, _meta = validate_paginated(
        api.list_licenses(CLEARANCE_SUPERVISOR, params={"asset_id": asset_id, "limit": 100}))
    return rows


def _candidates_of_asset(api, asset_id: str):
    rows, _meta = validate_paginated(
        api.list_asset_source_candidates(asset_id, CLEARANCE_SUPERVISOR, params={"limit": 100}))
    return rows


def _setup_locked_production_over_a_live_footage_licence(api) -> Dict[str, Any]:
    """A production driven CLEARANCE → LOCKED over one CLEARED footage asset.

    PRD §3.1 gates that move on posture exactly OPEN and on an E&O application in
    BOUND, so the whole chart-pin / E&O-bind path is walked before locking.
    """
    scenario = setup_bound_eo_production(api)
    scenario["production"] = drive_production(
        api, scenario["production"]["id"], "LOCKED", CLEARANCE_SUPERVISOR)
    return scenario


def _setup_gapped_chart_delivery_package(api, stale_the_chart: bool) -> Dict[str, Any]:
    """A DRAFT package over a PINNED chart whose music_leg_gap_count is 1.

    Three footage assets are CLEARED by executed FOOTAGE licences and one MUSIC asset
    holds only its MASTER leg, so PRD §2.8 rule 4 makes the posture RESTRICTED (one open
    asset out of four) rather than BLOCKED, and PRD §3.7's music_leg_gap_count is 1.
    When `stale_the_chart` is set, a second source selection on footage asset one
    advances that asset's version, which PRD §2.10 turns into chart staleness.
    """
    production = create_production_in_clearance(api, title="Stale And Gapped",
                                                delivery_deadline_date="2028-02-29")
    footage_archive, _footage_card = create_archive_with_rate_card(api)
    label, _label_card = create_archive_with_rate_card(
        api,
        archive_overrides={"name": "Harmony Masters", "holder_type": "RECORD_LABEL"},
        card_overrides={"base_rate_per_30s_cents": 10000, "minimum_fee_cents": 20000,
                        "festival_minimum_fee_cents": 10000})

    footage_assets = []
    footage_candidates = []
    for title in ("Footage one", "Footage two", "Footage three"):
        asset, candidate = create_asset_with_selected_source(
            api, production["id"], footage_archive["id"], title=title)
        create_and_execute_license(api, production["id"], asset["id"], footage_archive["id"])
        footage_assets.append(asset)
        footage_candidates.append(candidate)

    music = setup_music_asset_with_master_leg_only(api, production["id"], label["id"])
    chart = pin_chart(api, production["id"], "v1 with music gap")
    package = open_delivery_package(api, production["id"], chart["id"])

    replacement_candidate = None
    if stale_the_chart:
        replacement_candidate = add_source_candidate(
            api, footage_assets[0]["id"], footage_archive["id"])
        select_source(api, footage_assets[0]["id"], replacement_candidate["id"])

    return {
        "production": get_production(api, production["id"]),
        "footage_archive": footage_archive,
        "label": label,
        "footage_assets": footage_assets,
        "first_candidate": footage_candidates[0],
        "replacement_candidate": replacement_candidate,
        "music_asset": music["asset"],
        "chart": get_chart(api, chart["id"]),
        "package": package,
    }


# ─── priority_pair_validation_conflict ───────────────────────────────────────
# Rung 11 (ERR_PRODUCTION_NOT_IN_CLEARANCE) against rung 38 (ERR_LICENSE_TERM_OVERLAP).


def test_locked_production_outranks_the_overlapping_term_on_license_creation(api):
    """Both triggers armed on one licence creation: the production is LOCKED and the
    requested term overlaps a live sibling. PRD §2.12 rung 11: "The parent production
    accepts new clearance work, meaning its `status` is `DEVELOPMENT` or `CLEARANCE` —
    otherwise `ERR_PRODUCTION_NOT_IN_CLEARANCE`." That rung sits above PRD §2.12 rung
    38: "The requested term does not overlap a live sibling licence as defined in §3.3
    — otherwise `ERR_LICENSE_TERM_OVERLAP`.", so only the state error may surface.

    Design: Difficulty/priority_pair_validation_conflict/locked_production_state_error_outranks_license_term_overlap
    """
    scenario = _setup_locked_production_over_a_live_footage_licence(api)
    production_id = scenario["production"]["id"]
    asset_id = scenario["asset"]["id"]
    archive_id = scenario["archive"]["id"]

    before = get_production(api, production_id)
    assert before["status"] == "LOCKED"

    response = api.create_license(
        create_license_payload(production_id, asset_id, archive_id, **_OVERLAPPING_TERM),
        CLEARANCE_SUPERVISOR)
    validate_error(response, "ERR_PRODUCTION_NOT_IN_CLEARANCE")

    rows = _licenses_of_asset(api, asset_id)
    assert len(rows) == 1, (
        f"the rejected creation must not persist a licence, found {len(rows)} rows")
    assert rows[0]["id"] == scenario["license"]["id"]
    assert rows[0]["status"] == "EXECUTED"

    after = get_production(api, production_id)
    assert after["status"] == "LOCKED"
    assert after["version"] == before["version"], (
        "a rejected request must not advance the production's version")
    assert after["posture"] == "OPEN"


def test_term_overlap_surfaces_once_the_production_still_accepts_clearance_work(api):
    """The higher-ranked condition removed: the production stays in CLEARANCE, so the
    only violation left is the term collision. PRD §2.12 rung 38: "The requested term
    does not overlap a live sibling licence as defined in §3.3 — otherwise
    `ERR_LICENSE_TERM_OVERLAP`. Applies to licence creation and licence renewal."

    Design: Difficulty/priority_pair_validation_conflict/locked_production_state_error_outranks_license_term_overlap
    """
    scenario = setup_licensed_footage_production(api)
    production_id = scenario["production"]["id"]
    asset_id = scenario["asset"]["id"]
    archive_id = scenario["archive"]["id"]

    before = get_production(api, production_id)
    assert before["status"] == "CLEARANCE"

    response = api.create_license(
        create_license_payload(production_id, asset_id, archive_id, **_OVERLAPPING_TERM),
        CLEARANCE_SUPERVISOR)
    validate_error(response, "ERR_LICENSE_TERM_OVERLAP")

    rows = _licenses_of_asset(api, asset_id)
    assert len(rows) == 1, (
        f"the rejected creation must not persist a licence, found {len(rows)} rows")
    assert rows[0]["status"] == "EXECUTED"

    after = get_production(api, production_id)
    assert after["status"] == "CLEARANCE"
    assert after["version"] == before["version"]


def test_locked_production_refuses_even_a_non_overlapping_adjacent_term(api):
    """With the fiscal rule disarmed the state rung still fires alone. PRD §2.11: "The
    same half-open convention governs overlap between sibling licences, which means
    adjacency is legal — a term starting exactly on an existing term's end date does not
    overlap it." PRD §2.12 rung 11: "The parent production accepts new clearance work,
    meaning its `status` is `DEVELOPMENT` or `CLEARANCE` — otherwise
    `ERR_PRODUCTION_NOT_IN_CLEARANCE`."

    Design: Difficulty/priority_pair_validation_conflict/locked_production_state_error_outranks_license_term_overlap
    """
    scenario = _setup_locked_production_over_a_live_footage_licence(api)
    production_id = scenario["production"]["id"]
    asset_id = scenario["asset"]["id"]
    archive_id = scenario["archive"]["id"]

    response = api.create_license(
        create_license_payload(production_id, asset_id, archive_id, **_ADJACENT_TERM),
        CLEARANCE_SUPERVISOR)
    validate_error(response, "ERR_PRODUCTION_NOT_IN_CLEARANCE")

    assert len(_licenses_of_asset(api, asset_id)) == 1
    assert get_production(api, production_id)["status"] == "LOCKED"


# Rung 20 (ERR_CHART_STALE) against rung 26 (ERR_CUE_SHEET_INCOMPLETE).


def test_stale_chart_outranks_the_incomplete_cue_sheet_on_package_validation(api):
    """Both triggers armed on one package validation: the chart has gone STALE and its
    snapshot records a MUSIC row missing its PUBLISHING leg. PRD §2.12 rung 20: "The
    referenced clearance chart has not gone `STALE` — otherwise `ERR_CHART_STALE`.
    Applies to E&O submission and delivery-package validation." That rung sits above
    PRD §2.12 rung 26: "The chart's `music_leg_gap_count` is zero — otherwise
    `ERR_CUE_SHEET_INCOMPLETE`. Applies to delivery-package validation."

    Design: Difficulty/priority_pair_validation_conflict/stale_chart_referential_error_outranks_cue_sheet_safety_error
    """
    scenario = _setup_gapped_chart_delivery_package(api, stale_the_chart=True)
    chart = scenario["chart"]
    package_id = scenario["package"]["id"]

    assert chart["status"] == "STALE"
    assert chart["music_leg_gap_count"] == 1, (
        "the pinned MUSIC row carries only its MASTER leg, so the cue sheet is incomplete")
    assert scenario["production"]["posture"] == "RESTRICTED"

    response = api.set_delivery_package_state(
        package_id, state_payload("VALIDATED"), CLEARANCE_SUPERVISOR)
    validate_error(response, "ERR_CHART_STALE")

    assert get_delivery_package(api, package_id)["status"] == "DRAFT"
    assert get_chart(api, chart["id"])["status"] == "STALE"
    assert get_production(api, scenario["production"]["id"])["posture"] == "RESTRICTED"

    music_asset = get_asset(api, scenario["music_asset"]["id"])
    assert music_asset["licensing_status"] == "PARTIALLY_CLEARED", (
        "only the MASTER leg of the two required MUSIC legs is covered")

    candidates = {row["id"]: row for row in _candidates_of_asset(
        api, scenario["footage_assets"][0]["id"])}
    assert candidates[scenario["first_candidate"]["id"]]["selection_status"] == "REJECTED"
    assert candidates[scenario["replacement_candidate"]["id"]]["selection_status"] == "SELECTED"


def test_incomplete_cue_sheet_surfaces_once_the_chart_is_still_pinned(api):
    """The higher-ranked condition removed: no asset version moved, so the chart is
    still PINNED and the music-leg gap is the only violation left. PRD §2.12 rung 26:
    "The chart's `music_leg_gap_count` is zero — otherwise `ERR_CUE_SHEET_INCOMPLETE`.
    Applies to delivery-package validation."

    Design: Difficulty/priority_pair_validation_conflict/stale_chart_referential_error_outranks_cue_sheet_safety_error
    """
    scenario = _setup_gapped_chart_delivery_package(api, stale_the_chart=False)
    chart = scenario["chart"]
    package_id = scenario["package"]["id"]

    assert chart["status"] == "PINNED"
    assert chart["music_leg_gap_count"] == 1
    assert scenario["package"]["music_leg_gap_count"] == 1, (
        "the package copies music_leg_gap_count straight from the chart")

    response = api.set_delivery_package_state(
        package_id, state_payload("VALIDATED"), CLEARANCE_SUPERVISOR)
    validate_error(response, "ERR_CUE_SHEET_INCOMPLETE")

    assert get_delivery_package(api, package_id)["status"] == "DRAFT"
    assert get_chart(api, chart["id"])["status"] == "PINNED"
    assert get_production(api, scenario["production"]["id"])["posture"] == "RESTRICTED"
    assert get_asset(api, scenario["music_asset"]["id"])["licensing_status"] == \
        "PARTIALLY_CLEARED"
