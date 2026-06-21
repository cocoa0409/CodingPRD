"""Validation-priority ordering across error-category pairs and OCC
stale-version errors on the three guarded endpoints (PRD §2.5, §2.6, §2.7).
"""
from test_helpers import (
    validate_success, validate_error,
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_program, setup_certified_athlete, create_student_athlete,
    setup_program_with_certified_athlete,
    create_draft_offer, send_offer,
    create_period, set_clock,
    submit_certification,
    report_incident, open_investigation,
    make_coach_headers,
    create_recruiting_contact_payload,
    create_scholarship_offer_payload, send_scholarship_offer_payload,
    sustain_booster_incident_payload,
    create_booster_incident_payload,
    TEST_USERS,
)


# ─── Difficulty: priority_pair_validation_conflict (Rule 5) ─────────


def test_existence_wins_over_dead_period_when_fk_bogus(api):
    """PRD §2.6: "The order is: authentication of the request headers
    (`ERR_UNAUTHENTICATED`); authorization of the role for the endpoint
    (`ERR_UNAUTHORIZED`); resolution of every `id` segment in the URL
    path, left-to-right (`ERR_NOT_FOUND`); resolution of every
    foreign-key field carried in the request body (`ERR_NOT_FOUND`); the
    state-machine precondition that the target row is in a state from
    which the requested transition is legal (`ERR_INVALID_STATE`)"

    Design: Difficulty/priority_pair_validation_conflict/existence_vs_business_safety_not_found_wins_over_dead_period
    """
    # A real program with a DEAD period, but the request uses bogus FKs.
    real_program = create_program(sport_code="FOOTBALL", school_name="Calendar U",
                                  scholarship_slot_cap=85)
    create_period(real_program["id"], period_type="DEAD",
                  starts_at="2026-06-10T00:00:00Z", ends_at="2026-06-20T00:00:00Z")
    set_clock("2026-06-15T12:00:00Z")

    res = api.create_recruiting_contact(
        create_recruiting_contact_payload(
            program_id="00000000-0000-0000-0000-000000000000",
            student_athlete_id="00000000-0000-0000-0000-000000000001",
            coach_user_id="coach_zzz",
            contact_at="2026-06-15T12:00:00Z",
            channel="EMAIL",
        ),
        make_coach_headers("coach_zzz"),
    )
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_existence_wins_when_program_id_bogus_athlete_real(api):
    """PRD §2.7: "the system validates these identifiers in strict
    left-to-right order: if the first identifier in the path does not
    resolve to an existing row, the request is rejected with
    `ERR_NOT_FOUND` before the system attempts to resolve any subsequent
    identifier. The same rule applies to foreign-key identifiers carried
    in the request body — for example, the `program_id`,
    `student_athlete_id`, and `matched_program_id` fields — which are
    resolved against their target entities and rejected with
    `ERR_NOT_FOUND` if they do not exist."

    Design: Difficulty/priority_pair_validation_conflict/existence_vs_business_safety_not_found_wins_over_dead_period
    """
    # Real athlete, real program — but request uses a bogus program_id.
    # A DEAD period exists on the real program at the contact time.
    real_program = create_program(sport_code="FOOTBALL", school_name="Calendar2 U",
                                  scholarship_slot_cap=85)
    create_period(real_program["id"], period_type="DEAD",
                  starts_at="2026-06-10T00:00:00Z", ends_at="2026-06-20T00:00:00Z")
    set_clock("2026-06-15T12:00:00Z")
    athlete = create_student_athlete(sport_code="FOOTBALL", full_name="Real Cand")

    res = api.create_recruiting_contact(
        create_recruiting_contact_payload(
            program_id=NON_EXISTENT_UUID,
            student_athlete_id=athlete["id"],
            coach_user_id="coach_real",
            contact_at="2026-06-15T12:00:00Z",
            channel="EMAIL",
        ),
        make_coach_headers("coach_real"),
    )
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_business_constraint_athlete_not_certified_wins_over_slot_cap(api):
    """PRD §2.6: "In particular: ... On the scholarship-offer send
    endpoint, the cross-entity eligibility check (the athlete must be
    `CERTIFIED`) is checked before the slot-cap boundary check."

    Design: Difficulty/priority_pair_validation_conflict/business_fiscal_vs_business_constraint_athlete_not_certified_wins
    """
    # cap=1, slots_committed=1 from a SENT offer to a certified athlete X;
    # then DRAFT offer to athlete Y whose cert is still PENDING — sending
    # Y's offer violates BOTH cap (1+1>1) AND athlete-not-certified.
    program = create_program(sport_code="FOOTBALL", school_name="Cap1 U", scholarship_slot_cap=1)
    athlete_x = setup_certified_athlete(sport_code="FOOTBALL", full_name="Athlete X")
    athlete_y = create_student_athlete(sport_code="FOOTBALL", full_name="Athlete Y", gpa=3.500)
    submit_certification(athlete_y["id"])  # PENDING, never approved

    ox = create_draft_offer(program["id"], athlete_x["id"], annual_value_cents=5_000_000)
    send_offer(ox["id"], program["version"])
    program_v1 = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )

    oy = create_draft_offer(program["id"], athlete_y["id"], annual_value_cents=5_000_000)
    res = api.send_scholarship_offer(
        oy["id"],
        send_scholarship_offer_payload(expected_program_version=program_v1["version"]),
        TEST_USERS["coach_headers"],
    )
    validate_error(res, ApiErrorId.ERR_ATHLETE_NOT_CERTIFIED.value)


def test_business_constraint_athlete_not_certified_wins_when_athlete_ineligible(api):
    """PRD §2.6: "On the scholarship-offer send endpoint, the cross-entity
    eligibility check (the athlete must be `CERTIFIED`) is checked before
    the slot-cap boundary check."
    PRD §3.4: "an attempt to send an offer to an uncertified or
    ineligible athlete is rejected with `ERR_ATHLETE_NOT_CERTIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/business_fiscal_vs_business_constraint_athlete_not_certified_wins
    """
    # Same conflict, this time the athlete is INELIGIBLE (denial path)
    # while the program is at cap.
    from test_helpers import deny_certification
    program = create_program(sport_code="FOOTBALL", school_name="CapDeny U",
                             scholarship_slot_cap=1)
    athlete_x = setup_certified_athlete(sport_code="FOOTBALL", full_name="X")
    athlete_z = create_student_athlete(sport_code="FOOTBALL", full_name="Z", gpa=2.000)

    # Fill the cap with X.
    ox = create_draft_offer(program["id"], athlete_x["id"], annual_value_cents=5_000_000)
    send_offer(ox["id"], program["version"])
    program_v1 = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )

    # Athlete Z's certification gets denied → INELIGIBLE.
    cert_z = submit_certification(athlete_z["id"])
    deny_certification(cert_z["id"], denial_reason="GPA_BELOW_MIN")

    # Create a DRAFT to Z and try to send: violates BOTH slot cap AND
    # athlete-not-certified.
    oz = create_draft_offer(program["id"], athlete_z["id"], annual_value_cents=5_000_000)
    res = api.send_scholarship_offer(
        oz["id"],
        send_scholarship_offer_payload(expected_program_version=program_v1["version"]),
        TEST_USERS["coach_headers"],
    )
    validate_error(res, ApiErrorId.ERR_ATHLETE_NOT_CERTIFIED.value)


# ─── Corner: OCC stale-version errors ────────────────────


def test_stale_program_version_on_send_rejected(api):
    """PRD §2.5: "Sending a scholarship offer (i.e. the action that
    transitions `ScholarshipOffer.status` from `DRAFT` to `SENT`)
    requires `expected_program_version` in the request body, matching
    the current `version` of the offer's parent `Program`."
    PRD §2.5: "A mismatch is rejected with `ERR_STALE_PROGRAM_VERSION`
    (HTTP 412)."

    Design: Corner/errors/error_stale_program_version_on_send
    """
    program = create_program(sport_code="FOOTBALL", school_name="OCC U", scholarship_slot_cap=85)
    athlete_a = setup_certified_athlete(sport_code="FOOTBALL", full_name="A1")
    athlete_b = setup_certified_athlete(sport_code="FOOTBALL", full_name="A2", gpa=3.400)

    stale_version = program["version"]
    o1 = create_draft_offer(program["id"], athlete_a["id"], annual_value_cents=3_000_000)
    send_offer(o1["id"], stale_version)  # Advances program.version.

    # Second offer attempts to send with the now-stale version.
    o2 = create_draft_offer(program["id"], athlete_b["id"], annual_value_cents=3_000_000)
    res = api.send_scholarship_offer(
        o2["id"],
        send_scholarship_offer_payload(expected_program_version=stale_version),
        TEST_USERS["coach_headers"],
    )
    validate_error(res, ApiErrorId.ERR_STALE_PROGRAM_VERSION.value)


def test_stale_incident_version_on_sustain_rejected(api):
    """PRD §2.5: "Sustaining a booster incident requires
    `expected_boosterincident_version` in the request body, matching
    the current `version` of the targeted `BoosterIncident`."
    PRD §2.5: "A mismatch is rejected with `ERR_STALE_INCIDENT_VERSION`
    (HTTP 412)."

    Design: Corner/errors/error_stale_incident_version_on_sustain
    """
    program = create_program(sport_code="MBB", school_name="Inc U", scholarship_slot_cap=13)
    athlete = create_student_athlete(sport_code="MBB", full_name="AthInc")
    incident = report_incident(
        program, athlete, alleged_value_cents=100_000, booster_name="B",
    )
    stale_v = incident["version"]
    open_investigation(incident["id"])  # Advances incident.version.

    res = api.sustain_booster_incident(
        incident["id"],
        sustain_booster_incident_payload(expected_boosterincident_version=stale_v),
        TEST_USERS["compliance_officer_headers"],
    )
    validate_error(res, ApiErrorId.ERR_STALE_INCIDENT_VERSION.value)


def test_occ_correct_version_send_succeeds_and_program_version_increments(api):
    """PRD §2.5: "Sending a scholarship offer (i.e. the action that
    transitions `ScholarshipOffer.status` from `DRAFT` to `SENT`)
    requires `expected_program_version` in the request body, matching
    the current `version` of the offer's parent `Program`."
    PRD §2.4: "`version` (integer): begins at 1 on creation and is
    incremented by 1 on every mutation of the row, including mutations
    driven by cascades from elsewhere in the system."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds
    """
    program = create_program(sport_code="FOOTBALL", school_name="Happy U", scholarship_slot_cap=85)
    athlete = setup_certified_athlete(sport_code="FOOTBALL", full_name="OkAth")
    offer = create_draft_offer(program["id"], athlete["id"], annual_value_cents=3_000_000)

    assert program["version"] == 1
    res = api.send_scholarship_offer(
        offer["id"],
        send_scholarship_offer_payload(expected_program_version=program["version"]),
        TEST_USERS["coach_headers"],
    )
    sent = validate_success(res, 200)
    assert sent["status"] == "SENT"

    refreshed = validate_success(
        api.get_program(program["id"], TEST_USERS["compliance_officer_headers"]), 200,
    )
    assert refreshed["version"] == 2
