"""Priority-pair tests for the three collisions the PRD works out explicitly.

PRD 2.5 fixes a global evaluation order and then pins three worked collisions:
the engagement-quality-review window check over cooling-off, referential
consistency over the fiscal band, and the reviewer window check over the
capacity check.  Each test stages both violations on one request and pins the
single error_id the ladder produces.
"""
from typing import Any, Dict

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.assertions import assert_fields, read_entity
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.test_users import make_committee_headers, make_peer_reviewer_headers

COMMITTEE = make_committee_headers()


def _single_error(response, expected_error_id: str, expected_status: int) -> None:
    """One error_id and nothing else: the envelope never carries two failures."""
    error_data = validate_error(response, expected_error_id, expected_status)
    assert sorted(error_data) == ["error_id", "message"], (
        f"error body must carry exactly one error_id, got keys {sorted(error_data)}"
    )
    assert isinstance(error_data["error_id"], str)


def _rows(response) -> Dict[str, Any]:
    validate_success(response)
    return response.json()


# ---------------------------------------------------------------------------
# Pair 1 - the EQR window state check outranks the cooling-off safety check
# ---------------------------------------------------------------------------
def _stage_released_engagement_and_hot_reviewer(api) -> Dict[str, Any]:
    """A REPORT_RELEASED engagement plus a candidate reviewer who left that same
    client's engagement team only 400 days before its period_end."""
    fixtures.set_clock(api, DEFAULT_CLOCK)
    ctx = fixtures.firm_context(api, legal_name="Merrow Fen LLP")
    reviewer = fixtures.add_eq_reviewer(
        api,
        ctx,
        full_name="Sable Ord",
        prior_engagement_team_clients=[
            {"client_name": "Kite Co", "exit_date": "2023-05-27"}
        ],
    )
    engagement = fixtures.released_engagement(
        api,
        ctx,
        client_name="Kite Co",
        engagement_type="AUDIT",
        period_end="2024-06-30",
    )
    assert engagement["workflow_state"] == "REPORT_RELEASED"
    return {"ctx": ctx, "reviewer": reviewer, "engagement": engagement}


def _attempt_assignment(api, ctx, engagement: Dict[str, Any], reviewer_id: str):
    current = read_entity(
        api.get_engagement(engagement["id"], headers=ctx["qc_headers"])
    )
    return api.assign_quality_review(
        engagement["id"],
        f.quality_review_assignment_payload(reviewer_id, current["version"]),
        headers=ctx["qc_headers"],
    )


def test_eqr_window_state_check_beats_cooling_off_on_a_released_engagement(api):
    """Assigning a reviewer whose cooling-off is short to an engagement already
    past its review window returns the window error, not the cooling-off error.

    "When an engagement quality reviewer is assigned to an engagement that has
    already reached REPORT_RELEASED and the candidate reviewer's separation from
    the client's engagement team falls short of the cooling-off requirement, the
    response is ERR_ENGAGEMENT_NOT_IN_EQR_WINDOW, because the target-state
    precondition outranks the independence-and-objectivity band."

    Design: Difficulty/priority_pair_validation_conflict/eqr_window_state_check_outranks_cooling_off_safety_check
    """
    world = _stage_released_engagement_and_hot_reviewer(api)

    response = _attempt_assignment(
        api, world["ctx"], world["engagement"], world["reviewer"]["id"]
    )
    _single_error(response, E.ERR_ENGAGEMENT_NOT_IN_EQR_WINDOW, 409)
    assert response.json()["data"]["error_id"] != E.ERR_COOLING_OFF_NOT_MET


def test_eqr_window_refusal_creates_no_review_row_and_leaves_the_engagement(api):
    """The refused assignment is atomic: no quality review exists, the engagement
    keeps its released state and the candidate's open review count stays 0.

    "The engagement must be inside its review window - workflow_state in FIELDWORK
    or EQR_PENDING - otherwise the request is refused with
    ERR_ENGAGEMENT_NOT_IN_EQR_WINDOW."

    Design: Difficulty/priority_pair_validation_conflict/eqr_window_state_check_outranks_cooling_off_safety_check
    """
    world = _stage_released_engagement_and_hot_reviewer(api)
    ctx = world["ctx"]

    response = _attempt_assignment(
        api, ctx, world["engagement"], world["reviewer"]["id"]
    )
    validate_error(response, E.ERR_ENGAGEMENT_NOT_IN_EQR_WINDOW, 409)

    listing = _rows(
        api.list_quality_reviews(
            headers=ctx["qc_headers"],
            params={"engagement_id": world["engagement"]["id"]},
        )
    )
    assert listing["meta"]["total_count"] == 0, (
        f"expected 0 quality reviews, got {listing['meta']['total_count']}"
    )
    assert listing["data"] == []

    engagement = read_entity(
        api.get_engagement(world["engagement"]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(engagement, workflow_state="REPORT_RELEASED")
    assert engagement["eqr_concurred_at"] is None

    reviewer = read_entity(
        api.get_partner(world["reviewer"]["id"], headers=ctx["qc_headers"])
    )
    assert reviewer["open_eqr_count"] == 0


def test_cooling_off_error_surfaces_once_the_engagement_sits_in_its_window(api):
    """With the window violation removed, the loser of the pair is the error the
    same candidate now draws: the cooling-off refusal.

    "the server looks through the candidate's prior_engagement_team_clients for an
    entry whose client_name matches the engagement's client_name ... that
    separation must be at least 730 days ... refusing with
    ERR_COOLING_OFF_NOT_MET."

    Design: Difficulty/priority_pair_validation_conflict/eqr_window_state_check_outranks_cooling_off_safety_check
    """
    world = _stage_released_engagement_and_hot_reviewer(api)
    ctx = world["ctx"]

    in_window = fixtures.new_engagement(
        api,
        ctx,
        client_name="Kite Co",
        engagement_type="AUDIT",
        period_end="2024-06-29",
    )
    fixtures.workflow_step(api, in_window, "FIELDWORK", ctx["ep_headers"])

    response = _attempt_assignment(api, ctx, in_window, world["reviewer"]["id"])
    _single_error(response, E.ERR_COOLING_OFF_NOT_MET, 409)

    listing = _rows(
        api.list_quality_reviews(
            headers=ctx["qc_headers"], params={"engagement_id": in_window["id"]}
        )
    )
    assert listing["meta"]["total_count"] == 0


# ---------------------------------------------------------------------------
# Pair 2 - referential consistency outranks the fiscal scope-hours check
# ---------------------------------------------------------------------------
def _stage_cross_firm_peer_review_world(api) -> Dict[str, Any]:
    """Firm A's scoped 16-hour peer review, plus an engagement owned by firm B."""
    fixtures.set_clock(api, DEFAULT_CLOCK)
    firm_a = fixtures.new_firm(api, legal_name="Norwell Ash LLP")
    partner_a = fixtures.new_partner(
        api, firm_a["id"], full_name="Nia Wren", designations=["ENGAGEMENT_PARTNER"]
    )
    reviewer = fixtures.new_peer_reviewer(
        api,
        reviewer_firm_name="Kestrel Peer Review PC",
        license_state="CA",
        qualified_categories=[],
        max_concurrent_reviews=2,
        experience_hours=5000,
    )
    review = fixtures.new_peer_review(
        api,
        firm_a["id"],
        review_type="SYSTEM_REVIEW",
        year_end="2026-12-31",
        scheduled_window_start="2026-09-01",
        scheduled_window_end="2026-09-15",
    )
    fixtures.assign_reviewer(api, review["id"], reviewer["id"])
    scoped = fixtures.set_scope(api, review["id"], reviewer["id"])
    assert scoped["must_select_categories"] == []

    firm_b = fixtures.new_firm(api, legal_name="Osier Ridge LLP")
    partner_b = fixtures.new_partner(
        api, firm_b["id"], full_name="Tarn Wilde", designations=["ENGAGEMENT_PARTNER"]
    )
    engagement_b = fixtures.new_engagement(
        api,
        {"firm_id": firm_b["id"], "ep": partner_b},
        client_name="Pell Textiles",
        engagement_type="AUDIT",
        period_end="2024-06-30",
    )
    return {
        "firm_a": firm_a,
        "partner_a": partner_a,
        "reviewer": reviewer,
        "review": scoped,
        "engagement_b": engagement_b,
        "reviewer_headers": make_peer_reviewer_headers(reviewer["id"]),
    }


def _attempt_selection(api, world, engagement_id: str, hours: int):
    review = read_entity(
        api.get_peer_review(world["review"]["id"], headers=world["reviewer_headers"])
    )
    return api.create_peer_review_selection(
        world["review"]["id"],
        f.peer_review_selection_payload(engagement_id, review["version"], hours),
        headers=world["reviewer_headers"],
    )


def test_selection_firm_mismatch_beats_the_scope_hours_fiscal_check(api):
    """Committing another firm's engagement with more hours than the review holds
    returns the firm-mismatch error, never the fiscal scope-hours error.

    "When a peer review selection names an engagement belonging to a different firm
    and commits more hours than the review has left, the response is
    ERR_ENGAGEMENT_FIRM_MISMATCH, because referential consistency outranks the
    fiscal band."

    Design: Difficulty/priority_pair_validation_conflict/selection_firm_mismatch_referential_check_outranks_scope_hours_fiscal_check
    """
    world = _stage_cross_firm_peer_review_world(api)

    response = _attempt_selection(api, world, world["engagement_b"]["id"], 200)
    _single_error(response, E.ERR_ENGAGEMENT_FIRM_MISMATCH, 409)
    assert response.json()["data"]["error_id"] != E.ERR_SCOPE_HOURS_EXCEEDED


def test_selection_firm_mismatch_refusal_commits_no_hours_anywhere(api):
    """The refused commit leaves the hours-conservation invariant untouched: the
    review keeps all 16 unallocated hours and the reviewer's balance stays 0.

    "at every instant the review's total_scope_hours equals its unallocated_hours
    plus the sum of hours_committed across its committed selections."

    Design: Difficulty/priority_pair_validation_conflict/selection_firm_mismatch_referential_check_outranks_scope_hours_fiscal_check
    """
    world = _stage_cross_firm_peer_review_world(api)

    response = _attempt_selection(api, world, world["engagement_b"]["id"], 200)
    validate_error(response, E.ERR_ENGAGEMENT_FIRM_MISMATCH, 409)

    review = read_entity(
        api.get_peer_review(world["review"]["id"], headers=COMMITTEE)
    )
    assert_fields(review, total_scope_hours=16, unallocated_hours=16, state="SCOPE_SET")

    listing = _rows(
        api.list_peer_review_selections(
            headers=COMMITTEE, params={"peer_review_id": world["review"]["id"]}
        )
    )
    assert listing["meta"]["total_count"] == 0, (
        f"expected 0 selections, got {listing['meta']['total_count']}"
    )
    assert listing["data"] == []

    reviewer = read_entity(
        api.get_peer_reviewer(world["reviewer"]["id"], headers=COMMITTEE)
    )
    assert reviewer["committed_hours_balance"] == 0


def test_scope_hours_error_surfaces_once_the_engagement_belongs_to_the_firm(api):
    """With the referential violation removed, the loser of the pair is the error
    the same 200-hour commit now draws: the fiscal scope-hours refusal.

    "hours_committed may not exceed the review's remaining unallocated_hours,
    otherwise ERR_SCOPE_HOURS_EXCEEDED - the fiscal check that runs last of all."

    Design: Difficulty/priority_pair_validation_conflict/selection_firm_mismatch_referential_check_outranks_scope_hours_fiscal_check
    """
    world = _stage_cross_firm_peer_review_world(api)

    own_engagement = fixtures.new_engagement(
        api,
        {"firm_id": world["firm_a"]["id"], "ep": world["partner_a"]},
        client_name="Quill Dairy",
        engagement_type="AUDIT",
        period_end="2024-06-30",
    )

    response = _attempt_selection(api, world, own_engagement["id"], 200)
    _single_error(response, E.ERR_SCOPE_HOURS_EXCEEDED, 409)

    review = read_entity(api.get_peer_review(world["review"]["id"], headers=COMMITTEE))
    assert_fields(review, unallocated_hours=16, state="SCOPE_SET")


# ---------------------------------------------------------------------------
# Pair 3 - the buffered window check outranks the concurrent-review ceiling
# ---------------------------------------------------------------------------
def _stage_window_and_capacity_conflict_world(api) -> Dict[str, Any]:
    """A reviewer capped at one review already holds a 2026-09-01..09-15 review,
    and a second review opens on 2026-09-16 - inside the 5-day travel buffer."""
    fixtures.set_clock(api, DEFAULT_CLOCK)
    firm = fixtures.new_firm(api, legal_name="Pentland Row LLP")
    reviewer = fixtures.new_peer_reviewer(
        api,
        reviewer_firm_name="Kestrel Peer Review PC",
        license_state="CA",
        accepts_out_of_state=False,
        qualified_categories=[],
        max_concurrent_reviews=1,
        experience_hours=5000,
    )
    review_one = fixtures.new_peer_review(
        api,
        firm["id"],
        review_type="SYSTEM_REVIEW",
        year_end="2025-12-31",
        scheduled_window_start="2026-09-01",
        scheduled_window_end="2026-09-15",
    )
    assigned = fixtures.assign_reviewer(api, review_one["id"], reviewer["id"])
    assert assigned["state"] == "PLANNING"
    review_two = fixtures.new_peer_review(
        api,
        firm["id"],
        review_type="SYSTEM_REVIEW",
        year_end="2026-12-31",
        scheduled_window_start="2026-09-16",
        scheduled_window_end="2026-09-30",
    )
    return {
        "firm": firm,
        "reviewer": reviewer,
        "review_one": review_one,
        "review_two": review_two,
    }


def _attempt_reviewer_assignment(api, peer_review_id: str, reviewer_id: str):
    return api.assign_peer_reviewer(
        peer_review_id, f.reviewer_assignment_payload(reviewer_id), headers=COMMITTEE
    )


def test_reviewer_window_conflict_beats_the_concurrent_capacity_ceiling(api):
    """Naming a reviewer who is both window-conflicted and at their concurrent
    ceiling returns the window error, never the capacity error.

    "When a named peer reviewer both has a colliding on-site window and is already
    at their concurrent-review ceiling, the response is
    ERR_REVIEWER_WINDOW_CONFLICT, because the temporal-window check is evaluated
    ahead of the capacity check."

    Design: Difficulty/priority_pair_validation_conflict/reviewer_window_conflict_temporal_check_outranks_capacity_constraint_check
    """
    world = _stage_window_and_capacity_conflict_world(api)

    response = _attempt_reviewer_assignment(
        api, world["review_two"]["id"], world["reviewer"]["id"]
    )
    _single_error(response, E.ERR_REVIEWER_WINDOW_CONFLICT, 409)
    assert response.json()["data"]["error_id"] != E.ERR_REVIEWER_AT_CAPACITY


def test_reviewer_window_conflict_leaves_the_second_review_unassigned(api):
    """The refused assignment changes nothing: the second review stays SCHEDULED
    with no reviewer, and the roster counters and firm flag are untouched.

    "If no candidate survives the filter, the review stays in SCHEDULED, the firm's
    unassigned_review_flag is set true" - which is the empty-pool path, not this
    named-candidate refusal, and the earlier successful assignment already cleared
    the flag.

    Design: Difficulty/priority_pair_validation_conflict/reviewer_window_conflict_temporal_check_outranks_capacity_constraint_check
    """
    world = _stage_window_and_capacity_conflict_world(api)

    response = _attempt_reviewer_assignment(
        api, world["review_two"]["id"], world["reviewer"]["id"]
    )
    validate_error(response, E.ERR_REVIEWER_WINDOW_CONFLICT, 409)

    review_two = read_entity(
        api.get_peer_review(world["review_two"]["id"], headers=COMMITTEE)
    )
    assert_fields(review_two, state="SCHEDULED")
    assert review_two["assigned_reviewer_id"] is None

    reviewer = read_entity(
        api.get_peer_reviewer(world["reviewer"]["id"], headers=COMMITTEE)
    )
    assert reviewer["active_review_count"] == 1

    review_one = read_entity(
        api.get_peer_review(world["review_one"]["id"], headers=COMMITTEE)
    )
    assert review_one["assigned_reviewer_id"] == world["reviewer"]["id"]

    firm = read_entity(api.get_firm(world["firm"]["id"], headers=COMMITTEE))
    assert firm["unassigned_review_flag"] is False


def test_reviewer_capacity_error_surfaces_once_the_windows_no_longer_collide(api):
    """With the window collision removed, the loser of the pair is the error the
    same named reviewer now draws: the concurrent-review ceiling.

    "A new window starting exactly on an existing window's end date therefore
    collides, while one starting exactly 5 days after that end date does not."

    Design: Difficulty/priority_pair_validation_conflict/reviewer_window_conflict_temporal_check_outranks_capacity_constraint_check
    """
    world = _stage_window_and_capacity_conflict_world(api)

    clear_window = fixtures.new_peer_review(
        api,
        world["firm"]["id"],
        review_type="SYSTEM_REVIEW",
        year_end="2026-12-31",
        scheduled_window_start="2026-09-20",
        scheduled_window_end="2026-10-05",
    )

    response = _attempt_reviewer_assignment(
        api, clear_window["id"], world["reviewer"]["id"]
    )
    _single_error(response, E.ERR_REVIEWER_AT_CAPACITY, 409)

    review = read_entity(api.get_peer_review(clear_window["id"], headers=COMMITTEE))
    assert_fields(review, state="SCHEDULED")
    assert review["assigned_reviewer_id"] is None
