"""Two-way call-up stint overlap geometry and sponsorship distribution OCC.

Covers difficulty queue: resource_temporal_overlap (stint half-open adjacency allowed),
optimistic_concurrency (sponsorship distribute stale version); and corner sponsorship
idempotency cases.
"""
from test_helpers import (
    validate_success, validate_error,
    create_season, create_team, create_player, sign_contract,
    create_stint_payload, create_sponsorship, distribute_sponsorship,
    setup_single_team_sponsorship,
    make_team_gm_headers, TEST_USERS,
)

COMMISH = TEST_USERS["commissioner_headers"]


def _two_way_contract():
    season = create_season()
    team = create_team(season["id"], name="T", market_size_weight=1)
    p = create_player(season["id"], handle="p")
    c = sign_contract(team["id"], p["id"], base_salary_cents=4_000_000, contract_type="TWO_WAY")
    return season, team, c


def test_stint_adjacency_allowed(api):
    """PRD §3.5: "Because the interval is half-open, adjacency is explicitly allowed — a
    new stint whose starts_at equals an existing stint's ends_at, or whose ends_at
    equals an existing stint's starts_at, does not overlap and is accepted."

    Design: Difficulty/resource_temporal_overlap/stint_half_open_interval_adjacency_allowed
    """
    season, team, c = _two_way_contract()
    gm = make_team_gm_headers(team["id"])
    validate_success(api.create_stint(
        create_stint_payload(c["id"], starts_at="2026-03-01T00:00:00.000Z",
                             ends_at="2026-03-10T00:00:00.000Z"), gm), 201)
    res = api.create_stint(
        create_stint_payload(c["id"], starts_at="2026-03-10T00:00:00.000Z",
                             ends_at="2026-03-20T00:00:00.000Z"), gm)
    stint2 = validate_success(res, 201)
    assert stint2["starts_at"] == "2026-03-10T00:00:00.000Z"


def test_stint_overlap_rejected(api):
    """PRD §3.5: "The check treats each stint as the half-open interval [starts_at,
    ends_at): a new stint is rejected with ERR_STINT_OVERLAP (HTTP 409) if its interval
    overlaps any existing stint for the same player_id."

    Design: Difficulty/resource_temporal_overlap/stint_half_open_interval_adjacency_allowed
    """
    season, team, c = _two_way_contract()
    gm = make_team_gm_headers(team["id"])
    validate_success(api.create_stint(
        create_stint_payload(c["id"], starts_at="2026-03-01T00:00:00.000Z",
                             ends_at="2026-03-10T00:00:00.000Z"), gm), 201)
    # New stint starts strictly inside the existing interval → overlap.
    res = api.create_stint(
        create_stint_payload(c["id"], starts_at="2026-03-05T00:00:00.000Z",
                             ends_at="2026-03-15T00:00:00.000Z"), gm)
    validate_error(res, "ERR_STINT_OVERLAP")


def test_distribute_stale_sponsorship_version_rejected(api):
    """PRD §2.7: "If the sponsorship's pool or league share was edited and its version
    advanced after the commissioner read it, the distribute is rejected with
    ERR_STALE_VERSION (HTTP 412), so the payout is never computed against an
    out-of-date pool."

    Carrying expected_sponsorship_version one below the current version is stale.

    Design: Difficulty/optimistic_concurrency/sponsorship_distribute_stale_version_rejected
    """
    season, team, spo = setup_single_team_sponsorship(weight=1)
    res = api.distribute_sponsorship(
        spo["id"], {"expected_sponsorship_version": spo["version"] - 1}, COMMISH)
    validate_error(res, "ERR_STALE_VERSION")


def test_distribute_stale_leaves_sponsorship_pending(api):
    """PRD §2.7: "the distribute is rejected with ERR_STALE_VERSION (HTTP 412), so the
    payout is never computed against an out-of-date pool."
    PRD §3.9: "Distributing the pool moves the sponsorship from PENDING to DISTRIBUTED".

    Design: Difficulty/optimistic_concurrency/sponsorship_distribute_stale_version_rejected
    """
    season, team, spo = setup_single_team_sponsorship(weight=1)
    res = api.distribute_sponsorship(
        spo["id"], {"expected_sponsorship_version": spo["version"] - 1}, COMMISH)
    validate_error(res, "ERR_STALE_VERSION")
    s = validate_success(api.get_sponsorship(spo["id"], COMMISH), 200)
    assert s["status"] == "PENDING"


def test_distribute_already_distributed_returns_invalid_state(api):
    """PRD §3.9: "Distribution requires the sponsorship to be PENDING, else
    ERR_INVALID_STATE (HTTP 409)".

    Design: Corner/state_machines/distribute_already_distributed_sponsorship_returns_invalid_state
    """
    season = create_season()
    team = create_team(season["id"], name="A", market_size_weight=1)
    spo = create_sponsorship(season["id"], pool_cents=10_000_000, league_share_pct=0.40)
    first = validate_success(distribute_sponsorship(spo), 200)
    res = api.distribute_sponsorship(
        spo["id"], {"expected_sponsorship_version": first["version"]}, COMMISH)
    validate_error(res, "ERR_INVALID_STATE")
