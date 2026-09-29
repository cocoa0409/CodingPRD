"""Session-level refusals: the co-teaching gate, the closed residency term, the
travel buffer that only bites across schools, and which check speaks first when a
create request is both malformed and points at nobody."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assign_lead_artist,
    create_aligned_lesson_plan,
    create_cleared_artist,
    create_confirm_payload,
    create_residency_for_school,
    create_school,
    create_session_payload,
    create_standard,
    make_school_liaison_headers,
    read_residency,
    read_session,
    schedule_session,
    set_clock_to_default,
    set_residency_status,
    setup_active_residency,
    validate_error,
    validate_success,
)

RC = TEST_USERS["roster_coordinator_headers"]


def _attempt_session(
    residency_id: str,
    assigned_artist_id: str,
    expected_residency_version: int,
    session_date: str = "2026-09-15",
    start_time: str = "09:00",
    end_time: str = "10:00",
    **overrides,
):
    """Post a session creation and hand back the raw response for inspection."""
    payload = create_session_payload(
        residency_id,
        assigned_artist_id,
        expected_residency_version,
        session_date=session_date,
        start_time=start_time,
        end_time=end_time,
        **overrides,
    )
    return api_client.create_session(payload, RC)


# ==========================================================================
# The classroom-teacher collaboration expectation
# ==========================================================================
def _active_co_teach_residency_with_a_planned_session() -> dict:
    """Active CO_TEACH residency at Riverbend with one PLANNED 09:00-10:00
    session on the books for its cleared lead artist."""
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


def test_co_teach_confirmation_encumbers_only_once_co_planning_is_reported_done(api):
    """PRD §3.6: "When the residency's `collaboration_expectation` is `CO_TEACH`,
    the supplied `co_planning_completed` must be true, or the refusal is
    `ERR_CO_PLANNING_INCOMPLETE`; the `OBSERVE` and `PLANNING_ONLY` expectations
    impose no such requirement."
    PRD §3.6: "Confirmation persists both supplied fields and then **encumbers**
    the money it expects to owe."
    PRD §3.6: "The server evaluates the session fee rules of §3.7 as though the
    artist had taught the full `session_length_minutes`, writes that amount into
    the session's own `encumbered_cents`, adds it to the residency's
    `encumbered_cents`, and recomputes `available_cents`."
    PRD §2.12: "Available plus encumbered plus disbursed always equals
    `budget_cents`."

    Design: Corner/Validations/co_planning_incomplete_blocks_co_teach_confirmation_then_passes
    """
    scenario = _active_co_teach_residency_with_a_planned_session()
    residency_id = scenario["residency"]["id"]
    session_id = scenario["session"]["id"]
    liaison = make_school_liaison_headers(scenario["school"]["id"])
    assert scenario["residency"]["collaboration_expectation"] == "CO_TEACH", (
        "the co-planning rule is conditional on the expectation, got "
        f"{scenario['residency']['collaboration_expectation']}"
    )

    refused = api_client.confirm_session(
        session_id, create_confirm_payload(co_planning_completed=False), liaison
    )
    validate_error(
        refused, ApiErrorId.ERR_CO_PLANNING_INCOMPLETE.value, expected_status=409
    )

    # A refused confirmation must not have written a partial encumbrance.
    mid = read_residency(residency_id)
    assert mid["encumbered_cents"] == 0, (
        f"the rejected confirmation holds no money, got {mid['encumbered_cents']}"
    )
    assert mid["available_cents"] == 200000, (
        "the whole budget is still free after the refusal, got "
        f"{mid['available_cents']}"
    )
    assert read_session(session_id)["status"] == "PLANNED"

    confirmed = validate_success(
        api_client.confirm_session(
            session_id, create_confirm_payload(co_planning_completed=True), liaison
        ),
        expected_status=200,
    )
    assert confirmed["status"] == "CONFIRMED", (
        f"the identical call with co-planning done goes through, got {confirmed['status']}"
    )
    assert confirmed["co_planning_completed"] is True
    assert confirmed["encumbered_cents"] == 13974, (
        "DANCE 12000 graded to 12600 at G3_5, tiered to 11340 as APPRENTICE, plus "
        "a 1134 lead premium and a 1500 Spanish-language premium, holds 13974, got "
        f"{confirmed['encumbered_cents']}"
    )

    residency = read_residency(residency_id)
    assert residency["encumbered_cents"] == 13974, (
        f"the session's hold lands on the residency too, got {residency['encumbered_cents']}"
    )
    assert residency["available_cents"] == 186026, (
        f"200000 less the 13974 now held, got {residency['available_cents']}"
    )


# ==========================================================================
# The residency term as a closed date interval
# ==========================================================================
def test_a_session_dated_the_day_after_the_term_ends_is_refused(api):
    """PRD §3.6: "The `session_date` must fall inside the closed interval from
    `term_start_date` to `term_end_date`, or the request is refused with
    `ERR_SESSION_OUTSIDE_RESIDENCY_TERM`."
    PRD §3.4: "It fixes the calendar with a `term_start_date` and a
    `term_end_date` no earlier than the start, both inclusive bounds on session
    dates."
    PRD §3.6: "Creating the session updates the residency's ledger: a `REGULAR`
    session subtracts one from `sessions_unscheduled_count`, while a `MAKEUP`
    session leaves that counter alone and instead sets `makeup_consumed` to true
    on its origin session and subtracts one from `makeup_credits_outstanding`."

    Design: Corner/Validations/session_on_the_last_term_day_passes_while_the_next_day_fails
    """
    set_clock_to_default()
    scenario = setup_active_residency()
    residency_id = scenario["residency"]["id"]
    assert scenario["residency"]["term_end_date"] == "2026-12-18"

    version = read_residency(residency_id)["version"]
    res = _attempt_session(
        residency_id,
        scenario["artist"]["id"],
        version,
        session_date="2026-12-19",
        lesson_plan_id=scenario["lesson_plan"]["id"],
    )
    validate_error(
        res,
        ApiErrorId.ERR_SESSION_OUTSIDE_RESIDENCY_TERM.value,
        expected_status=409,
    )

    residency = read_residency(residency_id)
    assert residency["sessions_unscheduled_count"] == 10, (
        "the refused request must not draw allotment, got "
        f"{residency['sessions_unscheduled_count']}"
    )
    assert residency["sessions_open_count"] == 0
    assert residency["version"] == version, (
        f"a refusal leaves the residency untouched, got {residency['version']}"
    )


def test_a_session_dated_on_the_term_end_date_itself_is_accepted(api):
    """PRD §3.4: "It fixes the calendar with a `term_start_date` and a
    `term_end_date` no earlier than the start, both inclusive bounds on session
    dates."
    PRD §3.6: "The `session_date` must fall inside the closed interval from
    `term_start_date` to `term_end_date`, or the request is refused with
    `ERR_SESSION_OUTSIDE_RESIDENCY_TERM`."
    PRD §3.6: "A new session is created in `PLANNED` status with
    `vacated_artist_id`, `payment_voucher_id`, `cancel_reason`, and every delivery
    and money field still null or zero, and with `is_substitute` false,
    `co_planning_completed` false, `makeup_eligible` false, and `makeup_consumed`
    false."
    PRD §3.6: "Either way `sessions_open_count` gains one, `projected_cost_cents`
    is recomputed, and the residency's `version` increments."

    Design: Corner/Validations/session_on_the_last_term_day_passes_while_the_next_day_fails
    """
    set_clock_to_default()
    scenario = setup_active_residency()
    residency_id = scenario["residency"]["id"]
    artist_id = scenario["artist"]["id"]
    plan_id = scenario["lesson_plan"]["id"]

    # One version read serves both attempts: the refusal does not bump it.
    version = read_residency(residency_id)["version"]
    validate_error(
        _attempt_session(
            residency_id,
            artist_id,
            version,
            session_date="2026-12-19",
            lesson_plan_id=plan_id,
        ),
        ApiErrorId.ERR_SESSION_OUTSIDE_RESIDENCY_TERM.value,
        expected_status=409,
    )

    accepted = validate_success(
        _attempt_session(
            residency_id,
            artist_id,
            version,
            session_date="2026-12-18",
            lesson_plan_id=plan_id,
        ),
        expected_status=201,
    )
    assert accepted["session_date"] == "2026-12-18", (
        "the last day of the term is inside the interval, got "
        f"{accepted['session_date']}"
    )
    assert accepted["status"] == "PLANNED"
    assert accepted["encumbered_cents"] == 0, (
        f"a planned session holds nothing yet, got {accepted['encumbered_cents']}"
    )

    residency = read_residency(residency_id)
    assert residency["sessions_unscheduled_count"] == 9, (
        "the accepted session draws one allotment unit, got "
        f"{residency['sessions_unscheduled_count']}"
    )
    assert residency["sessions_open_count"] == 1


# ==========================================================================
# The 45-minute travel buffer, scoped to school changes
# ==========================================================================
def _one_artist_teaching_at_two_schools() -> dict:
    """One cleared artist leading an active dance residency at each of two
    two-room schools, with a 09:00-10:00 session booked at the first."""
    set_clock_to_default()
    riverbend = create_school()
    kestrel = create_school(
        name="Kestrel Ridge Middle",
        district_name="Kestrel USD",
        grade_span="6-8",
        total_enrollment=500,
        frl_pct=0.41,
        ell_pct=0.19,
        iep_pct=0.11,
    )
    artist = create_cleared_artist()

    first = create_residency_for_school(
        riverbend["id"],
        collaboration_expectation="OBSERVE",
        co_planning_hours_required=0,
        required_strands=["CREATING"],
    )
    assign_lead_artist(first["id"], artist["id"])
    set_residency_status(first["id"], "APPROVED")
    create_standard("DA:Cr1.1.4", "CREATING")
    first_plan = create_aligned_lesson_plan(first["id"], ["DA:Cr1.1.4"], 1)
    first = set_residency_status(first["id"], "ACTIVE")

    second = create_residency_for_school(
        kestrel["id"],
        title="Rhythm Lab",
        grade_band="G6_8",
        instruction_language="en",
        contracted_session_count=6,
        budget_cents=120000,
        materials_stipend_cents=0,
        collaboration_expectation="OBSERVE",
        co_planning_hours_required=0,
        required_strands=["CREATING"],
        enrolled_student_count=30,
    )
    assign_lead_artist(second["id"], artist["id"])
    set_residency_status(second["id"], "APPROVED")
    create_standard("DA:Cr1.1.7", "CREATING", grade_band="G6_8")
    second_plan = create_aligned_lesson_plan(second["id"], ["DA:Cr1.1.7"], 1)
    second = set_residency_status(second["id"], "ACTIVE")

    anchor = schedule_session(
        first["id"],
        artist["id"],
        session_date="2026-09-15",
        start_time="09:00",
        end_time="10:00",
        lesson_plan_id=first_plan["id"],
    )
    return {
        "riverbend": riverbend,
        "kestrel": kestrel,
        "artist": artist,
        "first": first,
        "second": second,
        "first_plan": first_plan,
        "second_plan": second_plan,
        "anchor": anchor,
    }


def test_a_fifteen_minute_gap_at_the_same_school_needs_no_travel_buffer(api):
    """PRD §3.6: "If they do not overlap but the two sessions belong to
    residencies at *different* schools and the gap between the intervals is less
    than 45 minutes, the refusal is `ERR_TRAVEL_BUFFER_VIOLATION`."
    PRD §3.6: "The gap is the non-negative distance between the two intervals, so
    two sessions that abut exactly — gap of zero — are permitted at the same
    school and rejected at different schools."
    PRD §3.6: "Either way `sessions_open_count` gains one, `projected_cost_cents`
    is recomputed, and the residency's `version` increments."

    Design: Corner/Validations/travel_buffer_applies_only_between_different_schools
    """
    scenario = _one_artist_teaching_at_two_schools()
    first_id = scenario["first"]["id"]

    version = read_residency(first_id)["version"]
    accepted = validate_success(
        _attempt_session(
            first_id,
            scenario["artist"]["id"],
            version,
            session_date="2026-09-15",
            start_time="10:15",
            end_time="11:15",
            lesson_plan_id=scenario["first_plan"]["id"],
        ),
        expected_status=201,
    )
    assert accepted["status"] == "PLANNED", (
        "a 15-minute turnaround inside one building is fine, got "
        f"{accepted['status']}"
    )
    assert accepted["start_time"] == "10:15"

    assert read_session(scenario["anchor"]["id"])["status"] == "PLANNED"
    first = read_residency(first_id)
    assert first["sessions_open_count"] == 2, (
        f"both back-to-back sessions are open, got {first['sessions_open_count']}"
    )
    assert first["sessions_unscheduled_count"] == 8


def test_crossing_schools_needs_a_full_forty_five_minute_gap(api):
    """PRD §3.6: "**The artist** is checked pairwise against each of their other
    blocking sessions on the same date."
    PRD §3.6: "A session occupies the **half-open** local interval running from
    its `start_time` up to but not including its `end_time`, on its
    `session_date`."
    PRD §3.6: "If they do not overlap but the two sessions belong to residencies
    at *different* schools and the gap between the intervals is less than 45
    minutes, the refusal is `ERR_TRAVEL_BUFFER_VIOLATION`."
    PRD §3.6: "The gap is the non-negative distance between the two intervals, so
    two sessions that abut exactly — gap of zero — are permitted at the same
    school and rejected at different schools."

    Design: Corner/Validations/travel_buffer_applies_only_between_different_schools
    """
    scenario = _one_artist_teaching_at_two_schools()
    artist_id = scenario["artist"]["id"]
    second_id = scenario["second"]["id"]
    # The artist's morning at Riverbend now ends at 11:15.
    schedule_session(
        scenario["first"]["id"],
        artist_id,
        session_date="2026-09-15",
        start_time="10:15",
        end_time="11:15",
        lesson_plan_id=scenario["first_plan"]["id"],
    )

    version = read_residency(second_id)["version"]
    refused = _attempt_session(
        second_id,
        artist_id,
        version,
        session_date="2026-09-15",
        start_time="11:30",
        end_time="12:30",
        lesson_plan_id=scenario["second_plan"]["id"],
    )
    validate_error(
        refused, ApiErrorId.ERR_TRAVEL_BUFFER_VIOLATION.value, expected_status=409
    )
    assert read_residency(second_id)["version"] == version, (
        "the refused cross-school booking leaves the second residency untouched"
    )

    accepted = validate_success(
        _attempt_session(
            second_id,
            artist_id,
            version,
            session_date="2026-09-15",
            start_time="12:00",
            end_time="13:00",
            lesson_plan_id=scenario["second_plan"]["id"],
        ),
        expected_status=201,
    )
    assert accepted["status"] == "PLANNED", (
        "a gap of exactly 45 minutes from 11:15 clears the buffer, got "
        f"{accepted['status']}"
    )
    assert accepted["start_time"] == "12:00"

    second = read_residency(second_id)
    assert second["sessions_open_count"] == 1, (
        f"only the 12:00 booking stuck, got {second['sessions_open_count']}"
    )
    assert second["sessions_unscheduled_count"] == 5, (
        "six contracted sessions less the one now open, got "
        f"{second['sessions_unscheduled_count']}"
    )
    assert read_residency(scenario["first"]["id"])["sessions_open_count"] == 2


# ==========================================================================
# Payload shape before body-reference resolution
# ==========================================================================
def _draft_residency_with_an_empty_roster() -> dict:
    """A school with one DRAFT residency and no artist on file at all, so any
    artist id in a session body is unresolvable."""
    set_clock_to_default()
    school = create_school()
    return {"school": school, "residency": create_residency_for_school(school["id"])}


def test_a_bad_session_type_is_reported_before_an_unresolvable_artist_id(api):
    """PRD §2.9: "Checks are therefore evaluated in a fixed global order, and the
    **first** violated check decides the response."
    PRD §2.9: "4. Required body fields are present, and every supplied value
    satisfies its declared type, enum domain, numeric range, date or time format,
    and array constraints including non-emptiness and absence of duplicates —
    `ERR_INVALID_REQUEST`."
    PRD §2.9: "5. Body-supplied identifiers resolve, and every standards code
    resolves — the entity-specific not-found codes, or
    `ERR_UNKNOWN_STANDARD_CODE`."
    PRD §3.6: "It may set a `session_type` of `REGULAR` or `MAKEUP`, defaulting to
    `REGULAR`; it may name the `lesson_plan_id` the session will teach; and for a
    make-up session it names the cancelled session whose credit it consumes
    through `makeup_for_session_id`."

    Design: Corner/Validations/shape_check_precedes_body_reference_resolution_on_session_create
    """
    scenario = _draft_residency_with_an_empty_roster()
    residency_id = scenario["residency"]["id"]

    version = read_residency(residency_id)["version"]
    res = _attempt_session(
        residency_id,
        NON_EXISTENT_UUID,
        version,
        session_date="2026-09-15",
        session_type="SPECIAL",
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

    residency = read_residency(residency_id)
    assert residency["version"] == version, (
        f"a rejected create leaves the residency alone, got {residency['version']}"
    )
    assert residency["sessions_open_count"] == 0


def test_the_unresolvable_artist_id_surfaces_once_the_session_type_is_legal(api):
    """PRD §2.9: "Checks are therefore evaluated in a fixed global order, and the
    **first** violated check decides the response."
    PRD §2.9: "5. Body-supplied identifiers resolve, and every standards code
    resolves — the entity-specific not-found codes, or
    `ERR_UNKNOWN_STANDARD_CODE`."
    PRD §2.8: "Identifiers supplied in a request **body** are resolved in the same
    style and with the same codes, once path resolution has succeeded and the
    payload has passed type and range checking."
    PRD §2.8: "The not-found code always names the entity type of the unresolved
    identifier: `ERR_SCHOOL_PARTNER_NOT_FOUND`, `ERR_TEACHING_ARTIST_NOT_FOUND`,
    `ERR_RESIDENCY_NOT_FOUND`, `ERR_LESSON_PLAN_NOT_FOUND`,
    `ERR_SESSION_NOT_FOUND`, `ERR_VOUCHER_NOT_FOUND`, or
    `ERR_FUNDER_REPORT_NOT_FOUND`."

    Design: Corner/Validations/shape_check_precedes_body_reference_resolution_on_session_create
    """
    scenario = _draft_residency_with_an_empty_roster()
    residency_id = scenario["residency"]["id"]

    version = read_residency(residency_id)["version"]
    validate_error(
        _attempt_session(
            residency_id,
            NON_EXISTENT_UUID,
            version,
            session_date="2026-09-15",
            session_type="SPECIAL",
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=400,
    )

    # Same unknown artist, same residency, only the enum corrected: the
    # reference failure was real all along.
    surfaced = _attempt_session(
        residency_id,
        NON_EXISTENT_UUID,
        version,
        session_date="2026-09-15",
        session_type="REGULAR",
    )
    validate_error(
        surfaced, ApiErrorId.ERR_TEACHING_ARTIST_NOT_FOUND.value, expected_status=404
    )

    residency = read_residency(residency_id)
    assert residency["version"] == version
    assert residency["sessions_open_count"] == 0
