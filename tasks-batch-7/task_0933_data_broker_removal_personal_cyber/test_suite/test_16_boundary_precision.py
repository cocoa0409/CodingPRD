"""Boundary precision: the strict 45-day reappearance cool-off, and the
empty-collection floor of the coverage ratio."""
from test_helpers import (
    validate_success, validate_paginated, assert_same_instant, fixtures as fx,
)


# ==========================================================================
# The reappearance cool-off is strict: 44 reappears, 45 is fresh
# ==========================================================================

def _two_suppressed_exposures_and_a_running_rescan():
    """Two exposures at two brokers, both suppressed at the startup instant, and
    a RECURRING scan started at 2026-06-14 — exactly 44 whole days later."""
    world = fx.setup_household_with_two_exposures(
        broker_a={"name": "PeopleFinderCo", "opt_out_method": "WEB_FORM",
                  "jurisdiction": "OTHER", "response_window_days": 30},
        broker_b={"name": "QuickLookup", "opt_out_method": "WEB_FORM",
                  "jurisdiction": "OTHER", "response_window_days": 30})
    fx.suppress_exposure(world["exposure_a"]["id"], broker_reference="PF-1")
    fx.suppress_exposure(world["exposure_b"]["id"], broker_reference="QL-1")

    fx.set_clock("2026-06-14T00:00:00Z")
    scan = fx.queue_scan(world["profile"]["id"], kind="RECURRING")
    fx.start_scan(scan["id"])
    world["rescan"] = scan
    return world


def test_a_re_finding_at_forty_four_elapsed_days_reappears_in_place(api):
    """PRD §3.4: "With a candidate in `SUPPRESSED` or `RE_SUPPRESSED`, the server computes
    the whole number of elapsed days by dividing the seconds between the candidate's
    `last_suppressed_at` and the current instant by 86400 and flooring, and classifies the
    hit as `REAPPEARANCE` when that figure is **strictly less than** 45 and as `FRESH`
    otherwise."
    PRD §3.4: "The boundary is strict and the consequences are large: at 44 whole elapsed
    days the hit is a `REAPPEARANCE`, and at exactly 45 it is `FRESH`."

    Design: Difficulty/boundary_precision_check/reappearance_cooloff_strict_boundary_44_vs_45_days
    """
    world = _two_suppressed_exposures_and_a_running_rescan()

    data = validate_success(api.record_finding(
        world["rescan"]["id"],
        {"broker_id": world["broker_a"]["id"], "exposure_kind": "PEOPLE_SEARCH",
         "source_url": "https://peoplefinderco.example/dana"},
        fx.AGENT))

    # 2026-05-01 to 2026-06-14 is 44 whole days, strictly below 45.
    assert data["id"] == world["exposure_a"]["id"], "the same row must be returned"
    assert data["status"] == "REAPPEARED"
    assert data["reappearance_count"] == 1
    assert data["suppression_count"] == 1
    assert data["fee_exempt"] is True

    _, meta = validate_paginated(api.list_exposures(
        world["household"]["owner"],
        params={"profile_id": world["profile"]["id"],
                "broker_id": world["broker_a"]["id"]}))
    assert meta["total_count"] == 1


def test_a_re_finding_at_exactly_forty_five_elapsed_days_creates_a_fresh_row(api):
    """PRD §3.4: "The boundary is strict and the consequences are large: at 44 whole
    elapsed days the hit is a `REAPPEARANCE`, and at exactly 45 it is `FRESH`."
    PRD §3.4: "`FRESH` creates a brand-new exposure row in `FOUND`, stamping
    `discovered_by_scan_id` with this scan — a value never rewritten by any later sighting
    — along with `first_found_at` and `last_seen_at` at the current instant,
    `suppression_count` and `reappearance_count` at 0."

    Design: Difficulty/boundary_precision_check/reappearance_cooloff_strict_boundary_44_vs_45_days
    """
    world = _two_suppressed_exposures_and_a_running_rescan()

    # 2026-05-01 to 2026-06-15 is exactly 45 whole days.
    fx.set_clock("2026-06-15T00:00:00Z")
    data = validate_success(api.record_finding(
        world["rescan"]["id"],
        {"broker_id": world["broker_b"]["id"], "exposure_kind": "PEOPLE_SEARCH",
         "source_url": "https://quicklookup.example/dana"},
        fx.AGENT))

    assert data["id"] != world["exposure_b"]["id"], "45 days belongs to the FRESH side"
    assert data["status"] == "FOUND"
    assert data["reappearance_count"] == 0
    assert data["suppression_count"] == 0
    assert data["fee_exempt"] is False
    assert data["discovered_by_scan_id"] == world["rescan"]["id"]
    assert_same_instant(data["first_found_at"], "2026-06-15T00:00:00Z", "first_found_at")

    incumbent = fx.read_exposure(world["exposure_b"]["id"])
    assert incumbent["status"] == "SUPPRESSED", "the incumbent row is untouched"
    assert incumbent["reappearance_count"] == 0

    _, meta = validate_paginated(api.list_exposures(
        world["household"]["owner"],
        params={"profile_id": world["profile"]["id"],
                "broker_id": world["broker_b"]["id"]}))
    assert meta["total_count"] == 2


# ==========================================================================
# The coverage ratio's empty-set floor
# ==========================================================================

def _member_with_a_profile_but_no_exposures():
    household = fx.open_household()
    profile = fx.setup_active_profile(household)
    scan, _ = fx.run_scan(profile["id"], [], kind="INITIAL", complete=True)
    return household, profile, scan


def test_coverage_ratio_is_pinned_to_zero_when_there_are_no_exposures(api):
    """PRD §3.9: "Finally it reports a `coverage_ratio`: the number of those exposures in
    `SUPPRESSED` or `RE_SUPPRESSED` divided by the total number of exposures, rounded
    half-up to 4 decimal places — and pinned to exactly 0.0000 when the member has no
    exposures at all."
    PRD §3.9: "That empty-set case is never null, never an error and never 1.0000."

    Design: Difficulty/boundary_precision_check/exposure_summary_coverage_ratio_zero_denominator
    """
    household, profile, scan = _member_with_a_profile_but_no_exposures()

    data = validate_success(api.get_exposure_summary(household["owner_id"],
                                                     household["owner"]))

    assert data["coverage_ratio"] is not None
    assert float(data["coverage_ratio"]) == 0.0
    assert data["brokers"] == []


def test_exposure_summary_tallies_are_all_zero_with_an_empty_inventory(api):
    """PRD §3.9: "It reports the `member_id`, the `profile_count`, the `exposure_total`,
    and the four status tallies `found_count`, `reappeared_count`, `suppressed_count` and
    `re_suppressed_count`; then `open_removal_count`, the number of that member's removal
    requests in `DRAFTED`, `SUBMITTED`, `ACKNOWLEDGED` or `ESCALATED`, and
    `completed_removal_count`, the number in `COMPLETED`."

    Design: Difficulty/boundary_precision_check/exposure_summary_coverage_ratio_zero_denominator
    """
    household, profile, scan = _member_with_a_profile_but_no_exposures()

    data = validate_success(api.get_exposure_summary(household["owner_id"],
                                                     household["owner"]))

    assert data["member_id"] == household["owner_id"]
    assert data["profile_count"] == 1
    assert data["exposure_total"] == 0
    assert data["found_count"] == 0
    assert data["reappeared_count"] == 0
    assert data["suppressed_count"] == 0
    assert data["re_suppressed_count"] == 0
    assert data["open_removal_count"] == 0
    assert data["completed_removal_count"] == 0

    scan_row = validate_success(api.get_scan_run(scan["id"], fx.ADMIN))
    assert scan_row["findings_count"] == 0
    assert scan_row["new_exposure_count"] == 0
