"""The standards catalog and its filters, the derived staffing and partnership
readings that a lead-artist assignment moves, and the open-work condition that
guards retirement."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assign_lead_artist,
    cancel_session_as_coordinator,
    create_arts_standard_payload,
    create_cleared_artist,
    create_lead_artist_payload,
    create_residency_for_school,
    create_roster_status_payload,
    create_school,
    create_standard,
    read_artist,
    read_residency,
    read_school,
    read_session,
    schedule_session,
    set_clock_to_default,
    setup_active_residency,
    validate_error,
    validate_paginated,
    validate_success,
)

CS = TEST_USERS["curriculum_specialist_headers"]
PD = TEST_USERS["program_director_headers"]
RC = TEST_USERS["roster_coordinator_headers"]
TA = TEST_USERS["teaching_artist_headers"]


# ==========================================================================
# The standards catalog
# ==========================================================================
def _three_catalogued_standards() -> dict:
    """A three-row standards catalog spanning two disciplines, two bands, and
    two strands."""
    set_clock_to_default()
    return {
        "dance_creating": create_standard("DA:Cr1.1.4", "CREATING"),
        "dance_responding": create_standard("DA:Re7.1.4", "RESPONDING"),
        "music_creating": create_standard(
            "MU:Cr1.1.7", "CREATING", discipline="MUSIC", grade_band="G6_8"
        ),
    }


def test_the_catalog_filters_narrow_to_a_single_matching_standard(api):
    """PRD §3.5: "Each arts standard carries a `code` of 3 to 24 characters that
    must be unique across the catalog — a repeat is refused with
    `ERR_DUPLICATE_STANDARD_CODE` — a `discipline` from the six-value discipline
    domain, a `grade_band` from the four-value band domain, a `strand` of
    `CREATING`, `PERFORMING`, `RESPONDING`, or `CONNECTING`, and the standard's
    `description` text."
    PRD §3.5: "The catalog is browsable with `discipline`, `grade_band`, and
    `strand` filters."
    PRD §2.3: "Every list response reports `limit`, `offset`, `total_count`, and
    `has_more` inside the envelope's `meta` object."

    Design: Corner/Endpoints/arts_standard_create_then_filtered_catalog_read
    """
    catalog = _three_catalogued_standards()
    assert catalog["dance_creating"]["code"] == "DA:Cr1.1.4"
    assert catalog["music_creating"]["discipline"] == "MUSIC"

    res = api_client.list_arts_standards(
        TA,
        {
            "discipline": "DANCE",
            "grade_band": "G3_5",
            "strand": "CREATING",
            "limit": 10,
            "offset": 0,
        },
    )
    rows, meta = validate_paginated(res)
    assert meta["total_count"] == 1, (
        "only the dance G3_5 creating standard satisfies all three filters, got "
        f"{meta['total_count']}"
    )
    assert meta["has_more"] is False, (
        f"one row inside a limit of ten leaves nothing behind, got {meta['has_more']}"
    )
    assert [row["id"] for row in rows] == [catalog["dance_creating"]["id"]], (
        "the responding standard and the music standard are both filtered out"
    )
    assert rows[0]["strand"] == "CREATING"
    assert rows[0]["grade_band"] == "G3_5"


def test_reposting_an_existing_standard_code_is_refused(api):
    """PRD §3.5: "Each arts standard carries a `code` of 3 to 24 characters that
    must be unique across the catalog — a repeat is refused with
    `ERR_DUPLICATE_STANDARD_CODE` — a `discipline` from the six-value discipline
    domain, a `grade_band` from the four-value band domain, a `strand` of
    `CREATING`, `PERFORMING`, `RESPONDING`, or `CONNECTING`, and the standard's
    `description` text."
    PRD §2.9: "19. Uniqueness and shape constraints — `ERR_DUPLICATE_EMAIL`,
    `ERR_DUPLICATE_STANDARD_CODE`, `ERR_DUPLICATE_SEQUENCE_NO`,
    `ERR_DUPLICATE_REVIEWER`, `ERR_MAKEUP_CREDIT_UNAVAILABLE`, or
    `ERR_SESSION_UNDERDELIVERED`."

    Design: Corner/Endpoints/arts_standard_create_then_filtered_catalog_read
    """
    catalog = _three_catalogued_standards()

    res = api_client.create_arts_standard(
        create_arts_standard_payload(
            "DA:Cr1.1.4",
            "CREATING",
            description="Explore movement ideas drawn from a story (resubmitted).",
        ),
        CS,
    )
    validate_error(
        res, ApiErrorId.ERR_DUPLICATE_STANDARD_CODE.value, expected_status=409
    )

    rows, meta = validate_paginated(api_client.list_arts_standards(TA))
    assert meta["total_count"] == 3, (
        f"the rejected repeat wrote no fourth row, got {meta['total_count']}"
    )
    assert catalog["dance_creating"]["id"] in [row["id"] for row in rows]


# ==========================================================================
# Staffing status and partnership health, recomputed together
# ==========================================================================
def _school_with_an_unstaffed_draft_residency() -> dict:
    """A school with one freshly scoped residency that has no lead artist yet,
    plus a cleared artist waiting to be named."""
    set_clock_to_default()
    school = create_school()
    return {
        "school": school,
        "artist": create_cleared_artist(),
        "residency": create_residency_for_school(school["id"]),
    }


def test_a_residency_without_a_lead_artist_puts_its_school_on_watch(api):
    """PRD §3.4: "If `lead_artist_id` is null, `staffing_status` is
    `LEAD_VACANT`."
    PRD §3.3: "The server looks at the school's residencies whose status is
    `DRAFT`, `APPROVED`, `ACTIVE`, or `SUSPENDED` — residencies that are
    `COMPLETED`, `CLOSED`, or `CANCELLED` never affect health at all."
    PRD §3.3: "Otherwise, if any residency in that set has a `staffing_status` of
    `AT_RISK` or `LEAD_VACANT`, health reads `WATCH`."
    PRD §3.3: "The size of that same set is published as `open_residency_count`."

    Design: Corner/Endpoints/lead_artist_assignment_recomputes_staffing_and_school_health
    """
    scenario = _school_with_an_unstaffed_draft_residency()

    residency = read_residency(scenario["residency"]["id"])
    assert residency["status"] == "DRAFT"
    assert residency["lead_artist_id"] is None
    assert residency["staffing_status"] == "LEAD_VACANT", (
        f"nobody leads this residency yet, got {residency['staffing_status']}"
    )

    school = read_school(scenario["school"]["id"])
    assert school["partnership_health"] == "WATCH", (
        "a vacant lead on an in-flight residency drops the school to WATCH, got "
        f"{school['partnership_health']}"
    )
    assert school["open_residency_count"] == 1, (
        f"the one DRAFT residency counts as open, got {school['open_residency_count']}"
    )


def test_naming_the_lead_artist_lifts_both_the_staffing_and_the_health_reading(api):
    """PRD §3.4: "Assigning the lead artist is a separate step available to a
    `ProgramDirector` or a `RosterCoordinator`, which names a `teaching_artist_id`
    and writes it into `lead_artist_id`."
    PRD §3.4: "Assignment recomputes `staffing_status`, recomputes the school's
    `partnership_health`, and re-projects `projected_cost_cents`."
    PRD §3.4: "Otherwise it is `STAFFED`."
    PRD §3.3: "Otherwise health reads `HEALTHY`."

    Design: Corner/Endpoints/lead_artist_assignment_recomputes_staffing_and_school_health
    """
    scenario = _school_with_an_unstaffed_draft_residency()
    residency_id = scenario["residency"]["id"]
    artist_id = scenario["artist"]["id"]

    assigned = validate_success(
        api_client.assign_lead_artist(
            residency_id, create_lead_artist_payload(artist_id), RC
        ),
        expected_status=200,
    )
    assert assigned["lead_artist_id"] == artist_id
    assert assigned["staffing_status"] == "STAFFED", (
        "a named lead with no vacated session reads STAFFED, got "
        f"{assigned['staffing_status']}"
    )
    assert assigned["status"] == "DRAFT", (
        f"naming a lead does not advance the lifecycle, got {assigned['status']}"
    )

    school = read_school(scenario["school"]["id"])
    assert school["partnership_health"] == "HEALTHY", (
        "with no vacant lead left at the school, health returns to HEALTHY, got "
        f"{school['partnership_health']}"
    )
    assert school["open_residency_count"] == 1, (
        "staffing a residency does not change how many are in flight, got "
        f"{school['open_residency_count']}"
    )


def _school_hosting_a_staffed_and_a_vacant_residency() -> dict:
    """One school running two residencies: a staffed dance residency for the
    lower grades and an unstaffed middle-grades one."""
    set_clock_to_default()
    school = create_school()
    artist = create_cleared_artist()

    staffed = create_residency_for_school(
        school["id"], collaboration_expectation="OBSERVE", co_planning_hours_required=0
    )
    staffed = assign_lead_artist(staffed["id"], artist["id"])
    vacant = create_residency_for_school(
        school["id"],
        title="Rhythm Lab",
        grade_band="G6_8",
        instruction_language="en",
        contracted_session_count=6,
        budget_cents=120000,
        materials_stipend_cents=0,
        collaboration_expectation="OBSERVE",
        co_planning_hours_required=0,
        enrolled_student_count=30,
    )
    return {
        "school": school,
        "artist": artist,
        "staffed": staffed,
        "vacant": vacant,
    }


def test_school_health_reflects_the_worst_of_its_in_flight_residencies(api):
    """PRD §3.3: "The server looks at the school's residencies whose status is
    `DRAFT`, `APPROVED`, `ACTIVE`, or `SUSPENDED` — residencies that are
    `COMPLETED`, `CLOSED`, or `CANCELLED` never affect health at all."
    PRD §3.3: "Otherwise, if any residency in that set has a `staffing_status` of
    `AT_RISK` or `LEAD_VACANT`, health reads `WATCH`."
    PRD §3.3: "Otherwise health reads `HEALTHY`."
    PRD §3.3: "The size of that same set is published as `open_residency_count`."

    Design: Corner/Endpoints/school_partner_read_returns_computed_health_over_two_residencies
    """
    scenario = _school_hosting_a_staffed_and_a_vacant_residency()
    school_id = scenario["school"]["id"]
    assert scenario["staffed"]["staffing_status"] == "STAFFED"
    assert scenario["vacant"]["staffing_status"] == "LEAD_VACANT", (
        f"the second residency has no lead, got {scenario['vacant']['staffing_status']}"
    )

    before = read_school(school_id)
    assert before["partnership_health"] == "WATCH", (
        "one vacant lead out of two residencies is enough for WATCH, got "
        f"{before['partnership_health']}"
    )
    assert before["open_residency_count"] == 2, (
        f"both residencies are in flight, got {before['open_residency_count']}"
    )

    filled = validate_success(
        api_client.assign_lead_artist(
            scenario["vacant"]["id"],
            create_lead_artist_payload(scenario["artist"]["id"]),
            RC,
        ),
        expected_status=200,
    )
    assert filled["staffing_status"] == "STAFFED"

    after = read_school(school_id)
    assert after["partnership_health"] == "HEALTHY", (
        "no residency at the school is vacant or at risk any more, got "
        f"{after['partnership_health']}"
    )
    assert after["open_residency_count"] == 2, (
        f"the in-flight set is unchanged in size, got {after['open_residency_count']}"
    )
    assert read_residency(scenario["staffed"]["id"])["staffing_status"] == "STAFFED"


# ==========================================================================
# Retirement, conditional on the artist's open calendar
# ==========================================================================
def _active_residency_with_one_planned_session() -> dict:
    """Active residency whose lead artist still holds one PLANNED session."""
    set_clock_to_default()
    scenario = setup_active_residency()
    scenario["session"] = schedule_session(
        scenario["residency"]["id"],
        scenario["artist"]["id"],
        session_date="2026-09-15",
        start_time="09:00",
        end_time="10:00",
        lesson_plan_id=scenario["lesson_plan"]["id"],
    )
    return scenario


def test_retiring_an_artist_who_still_holds_a_planned_session_is_refused(api):
    """PRD §3.2: "From `ACTIVE` or from `PROBATION` it requires that the artist
    hold no session in `PLANNED` or `CONFIRMED`, or the request is refused with
    `ERR_ARTIST_HAS_OPEN_SESSIONS`."
    PRD §3.2: "A `ProgramDirector` moves the roster axis by naming a
    `to_roster_status`, optionally with a `reason`."
    PRD §3.6: "A new session is created in `PLANNED` status with
    `vacated_artist_id`, `payment_voucher_id`, `cancel_reason`, and every delivery
    and money field still null or zero, and with `is_substitute` false,
    `co_planning_completed` false, `makeup_eligible` false, and `makeup_consumed`
    false."

    Design: Corner/Endpoints/retirement_is_conditional_on_having_no_open_sessions
    """
    scenario = _active_residency_with_one_planned_session()
    artist_id = scenario["artist"]["id"]
    assert scenario["session"]["status"] == "PLANNED"

    res = api_client.set_roster_status(
        artist_id,
        create_roster_status_payload("RETIRED", reason="leaving the region"),
        PD,
    )
    validate_error(
        res, ApiErrorId.ERR_ARTIST_HAS_OPEN_SESSIONS.value, expected_status=409
    )

    artist = read_artist(artist_id)
    assert artist["roster_status"] == "ACTIVE", (
        f"the refused retirement leaves the artist on the roster, got {artist['roster_status']}"
    )
    assert read_session(scenario["session"]["id"])["status"] == "PLANNED"


def test_retirement_goes_through_once_the_last_planned_session_is_cancelled(api):
    """PRD §3.2: "From `ACTIVE` or from `PROBATION` it requires that the artist
    hold no session in `PLANNED` or `CONFIRMED`, or the request is refused with
    `ERR_ARTIST_HAS_OPEN_SESSIONS`."
    PRD §3.7: "`makeup_eligible` becomes true when the reason is
    `SCHOOL_CLOSURE`, `TESTING_CONFLICT`, `ARTIST_ILLNESS`, or `ARTIST_NO_SHOW`,
    and false when it is `LOW_ENROLLMENT` or `RESIDENCY_DESCOPED`."
    PRD §3.7: "From `PLANNED` there is nothing held, so the effects are just the
    eligibility flag and the ledger move: `sessions_open_count` loses one, and
    `makeup_credits_outstanding` gains one when the session was make-up-eligible
    while `sessions_forfeited_count` gains one when it was not."

    Design: Corner/Endpoints/retirement_is_conditional_on_having_no_open_sessions
    """
    scenario = _active_residency_with_one_planned_session()
    artist_id = scenario["artist"]["id"]
    residency_id = scenario["residency"]["id"]
    retire = create_roster_status_payload("RETIRED", reason="leaving the region")
    validate_error(
        api_client.set_roster_status(artist_id, retire, PD),
        ApiErrorId.ERR_ARTIST_HAS_OPEN_SESSIONS.value,
        expected_status=409,
    )

    cancelled = cancel_session_as_coordinator(
        scenario["session"]["id"], "LOW_ENROLLMENT", note="class roster too thin"
    )
    assert cancelled["status"] == "CANCELLED_SCHOOL"
    assert cancelled["makeup_eligible"] is False, (
        "a low-enrolment cancellation earns no make-up credit, got "
        f"{cancelled['makeup_eligible']}"
    )

    retired = validate_success(
        api_client.set_roster_status(artist_id, retire, PD), expected_status=200
    )
    assert retired["roster_status"] == "RETIRED", (
        f"with no open session left the move is allowed, got {retired['roster_status']}"
    )
    assert retired["vetting_status"] == "CLEARED", (
        "retirement moves the roster axis only, and leaves clearance alone, got "
        f"{retired['vetting_status']}"
    )

    residency = read_residency(residency_id)
    assert residency["sessions_open_count"] == 0, (
        f"the cancelled session is no longer open, got {residency['sessions_open_count']}"
    )
    assert residency["sessions_forfeited_count"] == 1, (
        "an ineligible cancellation forfeits the session outright, got "
        f"{residency['sessions_forfeited_count']}"
    )
    assert residency["makeup_credits_outstanding"] == 0, (
        f"no credit was earned, got {residency['makeup_credits_outstanding']}"
    )
    assert residency["encumbered_cents"] == 0, (
        "the session was never confirmed so nothing was held, got "
        f"{residency['encumbered_cents']}"
    )
