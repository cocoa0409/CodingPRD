"""Leagues, registrations and season lockers: the league-cancel cascade to
registrations and lockers, half-open locker-interval overlap, locker-unit
conservation, roster capacity, the registration-state gate, and ownership."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    make_skater_headers,
    create_rink, create_skater, create_funded_skater, create_league,
    register_skater, assign_locker, setup_locker_holder,
)

RM = TEST_USERS["rink_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/locker_season_half_open_overlap
# ---------------------------------------------------------------------------
def test_locker_overlapping_season_range_rejected(api):
    """PRD §3.5: "the requested `[season_start_date, season_end_date)` half-open
    interval must not overlap any existing `ACTIVE` assignment's interval.
    Adjacency is allowed — if an existing assignment ends exactly on the requested
    start date, there is no overlap — but any true overlap is rejected with
    `ERR_LOCKER_OCCUPIED`."

    Design: Difficulty/resource_temporal_overlap/locker_season_half_open_overlap
    """
    setup = setup_locker_holder(api, locker_fee_cents=0, locker_number=1,
                                season_start_date="2026-06-01",
                                season_end_date="2026-09-01")
    sk = setup["skater"]
    resp = api.create_locker_assignment(
        setup["rink"]["id"],
        {"skater_id": sk["id"], "locker_number": 1,
         "season_start_date": "2026-08-01", "season_end_date": "2026-10-01"},
        make_skater_headers(sk["id"]))
    validate_error(resp, ApiErrorId.ERR_LOCKER_OCCUPIED.value)


def test_locker_adjacent_season_range_allowed(api):
    """PRD §3.5: "Adjacency is allowed — if an existing assignment ends exactly on
    the requested start date, there is no overlap".

    Design: Difficulty/resource_temporal_overlap/locker_season_half_open_overlap
    """
    setup = setup_locker_holder(api, locker_fee_cents=0, locker_number=1,
                                season_start_date="2026-06-01",
                                season_end_date="2026-09-01")
    sk = setup["skater"]
    # Requested start == existing end (2026-09-01) -> no overlap.
    data = validate_success(api.create_locker_assignment(
        setup["rink"]["id"],
        {"skater_id": sk["id"], "locker_number": 1,
         "season_start_date": "2026-09-01", "season_end_date": "2026-11-01"},
        make_skater_headers(sk["id"])), 201)
    assert data["status"] == "ACTIVE", f"adjacent assignment expected ACTIVE, got {data['status']}"


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/locker_units_conserved_across_assign_and_release
# ---------------------------------------------------------------------------
def test_release_returns_locker_to_released(api):
    """PRD §3.5: "Releasing a locker ... moves the assignment from `ACTIVE` to
    `RELEASED`, recomputes the rink's available-locker figure so that this locker
    number frees up, and increments `version`."

    Design: Difficulty/compensating_invariant/locker_units_conserved_across_assign_and_release
    """
    setup = setup_locker_holder(api, locker_fee_cents=2000)
    data = validate_success(api.release_locker(
        setup["locker"]["id"], make_skater_headers(setup["skater"]["id"])))
    assert data["status"] == "RELEASED", f"expected RELEASED, got {data['status']}"


def test_locker_units_conserved_across_release(api):
    """PRD §3.5: "A rink's `available_lockers` equals its `locker_count` minus the
    number of distinct `locker_number` values among that rink's `ACTIVE` locker
    assignments."

    Design: Difficulty/compensating_invariant/locker_units_conserved_across_assign_and_release
    """
    setup = setup_locker_holder(api, locker_fee_cents=2000)
    # Before release: 1 locker occupied -> available 2 (2 + 1 == locker_count 3).
    rink = validate_success(api.get_rink(setup["rink"]["id"], RM))
    assert rink["available_lockers"] + 1 == 3, (
        f"one locker occupied; available+occupied must equal 3, got {rink['available_lockers']}")
    validate_success(api.release_locker(
        setup["locker"]["id"], make_skater_headers(setup["skater"]["id"])))
    rink = validate_success(api.get_rink(setup["rink"]["id"], RM))
    assert rink["available_lockers"] == 3, (
        f"after release all 3 lockers free, got {rink['available_lockers']}")


# ---------------------------------------------------------------------------
# Corner/validations/league_roster_full_returns_capacity_full
# ---------------------------------------------------------------------------
def test_registration_beyond_roster_capacity_rejected(api):
    """PRD §3.5: "Registration is capped by the roster: it is allowed only while
    `roster_count` is strictly below `roster_capacity`, and a full roster yields
    `ERR_CAPACITY_FULL`."

    Design: Corner/validations/league_roster_full_returns_capacity_full
    """
    league = create_league(api, name="Solo", sport="FIGURE", roster_capacity=1)
    s1 = create_skater(api, "roster1@x.com")
    s2 = create_skater(api, "roster2@x.com")
    register_skater(api, league["id"], s1["id"], as_skater_id=s1["id"])
    resp = api.create_registration(league["id"], {"skater_id": s2["id"]},
                                   make_skater_headers(s2["id"]))
    validate_error(resp, ApiErrorId.ERR_CAPACITY_FULL.value)


# ---------------------------------------------------------------------------
# Corner/validations/register_on_in_season_league_returns_invalid_state
# ---------------------------------------------------------------------------
def test_register_on_in_season_league_rejected(api):
    """PRD §3.5: "Registering a skater is a `Skater` or `RinkManager` action against
    a league that must still be in `REGISTRATION_OPEN`; registering on an
    `IN_SEASON` or `CANCELLED` league yields `ERR_INVALID_STATE`."

    Design: Corner/validations/register_on_in_season_league_returns_invalid_state
    """
    league = create_league(api, name="Started")
    validate_success(api.start_league(league["id"], RM))
    sk = create_skater(api, "late@x.com")
    resp = api.create_registration(league["id"], {"skater_id": sk["id"]},
                                   make_skater_headers(sk["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Corner/rbac/skater_cannot_release_other_skaters_locker
# ---------------------------------------------------------------------------
def test_skater_cannot_release_another_skaters_locker(api):
    """PRD §2.1: "A `Skater` who attempts to act on a resource whose `skater_id`
    is not their own is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/skater_cannot_release_other_skaters_locker
    """
    rink = create_rink(api, locker_fee_cents=0)
    sk_a = create_funded_skater(api, "owna@x.com", 100000)
    sk_b = create_skater(api, "ownb@x.com")
    la = assign_locker(api, rink["id"], sk_a["id"], 1, "2026-06-01", "2026-09-01",
                       as_skater_id=sk_a["id"])
    resp = api.release_locker(la["id"], make_skater_headers(sk_b["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
