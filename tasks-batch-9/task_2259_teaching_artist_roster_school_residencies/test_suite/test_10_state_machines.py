"""Declared transitions and their side effects: what each hop writes, what a
hop that was never declared refuses to do, and how far a loop may run."""
from test_helpers import (
    ApiErrorId,
    CURRICULUM_SPECIALIST_USER_ID,
    OBSERVER_USER_ID,
    TEST_DEFAULTS,
    TEST_USERS,
    advance_vetting,
    align_lesson_plan,
    api_client,
    assign_lead_artist,
    attach_observation_rubric,
    confirm_session_as_liaison,
    create_artist_applicant,
    create_cleared_artist,
    create_confirm_payload,
    create_confirmed_session,
    create_deliver_payload,
    create_delivered_session,
    create_lesson_plan_payload,
    create_lesson_plan_review_payload,
    create_lesson_plan_revision_payload,
    create_payment_voucher_payload,
    create_residency_for_school,
    create_residency_payload,
    create_residency_status_payload,
    create_school,
    create_standard,
    create_vetting_payload,
    get_success_data,
    make_teaching_artist_headers,
    read_artist,
    read_lesson_plan,
    read_residency,
    read_school,
    read_session,
    schedule_session,
    set_clock_to_default,
    set_residency_status,
    set_roster_status,
    setup_active_residency,
    validate_error,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]
RC = TEST_USERS["roster_coordinator_headers"]
CS = TEST_USERS["curriculum_specialist_headers"]

CREATING_CODE = TEST_DEFAULTS["STANDARD_CODE_CREATING"]


# ==========================================================================
# Curriculum review: the align hop and the bounded adaptation loop
# ==========================================================================
def _plan_authored_by_artist() -> dict:
    """A draft residency plus one SUBMITTED lesson plan the artist wrote
    herself, covering a single CREATING standard."""
    set_clock_to_default()
    school = create_school()
    artist = create_artist_applicant()
    residency = create_residency_for_school(
        school["id"], required_strands=["CREATING"]
    )
    create_standard(CREATING_CODE, "CREATING", discipline="DANCE", grade_band="G3_5")
    plan = get_success_data(
        api_client.create_lesson_plan(
            create_lesson_plan_payload(
                residency["id"],
                [CREATING_CODE],
                1,
                title="Story in Motion 1",
                materials_list="scarves, hand drum",
            ),
            make_teaching_artist_headers(artist["id"]),
        )
    )
    return {
        "school": school,
        "artist": artist,
        "residency": residency,
        "plan": plan,
    }


def _resubmit_adaptation(plan_id: str, artist_id: str, adaptation_summary: str):
    """The authoring artist answers a change request, returning the raw
    response so a refusal can be inspected."""
    return api_client.revise_lesson_plan(
        plan_id,
        create_lesson_plan_revision_payload(adaptation_summary),
        make_teaching_artist_headers(artist_id),
    )


def test_aligning_a_plan_stamps_the_logical_clock_and_the_reviewing_operator(api):
    """PRD §3.5: "Authorship is recorded rather than supplied:
    `author_artist_id` becomes the acting `X-User-ID` when a `TeachingArtist`
    submits the plan, and otherwise becomes the residency's `lead_artist_id`."
    PRD §3.5: "A new plan starts with a `status` of `SUBMITTED` and a
    `revision_round` of zero, and the server derives `covered_strands` as the
    distinct set of `strand` values on the standards resolved from
    `standard_codes`."
    PRD §2.4: "Every date and datetime comparison in this specification —
    clearance expiry, program-year membership, reporting-period membership, and
    the moment written into a lesson plan's `aligned_on` — reads a server-side
    **logical clock** rather than real wall-clock time."
    PRD §3.5: "Aligning a plan stamps `aligned_on` with the current
    logical-clock instant and records the acting operator in
    `reviewer_user_id`."

    Design: Corner/State Machines/lesson_plan_align_records_reviewer_and_aligned_on
    """
    scenario = _plan_authored_by_artist()
    plan = scenario["plan"]
    assert plan["status"] == "SUBMITTED"
    assert plan["author_artist_id"] == scenario["artist"]["id"], (
        "the artist submitted the plan herself, so authorship is her own id, "
        f"got {plan['author_artist_id']}"
    )
    assert plan["revision_round"] == 0

    aligned = align_lesson_plan(plan["id"])
    assert aligned["status"] == "ALIGNED", (
        f"an ALIGN decision on a submitted plan aligns it, got {aligned['status']}"
    )
    assert aligned["aligned_on"].startswith("2026-08-01T00:00:00"), (
        "aligned_on carries the logical-clock instant 2026-08-01T00:00:00Z, "
        f"got {aligned['aligned_on']}"
    )
    assert aligned["reviewer_user_id"] == CURRICULUM_SPECIALIST_USER_ID, (
        "the acting curriculum operator is recorded as the reviewer, got "
        f"{aligned['reviewer_user_id']}"
    )
    assert aligned["revision_round"] == 0, (
        f"aligning consumes no adaptation round, got {aligned['revision_round']}"
    )
    assert aligned["covered_strands"] == ["CREATING"], (
        "the single resolved standard sits in the CREATING strand, got "
        f"{aligned['covered_strands']}"
    )
    assert read_residency(scenario["residency"]["id"])["status"] == "DRAFT", (
        "aligning curriculum does not move the residency's own lifecycle"
    )


def test_a_third_change_request_closes_the_adaptation_loop(api):
    """PRD §3.5: "`SUBMITTED → CHANGES_REQUESTED` under a `REQUEST_CHANGES`
    decision requires that `revision_round` be less than 3, or the review is
    refused with `ERR_ADAPTATION_ROUND_LIMIT`."
    PRD §3.5: "It adds one to `revision_round`, stores the supplied
    `reviewer_note`, and records the acting operator in `reviewer_user_id`."
    PRD §3.5: "The round limit applies here too: `revision_round` must be below
    3, else `ERR_ADAPTATION_ROUND_LIMIT`."
    PRD §3.5: "Because each change request consumes one round and the limit is
    3, the `SUBMITTED → CHANGES_REQUESTED → SUBMITTED` adaptation cycle is
    bounded at three rounds."

    Design: Corner/State Machines/lesson_plan_revision_cycle_is_bounded_by_adaptation_round_limit
    """
    scenario = _plan_authored_by_artist()
    plan_id = scenario["plan"]["id"]
    artist_id = scenario["artist"]["id"]

    first_request = validate_success(
        api_client.review_lesson_plan(
            plan_id,
            create_lesson_plan_review_payload(
                "REQUEST_CHANGES", reviewer_note="add a differentiation strategy"
            ),
            CS,
        )
    )
    assert first_request["status"] == "CHANGES_REQUESTED"
    assert first_request["revision_round"] == 1, (
        "the review leg is what consumes a round, got "
        f"{first_request['revision_round']}"
    )

    first_answer = validate_success(
        _resubmit_adaptation(plan_id, artist_id, "added tiered movement prompts")
    )
    assert first_answer["status"] == "SUBMITTED"
    assert first_answer["revision_round"] == 1, (
        "answering a change request must not consume a second round, got "
        f"{first_answer['revision_round']}"
    )

    second_request = validate_success(
        api_client.review_lesson_plan(
            plan_id,
            create_lesson_plan_review_payload(
                "REQUEST_CHANGES", reviewer_note="assessment evidence still thin"
            ),
            CS,
        )
    )
    assert second_request["revision_round"] == 2
    validate_success(
        _resubmit_adaptation(plan_id, artist_id, "added exit-ticket rubric")
    )

    third_request = validate_success(
        api_client.review_lesson_plan(
            plan_id,
            create_lesson_plan_review_payload(
                "REQUEST_CHANGES", reviewer_note="third and final change request"
            ),
            CS,
        )
    )
    assert third_request["revision_round"] == 3, (
        "three change requests exhaust the adaptation allowance, got "
        f"{third_request['revision_round']}"
    )
    assert third_request["status"] == "CHANGES_REQUESTED"

    validate_error(
        _resubmit_adaptation(plan_id, artist_id, "one more attempt"),
        ApiErrorId.ERR_ADAPTATION_ROUND_LIMIT.value,
        expected_status=409,
    )

    plan = read_lesson_plan(plan_id)
    assert plan["status"] == "CHANGES_REQUESTED", (
        f"the refused resubmission leaves the plan where it was, got {plan['status']}"
    )
    assert plan["revision_round"] == 3


# ==========================================================================
# The residency lifecycle: approval and destructive suspension
# ==========================================================================
def _draft_residency_without_a_lead() -> dict:
    """A freshly scoped residency whose lead artist was never nominated."""
    set_clock_to_default()
    school = create_school()
    residency = create_residency_for_school(
        school["id"], required_strands=["CREATING"]
    )
    return {"school": school, "residency": residency}


def _draft_residency_with_a_cleared_lead() -> dict:
    """A draft residency whose lead artist is vetted CLEARED and rostered
    ACTIVE, so approval's preconditions are all met."""
    set_clock_to_default()
    school = create_school()
    artist = create_cleared_artist()
    residency = create_residency_for_school(school["id"])
    return {"school": school, "artist": artist, "residency": residency}


def test_approval_without_a_lead_artist_is_refused_and_initializes_nothing(api):
    """PRD §3.4: "A freshly scoped residency has a `status` of `DRAFT`, a
    `staffing_status` of `LEAD_VACANT`, and every ledger counter and money field
    at zero."
    PRD §3.4: "`DRAFT → APPROVED` is the moment the commitment becomes real, and
    it has three preconditions: a lead artist must be assigned, or the
    transition is refused with `ERR_INVALID_STATE_TRANSITION`; that lead artist
    must have a `vetting_status` of `CLEARED` and a `roster_status` of `ACTIVE`,
    or the refusal is `ERR_ARTIST_NOT_ON_ACTIVE_ROSTER`; and the host school's
    `partnership_health` must not be `INTAKE_SUSPENDED`, or the refusal is
    `ERR_PARTNERSHIP_INTAKE_SUSPENDED`."
    PRD §3.4: "Approval initializes the allotment by setting
    `sessions_unscheduled_count` to `contracted_session_count`, and initializes
    the money ledger by setting `available_cents` to `budget_cents` with
    `encumbered_cents` and `disbursed_cents` both at zero."
    PRD §3.3: "Otherwise, if any residency in that set has a `staffing_status`
    of `AT_RISK` or `LEAD_VACANT`, health reads `WATCH`."

    Design: Corner/State Machines/residency_approval_precondition_requires_a_lead_artist
    """
    scenario = _draft_residency_without_a_lead()
    residency_id = scenario["residency"]["id"]
    assert scenario["residency"]["staffing_status"] == "LEAD_VACANT", (
        "a residency with no lead reads LEAD_VACANT, got "
        f"{scenario['residency']['staffing_status']}"
    )

    validate_error(
        api_client.set_residency_status(
            residency_id, create_residency_status_payload("APPROVED"), PD
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        expected_status=409,
    )

    residency = read_residency(residency_id)
    assert residency["status"] == "DRAFT", (
        f"the refused approval leaves the residency in DRAFT, got {residency['status']}"
    )
    assert residency["sessions_unscheduled_count"] == 0, (
        "the allotment is only initialized by a successful approval, got "
        f"{residency['sessions_unscheduled_count']}"
    )
    assert residency["available_cents"] == 0, (
        "the money ledger is only initialized by a successful approval, got "
        f"{residency['available_cents']}"
    )
    assert read_school(scenario["school"]["id"])["partnership_health"] == "WATCH", (
        "a draft residency with a vacant lead puts its school on watch"
    )


def test_approval_initializes_the_allotment_and_the_money_ledger(api):
    """PRD §3.4: "Otherwise it is `STAFFED`."
    PRD §3.4: "Approval initializes the allotment by setting
    `sessions_unscheduled_count` to `contracted_session_count`, and initializes
    the money ledger by setting `available_cents` to `budget_cents` with
    `encumbered_cents` and `disbursed_cents` both at zero."
    PRD §2.12: "The sum of those five buckets always equals
    `contracted_session_count`."
    PRD §3.3: "Otherwise health reads `HEALTHY`."

    Design: Corner/State Machines/residency_approval_initialises_allotment_and_money_ledger
    """
    scenario = _draft_residency_with_a_cleared_lead()
    residency_id = scenario["residency"]["id"]
    assert scenario["artist"]["vetting_status"] == "CLEARED"
    assert scenario["artist"]["roster_status"] == "ACTIVE"

    staffed = assign_lead_artist(residency_id, scenario["artist"]["id"])
    assert staffed["staffing_status"] == "STAFFED", (
        "a lead is in place and no session is vacated, got "
        f"{staffed['staffing_status']}"
    )

    approved = set_residency_status(residency_id, "APPROVED")
    assert approved["status"] == "APPROVED"
    assert approved["sessions_unscheduled_count"] == 10, (
        "the whole contracted allotment of 10 becomes unscheduled at approval, "
        f"got {approved['sessions_unscheduled_count']}"
    )
    assert approved["available_cents"] == 200000, (
        f"available starts at the full budget of 200000, got {approved['available_cents']}"
    )
    assert approved["encumbered_cents"] == 0
    assert approved["disbursed_cents"] == 0
    assert approved["sessions_open_count"] == 0, (
        "approval schedules nothing, got " f"{approved['sessions_open_count']}"
    )
    buckets = (
        approved["sessions_unscheduled_count"]
        + approved["sessions_open_count"]
        + approved["sessions_delivered_count"]
        + approved["sessions_forfeited_count"]
        + approved["makeup_credits_outstanding"]
    )
    assert buckets == 10, (
        f"the five session buckets must still sum to the contracted 10, got {buckets}"
    )
    assert read_school(scenario["school"]["id"])["partnership_health"] == "HEALTHY", (
        "the school's only residency is staffed, so health returns to HEALTHY"
    )


def _active_residency_with_one_confirmed_session() -> dict:
    """An ACTIVE residency on a 200000-cent budget whose 2026-09-15 session is
    CONFIRMED, so its full-length fee sits encumbered."""
    set_clock_to_default()
    scenario = setup_active_residency()
    scenario["session"] = create_confirmed_session(scenario, session_date="2026-09-15")
    return scenario


def test_suspending_a_residency_descopes_its_sessions_and_shuts_intake(api):
    """PRD §3.4: "Every session of the residency whose status is `PLANNED`,
    `CONFIRMED`, or `VACATED` is driven to `CANCELLED_SCHOOL` with a
    `cancel_reason` of `RESIDENCY_DESCOPED` and `makeup_eligible` set to false;
    each one releases whatever it was holding against the money ledger and adds
    one to `sessions_forfeited_count`."
    PRD §3.4: "The host school's `partnership_health` is then recomputed, which
    — because a suspended residency is present — yields `INTAKE_SUSPENDED`."
    PRD §3.3: "`INTAKE_SUSPENDED` blocks three things at that school: creating a
    new residency, moving a residency from `DRAFT` to `APPROVED`, and creating a
    session — all refused with `ERR_PARTNERSHIP_INTAKE_SUSPENDED` at HTTP 403."
    PRD §2.12: "The sum of those five buckets always equals
    `contracted_session_count`."

    Design: Corner/State Machines/residency_suspension_descopes_open_sessions_and_suspends_intake
    """
    scenario = _active_residency_with_one_confirmed_session()
    residency_id = scenario["residency"]["id"]
    school_id = scenario["school"]["id"]
    assert scenario["session"]["encumbered_cents"] == 13974, (
        "the confirmed session holds its full-length fee, got "
        f"{scenario['session']['encumbered_cents']}"
    )

    suspended = set_residency_status(
        residency_id,
        "SUSPENDED",
        reason="district paused arts contracts pending audit",
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["sessions_open_count"] == 0, (
        "the descoping sweep terminates every open session, got "
        f"{suspended['sessions_open_count']}"
    )
    assert suspended["sessions_forfeited_count"] == 1, (
        "the descoped session earns no credit and is written off, got "
        f"{suspended['sessions_forfeited_count']}"
    )
    assert suspended["makeup_credits_outstanding"] == 0, (
        "RESIDENCY_DESCOPED is not make-up eligible, got "
        f"{suspended['makeup_credits_outstanding']}"
    )
    assert suspended["encumbered_cents"] == 0, (
        f"the released hold leaves nothing encumbered, got {suspended['encumbered_cents']}"
    )
    assert suspended["available_cents"] == 200000, (
        "the whole budget is free again once the hold is released, got "
        f"{suspended['available_cents']}"
    )
    buckets = (
        suspended["sessions_unscheduled_count"]
        + suspended["sessions_open_count"]
        + suspended["sessions_delivered_count"]
        + suspended["sessions_forfeited_count"]
        + suspended["makeup_credits_outstanding"]
    )
    assert buckets == 10, (
        f"9 unscheduled plus 1 forfeited must still be the contracted 10, got {buckets}"
    )

    session = read_session(scenario["session"]["id"])
    assert session["status"] == "CANCELLED_SCHOOL", (
        f"the descoped session terminates school-side, got {session['status']}"
    )
    assert session["cancel_reason"] == "RESIDENCY_DESCOPED", (
        f"the sweep stamps its own system reason, got {session['cancel_reason']}"
    )
    assert session["makeup_eligible"] is False
    assert session["encumbered_cents"] == 0

    assert read_school(school_id)["partnership_health"] == "INTAKE_SUSPENDED", (
        "a suspended residency at the school suspends intake"
    )
    validate_error(
        api_client.create_residency(
            create_residency_payload(
                school_id,
                title="Second Residency",
                contracted_session_count=4,
                budget_cents=50000,
                collaboration_expectation="OBSERVE",
                co_planning_hours_required=0,
                materials_stipend_cents=0,
                required_strands=["CREATING"],
                enrolled_student_count=20,
            ),
            PD,
        ),
        ApiErrorId.ERR_PARTNERSHIP_INTAKE_SUSPENDED.value,
        expected_status=403,
    )


# ==========================================================================
# The recruitment axis: a terminal decline
# ==========================================================================
def _declined_applicant() -> dict:
    """An applicant turned away at the portfolio stage."""
    set_clock_to_default()
    artist = create_artist_applicant()
    advance_vetting(artist["id"], "PORTFOLIO_REVIEW")
    declined = advance_vetting(
        artist["id"],
        "DECLINED",
        decline_reason="portfolio does not evidence classroom practice",
    )
    return {"artist": artist, "declined": declined}


def test_a_declined_applicant_cannot_be_scheduled_for_a_demonstration(api):
    """PRD §3.1: "The recruitment axis, `vetting_status`, starts at `APPLIED`
    and ranges over `APPLIED`, `PORTFOLIO_REVIEW`, `DEMO_SCHEDULED`,
    `DEMO_FAILED`, `DEMO_PASSED`, `SCREENING_PENDING`, `CLEARED`, `DECLINED`,
    and `SCREEN_FAILED`, of which `DECLINED` and `SCREEN_FAILED` are terminal."
    PRD §3.1: "The assignability axis, `roster_status`, starts at `NOT_LISTED`
    and ranges over `NOT_LISTED`, `ACTIVE`, `PROBATION`, `SUSPENDED`, and
    `RETIRED`, of which `RETIRED` is terminal."
    PRD §3.1: "`PORTFOLIO_REVIEW → DECLINED` requires the artist to currently be
    in either `PORTFOLIO_REVIEW` or `DEMO_FAILED`, and `DEMO_FAILED → DECLINED`
    carries no further precondition; both accept a `decline_reason` and both are
    terminal on the recruitment axis."
    PRD §2.9: "8. The target row is in a state from which the requested
    transition is declared, on the addressed axis, with a legal reason or
    decision value for that transition — `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/State Machines/declined_artist_vetting_axis_is_terminally_locked
    """
    scenario = _declined_applicant()
    artist_id = scenario["artist"]["id"]
    assert scenario["declined"]["vetting_status"] == "DECLINED"

    validate_error(
        api_client.advance_vetting(
            artist_id, create_vetting_payload("DEMO_SCHEDULED"), RC
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        expected_status=409,
    )

    artist = read_artist(artist_id)
    assert artist["vetting_status"] == "DECLINED", (
        f"a declined file admits no further vetting hop, got {artist['vetting_status']}"
    )
    assert artist["roster_status"] == "NOT_LISTED", (
        "the assignability axis was never dragged along by the decline, got "
        f"{artist['roster_status']}"
    )
    assert artist["demo_attempt_count"] == 0, (
        "the refused hop consumed no demonstration attempt, got "
        f"{artist['demo_attempt_count']}"
    )


# ==========================================================================
# Session confirmation and delivery
# ==========================================================================
def _active_residency_with_one_planned_session() -> dict:
    """An ACTIVE residency of 10 sessions on a 200000-cent budget with one
    PLANNED session on 2026-09-15."""
    set_clock_to_default()
    scenario = setup_active_residency()
    scenario["session"] = schedule_session(
        scenario["residency"]["id"],
        scenario["artist"]["id"],
        session_date="2026-09-15",
        lesson_plan_id=scenario["lesson_plan"]["id"],
    )
    return scenario


def test_delivery_reported_on_a_session_that_was_never_confirmed_is_refused(api):
    """PRD §3.7: "`CONFIRMED → DELIVERED` has four preconditions beyond
    ownership."
    PRD §2.9: "8. The target row is in a state from which the requested
    transition is declared, on the addressed axis, with a legal reason or
    decision value for that transition — `ERR_INVALID_STATE_TRANSITION`."
    PRD §3.6: "A new session is created in `PLANNED` status with
    `vacated_artist_id`, `payment_voucher_id`, `cancel_reason`, and every
    delivery and money field still null or zero, and with `is_substitute` false,
    `co_planning_completed` false, `makeup_eligible` false, and
    `makeup_consumed` false."
    PRD §3.7: "The residency's `sessions_open_count` loses one,
    `sessions_delivered_count` gains one, and both `earned_to_date_cents` and
    `projected_cost_cents` are recomputed."

    Design: Corner/State Machines/deliver_from_planned_is_not_a_declared_transition
    """
    scenario = _active_residency_with_one_planned_session()
    session_id = scenario["session"]["id"]
    artist_id = scenario["artist"]["id"]
    assert scenario["session"]["status"] == "PLANNED"

    validate_error(
        api_client.deliver_session(
            session_id,
            create_deliver_payload(
                students_present_count=22,
                minutes_delivered=60,
                travel_miles=20.5,
                materials_spend_cents=3000,
            ),
            make_teaching_artist_headers(artist_id),
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        expected_status=409,
    )

    session = read_session(session_id)
    assert session["status"] == "PLANNED", (
        f"the refused report leaves the session unconfirmed, got {session['status']}"
    )
    assert not session["fee_cents"], (
        f"no fee is computed for a refused delivery, got {session['fee_cents']}"
    )
    assert not session["payable_cents"], (
        f"nothing is payable on a refused delivery, got {session['payable_cents']}"
    )

    residency = read_residency(scenario["residency"]["id"])
    assert residency["sessions_delivered_count"] == 0, (
        "the delivered bucket is untouched by the refusal, got "
        f"{residency['sessions_delivered_count']}"
    )
    assert residency["sessions_open_count"] == 1, (
        f"the session is still open, got {residency['sessions_open_count']}"
    )
    assert residency["earned_to_date_cents"] == 0, (
        f"nothing has been earned, got {residency['earned_to_date_cents']}"
    )
    assert residency["encumbered_cents"] == 0, (
        f"a planned session holds no money, got {residency['encumbered_cents']}"
    )


def test_confirmation_writes_the_same_hold_to_the_session_and_the_residency(api):
    """PRD §3.6: "The server evaluates the session fee rules of §3.7 as though
    the artist had taught the full `session_length_minutes`, writes that amount
    into the session's own `encumbered_cents`, adds it to the residency's
    `encumbered_cents`, and recomputes `available_cents`."
    PRD §2.12: "The **money ledger** partitions the budget across three
    accounts: `encumbered_cents`, the sum of the amounts currently held by this
    residency's sessions; `disbursed_cents`, the sum of `total_cents` over this
    residency's `APPROVED` vouchers; and `available_cents`, which is
    `budget_cents` less encumbered less disbursed."
    PRD §2.12: "Available plus encumbered plus disbursed always equals
    `budget_cents`."
    PRD §3.4: "`earned_to_date_cents` is the chronological, backward-looking
    figure: the sum of `payable_cents` over this residency's `DELIVERED`
    sessions, at the actual fees and reimbursements recorded at delivery, with
    real prorated minutes and real mileage."

    Design: Corner/State Machines/confirmation_encumbrance_syncs_the_residency_money_ledger
    """
    scenario = _active_residency_with_one_planned_session()
    residency_id = scenario["residency"]["id"]
    assert scenario["session"]["encumbered_cents"] == 0, (
        "a planned session holds nothing yet, got "
        f"{scenario['session']['encumbered_cents']}"
    )
    before = read_residency(residency_id)
    assert before["encumbered_cents"] == 0
    assert before["available_cents"] == 200000

    confirmed = confirm_session_as_liaison(
        scenario["session"]["id"], scenario["school"]["id"]
    )
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["encumbered_cents"] == 13974, (
        "a full 60-minute DANCE G3_5 session by the APPRENTICE lead in Spanish "
        "holds 11340 tiered plus 1134 lead premium plus 1500 language premium, "
        f"got {confirmed['encumbered_cents']}"
    )

    after = read_residency(residency_id)
    assert after["encumbered_cents"] == 13974, (
        "the residency aggregate carries the same hold as its session, got "
        f"{after['encumbered_cents']}"
    )
    assert after["available_cents"] == 186026, (
        f"200000 less the 13974 hold leaves 186026, got {after['available_cents']}"
    )
    assert after["disbursed_cents"] == 0
    assert (
        after["available_cents"] + after["encumbered_cents"] + after["disbursed_cents"]
        == 200000
    ), "available plus encumbered plus disbursed must still be the budget"
    assert after["earned_to_date_cents"] == 0, (
        "confirmation teaches nothing, so nothing is earned yet, got "
        f"{after['earned_to_date_cents']}"
    )
    assert not read_session(scenario["session"]["id"])["fee_cents"], (
        "the projected hold is not a recorded fee"
    )


def test_confirming_an_already_confirmed_session_does_not_encumber_twice(api):
    """PRD §2.9: "8. The target row is in a state from which the requested
    transition is declared, on the addressed axis, with a legal reason or
    decision value for that transition — `ERR_INVALID_STATE_TRANSITION`."
    PRD §3.6: "Confirmation persists both supplied fields and then **encumbers**
    the money it expects to owe."
    PRD §3.6: "The server evaluates the session fee rules of §3.7 as though the
    artist had taught the full `session_length_minutes`, writes that amount into
    the session's own `encumbered_cents`, adds it to the residency's
    `encumbered_cents`, and recomputes `available_cents`."
    PRD §2.7: "A single request may legitimately mutate several rows: each
    mutated row has its `updated_at` refreshed and its `version` incremented,
    even when the only thing that changed was a derived counter."

    Design: Corner/State Machines/second_confirm_of_a_confirmed_session_is_rejected_without_double_encumbrance
    """
    scenario = _active_residency_with_one_confirmed_session()
    first = scenario["session"]
    assert first["status"] == "CONFIRMED"
    assert first["encumbered_cents"] == 13974
    assert first["classroom_teacher_name"] == "Ms. Delgado"

    validate_error(
        api_client.confirm_session(
            first["id"],
            create_confirm_payload("Mr. Okonkwo", co_planning_completed=True),
            RC,
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        expected_status=409,
    )

    session = read_session(first["id"])
    assert session["status"] == "CONFIRMED"
    assert session["classroom_teacher_name"] == "Ms. Delgado", (
        "the refused replay persisted none of its fields, got "
        f"{session['classroom_teacher_name']}"
    )
    assert session["encumbered_cents"] == 13974, (
        f"the session holds one fee, not two, got {session['encumbered_cents']}"
    )
    assert session["version"] == first["version"], (
        "a refused request mutates no row, so the version must not move, got "
        f"{session['version']} against {first['version']}"
    )

    residency = read_residency(scenario["residency"]["id"])
    assert residency["encumbered_cents"] == 13974, (
        f"the residency was encumbered exactly once, got {residency['encumbered_cents']}"
    )
    assert residency["available_cents"] == 186026, (
        "a double encumbrance would have left 172052 available, got "
        f"{residency['available_cents']}"
    )


# ==========================================================================
# Opening a voucher over a delivered, evaluated session
# ==========================================================================
def _evaluated_delivery() -> dict:
    """One delivered 2026-09-15 session — 22 students, 60 minutes, 20.5 miles,
    3000 cents of materials — carrying its observation rubric."""
    set_clock_to_default()
    scenario = setup_active_residency()
    session = create_delivered_session(
        scenario,
        session_date="2026-09-15",
        students_present_count=22,
        minutes_delivered=60,
        travel_miles=20.5,
        materials_spend_cents=3000,
    )
    attach_observation_rubric(session["id"], OBSERVER_USER_ID, 4, 3, 4)
    scenario["session"] = session
    return scenario


def test_a_new_voucher_opens_in_draft_with_both_review_tracks_pending(api):
    """PRD §3.8: "A new voucher starts with a `status` of `DRAFT`, both review
    tracks at `PENDING`, and its `void_reason` null; each claimed session gets
    its `payment_voucher_id` pointed at the new voucher."
    PRD §3.8: "Alongside `status`, two **independent review axes** run in
    parallel once the voucher is submitted: `fiscal_review_status` and
    `program_review_status`, each of which reads `PENDING`, `PASSED`, or
    `FAILED`, with `fiscal_reviewed_by` and `program_reviewed_by` recording who
    closed each."
    PRD §3.8: "Voucher money is pure aggregation over the claimed sessions, with
    no further rounding: `session_fee_subtotal_cents` is the sum of their
    `fee_cents`, `travel_reimbursement_cents` is the sum of their per-session
    travel figures — already rounded individually, which is why summing raw
    mileage first would give a different answer — `materials_reimbursement_cents`
    is the sum of their per-session materials figures, and `total_cents` is
    those three subtotals added together."
    PRD §3.7: "The session's `payable_cents` is the sum of `fee_cents`,
    `travel_reimbursement_cents`, and `materials_reimbursement_cents`."

    Design: Corner/State Machines/voucher_is_created_in_draft_with_both_tracks_pending
    """
    scenario = _evaluated_delivery()
    session = scenario["session"]
    assert session["fee_cents"] == 13974
    assert session["travel_reimbursement_cents"] == 704, (
        "10.5 billable miles at 67 cents rounds half up from 703.5 to 704, got "
        f"{session['travel_reimbursement_cents']}"
    )
    assert session["materials_reimbursement_cents"] == 2500, (
        "3000 cents of spend is capped at the 2500-cent per-session cap, got "
        f"{session['materials_reimbursement_cents']}"
    )
    assert session["payable_cents"] == 17178, (
        f"13974 plus 704 plus 2500 is 17178, got {session['payable_cents']}"
    )

    voucher = validate_success(
        api_client.create_payment_voucher(
            create_payment_voucher_payload(
                scenario["artist"]["id"],
                scenario["residency"]["id"],
                [session["id"]],
                period_start="2026-09-01",
                period_end="2026-09-30",
            ),
            RC,
        ),
        expected_status=201,
    )
    assert voucher["status"] == "DRAFT", (
        f"a freshly opened voucher is not yet submitted, got {voucher['status']}"
    )
    assert voucher["fiscal_review_status"] == "PENDING"
    assert voucher["program_review_status"] == "PENDING"
    assert voucher["fiscal_reviewed_by"] is None, (
        "no operator has closed the fiscal track yet, got "
        f"{voucher['fiscal_reviewed_by']}"
    )
    assert voucher["program_reviewed_by"] is None
    assert voucher["session_fee_subtotal_cents"] == 13974, (
        "the single claimed session's fee is the whole fee subtotal, got "
        f"{voucher['session_fee_subtotal_cents']}"
    )
    assert voucher["travel_reimbursement_cents"] == 704
    assert voucher["materials_reimbursement_cents"] == 2500
    assert voucher["total_cents"] == 17178, (
        f"13974 plus 704 plus 2500 is 17178, got {voucher['total_cents']}"
    )
    assert read_session(session["id"])["payment_voucher_id"] == voucher["id"], (
        "the claimed session points at the voucher that claims it"
    )


# ==========================================================================
# Cascade A: suspension reaches only the sessions still in play
# ==========================================================================
def _delivered_and_planned_sessions_for_one_artist() -> dict:
    """The lead artist holds one delivered session worth 17178 cents and one
    session still merely PLANNED."""
    set_clock_to_default()
    scenario = setup_active_residency()
    scenario["delivered"] = create_delivered_session(
        scenario,
        session_date="2026-09-15",
        students_present_count=22,
        minutes_delivered=60,
        travel_miles=20.5,
        materials_spend_cents=3000,
    )
    scenario["planned"] = schedule_session(
        scenario["residency"]["id"],
        scenario["artist"]["id"],
        session_date="2026-09-22",
        lesson_plan_id=scenario["lesson_plan"]["id"],
    )
    return scenario


def test_suspending_an_artist_vacates_the_planned_session_but_spares_the_delivered_one(
    api,
):
    """PRD §2.7: "**Cascade A** begins when an artist's roster standing drops to
    `SUSPENDED` (whether by director action or as the automatic consequence of a
    failed screening) and runs four links: the roster axis moves to `SUSPENDED`;
    every one of that artist's `PLANNED` or `CONFIRMED` sessions is vacated;
    every residency touched by that vacating has its vacated-session count and
    staffing status recomputed, and loses its lead artist reference if the
    suspended artist held it; and every school owning one of those residencies
    has its partnership health recomputed."
    PRD §3.2: "Link two: every session of this artist whose status is `PLANNED`
    or `CONFIRMED` moves to `VACATED`, with the artist's identifier copied from
    `assigned_artist_id` into `vacated_artist_id` and `assigned_artist_id` set to
    null; each session that was `CONFIRMED` also releases its held amount,
    subtracting the session's held cents from the residency's
    `encumbered_cents`, zeroing the session's own held amount, and recomputing
    `available_cents`."
    PRD §3.2: "Link three: for every residency touched by link two,
    `vacated_session_count` gains one and `staffing_status` is recomputed, and if
    the suspended artist was that residency's `lead_artist_id`, the lead
    reference is cleared to null so the residency reads `LEAD_VACANT`."
    PRD §3.3: "Otherwise, if any residency in that set has a `staffing_status`
    of `AT_RISK` or `LEAD_VACANT`, health reads `WATCH`."

    Design: Corner/State Machines/artist_suspension_vacates_only_non_terminal_sessions
    """
    scenario = _delivered_and_planned_sessions_for_one_artist()
    artist_id = scenario["artist"]["id"]
    assert scenario["delivered"]["payable_cents"] == 17178

    suspended = set_roster_status(
        artist_id, "SUSPENDED", reason="pending district complaint review"
    )
    assert suspended["roster_status"] == "SUSPENDED"
    assert suspended["vetting_status"] == "CLEARED", (
        "suspension moves the assignability axis only, got "
        f"{suspended['vetting_status']}"
    )

    delivered = read_session(scenario["delivered"]["id"])
    assert delivered["status"] == "DELIVERED", (
        f"a terminal session is out of the cascade's reach, got {delivered['status']}"
    )
    assert delivered["assigned_artist_id"] == artist_id, (
        "the delivered session keeps the artist who taught it, got "
        f"{delivered['assigned_artist_id']}"
    )
    assert delivered["vacated_artist_id"] is None
    assert delivered["encumbered_cents"] == 17178, (
        "the delivered payable stays committed, got "
        f"{delivered['encumbered_cents']}"
    )

    planned = read_session(scenario["planned"]["id"])
    assert planned["status"] == "VACATED", (
        f"the session still in play is vacated, got {planned['status']}"
    )
    assert planned["assigned_artist_id"] is None
    assert planned["vacated_artist_id"] == artist_id, (
        "the vacated session records who held it, got "
        f"{planned['vacated_artist_id']}"
    )
    assert planned["encumbered_cents"] == 0

    residency = read_residency(scenario["residency"]["id"])
    assert residency["vacated_session_count"] == 1, (
        f"exactly one session vacated, got {residency['vacated_session_count']}"
    )
    assert residency["lead_artist_id"] is None, (
        "the suspended artist held the lead, so the reference is cleared"
    )
    assert residency["staffing_status"] == "LEAD_VACANT", (
        "LEAD_VACANT outranks AT_RISK when the lead reference is gone, got "
        f"{residency['staffing_status']}"
    )
    assert residency["encumbered_cents"] == 17178, (
        "only the vacated session released money, got "
        f"{residency['encumbered_cents']}"
    )
    assert residency["sessions_open_count"] == 1, (
        f"the vacated session is still open, got {residency['sessions_open_count']}"
    )
    assert residency["sessions_delivered_count"] == 1
    assert read_school(scenario["school"]["id"])["partnership_health"] == "WATCH", (
        "a residency with a vacant lead puts its school on watch"
    )
