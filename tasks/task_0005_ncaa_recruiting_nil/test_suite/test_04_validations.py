"""Validation claims: recruiting-calendar contact rules (DEAD / QUIET /
OUTSIDE / period overlap / invalid interval), segregation-of-duties on
NIL approve, scholarship slot cap boundary, athlete-not-certified, zero-
value booster incident, high-value NIL deal under sanction
(PRD §3.1, §3.3, §3.4, §3.5, §3.7).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_program, create_student_athlete, setup_certified_athlete,
    create_period, set_clock,
    setup_program_with_certified_athlete,
    setup_program_at_level_one,
    create_draft_offer, send_offer,
    submit_certification,
    create_nil_deal, submit_nil_deal,
    make_student_athlete_headers, make_nil_reviewer_headers,
    make_coach_headers,
    create_period_payload,
    create_recruiting_contact_payload,
    create_scholarship_offer_payload, send_scholarship_offer_payload,
    create_booster_incident_payload,
    TEST_USERS,
)


# ─── Corner: contact-calendar violations ────────────────


def test_dead_period_contact_rejected(api):
    """PRD §3.3: "First, if `contact_at` falls inside a period whose
    `period_type` is `DEAD`, the contact is rejected with
    `ERR_DEAD_PERIOD_CONTACT`; all contact is prohibited during a dead
    period regardless of channel."

    Design: Corner/validations/dead_period_contact_rejected
    """
    program = create_program(sport_code="FOOTBALL", school_name="Dead U", scholarship_slot_cap=85)
    create_period(program["id"], period_type="DEAD",
                  starts_at="2026-11-01T00:00:00Z", ends_at="2026-11-15T00:00:00Z")
    set_clock("2026-11-10T08:00:00Z")
    athlete = create_student_athlete(sport_code="FOOTBALL", gpa=3.000, full_name="Dd")

    res = api.create_recruiting_contact(
        create_recruiting_contact_payload(
            program_id=program["id"],
            student_athlete_id=athlete["id"],
            coach_user_id="coach_d",
            contact_at="2026-11-10T08:00:00Z",
            channel="IN_PERSON",
        ),
        make_coach_headers("coach_d"),
    )
    validate_error(res, ApiErrorId.ERR_DEAD_PERIOD_CONTACT.value)


def test_quiet_period_non_in_person_channel_rejected(api):
    """PRD §3.3: "Second, if `contact_at` falls inside a period whose
    `period_type` is `QUIET`, only in-person contact is permitted; a
    quiet-period contact whose `channel` is anything other than
    `IN_PERSON` is rejected with `ERR_QUIET_PERIOD_VIOLATION`."

    Design: Corner/validations/quiet_period_email_channel_rejected
    """
    program = create_program(sport_code="FOOTBALL", school_name="Quiet U", scholarship_slot_cap=85)
    create_period(program["id"], period_type="QUIET",
                  starts_at="2026-08-01T00:00:00Z", ends_at="2026-08-10T00:00:00Z")
    set_clock("2026-08-05T12:00:00Z")
    athlete = create_student_athlete(sport_code="FOOTBALL", full_name="Cand")

    res = api.create_recruiting_contact(
        create_recruiting_contact_payload(
            program_id=program["id"],
            student_athlete_id=athlete["id"],
            coach_user_id="coach_a",
            contact_at="2026-08-05T12:00:00Z",
            channel="EMAIL",
        ),
        make_coach_headers("coach_a"),
    )
    validate_error(res, ApiErrorId.ERR_QUIET_PERIOD_VIOLATION.value)


def test_contact_outside_any_period_rejected(api):
    """PRD §3.3: "Third, if `contact_at` does not fall inside any period
    at all — the program's calendar has a gap at that instant — the
    contact is implicitly prohibited and is rejected with
    `ERR_OUTSIDE_RECRUITING_WINDOW`."

    Design: Corner/validations/contact_outside_any_period_rejected
    """
    program = create_program(sport_code="SOFTBALL", school_name="Gap U", scholarship_slot_cap=12)
    create_period(program["id"], period_type="CONTACT",
                  starts_at="2026-09-01T00:00:00Z", ends_at="2026-09-10T00:00:00Z")
    athlete = create_student_athlete(sport_code="SOFTBALL", full_name="Gp")

    res = api.create_recruiting_contact(
        create_recruiting_contact_payload(
            program_id=program["id"],
            student_athlete_id=athlete["id"],
            coach_user_id="coach_b",
            contact_at="2026-09-15T12:00:00Z",  # falls in the gap after 09-10
            channel="PHONE",
        ),
        make_coach_headers("coach_b"),
    )
    validate_error(res, ApiErrorId.ERR_OUTSIDE_RECRUITING_WINDOW.value)


def test_period_invalid_interval_zero_length_rejected(api):
    """PRD §3.1: "Each period must describe a forward-going interval,
    i.e. its `starts_at` must be strictly earlier than its `ends_at`; an
    inverted or zero-length interval is rejected with
    `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/period_invalid_interval_rejected
    """
    program = create_program(sport_code="WBB", school_name="Inv U", scholarship_slot_cap=15)
    res = api.create_period(
        program["id"],
        create_period_payload(
            period_type="CONTACT",
            starts_at="2026-10-05T00:00:00Z",
            ends_at="2026-10-05T00:00:00Z",  # zero-length
        ),
        TEST_USERS["compliance_officer_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INVALID_INTERVAL.value)


def test_sod_violation_same_user_submits_and_approves(api):
    """PRD §3.5: "The first precondition on approval is segregation of
    duties: the approver's `X-User-ID` must differ from the `X-User-ID`
    of every prior submitter and revision-requester of this same deal,
    across all revision cycles. A violation is rejected with
    `ERR_SOD_VIOLATION`."

    Design: Corner/validations/sod_violation_same_user_submits_and_approves
    """
    athlete = setup_certified_athlete(sport_code="BASEBALL", full_name="Sod")
    deal = create_nil_deal(athlete, gross_value_cents=200_000, agent_fee_pct=0.0)
    submit_nil_deal(deal["id"], reviewer_user_id="reviewer_alpha")

    res = api.approve_nil_deal(
        deal["id"], make_nil_reviewer_headers("reviewer_alpha"),
    )
    validate_error(res, ApiErrorId.ERR_SOD_VIOLATION.value)


# ─── Difficulty: boundary_precision_check / slot cap (Rule 6, instance 1) ─


def test_scholarship_slot_send_succeeds_at_cap_minus_one(api):
    """PRD §3.4: "the boundary check is that one more than the program's
    current `slots_committed` must be no larger than its
    `scholarship_slot_cap`, which is equivalent to saying the current
    count must be strictly less than the cap."

    Design: Difficulty/boundary_precision_check/scholarship_slot_cap_boundary_at_equal
    """
    program = create_program(sport_code="WBB", school_name="Bound U", scholarship_slot_cap=2)
    athlete_p = setup_certified_athlete(sport_code="WBB", full_name="Athlete P")
    athlete_q = setup_certified_athlete(sport_code="WBB", full_name="Athlete Q", gpa=3.400)

    # First send: slots 0 → 1
    op = create_draft_offer(program["id"], athlete_p["id"], annual_value_cents=3_000_000)
    sent_p = send_offer(op["id"], program["version"])

    program_v1 = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )

    # Second send: slots 1 → 2 (= cap). One-more-than-current (2) <= cap (2): permitted.
    oq = create_draft_offer(program["id"], athlete_q["id"], annual_value_cents=3_000_000)
    res = api.send_scholarship_offer(
        oq["id"],
        send_scholarship_offer_payload(expected_program_version=program_v1["version"]),
        TEST_USERS["coach_headers"],
    )
    sent_q = validate_success(res, 200)
    assert sent_q["status"] == "SENT"

    program_v2 = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )
    assert program_v2["slots_committed"] == 2


def test_scholarship_slot_send_at_cap_rejects_next_with_slot_cap_exceeded(api):
    """PRD §3.4: "A program that is already at its cap rejects further
    sends with `ERR_SLOT_CAP_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/scholarship_slot_cap_boundary_at_equal
    """
    program = create_program(sport_code="WBB", school_name="OverCap U", scholarship_slot_cap=1)
    athlete_p = setup_certified_athlete(sport_code="WBB", full_name="Athlete P")
    athlete_q = setup_certified_athlete(sport_code="WBB", full_name="Athlete Q", gpa=3.400)

    # First send fills the cap (slots 0 → 1 = cap).
    op = create_draft_offer(program["id"], athlete_p["id"], annual_value_cents=3_000_000)
    send_offer(op["id"], program["version"])

    program_v1 = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )

    # Second send would exceed the cap.
    oq = create_draft_offer(program["id"], athlete_q["id"], annual_value_cents=3_000_000)
    res = api.send_scholarship_offer(
        oq["id"],
        send_scholarship_offer_payload(expected_program_version=program_v1["version"]),
        TEST_USERS["coach_headers"],
    )
    validate_error(res, ApiErrorId.ERR_SLOT_CAP_EXCEEDED.value)


# ─── Difficulty: boundary_precision_check / zero-value incident ─────────


def test_zero_value_incident_rejected_at_alleged_value_zero(api):
    """PRD §3.7: "The supplied `alleged_value_cents` must be strictly
    greater than zero — a report with `alleged_value_cents` equal to 0
    is rejected with `ERR_ZERO_VALUE_INCIDENT`, because a zero-value
    allegation carries no investigatory weight."

    Design: Difficulty/boundary_precision_check/zero_value_incident_rejected_empty_zero_boundary
    """
    program = create_program(sport_code="MBB", school_name="Zero U", scholarship_slot_cap=13)
    athlete = create_student_athlete(sport_code="MBB", full_name="Athlete R", gpa=3.000)

    res = api.create_booster_incident(
        create_booster_incident_payload(
            program_id=program["id"],
            booster_name="Zero Booster",
            student_athlete_id=athlete["id"],
            alleged_value_cents=0,
        ),
        TEST_USERS["compliance_officer_headers"],
    )
    validate_error(res, ApiErrorId.ERR_ZERO_VALUE_INCIDENT.value)


def test_zero_value_incident_at_one_cent_accepted(api):
    """PRD §3.7: "The supplied `alleged_value_cents` must be strictly
    greater than zero — a report with `alleged_value_cents` equal to 0
    is rejected with `ERR_ZERO_VALUE_INCIDENT`, because a zero-value
    allegation carries no investigatory weight."

    Design: Difficulty/boundary_precision_check/zero_value_incident_rejected_empty_zero_boundary
    """
    program = create_program(sport_code="MBB", school_name="One U", scholarship_slot_cap=13)
    athlete = create_student_athlete(sport_code="MBB", full_name="Athlete S", gpa=3.000)

    res = api.create_booster_incident(
        create_booster_incident_payload(
            program_id=program["id"],
            booster_name="One Cent Booster",
            student_athlete_id=athlete["id"],
            alleged_value_cents=1,
        ),
        TEST_USERS["compliance_officer_headers"],
    )
    incident = validate_success(res, 201)
    assert incident["alleged_value_cents"] == 1
    assert incident["status"] == "REPORTED"


# ─── Difficulty: cross_entity_state_dependency instances ─────────────


def test_send_offer_blocked_when_athlete_uncertified(api):
    """PRD §3.4: "First, the recipient athlete must already have
    `eligibility_status` equal to `CERTIFIED`; an attempt to send an
    offer to an uncertified or ineligible athlete is rejected with
    `ERR_ATHLETE_NOT_CERTIFIED`."

    Design: Difficulty/cross_entity_state_dependency/send_offer_requires_athlete_certified
    """
    program = create_program(sport_code="FOOTBALL", school_name="Cert U", scholarship_slot_cap=85)
    athlete = create_student_athlete(sport_code="FOOTBALL", full_name="Athlete S")
    submit_certification(athlete["id"])  # PENDING, never approved

    offer = create_draft_offer(
        program["id"], athlete["id"], annual_value_cents=5_000_000,
    )
    res = api.send_scholarship_offer(
        offer["id"],
        send_scholarship_offer_payload(expected_program_version=program["version"]),
        TEST_USERS["coach_headers"],
    )
    validate_error(res, ApiErrorId.ERR_ATHLETE_NOT_CERTIFIED.value)


def test_send_offer_succeeds_after_athlete_certified(api):
    """PRD §3.4: "First, the recipient athlete must already have
    `eligibility_status` equal to `CERTIFIED`; an attempt to send an
    offer to an uncertified or ineligible athlete is rejected with
    `ERR_ATHLETE_NOT_CERTIFIED`."

    Design: Difficulty/cross_entity_state_dependency/send_offer_requires_athlete_certified
    """
    program, athlete = setup_program_with_certified_athlete(
        sport_code="FOOTBALL", scholarship_slot_cap=85,
    )
    offer = create_draft_offer(program["id"], athlete["id"], annual_value_cents=5_000_000)
    res = api.send_scholarship_offer(
        offer["id"],
        send_scholarship_offer_payload(expected_program_version=program["version"]),
        TEST_USERS["coach_headers"],
    )
    sent = validate_success(res, 200)
    assert sent["status"] == "SENT"


def test_high_value_nil_approve_blocked_when_program_under_sanction(api):
    """PRD §3.5: "The second precondition is the high-value-under-sanction
    gate: if the deal's `tier` is `HIGH_VALUE` and the deal's athlete is
    enrolled in a program (i.e. `enrolled_program_id` is non-null) whose
    `penalty_tier` is anything other than `NONE`, approval is blocked. A
    violation is rejected with `ERR_PROGRAM_UNDER_SANCTION`."

    Design: Difficulty/cross_entity_state_dependency/nil_approve_requires_program_not_under_sanction
    """
    # 1) Set up program + certified athlete, send & accept an offer so the
    #    athlete's enrolled_program_id pins to this program.
    program, athlete = setup_program_with_certified_athlete(
        sport_code="MBB", scholarship_slot_cap=13,
    )
    offer = create_draft_offer(program["id"], athlete["id"], annual_value_cents=5_000_000)
    send_offer(offer["id"], program["version"])
    accept_res = api.accept_scholarship_offer(
        offer["id"], make_student_athlete_headers(athlete["id"]),
    )
    validate_success(accept_res, 200)

    # 2) Sustain a weight-3 incident (alleged_value 100,000 cents) to put
    #    penalty_tier at LEVEL_I.
    program_after = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )
    from test_helpers import report_and_sustain_incident
    report_and_sustain_incident(
        program_after, athlete, alleged_value_cents=100_000,
    )
    final_program = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )
    assert final_program["penalty_tier"] != "NONE"

    # 3) Create HIGH_VALUE NIL deal (gross 600,000, fee 0.0 → net 600,000)
    #    and walk it to UNDER_REVIEW with a distinct submitter so that the
    #    later approval — by a different reviewer identity — clears the
    #    PRD §3.5 SOD precondition and reaches the under-sanction gate.
    deal = create_nil_deal(
        athlete, brand_name="Big Brand",
        gross_value_cents=600_000, agent_fee_pct=0.0,
    )
    assert deal["tier"] == "HIGH_VALUE"
    submit_nil_deal(deal["id"], reviewer_user_id="submitter_x")

    # 4) Approve by a DIFFERENT reviewer identity (clears SOD) → still
    #    blocked because tier == HIGH_VALUE and program is under sanction.
    res = api.approve_nil_deal(
        deal["id"], make_nil_reviewer_headers("approver_y"),
    )
    validate_error(res, ApiErrorId.ERR_PROGRAM_UNDER_SANCTION.value)


def test_de_minimis_nil_approve_allowed_under_sanction(api):
    """PRD §3.5: "Equivalently: a high-value deal can be approved only
    when the athlete's enrolled program is under no sanction, while a
    `DE_MINIMIS` or `STANDARD` deal may be approved regardless of the
    program's `penalty_tier`."

    Design: Difficulty/cross_entity_state_dependency/nil_approve_requires_program_not_under_sanction
    """
    # 1) Program + accepted offer pinning enrolled_program_id.
    program, athlete = setup_program_with_certified_athlete(
        sport_code="MBB", scholarship_slot_cap=13,
    )
    offer = create_draft_offer(program["id"], athlete["id"], annual_value_cents=5_000_000)
    send_offer(offer["id"], program["version"])
    api.accept_scholarship_offer(
        offer["id"], make_student_athlete_headers(athlete["id"]),
    )

    program_after = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )

    # 2) Push penalty_tier to LEVEL_I.
    from test_helpers import report_and_sustain_incident
    report_and_sustain_incident(
        program_after, athlete, alleged_value_cents=100_000,
    )

    # 3) Submit a DE_MINIMIS deal (gross 50_000, fee 0.0 → net 50_000 → < 60_000).
    deal = create_nil_deal(
        athlete, brand_name="Small Brand",
        gross_value_cents=50_000, agent_fee_pct=0.0,
    )
    assert deal["tier"] == "DE_MINIMIS"
    submit_nil_deal(deal["id"], reviewer_user_id="submitter_x")

    # 4) Approve by a DIFFERENT reviewer (SOD): allowed because tier !=
    #    HIGH_VALUE.
    res = api.approve_nil_deal(
        deal["id"], make_nil_reviewer_headers("approver_y"),
    )
    approved = validate_success(res, 200)
    assert approved["status"] == "APPROVED"
