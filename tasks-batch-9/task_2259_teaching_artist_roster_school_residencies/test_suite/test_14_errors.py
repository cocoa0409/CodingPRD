"""Every way the residency contract turns a well-formed request away: the seven
entity-specific not-found codes, the four uniqueness scopes, and the vetting,
clearance, roster, partnership-health, curriculum and fiscal gates."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    PANELIST_1_USER_ID,
    PANELIST_2_USER_ID,
    TEST_DEFAULTS,
    TEST_USERS,
    advance_vetting,
    api_client,
    assign_lead_artist,
    attach_observation_rubric,
    cancel_session_as_coordinator,
    create_aligned_lesson_plan,
    create_artist_applicant,
    create_arts_standard_payload,
    create_cleared_artist,
    create_confirm_payload,
    create_delivered_session,
    create_lead_artist_payload,
    create_lesson_plan_payload,
    create_payment_voucher_payload,
    create_portfolio_review_payload,
    create_residency_for_school,
    create_residency_payload,
    create_residency_status_payload,
    create_school,
    create_session_payload,
    create_standard,
    create_teaching_artist_payload,
    create_vetting_payload,
    make_school_liaison_headers,
    open_voucher,
    read_artist,
    read_lesson_plan,
    read_residency,
    read_school,
    read_session,
    record_passing_portfolio_panel,
    record_portfolio_review,
    schedule_session,
    set_clock_to_default,
    set_residency_status,
    set_roster_status,
    setup_active_residency,
    submit_lesson_plan,
    validate_error,
)

PD = TEST_USERS["program_director_headers"]
RC = TEST_USERS["roster_coordinator_headers"]
CS = TEST_USERS["curriculum_specialist_headers"]
FO = TEST_USERS["fiscal_officer_headers"]


# ==========================================================================
# Addressing something that was never persisted
# ==========================================================================
def test_each_absent_entity_reports_its_own_not_found_code(api):
    """PRD §2.8: "For any request whose path contains identifiers, the server
    resolves them strictly left to right and rejects on the **first** identifier
    that does not resolve, before evaluating anything else about the request."
    PRD §2.8: "The not-found code always names the entity type of the unresolved
    identifier: `ERR_SCHOOL_PARTNER_NOT_FOUND`, `ERR_TEACHING_ARTIST_NOT_FOUND`,
    `ERR_RESIDENCY_NOT_FOUND`, `ERR_LESSON_PLAN_NOT_FOUND`,
    `ERR_SESSION_NOT_FOUND`, `ERR_VOUCHER_NOT_FOUND`, or
    `ERR_FUNDER_REPORT_NOT_FOUND`."
    PRD §2.9: "3. Path identifiers resolve, left to right — the entity-specific
    not-found codes."

    Design: Corner/Errors/not_found_errors_for_every_path_addressed_entity
    """
    set_clock_to_default()

    validate_error(
        api_client.get_school_partner(NON_EXISTENT_UUID, PD),
        ApiErrorId.ERR_SCHOOL_PARTNER_NOT_FOUND.value,
        expected_status=404,
    )
    validate_error(
        api_client.get_teaching_artist(NON_EXISTENT_UUID, RC),
        ApiErrorId.ERR_TEACHING_ARTIST_NOT_FOUND.value,
        expected_status=404,
    )
    validate_error(
        api_client.get_residency(NON_EXISTENT_UUID, PD),
        ApiErrorId.ERR_RESIDENCY_NOT_FOUND.value,
        expected_status=404,
    )
    validate_error(
        api_client.get_lesson_plan(NON_EXISTENT_UUID, CS),
        ApiErrorId.ERR_LESSON_PLAN_NOT_FOUND.value,
        expected_status=404,
    )
    validate_error(
        api_client.get_session(NON_EXISTENT_UUID, RC),
        ApiErrorId.ERR_SESSION_NOT_FOUND.value,
        expected_status=404,
    )
    validate_error(
        api_client.get_payment_voucher(NON_EXISTENT_UUID, FO),
        ApiErrorId.ERR_VOUCHER_NOT_FOUND.value,
        expected_status=404,
    )
    validate_error(
        api_client.get_funder_report(NON_EXISTENT_UUID, PD),
        ApiErrorId.ERR_FUNDER_REPORT_NOT_FOUND.value,
        expected_status=404,
    )


# ==========================================================================
# Four uniqueness scopes, and the standards reference that is not one of them
# ==========================================================================
def test_a_repeat_roster_email_and_a_repeat_catalog_code_are_both_refused(api):
    """PRD §3.1: "A `RosterCoordinator` opens an applicant file by supplying the
    artist's `full_name`, an `email` that must be unique across the roster — a
    repeat address is refused with `ERR_DUPLICATE_EMAIL` — and the capability tags
    that will later decide what the artist may teach."
    PRD §3.5: "Each arts standard carries a `code` of 3 to 24 characters that must
    be unique across the catalog — a repeat is refused with
    `ERR_DUPLICATE_STANDARD_CODE` — a `discipline` from the six-value discipline
    domain, a `grade_band` from the four-value band domain, a `strand` of
    `CREATING`, `PERFORMING`, `RESPONDING`, or `CONNECTING`, and the standard's
    `description` text."
    PRD §2.9: "19. Uniqueness and shape constraints — `ERR_DUPLICATE_EMAIL`,
    `ERR_DUPLICATE_STANDARD_CODE`, `ERR_DUPLICATE_SEQUENCE_NO`,
    `ERR_DUPLICATE_REVIEWER`, `ERR_MAKEUP_CREDIT_UNAVAILABLE`, or
    `ERR_SESSION_UNDERDELIVERED`."

    Design: Corner/Errors/uniqueness_and_unknown_standard_code_errors
    """
    set_clock_to_default()
    artist = create_artist_applicant()

    # A different person, a different discipline, the same mailbox.
    repeat_email = api_client.create_teaching_artist(
        create_teaching_artist_payload(
            full_name="Ana R. Reyes",
            email=TEST_DEFAULTS["ARTIST_EMAIL"],
            primary_discipline="THEATER",
            secondary_disciplines=[],
            grade_bands=["G6_8"],
            languages=["en"],
        ),
        RC,
    )
    validate_error(
        repeat_email, ApiErrorId.ERR_DUPLICATE_EMAIL.value, expected_status=409
    )

    create_standard(TEST_DEFAULTS["STANDARD_CODE_CREATING"], "CREATING")
    # Uniqueness of a standard is on the code alone, not the code plus frame.
    repeat_code = api_client.create_arts_standard(
        create_arts_standard_payload(
            TEST_DEFAULTS["STANDARD_CODE_CREATING"], "RESPONDING", grade_band="G6_8"
        ),
        CS,
    )
    validate_error(
        repeat_code,
        ApiErrorId.ERR_DUPLICATE_STANDARD_CODE.value,
        expected_status=409,
    )

    survivor = read_artist(artist["id"])
    assert survivor["full_name"] == "Ana Reyes", (
        f"the refused intake must not overwrite the holder of the address, got "
        f"{survivor['full_name']}"
    )
    assert survivor["primary_discipline"] == "DANCE", (
        f"expected the original capability tags intact, got "
        f"{survivor['primary_discipline']}"
    )


def test_sequence_and_reviewer_collide_within_their_parent_while_an_unknown_code_is_a_reference_failure(
    api,
):
    """PRD §3.5: "The payload names the `residency_id`, gives the plan a `title`,
    places it in the arc with a `session_sequence_no` between 1 and 60 that must be
    unique among that residency's plans — a collision is refused with
    `ERR_DUPLICATE_SEQUENCE_NO` — lists the standards it covers in a non-empty
    `standard_codes` array whose elements must each match an existing standard's
    `code` and must contain no duplicates, and may carry a `materials_list` and an
    `adaptation_summary`, both defaulting to null."
    PRD §3.1: "A given `reviewer_user_id` may score a given artist only once; a
    repeat is refused with `ERR_DUPLICATE_REVIEWER`."
    PRD §2.8: "A standards reference is the one exception in kind rather than in
    ordering: every element of `standard_codes` must equal the `code` of an existing
    arts standard, and an element that matches none is rejected with
    `ERR_UNKNOWN_STANDARD_CODE` at HTTP 422."
    PRD §3.1: "`portfolio_review_count` is the number of distinct
    `reviewer_user_id` values that have scored this artist, and
    `portfolio_mean_composite` is the arithmetic mean of `composite_score` across
    **all** of the artist's reviews, rounded half up to two decimal places; the mean
    is null while the artist has no reviews at all."

    Design: Corner/Errors/uniqueness_and_unknown_standard_code_errors
    """
    set_clock_to_default()
    school = create_school()
    artist = create_artist_applicant()
    advance_vetting(artist["id"], "PORTFOLIO_REVIEW")
    record_portfolio_review(artist["id"], PANELIST_1_USER_ID, 3.5, 4.0, 3.2)
    create_standard(TEST_DEFAULTS["STANDARD_CODE_CREATING"], "CREATING")
    residency = create_residency_for_school(
        school["id"],
        required_strands=["CREATING"],
        collaboration_expectation="OBSERVE",
        co_planning_hours_required=0,
    )
    plan = submit_lesson_plan(
        residency["id"], [TEST_DEFAULTS["STANDARD_CODE_CREATING"]], 1
    )

    repeat_sequence = api_client.create_lesson_plan(
        create_lesson_plan_payload(
            residency["id"],
            [TEST_DEFAULTS["STANDARD_CODE_CREATING"]],
            1,
            title="Story in Motion 1 (again)",
        ),
        RC,
    )
    validate_error(
        repeat_sequence,
        ApiErrorId.ERR_DUPLICATE_SEQUENCE_NO.value,
        expected_status=409,
    )

    repeat_reviewer = api_client.create_portfolio_review(
        artist["id"],
        create_portfolio_review_payload(
            PANELIST_1_USER_ID,
            artistic_quality_score=4.0,
            pedagogical_clarity_score=4.0,
            cultural_responsiveness_score=4.0,
        ),
        RC,
    )
    validate_error(
        repeat_reviewer, ApiErrorId.ERR_DUPLICATE_REVIEWER.value, expected_status=409
    )

    # A free sequence number, but a standard the catalog has never heard of.
    unknown_code = api_client.create_lesson_plan(
        create_lesson_plan_payload(
            residency["id"], ["DA:Zz9.9.9"], 2, title="Story in Motion 2"
        ),
        RC,
    )
    validate_error(
        unknown_code,
        ApiErrorId.ERR_UNKNOWN_STANDARD_CODE.value,
        expected_status=422,
    )

    assert read_artist(artist["id"])["portfolio_review_count"] == 1, (
        "the refused repeat must leave one distinct panelist on file"
    )
    assert read_lesson_plan(plan["id"])["status"] == "SUBMITTED", (
        "the surviving plan keeps its own place in the arc"
    )


# ==========================================================================
# The two portfolio gates and the bounded demonstration counter
# ==========================================================================
def _artist_with_one_below_threshold_review() -> dict:
    """An applicant sitting in portfolio review with a single panel score whose
    composite falls short of the advance threshold."""
    set_clock_to_default()
    artist = create_artist_applicant(
        full_name="Ben Ortiz",
        email="ben.ortiz@arts.org",
        primary_discipline="MUSIC",
        secondary_disciplines=[],
        grade_bands=["G6_8"],
        languages=["en"],
    )
    advance_vetting(artist["id"], "PORTFOLIO_REVIEW")
    first = record_portfolio_review(artist["id"], PANELIST_1_USER_ID, 3.4, 3.4, 3.4)
    return {"artist": artist, "first_review": first}


def test_the_panel_count_gate_speaks_before_the_mean_composite_floor(api):
    """PRD §3.1: "The panel weights artistic quality at forty percent (a factor of
    0.40), pedagogical clarity at thirty-five percent (0.35), and cultural
    responsiveness at twenty-five percent (0.25): the review's `composite_score` is
    the sum of each score multiplied by its weight, rounded half up to two decimal
    places."
    PRD §3.1: "`portfolio_review_count` is the number of distinct
    `reviewer_user_id` values that have scored this artist, and
    `portfolio_mean_composite` is the arithmetic mean of `composite_score` across
    **all** of the artist's reviews, rounded half up to two decimal places; the mean
    is null while the artist has no reviews at all."
    PRD §3.1: "At least two distinct reviewers must have scored the portfolio, or
    the request is refused with `ERR_INSUFFICIENT_PORTFOLIO_REVIEWS`."
    PRD §3.1: "The rounded `portfolio_mean_composite` must be at least 3.50 — a
    mean of exactly 3.50 passes — or the refusal is
    `ERR_PORTFOLIO_THRESHOLD_NOT_MET`."

    Design: Corner/Errors/portfolio_and_demo_gate_errors_on_the_vetting_axis
    """
    scenario = _artist_with_one_below_threshold_review()
    artist_id = scenario["artist"]["id"]
    assert scenario["first_review"]["composite_score"] == 3.40, (
        "0.40*3.4 + 0.35*3.4 + 0.25*3.4 is 3.40, got "
        f"{scenario['first_review']['composite_score']}"
    )

    too_few = api_client.advance_vetting(
        artist_id, create_vetting_payload("DEMO_SCHEDULED"), RC
    )
    validate_error(
        too_few,
        ApiErrorId.ERR_INSUFFICIENT_PORTFOLIO_REVIEWS.value,
        expected_status=409,
    )

    # A second panelist satisfies the count, which exposes the floor beneath it.
    record_portfolio_review(artist_id, PANELIST_2_USER_ID, 3.4, 3.4, 3.4)
    artist = read_artist(artist_id)
    assert artist["portfolio_review_count"] == 2, (
        f"two distinct panelists have scored, got {artist['portfolio_review_count']}"
    )
    assert artist["portfolio_mean_composite"] == 3.40, (
        "the mean of two 3.40 composites is 3.40, got "
        f"{artist['portfolio_mean_composite']}"
    )

    below_floor = api_client.advance_vetting(
        artist_id, create_vetting_payload("DEMO_SCHEDULED"), RC
    )
    validate_error(
        below_floor,
        ApiErrorId.ERR_PORTFOLIO_THRESHOLD_NOT_MET.value,
        expected_status=409,
    )

    third = record_portfolio_review(artist_id, "panelist-3", 4.0, 3.8, 3.6)
    assert third["composite_score"] == 3.83, (
        f"0.40*4.0 + 0.35*3.8 + 0.25*3.6 is 3.83, got {third['composite_score']}"
    )
    artist = read_artist(artist_id)
    assert artist["portfolio_mean_composite"] == 3.54, (
        "the mean of 3.40, 3.40 and 3.83 is 10.63/3 rounded half up to 3.54, got "
        f"{artist['portfolio_mean_composite']}"
    )

    scheduled = advance_vetting(artist_id, "DEMO_SCHEDULED")
    assert scheduled["vetting_status"] == "DEMO_SCHEDULED", (
        f"a mean of 3.54 clears the 3.50 floor, got {scheduled['vetting_status']}"
    )


def _artist_who_has_used_both_demonstration_attempts() -> dict:
    """An applicant whose panel clears the floor and who has already failed two
    teaching demonstrations."""
    set_clock_to_default()
    artist = create_artist_applicant(
        full_name="Cleo Marsh", email="cleo.marsh@arts.org"
    )
    advance_vetting(artist["id"], "PORTFOLIO_REVIEW")
    record_passing_portfolio_panel(artist["id"])
    # The acting coordinator never scored this portfolio, so recording the
    # demonstration outcome clears the segregation-of-duties comparison.
    first = advance_vetting(artist["id"], "DEMO_SCHEDULED")
    advance_vetting(artist["id"], "DEMO_FAILED", demo_rubric_score=3.4)
    second = advance_vetting(artist["id"], "DEMO_SCHEDULED")
    advance_vetting(artist["id"], "DEMO_FAILED", demo_rubric_score=3.0)
    return {"artist": artist, "first_attempt": first, "second_attempt": second}


def test_a_third_demonstration_round_is_refused_and_the_file_is_turned_away(api):
    """PRD §3.1: "Entering `DEMO_SCHEDULED` adds one to `demo_attempt_count`."
    PRD §3.1: "And the artist must have used fewer than two demonstration
    attempts, or the refusal is `ERR_DEMO_ATTEMPT_LIMIT_REACHED`."
    PRD §3.1: "Because each entry into `DEMO_SCHEDULED` consumes an attempt and
    the limit is two, the demonstration cycle `DEMO_SCHEDULED → DEMO_FAILED →
    DEMO_SCHEDULED` can run at most twice in total."
    PRD §3.1: "`PORTFOLIO_REVIEW → DECLINED` requires the artist to currently be
    in either `PORTFOLIO_REVIEW` or `DEMO_FAILED`, and `DEMO_FAILED → DECLINED`
    carries no further precondition; both accept a `decline_reason` and both are
    terminal on the recruitment axis."

    Design: Corner/Errors/portfolio_and_demo_gate_errors_on_the_vetting_axis
    """
    scenario = _artist_who_has_used_both_demonstration_attempts()
    artist_id = scenario["artist"]["id"]
    assert scenario["first_attempt"]["demo_attempt_count"] == 1, (
        "the first entry into the demonstration consumes one attempt, got "
        f"{scenario['first_attempt']['demo_attempt_count']}"
    )
    assert scenario["second_attempt"]["demo_attempt_count"] == 2, (
        "the re-demonstration round consumes the second attempt, got "
        f"{scenario['second_attempt']['demo_attempt_count']}"
    )
    assert read_artist(artist_id)["vetting_status"] == "DEMO_FAILED"

    exhausted = api_client.advance_vetting(
        artist_id, create_vetting_payload("DEMO_SCHEDULED"), RC
    )
    validate_error(
        exhausted,
        ApiErrorId.ERR_DEMO_ATTEMPT_LIMIT_REACHED.value,
        expected_status=409,
    )

    declined = advance_vetting(
        artist_id,
        "DECLINED",
        decline_reason="demonstration standard not met after two attempts",
    )
    assert declined["vetting_status"] == "DECLINED", (
        f"a twice-failed file can still be turned away, got "
        f"{declined['vetting_status']}"
    )
    assert declined["demo_attempt_count"] == 2, (
        f"the refused third round consumed nothing, got "
        f"{declined['demo_attempt_count']}"
    )


# ==========================================================================
# Child safety and roster standing, on assignment and on the schedule
# ==========================================================================
def _draft_residency_without_a_lead() -> dict:
    """A DRAFT residency at a healthy school, a cleared artist available to lead
    it, and a second applicant still waiting on the portfolio panel."""
    set_clock_to_default()
    school = create_school()
    cleared = create_cleared_artist()
    applicant = create_artist_applicant(
        full_name="Cal Diaz",
        email="cal.diaz@arts.org",
        primary_discipline="DANCE",
        secondary_disciplines=[],
        grade_bands=["G3_5"],
        languages=["en", "es"],
    )
    residency = create_residency_for_school(
        school["id"],
        required_strands=["CREATING"],
        collaboration_expectation="OBSERVE",
        co_planning_hours_required=0,
    )
    return {
        "school": school,
        "cleared": cleared,
        "applicant": applicant,
        "residency": residency,
    }


def test_an_unscreened_lead_a_leaderless_approval_and_a_suspended_artist_are_all_refused(
    api,
):
    """PRD §2.10: "The screening gate — the artist involved must have vetting
    completed and clearance current — guards six operations: session creation,
    session confirmation, session reassignment, lead-artist assignment on a
    residency, moving a residency from draft to approved, and reinstating an artist
    onto the active roster."
    PRD §3.4: "The nominated artist must be vetted and cleared
    (`ERR_ARTIST_NOT_CLEARED`), must have a `roster_status` of `ACTIVE`
    (`ERR_ARTIST_NOT_ON_ACTIVE_ROSTER`), and must be capable of the work: the
    residency's discipline must appear among the artist's primary and secondary
    disciplines, the residency's grade band must appear in the artist's
    `grade_bands`, and the residency's instruction language must appear in the
    artist's `languages` — refused respectively with `ERR_DISCIPLINE_MISMATCH`,
    `ERR_GRADE_BAND_MISMATCH`, and `ERR_LANGUAGE_CAPABILITY_MISSING`, all at HTTP
    422."
    PRD §3.4: "`DRAFT → APPROVED` is the moment the commitment becomes real, and
    it has three preconditions: a lead artist must be assigned, or the transition is
    refused with `ERR_INVALID_STATE_TRANSITION`; that lead artist must have a
    `vetting_status` of `CLEARED` and a `roster_status` of `ACTIVE`, or the refusal
    is `ERR_ARTIST_NOT_ON_ACTIVE_ROSTER`; and the host school's
    `partnership_health` must not be `INTAKE_SUSPENDED`, or the refusal is
    `ERR_PARTNERSHIP_INTAKE_SUSPENDED`."
    PRD §3.6: "The assigned artist must be vetted and cleared
    (`ERR_ARTIST_NOT_CLEARED`), must still be covered on the session's own date
    (`ERR_CLEARANCE_EXPIRED`), and must have a `roster_status` of `ACTIVE`
    (`ERR_ARTIST_NOT_ON_ACTIVE_ROSTER`)."

    Design: Corner/Errors/clearance_and_roster_gates_on_assignment_and_scheduling
    """
    scenario = _draft_residency_without_a_lead()
    residency_id = scenario["residency"]["id"]
    assert scenario["applicant"]["vetting_status"] == "APPLIED", (
        f"the second applicant has no screening set at all, got "
        f"{scenario['applicant']['vetting_status']}"
    )

    unscreened = api_client.assign_lead_artist(
        residency_id, create_lead_artist_payload(scenario["applicant"]["id"]), PD
    )
    validate_error(
        unscreened, ApiErrorId.ERR_ARTIST_NOT_CLEARED.value, expected_status=403
    )

    leaderless = api_client.set_residency_status(
        residency_id, create_residency_status_payload("APPROVED"), PD
    )
    validate_error(
        leaderless,
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        expected_status=409,
    )

    # Staff it properly and drive it all the way to ACTIVE.
    assign_lead_artist(residency_id, scenario["cleared"]["id"])
    set_residency_status(residency_id, "APPROVED")
    create_standard(TEST_DEFAULTS["STANDARD_CODE_CREATING"], "CREATING")
    plan = create_aligned_lesson_plan(
        residency_id, [TEST_DEFAULTS["STANDARD_CODE_CREATING"]], 1
    )
    active = set_residency_status(residency_id, "ACTIVE")
    assert active["status"] == "ACTIVE"

    suspended = set_roster_status(
        scenario["cleared"]["id"], "SUSPENDED", reason="pending conduct review"
    )
    assert suspended["roster_status"] == "SUSPENDED"
    assert suspended["vetting_status"] == "CLEARED", (
        "suspension moves the roster axis only, so the screening gate still "
        f"passes, got {suspended['vetting_status']}"
    )

    version = read_residency(residency_id)["version"]
    off_roster = api_client.create_session(
        create_session_payload(
            residency_id,
            scenario["cleared"]["id"],
            version,
            session_date="2026-09-15",
            start_time="09:00",
            end_time="10:00",
            lesson_plan_id=plan["id"],
        ),
        RC,
    )
    validate_error(
        off_roster,
        ApiErrorId.ERR_ARTIST_NOT_ON_ACTIVE_ROSTER.value,
        expected_status=409,
    )

    residency = read_residency(residency_id)
    assert residency["sessions_open_count"] == 0, (
        f"the refused creation opened nothing, got {residency['sessions_open_count']}"
    )
    assert residency["sessions_unscheduled_count"] == 10, (
        "the whole contracted allotment is still unscheduled, got "
        f"{residency['sessions_unscheduled_count']}"
    )
    assert residency["version"] == version, (
        f"a refused request mutates no row, so the version holds at {version}, got "
        f"{residency['version']}"
    )


def test_the_three_capability_dimensions_are_checked_independently(api):
    """PRD §3.4: "The nominated artist must be vetted and cleared
    (`ERR_ARTIST_NOT_CLEARED`), must have a `roster_status` of `ACTIVE`
    (`ERR_ARTIST_NOT_ON_ACTIVE_ROSTER`), and must be capable of the work: the
    residency's discipline must appear among the artist's primary and secondary
    disciplines, the residency's grade band must appear in the artist's
    `grade_bands`, and the residency's instruction language must appear in the
    artist's `languages` — refused respectively with `ERR_DISCIPLINE_MISMATCH`,
    `ERR_GRADE_BAND_MISMATCH`, and `ERR_LANGUAGE_CAPABILITY_MISSING`, all at HTTP
    422."
    PRD §3.4: "A freshly scoped residency has a `status` of `DRAFT`, a
    `staffing_status` of `LEAD_VACANT`, and every ledger counter and money field at
    zero."
    PRD §3.4: "If `lead_artist_id` is null, `staffing_status` is `LEAD_VACANT`."

    Design: Corner/Errors/capability_tag_mismatch_errors_on_lead_artist_assignment
    """
    set_clock_to_default()
    school = create_school()
    artist = create_cleared_artist(
        full_name="Dara Kim",
        email="dara.kim@arts.org",
        primary_discipline="DANCE",
        secondary_disciplines=["THEATER"],
        grade_bands=["K_2"],
        languages=["en"],
        roster_tier_assigned="TEACHING_ARTIST",
    )
    assert artist["vetting_status"] == "CLEARED"
    assert artist["roster_status"] == "ACTIVE", (
        f"clearance activates the roster axis, got {artist['roster_status']}"
    )

    # Each residency differs from the artist's tags along exactly one dimension.
    wrong_band = create_residency_for_school(
        school["id"],
        title="Story in Motion",
        discipline="DANCE",
        grade_band="G3_5",
        instruction_language="en",
        collaboration_expectation="OBSERVE",
        co_planning_hours_required=0,
    )
    wrong_language = create_residency_for_school(
        school["id"],
        title="Primary Movement",
        discipline="DANCE",
        grade_band="K_2",
        instruction_language="es",
        collaboration_expectation="OBSERVE",
        co_planning_hours_required=0,
    )
    wrong_discipline = create_residency_for_school(
        school["id"],
        title="Primary Sound Lab",
        discipline="MUSIC",
        grade_band="K_2",
        instruction_language="en",
        collaboration_expectation="OBSERVE",
        co_planning_hours_required=0,
    )

    validate_error(
        api_client.assign_lead_artist(
            wrong_band["id"], create_lead_artist_payload(artist["id"]), PD
        ),
        ApiErrorId.ERR_GRADE_BAND_MISMATCH.value,
        expected_status=422,
    )
    validate_error(
        api_client.assign_lead_artist(
            wrong_language["id"], create_lead_artist_payload(artist["id"]), PD
        ),
        ApiErrorId.ERR_LANGUAGE_CAPABILITY_MISSING.value,
        expected_status=422,
    )
    validate_error(
        api_client.assign_lead_artist(
            wrong_discipline["id"], create_lead_artist_payload(artist["id"]), PD
        ),
        ApiErrorId.ERR_DISCIPLINE_MISMATCH.value,
        expected_status=422,
    )

    for residency in (wrong_band, wrong_language, wrong_discipline):
        after = read_residency(residency["id"])
        assert after["lead_artist_id"] is None, (
            f"{after['title']} must keep no lead after a refused assignment, got "
            f"{after['lead_artist_id']}"
        )
        assert after["staffing_status"] == "LEAD_VACANT", (
            f"{after['title']} has a null lead, so staffing reads LEAD_VACANT, got "
            f"{after['staffing_status']}"
        )


# ==========================================================================
# Partnership health as a gate rather than a label
# ==========================================================================
def _watch_school_after_the_lead_was_suspended() -> dict:
    """An ACTIVE residency whose only session was vacated when its lead artist
    was suspended, leaving the school on watch; the artist is then reinstated."""
    set_clock_to_default()
    scenario = setup_active_residency(required_strands=["CREATING"])
    scenario["session"] = schedule_session(
        scenario["residency"]["id"],
        scenario["artist"]["id"],
        session_date="2026-09-15",
        lesson_plan_id=scenario["lesson_plan"]["id"],
    )
    set_roster_status(
        scenario["artist"]["id"], "SUSPENDED", reason="pending conduct review"
    )
    scenario["artist"] = set_roster_status(
        scenario["artist"]["id"], "ACTIVE", reason="review closed with no finding"
    )
    return scenario


def test_watch_health_blocks_a_new_regular_session_on_the_understaffed_residency(api):
    """PRD §3.2: "Link three: for every residency touched by link two,
    `vacated_session_count` gains one and `staffing_status` is recomputed, and if the
    suspended artist was that residency's `lead_artist_id`, the lead reference is
    cleared to null so the residency reads `LEAD_VACANT`."
    PRD §3.3: "Otherwise, if any residency in that set has a `staffing_status` of
    `AT_RISK` or `LEAD_VACANT`, health reads `WATCH`."
    PRD §3.3: "`WATCH` is narrower: it blocks session creation only, and only when
    the target residency's `staffing_status` is not `STAFFED` and the requested
    `session_type` is not `MAKEUP`; that refusal is `ERR_PARTNERSHIP_HEALTH_GATE`,
    also at HTTP 403."

    Design: Corner/Errors/partnership_health_gate_then_intake_suspension
    """
    scenario = _watch_school_after_the_lead_was_suspended()
    residency_id = scenario["residency"]["id"]
    assert scenario["artist"]["roster_status"] == "ACTIVE", (
        f"the artist is back on the roster, got {scenario['artist']['roster_status']}"
    )

    residency = read_residency(residency_id)
    assert residency["vacated_session_count"] == 1, (
        f"the suspension emptied the one session, got "
        f"{residency['vacated_session_count']}"
    )
    assert residency["lead_artist_id"] is None, (
        "the suspended artist held the lead of a residency the vacating touched, "
        f"so the reference is cleared, got {residency['lead_artist_id']}"
    )
    assert residency["staffing_status"] == "LEAD_VACANT", (
        f"a null lead outranks the vacated session, got {residency['staffing_status']}"
    )
    assert read_school(scenario["school"]["id"])["partnership_health"] == "WATCH", (
        "an open residency that is not staffed puts the school on watch"
    )

    version = residency["version"]
    refused = api_client.create_session(
        create_session_payload(
            residency_id,
            scenario["artist"]["id"],
            version,
            session_date="2026-09-22",
            start_time="09:00",
            end_time="10:00",
            session_type="REGULAR",
            lesson_plan_id=scenario["lesson_plan"]["id"],
        ),
        RC,
    )
    validate_error(
        refused,
        ApiErrorId.ERR_PARTNERSHIP_HEALTH_GATE.value,
        expected_status=403,
    )

    after = read_residency(residency_id)
    assert after["sessions_open_count"] == 1, (
        f"only the vacated session is still open, got {after['sessions_open_count']}"
    )
    assert after["version"] == version, (
        f"the refused creation left the residency at version {version}, got "
        f"{after['version']}"
    )


def test_a_suspended_residency_suspends_intake_at_its_school(api):
    """PRD §3.4: "The host school's `partnership_health` is then recomputed, which
    — because a suspended residency is present — yields `INTAKE_SUSPENDED`."
    PRD §3.3: "If any residency in that set is `SUSPENDED`, health reads
    `INTAKE_SUSPENDED`."
    PRD §3.3: "The size of that same set is published as `open_residency_count`."
    PRD §3.3: "`INTAKE_SUSPENDED` blocks three things at that school: creating a
    new residency, moving a residency from `DRAFT` to `APPROVED`, and creating a
    session — all refused with `ERR_PARTNERSHIP_INTAKE_SUSPENDED` at HTTP 403."

    Design: Corner/Errors/partnership_health_gate_then_intake_suspension
    """
    set_clock_to_default()
    scenario = setup_active_residency(required_strands=["CREATING"])
    school_id = scenario["school"]["id"]
    assert read_school(school_id)["partnership_health"] == "HEALTHY"

    suspended = set_residency_status(
        scenario["residency"]["id"], "SUSPENDED", reason="school leadership change"
    )
    assert suspended["status"] == "SUSPENDED"

    school = read_school(school_id)
    assert school["partnership_health"] == "INTAKE_SUSPENDED", (
        f"a suspended residency outranks every other health input, got "
        f"{school['partnership_health']}"
    )
    assert school["open_residency_count"] == 1, (
        "a SUSPENDED residency is still part of the open set, got "
        f"{school['open_residency_count']}"
    )

    refused = api_client.create_residency(
        create_residency_payload(
            school_id,
            title="Winter Movement Lab",
            grade_band="G6_8",
            instruction_language="en",
            contracted_session_count=6,
            budget_cents=120000,
            required_strands=["CREATING"],
            collaboration_expectation="OBSERVE",
            co_planning_hours_required=0,
            term_start_date="2027-01-12",
            term_end_date="2027-03-30",
            enrolled_student_count=30,
        ),
        PD,
    )
    validate_error(
        refused,
        ApiErrorId.ERR_PARTNERSHIP_INTAKE_SUSPENDED.value,
        expected_status=403,
    )

    assert read_school(school_id)["open_residency_count"] == 1, (
        "the refused scoping added nothing to the school's open set"
    )


# ==========================================================================
# Curriculum linkage is a per-session question
# ==========================================================================
def test_a_session_carrying_no_lesson_plan_cannot_be_confirmed(api):
    """PRD §3.4: "`APPROVED → ACTIVE` is gated on curriculum readiness and is
    described from the curriculum side in §3.5: at least one lesson plan of this
    residency must be `ALIGNED`, or the transition is refused with
    `ERR_NO_ALIGNED_LESSON_PLAN`; and the union of `covered_strands` across all of
    this residency's `ALIGNED` plans must include every entry of `required_strands`,
    or the refusal is `ERR_STANDARDS_COVERAGE_INCOMPLETE`."
    PRD §3.6: "It may set a `session_type` of `REGULAR` or `MAKEUP`, defaulting to
    `REGULAR`; it may name the `lesson_plan_id` the session will teach; and for a
    make-up session it names the cancelled session whose credit it consumes through
    `makeup_for_session_id`."
    PRD §3.6: "The session must name a `lesson_plan_id` whose plan is `ALIGNED`, or
    the refusal is `ERR_NO_ALIGNED_LESSON_PLAN`."
    PRD §3.6: "The server evaluates the session fee rules of §3.7 as though the
    artist had taught the full `session_length_minutes`, writes that amount into the
    session's own `encumbered_cents`, adds it to the residency's `encumbered_cents`,
    and recomputes `available_cents`."

    Design: Corner/Errors/confirmation_without_an_aligned_lesson_plan_is_refused
    """
    set_clock_to_default()
    scenario = setup_active_residency(required_strands=["CREATING"])
    # The residency's own plan is aligned — that is what let it go ACTIVE — but
    # this session was put on the calendar without naming any plan.
    session = schedule_session(
        scenario["residency"]["id"],
        scenario["artist"]["id"],
        session_date="2026-09-15",
    )
    assert session["lesson_plan_id"] is None, (
        f"the session teaches no named plan, got {session['lesson_plan_id']}"
    )
    assert read_lesson_plan(scenario["lesson_plan"]["id"])["status"] == "ALIGNED"

    refused = api_client.confirm_session(
        session["id"],
        create_confirm_payload(),
        make_school_liaison_headers(scenario["school"]["id"]),
    )
    validate_error(
        refused, ApiErrorId.ERR_NO_ALIGNED_LESSON_PLAN.value, expected_status=409
    )

    assert read_session(session["id"])["status"] == "PLANNED", (
        "the refused confirmation leaves the session on the calendar unconfirmed"
    )
    residency = read_residency(scenario["residency"]["id"])
    assert residency["status"] == "ACTIVE", (
        f"the residency-level curriculum gate was satisfied, got {residency['status']}"
    )
    assert residency["encumbered_cents"] == 0, (
        f"a refused confirmation encumbers nothing, got "
        f"{residency['encumbered_cents']}"
    )


# ==========================================================================
# The three fiscal refusals on a deliberately under-funded residency
# ==========================================================================
def _single_session_shoestring_residency() -> dict:
    """An ACTIVE residency contracted for one session against a budget too small
    to cover a single full-length fee, with that one session already planned."""
    set_clock_to_default()
    scenario = setup_active_residency(
        residency_overrides={
            "title": "Shoestring Studio",
            "contracted_session_count": 1,
            "budget_cents": 10000,
            "enrolled_student_count": 24,
        },
        required_strands=["CREATING"],
    )
    scenario["session"] = schedule_session(
        scenario["residency"]["id"],
        scenario["artist"]["id"],
        session_date="2026-09-15",
        lesson_plan_id=scenario["lesson_plan"]["id"],
    )
    scenario["residency"] = read_residency(scenario["residency"]["id"])
    return scenario


def test_the_allotment_the_makeup_credit_and_the_budget_each_refuse_separately(api):
    """PRD §3.4: "Approval initializes the allotment by setting
    `sessions_unscheduled_count` to `contracted_session_count`, and initializes the
    money ledger by setting `available_cents` to `budget_cents` with
    `encumbered_cents` and `disbursed_cents` both at zero."
    PRD §3.6: "Creating the session updates the residency's ledger: a `REGULAR`
    session subtracts one from `sessions_unscheduled_count`, while a `MAKEUP` session
    leaves that counter alone and instead sets `makeup_consumed` to true on its origin
    session and subtracts one from `makeup_credits_outstanding`."
    PRD §3.6: "And the allotment must support the request: a `REGULAR` session
    requires `sessions_unscheduled_count` to be at least 1, or the refusal is
    `ERR_SESSION_ALLOTMENT_EXHAUSTED`; a `MAKEUP` session requires
    `makeup_credits_outstanding` to be at least 1 together with a matching origin
    session, and a make-up request that names a session which is not an unconsumed,
    make-up-eligible cancellation of the **same** residency — or which omits
    `makeup_for_session_id` altogether — is refused with
    `ERR_MAKEUP_CREDIT_UNAVAILABLE`."
    PRD §3.6: "If that would drive `available_cents` below zero, the transition is
    refused with `ERR_RESIDENCY_BUDGET_EXCEEDED` instead."

    Design: Corner/Errors/fiscal_allotment_and_budget_and_makeup_errors
    """
    scenario = _single_session_shoestring_residency()
    residency_id = scenario["residency"]["id"]
    version = scenario["residency"]["version"]
    assert scenario["residency"]["sessions_unscheduled_count"] == 0, (
        "the single contracted unit has been turned into a session, got "
        f"{scenario['residency']['sessions_unscheduled_count']}"
    )
    assert scenario["residency"]["makeup_credits_outstanding"] == 0, (
        "nothing has been cancelled, so no credit is outstanding, got "
        f"{scenario['residency']['makeup_credits_outstanding']}"
    )
    assert scenario["residency"]["available_cents"] == 10000

    exhausted = api_client.create_session(
        create_session_payload(
            residency_id,
            scenario["artist"]["id"],
            version,
            session_date="2026-09-22",
            start_time="09:00",
            end_time="10:00",
            session_type="REGULAR",
            lesson_plan_id=scenario["lesson_plan"]["id"],
        ),
        RC,
    )
    validate_error(
        exhausted,
        ApiErrorId.ERR_SESSION_ALLOTMENT_EXHAUSTED.value,
        expected_status=409,
    )

    # A make-up must consume a credit issued by a cancellation; the named origin
    # is still sitting on the calendar as PLANNED.
    no_credit = api_client.create_session(
        create_session_payload(
            residency_id,
            scenario["artist"]["id"],
            version,
            session_date="2026-09-29",
            start_time="09:00",
            end_time="10:00",
            session_type="MAKEUP",
            makeup_for_session_id=scenario["session"]["id"],
            lesson_plan_id=scenario["lesson_plan"]["id"],
        ),
        RC,
    )
    validate_error(
        no_credit,
        ApiErrorId.ERR_MAKEUP_CREDIT_UNAVAILABLE.value,
        expected_status=409,
    )

    # Confirming the one legitimate session would hold a full-length fee far
    # larger than the whole 10000-cent budget.
    overdrawn = api_client.confirm_session(
        scenario["session"]["id"], create_confirm_payload(), RC
    )
    validate_error(
        overdrawn,
        ApiErrorId.ERR_RESIDENCY_BUDGET_EXCEEDED.value,
        expected_status=409,
    )

    session = read_session(scenario["session"]["id"])
    assert session["status"] == "PLANNED", (
        f"the refused confirmation leaves the session planned, got {session['status']}"
    )
    assert session["encumbered_cents"] == 0, (
        f"an unconfirmed session holds nothing, got {session['encumbered_cents']}"
    )
    residency = read_residency(residency_id)
    assert residency["encumbered_cents"] == 0
    assert residency["available_cents"] == 10000, (
        f"the whole budget is still free, got {residency['available_cents']}"
    )
    assert residency["version"] == version, (
        f"three refusals mutated nothing, so the version holds at {version}, got "
        f"{residency['version']}"
    )


# ==========================================================================
# Closing the books: two different gates, and one session claimed twice
# ==========================================================================
def _residency_with_one_claimed_delivery_and_one_open_session() -> dict:
    """An ACTIVE residency contracted for two sessions: the first delivered,
    evaluated and claimed on a DRAFT voucher, the second still planned."""
    set_clock_to_default()
    scenario = setup_active_residency(
        residency_overrides={"contracted_session_count": 2},
        required_strands=["CREATING"],
    )
    delivered = create_delivered_session(
        scenario,
        session_date="2026-09-15",
        students_present_count=22,
        minutes_delivered=60,
    )
    attach_observation_rubric(delivered["id"])
    planned = schedule_session(
        scenario["residency"]["id"],
        scenario["artist"]["id"],
        session_date="2026-09-22",
        lesson_plan_id=scenario["lesson_plan"]["id"],
    )
    scenario["delivered_session"] = delivered
    scenario["planned_session"] = planned
    scenario["voucher"] = open_voucher(
        scenario["artist"]["id"],
        scenario["residency"]["id"],
        [delivered["id"]],
        period_start="2026-09-01",
        period_end="2026-09-30",
    )
    return scenario


def test_completion_needs_an_empty_schedule_and_closing_needs_a_settled_voucher(api):
    """PRD §3.4: "`ACTIVE → COMPLETED` requires that `sessions_open_count` be
    exactly zero — no `PLANNED`, `CONFIRMED`, or `VACATED` session may remain — or
    the request is refused with `ERR_RESIDENCY_HAS_OPEN_SESSIONS`."
    PRD §3.8: "Creation already applies three of the linkage rules that submission
    will re-apply: a session already claimed by a different voucher is refused with
    `ERR_SESSION_ALREADY_VOUCHERED`; a claimed session lacking an
    `OBSERVATION_RUBRIC` evaluation with all three rubric scores is refused with
    `ERR_EVALUATION_MISSING`; and a claimed session whose `session_date` falls
    outside the closed period from `period_start` to `period_end` is refused with
    `ERR_VOUCHER_PERIOD_MISMATCH`."
    PRD §3.8: "A new voucher starts with a `status` of `DRAFT`, both review tracks
    at `PENDING`, and its `void_reason` null; each claimed session gets its
    `payment_voucher_id` pointed at the new voucher."
    PRD §3.4: "No payment voucher of this residency may be in `DRAFT` or
    `SUBMITTED`, and `encumbered_cents` must be exactly zero; either violation is
    refused with `ERR_RESIDENCY_HAS_OPEN_VOUCHERS`."

    Design: Corner/Errors/residency_finalisation_and_double_claim_errors
    """
    scenario = _residency_with_one_claimed_delivery_and_one_open_session()
    residency_id = scenario["residency"]["id"]
    voucher = scenario["voucher"]
    assert voucher["status"] == "DRAFT", (
        f"a freshly opened voucher is a draft, got {voucher['status']}"
    )
    assert voucher["total_cents"] == scenario["delivered_session"]["payable_cents"], (
        "the voucher aggregates the one claimed session, got "
        f"{voucher['total_cents']} against "
        f"{scenario['delivered_session']['payable_cents']}"
    )
    assert (
        read_session(scenario["delivered_session"]["id"])["payment_voucher_id"]
        == voucher["id"]
    )

    open_sessions = api_client.set_residency_status(
        residency_id, create_residency_status_payload("COMPLETED"), PD
    )
    validate_error(
        open_sessions,
        ApiErrorId.ERR_RESIDENCY_HAS_OPEN_SESSIONS.value,
        expected_status=409,
    )

    second_claim = api_client.create_payment_voucher(
        create_payment_voucher_payload(
            scenario["artist"]["id"],
            residency_id,
            [scenario["delivered_session"]["id"]],
            period_start="2026-09-01",
            period_end="2026-09-30",
        ),
        RC,
    )
    validate_error(
        second_claim,
        ApiErrorId.ERR_SESSION_ALREADY_VOUCHERED.value,
        expected_status=409,
    )

    cancelled = cancel_session_as_coordinator(
        scenario["planned_session"]["id"], "LOW_ENROLLMENT", note="class merged"
    )
    assert cancelled["status"] == "CANCELLED_SCHOOL"
    completed = set_residency_status(residency_id, "COMPLETED")
    assert completed["status"] == "COMPLETED", (
        f"with the schedule empty the completion goes through, got "
        f"{completed['status']}"
    )
    assert completed["sessions_open_count"] == 0

    open_vouchers = api_client.set_residency_status(
        residency_id, create_residency_status_payload("CLOSED"), PD
    )
    validate_error(
        open_vouchers,
        ApiErrorId.ERR_RESIDENCY_HAS_OPEN_VOUCHERS.value,
        expected_status=409,
    )

    residency = read_residency(residency_id)
    assert residency["status"] == "COMPLETED", (
        f"the refused close leaves the residency completed, got {residency['status']}"
    )
    assert residency["encumbered_cents"] == voucher["total_cents"], (
        "the delivered session still holds its payable against the budget, got "
        f"{residency['encumbered_cents']} against {voucher['total_cents']}"
    )
