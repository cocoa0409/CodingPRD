"""Rule enforcement: inclusive league floors, the fixed evaluation ladder,
conjunctive cross-entity gates, clock-relative expiry and aggregate quotas.
"""

from test_helpers import (
    FARM_DIRECTOR_HEADERS,
    INTERNATIONAL_SCOUT_HEADERS,
    MEDICAL_DIRECTOR_HEADERS,
    NON_EXISTENT_UUID,
    ApiClient,
    ApiErrorId,
    assert_integer,
    assert_money,
    assert_status,
    factories,
    fixtures,
    headers_with_unknown_role,
    headers_without_role,
    validate_error,
    validate_paginated,
    validate_success,
)


def _register_affiliate(api: ApiClient, **overrides):
    """Raw club registration, so a refusal can be inspected rather than raised."""
    return api.create_affiliate(factories.affiliate_payload(**overrides), FARM_DIRECTOR_HEADERS)


def _create_assignment(api: ApiClient, player_id: str, affiliate_id: str, expected_version: int, **overrides):
    """Raw assignment create against a caller-supplied parent version."""
    return api.create_assignment(
        factories.assignment_payload(player_id, affiliate_id, expected_version, **overrides),
        FARM_DIRECTOR_HEADERS,
    )


def _create_signing(api: ApiClient, pool_id: str, player_id: str, academy_id: str, expected_version: int, **overrides):
    """Raw signing submission, so a refusal can be inspected rather than raised."""
    return api.create_international_signing(
        factories.international_signing_payload(
            pool_id, player_id, academy_id, expected_version, **overrides
        ),
        INTERNATIONAL_SCOUT_HEADERS,
    )


def _create_allocation(api: ApiClient, staff_member_id: str, affiliate_id: str, expected_version: int, **overrides):
    """Raw allocation proposal, so a refusal can be inspected rather than raised."""
    return api.create_staff_allocation(
        factories.staff_allocation_payload(
            staff_member_id, affiliate_id, expected_version, **overrides
        ),
        FARM_DIRECTOR_HEADERS,
    )


def _activate(api: ApiClient, assignment_id: str):
    """Raw assignment ACTIVATE, so a refusal can be inspected rather than raised."""
    return api.dispose_assignment(
        assignment_id, factories.disposition_payload("ACTIVATE"), FARM_DIRECTOR_HEADERS
    )


def test_a_stipend_one_cent_under_the_league_floor_is_refused_outright(api: ApiClient):
    """2499 cents a day fails the floor, and no club row survives the attempt.

    PRD 3.1: "The registrant must also declare the daily meal stipend paid to
    assigned players, `meal_stipend_cents_per_day`, and the league sets a floor
    here: a stipend below twenty-five dollars a day, that is below 2500 cents, is
    refused with `ERR_MEAL_STIPEND_BELOW_MINIMUM`."  That is a rule violation and
    not a shape problem, so it carries the 422 PRD 2.6 assigns it — "The declared
    meal stipend meets the league floor, otherwise
    `ERR_MEAL_STIPEND_BELOW_MINIMUM` (422)." — rather than the 400 reserved for a
    malformed body.

    Design: Corner/validations/meal_stipend_below_the_league_minimum_is_refused
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")

    response = _register_affiliate(
        api,
        name="Underfed Club",
        level="SINGLE_A",
        market_city="Augusta",
        meal_stipend_cents_per_day=2499,
    )
    validate_error(response, ApiErrorId.ERR_MEAL_STIPEND_BELOW_MINIMUM.value, 422)

    _, meta = validate_paginated(api.list_affiliates(FARM_DIRECTOR_HEADERS))
    assert_integer(meta["total_count"], 0, "affiliate total_count")


def test_a_stipend_exactly_on_the_league_floor_registers_the_club(api: ApiClient):
    """2500 cents a day is admitted, so the comparison is 'below', not 'at most'.

    PRD 3.1 sets the floor as a strict comparison: "a stipend below twenty-five
    dollars a day, that is below 2500 cents, is refused with
    `ERR_MEAL_STIPEND_BELOW_MINIMUM`."  The create therefore runs to completion
    and applies the level default of PRD 3.1: "`roster_limit` bounds how many
    level or complex assignments the club may carry concurrently; it accepts
    integers from 1 through 40, and when it is omitted the server applies the
    league default for the declared level — 28 for both `TRIPLE_A` and
    `DOUBLE_A`, 30 for both `HIGH_A` and `SINGLE_A`, 35 for `COMPLEX`, and 40 for
    `DOMINICAN_ACADEMY`."

    Design: Corner/validations/meal_stipend_exactly_at_the_minimum_is_accepted
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")

    club = validate_success(
        _register_affiliate(
            api,
            name="Exactly Fed Club",
            level="COMPLEX",
            market_city="Sarasota",
            meal_stipend_cents_per_day=2500,
        ),
        201,
    )
    assert_money(club["meal_stipend_cents_per_day"], 2500, "meal_stipend_cents_per_day")
    assert_integer(club["roster_limit"], 35, "roster_limit")


def test_the_low_rungs_of_the_ladder_outrank_existence_and_shape_checks(api: ApiClient):
    """Auth, role, shape and existence violations stack, and the first one wins.

    PRD 2.6: "Checks are evaluated in the ascending order below, and the first
    violated check short-circuits every later one".  Rungs one and two are the
    header rungs — "Both `X-User-Role` and `X-User-ID` are present and non-empty,
    otherwise `ERR_MISSING_AUTH_HEADERS` (401)." and "`X-User-Role` names one of
    the five declared roles, otherwise `ERR_INVALID_ROLE` (401)." — and rung three
    is the endpoint rung: "The acting role appears on the target endpoint,
    otherwise `ERR_ROLE_NOT_PERMITTED` (403)."  All three outrank rung seven,
    "Every id embedded in the request path resolves to a stored resource,
    validated strictly left to right, otherwise the not-found error for the
    leftmost unresolved segment (404)", and clearance disposition is closed to a
    `FarmDirector` because PRD 3.5 says "Disposition of a clearance belongs
    exclusively to a `MedicalDirector`."  Inside the body the same precedence
    holds between rung eight, "The request body is well-shaped, otherwise
    `ERR_INVALID_REQUEST` (400)", and rung nine, "Every foreign key supplied in
    the request body resolves to a stored resource (404)."

    Design: Corner/validations/auth_shape_and_existence_rungs_fire_in_priority_order
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    club = fixtures.create_affiliate(
        api,
        name="Ladder Club",
        level="HIGH_A",
        market_city="Bowie",
        meal_stipend_cents_per_day=2800,
    )
    player = fixtures.create_player(
        api, full_name="Ladder Player", origin="DOMESTIC_DRAFT", signed_date="2025-06-10"
    )
    version = fixtures.player_version(api, player["id"])

    missing_headers = api.get_affiliate(NON_EXISTENT_UUID, headers_without_role())
    validate_error(missing_headers, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value, 401)

    unknown_role = api.get_affiliate(NON_EXISTENT_UUID, headers_with_unknown_role())
    validate_error(unknown_role, ApiErrorId.ERR_INVALID_ROLE.value, 401)

    wrong_role = api.dispose_medical_clearance(
        NON_EXISTENT_UUID,
        factories.clearance_issue_payload(cleared_workload_ceiling_index=20.00),
        FARM_DIRECTOR_HEADERS,
    )
    validate_error(wrong_role, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    bad_shape = _create_assignment(
        api,
        NON_EXISTENT_UUID,
        club["id"],
        version,
        assignment_type="SHORT_TERM",
        effective_date="2026-04-01",
        end_date="2026-06-30",
    )
    validate_error(bad_shape, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    # Correcting only the enum leaves the unresolved body foreign key exposed.
    unknown_fk = _create_assignment(
        api,
        NON_EXISTENT_UUID,
        club["id"],
        version,
        effective_date="2026-04-01",
        end_date="2026-06-30",
    )
    validate_error(unknown_fk, ApiErrorId.ERR_PLAYER_NOT_FOUND.value, 404)


def test_signing_eligibility_needs_the_right_origin_and_the_right_level_together(api: ApiClient):
    """Each half of the pair is refused alone; only the matching pair is admitted.

    PRD 3.9: "An eligibility pair is enforced at submission: the named player's
    `origin` must be `INTERNATIONAL_FA` and the named academy's `level` must be
    `DOMINICAN_ACADEMY`, and a violation of either half is refused with
    `ERR_SIGNING_ELIGIBILITY_VIOLATION`."  The admitted submission lands where PRD
    3.9 says it must — "The submission is persisted in status `SUBMITTED` with
    `pool_charge_cents` 0, `overage_tax_cents` 0, `tier3_breach` false, and
    `rejection_reason` and `approved_by_user_id` both null." — and it charges the
    pool nothing, because PRD 3.9 counts only approvals: "signings in `SUBMITTED`,
    `REJECTED` or `VOIDED` contribute nothing to either."  Both refusals also
    leave the pool untouched, so one `expected_pool_version` reading serves all
    three calls under PRD 2.7's optimistic check.

    Design: Corner/validations/signing_eligibility_depends_on_both_player_origin_and_academy_level
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    academy = fixtures.licensed_academy(
        api,
        affiliate_overrides={
            "name": "Eligible Academy",
            "market_city": "San Pedro",
            "meal_stipend_cents_per_day": 2500,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    wrong_level = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Wrong Level Club",
            "level": "HIGH_A",
            "market_city": "Vancouver",
            "meal_stipend_cents_per_day": 2800,
        },
    )
    international = fixtures.create_player(
        api,
        INTERNATIONAL_SCOUT_HEADERS,
        full_name="Eligible Prospect",
        origin="INTERNATIONAL_FA",
        signed_date="2026-01-15",
    )
    drafted = fixtures.create_player(
        api,
        INTERNATIONAL_SCOUT_HEADERS,
        full_name="Drafted Player",
        origin="DOMESTIC_DRAFT",
        signed_date="2025-06-10",
    )
    pool = fixtures.create_pool(api, season_year=2026, base_pool_cents=5000000)
    reading = fixtures.pool_version(api, pool["id"])

    wrong_origin = _create_signing(
        api, pool["id"], drafted["id"], academy["affiliate_id"], reading, bonus_cents=400000
    )
    validate_error(wrong_origin, ApiErrorId.ERR_SIGNING_ELIGIBILITY_VIOLATION.value, 422)

    wrong_academy = _create_signing(
        api,
        pool["id"],
        international["id"],
        wrong_level["affiliate_id"],
        reading,
        bonus_cents=400000,
    )
    validate_error(wrong_academy, ApiErrorId.ERR_SIGNING_ELIGIBILITY_VIOLATION.value, 422)

    # Neither refusal advanced the pool, so the original reading is still current.
    accepted = validate_success(
        _create_signing(
            api,
            pool["id"],
            international["id"],
            academy["affiliate_id"],
            reading,
            bonus_cents=400000,
        ),
        201,
    )
    assert_status(accepted, "SUBMITTED", "InternationalSigning")
    assert_money(accepted["pool_charge_cents"], 0, "pool_charge_cents")
    assert_money(
        fixtures.read_pool(api, pool["id"])["allocated_cents"], 0, "allocated_cents"
    )


def test_moving_the_clock_past_expiry_turns_a_valid_clearance_into_a_lapsed_one(api: ApiClient):
    """Nothing about the record changes; only the clock moves, and the refusal shifts.

    PRD 3.5: "A clearance advertises its own lapse through `is_expired`, which
    reads true when its status is `ISSUED` and the logical clock date is strictly
    after `expires_on`."  Which refusal that produces is fixed by PRD 3.6: "When no
    clearance of the required type is issued at all the refusal is
    `ERR_MEDICAL_CLEARANCE_REQUIRED`; when the only issued match has lapsed the
    refusal is `ERR_MEDICAL_CLEARANCE_EXPIRED`."  The lapse is derived rather than
    stored, because PRD 2.5 makes it a function of the clock: "the server
    re-evaluates, for every non-terminal row affected: whether a facility
    inspection is overdue (`is_overdue`), whether a medical clearance has lapsed
    (`is_expired`), and whether a pending transaction report has gone late
    (`is_late`, along with the `late_fee_cents` that lateness implies)."  And the
    player's medical dimension does not move, because PRD 3.5 confines it:
    "Medical standing advances on clearance outcomes alone."

    Design: Corner/validations/expired_clearance_blocks_activation_once_the_clock_passes_expiry
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Expiry Club",
            "level": "SINGLE_A",
            "market_city": "Bradenton",
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
        expires_on="2026-04-10",
        full_name="Expiring Clearance",
        origin="DOMESTIC_DRAFT",
        signed_date="2025-06-10",
    )
    assert_status(bundle["clearance"], "ISSUED", "MedicalClearance")
    assignment = fixtures.create_assignment(
        api,
        bundle["player_id"],
        club["affiliate_id"],
        effective_date="2026-04-15",
        end_date="2026-06-30",
    )

    fixtures.set_clock(api, "2026-04-11T00:00:00Z", MEDICAL_DIRECTOR_HEADERS)

    refused = _activate(api, assignment["id"])
    validate_error(refused, ApiErrorId.ERR_MEDICAL_CLEARANCE_EXPIRED.value, 409)

    lapsed = fixtures.read_clearance(api, bundle["player_id"], bundle["clearance_id"])
    assert_status(lapsed, "ISSUED", "MedicalClearance")
    assert lapsed["is_expired"] is True, (
        f"a clock past expires_on lapses the clearance, got {lapsed!r}"
    )

    assert_status(
        fixtures.read_assignment(api, assignment["id"]), "PENDING_CLEARANCE", "PlayerAssignment"
    )
    assert_integer(
        fixtures.read_affiliate(api, club["affiliate_id"])["active_roster_count"],
        0,
        "active_roster_count",
    )
    player = fixtures.read_player(api, bundle["player_id"])
    assert player["medical_status"] == "CLEARED", (
        f"expiry is not a clearance outcome, got {player['medical_status']!r}"
    )


def _rehab_complex_with_four_pending_rehab_windows(api: ApiClient) -> dict:
    """A COMPLEX club and four separately cleared players each holding a rehab row."""
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Rehab Complex",
            "level": "COMPLEX",
            "market_city": "Goodyear",
            "meal_stipend_cents_per_day": 2500,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    assignment_ids = []
    for index, name in enumerate(("Rehab One", "Rehab Two", "Rehab Three", "Rehab Four")):
        player = fixtures.cleared_player(
            api,
            clearance_type="REHAB_START",
            cleared_workload_ceiling_index=8.00,
            full_name=name,
            origin="DOMESTIC_DRAFT",
            signed_date=f"2025-06-1{index}",
        )
        assignment = fixtures.create_assignment(
            api,
            player["player_id"],
            club["affiliate_id"],
            assignment_type="REHAB",
            movement_reason="REHAB_START",
            effective_date="2026-04-01",
            end_date="2026-05-01",
        )
        assignment_ids.append(assignment["id"])
    club["assignment_ids"] = assignment_ids
    return club


def test_the_fourth_concurrent_rehab_activation_exhausts_the_slot_allowance(api: ApiClient):
    """Three rehab slots fill, the fourth is refused, and the roster stays empty.

    PRD 3.6: "for a `REHAB` assignment the club's `rehab_assignment_count` must be
    strictly below the organization's rehab slot allowance of three concurrent
    rehab assignments per club (`ERR_REHAB_SLOT_LIMIT_EXCEEDED`)."  The comparison
    is made against the live count, per PRD 3.6: "Every capacity comparison is
    made against the counters as they stand *before* this activation increments
    them."  Rehab rows never touch the roster dimension, because PRD 3.6 splits
    the aggregations by type: "`rehab_assignment_count` is the number at the club
    with status `ACTIVE` and type `REHAB`."

    Design: Corner/validations/fourth_rehab_assignment_exceeds_the_aggregate_rehab_slot_limit
    """
    bundle = _rehab_complex_with_four_pending_rehab_windows(api)
    first, second, third, fourth = bundle["assignment_ids"]

    for assignment_id in (first, second, third):
        fixtures.dispose_assignment(api, assignment_id, "ACTIVATE")

    filled = fixtures.read_affiliate(api, bundle["affiliate_id"])
    assert_integer(filled["rehab_assignment_count"], 3, "rehab_assignment_count")
    assert_integer(filled["active_roster_count"], 0, "active_roster_count")

    refused = _activate(api, fourth)
    validate_error(refused, ApiErrorId.ERR_REHAB_SLOT_LIMIT_EXCEEDED.value, 409)
    assert_status(
        fixtures.read_assignment(api, fourth), "PENDING_CLEARANCE", "PlayerAssignment"
    )


def test_revoking_one_rehab_row_frees_the_slot_the_aggregate_was_counting(api: ApiClient):
    """The quota is recomputed from live rows, not held as a high-water mark.

    PRD 3.6: "Only `ACTIVE` assignments occupy a slot: rows in
    `PENDING_CLEARANCE`, `SUSPENDED`, `COMPLETED` or `REVOKED` release their slot
    immediately."  The retried activation therefore passes the same check that
    just refused it — PRD 3.6: "for a `REHAB` assignment the club's
    `rehab_assignment_count` must be strictly below the organization's rehab slot
    allowance of three concurrent rehab assignments per club
    (`ERR_REHAB_SLOT_LIMIT_EXCEEDED`)." — and none of the four rows charges
    anything, because PRD 3.6 conditions the charge on type: "When the assignment
    is `LEVEL` or `COMPLEX` and its `projected_optional_days` is 20 or more, the
    server charges an option year".

    Design: Corner/validations/fourth_rehab_assignment_exceeds_the_aggregate_rehab_slot_limit
    """
    bundle = _rehab_complex_with_four_pending_rehab_windows(api)
    first, second, third, fourth = bundle["assignment_ids"]

    for assignment_id in (first, second, third):
        fixtures.dispose_assignment(api, assignment_id, "ACTIVATE")
    _activate(api, fourth)

    fixtures.dispose_assignment(api, first, "REVOKE", note="rehab abandoned")
    freed = fixtures.read_affiliate(api, bundle["affiliate_id"])
    assert_integer(freed["rehab_assignment_count"], 2, "rehab_assignment_count")

    activated = fixtures.dispose_assignment(api, fourth, "ACTIVATE")
    assert_status(activated, "ACTIVE", "PlayerAssignment")
    assert_integer(
        fixtures.read_affiliate(api, bundle["affiliate_id"])["rehab_assignment_count"],
        3,
        "rehab_assignment_count",
    )

    for assignment_id in bundle["assignment_ids"]:
        assert fixtures.option_years_for(api, assignment_id) == [], (
            f"a rehab assignment charges no option year, got rows for {assignment_id}"
        )


def test_the_curriculum_gate_compares_against_the_org_and_against_the_member(api: ApiClient):
    """Two mismatches on two different sides, then the one body that satisfies both.

    PRD 2.11: "The organization teaches one player-development curriculum at a
    time, and the current organization-wide curriculum version is `2026.1`. Any
    `curriculum_version` supplied on a staff allocation or a development plan must
    equal that value; for a staff allocation it must additionally equal the staff
    member's own `curriculum_version_certified`, because a coach may not teach a
    version they are not certified on. A mismatch on either comparison is rejected
    with `ERR_CURRICULUM_VERSION_MISMATCH` (HTTP 422)."  The satisfying proposal
    lands where PRD 3.4 puts it — "A proposed allocation is persisted in status
    `PROPOSED`" — and because neither refusal mutated the club, one
    `expected_affiliate_version` reading serves all three calls.

    Design: Corner/validations/staff_allocation_curriculum_must_match_both_the_org_and_the_member
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Curriculum Club",
            "level": "HIGH_A",
            "market_city": "Peoria",
            "meal_stipend_cents_per_day": 2800,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    current = fixtures.create_staff_member(
        api,
        full_name="Current Coach",
        discipline="PITCHING",
        curriculum_version_certified="2026.1",
        certification_expires_on="2027-01-31",
    )
    legacy = fixtures.create_staff_member(
        api,
        full_name="Legacy Coach",
        discipline="HITTING",
        curriculum_version_certified="2025.2",
        certification_expires_on="2027-01-31",
    )
    reading = fixtures.affiliate_version(api, club["affiliate_id"])

    stale_org = _create_allocation(
        api,
        current["id"],
        club["affiliate_id"],
        reading,
        staff_role="PITCHING_COACH",
        curriculum_version="2025.2",
    )
    validate_error(stale_org, ApiErrorId.ERR_CURRICULUM_VERSION_MISMATCH.value, 422)

    stale_member = _create_allocation(
        api,
        legacy["id"],
        club["affiliate_id"],
        reading,
        staff_role="HITTING_COACH",
        curriculum_version="2026.1",
    )
    validate_error(stale_member, ApiErrorId.ERR_CURRICULUM_VERSION_MISMATCH.value, 422)

    accepted = validate_success(
        _create_allocation(
            api,
            current["id"],
            club["affiliate_id"],
            reading,
            staff_role="PITCHING_COACH",
            curriculum_version="2026.1",
        ),
        201,
    )
    assert_status(accepted, "PROPOSED", "StaffAllocation")
    assert_integer(
        fixtures.affiliate_version(api, club["affiliate_id"]),
        reading + 1,
        "Affiliate.version",
    )

    _, meta = validate_paginated(
        api.list_affiliate_staff_allocations(club["affiliate_id"], FARM_DIRECTOR_HEADERS)
    )
    assert_integer(meta["total_count"], 1, "staff-allocation total_count")
