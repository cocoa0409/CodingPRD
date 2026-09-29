"""Statutory windows, capacity caps and the gates that shadow one another.

Every case in this module is built from an empty database up to the exact
instant the rule under test turns on: the posture hold that outranks the
message-compliance analysis, the cure and objection windows that are inclusive
at their closing instant, the per-party observer cap, the prohibited risk
score, and the order in which certification reports its own refusals.
"""
from test_helpers import (
    BOARD,
    DIRECTOR,
    UNION,
    ApiErrorId,
    accuracy_review,
    api_client,
    assert_instant_equals,
    close_poll_session,
    create_campaign_message,
    create_election_agreement,
    create_poll_session,
    create_voter_list,
    designate_observer,
    determine_charge,
    docket_charge,
    latest_round,
    open_polls,
    open_scope_analysis,
    post_tally,
    read_campaign_message,
    read_petition,
    read_poll_session,
    read_round,
    read_voter_list,
    register_supervisor,
    resolve_ballot,
    review_message,
    review_voter_list,
    revise_tally,
    rule_classification,
    score_classification,
    segregate_ballot,
    set_clock,
    settle_charge,
    stipulate_agreement,
    submit_message_for_review,
    submit_voter_list,
    validate_error,
    validate_success,
    verify_showing,
)
from test_helpers import (
    add_classification,
    add_complete_entries,
    add_incomplete_entries,
    create_petition,
    create_trained_supervisor,
)


# --------------------------------------------------------------------------
# Case-building blocks shared by the scenarios below.
# --------------------------------------------------------------------------
PROD_SPEC = {
    "code": "PROD",
    "title": "Production Operator",
    "headcount": 60,
    "avg_hourly_wage_cents": 2400,
    "shift_code": "A",
    "work_location": "PLANT_1",
    "supervisory_authority_count": 0,
    "employer_position": "INCLUDE",
    "union_position": "INCLUDE",
    "supervision_overlap": 88,
    "skills_overlap": 90,
    "functional_integration": 92,
    "interchange_rate": 74,
    "work_conditions_overlap": 95,
}

MAINT_SPEC = {
    "code": "MAINT",
    "title": "Maintenance Mechanic",
    "headcount": 30,
    "avg_hourly_wage_cents": 3200,
    "shift_code": "A",
    "work_location": "PLANT_1",
    "supervisory_authority_count": 0,
    "employer_position": "INCLUDE",
    "union_position": "INCLUDE",
    "supervision_overlap": 82,
    "skills_overlap": 78,
    "functional_integration": 86,
    "interchange_rate": 61,
    "work_conditions_overlap": 84,
}

POLLS_OPEN_AT = "2026-09-01T06:00:00Z"
POLLS_CLOSE_AT = "2026-09-01T17:00:00Z"
APPROVAL_CLOCK = "2026-08-20T15:00:00Z"
LIST_DUE_AT = "2026-08-24T23:59:59Z"


def _soi_verified_case(clock="2026-08-03T09:00:00Z"):
    """Docket a case, rule both classifications and verify a sufficient showing."""
    set_clock(clock)
    petition = create_petition()
    open_scope_analysis(petition["id"])
    classifications = [
        add_classification(petition["id"], **PROD_SPEC),
        add_classification(petition["id"], **MAINT_SPEC),
    ]
    for classification in classifications:
        score_classification(classification["id"], "TRADITIONAL")
    ruled = [rule_classification(c["id"], "INCLUDED") for c in classifications]
    petition = verify_showing(petition["id"])
    return petition, ruled


def _election_set_case(polls_open_at=POLLS_OPEN_AT, polls_close_at=POLLS_CLOSE_AT):
    """Take a verified case through a stipulated approval, so round 1 exists."""
    petition, classifications = _soi_verified_case()
    agreement = create_election_agreement(petition["id"])
    set_clock(APPROVAL_CLOCK)
    agreement = stipulate_agreement(
        agreement["id"],
        approved_election_date="2026-09-01",
        voting_method="MANUAL",
        polls_open_at=polls_open_at,
        polls_close_at=polls_close_at,
    )
    return {
        "petition": read_petition(petition["id"]),
        "classifications": classifications,
        "agreement": agreement,
        "round": latest_round(petition["id"]),
    }


def _accepted_voter_list(case, entry_count=3, submit_clock="2026-08-21T10:00:00Z"):
    """A complete list filed on time and accepted, which is what lets polls open."""
    voter_list = create_voter_list(case["petition"]["id"], case["agreement"]["id"])
    entries = add_complete_entries(
        voter_list["id"], case["classifications"][0]["id"], entry_count
    )
    set_clock(submit_clock)
    submit_voter_list(voter_list["id"])
    review_voter_list(voter_list["id"], "ACCEPT")
    return read_voter_list(voter_list["id"]), entries


def _two_sessions(round_id):
    """Lay out the cafeteria and breakroom sessions on a scheduled round."""
    first = create_poll_session(
        round_id,
        location_code="PLANT_1_CAFETERIA",
        session_start_at=POLLS_OPEN_AT,
        session_end_at=POLLS_CLOSE_AT,
    )
    second = create_poll_session(
        round_id,
        location_code="PLANT_2_BREAKROOM",
        session_start_at=POLLS_OPEN_AT,
        session_end_at=POLLS_CLOSE_AT,
    )
    return [first, second]


def _polls_closed_case():
    """Both sessions closed on 82 counted ballots with three challenges still open.

    The counted figures are the worked pair 30/25/1 and 12/14/0, so the round
    accumulates 42 for, 39 against, 1 void and a ballots_cast_total of 85.
    """
    case = _election_set_case()
    voter_list, entries = _accepted_voter_list(case)
    sessions = _two_sessions(case["round"]["id"])
    set_clock(POLLS_OPEN_AT)
    open_polls(case["round"]["id"])
    ballots = [
        segregate_ballot(
            sessions[0]["id"], challenger_party="EMPLOYER", basis="SUPERVISOR"
        ),
        segregate_ballot(
            sessions[0]["id"], challenger_party="UNION", basis="NOT_ON_LIST"
        ),
        segregate_ballot(
            sessions[1]["id"], challenger_party="EMPLOYER", basis="OUTSIDE_UNIT"
        ),
    ]
    set_clock("2026-09-01T17:30:00Z")
    close_poll_session(
        sessions[0]["id"], votes_for_count=30, votes_against_count=25, void_count=1
    )
    close_poll_session(
        sessions[1]["id"], votes_for_count=12, votes_against_count=14, void_count=0
    )
    case["voter_list"] = voter_list
    case["entries"] = entries
    case["sessions"] = sessions
    case["ballots"] = ballots
    case["round"] = read_round(case["round"]["id"])
    return case


def _revised_tally_case(post_clock="2026-09-02T12:00:00Z"):
    """Post the provisional tally, dispose of the three challenges, then revise.

    Two challenges count for and one is voided, so the revised figures are
    44 for, 39 against and 2 void on the same 85 ballots cast.
    """
    case = _polls_closed_case()
    set_clock(post_clock)
    post_tally(case["round"]["id"])
    resolve_ballot(case["ballots"][0]["id"], resolution="COUNTED_FOR")
    resolve_ballot(case["ballots"][1]["id"], resolution="COUNTED_FOR")
    resolve_ballot(case["ballots"][2]["id"], resolution="VOIDED")
    revise_tally(case["round"]["id"])
    case["round"] = read_round(case["round"]["id"])
    case["petition"] = read_petition(case["petition"]["id"])
    return case


def _captive_audience_draft(petition_id, planned_delivery_at, **overrides):
    """Draft a captive-audience meeting fronted by a fully trained supervisor."""
    supervisor = create_trained_supervisor(petition_id)
    message = create_campaign_message(
        petition_id,
        channel="CAPTIVE_AUDIENCE_MEETING",
        presenter_supervisor_id=supervisor["id"],
        planned_delivery_at=planned_delivery_at,
        **overrides,
    )
    return supervisor, message


# --------------------------------------------------------------------------
# The posture hold answers before any message-level compliance analysis.
# --------------------------------------------------------------------------
def test_a_blocked_case_refuses_delivery_before_it_analyses_the_message():
    """A blocking charge stops delivery of an approved captive-audience meeting even
    though that meeting also sits inside the pre-poll blackout.

    PRD: "And a delivery attempted while the case is blocked by a charge, on a message that also carries a per-se blackout violation, reports `ERR_CASE_POSTURE_BLOCKED` (409) rather than `ERR_PEERLESS_PLYWOOD_WINDOW` (422), because the posture gate is a state check on the parent case and runs before any message-level compliance analysis."

    Design: Corner/validations/posture_gate_outranks_the_per_se_blackout_gate
    """
    petition, _ = _soi_verified_case()
    _, message = _captive_audience_draft(
        petition["id"], "2026-09-01T05:00:00Z", audience_scope="UNIT_WIDE"
    )
    accuracy_review(message["id"])
    submit_message_for_review(message["id"])
    review_message(message["id"], "APPROVE")
    drafted = read_campaign_message(message["id"])
    assert drafted["status"] == "APPROVED"
    assert drafted["peerless_plywood_violation"] is False

    agreement = create_election_agreement(petition["id"])
    set_clock(APPROVAL_CLOCK)
    stipulate_agreement(
        agreement["id"],
        approved_election_date="2026-09-01",
        voting_method="MANUAL",
        polls_open_at=POLLS_OPEN_AT,
        polls_close_at=POLLS_CLOSE_AT,
    )
    round_row = latest_round(petition["id"])
    docket_charge(
        petition["id"],
        blocking_requested=True,
        section_code="8A1",
        conduct_occurred_at="2026-08-19T15:00:00Z",
    )

    refused = api_client.deliver_communication(message["id"], DIRECTOR)
    validate_error(refused, ApiErrorId.ERR_CASE_POSTURE_BLOCKED)

    held = read_campaign_message(message["id"])
    assert held["status"] == "BLOCKED"
    assert held["blocked_reason"] == "POSTURE_BLOCKED"
    assert held.get("delivered_at") is None

    blocked_case = read_petition(petition["id"])
    assert blocked_case["case_posture"] == "BLOCKED"
    assert blocked_case["blocking_charge_count"] == 1
    assert blocked_case["case_status"] == "ELECTION_SET"
    assert read_round(round_row["id"])["status"] == "SUSPENDED"


def test_the_blackout_refusal_surfaces_once_the_posture_hold_is_released():
    """With the charge settled and the case open again, the same delivery is refused
    for the blackout the logical clock now sits inside.

    PRD: "Delivery requires the case's `case_posture` to be `OPEN`, requires that the logical clock not sit inside the current round's captive-audience blackout, and requires the campaign period to still be open — the current round must be `SCHEDULED` or `POLLS_OPEN` and the logical clock must be before that round's `polls_close_at`."

    Design: Corner/validations/posture_gate_outranks_the_per_se_blackout_gate
    """
    petition, _ = _soi_verified_case()
    _, message = _captive_audience_draft(
        petition["id"], "2026-09-01T05:00:00Z", audience_scope="UNIT_WIDE"
    )
    accuracy_review(message["id"])
    submit_message_for_review(message["id"])
    review_message(message["id"], "APPROVE")

    agreement = create_election_agreement(petition["id"])
    set_clock(APPROVAL_CLOCK)
    stipulate_agreement(
        agreement["id"],
        approved_election_date="2026-09-01",
        voting_method="MANUAL",
        polls_open_at=POLLS_OPEN_AT,
        polls_close_at=POLLS_CLOSE_AT,
    )
    round_row = latest_round(petition["id"])
    charge = docket_charge(
        petition["id"],
        blocking_requested=True,
        section_code="8A1",
        conduct_occurred_at="2026-08-19T15:00:00Z",
    )
    settle_charge(charge["id"], "NON_BOARD")

    released = read_petition(petition["id"])
    assert released["case_posture"] == "OPEN"
    assert released["blocking_charge_count"] == 0
    assert read_round(round_row["id"])["status"] == "SCHEDULED"
    restored = read_campaign_message(message["id"])
    assert restored["status"] == "APPROVED"
    assert restored.get("blocked_reason") is None

    set_clock("2026-09-01T05:00:00Z")
    refused = api_client.deliver_communication(message["id"], DIRECTOR)
    validate_error(refused, ApiErrorId.ERR_PEERLESS_PLYWOOD_WINDOW)
    assert read_campaign_message(message["id"])["status"] == "APPROVED"


# --------------------------------------------------------------------------
# The cure window is inclusive at its closing instant.
# --------------------------------------------------------------------------
ATTESTATION = {"attested_by_title": "Director of Labor Relations"}


def _list_returned_for_cure():
    """A six-entry list, one entry missing its phone, returned for a 24-hour cure."""
    case = _election_set_case()
    voter_list = create_voter_list(case["petition"]["id"], case["agreement"]["id"])
    add_complete_entries(voter_list["id"], case["classifications"][0]["id"], 5)
    add_incomplete_entries(
        voter_list["id"],
        case["classifications"][0]["id"],
        1,
        missing_fields=("personal_phone",),
    )
    set_clock("2026-08-21T10:00:00Z")
    submitted = submit_voter_list(voter_list["id"])
    assert float(submitted["completeness_pct"]) == 83.33
    assert submitted["list_grade"] == "MATERIAL_DEFECT"
    set_clock("2026-08-21T18:00:00Z")
    reviewed = review_voter_list(
        voter_list["id"], "RETURN_FOR_CURE", noted_defects=["MISSING_PHONE"]
    )
    return case, voter_list, reviewed


def test_a_cure_resubmission_at_the_deadline_instant_is_still_timely():
    """A list resubmitted at the very instant its cure deadline falls is accepted and
    re-graded as though it had come in early.

    PRD: "Wherever a deadline is compared against the logical clock, an instant exactly equal to the deadline is still inside the window — the comparisons are inclusive at the deadline."

    Design: Corner/validations/cure_resubmission_at_the_deadline_instant_is_timely
    """
    _, voter_list, reviewed = _list_returned_for_cure()
    assert reviewed["status"] == "DEFICIENT"
    assert_instant_equals(
        reviewed["cure_deadline_at"], "2026-08-22T18:00:00Z", "cure_deadline_at"
    )

    set_clock("2026-08-22T18:00:00Z")
    resp = api_client.resubmit_voter_list(voter_list["id"], dict(ATTESTATION), DIRECTOR)
    resubmitted = validate_success(resp)

    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["resubmission_count"] == 1
    assert_instant_equals(
        resubmitted["submitted_at"], "2026-08-22T18:00:00Z", "submitted_at"
    )
    assert float(resubmitted["completeness_pct"]) == 83.33
    assert resubmitted["is_late"] is False
    assert resubmitted["list_grade"] == "MATERIAL_DEFECT"
    assert_instant_equals(resubmitted["due_at"], LIST_DUE_AT, "due_at")


def test_a_cure_resubmission_one_second_late_reports_the_expired_window():
    """A second cure cycle missed by one second is refused for the window rather than
    for the resubmission ceiling, which still has a cycle left.

    PRD: "Resubmission is only possible from `DEFICIENT`, only while the logical clock is at or before `cure_deadline_at` — later is `ERR_CURE_WINDOW_EXPIRED` — and only while `resubmission_count` is still below its ceiling of 2, since a third cure attempt is refused with `ERR_RESUBMISSION_LIMIT_EXCEEDED`."

    Design: Corner/validations/cure_resubmission_at_the_deadline_instant_is_timely
    """
    _, voter_list, _ = _list_returned_for_cure()
    set_clock("2026-08-22T18:00:00Z")
    validate_success(
        api_client.resubmit_voter_list(voter_list["id"], dict(ATTESTATION), DIRECTOR)
    )

    set_clock("2026-08-22T19:00:00Z")
    second_review = review_voter_list(
        voter_list["id"], "RETURN_FOR_CURE", noted_defects=["MISSING_PHONE"]
    )
    assert_instant_equals(
        second_review["cure_deadline_at"], "2026-08-23T19:00:00Z", "cure_deadline_at"
    )
    assert second_review["cure_window_hours"] == 24

    set_clock("2026-08-23T19:00:01Z")
    refused = api_client.resubmit_voter_list(
        voter_list["id"], dict(ATTESTATION), DIRECTOR
    )
    validate_error(refused, ApiErrorId.ERR_CURE_WINDOW_EXPIRED)

    unchanged = read_voter_list(voter_list["id"])
    assert unchanged["status"] == "DEFICIENT"
    assert unchanged["resubmission_count"] == 1


# --------------------------------------------------------------------------
# The late-filing acknowledgement trades a refusal for a worse grade.
# --------------------------------------------------------------------------
def _complete_list_past_its_deadline():
    """Six flawless entries on a list whose deadline the clock has already passed."""
    case = _election_set_case()
    voter_list = create_voter_list(case["petition"]["id"], case["agreement"]["id"])
    add_complete_entries(voter_list["id"], case["classifications"][0]["id"], 6)
    drafted = read_voter_list(voter_list["id"])
    assert_instant_equals(drafted["due_at"], LIST_DUE_AT, "due_at")
    set_clock("2026-08-25T09:00:00Z")
    return case, voter_list


def test_a_list_filed_after_the_deadline_without_the_acknowledgement_is_refused():
    """Filing past the deadline with no acknowledgement leaves the list untouched in
    draft rather than grading it late.

    PRD: "Unless the request carries `late_submission_ack` set to true, the logical clock must be at or before `due_at`; a submission past the deadline without that acknowledgement is refused with `ERR_VOTER_LIST_PAST_DUE`."

    Design: Corner/validations/late_submission_ack_converts_a_hard_error_into_a_graded_downgrade
    """
    _, voter_list = _complete_list_past_its_deadline()

    refused = api_client.submit_voter_list(
        voter_list["id"], dict(ATTESTATION), DIRECTOR
    )
    validate_error(refused, ApiErrorId.ERR_VOTER_LIST_PAST_DUE)

    untouched = read_voter_list(voter_list["id"])
    assert untouched["status"] == "DRAFT"
    assert untouched.get("submitted_at") is None
    assert untouched.get("list_grade") is None
    assert untouched["is_late"] is False


def test_an_acknowledged_late_filing_is_graded_one_tier_worse():
    """The acknowledgement lets a flawless list in, and the lateness alone drops it from
    compliant to a minor defect with a forty-eight-hour cure.

    PRD: "A late list is then graded **one tier worse** than its base tier, where the tiers run in the order `COMPLIANT`, `MINOR_DEFECT`, `MATERIAL_DEFECT`, `GROSSLY_DEFICIENT`, and the outcome is stored in `list_grade`."

    Design: Corner/validations/late_submission_ack_converts_a_hard_error_into_a_graded_downgrade
    """
    _, voter_list = _complete_list_past_its_deadline()

    payload = dict(ATTESTATION)
    payload["late_submission_ack"] = True
    accepted = validate_success(
        api_client.submit_voter_list(voter_list["id"], payload, DIRECTOR)
    )

    assert accepted["status"] == "SUBMITTED"
    assert_instant_equals(
        accepted["submitted_at"], "2026-08-25T09:00:00Z", "submitted_at"
    )
    assert accepted["total_entry_count"] == 6
    assert accepted["complete_entry_count"] == 6
    assert float(accepted["completeness_pct"]) == 100.00
    assert accepted["is_late"] is True
    assert accepted["list_grade"] == "MINOR_DEFECT"

    cured = review_voter_list(
        voter_list["id"], "RETURN_FOR_CURE", noted_defects=["LATE_FILING"]
    )
    assert cured["status"] == "DEFICIENT"
    assert cured["cure_window_hours"] == 48
    assert_instant_equals(
        cured["cure_deadline_at"], "2026-08-27T09:00:00Z", "cure_deadline_at"
    )


# --------------------------------------------------------------------------
# Observer seats are metered per party per session.
# --------------------------------------------------------------------------
def _case_with_two_sessions():
    """An election-set case whose round already carries two scheduled sessions."""
    case = _election_set_case()
    case["sessions"] = _two_sessions(case["round"]["id"])
    return case


def test_a_fourth_observer_for_the_same_party_exhausts_the_seat_cap():
    """Three employer observers fill the employer's seats, and the fourth designation is
    turned away even though the session still has room for the union.

    PRD: "And each party is capped at three observers per session, counted separately for the employer and the union, so a fourth designation for the same party is refused with `ERR_OBSERVER_CAPACITY_EXCEEDED`."

    Design: Corner/validations/observer_capacity_is_metered_per_party_not_per_session
    """
    case = _case_with_two_sessions()
    session = case["sessions"][0]
    for index in range(3):
        designate_observer(
            session["id"],
            headers=DIRECTOR,
            party="EMPLOYER",
            observer_name=f"Obs Employer {index + 1}",
        )
    designate_observer(
        session["id"], headers=UNION, party="UNION", observer_name="Obs Union One"
    )

    refused = api_client.designate_observer(
        session["id"],
        {"party": "EMPLOYER", "observer_name": "Obs Employer Four"},
        DIRECTOR,
    )
    validate_error(refused, ApiErrorId.ERR_OBSERVER_CAPACITY_EXCEEDED)

    unchanged = read_poll_session(session["id"])
    assert unchanged["employer_observer_count"] == 3
    assert unchanged["union_observer_count"] == 1
    assert len(unchanged["observer_roster"]) == 4


def test_the_union_may_still_be_seated_while_the_employer_cap_is_exhausted():
    """With the employer's three seats taken, the union's second seat is unaffected and
    the sibling session keeps an empty roster.

    PRD: "A successful designation increments either `employer_observer_count` or `union_observer_count` according to the party, and appends an entry to `observer_roster` recording the party, the observer name and the supervisor identifier, in designation order."

    Design: Corner/validations/observer_capacity_is_metered_per_party_not_per_session
    """
    case = _case_with_two_sessions()
    session, sibling = case["sessions"]
    for index in range(3):
        designate_observer(
            session["id"],
            headers=DIRECTOR,
            party="EMPLOYER",
            observer_name=f"Obs Employer {index + 1}",
        )
    designate_observer(
        session["id"], headers=UNION, party="UNION", observer_name="Obs Union One"
    )
    validate_error(
        api_client.designate_observer(
            session["id"],
            {"party": "EMPLOYER", "observer_name": "Obs Employer Four"},
            DIRECTOR,
        ),
        ApiErrorId.ERR_OBSERVER_CAPACITY_EXCEEDED,
    )

    seated = validate_success(
        api_client.designate_observer(
            session["id"],
            {"party": "UNION", "observer_name": "Obs Union Two"},
            UNION,
        )
    )
    assert seated["employer_observer_count"] == 3
    assert seated["union_observer_count"] == 2
    assert len(seated["observer_roster"]) == 5

    validate_error(
        api_client.designate_observer(
            session["id"],
            {"party": "EMPLOYER", "observer_name": "Obs Employer One"},
            DIRECTOR,
        ),
        ApiErrorId.ERR_OBSERVER_CAPACITY_EXCEEDED,
    )

    untouched = read_poll_session(sibling["id"])
    assert untouched["employer_observer_count"] == 0
    assert untouched["union_observer_count"] == 0
    assert untouched["observer_roster"] == []


# --------------------------------------------------------------------------
# A statutory supervisor may not observe for anybody.
# --------------------------------------------------------------------------
def test_a_statutory_supervisor_may_not_be_seated_for_the_employer():
    """Naming a supervisor who holds hire-and-fire authority is refused, and the same
    designation succeeds once no supervisor is named.

    PRD: "A supervisor holding Section 2(11) hire-and-fire authority may never be seated: naming such a supervisor is refused with `ERR_SUPERVISOR_OBSERVER_PROHIBITED` (HTTP 422)."

    Design: Corner/validations/a_statutory_supervisor_is_barred_from_observing_for_either_party
    """
    case = _case_with_two_sessions()
    session = case["sessions"][0]
    supervisor = register_supervisor(
        case["petition"]["id"],
        full_name="Marta Kowalski",
        job_title="Shift Superintendent",
        has_hire_fire_authority=True,
    )
    assert supervisor["has_hire_fire_authority"] is True

    refused = api_client.designate_observer(
        session["id"],
        {
            "party": "EMPLOYER",
            "observer_name": "Marta Kowalski",
            "supervisor_id": supervisor["id"],
        },
        DIRECTOR,
    )
    validate_error(refused, ApiErrorId.ERR_SUPERVISOR_OBSERVER_PROHIBITED)

    empty = read_poll_session(session["id"])
    assert empty["employer_observer_count"] == 0
    assert empty["union_observer_count"] == 0
    assert empty["observer_roster"] == []

    seated = validate_success(
        api_client.designate_observer(
            session["id"],
            {"party": "EMPLOYER", "observer_name": "Rita Chen, HR Generalist"},
            DIRECTOR,
        )
    )
    assert seated["employer_observer_count"] == 1
    assert len(seated["observer_roster"]) == 1


def test_a_statutory_supervisor_may_not_be_seated_for_the_union_either():
    """The bar reads the supervisor's authority rather than the party being served, so a
    union-side designation of the same supervisor is refused too.

    PRD: "A supervisor holding Section 2(11) hire-and-fire authority may never be seated: naming such a supervisor is refused with `ERR_SUPERVISOR_OBSERVER_PROHIBITED` (HTTP 422)."

    Design: Corner/validations/a_statutory_supervisor_is_barred_from_observing_for_either_party
    """
    case = _case_with_two_sessions()
    session = case["sessions"][0]
    supervisor = register_supervisor(
        case["petition"]["id"],
        full_name="Marta Kowalski",
        job_title="Shift Superintendent",
        has_hire_fire_authority=True,
    )

    refused = api_client.designate_observer(
        session["id"],
        {
            "party": "UNION",
            "observer_name": "Marta Kowalski",
            "supervisor_id": supervisor["id"],
        },
        UNION,
    )
    validate_error(refused, ApiErrorId.ERR_SUPERVISOR_OBSERVER_PROHIBITED)

    empty = read_poll_session(session["id"])
    assert empty["union_observer_count"] == 0
    assert empty["observer_roster"] == []


# --------------------------------------------------------------------------
# Ninety is the prohibition boundary, not the escalation boundary.
# --------------------------------------------------------------------------
def _scored_captive_audience_message(**content):
    """A captive-audience draft, accuracy-reviewed so its risk score is written."""
    case = _election_set_case()
    _, message = _captive_audience_draft(
        case["petition"]["id"],
        "2026-08-26T13:00:00Z",
        audience_scope="CLASSIFICATION",
        **content,
    )
    scored = accuracy_review(
        message["id"], material_claim_count=2, unsupported_material_claim_count=1
    )
    return case, message, scored


def test_a_risk_score_of_exactly_ninety_may_not_enter_legal_review():
    """A captive-audience meeting scoring exactly ninety is prohibited outright, so the
    draft never reaches counsel at all.

    PRD: "A `risk_score` of 90 or more is **prohibited**: the message may not even enter legal review, and the attempt is refused with `ERR_RISK_SCORE_PROHIBITED` (HTTP 422)."

    Design: Corner/validations/a_risk_score_of_exactly_ninety_may_not_even_be_submitted
    """
    _, message, scored = _scored_captive_audience_message(
        threat_statement_count=2,
        contains_interrogation=True,
        contains_promise_of_benefit=True,
        contains_surveillance_reference=True,
    )
    assert scored["risk_score"] == 90
    assert scored["peerless_plywood_violation"] is False
    assert_instant_equals(
        scored["accuracy_reviewed_at"], APPROVAL_CLOCK, "accuracy_reviewed_at"
    )

    refused = api_client.submit_communication_for_review(message["id"], DIRECTOR)
    validate_error(refused, ApiErrorId.ERR_RISK_SCORE_PROHIBITED)

    held = read_campaign_message(message["id"])
    assert held["status"] == "DRAFT"
    assert held["revision_round"] == 0
    assert held.get("reviewed_by_user_id") is None


def test_an_elevated_score_below_ninety_still_enters_legal_review():
    """The same meeting without the surveillance reference scores eighty-two, which is
    elevated but not prohibited, so it reaches counsel.

    PRD: "A `risk_score` of 70 or more is **elevated**: the message may enter review, but counsel may only approve it when the approving request carries `escalation_ack` set to true, and approval without it is refused with `ERR_ESCALATION_ACK_REQUIRED` (HTTP 422)."

    Design: Corner/validations/a_risk_score_of_exactly_ninety_may_not_even_be_submitted
    """
    _, message, scored = _scored_captive_audience_message(
        threat_statement_count=2,
        contains_interrogation=True,
        contains_promise_of_benefit=True,
    )
    assert scored["risk_score"] == 82

    accepted = validate_success(
        api_client.submit_communication_for_review(message["id"], DIRECTOR)
    )
    assert accepted["status"] == "PENDING_LEGAL_REVIEW"
    assert accepted["risk_score"] == 82


# --------------------------------------------------------------------------
# The posture gate answers before the impounded-ballot guard.
# --------------------------------------------------------------------------
def test_posting_a_tally_on_impounded_ballots_reports_the_posture_gate():
    """A blocking charge filed once the ballots are in the box impounds them, and the
    tally posting is refused for the posture rather than for the impoundment.

    PRD: "The posture is written only by unfair labor practice charge activity, and its purpose is to act as a gate: while the posture is anything other than `OPEN`, every write that would advance the election is refused with `ERR_CASE_POSTURE_BLOCKED` (HTTP 409)."
    PRD: "Checks run in the following fixed order, and the first failing check determines both the `error_id` and the HTTP status:"

    Design: Corner/validations/the_posture_gate_shadows_the_impounded_ballot_guard
    """
    case = _polls_closed_case()
    docket_charge(
        case["petition"]["id"],
        blocking_requested=True,
        section_code="8A1",
        conduct_occurred_at="2026-09-01T09:30:00Z",
    )

    impounded = read_round(case["round"]["id"])
    assert impounded["status"] == "POLLS_CLOSED"
    assert impounded["ballots_impounded"] is True
    assert impounded["ballots_cast_total"] == 85
    assert read_petition(case["petition"]["id"])["case_posture"] == "IMPOUNDED"

    refused = api_client.post_tally(case["round"]["id"], BOARD)
    validate_error(refused, ApiErrorId.ERR_CASE_POSTURE_BLOCKED)

    still_closed = read_round(case["round"]["id"])
    assert still_closed["status"] == "POLLS_CLOSED"
    assert still_closed.get("tally_posted_at") is None
    assert read_petition(case["petition"]["id"])["case_status"] == "VOTING_CLOSED"


def test_the_tally_posts_once_the_impounding_charge_is_settled():
    """Settling the blocking charge lifts the impoundment, and the identical posting then
    computes the provisional figures and opens the objection window.

    PRD: "When the posture had been `IMPOUNDED`, the impounded round's `ballots_impounded` flag returns to false."
    PRD: "`tally_posted_at` is stamped, the case's `case_status` becomes `TALLY_POSTED`, and the objection window opens, with `objection_window_close_at` set to the end of the seventh business day after the tally date."

    Design: Corner/validations/the_posture_gate_shadows_the_impounded_ballot_guard
    """
    case = _polls_closed_case()
    charge = docket_charge(
        case["petition"]["id"],
        blocking_requested=True,
        section_code="8A1",
        conduct_occurred_at="2026-09-01T09:30:00Z",
    )
    validate_error(
        api_client.post_tally(case["round"]["id"], BOARD),
        ApiErrorId.ERR_CASE_POSTURE_BLOCKED,
    )

    settled = settle_charge(charge["id"], "NON_BOARD")
    assert settled["status"] == "SETTLED"
    assert_instant_equals(settled["settled_at"], "2026-09-01T17:30:00Z", "settled_at")

    released = read_petition(case["petition"]["id"])
    assert released["case_posture"] == "OPEN"
    assert released["blocking_charge_count"] == 0
    assert released.get("notice_posting_end_at") is None
    assert read_round(case["round"]["id"])["ballots_impounded"] is False

    set_clock("2026-09-02T12:00:00Z")
    posted = validate_success(api_client.post_tally(case["round"]["id"], BOARD))
    assert posted["provisional_votes_for"] == 42
    assert posted["provisional_votes_against"] == 39
    assert posted["provisional_void_count"] == 1
    assert posted["provisional_margin"] == 3
    assert posted["valid_votes_cast"] == 81
    assert float(posted["majority_threshold"]) == 41
    assert posted["determinative_challenges"] is True
    assert_instant_equals(
        posted["objection_window_close_at"],
        "2026-09-14T23:59:59Z",
        "objection_window_close_at",
    )
    assert read_petition(case["petition"]["id"])["case_status"] == "TALLY_POSTED"


# --------------------------------------------------------------------------
# Certification refuses for the window first and for the case status next.
# --------------------------------------------------------------------------
def test_certifying_inside_the_objection_window_reports_the_open_window():
    """With every other condition satisfied, certifying before the objection window has
    closed is refused for the window alone.

    PRD: "The case must be in `TALLY_POSTED`, its `case_posture` must be `OPEN`, the named round's `status` must be `TALLY_REVISED` — a round that has not been revised is refused with `ERR_ROUND_NOT_REVISED` — the logical clock must be **strictly after** that round's `objection_window_close_at`, since certifying at or before the window's close is refused with `ERR_OBJECTION_WINDOW_OPEN`, `pending_objection_count` must be 0 or the attempt is refused with `ERR_PENDING_OBJECTIONS`, `blocking_charge_count` must be 0 or it is refused with `ERR_BLOCKING_CHARGE_PENDING`, and `notice_posting_end_at` must be either absent or at or before the logical clock, since a still-running settlement notice period is refused with `ERR_NOTICE_POSTING_ACTIVE`."

    Design: Corner/validations/certification_gates_report_the_window_error_then_the_status_error
    """
    case = _revised_tally_case()
    assert case["petition"]["case_status"] == "TALLY_POSTED"
    assert case["petition"]["case_posture"] == "OPEN"
    assert case["petition"]["pending_objection_count"] == 0
    assert case["petition"]["blocking_charge_count"] == 0
    assert case["petition"].get("notice_posting_end_at") is None
    assert case["round"]["status"] == "TALLY_REVISED"
    assert_instant_equals(
        case["round"]["objection_window_close_at"],
        "2026-09-14T23:59:59Z",
        "objection_window_close_at",
    )

    refused = api_client.certify_petition(
        case["petition"]["id"], {"election_round_id": case["round"]["id"]}, BOARD
    )
    validate_error(refused, ApiErrorId.ERR_OBJECTION_WINDOW_OPEN)

    uncertified = read_petition(case["petition"]["id"])
    assert uncertified["case_status"] == "TALLY_POSTED"
    assert uncertified.get("certified_at") is None
    assert uncertified.get("certified_round_id") is None


def test_certifying_a_case_with_objections_pending_reports_the_case_status():
    """Once an objection has moved the case out of the posted-tally state, the certify
    call is answered by the case-status check rather than by the objection count.

    PRD: "**Own-state precondition** — the target row is in a state from which the requested transition is declared, else the state code for that resource type: `ERR_PETITION_STATUS_INVALID`, `ERR_CLASSIFICATION_ALREADY_RULED`, `ERR_AGREEMENT_STATUS_INVALID`, `ERR_VOTER_LIST_STATUS_INVALID`, `ERR_COMMUNICATION_STATUS_INVALID`, `ERR_ROUND_NOT_SCHEDULED`, `ERR_ROUND_STATUS_INVALID`, `ERR_POLL_SESSION_STATUS_INVALID`, `ERR_BALLOT_STATUS_INVALID`, `ERR_OBJECTION_ALREADY_RULED` or `ERR_CHARGE_STATUS_INVALID`, each HTTP 409. Applies to every action endpoint."
    PRD: "Filing raises the case's `pending_objection_count` by 1, and the first objection accepted against the current round moves `case_status` from `TALLY_POSTED` to `OBJECTIONS_PENDING`."

    Design: Corner/validations/certification_gates_report_the_window_error_then_the_status_error
    """
    case = _revised_tally_case()
    filed = validate_success(
        api_client.create_objection(
            {
                "election_round_id": case["round"]["id"],
                "filed_by_party": "UNION",
                "ground_code": "POLLING_IRREGULARITY",
                "conduct_occurred_at": "2026-09-01T09:30:00Z",
                "alleged_affected_voter_count": 6,
                "description": "Ballot box left unattended for twenty minutes at the cafeteria table",
            },
            UNION,
        ),
        201,
    )
    assert filed["status"] == "FILED"
    assert filed["affects_results"] is True

    set_clock("2026-09-15T09:00:00Z")
    refused = api_client.certify_petition(
        case["petition"]["id"], {"election_round_id": case["round"]["id"]}, BOARD
    )
    validate_error(refused, ApiErrorId.ERR_PETITION_STATUS_INVALID)

    uncertified = read_petition(case["petition"]["id"])
    assert uncertified["case_status"] == "OBJECTIONS_PENDING"
    assert uncertified["pending_objection_count"] == 1
    assert uncertified.get("certified_at") is None
    assert uncertified.get("certified_round_id") is None


# --------------------------------------------------------------------------
# A running notice-posting period defers certification to its last instant.
# --------------------------------------------------------------------------
def _case_with_a_running_notice_period():
    """A merit finding then a formal settlement, each carrying a thirty-day posting."""
    case = _revised_tally_case()
    set_clock("2026-09-03T09:00:00Z")
    charge = docket_charge(
        case["petition"]["id"],
        blocking_requested=True,
        section_code="8A1",
        conduct_occurred_at="2026-08-30T09:00:00Z",
    )
    set_clock("2026-09-03T10:00:00Z")
    determine_charge(
        charge["id"], "MERIT", remedy_code="NOTICE_POSTING", notice_posting_days=30
    )
    after_merit = read_petition(case["petition"]["id"])
    set_clock("2026-09-04T09:00:00Z")
    settled = settle_charge(charge["id"], "FORMAL", notice_posting_days=30)
    return case, after_merit, settled


def test_certification_is_refused_while_the_settlement_notice_period_runs():
    """The settlement rewrites the posting date rather than extending it, and while that
    date is in the future certification is refused even though nothing else is pending.

    PRD: "Settlement stamps `settled_at`, moves the charge to the terminal `SETTLED` state, lowers `blocking_charge_count` by 1 when the charge was a blocking one, and, when `notice_posting_days` is greater than 0, sets the case's `notice_posting_end_at` to `settled_at` plus that many days."

    Design: Corner/validations/a_running_notice_posting_period_defers_certification_until_its_last_instant
    """
    case, after_merit, settled = _case_with_a_running_notice_period()

    assert_instant_equals(
        after_merit["notice_posting_end_at"],
        "2026-10-03T10:00:00Z",
        "notice_posting_end_at after the merit finding",
    )
    assert after_merit["blocking_charge_count"] == 1

    assert settled["status"] == "SETTLED"
    assert_instant_equals(settled["settled_at"], "2026-09-04T09:00:00Z", "settled_at")

    released = read_petition(case["petition"]["id"])
    assert released["blocking_charge_count"] == 0
    assert released["case_posture"] == "OPEN"
    assert released["case_status"] == "TALLY_POSTED"
    assert_instant_equals(
        released["notice_posting_end_at"],
        "2026-10-04T09:00:00Z",
        "notice_posting_end_at after the settlement",
    )

    set_clock("2026-09-15T09:00:00Z")
    refused = api_client.certify_petition(
        case["petition"]["id"], {"election_round_id": case["round"]["id"]}, BOARD
    )
    validate_error(refused, ApiErrorId.ERR_NOTICE_POSTING_ACTIVE)
    assert read_petition(case["petition"]["id"]).get("certified_at") is None


def test_certification_issues_at_the_last_instant_of_the_notice_period():
    """At exactly the posting end instant the notice condition is satisfied, and the
    certification of representative issues on the revised tally.

    PRD: "When the union prevailed, `certification_outcome` becomes `CERTIFICATION_OF_REPRESENTATIVE`; `bargaining_obligation_start_at` equals `certified_at`, because the duty to bargain begins immediately; `certification_year_end_at` is `certified_at` plus 365 days, the insulated certification year; `decert_window_open_at` equals `certification_year_end_at`, since a decertification petition may only be filed once that year closes; and `election_bar_end_at` and `bargaining_obligation_end_at` are both left absent."

    Design: Corner/validations/a_running_notice_posting_period_defers_certification_until_its_last_instant
    """
    case, _, _ = _case_with_a_running_notice_period()
    revised = read_round(case["round"]["id"])
    assert revised["revised_votes_for"] == 44
    assert float(revised["majority_threshold"]) == 42

    set_clock("2026-10-04T09:00:00Z")
    certified = validate_success(
        api_client.certify_petition(
            case["petition"]["id"], {"election_round_id": case["round"]["id"]}, BOARD
        )
    )

    assert certified["case_status"] == "CERTIFIED"
    assert certified["certification_outcome"] == "CERTIFICATION_OF_REPRESENTATIVE"
    assert certified["certified_round_id"] == case["round"]["id"]
    assert_instant_equals(
        certified["certified_at"], "2026-10-04T09:00:00Z", "certified_at"
    )
    assert_instant_equals(
        certified["bargaining_obligation_start_at"],
        "2026-10-04T09:00:00Z",
        "bargaining_obligation_start_at",
    )
    assert_instant_equals(
        certified["certification_year_end_at"],
        "2027-10-04T09:00:00Z",
        "certification_year_end_at",
    )
    assert_instant_equals(
        certified["decert_window_open_at"],
        "2027-10-04T09:00:00Z",
        "decert_window_open_at",
    )
    assert certified.get("election_bar_end_at") is None
    assert certified.get("bargaining_obligation_end_at") is None
    assert read_round(case["round"]["id"])["status"] == "ROUND_CERTIFIED"


# --------------------------------------------------------------------------
# The objection window is inclusive at its closing instant.
# --------------------------------------------------------------------------
PICKET_OBJECTION = {
    "filed_by_party": "EMPLOYER",
    "ground_code": "THIRD_PARTY_CONDUCT",
    "conduct_occurred_at": "2026-09-01T08:00:00Z",
    "alleged_affected_voter_count": 2,
    "description": "Community picket outside the plant gate during polling hours",
}


def test_an_objection_one_second_past_the_window_is_refused():
    """A second after the window closes the filing is turned away and the case keeps its
    posted-tally status with nothing pending.

    PRD: "Filing is only possible while the objected round is `TALLY_POSTED` or `TALLY_REVISED` and while the logical clock is at or before that round's `objection_window_close_at`; a late filing is refused with `ERR_OBJECTION_WINDOW_CLOSED`."

    Design: Corner/validations/an_objection_filed_at_the_closing_instant_is_timely
    """
    case = _revised_tally_case()
    assert_instant_equals(
        case["round"]["objection_window_close_at"],
        "2026-09-14T23:59:59Z",
        "objection_window_close_at",
    )

    set_clock("2026-09-15T00:00:00Z")
    payload = dict(PICKET_OBJECTION)
    payload["election_round_id"] = case["round"]["id"]
    refused = api_client.create_objection(payload, DIRECTOR)
    validate_error(refused, ApiErrorId.ERR_OBJECTION_WINDOW_CLOSED)

    untouched = read_petition(case["petition"]["id"])
    assert untouched["case_status"] == "TALLY_POSTED"
    assert untouched["pending_objection_count"] == 0


def test_an_objection_filed_at_the_closing_instant_is_timely():
    """Filed at the closing instant itself the objection is docketed, and because it
    alleges fewer voters than the provisional margin it does not affect the results.

    PRD: "A new objection starts at `status` `FILED` with `rerun_directed` false and no `ruled_at` or `disposition_rationale`, and the system immediately computes `affects_results`: it is true exactly when `alleged_affected_voter_count` is greater than or equal to the absolute value of the objected round's `provisional_margin`."

    Design: Corner/validations/an_objection_filed_at_the_closing_instant_is_timely
    """
    case = _revised_tally_case()
    assert case["round"]["provisional_margin"] == 3

    set_clock("2026-09-14T23:59:59Z")
    payload = dict(PICKET_OBJECTION)
    payload["election_round_id"] = case["round"]["id"]
    filed = validate_success(api_client.create_objection(payload, DIRECTOR), 201)

    assert filed["status"] == "FILED"
    assert filed["affects_results"] is False
    assert filed["rerun_directed"] is False
    assert filed.get("ruled_at") is None
    assert_instant_equals(filed["filed_at"], "2026-09-14T23:59:59Z", "filed_at")

    pending = read_petition(case["petition"]["id"])
    assert pending["case_status"] == "OBJECTIONS_PENDING"
    assert pending["pending_objection_count"] == 1
