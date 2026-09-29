"""Appeals, the remedies they carry, and the officer transition that follows a
certified result."""

from test_helpers import (
    AFTER_TERM_START,
    ApiErrorId,
    TERM_END_DATE,
    TERM_START_DATE,
    TEST_USERS,
    assert_appeal,
    assert_instant_equals,
    create_appeal_payload,
    declare_election,
    declare_office,
    file_candidacy,
    file_compliance_case,
    make_candidate_headers,
    open_petitioning,
    read_appeal,
    read_ballot,
    read_ballot_line,
    read_candidacy,
    read_case,
    read_election,
    read_office,
    record_training,
    register_student,
    run_transition_checkpoint,
    set_clock,
    setup_certified_election_with_results_appeal,
    setup_certified_election_with_runner_up,
    setup_disqualified_candidacy_with_appeal,
    setup_lapsed_officer_checkpoint,
    validate_error,
    validate_paginated,
    validate_success,
)

COMMISSIONER = TEST_USERS["commissioner_headers"]
ADVISOR = TEST_USERS["advisor_headers"]
SECOND_ADVISOR = TEST_USERS["second_advisor_headers"]


# ─── Filing and resolving an appeal ───────────────────────────────────────────

def test_an_appeal_citing_a_case_from_another_election_is_refused(api):
    """PRD §3.9: "A `compliance_case_id` may be supplied to cite the specific ruling under
    challenge, or omitted for a pure results appeal; when supplied, the cited case's own
    election and candidacy must both match the appeal's, or the filing is refused with
    `ERR_APPEAL_SCOPE_INVALID`."

    Design: Corner/validations/appeal_citing_case_from_another_election_returns_scope_invalid
    """
    first_election = declare_election(title="Fall 2026 SGA General")
    second_election = declare_election(title="Fall 2026 Class Council")
    first_office = declare_office(first_election["id"], eligible_class_years=["SENIOR"])
    second_office = declare_office(
        second_election["id"], name="Senior Class Chair", eligible_class_years=["SENIOR"]
    )
    student = register_student(class_year="SENIOR", gpa=3.50, credits_completed=95)
    open_petitioning(first_election["id"])
    open_petitioning(second_election["id"])
    first_candidacy = file_candidacy(
        first_election["id"], first_office["id"], student["id"]
    )
    second_candidacy = file_candidacy(
        second_election["id"], second_office["id"], student["id"]
    )
    case = file_compliance_case(
        first_election["id"], first_candidacy, severity="MINOR",
        rule_code="C-1.1", description="Chalking outside the approved zone",
    )

    validate_error(
        api.create_appeal(
            create_appeal_payload(
                second_election["id"], second_candidacy["id"],
                remedy_requested="REINSTATEMENT",
                grounds="Wrong election cited on purpose",
                compliance_case_id=case["id"],
            ),
            make_candidate_headers(student["id"]),
        ),
        ApiErrorId.ERR_APPEAL_SCOPE_INVALID.value,
        422,
    )

    _, meta = validate_paginated(
        api.list_appeals(COMMISSIONER, params={"election_id": second_election["id"]})
    )
    assert meta["total_count"] == 0, "the out-of-scope appeal was never filed"


def test_sustaining_a_reinstatement_unwinds_the_whole_disqualification(api):
    """PRD §3.9: "A `REINSTATEMENT` unwinds a disqualification and therefore requires the
    appeal to have cited a `compliance_case_id`: the cited compliance case moves
    `UPHELD → DISMISSED` with its `penalty_points` reset to zero, the candidacy's
    `penalty_points_total` is recomputed and its `disqualified_reason` cleared, the
    candidacy moves `DISQUALIFIED → ON_BALLOT`, and every ballot line naming it that had
    been voided returns `VOIDED → ACTIVE` — provided the parent ballot is not itself
    `VOIDED` — with the ballot's `active_line_count` incremented by one for each line
    restored."
    PRD §3.9: "Sustaining an appeal moves it `FILED → SUSTAINED`, stamps
    `resolved_by_user_id` and the optional `resolution_note`, and then applies the remedy
    that was requested — each remedy with its own distinct set of consequences."

    Design: Corner/state_machines/appeal_sustain_reinstatement_restores_candidacy_and_ballot_line
    """
    scenario = setup_disqualified_candidacy_with_appeal(remedy="REINSTATEMENT")

    sustained = validate_success(
        api.sustain_appeal(
            scenario["appeal"]["id"],
            SECOND_ADVISOR,
            {"resolution_note": "Chain of custody could not be established"},
        )
    )

    assert_appeal(sustained)
    assert sustained["status"] == "SUSTAINED"
    assert sustained["resolved_by_user_id"] == "advisor-2"

    case = read_case(scenario["upheld_case"]["id"])
    assert case["status"] == "DISMISSED"
    assert case["penalty_points"] == 0

    respondent = read_candidacy(scenario["respondent"]["id"])
    assert respondent["penalty_points_total"] == 0
    assert respondent["status"] == "ON_BALLOT"
    assert respondent["disqualified_reason"] is None

    assert read_ballot_line(scenario["voided_line"]["id"])["status"] == "ACTIVE"
    assert read_ballot(scenario["ballot"]["id"])["active_line_count"] == 2


def test_the_advisor_who_upheld_the_case_may_not_sustain_the_appeal_citing_it(api):
    """PRD §3.9: "An advisor may neither sustain nor deny an appeal when their own
    `X-User-ID` equals the `certified_by_user_id` recorded on the election in question,
    and — when the appeal cites a compliance case — when their own `X-User-ID` equals the
    `adjudicated_by_user_id` recorded on that cited case. Either overlap is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/case_adjudicator_cannot_sustain_the_appeal_that_cites_the_case
    """
    scenario = setup_disqualified_candidacy_with_appeal(remedy="REINSTATEMENT")

    validate_error(
        api.sustain_appeal(
            scenario["appeal"]["id"], ADVISOR,
            {"resolution_note": "Reviewing my own ruling"},
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )

    case = read_case(scenario["upheld_case"]["id"])
    assert case["adjudicated_by_user_id"] == "advisor-1"
    assert case["status"] == "UPHELD"

    appeal = read_appeal(scenario["appeal"]["id"])
    assert appeal["status"] == "FILED"
    assert appeal["resolved_by_user_id"] is None
    assert read_candidacy(scenario["respondent"]["id"])["status"] == "DISQUALIFIED"


def test_the_certifying_advisor_may_not_deny_a_results_appeal(api):
    """PRD §3.9: "**Segregation of duties governs who may resolve an appeal.** An advisor
    may neither sustain nor deny an appeal when their own `X-User-ID` equals the
    `certified_by_user_id` recorded on the election in question, and — when the appeal
    cites a compliance case — when their own `X-User-ID` equals the
    `adjudicated_by_user_id` recorded on that cited case."
    PRD §3.9: "The advisor who blessed the result may not sit in judgment on a challenge to
    it, and the advisor who upheld a case may not hear the appeal against that case."

    Design: Corner/rbac/certifying_advisor_cannot_deny_a_results_appeal
    """
    scenario = setup_certified_election_with_results_appeal()

    validate_error(
        api.deny_appeal(
            scenario["appeal"]["id"], ADVISOR,
            {"resolution_note": "Denying an appeal against my own certification"},
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )

    election = read_election(scenario["election"]["id"])
    assert election["certified_by_user_id"] == "advisor-1"
    assert election["status"] == "CERTIFIED"

    appeal = read_appeal(scenario["appeal"]["id"])
    assert appeal["status"] == "FILED"
    assert appeal["resolved_by_user_id"] is None


# ─── The officer transition axis ──────────────────────────────────────────────

def test_training_short_of_the_requirement_leaves_the_transition_pending(api):
    """PRD §3.9: "A winner then records training: each submission adds its
    `modules_completed` to the candidacy's running `training_modules_completed`, and when
    the running total reaches the office's `required_training_modules`, compared as "at
    least", the axis advances `PENDING → TRAINING_COMPLETE`. A submission that leaves the
    running total short of the requirement still succeeds — the counter advances and
    `transition_status` simply stays at `PENDING`."
    PRD §3.8: "each winner copies `term_start_date` and `term_end_date` from its office,
    opens its officer transition by moving `transition_status` `NOT_APPLICABLE → PENDING`,
    and raises the office's `filled_seat_count` by one."

    Design: Corner/state_machines/record_training_below_requirement_keeps_transition_status_pending
    """
    scenario = setup_certified_election_with_runner_up(required_training_modules=3)
    winner = scenario["winner"]

    recorded = validate_success(
        api.record_training(
            winner["id"], {"modules_completed": 2},
            make_candidate_headers(winner["student_id"]),
        )
    )

    assert recorded["training_modules_completed"] == 2
    assert recorded["transition_status"] == "PENDING", (
        f"two of three modules leaves the axis at PENDING, got {recorded['transition_status']}"
    )
    assert recorded["status"] == "ELECTED", "the two axes move independently"
    assert_instant_equals(
        recorded["term_start_date"], TERM_START_DATE, "Candidacy.term_start_date"
    )

    election = read_election(scenario["election"]["id"])
    assert election["status"] == "CERTIFIED"
    assert election["certified_by_user_id"] == "advisor-1"


def test_seating_an_untrained_officer_reports_the_training_error(api):
    """PRD §3.9: "An officer still sitting at `PENDING` is treated deliberately: the
    request passes the state gate rather than being rejected as an invalid source state,
    and is refused further along with `ERR_TRAINING_INCOMPLETE`, so the officer is told the
    actual reason rather than a generic state error."
    PRD §3.9: "Seating the officer moves the axis `TRAINING_COMPLETE → ACTIVE`, stamps
    `activated_at` from the logical clock, and is the advisor's act."

    Design: Corner/endpoints/activate_officer_with_incomplete_training_returns_training_incomplete
    """
    scenario = setup_certified_election_with_runner_up(required_training_modules=3)
    winner = scenario["winner"]
    record_training(winner, 1)
    set_clock(AFTER_TERM_START)

    validate_error(
        api.activate_officer(winner["id"], ADVISOR),
        ApiErrorId.ERR_TRAINING_INCOMPLETE.value,
        422,
    )

    after = read_candidacy(winner["id"])
    assert after["transition_status"] == "PENDING"
    assert after["training_modules_completed"] == 1
    assert after["activated_at"] is None
    assert after["status"] == "ELECTED"


# ─── The three-hop transition checkpoint ──────────────────────────────────────

def test_the_checkpoint_lapses_the_untrained_officer_and_vacates_the_seat(api):
    """PRD §3.9: "The first hop lapses the delinquent: any officer whose
    `transition_status` is `PENDING`, whose `term_start_date` the logical clock has passed
    strictly, and whose `training_modules_completed` remains below the office's
    `required_training_modules`, moves `PENDING → LAPSED`."
    PRD §3.9: "The second hop vacates the seat: that candidacy moves `ELECTED → VACATED`,
    the office's `filled_seat_count` falls by one, and the office moves
    `DECIDED → VACANT_SEAT`."

    Design: Difficulty/transitive_cascade/checkpoint_lapse_to_seat_vacate_to_alternate_promotion
    """
    scenario = setup_lapsed_officer_checkpoint()

    run_transition_checkpoint(scenario["election"]["id"])

    lapsed = read_candidacy(scenario["winner"]["id"])
    assert lapsed["transition_status"] == "LAPSED", (
        f"the officer recorded no training at all, got {lapsed['transition_status']}"
    )
    assert lapsed["status"] == "VACATED", (
        f"the lapse vacates the seat, got {lapsed['status']}"
    )


def test_the_checkpoint_promotes_the_ranking_alternate_into_the_vacancy(api):
    """PRD §3.9: "The third hop promotes the alternate: among that office's `ELIMINATED`
    candidacies, the first by the ranking of Section 3.8 — `certified_votes_count`
    descending, then `petition_signature_valid_count` descending, then `created_at`
    ascending — moves `ELIMINATED → ELECTED`, copies `term_start_date` and `term_end_date`
    from the office, opens its own transition at `PENDING`, raises `filled_seat_count` by
    one, and returns the office `VACANT_SEAT → DECIDED`."
    PRD §3.9: "Once every candidacy of the election in `ELECTED` has reached
    `transition_status` `ACTIVE`, and the logical clock has reached the latest
    `term_start_date` among the election's offices, the election moves
    `CERTIFIED → CLOSED`, which is terminal."

    Design: Difficulty/transitive_cascade/checkpoint_lapse_to_seat_vacate_to_alternate_promotion
    """
    scenario = setup_lapsed_officer_checkpoint()

    run_transition_checkpoint(scenario["election"]["id"])

    alternate = read_candidacy(scenario["runner_up"]["id"])
    assert alternate["status"] == "ELECTED", (
        f"the ranking runner-up takes the seat, got {alternate['status']}"
    )
    assert alternate["transition_status"] == "PENDING"
    assert_instant_equals(
        alternate["term_start_date"], TERM_START_DATE, "the alternate's term_start_date"
    )
    assert_instant_equals(
        alternate["term_end_date"], TERM_END_DATE, "the alternate's term_end_date"
    )

    office = read_office(scenario["office"]["id"])
    assert office["status"] == "DECIDED", (
        f"the promotion returns the seat to DECIDED, got {office['status']}"
    )
    assert office["filled_seat_count"] == 1

    assert read_election(scenario["election"]["id"])["status"] == "CERTIFIED", (
        "the new officer is not yet ACTIVE, so the cycle stays open"
    )
