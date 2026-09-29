"""Layers that only show up when several mechanisms are stacked on one path:
the three version-guarded creates, an FTE figure reconciled across a whole
allocation lifecycle, and a workload ceiling that both trips and un-trips.
"""

from test_helpers import (
    FARM_DIRECTOR_HEADERS,
    INTERNATIONAL_SCOUT_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_decimal,
    assert_integer,
    assert_money,
    assert_status,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def _read_member(api: ApiClient, staff_member_id: str):
    """Read one staff member, whose FTE figure the allocation lifecycle drives."""
    return validate_success(
        api.get_staff_member(staff_member_id, FARM_DIRECTOR_HEADERS), 200
    )


def _create_assignment(api: ApiClient, player_id: str, affiliate_id: str, expected_player_version, **overrides):
    """Raw assignment create, so a refusal can be inspected rather than raised."""
    return api.create_assignment(
        factories.assignment_payload(
            player_id, affiliate_id, expected_player_version, **overrides
        ),
        FARM_DIRECTOR_HEADERS,
    )


def _create_signing(api: ApiClient, pool_id: str, player_id: str, academy_id: str, expected_pool_version, **overrides):
    """Raw signing submission, so a refusal can be inspected rather than raised."""
    return api.create_international_signing(
        factories.international_signing_payload(
            pool_id, player_id, academy_id, expected_pool_version, **overrides
        ),
        INTERNATIONAL_SCOUT_HEADERS,
    )


def _create_allocation(api: ApiClient, staff_member_id: str, affiliate_id: str, expected_affiliate_version, **overrides):
    """Raw allocation proposal, so a refusal can be inspected rather than raised."""
    return api.create_staff_allocation(
        factories.staff_allocation_payload(
            staff_member_id, affiliate_id, expected_affiliate_version, **overrides
        ),
        FARM_DIRECTOR_HEADERS,
    )


def _log_outing(api: ApiClient, assignment_id: str, log_date: str, **measures):
    """Raw outing append, so a refusal can be inspected rather than raised."""
    return api.create_workload_log(
        assignment_id,
        factories.workload_log_payload(log_date=log_date, **measures),
        FARM_DIRECTOR_HEADERS,
    )


# ---------------------------------------------------------------------------
# Instance 1 — a stale player version refuses the second assignment create
# ---------------------------------------------------------------------------


def test_a_stale_player_version_refuses_the_second_assignment_create(api: ApiClient):
    """The version the client read is spent by its own first create.

    PRD 2.7: "A `POST /assignments` request must carry `expected_player_version`
    holding the client's last observed `version` of the target `Player`. If the
    player's `version` has advanced since the client read it, the create is
    rejected with `ERR_STALE_PLAYER_VERSION` (HTTP 412)."  PRD 2.7 also states
    why one read cannot serve two writes: "Note also that each of the three
    guarded creates itself bumps the parent's `version` by one on success —
    creating an assignment advances the player's `version`, submitting a signing
    advances the pool's `version`, and proposing an allocation advances the
    affiliate's `version` — so a client that issues two creates in a row against
    the same parent must re-read the parent between them."

    Design: Corner/cross_cutting_complexity_layers/stale_player_version_blocks_an_assignment_create
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Stale Player Club",
            "level": "SINGLE_A",
            "market_city": "Modesto",
            "meal_stipend_cents_per_day": 2600,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    bundle = fixtures.cleared_player(
        api,
        clearance_type="LEVEL_ASSIGNMENT",
        cleared_workload_ceiling_index=25.00,
        expires_on="2026-12-31",
        full_name="Stale Read Player",
        origin="DOMESTIC_DRAFT",
        signed_date="2025-06-10",
    )
    player_id = bundle["player_id"]

    first_read = fixtures.player_version(api, player_id)
    first = fixtures.create_assignment(
        api,
        player_id,
        club["affiliate_id"],
        expected_player_version=first_read,
        assignment_type="LEVEL",
        movement_reason="INITIAL",
        effective_date="2026-04-01",
        end_date="2026-06-30",
    )
    assert_status(first, "PENDING_CLEARANCE", "PlayerAssignment")
    fixtures.dispose_assignment(api, first["id"], "ACTIVATE")

    refused = _create_assignment(
        api,
        player_id,
        club["affiliate_id"],
        first_read,
        assignment_type="LEVEL",
        movement_reason="LATERAL",
        effective_date="2026-08-01",
        end_date="2026-09-30",
    )
    validate_error(refused, ApiErrorId.ERR_STALE_PLAYER_VERSION.value, 412)

    _, after_refusal = validate_paginated(
        api.list_assignments(FARM_DIRECTOR_HEADERS, {"player_id": player_id})
    )
    assert_integer(after_refusal["total_count"], 1, "assignment total_count")

    refreshed = fixtures.player_version(api, player_id)
    assert refreshed > first_read, (
        f"the accepted create must have advanced the player version past {first_read}, got {refreshed}"
    )
    second = fixtures.create_assignment(
        api,
        player_id,
        club["affiliate_id"],
        expected_player_version=refreshed,
        assignment_type="LEVEL",
        movement_reason="LATERAL",
        effective_date="2026-08-01",
        end_date="2026-09-30",
    )
    assert_status(second, "PENDING_CLEARANCE", "PlayerAssignment")

    _, after_retry = validate_paginated(
        api.list_assignments(FARM_DIRECTOR_HEADERS, {"player_id": player_id})
    )
    assert_integer(after_retry["total_count"], 2, "assignment total_count")


# ---------------------------------------------------------------------------
# Instance 2 — a stale pool version refuses the second signing submission
# ---------------------------------------------------------------------------


def test_a_stale_pool_version_refuses_the_second_signing_submission(api: ApiClient):
    """The quota is shared, so the pool revision must be re-read between writes.

    PRD 2.7: "A `POST /international-signings` request must carry
    `expected_pool_version` holding the client's last observed `version` of the
    target `SigningPool`. A mismatch with the pool's current `version` is
    rejected with `ERR_STALE_POOL_VERSION` (HTTP 412)."  Neither submission
    touches the ledger, because PRD 3.9 charges the pool only on approval:
    "Once signings begin, `allocated_cents` is the sum of `pool_charge_cents`
    over the pool's `APPROVED` signings and `overage_tax_accrued_cents` is the
    sum of their `overage_tax_cents`; signings in `SUBMITTED`, `REJECTED` or
    `VOIDED` contribute nothing to either."

    Design: Corner/cross_cutting_complexity_layers/stale_pool_version_blocks_a_signing_submission
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    academy = fixtures.licensed_academy(
        api,
        affiliate_overrides={
            "name": "Stale Pool Academy",
            "market_city": "San Pedro",
            "meal_stipend_cents_per_day": 2500,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    pool = fixtures.create_pool(api, season_year=2026, base_pool_cents=5000000)
    first_player = fixtures.create_player(
        api,
        INTERNATIONAL_SCOUT_HEADERS,
        full_name="Race One",
        origin="INTERNATIONAL_FA",
        signed_date="2026-01-15",
    )
    second_player = fixtures.create_player(
        api,
        INTERNATIONAL_SCOUT_HEADERS,
        full_name="Race Two",
        origin="INTERNATIONAL_FA",
        signed_date="2026-01-16",
    )

    first_read = fixtures.pool_version(api, pool["id"])
    first = fixtures.create_signing(
        api,
        pool["id"],
        first_player["id"],
        academy["affiliate_id"],
        bonus_cents=600000,
        expected_pool_version=first_read,
    )
    assert_status(first, "SUBMITTED", "InternationalSigning")
    assert_money(fixtures.read_pool(api, pool["id"])["allocated_cents"], 0, "allocated_cents")

    refused = _create_signing(
        api,
        pool["id"],
        second_player["id"],
        academy["affiliate_id"],
        first_read,
        bonus_cents=700000,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_POOL_VERSION.value, 412)

    _, after_refusal = validate_paginated(
        api.list_international_signings(
            INTERNATIONAL_SCOUT_HEADERS, {"pool_id": pool["id"]}
        )
    )
    assert_integer(after_refusal["total_count"], 1, "signing total_count")

    refreshed = fixtures.pool_version(api, pool["id"])
    assert refreshed > first_read, (
        f"the accepted submission must have advanced the pool version past {first_read}, got {refreshed}"
    )
    second = fixtures.create_signing(
        api,
        pool["id"],
        second_player["id"],
        academy["affiliate_id"],
        bonus_cents=700000,
        expected_pool_version=refreshed,
    )
    assert_status(second, "SUBMITTED", "InternationalSigning")

    _, after_retry = validate_paginated(
        api.list_international_signings(
            INTERNATIONAL_SCOUT_HEADERS, {"pool_id": pool["id"]}
        )
    )
    assert_integer(after_retry["total_count"], 2, "signing total_count")

    ledger = fixtures.read_pool(api, pool["id"])
    assert_money(ledger["allocated_cents"], 0, "allocated_cents")
    assert_money(ledger["remaining_cents"], 5000000, "remaining_cents")
    assert_status(ledger, "OPEN", "SigningPool")


# ---------------------------------------------------------------------------
# Instance 3 — a stale affiliate version refuses the second allocation proposal
# ---------------------------------------------------------------------------


def test_a_stale_affiliate_version_refuses_the_second_allocation_proposal(api: ApiClient):
    """Two coverage proposals in a row need two reads of the club.

    PRD 2.7: "A `POST /staff-allocations` request must carry
    `expected_affiliate_version` holding the client's last observed `version` of
    the target `Affiliate`. A mismatch with the affiliate's current `version` is
    rejected with `ERR_STALE_AFFILIATE_VERSION` (HTTP 412)."  Both accepted
    proposals sit in `PROPOSED`, and PRD 3.4 binds the committed-time figure to
    activation alone: "On success, the member's `total_committed_fte_pct` is
    recomputed as the sum of `fte_pct` across their `ACTIVE` allocations whose
    half-open interval contains the current logical clock date".

    Design: Corner/cross_cutting_complexity_layers/stale_affiliate_version_blocks_a_staff_allocation
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Stale Affiliate Club",
            "level": "DOUBLE_A",
            "market_city": "Springfield",
            "meal_stipend_cents_per_day": 2900,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    first_member = fixtures.create_staff_member(
        api,
        full_name="Coverage One",
        discipline="PITCHING",
        certification_expires_on="2027-01-31",
    )
    second_member = fixtures.create_staff_member(
        api,
        full_name="Coverage Two",
        discipline="HITTING",
        certification_expires_on="2027-01-31",
    )

    first_read = fixtures.affiliate_version(api, club["affiliate_id"])
    first = fixtures.create_allocation(
        api,
        first_member["id"],
        club["affiliate_id"],
        staff_role="PITCHING_COACH",
        fte_pct=50,
        effective_start="2026-04-01",
        effective_end="2026-09-01",
        expected_affiliate_version=first_read,
    )
    assert_status(first, "PROPOSED", "StaffAllocation")

    refused = _create_allocation(
        api,
        second_member["id"],
        club["affiliate_id"],
        first_read,
        staff_role="HITTING_COACH",
        fte_pct=50,
        effective_start="2026-04-01",
        effective_end="2026-09-01",
    )
    validate_error(refused, ApiErrorId.ERR_STALE_AFFILIATE_VERSION.value, 412)

    _, after_refusal = validate_paginated(
        api.list_affiliate_staff_allocations(club["affiliate_id"], FARM_DIRECTOR_HEADERS)
    )
    assert_integer(after_refusal["total_count"], 1, "allocation total_count")

    refreshed = fixtures.affiliate_version(api, club["affiliate_id"])
    assert refreshed > first_read, (
        f"the accepted proposal must have advanced the affiliate version past {first_read}, got {refreshed}"
    )
    second = fixtures.create_allocation(
        api,
        second_member["id"],
        club["affiliate_id"],
        staff_role="HITTING_COACH",
        fte_pct=50,
        effective_start="2026-04-01",
        effective_end="2026-09-01",
        expected_affiliate_version=refreshed,
    )
    assert_status(second, "PROPOSED", "StaffAllocation")

    _, after_retry = validate_paginated(
        api.list_affiliate_staff_allocations(club["affiliate_id"], FARM_DIRECTOR_HEADERS)
    )
    assert_integer(after_retry["total_count"], 2, "allocation total_count")

    for member in (first_member, second_member):
        reread = _read_member(api, member["id"])
        assert_integer(reread["total_committed_fte_pct"], 0, "total_committed_fte_pct")
        assert_status(reread, "ACTIVE", "StaffMember")


# ---------------------------------------------------------------------------
# Instance 4 — one member's FTE across two proposals, two activations and an end
# ---------------------------------------------------------------------------


def test_committed_fte_is_recomputed_at_every_step_of_the_allocation_lifecycle(api: ApiClient):
    """The figure is always the live sum, never an incrementally patched total.

    PRD 3.4: "A newly registered member has `total_committed_fte_pct`
    initialised to 0 and a `status` of `ACTIVE`, which is the only value that
    field ever takes: no transition in this system moves a staff member out of
    `ACTIVE`."  Activation is what moves the figure — "On success, the member's
    `total_committed_fte_pct` is recomputed as the sum of `fte_pct` across their
    `ACTIVE` allocations whose half-open interval contains the current logical
    clock date" — and the way out moves it back, because "Ending an allocation
    moves it `ACTIVE` → `ENDED`; recalling an active allocation moves it
    `ACTIVE` → `RECALLED`. Both recompute the member's
    `total_committed_fte_pct`".  So one member holding 40 and 30 at the same club
    walks 0, 0, 40, 70, 30.

    Design: Corner/cross_cutting_complexity_layers/staff_fte_reconciles_across_create_activate_and_end
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Reconcile Club",
            "level": "TRIPLE_A",
            "market_city": "Reno",
            "meal_stipend_cents_per_day": 3000,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_1",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    member = fixtures.create_staff_member(
        api,
        full_name="Reconcile Coach",
        discipline="PITCHING",
        certification_expires_on="2027-01-31",
    )
    assert_integer(member["total_committed_fte_pct"], 0, "total_committed_fte_pct")

    pitching = fixtures.create_allocation(
        api,
        member["id"],
        club["affiliate_id"],
        staff_role="PITCHING_COACH",
        fte_pct=40,
        effective_start="2026-04-01",
        effective_end="2026-09-01",
    )
    strength = fixtures.create_allocation(
        api,
        member["id"],
        club["affiliate_id"],
        staff_role="STRENGTH_COACH",
        fte_pct=30,
        effective_start="2026-04-01",
        effective_end="2026-09-01",
    )
    assert_status(pitching, "PROPOSED", "StaffAllocation")
    assert_status(strength, "PROPOSED", "StaffAllocation")
    assert_integer(
        _read_member(api, member["id"])["total_committed_fte_pct"],
        0,
        "total_committed_fte_pct",
    )

    fixtures.dispose_allocation(api, pitching["id"], "ACTIVATE")
    assert_integer(
        _read_member(api, member["id"])["total_committed_fte_pct"],
        40,
        "total_committed_fte_pct",
    )

    fixtures.dispose_allocation(api, strength["id"], "ACTIVATE")
    assert_integer(
        _read_member(api, member["id"])["total_committed_fte_pct"],
        70,
        "total_committed_fte_pct",
    )

    ended = fixtures.dispose_allocation(api, pitching["id"], "END", note="season role closed")
    assert_status(ended, "ENDED", "StaffAllocation")
    assert_integer(
        _read_member(api, member["id"])["total_committed_fte_pct"],
        30,
        "total_committed_fte_pct",
    )

    active_rows, active_meta = validate_paginated(
        api.list_staff_member_allocations(
            member["id"], FARM_DIRECTOR_HEADERS, {"status": "ACTIVE"}
        )
    )
    assert_integer(active_meta["total_count"], 1, "active allocation total_count")
    assert active_rows[0]["id"] == strength["id"], (
        f"the surviving active allocation must be the strength role, got {active_rows[0]!r}"
    )

    _, all_meta = validate_paginated(
        api.list_staff_member_allocations(member["id"], FARM_DIRECTOR_HEADERS)
    )
    assert_integer(all_meta["total_count"], 2, "allocation total_count")


# ---------------------------------------------------------------------------
# Instance 5 — the effective ceiling trips on the second outing, then the
# rolling window moves and the same outing becomes admissible again
# ---------------------------------------------------------------------------


def _ceiling_club_with_a_capped_arm(api: ApiClient) -> dict:
    """A SINGLE_A club and one active arm cleared only to an index of 1.00."""
    fixtures.set_clock(api, "2026-04-05T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Ceiling Club",
            "level": "SINGLE_A",
            "market_city": "Beloit",
            "meal_stipend_cents_per_day": 2600,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    bundle = fixtures.active_assignment(
        api,
        club["affiliate_id"],
        player_overrides={
            "full_name": "Ceiling Arm",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2025-06-10",
            "cleared_workload_ceiling_index": 1.00,
            "expires_on": "2026-12-31",
        },
        assignment_type="LEVEL",
        movement_reason="INITIAL",
        effective_date="2026-04-01",
        end_date="2026-08-31",
    )
    club.update(bundle)
    return club


def test_the_effective_ceiling_is_the_cleared_one_and_the_window_releases_it(api: ApiClient):
    """The clearance caps the assignment, then the window drops the load.

    PRD 3.7: "Recording an outing is refused when it would drive the *actual*
    rolling figure above the effective ceiling for that assignment. The effective
    ceiling is the smaller of the assignment's own `workload_ceiling_index` and
    the `cleared_workload_ceiling_index` on the governing medical clearance when
    that value is non-null; when the clearance carries no cleared ceiling, the
    assignment's own figure stands alone. An outing that would breach the
    effective ceiling is refused with `ERR_WORKLOAD_CEILING_EXCEEDED` and nothing
    is written."  A 150-pitch outing weighs "fifty-five hundredths of the pitch
    count divided by one hundred" at a `SINGLE_A` multiplier of `1.00`, which
    PRD 3.7 then rounds — the figure "rounds the sum half-up to two decimal
    places" — to `0.83`, so one outing sits under the cleared `1.00` and two do
    not.  The release comes from PRD 3.7's window: "And the outing's `log_date`
    must fall inside a rolling fourteen-day window that is inclusive at both
    ends: the window runs from thirteen days before the current logical clock
    date through the clock date itself."

    Design: Corner/cross_cutting_complexity_layers/workload_ceiling_trips_at_the_cumulative_boundary_and_resets_with_the_window
    """
    bundle = _ceiling_club_with_a_capped_arm(api)
    assignment_id = bundle["assignment_id"]
    player_id = bundle["player_id"]

    assert_decimal(
        fixtures.read_assignment(api, assignment_id)["workload_ceiling_index"],
        "12.00",
        2,
        "PlayerAssignment.workload_ceiling_index",
    )
    assert_decimal(
        bundle["clearance"]["cleared_workload_ceiling_index"],
        "1.00",
        2,
        "MedicalClearance.cleared_workload_ceiling_index",
    )
    assert_decimal(
        fixtures.read_player(api, player_id)["workload_index"],
        "0.00",
        2,
        "Player.workload_index",
    )

    first = fixtures.log_outing(api, assignment_id, "2026-04-05", pitches_thrown=150)
    assert_integer(first["pitches_thrown"], 150, "pitches_thrown")
    assert_decimal(
        fixtures.read_player(api, player_id)["workload_index"],
        "0.83",
        2,
        "Player.workload_index",
    )

    fixtures.set_clock(api, "2026-04-06T00:00:00Z")
    refused = _log_outing(api, assignment_id, "2026-04-06", pitches_thrown=150)
    validate_error(refused, ApiErrorId.ERR_WORKLOAD_CEILING_EXCEEDED.value, 422)
    assert_decimal(
        fixtures.read_player(api, player_id)["workload_index"],
        "0.83",
        2,
        "Player.workload_index",
    )
    _, after_refusal = validate_paginated(
        api.list_workload_logs(assignment_id, FARM_DIRECTOR_HEADERS)
    )
    assert_integer(after_refusal["total_count"], 1, "workload log total_count")

    # Thirteen days before 2026-04-25 is 2026-04-12, so the 2026-04-05 outing
    # has fallen out of the window and the rolling figure is empty again.
    fixtures.set_clock(api, "2026-04-25T00:00:00Z")
    assert_decimal(
        fixtures.read_player(api, player_id)["workload_index"],
        "0.00",
        2,
        "Player.workload_index",
    )

    second = fixtures.log_outing(api, assignment_id, "2026-04-25", pitches_thrown=150)
    assert_integer(second["pitches_thrown"], 150, "pitches_thrown")
    assert_decimal(
        fixtures.read_player(api, player_id)["workload_index"],
        "0.83",
        2,
        "Player.workload_index",
    )

    _, final_meta = validate_paginated(
        api.list_workload_logs(assignment_id, FARM_DIRECTOR_HEADERS)
    )
    assert_integer(final_meta["total_count"], 2, "workload log total_count")
