"""Endpoint surface: a collection walked end to end, an action endpoint whose
effects reach two other resources, a self-referential link, derived read
dimensions and an action the clock alone decides.
"""

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    FARM_DIRECTOR_HEADERS,
    INTERNATIONAL_SCOUT_HEADERS,
    MEDICAL_DIRECTOR_HEADERS,
    NON_EXISTENT_UUID,
    ApiClient,
    ApiErrorId,
    assert_decimal,
    assert_integer,
    assert_iso_timestamp,
    assert_status,
    factories,
    fixtures,
    make_affiliate_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _create_assignment(api: ApiClient, player_id: str, affiliate_id: str, **overrides):
    """Raw assignment create, so a refusal can be inspected rather than raised."""
    expected = overrides.pop("expected_player_version", None)
    if expected is None:
        expected = fixtures.player_version(api, player_id)
    return api.create_assignment(
        factories.assignment_payload(player_id, affiliate_id, expected, **overrides),
        FARM_DIRECTOR_HEADERS,
    )


def _submit_remediation(api: ApiClient, review_id: str, headers, note: str):
    """Raw remediation submission, so a refusal can be inspected rather than raised."""
    return api.dispose_facility_review(
        review_id,
        factories.disposition_payload("SUBMIT_REMEDIATION", remediation_note=note, note=note),
        headers,
    )


def test_the_staff_collection_creates_reads_and_filters_on_both_declared_keys(api: ApiClient):
    """Two members, two independent filters, one unfiltered count and one 404.

    PRD 3.4: "A newly registered member has `total_committed_fte_pct` initialised
    to 0 and a `status` of `ACTIVE`, which is the only value that field ever
    takes: no transition in this system moves a staff member out of `ACTIVE`.
    Staff may be listed with filters on `discipline` and on
    `curriculum_version_certified`."  The counts come from PRD 2.3: "List responses
    populate four pagination fields inside the envelope's `meta` object: `limit`,
    `offset`, `total_count`, and `has_more`."  A read of an id that was never
    minted falls to PRD 2.6's existence rung, whose catalogue includes
    `ERR_STAFF_MEMBER_NOT_FOUND`.

    Design: Corner/endpoints/staff_member_create_read_and_filtered_listing
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")

    pitching = fixtures.create_staff_member(
        api,
        full_name="Pitching Pat",
        discipline="PITCHING",
        curriculum_version_certified="2026.1",
        certification_expires_on="2027-01-31",
    )
    hitting = fixtures.create_staff_member(
        api,
        full_name="Hitting Hal",
        discipline="HITTING",
        curriculum_version_certified="2025.2",
        certification_expires_on="2026-12-31",
    )
    for member in (pitching, hitting):
        assert_integer(member["total_committed_fte_pct"], 0, "total_committed_fte_pct")
        assert_status(member, "ACTIVE", "StaffMember")
        assert_integer(member["version"], 1, "StaffMember.version")

    read_back = validate_success(
        api.get_staff_member(pitching["id"], COMPLIANCE_OFFICER_HEADERS), 200
    )
    assert read_back["full_name"] == "Pitching Pat", (
        f"the read must echo the registered name, got {read_back['full_name']!r}"
    )
    assert read_back["discipline"] == "PITCHING", (
        f"the read must echo the discipline, got {read_back['discipline']!r}"
    )
    assert read_back["certification_expires_on"] == "2027-01-31", (
        f"the read must echo the lapse date, got {read_back['certification_expires_on']!r}"
    )

    by_discipline, discipline_meta = validate_paginated(
        api.list_staff_members(COMPLIANCE_OFFICER_HEADERS, {"discipline": "PITCHING"})
    )
    assert_integer(discipline_meta["total_count"], 1, "discipline-filtered total_count")
    assert by_discipline[0]["id"] == pitching["id"], (
        f"the discipline filter must select the pitching coach, got {by_discipline[0]['id']!r}"
    )

    by_curriculum, curriculum_meta = validate_paginated(
        api.list_staff_members(FARM_DIRECTOR_HEADERS, {"curriculum_version_certified": "2025.2"})
    )
    assert_integer(curriculum_meta["total_count"], 1, "curriculum-filtered total_count")
    assert by_curriculum[0]["id"] == hitting["id"], (
        f"the curriculum filter must select the legacy coach, got {by_curriculum[0]['id']!r}"
    )

    _, all_meta = validate_paginated(api.list_staff_members(FARM_DIRECTOR_HEADERS))
    assert_integer(all_meta["total_count"], 2, "unfiltered total_count")
    assert all_meta["has_more"] is False, (
        f"two rows inside one page leaves nothing more, got {all_meta!r}"
    )

    missing = api.get_staff_member(NON_EXISTENT_UUID, FARM_DIRECTOR_HEADERS)
    validate_error(missing, ApiErrorId.ERR_STAFF_MEMBER_NOT_FOUND.value, 404)


def test_activating_the_allocation_covers_the_required_role_and_opens_the_posture(api: ApiClient):
    """The licence sits RESTRICTED until the coach is live, then swings twice.

    PRD 2.9: "Failing that, it is `RESTRICTED` when the affiliate's
    `active_roster_count` is below the agreement's `minimum_active_players`, or
    when any role listed in the agreement's `required_staff_roles` has no
    allocation at this affiliate that is both in status `ACTIVE` and filling that
    `staff_role`."  Activation is what covers the role, per PRD 3.4: "On success,
    the member's `total_committed_fte_pct` is recomputed as the sum of `fte_pct`
    across their `ACTIVE` allocations whose half-open interval contains the current
    logical clock date, and the posture of the club's `ACTIVE` licence is
    re-derived — which is how filling the last uncovered entry in
    `required_staff_roles` lifts a club from `RESTRICTED` to `OPEN`."  Ending it
    undoes exactly that, per PRD 3.4: "Ending an allocation moves it `ACTIVE` →
    `ENDED`; recalling an active allocation moves it `ACTIVE` → `RECALLED`. Both
    recompute the member's `total_committed_fte_pct` and both re-derive the club's
    licence posture, which is how a required role losing its last `ACTIVE`
    allocation drives a club from `OPEN` down to `RESTRICTED`."

    Design: Corner/endpoints/staff_allocation_activation_covers_a_required_role_and_lifts_posture
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Coverage Club",
            "level": "DOUBLE_A",
            "market_city": "Pensacola",
            "meal_stipend_cents_per_day": 2900,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
            "required_staff_roles": ["PITCHING_COACH"],
        },
    )
    assert club["agreement"]["posture"] == "RESTRICTED", (
        f"an uncovered required role restricts the licence, got {club['agreement']['posture']!r}"
    )
    coach = fixtures.create_staff_member(
        api,
        full_name="Coverage Coach",
        discipline="PITCHING",
        curriculum_version_certified="2026.1",
        certification_expires_on="2027-01-31",
    )
    allocation = fixtures.create_allocation(
        api,
        coach["id"],
        club["affiliate_id"],
        staff_role="PITCHING_COACH",
        fte_pct=60,
        effective_start="2026-04-01",
        effective_end="2026-09-01",
    )
    assert_status(allocation, "PROPOSED", "StaffAllocation")

    proposed_only = fixtures.read_agreement(api, club["affiliate_id"], club["agreement_id"])
    assert proposed_only["posture"] == "RESTRICTED", (
        f"a merely proposed allocation covers nothing, got {proposed_only['posture']!r}"
    )
    assert_integer(
        validate_success(api.get_staff_member(coach["id"], FARM_DIRECTOR_HEADERS), 200)[
            "total_committed_fte_pct"
        ],
        0,
        "total_committed_fte_pct",
    )

    activated = fixtures.dispose_allocation(api, allocation["id"], "ACTIVATE")
    assert_status(activated, "ACTIVE", "StaffAllocation")
    assert_integer(
        validate_success(api.get_staff_member(coach["id"], FARM_DIRECTOR_HEADERS), 200)[
            "total_committed_fte_pct"
        ],
        60,
        "total_committed_fte_pct",
    )
    opened = fixtures.read_agreement(api, club["affiliate_id"], club["agreement_id"])
    assert opened["posture"] == "OPEN", (
        f"covering the last required role opens the licence, got {opened['posture']!r}"
    )
    assert_status(opened, "ACTIVE", "AffiliationAgreement")

    ended = fixtures.dispose_allocation(api, allocation["id"], "END", note="season assignment over")
    assert_status(ended, "ENDED", "StaffAllocation")
    assert_integer(
        validate_success(api.get_staff_member(coach["id"], FARM_DIRECTOR_HEADERS), 200)[
            "total_committed_fte_pct"
        ],
        0,
        "total_committed_fte_pct",
    )
    restricted_again = fixtures.read_agreement(api, club["affiliate_id"], club["agreement_id"])
    assert restricted_again["posture"] == "RESTRICTED", (
        f"the role is uncovered once more, got {restricted_again['posture']!r}"
    )
    assert_status(restricted_again, "ACTIVE", "AffiliationAgreement")


def test_the_superseding_link_must_name_a_real_row_and_is_then_discoverable(api: ApiClient):
    """An unknown predecessor 404s; a real one waives the buffer and hands the slot over.

    PRD 2.6 resolves body references before any rule runs: "Every foreign key
    supplied in the request body resolves to a stored resource (404). The body
    foreign keys are `player_id`, `affiliate_id`, `staff_member_id`, `pool_id`,
    `academy_affiliate_id`, `superseded_assignment_id` and `assignment_id`, and
    this check guards assignment creation, staff-allocation creation and
    international-signing submission."  Naming a real predecessor exempts it from
    the collision rule, per PRD 3.6: "the one prior row named in
    `superseded_assignment_id` is exempt, because naming it is an explicit
    statement that the new movement replaces it."  The link is a declared list
    filter — PRD 3.6: "Assignments can be listed with filters on `player_id`, on
    `affiliate_id`, on `superseded_assignment_id` — which is how the chain of a
    player's movements is walked — and on `status` and `assignment_type`." — and
    the handover is PRD 3.6's activation consequence: "If
    `superseded_assignment_id` was supplied and that prior assignment is currently
    `ACTIVE`, it is moved to `COMPLETED`."

    Design: Corner/endpoints/superseded_assignment_link_requires_both_assignments_to_exist
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Link Club",
            "level": "SINGLE_A",
            "market_city": "Columbia",
            "meal_stipend_cents_per_day": 2600,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    first = fixtures.active_assignment(
        api,
        club["affiliate_id"],
        player_overrides={
            "full_name": "Linked Player",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2025-06-10",
        },
        effective_date="2026-04-01",
        end_date="2026-05-31",
    )
    reading = fixtures.player_version(api, first["player_id"])

    dangling = _create_assignment(
        api,
        first["player_id"],
        club["affiliate_id"],
        expected_player_version=reading,
        movement_reason="LATERAL",
        effective_date="2026-05-01",
        end_date="2026-07-31",
        superseded_assignment_id=NON_EXISTENT_UUID,
    )
    validate_error(dangling, ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND.value, 404)

    # The same overlapping window is admitted once it names the row it replaces.
    second = validate_success(
        _create_assignment(
            api,
            first["player_id"],
            club["affiliate_id"],
            expected_player_version=reading,
            movement_reason="LATERAL",
            effective_date="2026-05-01",
            end_date="2026-07-31",
            superseded_assignment_id=first["assignment_id"],
        ),
        201,
    )
    assert_status(second, "PENDING_CLEARANCE", "PlayerAssignment")

    linked, link_meta = validate_paginated(
        api.list_assignments(
            COMPLIANCE_OFFICER_HEADERS, {"superseded_assignment_id": first["assignment_id"]}
        )
    )
    assert_integer(link_meta["total_count"], 1, "superseded-filtered total_count")
    assert linked[0]["id"] == second["id"], (
        f"the filter must return the successor row, got {linked[0]['id']!r}"
    )

    fixtures.dispose_assignment(api, second["id"], "ACTIVATE")
    assert_status(
        fixtures.read_assignment(api, first["assignment_id"]), "COMPLETED", "PlayerAssignment"
    )
    assert_integer(
        fixtures.read_affiliate(api, club["affiliate_id"])["active_roster_count"],
        1,
        "active_roster_count",
    )


def test_the_player_listing_filters_on_each_derived_standing_independently(api: ApiClient):
    """Three players in three different standing pairs, one per filter.

    PRD 3.5: "A player carries two standings on the same row, and they evolve
    independently."  Each moves on its own events — PRD 3.5: "A player moves
    `RESERVE_LIST` → `ACTIVE` when one of their level or complex assignments moves
    into `ACTIVE`, and that transition sets `current_affiliate_id` to that
    assignment's affiliate." and "A player moves `PENDING_CLEARANCE` → `CLEARED`
    when a clearance for them is issued, and `PENDING_CLEARANCE` → `RESTRICTED`
    when a clearance for them is denied." — and PRD 3.5 fixes the roster leg of a
    denial for a player holding no active assignment: "And a player moves
    `RESERVE_LIST` → `RESTRICTED` when any clearance for them is denied, with no
    further side effect."  (The companion sentence "a denial restricts the medical
    dimension without touching `roster_status` and without disturbing any active
    assignment" governs the roster-`ACTIVE` player, exercised separately.)  The listing
    exposes all of it, per PRD 3.5: "Players may be listed with filters on `origin`
    and, independently, on each of the two standings."  Reserve-list membership is
    derived, per PRD 3.5: "Players whose `origin` is `INTERNATIONAL_FA` are never
    carried on the domestic reserve list, whatever their roster standing."

    Design: Corner/endpoints/player_listing_reads_the_two_derived_status_dimensions
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Dimension Club",
            "level": "SINGLE_A",
            "market_city": "Charleston",
            "meal_stipend_cents_per_day": 2600,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    active = fixtures.active_assignment(
        api,
        club["affiliate_id"],
        player_overrides={
            "full_name": "Dimension A",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2025-06-10",
        },
        effective_date="2026-04-01",
        end_date="2026-06-30",
    )
    denied_player = fixtures.create_player(
        api, full_name="Dimension B", origin="DOMESTIC_DRAFT", signed_date="2025-06-11"
    )
    denied_clearance = fixtures.request_clearance(api, denied_player["id"], "LEVEL_ASSIGNMENT")
    fixtures.dispose_clearance(
        api, denied_clearance["id"], "DENY", restriction_note="elbow inflammation"
    )
    untouched = fixtures.create_player(
        api,
        INTERNATIONAL_SCOUT_HEADERS,
        full_name="Dimension C",
        origin="INTERNATIONAL_FA",
        signed_date="2026-01-15",
    )

    on_roster, roster_meta = validate_paginated(
        api.list_players(COMPLIANCE_OFFICER_HEADERS, {"roster_status": "ACTIVE"})
    )
    assert_integer(roster_meta["total_count"], 1, "roster-filtered total_count")
    assert on_roster[0]["id"] == active["player_id"], (
        f"only the activated player is on the roster, got {on_roster[0]['id']!r}"
    )
    assert on_roster[0]["medical_status"] == "CLEARED", (
        f"the activated player is medically cleared, got {on_roster[0]['medical_status']!r}"
    )
    assert on_roster[0]["current_affiliate_id"] == club["affiliate_id"], (
        f"activation mirrors the club, got {on_roster[0]['current_affiliate_id']!r}"
    )
    assert on_roster[0]["is_on_domestic_reserve_list"] is True, (
        f"a drafted player is carried on the reserve list, got {on_roster[0]!r}"
    )

    restricted, restricted_meta = validate_paginated(
        api.list_players(MEDICAL_DIRECTOR_HEADERS, {"medical_status": "RESTRICTED"})
    )
    assert_integer(restricted_meta["total_count"], 1, "medically-restricted total_count")
    assert restricted[0]["id"] == denied_player["id"], (
        f"only the denied player is restricted, got {restricted[0]['id']!r}"
    )
    assert restricted[0]["roster_status"] == "RESTRICTED", (
        "a denial takes a reserve-list player's roster dimension to RESTRICTED, "
        f"got {restricted[0]['roster_status']!r}"
    )

    pending, pending_meta = validate_paginated(
        api.list_players(MEDICAL_DIRECTOR_HEADERS, {"medical_status": "PENDING_CLEARANCE"})
    )
    assert_integer(pending_meta["total_count"], 1, "medically-pending total_count")
    assert pending[0]["id"] == untouched["id"], (
        f"only the untouched player is still pending, got {pending[0]['id']!r}"
    )

    international, origin_meta = validate_paginated(
        api.list_players(INTERNATIONAL_SCOUT_HEADERS, {"origin": "INTERNATIONAL_FA"})
    )
    assert_integer(origin_meta["total_count"], 1, "origin-filtered total_count")
    assert international[0]["id"] == untouched["id"], (
        f"the origin filter must select the amateur, got {international[0]['id']!r}"
    )
    assert international[0]["is_on_domestic_reserve_list"] is False, (
        f"an international amateur is never on the reserve list, got {international[0]!r}"
    )

    assert_integer(
        fixtures.read_affiliate(api, club["affiliate_id"])["reserve_list_count"],
        1,
        "reserve_list_count",
    )


def test_remediation_is_admitted_on_the_due_date_and_refused_the_day_after(api: ApiClient):
    """Two identical findings, two different clock readings, two different outcomes.

    PRD 3.1: "A deficient inspection is persisted in status `OPEN` with a
    remediation clock attached: a `MAJOR` finding gives the club thirty days from
    the `review_date` to remediate, and a `MINOR` finding gives it sixty days, and
    that deadline is written into `remediation_due_date`."  The window is what
    decides, per PRD 3.1: "Submitting remediation moves the inspection from `OPEN`
    to `REMEDIATION_SUBMITTED`, or from `REOPENED` back to
    `REMEDIATION_SUBMITTED`, and requires two things: the acting `X-User-ID` must
    be the affiliate the inspection belongs to, and the logical clock date must not
    be later than `remediation_due_date` — a submission on the due date itself is
    in time, a submission the day after is refused with
    `ERR_REMEDIATION_WINDOW_CLOSED`."  The missed one advertises itself, per PRD
    3.1: "`is_overdue` reads true whenever the inspection's status is `OPEN` or
    `REOPENED` and the logical clock date is strictly after
    `remediation_due_date`."

    Design: Corner/endpoints/remediation_submission_is_allowed_only_before_the_due_date
    """
    fixtures.set_clock(api, "2026-03-01T00:00:00Z")
    affiliate = fixtures.create_affiliate(
        api,
        COMPLIANCE_OFFICER_HEADERS,
        name="Remediation Club",
        level="HIGH_A",
        market_city="Winston",
        meal_stipend_cents_per_day=2800,
    )
    operator_headers = make_affiliate_operator_headers(affiliate["id"])
    clubhouse = fixtures.file_facility_review(api, affiliate["id"], "CLUBHOUSE", "2026-03-01", 60)
    lighting = fixtures.file_facility_review(api, affiliate["id"], "LIGHTING", "2026-03-01", 60)
    for review in (clubhouse, lighting):
        assert review["deficiency_level"] == "MAJOR", (
            f"a score of 60 bands to MAJOR, got {review['deficiency_level']!r}"
        )
        assert_status(review, "OPEN", "FacilityStandardReview")
        assert review["remediation_due_date"] == "2026-03-31", (
            f"thirty days past 2026-03-01 is 2026-03-31, got {review['remediation_due_date']!r}"
        )

    club = fixtures.read_affiliate(api, affiliate["id"])
    assert club["facility_status"] == "DEFICIENT", (
        f"two open major findings are DEFICIENT, got {club['facility_status']!r}"
    )
    assert_integer(club["open_major_deficiency_count"], 2, "open_major_deficiency_count")
    assert_decimal(club["facility_score"], "60.00", 2, "Affiliate.facility_score")

    fixtures.set_clock(api, "2026-03-15T00:00:00Z", operator_headers)
    in_time = fixtures.dispose_facility_review(
        api,
        clubhouse["id"],
        "SUBMIT_REMEDIATION",
        operator_headers,
        remediation_note="clubhouse repairs completed",
        note="clubhouse repairs completed",
    )
    assert_status(in_time, "REMEDIATION_SUBMITTED", "FacilityStandardReview")
    assert_iso_timestamp(
        in_time["remediation_submitted_at"], "FacilityStandardReview.remediation_submitted_at"
    )

    fixtures.set_clock(api, "2026-04-01T00:00:00Z", operator_headers)
    too_late = _submit_remediation(
        api, lighting["id"], operator_headers, "lighting rig replaced"
    )
    validate_error(too_late, ApiErrorId.ERR_REMEDIATION_WINDOW_CLOSED.value, 409)

    missed = fixtures.read_review(api, affiliate["id"], lighting["id"])
    assert_status(missed, "OPEN", "FacilityStandardReview")
    assert missed["is_overdue"] is True, (
        f"a clock past the due date marks the row overdue, got {missed!r}"
    )

    still_open, open_meta = validate_paginated(
        api.list_facility_reviews(affiliate["id"], COMPLIANCE_OFFICER_HEADERS, {"status": "OPEN"})
    )
    assert_integer(open_meta["total_count"], 1, "OPEN-filtered total_count")
    assert still_open[0]["id"] == lighting["id"], (
        f"only the missed row is still OPEN, got {still_open[0]['id']!r}"
    )
