"""Two interval regimes that must not be confused: closed player-assignment
windows carrying a positive transfer buffer, and half-open staff windows whose
only aggregate constraint is a committed-time cap.
"""

from test_helpers import (
    FARM_DIRECTOR_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_integer,
    assert_status,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def _create_assignment(
    api: ApiClient, player_id: str, affiliate_id: str, expected_player_version: int, **overrides
):
    """Raw create call, so a refusal can be inspected rather than raised."""
    return api.create_assignment(
        factories.assignment_payload(
            player_id, affiliate_id, expected_player_version, **overrides
        ),
        FARM_DIRECTOR_HEADERS,
    )


# ---------------------------------------------------------------------------
# Instance 1 — closed assignment windows need a genuine transfer buffer
# ---------------------------------------------------------------------------


def _cardinals_club_with_an_april_window(api: ApiClient) -> dict:
    """A cleared player holding one pending April window at a DOUBLE_A club."""
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Springfield Cardinals",
            "level": "DOUBLE_A",
            "market_city": "Springfield",
            "meal_stipend_cents_per_day": 3000,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_1",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    pending = fixtures.pending_assignment(
        api,
        club["affiliate_id"],
        player_overrides={
            "full_name": "Elias Thorne",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2024-06-10",
            "service_days_accrued": 200,
        },
        effective_date="2026-04-01",
        end_date="2026-04-30",
    )
    club.update(pending)
    return club


def test_a_two_day_gap_after_the_prior_end_date_is_refused(api: ApiClient):
    """A gap of exactly two days is inside the buffer, so the create fails.

    PRD 3.6: "Second, the server measures the gap in whole days from the prior
    row's `end_date` to the new row's `effective_date`; if that gap is positive
    but no greater than two days, the creation is again refused with
    `ERR_ASSIGNMENT_WINDOW_CONFLICT`."  The prior row here is only
    `PENDING_CLEARANCE`, and PRD 3.6 still counts it: "For the new row the
    server examines every other assignment of the same player that is in status
    `PENDING_CLEARANCE`, `ACTIVE` or `SUSPENDED` and whose type is `LEVEL` or
    `COMPLEX`."  Because the write is refused it must leave the player's
    `version` exactly where it was.

    Design: Difficulty/resource_temporal_overlap/player_assignment_windows_require_three_day_transfer_gap_on_closed_intervals
    """
    club = _cardinals_club_with_an_april_window(api)

    version_before = fixtures.player_version(api, club["player_id"])
    refused = _create_assignment(
        api,
        club["player_id"],
        club["affiliate_id"],
        version_before,
        movement_reason="LATERAL",
        effective_date="2026-05-02",
        end_date="2026-06-30",
    )
    validate_error(refused, ApiErrorId.ERR_ASSIGNMENT_WINDOW_CONFLICT.value, 409)

    version_after = fixtures.player_version(api, club["player_id"])
    assert_integer(version_after, version_before, "Player.version")
    assert_status(
        fixtures.read_assignment(api, club["assignment_id"]),
        "PENDING_CLEARANCE",
        "PlayerAssignment",
    )


def test_a_three_day_gap_is_admitted_and_projects_its_own_optional_days(api: ApiClient):
    """One day later the same window clears the buffer and is persisted.

    PRD 3.6: "In other words, a player leaving a club needs a genuine transfer
    buffer: the gap between the old end date and the new start date must be
    strictly greater than two days, so at least three."  The accepted row prices
    its own window, since PRD 3.6 also fixes that "`projected_optional_days` is
    computed as the number of days from `effective_date` to `end_date` plus one,
    so a single-day assignment projects one optional day and a thirty-day window
    projects thirty" — 2026-05-03 through 2026-06-30 is 59 days.  The refused
    two-day attempt left no row behind, so the player ends with two assignments.

    Design: Difficulty/resource_temporal_overlap/player_assignment_windows_require_three_day_transfer_gap_on_closed_intervals
    """
    club = _cardinals_club_with_an_april_window(api)
    validate_error(
        _create_assignment(
            api,
            club["player_id"],
            club["affiliate_id"],
            fixtures.player_version(api, club["player_id"]),
            movement_reason="LATERAL",
            effective_date="2026-05-02",
            end_date="2026-06-30",
        ),
        ApiErrorId.ERR_ASSIGNMENT_WINDOW_CONFLICT.value,
        409,
    )

    accepted = validate_success(
        _create_assignment(
            api,
            club["player_id"],
            club["affiliate_id"],
            fixtures.player_version(api, club["player_id"]),
            movement_reason="LATERAL",
            effective_date="2026-05-03",
            end_date="2026-06-30",
        ),
        201,
    )
    assert_status(accepted, "PENDING_CLEARANCE", "PlayerAssignment")
    assert_integer(accepted["projected_optional_days"], 59, "projected_optional_days")

    rows, meta = validate_paginated(
        api.list_assignments(FARM_DIRECTOR_HEADERS, {"player_id": club["player_id"]})
    )
    assert_integer(meta["total_count"], 2, "assignment total_count")
    assert {row["effective_date"] for row in rows} == {"2026-04-01", "2026-05-03"}, (
        f"only the April window and the accepted May window may exist, got {rows}"
    )


# ---------------------------------------------------------------------------
# Instance 2 — half-open staff windows: adjacency is free, the sum is capped
# ---------------------------------------------------------------------------


def _create_allocation(
    api: ApiClient, staff_member_id: str, affiliate_id: str, expected_affiliate_version: int, **overrides
):
    """Raw propose call, so a refusal can be inspected rather than raised."""
    return api.create_staff_allocation(
        factories.staff_allocation_payload(
            staff_member_id, affiliate_id, expected_affiliate_version, **overrides
        ),
        FARM_DIRECTOR_HEADERS,
    )


def _two_clubs_and_a_coach_committed_sixty_percent(api: ApiClient) -> dict:
    """A coach 60% committed to club A over the half-open spring window."""
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    agreement_overrides = {
        "facility_standard_tier": "TIER_2",
        "club_reimbursement_cap_cents": 900000,
        "minimum_active_players": 0,
    }
    club_a = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Lansing Lugnuts",
            "level": "HIGH_A",
            "market_city": "Lansing",
            "meal_stipend_cents_per_day": 2800,
        },
        agreement_overrides=dict(agreement_overrides),
    )
    club_b = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Modesto Nuts",
            "level": "SINGLE_A",
            "market_city": "Modesto",
            "meal_stipend_cents_per_day": 2700,
        },
        agreement_overrides=dict(agreement_overrides),
    )
    member = fixtures.create_staff_member(
        api,
        full_name="Coach Imani Reed",
        discipline="PITCHING",
        curriculum_version_certified="2026.1",
        certification_expires_on="2027-01-31",
    )
    allocation_a = fixtures.create_allocation(
        api,
        member["id"],
        club_a["affiliate_id"],
        staff_role="PITCHING_COACH",
        fte_pct=60,
        effective_start="2026-04-01",
        effective_end="2026-07-01",
        curriculum_version="2026.1",
    )
    activated = fixtures.dispose_allocation(api, allocation_a["id"], "ACTIVATE")
    return {
        "affiliate_a_id": club_a["affiliate_id"],
        "affiliate_b_id": club_b["affiliate_id"],
        "staff_member_id": member["id"],
        "allocation_a_id": allocation_a["id"],
        "allocation_a": activated,
    }


def test_an_overlapping_window_pushes_the_aggregate_commitment_over_the_cap(api: ApiClient):
    """Sixty plus fifty across two different clubs breaches the single cap.

    PRD 3.4: "The server gathers the member's allocations that are in status
    `ACTIVE` and whose half-open intervals genuinely overlap the interval under
    consideration — that is, whose own start falls before the candidate's end and
    whose own end falls after the candidate's start — sums their `fte_pct`, adds
    the candidate's `fte_pct`, and refuses with `ERR_STAFF_FTE_OVERCOMMITTED` if
    that total exceeds 100."  The candidate window [2026-06-01, 2026-09-01)
    genuinely overlaps the active [2026-04-01, 2026-07-01), so 60 + 50 is
    refused, and the refused create must not bump the affiliate it named.

    Design: Difficulty/resource_temporal_overlap/staff_allocation_half_open_intervals_allow_adjacency_but_cap_aggregate_fte
    """
    bundle = _two_clubs_and_a_coach_committed_sixty_percent(api)
    assert_status(bundle["allocation_a"], "ACTIVE", "StaffAllocation")

    version_before = fixtures.affiliate_version(api, bundle["affiliate_b_id"])
    refused = _create_allocation(
        api,
        bundle["staff_member_id"],
        bundle["affiliate_b_id"],
        version_before,
        staff_role="PITCHING_COACH",
        fte_pct=50,
        effective_start="2026-06-01",
        effective_end="2026-09-01",
        curriculum_version="2026.1",
    )
    validate_error(refused, ApiErrorId.ERR_STAFF_FTE_OVERCOMMITTED.value, 422)

    version_after = fixtures.affiliate_version(api, bundle["affiliate_b_id"])
    assert_integer(version_after, version_before, "Affiliate.version")


def test_an_adjacent_window_sharing_one_boundary_date_is_accepted(api: ApiClient):
    """Starting on the day the prior window ends is not an overlap at all.

    PRD 3.4: "Intervals that merely touch at a shared boundary date are not
    overlapping and contribute nothing to the sum."  The same 50 FTE that was
    refused over [2026-06-01, 2026-09-01) is therefore accepted over
    [2026-07-01, 2026-09-01) and activates cleanly.  The member's committed time
    still reads 60, because PRD 3.4 scopes it to the clock: "the member's
    `total_committed_fte_pct` is recomputed as the sum of `fte_pct` across their
    `ACTIVE` allocations whose half-open interval contains the current logical
    clock date" — and only the April window contains 2026-04-01.

    Design: Difficulty/resource_temporal_overlap/staff_allocation_half_open_intervals_allow_adjacency_but_cap_aggregate_fte
    """
    bundle = _two_clubs_and_a_coach_committed_sixty_percent(api)
    validate_error(
        _create_allocation(
            api,
            bundle["staff_member_id"],
            bundle["affiliate_b_id"],
            fixtures.affiliate_version(api, bundle["affiliate_b_id"]),
            staff_role="PITCHING_COACH",
            fte_pct=50,
            effective_start="2026-06-01",
            effective_end="2026-09-01",
            curriculum_version="2026.1",
        ),
        ApiErrorId.ERR_STAFF_FTE_OVERCOMMITTED.value,
        422,
    )

    accepted = validate_success(
        _create_allocation(
            api,
            bundle["staff_member_id"],
            bundle["affiliate_b_id"],
            fixtures.affiliate_version(api, bundle["affiliate_b_id"]),
            staff_role="PITCHING_COACH",
            fte_pct=50,
            effective_start="2026-07-01",
            effective_end="2026-09-01",
            curriculum_version="2026.1",
        ),
        201,
    )
    assert_status(accepted, "PROPOSED", "StaffAllocation")
    activated = fixtures.dispose_allocation(api, accepted["id"], "ACTIVATE")
    assert_status(activated, "ACTIVE", "StaffAllocation")

    member = validate_success(
        api.get_staff_member(bundle["staff_member_id"], FARM_DIRECTOR_HEADERS), 200
    )
    assert_integer(member["total_committed_fte_pct"], 60, "total_committed_fte_pct")

    rows, meta = validate_paginated(
        api.list_staff_member_allocations(bundle["staff_member_id"], FARM_DIRECTOR_HEADERS)
    )
    assert_integer(meta["total_count"], 2, "allocation total_count")
    assert {row["effective_start"] for row in rows} == {"2026-04-01", "2026-07-01"}, (
        f"only the two accepted windows may exist, got {rows}"
    )
