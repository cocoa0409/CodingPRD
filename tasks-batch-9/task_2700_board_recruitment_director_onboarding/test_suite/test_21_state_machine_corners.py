"""State-machine corners: initial states, declared transitions, and the refusals
that guard every other originating state.

Each test drives one lifecycle to the edge of a declared transition and checks
both the refusal code and that the derived rollups on the neighbouring rows were
not moved by the rejected call.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_ASSIGNMENT_STATE_INVALID,
    ERR_CANDIDATE_STATE_INVALID,
    ERR_COMP_AWARD_STATE_INVALID,
    ERR_DIRECTOR_NOT_SEATABLE,
    ERR_DIRECTOR_STATE_INVALID,
    ERR_DIRECTORSHIP_STATE_INVALID,
    ERR_INSUFFICIENT_INTERVIEWS,
    ERR_INTERVIEW_STATE_INVALID,
    ERR_NOMINEE_STATE_INVALID,
    ERR_ONBOARDING_ITEM_STATE_INVALID,
    ERR_SCREEN_STATE_INVALID,
    ERR_SLATE_STATE_INVALID,
)
from test_helpers.assertions import (
    assert_committee_ledger,
    assert_fields_equal,
    assert_onboarding_rollup,
    assert_page,
)
from test_helpers.test_users import SECRETARY, STAFF, make_committee_chair_headers

# ---------------------------------------------------------------------------
# Literals every assertion below reads directly
# ---------------------------------------------------------------------------
# One completed interview scored 4 gives a mean of 4.00; adding a second scored 5
# gives (4 + 5) / 2 = 4.50, both already exact at two decimal places.
SCORE_AVG_AFTER_ONE = 4.00
SCORE_AVG_AFTER_TWO = 4.50

# readiness after the first completion: 32.00 interview (8.0 points per point of a
# 4.00 average) + 30.00 independence + 10.00 shareholder-proposal channel + 10.00
# board capacity, because the candidate holds no outside public board at all.
READINESS_AFTER_ONE = 82.00
# readiness after the second completion: the interview component alone moves to
# 36.00 on the 4.50 average, so the composite lands at 86.00.
READINESS_AFTER_TWO = 86.00

# Two distinct one-hour windows on consecutive days, so the shared interviewer's
# half-open calendar never overlaps.
SESSION_ONE = ("2026-03-02T10:00:00Z", "2026-03-02T11:00:00Z")
SESSION_TWO = ("2026-03-03T10:00:00Z", "2026-03-03T11:00:00Z")

# A full 2026 service year (365 inclusive days) on the shipped policy knobs:
# 12000000 prorated retainer + 0 committee fees + 20000000 equity = 32000000
# pre-offset, so the 2.5 percent tier applies.
AWARD_SHARES_HELD = 700
AWARD_SHARE_PRICE_CENTS = 90000
# 5.0 x the 12000000-cent cash retainer, with no committee seat fees in the base.
OWNERSHIP_REQUIREMENT_CENTS = 60000000
# 700 shares valued at 90000 cents each.
OWNERSHIP_ACTUAL_CENTS = 63000000

# The single required orientation module used wherever a programme must be walked.
ORIENTATION_MODULE_CODE = "BUSINESS_ORIENTATION_101"
ORIENTATION_DUE_ON = "2026-09-30"

# The first end date recorded on an outside seat, and the date a replayed end
# attempt tries to overwrite it with.
FIRST_END_ON = "2026-06-30"
REPLAY_END_ON = "2026-07-31"


# ---------------------------------------------------------------------------
# Shared local setup
# ---------------------------------------------------------------------------
def _seated_chair(client):
    """One SEATED director plus the `CommitteeChair` headers that act as them."""
    chair = X.new_seated_director(
        client,
        full_name="Dana Chair",
        email="dana.chair@issuer.example",
        birth_date="1962-03-15",
        appointed_on="2019-05-01",
        is_independent=True,
    )
    return chair, make_committee_chair_headers(chair["id"])


def _proposal_candidate(client, name, email):
    """A `SHAREHOLDER_PROPOSAL` candidate, the channel that needs no source row."""
    return X.new_candidate(
        client,
        full_name=name,
        email=email,
        birth_date="1974-01-05",
        source_channel="SHAREHOLDER_PROPOSAL",
        shareholder_proponent_name="Cedar Ridge Capital",
    )


def _candidate_at_screen_passed(client, chair_headers, name, email):
    """Source a candidate and walk one clean screen to a favourable determination."""
    candidate = _proposal_candidate(client, name, email)
    X.advance_to_screen_passed(client, candidate["id"], chair_headers)
    return candidate


def _interviewing_candidate(client, name, email):
    """A candidate at SCREEN_PASSED with one SCHEDULED session, plus its ids.

    Returns `(candidate, interviewer, session)`.  The policy is adopted with
    `min_completed_interviews` 1 so a single completion is enough to close the
    interview stage, which is what makes a missing completion observable.
    """
    X.adopt_policy(client, min_completed_interviews=1)
    _, chair_headers = _seated_chair(client)
    interviewer = X.new_seated_director(
        client,
        full_name="Ivan Interviewer",
        email="ivan@issuer.example",
        birth_date="1966-07-07",
        appointed_on="2020-05-01",
    )
    candidate = _candidate_at_screen_passed(client, chair_headers, name, email)
    session = X.schedule_interview(
        client, candidate["id"], interviewer["id"], SESSION_ONE[0], SESSION_ONE[1]
    )
    return candidate, interviewer, session


def _onboarding_director_with_pending_item(client):
    """One director in ONBOARDING whose only required module is still PENDING."""
    director = X.new_onboarding_director(
        client,
        full_name="Pia Pending",
        email="pia@issuer.example",
        birth_date="1972-01-01",
        appointed_on="2026-07-01",
        is_independent=True,
    )
    item = X.new_onboarding_item(
        client,
        director["id"],
        module_code=ORIENTATION_MODULE_CODE,
        category="BUSINESS_ORIENTATION",
        is_required=True,
        credit_hours=2.0,
        due_on=ORIENTATION_DUE_ON,
    )
    return director, item


def _get_session(client, interview_id):
    """Read one interview session back; the frozen helper set has no reader for it."""
    return validate_success(client.get_interview(interview_id, STAFF), 200)


def _audit_committee(client):
    """An AUDIT committee whose `min_seats` of 1 is met by a single active seat."""
    return X.new_committee(
        client,
        code="AUDIT",
        name="Audit Committee",
        authorized_seats=3,
        min_seats=1,
    )


# ---------------------------------------------------------------------------
# InterviewSession: SCHEDULED to COMPLETED
# ---------------------------------------------------------------------------
def test_completing_a_scheduled_interview_records_the_score_and_stamps_completed_at(client):
    """The declared completion transition moves a SCHEDULED session to COMPLETED, stores
    the submitted score and recommendation verbatim and stamps completed_at from the clock.

    PRD: "The session must be `SCHEDULED`, else `ERR_INTERVIEW_STATE_INVALID`, and it moves to `COMPLETED` with `completed_at` set to the logical clock instant."

    Design: Corner/state_machines/interview_complete_moves_scheduled_to_completed
    """
    candidate, _, session = _interviewing_candidate(
        client, "Vera Valid", "vera.valid@cand.example"
    )

    completed = validate_success(
        client.complete_interview(
            session["id"], F.interview_completion_payload(score=4, recommendation="ADVANCE"), STAFF
        ),
        200,
    )

    assert_fields_equal(
        completed,
        {
            "status": "COMPLETED",
            "score": 4,
            "recommendation": "ADVANCE",
            "interview_round": 1,
            "completed_at": C.CLOCK_DEFAULT,
        },
    )
    # Completing a session is not itself a candidate transition: scheduling the
    # first session of the round already moved the candidate into interviewing.
    assert_fields_equal(
        X.get_candidate(client, candidate["id"]), {"status": "INTERVIEWING"}
    )


def test_each_interview_completion_re_derives_the_candidate_interview_aggregates(client):
    """Two completions scored 4 and 5 walk the candidate's rollups from one session to
    two, the mean from 4.00 to 4.50, and the readiness composite from 82.00 to 86.00.

    PRD: "The candidate's `completed_interview_count` is then re-derived as the number of that candidate's sessions whose `status` is `COMPLETED`, the `interview_score_avg` as the mean `score` over exactly those sessions rounded half up to two decimal places (0.00 when there are none), and the `readiness_score` is recomputed."

    Design: Corner/state_machines/interview_complete_updates_the_candidate_interview_aggregates
    """
    candidate, interviewer, session_one = _interviewing_candidate(
        client, "Ava Average", "ava@cand.example"
    )
    session_two = X.schedule_interview(
        client, candidate["id"], interviewer["id"], SESSION_TWO[0], SESSION_TWO[1]
    )

    X.complete_interview(client, session_one["id"], score=4)
    after_one = X.get_candidate(client, candidate["id"])
    assert_fields_equal(
        after_one,
        {
            "completed_interview_count": 1,
            "interview_score_avg": SCORE_AVG_AFTER_ONE,
            "readiness_score": READINESS_AFTER_ONE,
            "external_public_board_count": 0,
            "interview_round": 1,
        },
    )

    X.complete_interview(client, session_two["id"], score=5)
    after_two = X.get_candidate(client, candidate["id"])
    assert_fields_equal(
        after_two,
        {
            "completed_interview_count": 2,
            "interview_score_avg": SCORE_AVG_AFTER_TWO,
            "readiness_score": READINESS_AFTER_TWO,
            "adverse_reference_found": False,
            # Both sessions belong to the round opened at SCREEN_PASSED.
            "interview_round": 1,
        },
    )


def test_completing_a_cancelled_interview_is_refused_and_the_session_never_counts(client):
    """A CANCELLED session is outside the declared completion transition, so the call is
    refused and the candidate still holds too few completed sessions for a reference check.

    PRD: "The session must be `SCHEDULED`, else `ERR_INTERVIEW_STATE_INVALID`, and it moves to `COMPLETED` with `completed_at` set to the logical clock instant."

    Design: Corner/state_machines/completing_a_cancelled_interview_returns_interview_state_invalid
    """
    candidate, _, session = _interviewing_candidate(
        client, "Cody Cancel", "cody@cand.example"
    )
    validate_success(
        client.cancel_interview(
            session["id"], F.interview_cancellation_payload(resolution="CANCELLED"), STAFF
        ),
        200,
    )

    validate_error(
        client.complete_interview(
            session["id"], F.interview_completion_payload(score=4, recommendation="ADVANCE"), STAFF
        ),
        ERR_INTERVIEW_STATE_INVALID,
        409,
    )

    assert_fields_equal(
        _get_session(client, session["id"]),
        {"status": "CANCELLED", "score": None, "completed_at": None},
    )
    assert_fields_equal(
        X.get_candidate(client, candidate["id"]),
        {"completed_interview_count": 0, "interview_score_avg": 0.00},
    )
    # The cancelled slot released the calendar but credited nothing, so the
    # minimum-interview gate on the reference check is still unmet.
    validate_error(
        client.record_reference_check(
            candidate["id"], F.reference_check_payload(reference_count=3, adverse_findings=False), STAFF
        ),
        ERR_INSUFFICIENT_INTERVIEWS,
        422,
    )


# ---------------------------------------------------------------------------
# CommitteeAssignment: PROPOSED to ACTIVE
# ---------------------------------------------------------------------------
def test_activating_an_assignment_for_an_onboarding_director_is_refused(client):
    """Activation demands a director whose service dimension is exactly SEATED, so a
    PROPOSED seat for a director still in ONBOARDING is refused and no seat is occupied.

    PRD: "`ERR_DIRECTOR_NOT_SEATABLE` when an incumbent renomination names a director who is neither `SEATED` nor `RETIREMENT_NOTICED`, or when an assignment is activated for a director whose `service_status` is not exactly `SEATED` or while the committee is `SUSPENDED`"

    Design: Corner/state_machines/activate_assignment_for_an_onboarding_director_returns_not_seatable
    """
    X.adopt_policy(client)
    director, _ = _onboarding_director_with_pending_item(client)
    committee = _audit_committee(client)
    assignment = X.propose_assignment(
        client,
        committee["id"],
        director["id"],
        seat_role="MEMBER",
        term_start_on="2026-08-01",
        term_end_on="2026-12-31",
    )

    validate_error(
        client.activate_assignment(assignment["id"], SECRETARY),
        ERR_DIRECTOR_NOT_SEATABLE,
        409,
    )

    assert_fields_equal(
        X.get_assignment(client, assignment["id"]),
        {"status": "PROPOSED", "activated_at": None},
    )
    assert_committee_ledger(X.get_committee(client, committee["id"]), 0, "UNDER_STRENGTH")


def test_the_same_assignment_activates_once_the_director_has_been_seated(client):
    """Closing the required module completes the programme, seating becomes available, and
    the previously refused activation then occupies exactly one committee seat.

    PRD: "The `filled_seats` is the count of that committee's assignments whose `status` is exactly `ACTIVE`; `PROPOSED`, `ENDED` and `REVOKED` rows never occupy a seat."

    Design: Corner/state_machines/activate_assignment_for_an_onboarding_director_returns_not_seatable
    """
    X.adopt_policy(client)
    director, item = _onboarding_director_with_pending_item(client)
    committee = _audit_committee(client)
    assignment = X.propose_assignment(
        client,
        committee["id"],
        director["id"],
        seat_role="MEMBER",
        term_start_on="2026-08-01",
        term_end_on="2026-12-31",
    )
    validate_error(
        client.activate_assignment(assignment["id"], SECRETARY),
        ERR_DIRECTOR_NOT_SEATABLE,
        409,
    )

    X.complete_item(client, item["id"])
    seated = X.seat_director(client, director["id"])
    assert_fields_equal(seated, {"service_status": "SEATED"})
    assert_onboarding_rollup(seated, "COMPLETE", 100.00)

    activated = X.activate_assignment(client, assignment["id"])
    assert_fields_equal(
        activated, {"status": "ACTIVE", "activated_at": C.CLOCK_DEFAULT}
    )
    # min_seats of 1 is met, but the only active seat is a MEMBER seat, so the
    # posture stops short of AT_STRENGTH.
    assert_committee_ledger(X.get_committee(client, committee["id"]), 1, "UNDER_STRENGTH")


def test_activating_an_already_active_assignment_does_not_take_a_second_seat(client):
    """Replaying activate on an ACTIVE assignment is outside the declared transition, so it
    is refused and the committee's seat ledger stays at one filled seat.

    PRD: "The addressed resource is in a state from which the requested transition is declared; every other originating state, terminal states included, is refused with the code for that resource type"

    Design: Corner/state_machines/activating_an_already_active_assignment_returns_assignment_state_invalid
    """
    X.adopt_policy(client)
    director = X.new_seated_director(
        client,
        full_name="Alma Active",
        email="alma@issuer.example",
        birth_date="1970-01-01",
        appointed_on="2022-01-01",
        is_independent=True,
    )
    committee = _audit_committee(client)
    assignment = X.seat_assignment(
        client,
        committee["id"],
        director["id"],
        seat_role="CHAIR",
        term_start_on="2026-01-01",
        term_end_on="2026-12-31",
    )

    validate_error(
        client.activate_assignment(assignment["id"], SECRETARY),
        ERR_ASSIGNMENT_STATE_INVALID,
        409,
    )

    assert_fields_equal(
        X.get_assignment(client, assignment["id"]),
        {"status": "ACTIVE", "activated_at": C.CLOCK_DEFAULT},
    )
    # One ACTIVE CHAIR seat with min_seats of 1 satisfied gives AT_STRENGTH, and
    # the refused replay left filled_seats at 1 rather than 2.
    assert_committee_ledger(X.get_committee(client, committee["id"]), 1, "AT_STRENGTH")


# ---------------------------------------------------------------------------
# Candidate: the declared initial state
# ---------------------------------------------------------------------------
def test_a_newly_sourced_candidate_starts_in_sourced_with_pending_independence(client):
    """A freshly sourced candidate is born at SOURCED with every derived counter at its
    declared zero, and no independence screen exists for them yet.

    PRD: "A newly sourced candidate begins at `SOURCED` with `independence_result` `PENDING`, `readiness_score` 0.00, `completed_interview_count` 0, `interview_score_avg` 0.00, `external_public_board_count` 0, `interlock_shared_board_count` 0, `reference_check_count` 0, `adverse_reference_found` false, `interview_round` 0, and both `rejection_reason_code` and `deferred_cycle_year` null."

    Design: Corner/state_machines/candidate_starts_in_sourced_with_pending_independence
    """
    X.adopt_policy(client)

    candidate = validate_success(
        client.create_candidate(
            F.candidate_payload(
                full_name="Ini Initial",
                email="ini@cand.example",
                birth_date="1974-01-01",
                source_channel="SHAREHOLDER_PROPOSAL",
                shareholder_proponent_name="Cedar Ridge Capital",
            ),
            STAFF,
        ),
        201,
    )

    assert_fields_equal(
        candidate,
        {
            "status": "SOURCED",
            "independence_result": "PENDING",
            # The creation side effect pins the score to zero: the readiness
            # composite is not computed until a screen is determined.
            "readiness_score": 0.00,
            "completed_interview_count": 0,
            "interview_score_avg": 0.00,
            "external_public_board_count": 0,
            "interlock_shared_board_count": 0,
            "reference_check_count": 0,
            "adverse_reference_found": False,
            "interview_round": 0,
            "rejection_reason_code": None,
            "deferred_cycle_year": None,
        },
    )
    assert_page(
        client.list_candidate_screens(candidate["id"], STAFF), expected_total=0, expected_ids=[]
    )


def test_screening_a_withdrawn_candidate_and_every_other_trigger_is_refused(client):
    """WITHDRAWN is terminal, so opening a screen, withdrawing again and reopening
    screening are all refused, and the candidate still carries no screen row.

    PRD: "Withdrawal is available from `SOURCED`, `SCREENING`, `SCREEN_PASSED`, `INTERVIEWING`, `REFERENCE_CHECK` and `SLATE_ELIGIBLE`, and moves the candidate to the terminal `WITHDRAWN`; a candidate already at `NOMINATED` must have their nominee row voided first, and any other originating status is refused with `ERR_CANDIDATE_STATE_INVALID`."

    Design: Corner/state_machines/screening_a_withdrawn_candidate_returns_candidate_state_invalid
    """
    X.adopt_policy(client)
    candidate = _proposal_candidate(client, "Wilma Withdrawn", "wilma@cand.example")
    withdrawn = validate_success(client.withdraw_candidate(candidate["id"], STAFF), 200)
    assert_fields_equal(withdrawn, {"status": "WITHDRAWN"})

    validate_error(
        client.create_screen(candidate["id"], F.screen_payload(), STAFF),
        ERR_CANDIDATE_STATE_INVALID,
        409,
    )
    validate_error(
        client.withdraw_candidate(candidate["id"], STAFF), ERR_CANDIDATE_STATE_INVALID, 409
    )
    validate_error(
        client.reopen_screening(candidate["id"], STAFF), ERR_CANDIDATE_STATE_INVALID, 409
    )

    assert_fields_equal(
        X.get_candidate(client, candidate["id"]),
        {"status": "WITHDRAWN", "deferred_cycle_year": None},
    )
    assert_page(
        client.list_candidate_screens(candidate["id"], STAFF), expected_total=0, expected_ids=[]
    )


# ---------------------------------------------------------------------------
# IndependenceScreen: determination is declared only from SUBMITTED
# ---------------------------------------------------------------------------
def test_determining_a_draft_screen_before_submit_is_refused(client):
    """A screen that was never submitted cannot be determined: the call is refused, the
    determination stays PENDING and the candidate remains at SCREENING.

    PRD: "the fork is decided by the screen data and never by the actor. The screen must be at `SUBMITTED`, else `ERR_SCREEN_STATE_INVALID`."

    Design: Corner/state_machines/determining_a_draft_screen_before_submit_returns_screen_state_invalid
    """
    X.adopt_policy(client)
    _, chair_headers = _seated_chair(client)
    candidate = _proposal_candidate(client, "Drew Draft", "drew@cand.example")
    screen = X.open_screen(client, candidate["id"])
    assert_fields_equal(screen, {"status": "DRAFT"})

    validate_error(
        client.determine_screen(screen["id"], chair_headers), ERR_SCREEN_STATE_INVALID, 409
    )

    assert_fields_equal(
        X.get_screen(client, screen["id"]),
        {"status": "DRAFT", "determination": "PENDING", "determined_at": None},
    )
    assert_fields_equal(
        X.get_candidate(client, candidate["id"]),
        {"status": "SCREENING", "independence_result": "PENDING"},
    )


# ---------------------------------------------------------------------------
# SlateNominee and NominationSlate
# ---------------------------------------------------------------------------
def test_voiding_an_already_voided_nominee_does_not_decrement_the_slate_twice(client):
    """The void of a nominee is not replayable: the second call is refused and the slate's
    nominee rollups stay where the first void left them.

    PRD: "The nominee must be `PROPOSED` or `CONFIRMED` and its slate must be `DRAFT` or `COMMITTEE_REVIEW`, else `ERR_NOMINEE_STATE_INVALID`."

    Design: Corner/state_machines/voiding_an_already_voided_nominee_returns_nominee_state_invalid
    """
    X.adopt_policy(client)
    incumbent = X.new_seated_director(
        client,
        full_name="Ida Incumbent",
        email="ida@issuer.example",
        birth_date="1968-01-01",
        appointed_on="2021-01-01",
        is_independent=True,
    )
    slate = X.new_slate(client, cycle_year=C.CYCLE_YEAR, seat_count=9)
    nominee = X.add_incumbent_nominee(client, slate["id"], incumbent["id"], 1)

    voided = validate_success(client.void_slate_nominee(nominee["id"], STAFF), 200)
    assert_fields_equal(
        voided, {"status": "VOIDED", "voided_at": C.CLOCK_DEFAULT}
    )

    validate_error(
        client.void_slate_nominee(nominee["id"], STAFF), ERR_NOMINEE_STATE_INVALID, 409
    )

    assert_fields_equal(
        X.get_slate(client, slate["id"]),
        {"nominee_count": 0, "independent_nominee_count": 0, "independent_nominee_pct": 0.00},
    )
    # Voiding an incumbent's nominee row is a slate-side event only; the sitting
    # director keeps their seat.
    assert_fields_equal(
        X.get_director(client, incumbent["id"]), {"service_status": "SEATED"}
    )


def test_deciding_a_draft_slate_reports_the_state_code_ahead_of_the_quorum_rule(client):
    """An APPROVE decision is declared only from COMMITTEE_REVIEW, so a DRAFT slate is
    refused on its state rather than on the quorum it also fails with zero ballots.

    PRD: "`APPROVE` requires the slate to be at `COMMITTEE_REVIEW`, with `quorum_met` true, `approval_pct` at or above `approval_threshold_pct` and `independence_shortfall` false."

    Design: Corner/state_machines/deciding_a_draft_slate_returns_slate_state_invalid
    """
    X.adopt_policy(client)
    _, chair_headers = _seated_chair(client)
    incumbent = X.new_seated_director(
        client,
        full_name="Ida Incumbent",
        email="ida@issuer.example",
        birth_date="1968-01-01",
        appointed_on="2021-01-01",
        is_independent=True,
    )
    slate = X.new_slate(client, cycle_year=C.CYCLE_YEAR, seat_count=9)
    X.add_incumbent_nominee(client, slate["id"], incumbent["id"], 1)

    validate_error(
        client.decide_slate(
            slate["id"], F.decision_payload(decision="APPROVE"), chair_headers
        ),
        ERR_SLATE_STATE_INVALID,
        409,
    )

    assert_fields_equal(
        X.get_slate(client, slate["id"]),
        {"status": "DRAFT", "revision_count": 0, "quorum_met": False},
    )


# ---------------------------------------------------------------------------
# OnboardingItem, Director, ExternalDirectorship and the award
# ---------------------------------------------------------------------------
def test_waiving_an_already_completed_onboarding_item_is_refused(client):
    """COMPLETED and WAIVED are alternative terminal closures of the same PENDING module,
    so waiving a completed item is refused and no waiver reason is recorded.

    PRD: "Either closure attempted on an item that is already `COMPLETED` or `WAIVED` is refused with `ERR_ONBOARDING_ITEM_STATE_INVALID`."

    Design: Corner/state_machines/waiving_a_completed_onboarding_item_returns_item_state_invalid
    """
    X.adopt_policy(client)
    director = X.new_onboarding_director(
        client,
        full_name="Wanda Waiver",
        email="wanda@issuer.example",
        birth_date="1972-01-01",
        appointed_on="2026-07-01",
    )
    item = X.new_onboarding_item(
        client,
        director["id"],
        module_code=ORIENTATION_MODULE_CODE,
        category="BUSINESS_ORIENTATION",
        is_required=True,
        credit_hours=2.0,
        due_on=ORIENTATION_DUE_ON,
    )
    X.complete_item(client, item["id"])

    validate_error(
        client.waive_onboarding_item(
            item["id"],
            F.waiver_payload(waiver_reason="Credited from prior board service"),
            SECRETARY,
        ),
        ERR_ONBOARDING_ITEM_STATE_INVALID,
        409,
    )

    assert_fields_equal(
        X.get_item(client, item["id"]),
        {"status": "COMPLETED", "waiver_reason": None, "completed_at": C.CLOCK_DEFAULT},
    )
    assert_onboarding_rollup(X.get_director(client, director["id"]), "COMPLETE", 100.00)


def test_seating_a_director_who_is_not_onboarding_reports_the_service_state_code(client):
    """Seating is declared only out of ONBOARDING, so a SEATED director and a RESIGNED one
    are both refused on the service dimension rather than on the onboarding gate.

    PRD: "A director whose `service_status` is anything other than `ONBOARDING` cannot be seated, and the attempt is refused with `ERR_DIRECTOR_STATE_INVALID`."

    Design: Corner/state_machines/seating_an_already_seated_director_returns_director_state_invalid
    """
    X.adopt_policy(client)
    already_seated = X.new_seated_director(
        client,
        full_name="Sam Seated",
        email="sam@issuer.example",
        birth_date="1970-01-01",
        appointed_on="2022-01-01",
    )
    departed = X.new_seated_director(
        client,
        full_name="Gone Away",
        email="gone@issuer.example",
        birth_date="1971-01-01",
        appointed_on="2022-01-01",
    )
    X.record_departure(client, departed["id"], notice_type="RESIGNATION")

    # Neither director owns a single onboarding item, so the onboarding gate would
    # also fail; the state precondition on the target row is reported instead.
    validate_error(
        client.seat_director(already_seated["id"], SECRETARY), ERR_DIRECTOR_STATE_INVALID, 409
    )
    validate_error(
        client.seat_director(departed["id"], SECRETARY), ERR_DIRECTOR_STATE_INVALID, 409
    )

    assert_fields_equal(
        X.get_director(client, already_seated["id"]), {"service_status": "SEATED"}
    )
    assert_fields_equal(
        X.get_director(client, departed["id"]), {"service_status": "RESIGNED"}
    )


def test_ending_an_already_ended_directorship_keeps_the_first_end_date(client):
    """ENDED is terminal for an outside seat: the replayed end is refused, the recorded
    end date is not overwritten, and the subject's public board count is not decremented twice.

    PRD: "a seat that is already `ENDED` cannot be ended again and is refused with `ERR_DIRECTORSHIP_STATE_INVALID`"

    Design: Corner/state_machines/ending_an_already_ended_directorship_returns_directorship_state_invalid
    """
    X.adopt_policy(client)
    director = X.new_seated_director(
        client,
        full_name="Ella Ended",
        email="ella@issuer.example",
        birth_date="1970-01-01",
        appointed_on="2022-01-01",
    )
    first_company = X.new_external_company(
        client, name="Northwind Industries", ticker="NWI", is_public=True, is_competitor=False
    )
    second_company = X.new_external_company(
        client, name="Cascade Logistics", ticker="CSL", is_public=True, is_competitor=False
    )
    X.seat_director_on_board(client, director["id"], first_company["id"], start_on="2023-01-01")
    second_seat = X.seat_director_on_board(
        client, director["id"], second_company["id"], start_on="2023-02-01"
    )
    validate_success(
        client.end_external_directorship(
            second_seat["id"], F.end_directorship_payload(end_on=FIRST_END_ON), STAFF
        ),
        200,
    )

    validate_error(
        client.end_external_directorship(
            second_seat["id"], F.end_directorship_payload(end_on=REPLAY_END_ON), STAFF
        ),
        ERR_DIRECTORSHIP_STATE_INVALID,
        409,
    )

    assert_fields_equal(
        X.get_directorship(client, second_seat["id"]),
        {"status": "ENDED", "end_on": FIRST_END_ON},
    )
    # Only the first seat is still ACTIVE, and one outside board plus this one is
    # inside the default limit of four.
    assert_fields_equal(
        X.get_director(client, director["id"]),
        {"external_public_board_count": 1, "compliance_status": "COMPLIANT"},
    )


def test_finalizing_an_already_finalized_award_keeps_its_first_finalized_at(client):
    """Finalize is declared only out of DRAFT, so replaying it is refused, finalized_at
    keeps its first value and the director's ownership posture does not move.

    PRD: "The award must be `DRAFT`, else `ERR_COMP_AWARD_STATE_INVALID`, and the owning director's `service_status` must be `ONBOARDING`, `SEATED` or `RETIREMENT_NOTICED`, else `ERR_DIRECTOR_STATE_INVALID`."

    Design: Corner/state_machines/finalizing_an_already_finalized_award_returns_comp_award_state_invalid
    """
    X.adopt_policy(client)
    director = X.new_seated_director(
        client,
        full_name="Fina Lized",
        email="fina@issuer.example",
        birth_date="1970-01-01",
        appointed_on="2022-01-01",
        shares_held=AWARD_SHARES_HELD,
    )
    award = X.new_comp_award(
        client,
        director["id"],
        cycle_year=C.CYCLE_YEAR,
        service_start_on="2026-01-01",
        service_end_on="2026-12-31",
        share_price_cents=AWARD_SHARE_PRICE_CENTS,
        shares_held=AWARD_SHARES_HELD,
    )
    finalized = X.finalize_award(client, award["id"])
    assert_fields_equal(
        finalized,
        {
            "status": "FINALIZED",
            "finalized_at": C.CLOCK_DEFAULT,
            "ownership_requirement_cents": OWNERSHIP_REQUIREMENT_CENTS,
            "ownership_actual_cents": OWNERSHIP_ACTUAL_CENTS,
            "ownership_compliant": True,
        },
    )

    validate_error(
        client.finalize_comp_award(award["id"], SECRETARY), ERR_COMP_AWARD_STATE_INVALID, 409
    )

    assert_fields_equal(
        X.get_award(client, award["id"]),
        {"status": "FINALIZED", "finalized_at": C.CLOCK_DEFAULT},
    )
    assert_fields_equal(
        X.get_director(client, director["id"]),
        {"shares_held": AWARD_SHARES_HELD, "compliance_status": "COMPLIANT"},
    )
