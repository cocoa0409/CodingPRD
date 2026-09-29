"""Rejection ordering when two checks fail at once, and the exact-equality edges of the
case's percentages, scores and statutory deadlines.

The first half exercises requests that violate two rules simultaneously, where the
contract names which failure is reported. The second half pins the showing-of-interest
threshold, the community-of-interest rounding order, the campaign risk escalation gate
and the voter-list completeness and deadline edges to the value at the boundary and the
value one unit away from it.
"""
import pytest

from test_helpers import (
    ANALYST,
    BOARD,
    COUNSEL,
    DIRECTOR,
    ApiErrorId,
    accuracy_review,
    add_classification,
    api_client,
    assert_absent,
    assert_instant_equals,
    create_approved_message,
    create_campaign_message,
    create_election_agreement,
    create_petition_in_scope_analysis,
    create_poll_session,
    create_poll_session_payload,
    create_trained_supervisor,
    designate_observer,
    designate_observer_payload,
    docket_blocking_charge,
    get_success_data,
    latest_round,
    read_campaign_message,
    read_petition,
    read_poll_session,
    read_round,
    register_supervisor,
    review_communication_payload,
    review_voter_list,
    round_version,
    rule_classification,
    score_and_rule,
    score_classification,
    set_clock,
    setup_draft_voter_list,
    setup_scope_analysis,
    setup_soi_verified,
    stipulate_agreement,
    submit_message_for_review,
    submit_voter_list,
    validate_error,
    validate_success,
    verify_showing_payload,
)

# Two INCLUDE classifications totalling 90 heads, so a fully ruled case has an
# included headcount of 90.
PRODUCTION_AND_MAINTENANCE = [
    {
        "code": "PROD", "title": "Production Operator", "headcount": 60,
        "avg_hourly_wage_cents": 2400, "shift_code": "A", "work_location": "PLANT_1",
        "supervisory_authority_count": 0, "employer_position": "INCLUDE",
        "union_position": "INCLUDE", "supervision_overlap": 88, "skills_overlap": 90,
        "functional_integration": 92, "interchange_rate": 74, "work_conditions_overlap": 95,
    },
    {
        "code": "MAINT", "title": "Maintenance Mechanic", "headcount": 30,
        "avg_hourly_wage_cents": 3200, "shift_code": "A", "work_location": "PLANT_1",
        "supervisory_authority_count": 0, "employer_position": "INCLUDE",
        "union_position": "INCLUDE", "supervision_overlap": 82, "skills_overlap": 78,
        "functional_integration": 86, "interchange_rate": 61, "work_conditions_overlap": 84,
    },
]

# 40 submitted less 3 duplicate, 2 undated, 2 stale and 3 non-unit leaves 30 valid cards.
SUFFICIENT_CARDS = {
    "submitted_card_count": 40, "duplicate_card_count": 3, "undated_card_count": 2,
    "stale_card_count": 2, "nonunit_card_count": 3,
}


def _case_with_two_approved_messages_after_polls_closed():
    """One approved captive-audience meeting inside the pre-poll blackout and one
    approved e-mail, on a case whose polls have already closed.

    Both messages clear legal review before any election round exists, so nothing in
    the review pipeline objects to the meeting at the time it is approved.
    """
    ctx = setup_soi_verified(
        clock="2026-08-10T09:00:00Z",
        classification_specs=PRODUCTION_AND_MAINTENANCE,
        card_counts=SUFFICIENT_CARDS,
    )
    petition_id = ctx["petition"]["id"]
    presenter = create_trained_supervisor(
        petition_id,
        full_name="Marta Kowalski",
        job_title="Shift Supervisor",
        span_of_control=18,
        has_hire_fire_authority=True,
    )
    captive = create_approved_message(
        petition_id,
        message_overrides={
            "channel": "CAPTIVE_AUDIENCE_MEETING",
            "audience_scope": "UNIT_WIDE",
            "planned_delivery_at": "2026-09-01T05:00:00Z",
            "duration_minutes": 45,
            "presenter_supervisor_id": presenter["id"],
            "message_summary": "All-hands meeting on the employer position ahead of the vote.",
        },
        accuracy_overrides={"material_claim_count": 3, "unsupported_material_claim_count": 0},
    )
    email = create_approved_message(
        petition_id,
        message_overrides={
            "channel": "EMAIL",
            "audience_scope": "UNIT_WIDE",
            "planned_delivery_at": "2026-08-26T13:00:00Z",
            "message_summary": "Written summary of the employer position for the whole unit.",
        },
        accuracy_overrides={"material_claim_count": 3, "unsupported_material_claim_count": 0},
    )
    agreement = create_election_agreement(petition_id)
    set_clock("2026-08-20T15:00:00Z")
    stipulate_agreement(
        agreement["id"],
        polls_open_at="2026-09-01T06:00:00Z",
        polls_close_at="2026-09-01T17:00:00Z",
    )
    set_clock("2026-09-01T18:00:00Z")
    return petition_id, captive, email


def test_captive_audience_delivery_in_the_blackout_reports_the_per_se_violation_not_the_closed_period():
    """A captive-audience meeting planned inside the pre-poll blackout is turned away for
    the statutory violation even though the campaign period has also closed.

    PRD: "A captive-audience message whose planned delivery sits inside the blackout, submitted for delivery after the polls have already closed, reports `ERR_PEERLESS_PLYWOOD_WINDOW` (422) rather than `ERR_CAMPAIGN_PERIOD_CLOSED` (409): a per-se statutory violation outranks a scheduling-window failure."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_delivery
    """
    _petition_id, captive, _email = _case_with_two_approved_messages_after_polls_closed()

    resp = api_client.deliver_communication(captive["id"], DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_PEERLESS_PLYWOOD_WINDOW)

    unchanged = read_campaign_message(captive["id"])
    assert unchanged["status"] == "APPROVED", (
        f"a refused delivery must leave the message approved, got {unchanged['status']}"
    )
    assert_absent(unchanged, "delivered_at", "captive-audience message")


def test_delivery_after_the_polls_close_reports_the_closed_campaign_period_on_its_own():
    """An e-mail with no per-se defect, delivered on the same closed case, surfaces the
    scheduling-window failure that the captive-audience meeting outranked.

    PRD: "A delivery attempted after the polls have closed, or against a round that has moved past `POLLS_OPEN`, is refused with `ERR_CAMPAIGN_PERIOD_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_delivery
    """
    _petition_id, _captive, email = _case_with_two_approved_messages_after_polls_closed()

    resp = api_client.deliver_communication(email["id"], DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_PERIOD_CLOSED)

    unchanged = read_campaign_message(email["id"])
    assert unchanged["status"] == "APPROVED", (
        f"a refused delivery must leave the message approved, got {unchanged['status']}"
    )
    assert_absent(unchanged, "delivered_at", "e-mail message")


def _round_with_one_scheduled_session():
    """A SCHEDULED round holding a single cafeteria session from 06:00 to 09:00."""
    ctx = setup_soi_verified(
        classification_specs=PRODUCTION_AND_MAINTENANCE,
        card_counts=SUFFICIENT_CARDS,
    )
    petition_id = ctx["petition"]["id"]
    agreement = create_election_agreement(petition_id)
    set_clock("2026-08-20T15:00:00Z")
    stipulate_agreement(
        agreement["id"],
        polls_open_at="2026-09-01T06:00:00Z",
        polls_close_at="2026-09-01T17:00:00Z",
    )
    election_round = latest_round(petition_id)
    first_session = create_poll_session(
        election_round["id"],
        location_code="PLANT_1_CAFETERIA",
        session_start_at="2026-09-01T06:00:00Z",
        session_end_at="2026-09-01T09:00:00Z",
        method="MANUAL",
    )
    set_clock("2026-08-27T09:00:00Z")
    return petition_id, read_round(election_round["id"]), first_session


def _cafeteria_session_overlapping_teardown(round_id):
    """A cafeteria session starting 15 minutes into the previous session's teardown."""
    return create_poll_session_payload(
        round_id,
        round_version(round_id),
        location_code="PLANT_1_CAFETERIA",
        session_start_at="2026-09-01T09:15:00Z",
        session_end_at="2026-09-01T12:00:00Z",
        method="MANUAL",
    )


def test_second_cafeteria_session_inside_the_teardown_window_is_a_location_conflict():
    """While the round is still scheduled, a session overlapping the half-hour teardown
    tail of an existing session at the same location is the reported failure.

    PRD: "Occupancy of a location extends 30 minutes past a session's close to allow for teardown, so two sessions at the same `location_code` on the same round may not overlap on the interval running from `session_start_at` up to but not including `session_end_at` plus 30 minutes."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_constraint_on_poll_session_create
    """
    _petition_id, election_round, _first_session = _round_with_one_scheduled_session()
    assert election_round["status"] == "SCHEDULED", (
        f"the round must still be schedulable, got {election_round['status']}"
    )

    resp = api_client.create_poll_session(
        _cafeteria_session_overlapping_teardown(election_round["id"]), BOARD
    )
    validate_error(resp, ApiErrorId.ERR_POLL_SESSION_LOCATION_CONFLICT)


def test_suspended_round_reports_the_round_state_rather_than_the_location_conflict():
    """Once a blocking charge suspends the round, the very same overlapping session body
    is turned away for the round state, because a suspended round hosts nothing at all.

    PRD: "A poll session created against a round that a blocking charge has already suspended, at a location and time window that also collide with an existing session, reports `ERR_ROUND_NOT_SCHEDULED` rather than `ERR_POLL_SESSION_LOCATION_CONFLICT` — the round cannot host any session at all, so the overlap question never arises, and note that both are HTTP 409, so the implementation must order the checks rather than infer the order from status codes."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_constraint_on_poll_session_create
    """
    petition_id, election_round, first_session = _round_with_one_scheduled_session()
    docket_blocking_charge(
        petition_id,
        section_code="8A1",
        allegation_summary="Supervisor threatened plant closure during a shift meeting.",
        conduct_occurred_at="2026-08-25T15:00:00Z",
    )
    suspended = read_round(election_round["id"])
    assert suspended["status"] == "SUSPENDED", (
        f"a blocking charge must suspend the scheduled round, got {suspended['status']}"
    )
    assert read_poll_session(first_session["id"])["status"] == "CANCELLED", (
        "the suspended round's scheduled session must be cancelled"
    )

    # The suspension bumped the round version, so the retry carries the current one and
    # the concurrency guard has nothing to object to.
    resp = api_client.create_poll_session(
        _cafeteria_session_overlapping_teardown(election_round["id"]), BOARD
    )
    validate_error(resp, ApiErrorId.ERR_ROUND_NOT_SCHEDULED)

    assert read_round(election_round["id"])["scheduled_session_count"] == 0, (
        "neither the cancelled session nor the refused layout may be counted"
    )


def _full_employer_roster_and_a_supervisor_from_another_case():
    """A session already seating three employer observers, plus a supervisor registered
    on an unrelated petition."""
    ctx = setup_soi_verified(
        classification_specs=PRODUCTION_AND_MAINTENANCE,
        card_counts=SUFFICIENT_CARDS,
    )
    petition_id = ctx["petition"]["id"]
    agreement = create_election_agreement(petition_id)
    stipulate_agreement(
        agreement["id"],
        polls_open_at="2026-09-01T06:00:00Z",
        polls_close_at="2026-09-01T17:00:00Z",
    )
    election_round = latest_round(petition_id)
    session = create_poll_session(
        election_round["id"],
        location_code="PLANT_1_CAFETERIA",
        session_start_at="2026-09-01T06:00:00Z",
        session_end_at="2026-09-01T17:00:00Z",
        method="MANUAL",
    )
    for observer_name in ("Ingrid Sollie", "Hugo Almeida", "Priya Raman"):
        designate_observer(session["id"], party="EMPLOYER", observer_name=observer_name)

    other_case = create_petition_in_scope_analysis(
        union_name="Allied Trades Council Local 44",
        filed_date="2026-08-05",
        proposed_unit_description="All warehouse employees at Depot 3",
        claimed_employee_count=40,
    )
    outsider = register_supervisor(
        other_case["id"],
        full_name="Nils Berg",
        job_title="Warehouse Lead",
        span_of_control=6,
        has_hire_fire_authority=False,
    )
    return read_poll_session(session["id"]), outsider


def test_observer_from_another_petition_is_refused_for_the_wrong_case_not_the_full_roster():
    """Naming a supervisor belonging to a different petition is turned away as a
    cross-case reference even though the employer roster is already full.

    PRD: "An observer designation naming a supervisor from a different petition for a party that already seats three observers reports `ERR_CROSS_PETITION_REFERENCE`, not `ERR_OBSERVER_CAPACITY_EXCEEDED`: someone who is not part of the case can never occupy a seat, so the seat count is never consulted."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_observer_seat
    """
    session, outsider = _full_employer_roster_and_a_supervisor_from_another_case()
    assert session["employer_observer_count"] == 3, (
        f"the employer seats must be full, got {session['employer_observer_count']}"
    )

    resp = api_client.designate_observer(
        session["id"],
        designate_observer_payload(
            party="EMPLOYER", observer_name="Nils Berg", supervisor_id=outsider["id"]
        ),
        BOARD,
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_PETITION_REFERENCE)

    unchanged = read_poll_session(session["id"])
    assert unchanged["employer_observer_count"] == 3, (
        f"a refused designation must not seat anyone, got {unchanged['employer_observer_count']}"
    )
    assert unchanged["union_observer_count"] == 0, (
        f"the union seats must stay empty, got {unchanged['union_observer_count']}"
    )
    assert len(unchanged["observer_roster"]) == 3, (
        f"the roster must still hold three entries, got {len(unchanged['observer_roster'])}"
    )
    assert "Nils Berg" not in str(unchanged["observer_roster"]), (
        "the outsider must not appear anywhere on the roster"
    )


def test_fourth_employer_observer_from_the_same_case_exhausts_the_party_seat_cap():
    """With no cross-case reference to outrank it, the fourth employer designation on the
    same session reports the seat cap.

    PRD: "And each party is capped at three observers per session, counted separately for the employer and the union, so a fourth designation for the same party is refused with `ERR_OBSERVER_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_observer_seat
    """
    session, _outsider = _full_employer_roster_and_a_supervisor_from_another_case()

    resp = api_client.designate_observer(
        session["id"],
        designate_observer_payload(party="EMPLOYER", observer_name="Nils Berg"),
        BOARD,
    )
    validate_error(resp, ApiErrorId.ERR_OBSERVER_CAPACITY_EXCEEDED)

    unchanged = read_poll_session(session["id"])
    assert unchanged["employer_observer_count"] == 3, (
        f"the seat count must not move, got {unchanged['employer_observer_count']}"
    )
    assert len(unchanged["observer_roster"]) == 3, (
        f"the roster must still hold three entries, got {len(unchanged['observer_roster'])}"
    )


def _fully_ruled_unit_of_ninety_heads():
    """A case whose scope is settled, leaving 90 heads inside the voting unit."""
    ctx = setup_scope_analysis(classification_specs=PRODUCTION_AND_MAINTENANCE)
    for classification in ctx["classifications"]:
        score_and_rule(classification["id"], "INCLUDED")
    petition = read_petition(ctx["petition"]["id"])
    assert petition["included_headcount"] == 90, (
        f"the ruled unit must hold 90 heads, got {petition['included_headcount']}"
    )
    return petition["id"]


def test_twenty_seven_valid_cards_out_of_ninety_heads_is_exactly_a_sufficient_showing():
    """Twenty-seven valid cards against a ruled unit of ninety is exactly the threshold,
    and the inclusive comparison lets the showing through.

    PRD: "`showing_verdict` is `SUFFICIENT` when the rounded percentage is at least 30.00, and `INSUFFICIENT` otherwise; exactly 30.00 is sufficient, since the comparison is inclusive at the threshold."

    Design: Difficulty/boundary_precision_check/showing_of_interest_exactly_thirty_percent
    """
    petition_id = _fully_ruled_unit_of_ninety_heads()

    resp = api_client.verify_showing(
        petition_id,
        verify_showing_payload(
            submitted_card_count=33, duplicate_card_count=3, undated_card_count=1,
            stale_card_count=1, nonunit_card_count=1,
        ),
        BOARD,
    )
    validate_success(resp)
    petition = get_success_data(resp)

    assert petition["valid_card_count"] == 27, (
        f"33 cards less 6 defective leaves 27 valid, got {petition['valid_card_count']}"
    )
    assert petition["showing_headcount_basis"] == "AS_RULED", (
        f"a fully ruled case counts against the ruled unit, got {petition['showing_headcount_basis']}"
    )
    assert float(petition["showing_of_interest_pct"]) == pytest.approx(30.00, abs=0.005), (
        f"27 of 90 is exactly 30.00, got {petition['showing_of_interest_pct']}"
    )
    assert petition["showing_verdict"] == "SUFFICIENT", (
        f"exactly 30.00 is sufficient, got {petition['showing_verdict']}"
    )
    assert petition["case_status"] == "SOI_VERIFIED", (
        f"a sufficient showing advances the case, got {petition['case_status']}"
    )


def test_twenty_six_valid_cards_out_of_ninety_heads_falls_one_card_short():
    """One card fewer rounds to 28.89 and misses the threshold, dismissing the case.

    PRD: "For a case with 90 heads in the counted unit, 27 valid cards is exactly 30.00 and sufficient, while 26 valid cards is 28.89 and insufficient."

    Design: Difficulty/boundary_precision_check/showing_of_interest_exactly_thirty_percent
    """
    petition_id = _fully_ruled_unit_of_ninety_heads()

    resp = api_client.verify_showing(
        petition_id,
        verify_showing_payload(
            submitted_card_count=32, duplicate_card_count=3, undated_card_count=1,
            stale_card_count=1, nonunit_card_count=1,
        ),
        BOARD,
    )
    validate_success(resp)
    petition = get_success_data(resp)

    assert petition["valid_card_count"] == 26, (
        f"32 cards less 6 defective leaves 26 valid, got {petition['valid_card_count']}"
    )
    reported_pct = float(petition["showing_of_interest_pct"])
    assert reported_pct == pytest.approx(28.89, abs=0.005), (
        f"26 of 90 rounds half-up to 28.89, got {petition['showing_of_interest_pct']}"
    )
    assert reported_pct != pytest.approx(28.88, abs=0.001), (
        "28.88 would mean the percentage was truncated rather than rounded half-up"
    )
    assert petition["showing_verdict"] == "INSUFFICIENT", (
        f"28.89 is below the threshold, got {petition['showing_verdict']}"
    )
    assert petition["case_status"] == "DISMISSED", (
        f"an insufficient showing dismisses the case, got {petition['case_status']}"
    )


def _case_with_a_disputed_quality_inspector_group():
    """Two undisputed core groups plus a disputed quality-inspection group, with the core
    wage already frozen by the first scoring call."""
    set_clock("2026-08-04T10:00:00Z")
    petition = create_petition_in_scope_analysis()
    production = add_classification(petition["id"], **PRODUCTION_AND_MAINTENANCE[0])
    maintenance = add_classification(petition["id"], **PRODUCTION_AND_MAINTENANCE[1])
    quality = add_classification(
        petition["id"],
        code="QC", title="Quality Inspector", headcount=12, avg_hourly_wage_cents=2900,
        shift_code="B", work_location="PLANT_1_LAB", supervisory_authority_count=0,
        employer_position="EXCLUDE", union_position="INCLUDE",
        supervision_overlap=41, skills_overlap=55, functional_integration=61,
        interchange_rate=21, work_conditions_overlap=71,
    )
    production = score_classification(production["id"], "TRADITIONAL", COUNSEL)
    rule_classification(production["id"], "INCLUDED")
    maintenance = score_classification(maintenance["id"], "TRADITIONAL", COUNSEL)
    rule_classification(maintenance["id"], "INCLUDED")
    return petition["id"], production, maintenance, quality


def test_community_of_interest_score_rounds_each_weighted_term_before_summing():
    """The disputed inspection group scores 50.68, the total of six individually rounded
    products, not the 50.66 that rounding the sum once would give.

    PRD: "Under `TRADITIONAL`, each of the six factors is multiplied by its own weight — `supervision_overlap` by 0.325, `skills_overlap` by 0.225, `functional_integration` by 0.175, `interchange_rate` by 0.125, `work_conditions_overlap` by 0.100 and `wage_proximity` by 0.050 — **each product is rounded half-up to two decimals individually**, and only then are the six rounded terms added together to give `coi_score`."

    Design: Difficulty/boundary_precision_check/coi_per_term_rounding_versus_sum_then_round
    """
    petition_id, _production, _maintenance, quality = _case_with_a_disputed_quality_inspector_group()
    frozen_case = read_petition(petition_id)
    assert frozen_case["core_avg_hourly_wage_cents"] == 2667, (
        "the headcount-weighted core wage of 60 heads at 2400 and 30 at 3200 is 2667, "
        f"got {frozen_case['core_avg_hourly_wage_cents']}"
    )
    assert_instant_equals(
        frozen_case["core_wage_locked_at"], "2026-08-04T10:00:00Z", "core wage lock instant"
    )

    resp = api_client.score_classification(
        quality["id"], {"scoring_standard": "TRADITIONAL"}, COUNSEL
    )
    validate_success(resp)
    scored = get_success_data(resp)

    assert float(scored["wage_proximity"]) == pytest.approx(91.26, abs=0.005), (
        f"a 233 cent gap on a 2667 cent core wage leaves 91.26, got {scored['wage_proximity']}"
    )
    reported_score = float(scored["coi_score"])
    assert reported_score == pytest.approx(50.68, abs=0.005), (
        f"the six rounded terms total 50.68, got {scored['coi_score']}"
    )
    assert reported_score != pytest.approx(50.66, abs=0.001), (
        "50.66 would mean the unrounded products were summed and rounded once at the end"
    )
    assert reported_score != pytest.approx(50.08, abs=0.001), (
        "50.08 would mean the core wage came from a plain mean of the classification averages"
    )
    assert scored["coi_recommendation"] == "CONTESTED_COMMUNITY", (
        f"50.68 sits in the contested band, got {scored['coi_recommendation']}"
    )


def test_core_group_scores_also_total_their_individually_rounded_terms():
    """The two undisputed groups, scored against the same frozen core wage, come out at
    88.20 and 79.28 — again the sums of six separately rounded products.

    PRD: "Summing the unrounded products and rounding once at the end yields a different score and is wrong."

    Design: Difficulty/boundary_precision_check/coi_per_term_rounding_versus_sum_then_round
    """
    _petition_id, production, maintenance, _quality = _case_with_a_disputed_quality_inspector_group()

    assert float(production["wage_proximity"]) == pytest.approx(89.99, abs=0.005), (
        f"a 267 cent gap on a 2667 cent core wage leaves 89.99, got {production['wage_proximity']}"
    )
    assert float(production["coi_score"]) == pytest.approx(88.20, abs=0.005), (
        f"the production group's six rounded terms total 88.20, got {production['coi_score']}"
    )
    assert float(maintenance["wage_proximity"]) == pytest.approx(80.01, abs=0.005), (
        f"a 533 cent gap on a 2667 cent core wage leaves 80.01, got {maintenance['wage_proximity']}"
    )
    assert float(maintenance["coi_score"]) == pytest.approx(79.28, abs=0.005), (
        f"the maintenance group's six rounded terms total 79.28, got {maintenance['coi_score']}"
    )


def _elevated_and_borderline_messages_awaiting_counsel():
    """Two accuracy-reviewed messages in legal review, one scoring exactly 70 and one 69.

    No election round exists yet, so neither message can carry a per-se violation.
    """
    set_clock("2026-08-12T09:00:00Z")
    petition = create_petition_in_scope_analysis()
    presenter = create_trained_supervisor(
        petition["id"],
        full_name="Marta Kowalski",
        job_title="Shift Supervisor",
        span_of_control=18,
        has_hire_fire_authority=True,
    )
    elevated = create_campaign_message(
        petition["id"],
        channel="SMALL_GROUP_MEETING",
        audience_scope="CLASSIFICATION",
        planned_delivery_at="2026-08-25T10:00:00Z",
        duration_minutes=60,
        presenter_supervisor_id=presenter["id"],
        message_summary="Shift briefing on the consequences of union representation.",
        threat_statement_count=2,
        contains_interrogation=True,
        contains_promise_of_benefit=False,
        contains_surveillance_reference=True,
        material_claim_count=5,
        unsupported_material_claim_count=1,
    )
    accuracy_review(elevated["id"], material_claim_count=5, unsupported_material_claim_count=1)
    elevated = submit_message_for_review(elevated["id"])

    borderline = create_campaign_message(
        petition["id"],
        channel="CAPTIVE_AUDIENCE_MEETING",
        audience_scope="CLASSIFICATION",
        planned_delivery_at="2026-08-25T14:00:00Z",
        duration_minutes=45,
        presenter_supervisor_id=presenter["id"],
        message_summary="Afternoon all-hands on the employer position before the vote.",
        threat_statement_count=1,
        contains_interrogation=True,
        contains_promise_of_benefit=False,
        contains_surveillance_reference=False,
        material_claim_count=4,
        unsupported_material_claim_count=3,
    )
    accuracy_review(borderline["id"], material_claim_count=4, unsupported_material_claim_count=3)
    borderline = submit_message_for_review(borderline["id"])
    return elevated, borderline


def test_message_scoring_exactly_seventy_needs_the_escalation_acknowledgement_to_be_approved():
    """A message landing exactly on 70 is elevated, so counsel cannot approve it until the
    approving request carries the acknowledgement.

    PRD: "A `risk_score` of 70 or more is **elevated**: the message may enter review, but counsel may only approve it when the approving request carries `escalation_ack` set to true, and approval without it is refused with `ERR_ESCALATION_ACK_REQUIRED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/risk_score_escalation_threshold_seventy
    """
    elevated, _borderline = _elevated_and_borderline_messages_awaiting_counsel()
    assert elevated["risk_score"] == 70, (
        "a small-group meeting with two threats, an interrogation and a surveillance "
        f"reference scores 70, got {elevated['risk_score']}"
    )

    refused = api_client.review_communication(
        elevated["id"], review_communication_payload(disposition="APPROVE"), COUNSEL
    )
    validate_error(refused, ApiErrorId.ERR_ESCALATION_ACK_REQUIRED)

    untouched = read_campaign_message(elevated["id"])
    assert untouched["status"] == "PENDING_LEGAL_REVIEW", (
        f"a refused approval must leave the message in review, got {untouched['status']}"
    )
    assert untouched["revision_round"] == 0, (
        f"a refused approval is not a revision round, got {untouched['revision_round']}"
    )

    acknowledged = api_client.review_communication(
        elevated["id"],
        review_communication_payload(disposition="APPROVE", escalation_ack=True),
        COUNSEL,
    )
    validate_success(acknowledged)
    approved = get_success_data(acknowledged)
    assert approved["status"] == "APPROVED", (
        f"the acknowledged approval must land, got {approved['status']}"
    )
    assert approved["escalation_ack"] is True, (
        f"the acknowledgement must be recorded, got {approved['escalation_ack']}"
    )


def test_message_scoring_sixty_nine_is_approved_without_any_acknowledgement():
    """One point below the threshold the message is not elevated, so a plain approval is
    accepted.

    PRD: "Exactly 70 requires the acknowledgement; 69 does not."

    Design: Difficulty/boundary_precision_check/risk_score_escalation_threshold_seventy
    """
    _elevated, borderline = _elevated_and_borderline_messages_awaiting_counsel()
    assert borderline["risk_score"] == 69, (
        "a captive-audience meeting with one threat, an interrogation and three "
        f"unsupported claims scores 69, got {borderline['risk_score']}"
    )
    assert borderline["peerless_plywood_violation"] is False, (
        "with no election round there is no blackout for the meeting to fall inside"
    )

    resp = api_client.review_communication(
        borderline["id"], review_communication_payload(disposition="APPROVE"), COUNSEL
    )
    validate_success(resp)
    approved = get_success_data(resp)
    assert approved["status"] == "APPROVED", (
        f"a message below the elevation threshold is approved outright, got {approved['status']}"
    )


def _draft_list_due_on_the_twenty_fourth(complete_count=9, incomplete_count=1):
    """A draft list on a case stipulated on Thursday 2026-08-20, so the list is due at the
    end of the second business day, Monday 2026-08-24."""
    return setup_draft_voter_list(
        clock="2026-08-20T15:00:00Z",
        classification_specs=PRODUCTION_AND_MAINTENANCE,
        card_counts=SUFFICIENT_CARDS,
        entry_count=complete_count,
        incomplete_count=incomplete_count,
    )


def test_nine_complete_entries_of_ten_filed_exactly_at_the_deadline_is_a_minor_defect():
    """Ninety percent complete is exactly the minor-defect edge, and filing at the very
    instant of the deadline is still on time.

    PRD: "`is_late` is true exactly when `submitted_at` falls after `due_at`; equality is on time, and one second later is late."

    Design: Difficulty/boundary_precision_check/voter_list_ninety_percent_and_deadline_equality
    """
    ctx = _draft_list_due_on_the_twenty_fourth()
    assert_instant_equals(
        ctx["agreement"]["voter_list_due_at"], "2026-08-24T23:59:59Z", "arrangement list deadline"
    )
    assert_instant_equals(
        ctx["voter_list"]["due_at"], "2026-08-24T23:59:59Z", "voter list deadline"
    )

    set_clock("2026-08-24T23:59:59Z")
    resp = api_client.submit_voter_list(
        ctx["voter_list"]["id"], {"attested_by_title": "Director of Labor Relations"}, DIRECTOR
    )
    validate_success(resp)
    filed = get_success_data(resp)

    assert filed["total_entry_count"] == 10, (
        f"the list carries ten entries, got {filed['total_entry_count']}"
    )
    assert float(filed["completeness_pct"]) == pytest.approx(90.00, abs=0.005), (
        f"nine complete of ten is 90.00, got {filed['completeness_pct']}"
    )
    assert filed["is_late"] is False, (
        "a submission at the deadline instant is on time, not late"
    )
    assert filed["list_grade"] == "MINOR_DEFECT", (
        f"exactly 90.00 filed on time is a minor defect, got {filed['list_grade']}"
    )


def test_eight_complete_entries_of_nine_falls_just_below_the_minor_defect_edge():
    """A shade under ninety percent — 88.89 — drops the on-time list to the material tier.

    PRD: "Exactly 90.00 is a minor defect while 89.99 is a material one, and exactly 75.00 is a material defect."

    Design: Difficulty/boundary_precision_check/voter_list_ninety_percent_and_deadline_equality
    """
    ctx = _draft_list_due_on_the_twenty_fourth(complete_count=8, incomplete_count=1)

    set_clock("2026-08-24T23:59:59Z")
    resp = api_client.submit_voter_list(
        ctx["voter_list"]["id"], {"attested_by_title": "Director of Labor Relations"}, DIRECTOR
    )
    validate_success(resp)
    filed = get_success_data(resp)

    assert filed["total_entry_count"] == 9, (
        f"the list carries nine entries, got {filed['total_entry_count']}"
    )
    assert float(filed["completeness_pct"]) == pytest.approx(88.89, abs=0.005), (
        f"eight complete of nine rounds half-up to 88.89, got {filed['completeness_pct']}"
    )
    assert filed["is_late"] is False, "the list still went in at the deadline instant"
    assert filed["list_grade"] == "MATERIAL_DEFECT", (
        f"88.89 is below the minor-defect edge, got {filed['list_grade']}"
    )


def test_same_list_filed_one_second_past_the_deadline_is_graded_one_tier_worse():
    """One second after the deadline the list is late, so the same 90.00 lands a tier down.

    PRD: "Nine complete entries out of ten scores 90.00 and grades `MINOR_DEFECT` if on time, but `MATERIAL_DEFECT` if late."

    Design: Difficulty/boundary_precision_check/voter_list_ninety_percent_and_deadline_equality
    """
    ctx = _draft_list_due_on_the_twenty_fourth()

    set_clock("2026-08-25T00:00:00Z")
    resp = api_client.submit_voter_list(
        ctx["voter_list"]["id"],
        {"attested_by_title": "Director of Labor Relations", "late_submission_ack": True},
        DIRECTOR,
    )
    validate_success(resp)
    filed = get_success_data(resp)

    assert float(filed["completeness_pct"]) == pytest.approx(90.00, abs=0.005), (
        f"nine complete of ten is still 90.00, got {filed['completeness_pct']}"
    )
    assert filed["is_late"] is True, (
        "one second past the deadline is late"
    )
    assert filed["list_grade"] == "MATERIAL_DEFECT", (
        f"a late minor defect is graded one tier worse, got {filed['list_grade']}"
    )


def test_cure_resubmitted_at_the_exact_cure_deadline_is_accepted_and_regraded():
    """Curing the missing e-mail and resubmitting at the very instant the cure window
    closes is accepted; the list scores 100.00 but is now late, so it grades one tier down.

    PRD: "Resubmission is only possible from `DEFICIENT`, only while the logical clock is at or before `cure_deadline_at` — later is `ERR_CURE_WINDOW_EXPIRED` — and only while `resubmission_count` is still below its ceiling of 2, since a third cure attempt is refused with `ERR_RESUBMISSION_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/voter_list_ninety_percent_and_deadline_equality
    """
    ctx = _draft_list_due_on_the_twenty_fourth()
    voter_list_id = ctx["voter_list"]["id"]
    incomplete_entry = ctx["entries"][-1]

    set_clock("2026-08-24T23:59:59Z")
    submit_voter_list(voter_list_id)

    set_clock("2026-08-25T09:00:00Z")
    returned = review_voter_list(voter_list_id, "RETURN_FOR_CURE", ["MISSING_EMAIL"])
    assert returned["status"] == "DEFICIENT", (
        f"a returned list waits in the deficient state, got {returned['status']}"
    )
    assert returned["cure_window_hours"] == 48, (
        f"a minor defect earns a 48 hour cure window, got {returned['cure_window_hours']}"
    )
    assert_instant_equals(
        returned["cure_deadline_at"], "2026-08-27T09:00:00Z", "cure deadline"
    )

    cured = api_client.update_voter_list_entry(
        incomplete_entry["id"], {"personal_email": "jonas.weber@example.com"}, ANALYST
    )
    validate_success(cured)

    set_clock("2026-08-27T09:00:00Z")
    resp = api_client.resubmit_voter_list(
        voter_list_id, {"attested_by_title": "Director of Labor Relations"}, DIRECTOR
    )
    validate_success(resp)
    refiled = get_success_data(resp)

    assert refiled["status"] == "SUBMITTED", (
        f"a successful resubmission returns the list to submitted, got {refiled['status']}"
    )
    assert refiled["resubmission_count"] == 1, (
        f"the cure attempt is counted once, got {refiled['resubmission_count']}"
    )
    assert float(refiled["completeness_pct"]) == pytest.approx(100.00, abs=0.005), (
        f"every entry is now complete, got {refiled['completeness_pct']}"
    )
    assert refiled["is_late"] is True, (
        "the lateness test runs afresh against the original deadline of 2026-08-24T23:59:59Z"
    )
    assert refiled["list_grade"] == "MINOR_DEFECT", (
        f"a late but complete list is graded one tier below compliant, got {refiled['list_grade']}"
    )
    assert refiled["eligible_voter_count"] == 10, (
        f"all ten voters remain eligible, got {refiled['eligible_voter_count']}"
    )
