"""Who may act: the role table on scheduling, intake and the roster axis, the
401-versus-403 split, an artist's self-scoping on delivery, and the two duty
separations that read the operator identifier rather than the role."""
from test_helpers import (
    ApiErrorId,
    DEMO_EVALUATOR_USER_ID,
    NON_EXISTENT_UUID,
    PANELIST_1_USER_ID,
    PANELIST_2_USER_ID,
    PROGRAM_DIRECTOR_USER_ID,
    TEST_USERS,
    advance_vetting,
    api_client,
    build_user_headers,
    create_artist_applicant,
    create_cancel_payload,
    create_cleared_artist,
    create_confirm_payload,
    create_confirmed_session,
    create_deliver_payload,
    create_roster_status_payload,
    create_school_partner_payload,
    create_session_payload,
    create_teaching_artist_payload,
    create_vetting_payload,
    make_roster_coordinator_headers,
    make_school_liaison_headers,
    make_teaching_artist_headers,
    read_artist,
    read_residency,
    read_session,
    record_passing_portfolio_panel,
    schedule_session,
    set_clock_to_default,
    setup_active_residency,
    setup_approved_residency,
    validate_error,
    validate_paginated,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]
RC = TEST_USERS["roster_coordinator_headers"]
CS = TEST_USERS["curriculum_specialist_headers"]
SL = TEST_USERS["school_liaison_headers"]


# ==========================================================================
# Authorisation is per operation, not per entity
# ==========================================================================
def _approved_residency() -> dict:
    """A Riverbend residency approved with its allotment initialized, so the
    curriculum side can read the schedule it may not write."""
    set_clock_to_default()
    return setup_approved_residency()


def test_curriculum_specialist_is_refused_on_both_scheduling_endpoints(api):
    """PRD §2.1: "If the headers are well-formed but the acting role is not
    permitted to invoke the requested operation, the rejection is
    `ERR_UNAUTHORIZED`."
    PRD §2.9: "2. The acting role is permitted on the endpoint —
    `ERR_UNAUTHORIZED`."
    PRD §2.9: "3. Path identifiers resolve, left to right — the entity-specific
    not-found codes."
    PRD §3.6: "The schedule is searchable with `residency_id`,
    `assigned_artist_id`, `vacated_artist_id`, `lesson_plan_id`,
    `makeup_for_session_id`, `payment_voucher_id`, and `status` filters plus a
    `session_date_from` and `session_date_to` date range."

    Design: Corner/RBAC/curriculum_specialist_may_read_but_never_schedule
    """
    scenario = _approved_residency()
    residency_id = scenario["residency"]["id"]
    version = read_residency(residency_id)["version"]

    creation = api_client.create_session(
        create_session_payload(
            residency_id,
            scenario["artist"]["id"],
            version,
            session_date="2026-09-15",
            start_time="09:00",
            end_time="10:00",
        ),
        CS,
    )
    validate_error(creation, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)

    # The session id is deliberately one that does not exist: the role check
    # runs before the path identifier is ever resolved, so the answer is the
    # authorisation refusal rather than a not-found.
    confirmation = api_client.confirm_session(
        NON_EXISTENT_UUID,
        create_confirm_payload("Ms. Delgado", True),
        CS,
    )
    validate_error(confirmation, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)

    # Reading the same collection is unrestricted — the curriculum role owns
    # alignment and needs to see the arc it is aligning to.
    sessions, meta = validate_paginated(
        api_client.list_sessions(
            CS, params={"residency_id": residency_id, "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 0, (
        f"neither refused write may have opened a session, got {meta['total_count']}"
    )
    assert sessions == [], f"the schedule must still be empty, got {sessions}"

    residency = read_residency(residency_id)
    assert residency["version"] == version, (
        "a refused request mutates nothing, so the residency version must stand "
        f"at {version}, got {residency['version']}"
    )
    assert residency["sessions_unscheduled_count"] == 10, (
        "approval initialized the whole contracted allotment and no session drew "
        f"on it, got {residency['sessions_unscheduled_count']}"
    )
    assert residency["sessions_open_count"] == 0


# ==========================================================================
# Priority 1 and priority 2 are different rules with different codes
# ==========================================================================
def _headers_without_a_role_declaration() -> dict:
    """A request that names its principal but never declares the capacity it
    acts in."""
    headers = dict(build_user_headers(PROGRAM_DIRECTOR_USER_ID, "ProgramDirector"))
    del headers["X-User-Role"]
    return headers


def test_absent_role_header_is_unauthenticated_while_a_wrong_role_is_unauthorized(
    api,
):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying
    the acting principal, and `X-User-Role`, declaring the capacity in which it
    acts."
    PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the
    six recognized role names, the request is rejected with
    `ERR_UNAUTHENTICATED`."
    PRD §2.1: "If the headers are well-formed but the acting role is not
    permitted to invoke the requested operation, the rejection is
    `ERR_UNAUTHORIZED`."
    PRD §3.3: "A newly registered school starts with `partnership_health` of
    `HEALTHY` and `open_residency_count` of zero."

    Design: Corner/RBAC/missing_role_header_is_unauthenticated_not_unauthorized
    """
    set_clock_to_default()
    payload = create_school_partner_payload(
        name="Nowhere Elementary",
        district_name="Nowhere USD",
        grade_span="K-5",
        concurrent_session_capacity=1,
        total_enrollment=300,
        frl_pct=0.5,
        ell_pct=0.2,
        iep_pct=0.1,
    )

    unauthenticated = api_client.create_school_partner(
        payload, _headers_without_a_role_declaration()
    )
    validate_error(
        unauthenticated, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401
    )

    unauthorized = api_client.create_school_partner(payload, SL)
    validate_error(
        unauthorized, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403
    )

    # The identical payload from the one role that owns school registration is
    # accepted, so nothing about the body was ever at fault.
    school = validate_success(
        api_client.create_school_partner(payload, PD), expected_status=201
    )
    assert school["partnership_health"] == "HEALTHY", (
        f"a fresh partnership starts healthy, got {school['partnership_health']}"
    )
    assert school["open_residency_count"] == 0


# ==========================================================================
# The TeachingArtist role is entity-backed: holding it is not enough
# ==========================================================================
def _confirmed_session_and_a_second_artist() -> dict:
    """An active Riverbend residency with one confirmed session held by Ana
    Reyes, plus a freshly intaken artist who holds no session at all."""
    set_clock_to_default()
    scenario = setup_active_residency()
    scenario["session"] = create_confirmed_session(scenario)
    scenario["other_artist"] = create_artist_applicant(
        full_name="Cal Diaz",
        email="cal.diaz@arts.org",
        primary_discipline="DANCE",
        secondary_disciplines=[],
        grade_bands=["G3_5"],
        languages=["en", "es"],
    )
    return scenario


def test_an_artist_may_not_report_delivery_of_a_session_held_by_another(api):
    """PRD §2.1: "When `X-User-Role` is `TeachingArtist`, `X-User-ID` is the `id`
    of the acting `TeachingArtist`; ownership checks on any resource that
    references a `TeachingArtist` compare the resource's artist reference to
    `X-User-ID` — specifically a session's `assigned_artist_id`, a lesson plan's
    `author_artist_id`, and a voucher's `teaching_artist_id`."
    PRD §2.1: "An ownership violation by one of the two entity-backed roles is
    rejected with `ERR_ACTOR_NOT_RESOURCE_OWNER`."
    PRD §3.7: "Only the artist who holds the session may report its delivery:
    the acting `X-User-ID` must equal `assigned_artist_id`, or the request is
    refused with `ERR_ACTOR_NOT_RESOURCE_OWNER`."
    PRD §3.6: "A new session is created in `PLANNED` status with
    `vacated_artist_id`, `payment_voucher_id`, `cancel_reason`, and every
    delivery and money field still null or zero, and with `is_substitute` false,
    `co_planning_completed` false, `makeup_eligible` false, and
    `makeup_consumed` false."

    Design: Corner/RBAC/teaching_artist_cannot_deliver_another_artists_session
    """
    scenario = _confirmed_session_and_a_second_artist()
    session_id = scenario["session"]["id"]
    intruder = scenario["other_artist"]
    assert intruder["vetting_status"] == "APPLIED", (
        f"the second artist is a bare applicant, got {intruder['vetting_status']}"
    )
    assert scenario["session"]["assigned_artist_id"] == scenario["artist"]["id"]

    res = api_client.deliver_session(
        session_id,
        create_deliver_payload(
            students_present_count=22,
            minutes_delivered=60,
            travel_miles=0.0,
            materials_spend_cents=0,
        ),
        make_teaching_artist_headers(intruder["id"]),
    )
    validate_error(
        res, ApiErrorId.ERR_ACTOR_NOT_RESOURCE_OWNER.value, expected_status=403
    )

    session = read_session(session_id)
    assert session["status"] == "CONFIRMED", (
        f"the refused report may not terminate the session, got {session['status']}"
    )
    # PRD §3.6 pins the un-delivered state of these fields as "still null or
    # zero", so either reading is faithful; what the refusal must not do is
    # record a real delivery figure.
    assert session["fee_cents"] in (None, 0), (
        f"no delivery figure was recorded, got {session['fee_cents']}"
    )
    assert session["payable_cents"] in (None, 0)
    assert session["encumbered_cents"] == 13974, (
        "the confirmation hold is untouched by the refusal, got "
        f"{session['encumbered_cents']}"
    )


def test_the_assigned_artist_reports_delivery_and_earns_the_lead_language_fee(api):
    """PRD §3.7: "Compute a lead premium of ten percent (a factor of 0.10) of
    that tiered amount, rounded, but only when the session's
    `assigned_artist_id` equals the residency's `lead_artist_id`; otherwise the
    premium is zero."
    PRD §3.7: "Compute a language premium of a flat 1,500 cents, but only when
    the residency's `instruction_language` is something other than `en` **and**
    that language appears in the artist's `languages`; otherwise it is zero."
    PRD §3.7: "The session's `payable_cents` is the sum of `fee_cents`,
    `travel_reimbursement_cents`, and `materials_reimbursement_cents`."
    PRD §3.7: "The artist's `lifetime_delivered_count` gains one, both
    reliability figures are recomputed, and `roster_tier_effective` is
    recomputed — which is how the twenty-fifth delivery can promote an artist to
    `MASTER`."

    Design: Corner/RBAC/teaching_artist_cannot_deliver_another_artists_session
    """
    scenario = _confirmed_session_and_a_second_artist()
    session_id = scenario["session"]["id"]
    artist_id = scenario["artist"]["id"]

    refused = api_client.deliver_session(
        session_id,
        create_deliver_payload(
            students_present_count=22, minutes_delivered=60, travel_miles=0.0
        ),
        make_teaching_artist_headers(scenario["other_artist"]["id"]),
    )
    validate_error(
        refused, ApiErrorId.ERR_ACTOR_NOT_RESOURCE_OWNER.value, expected_status=403
    )

    delivered = validate_success(
        api_client.deliver_session(
            session_id,
            create_deliver_payload(
                students_present_count=22,
                minutes_delivered=60,
                travel_miles=0.0,
                materials_spend_cents=0,
            ),
            make_teaching_artist_headers(artist_id),
        )
    )
    assert delivered["status"] == "DELIVERED", (
        f"the session's own artist may report it, got {delivered['status']}"
    )
    assert delivered["fee_cents"] == 13974, (
        "DANCE 12000 graded to 12600, APPRENTICE-tiered to 11340, plus a 1134 "
        "lead premium and the flat 1500 Spanish-language premium, taught at full "
        f"length, got {delivered['fee_cents']}"
    )
    assert delivered["payable_cents"] == 13974, (
        "no travel and no materials were claimed, got "
        f"{delivered['payable_cents']}"
    )

    artist = read_artist(artist_id)
    assert artist["lifetime_delivered_count"] == 1, (
        f"one delivery is on the artist's record, got "
        f"{artist['lifetime_delivered_count']}"
    )
    assert read_artist(scenario["other_artist"]["id"])["lifetime_delivered_count"] == 0


# ==========================================================================
# The demonstration evaluator is blocked by data, not by role
# ==========================================================================
def _artist_awaiting_a_demonstration() -> dict:
    """Ana Reyes scored by panelist-1 and panelist-2 to a 3.59 mean composite
    and now sitting in DEMO_SCHEDULED on her first attempt."""
    set_clock_to_default()
    artist = create_artist_applicant()
    advance_vetting(artist["id"], "PORTFOLIO_REVIEW")
    record_passing_portfolio_panel(artist["id"])
    return advance_vetting(artist["id"], "DEMO_SCHEDULED")


def test_a_portfolio_panelist_may_not_record_the_demonstration_outcome(api):
    """PRD §2.11: "Three separations of duty are enforced structurally, and all
    three share the rejection code `ERR_SEGREGATION_OF_DUTIES` at HTTP 409."
    PRD §2.11: "The operator who records a teaching demonstration outcome — pass
    or fail — must not be any of the panelists who scored that artist's
    portfolio; the server compares the acting `X-User-ID` against every
    `reviewer_user_id` on that artist's portfolio reviews."
    PRD §3.1: "Moving `DEMO_SCHEDULED → DEMO_PASSED` requires a
    `demo_rubric_score` to be present and to lie between 1.0 and 5.0 inclusive —
    its absence or an out-of-range value is an `ERR_INVALID_REQUEST` — and that
    score must be at least 3.5, compared at one decimal place; the acting
    operator must not appear as a `reviewer_user_id` on any of this artist's
    portfolio reviews, on pain of `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.1: "Entering `DEMO_SCHEDULED` adds one to `demo_attempt_count`."

    Design: Corner/RBAC/portfolio_panelist_may_not_judge_the_demonstration
    """
    artist = _artist_awaiting_a_demonstration()
    artist_id = artist["id"]
    assert artist["vetting_status"] == "DEMO_SCHEDULED"
    assert artist["demo_attempt_count"] == 1, (
        f"scheduling the demonstration consumed one attempt, got "
        f"{artist['demo_attempt_count']}"
    )
    assert artist["portfolio_mean_composite"] == 3.59, (
        "the panel mean of the 3.60 and 3.58 composites clears the 3.50 floor, "
        f"got {artist['portfolio_mean_composite']}"
    )

    # Both panelists carry the RosterCoordinator role, which owns this
    # capability; what disqualifies them is their own scoring of this file.
    for panelist in (PANELIST_1_USER_ID, PANELIST_2_USER_ID):
        res = api_client.advance_vetting(
            artist_id,
            create_vetting_payload("DEMO_PASSED", demo_rubric_score=4.2),
            make_roster_coordinator_headers(panelist),
        )
        validate_error(
            res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=409
        )

    after = read_artist(artist_id)
    assert after["vetting_status"] == "DEMO_SCHEDULED", (
        f"the refusals leave the file where it was, got {after['vetting_status']}"
    )
    assert after["demo_attempt_count"] == 1, (
        "a refused outcome is not a new demonstration and consumes no attempt, "
        f"got {after['demo_attempt_count']}"
    )
    assert after["demo_evaluator_user_id"] is None
    assert after["demo_rubric_score"] is None


def test_an_untainted_evaluator_passes_the_demonstration_without_listing_the_artist(
    api,
):
    """PRD §3.1: "Moving `DEMO_SCHEDULED → DEMO_PASSED` requires a
    `demo_rubric_score` to be present and to lie between 1.0 and 5.0 inclusive —
    its absence or an out-of-range value is an `ERR_INVALID_REQUEST` — and that
    score must be at least 3.5, compared at one decimal place; the acting
    operator must not appear as a `reviewer_user_id` on any of this artist's
    portfolio reviews, on pain of `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.1: "Both branches persist the supplied score into `demo_rubric_score`
    and stamp `demo_evaluator_user_id` with the acting operator's identifier."
    PRD §3.1: "Reaching `CLEARED` on the recruitment axis fires an automatic
    transition on the roster axis, moving `roster_status` from `NOT_LISTED` to
    `ACTIVE`, and recomputes `roster_tier_effective`."
    PRD §3.1: "Entering `DEMO_SCHEDULED` adds one to `demo_attempt_count`."

    Design: Corner/RBAC/portfolio_panelist_may_not_judge_the_demonstration
    """
    artist = _artist_awaiting_a_demonstration()
    artist_id = artist["id"]

    refused = api_client.advance_vetting(
        artist_id,
        create_vetting_payload("DEMO_PASSED", demo_rubric_score=4.2),
        make_roster_coordinator_headers(PANELIST_1_USER_ID),
    )
    validate_error(
        refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=409
    )

    # Same role, same payload, an operator who never scored the portfolio.
    passed = validate_success(
        api_client.advance_vetting(
            artist_id,
            create_vetting_payload("DEMO_PASSED", demo_rubric_score=4.2),
            make_roster_coordinator_headers(DEMO_EVALUATOR_USER_ID),
        )
    )
    assert passed["vetting_status"] == "DEMO_PASSED", (
        f"the eligible evaluator may record the outcome, got "
        f"{passed['vetting_status']}"
    )
    assert passed["demo_rubric_score"] == 4.2
    assert passed["demo_evaluator_user_id"] == DEMO_EVALUATOR_USER_ID, (
        "the acting operator is stamped as the evaluator, got "
        f"{passed['demo_evaluator_user_id']}"
    )
    assert passed["demo_attempt_count"] == 1, (
        "recording the outcome is not a new attempt, got "
        f"{passed['demo_attempt_count']}"
    )
    assert passed["roster_status"] == "NOT_LISTED", (
        "the roster axis waits for CLEARED, not for a passed demonstration, got "
        f"{passed['roster_status']}"
    )


# ==========================================================================
# The cancellation reason is scoped to the role that supplies it
# ==========================================================================
def _planned_session_at_riverbend() -> dict:
    """An active Riverbend residency with one PLANNED session on 2026-09-15."""
    set_clock_to_default()
    scenario = setup_active_residency()
    scenario["session"] = schedule_session(
        scenario["residency"]["id"],
        scenario["artist"]["id"],
        session_date="2026-09-15",
        lesson_plan_id=scenario["lesson_plan"]["id"],
    )
    return scenario


def test_each_role_may_cancel_only_for_the_reasons_that_belong_to_it(api):
    """PRD §3.7: "Which reasons a role may use is itself a rule: a
    `SchoolLiaison` may use `SCHOOL_CLOSURE`, `TESTING_CONFLICT`, or
    `LOW_ENROLLMENT`; a `TeachingArtist` may use `ARTIST_ILLNESS` only, and only
    on their own session; a `RosterCoordinator` may use any reason except
    `RESIDENCY_DESCOPED`, which is reserved for the system's own descoping
    sweep."
    PRD §3.7: "A reason outside the acting role's permitted set — or any client
    use of `RESIDENCY_DESCOPED` — is refused with
    `ERR_CANCEL_REASON_NOT_PERMITTED` at HTTP 403, and an artist reaching for
    somebody else's session is refused with `ERR_ACTOR_NOT_RESOURCE_OWNER`."
    PRD §3.7: "`makeup_eligible` becomes true when the reason is
    `SCHOOL_CLOSURE`, `TESTING_CONFLICT`, `ARTIST_ILLNESS`, or
    `ARTIST_NO_SHOW`, and false when it is `LOW_ENROLLMENT` or
    `RESIDENCY_DESCOPED`."
    PRD §3.7: "From `PLANNED` there is nothing held, so the effects are just the
    eligibility flag and the ledger move: `sessions_open_count` loses one, and
    `makeup_credits_outstanding` gains one when the session was make-up-eligible
    while `sessions_forfeited_count` gains one when it was not."

    Design: Corner/RBAC/cancellation_reason_matrix_differs_by_acting_role
    """
    scenario = _planned_session_at_riverbend()
    session_id = scenario["session"]["id"]
    school_id = scenario["school"]["id"]
    liaison = make_school_liaison_headers(school_id)
    artist = make_teaching_artist_headers(scenario["artist"]["id"])

    # The host school owns this session, and the artist teaches it: both clear
    # the ownership check and fall on the reason itself.
    validate_error(
        api_client.cancel_session(
            session_id,
            create_cancel_payload("ARTIST_ILLNESS", note="liaison overreach"),
            liaison,
        ),
        ApiErrorId.ERR_CANCEL_REASON_NOT_PERMITTED.value,
        expected_status=403,
    )
    validate_error(
        api_client.cancel_session(
            session_id,
            create_cancel_payload("SCHOOL_CLOSURE", note="artist overreach"),
            artist,
        ),
        ApiErrorId.ERR_CANCEL_REASON_NOT_PERMITTED.value,
        expected_status=403,
    )
    validate_error(
        api_client.cancel_session(
            session_id,
            create_cancel_payload(
                "RESIDENCY_DESCOPED", note="manual use of the system's own reason"
            ),
            RC,
        ),
        ApiErrorId.ERR_CANCEL_REASON_NOT_PERMITTED.value,
        expected_status=403,
    )
    assert read_session(session_id)["status"] == "PLANNED", (
        "three refused reasons leave the session on the calendar"
    )

    cancelled = validate_success(
        api_client.cancel_session(
            session_id,
            create_cancel_payload("TESTING_CONFLICT", note="state testing window"),
            liaison,
        )
    )
    assert cancelled["status"] == "CANCELLED_SCHOOL", (
        f"a testing conflict is a school-side cancellation, got "
        f"{cancelled['status']}"
    )
    assert cancelled["makeup_eligible"] is True, (
        "TESTING_CONFLICT earns the school its session back, got "
        f"{cancelled['makeup_eligible']}"
    )

    residency = read_residency(scenario["residency"]["id"])
    assert residency["makeup_credits_outstanding"] == 1, (
        "the make-up-eligible cancellation moved one unit into the credit "
        f"bucket, got {residency['makeup_credits_outstanding']}"
    )
    assert residency["sessions_open_count"] == 0, (
        f"the only open session terminated, got {residency['sessions_open_count']}"
    )
    assert residency["sessions_forfeited_count"] == 0, (
        "an eligible cancellation forfeits nothing, got "
        f"{residency['sessions_forfeited_count']}"
    )
    assert residency["sessions_unscheduled_count"] == 9


# ==========================================================================
# The vetting axis and the roster axis have different owners
# ==========================================================================
def _artist_cleared_and_listed() -> dict:
    """Ana Reyes walked through intake, panel, demonstration and screening by
    the roster coordinator, so vetting reads CLEARED and the roster ACTIVE."""
    set_clock_to_default()
    return create_cleared_artist()


def test_the_roster_axis_belongs_to_the_director_and_intake_to_the_coordinator(api):
    """PRD §2.1: "If the headers are well-formed but the acting role is not
    permitted to invoke the requested operation, the rejection is
    `ERR_UNAUTHORIZED`."
    PRD §3.2: "A `ProgramDirector` moves the roster axis by naming a
    `to_roster_status`, optionally with a `reason`."
    PRD §3.1: "A `RosterCoordinator` opens an applicant file by supplying the
    artist's `full_name`, an `email` that must be unique across the roster — a
    repeat address is refused with `ERR_DUPLICATE_EMAIL` — and the capability
    tags that will later decide what the artist may teach."
    PRD §3.1: "The roster is searchable by capability and lifecycle state: a
    `discipline`, `grade_band`, `language`, `vetting_status`, or `roster_status`
    filter may be supplied, alone or in combination."

    Design: Corner/RBAC/roster_coordinator_holds_both_shared_and_exclusive_operations
    """
    artist = _artist_cleared_and_listed()
    artist_id = artist["id"]
    assert artist["vetting_status"] == "CLEARED"
    assert artist["roster_status"] == "ACTIVE", (
        f"clearance listed the artist automatically, got {artist['roster_status']}"
    )

    # The coordinator ran every vetting step above, yet the roster axis is not
    # its to move.
    validate_error(
        api_client.set_roster_status(
            artist_id,
            create_roster_status_payload("PROBATION", reason="coordinator attempt"),
            RC,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        expected_status=403,
    )
    on_probation = validate_success(
        api_client.set_roster_status(
            artist_id,
            create_roster_status_payload("PROBATION", reason="director decision"),
            PD,
        )
    )
    assert on_probation["roster_status"] == "PROBATION", (
        f"the director owns this axis, got {on_probation['roster_status']}"
    )
    assert on_probation["vetting_status"] == "CLEARED", (
        "the two axes are independent, so the recruitment axis is undisturbed, "
        f"got {on_probation['vetting_status']}"
    )

    # And the reverse exclusion: applicant intake is not the director's.
    validate_error(
        api_client.create_teaching_artist(
            create_teaching_artist_payload(
                full_name="Eve Nakamura",
                email="eve.nakamura@arts.org",
                primary_discipline="VISUAL_ARTS",
                secondary_disciplines=[],
                grade_bands=["K_2"],
                languages=["en"],
            ),
            PD,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        expected_status=403,
    )

    roster, meta = validate_paginated(
        api_client.list_teaching_artists(
            RC,
            params={
                "discipline": "DANCE",
                "roster_status": "PROBATION",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 1, (
        "the refused intake created nobody, so one DANCE artist is on probation, "
        f"got {meta['total_count']}"
    )
    assert roster[0]["id"] == artist_id, (
        f"the listed artist must be the one just moved, got {roster[0]['id']}"
    )
