"""Lost-and-found reports and reciprocal matching (PRD §3.8).

Covers weighted scoring (tag-exact dominance, MATCH_MIN_SCORE gate), the
match/unmatch open cycle, the unmatch compensating reversal, the resolve
cascade, and the no-candidate rejection.
"""
import pytest
from test_helpers import (
    validate_success,
    TEST_USERS,
    set_clock,
    create_report,
    setup_matched_pair,
)

OFFICER = TEST_USERS["officer_headers"]


def test_tag_exact_match_dominates_selection(api):
    """PRD §3.8: "100 points if both reports carry a non-null tag_serial_seen and
    those serials are equal - an exact tag-serial agreement is decisive on its
    own, while species-plus-zip agreement is the next-best signal."
    PRD §3.8: "Among the eligible candidates the winner is the one with the
    highest score".

    Design: Difficulty/combinatorial_formula/lost_found_match_multi_input_nonlinear_selection
    """
    set_clock("2026-03-01T00:00:00Z")
    # F2: species+zip only → score 30. F1: species+zip+tag-exact → score 130.
    f2 = create_report(
        "FOUND", "DOG", zip_seen="30303", reported_at="2026-03-01T08:00:00Z"
    )
    f1 = create_report(
        "FOUND", "DOG", zip_seen="30303", reported_at="2026-03-01T09:00:00Z",
        tag_serial_seen="TAG-XYZ",
    )
    r = create_report(
        "LOST", "DOG", zip_seen="30303", reported_at="2026-03-01T07:00:00Z",
        tag_serial_seen="TAG-XYZ",
    )

    matched = validate_success(api.match_report(r["id"], OFFICER), 200)
    assert matched["matched_report_id"] == f1["id"]
    assert matched["match_score"] == 130

    f1_after = validate_success(api.get_lost_found_report(f1["id"], OFFICER), 200)
    f2_after = validate_success(api.get_lost_found_report(f2["id"], OFFICER), 200)
    assert f1_after["status"] == "MATCHED"
    assert f2_after["status"] == "OPEN"


def test_match_min_score_gate_zip_only_at_boundary(api):
    """PRD §3.8: "Only candidates whose score is at least 20 - the minimum that
    requires at least a ZIP-level agreement - are eligible."
    PRD §3.8: "20 points if the candidate's zip_seen equals this report's
    zip_seen".

    Design: Corner/cross_cutting_complexity_layers/match_min_score_gate_zip_only_at_boundary
    """
    set_clock("2026-03-01T00:00:00Z")
    # CAT vs DOG (species differ) but same zip → score exactly 20, at the gate.
    fb = create_report(
        "FOUND", "CAT", zip_seen="80808", reported_at="2026-03-01T08:00:00Z"
    )
    rb = create_report(
        "LOST", "DOG", zip_seen="80808", reported_at="2026-03-01T07:00:00Z"
    )
    matched = validate_success(api.match_report(rb["id"], OFFICER), 200)
    assert matched["matched_report_id"] == fb["id"]
    assert matched["match_score"] == 20


def test_match_with_no_candidate_returns_no_match_candidate(api):
    """PRD §3.8: "If no candidate reaches that floor, the match fails with
    ERR_NO_MATCH_CANDIDATE."
    PRD §3.8: "10 points if the candidate's species equals this report's species".

    Design: Corner/state_machines/match_with_no_candidate_returns_no_match_candidate
    """
    set_clock("2026-03-01T00:00:00Z")
    # Species match only (DOG/DOG) with differing zips → score 10 < 20.
    create_report("FOUND", "DOG", zip_seen="70000", reported_at="2026-03-01T08:00:00Z")
    rz = create_report(
        "LOST", "DOG", zip_seen="71111", reported_at="2026-03-01T07:00:00Z"
    )
    from test_helpers import validate_error
    res = api.match_report(rz["id"], OFFICER)
    validate_error(res, "ERR_NO_MATCH_CANDIDATE")
    rz_after = validate_success(api.get_lost_found_report(rz["id"], OFFICER), 200)
    assert rz_after["status"] == "OPEN"


def test_unmatch_returns_pair_to_open_cycle(api):
    """PRD §3.8: "A match can be undone: unmatching advances MATCHED -> OPEN,
    requires the report to be MATCHED (ERR_INVALID_STATE), resets this report's
    matched_report_id to null and its match_score to zero, and applies the same
    compensating reversal to the counterpart - returning it to OPEN with its
    matched_report_id nulled and its match_score zeroed - so the pair becomes
    re-matchable."

    Design: Difficulty/non_linear_state_machine/lost_found_match_unmatch_open_cycle
    """
    set_clock("2026-03-01T00:00:00Z")
    lost, found = setup_matched_pair(species="CAT", zip_seen="40404")
    assert lost["status"] == "MATCHED"

    unmatched = validate_success(api.unmatch_report(lost["id"], OFFICER), 200)
    assert unmatched["status"] == "OPEN"
    assert unmatched["matched_report_id"] is None

    found_after = validate_success(api.get_lost_found_report(found["id"], OFFICER), 200)
    assert found_after["status"] == "OPEN"
    assert found_after["matched_report_id"] is None


def test_unmatch_restores_open_report_links_and_scores(api):
    """PRD §3.8: "resets this report's matched_report_id to null and its
    match_score to zero, and applies the same compensating reversal to the
    counterpart - returning it to OPEN with its matched_report_id nulled and its
    match_score zeroed - so the pair becomes re-matchable."

    Design: Difficulty/compensating_invariant/lost_found_unmatch_restores_open_report_count
    """
    set_clock("2026-03-01T00:00:00Z")
    lost, found = setup_matched_pair(species="DOG", zip_seen="55555")

    validate_success(api.unmatch_report(lost["id"], OFFICER), 200)

    lost_after = validate_success(api.get_lost_found_report(lost["id"], OFFICER), 200)
    found_after = validate_success(api.get_lost_found_report(found["id"], OFFICER), 200)
    assert lost_after["status"] == "OPEN"
    assert lost_after["matched_report_id"] is None
    assert lost_after["match_score"] == 0
    assert found_after["status"] == "OPEN"
    assert found_after["matched_report_id"] is None
    assert found_after["match_score"] == 0


def test_resolve_matched_pair_cascades_counterpart(api):
    """PRD §3.8: "A matched pair is resolved together: resolving advances MATCHED
    -> RESOLVED, requires the report to be MATCHED (ERR_INVALID_STATE), and
    cascades the same move onto the matched counterpart, setting its status to
    RESOLVED as well."

    Design: Corner/state_machines/resolve_matched_pair_cascades_counterpart
    """
    set_clock("2026-03-01T00:00:00Z")
    lost, found = setup_matched_pair(species="DOG", zip_seen="66666")

    resolved = validate_success(api.resolve_report(lost["id"], OFFICER), 200)
    assert resolved["status"] == "RESOLVED"

    found_after = validate_success(api.get_lost_found_report(found["id"], OFFICER), 200)
    assert found_after["status"] == "RESOLVED"


def test_match_argmax_picks_highest_species_plus_zip_over_zip_only(api):
    """PRD §3.8: "10 points if the candidate's species equals this report's
    species; 20 points if the candidate's zip_seen equals this report's zip_seen".
    PRD §3.8: "Among the eligible candidates the winner is the one with the
    highest score".

    Companion (no tag-exact path): a species+zip candidate (30) beats a zip-only
    candidate (20); the LOST report matches the 30-scorer and match_score==30.

    Design: Difficulty/combinatorial_formula/lost_found_match_multi_input_nonlinear_selection
    """
    set_clock("2026-03-01T00:00:00Z")
    # Zip-only candidate (CAT, same zip) → 20. Species+zip candidate (DOG) → 30.
    zip_only = create_report(
        "FOUND", "CAT", zip_seen="20202", reported_at="2026-03-01T08:00:00Z"
    )
    best = create_report(
        "FOUND", "DOG", zip_seen="20202", reported_at="2026-03-01T09:00:00Z"
    )
    r = create_report(
        "LOST", "DOG", zip_seen="20202", reported_at="2026-03-01T07:00:00Z"
    )
    matched = validate_success(api.match_report(r["id"], OFFICER), 200)
    assert matched["matched_report_id"] == best["id"]
    assert matched["match_score"] == 30
    zip_only_after = validate_success(
        api.get_lost_found_report(zip_only["id"], OFFICER), 200
    )
    assert zip_only_after["status"] == "OPEN"


def test_unmatched_pair_is_rematchable(api):
    """PRD §3.8: "applies the same compensating reversal to the counterpart -
    returning it to OPEN with its matched_report_id nulled and its match_score
    zeroed - so the pair becomes re-matchable."
    PRD §3.8: "Matching a report advances it OPEN -> MATCHED".

    Companion: the cycle's defining property is re-matchability — after unmatch,
    matching the same report again succeeds and re-links the pair.

    Design: Difficulty/non_linear_state_machine/lost_found_match_unmatch_open_cycle
    """
    set_clock("2026-03-01T00:00:00Z")
    lost, found = setup_matched_pair(species="CAT", zip_seen="41414")
    validate_success(api.unmatch_report(lost["id"], OFFICER), 200)

    # Re-match: the now-OPEN pair matches again.
    rematched = validate_success(api.match_report(lost["id"], OFFICER), 200)
    assert rematched["status"] == "MATCHED"
    assert rematched["matched_report_id"] == found["id"]
    found_after = validate_success(api.get_lost_found_report(found["id"], OFFICER), 200)
    assert found_after["status"] == "MATCHED"


def test_unmatch_restores_both_reports_to_open_status(api):
    """PRD §3.8: "unmatching advances MATCHED -> OPEN ... and applies the same
    compensating reversal to the counterpart - returning it to OPEN".

    Companion (status-conservation facet): the open-count of the pool is restored
    — both reports, removed from OPEN by the match, are returned to OPEN by the
    unmatch.

    Design: Difficulty/compensating_invariant/lost_found_unmatch_restores_open_report_count
    """
    set_clock("2026-03-01T00:00:00Z")
    lost, found = setup_matched_pair(species="DOG", zip_seen="51515")
    # Both are MATCHED after setup; the unmatch must return both to OPEN.
    validate_success(api.unmatch_report(found["id"], OFFICER), 200)

    lost_after = validate_success(api.get_lost_found_report(lost["id"], OFFICER), 200)
    found_after = validate_success(api.get_lost_found_report(found["id"], OFFICER), 200)
    assert lost_after["status"] == "OPEN"
    assert found_after["status"] == "OPEN"
