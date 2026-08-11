"""Intake: participant files, support assessments, consent and eligibility."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    activate_assessment,
    api_client,
    assert_participant,
    assert_slot_conservation,
    charge_for,
    create_active_participant,
    create_assessment,
    create_caregiver,
    create_confirmed_enrollment,
    create_consent,
    create_fee_band,
    create_goal,
    create_open_session,
    create_participant,
    create_signed_consent,
    participant_payload,
    participant_version,
    read_enrollment,
    read_goal,
    read_participant,
    read_session,
    request_enrollment,
    set_clock,
    set_participant_status,
    staffing_summary,
    support_assessment_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, COORD


def test_participant_create_returns_intake_status_and_null_effective_tier():
    """PRD §3.2: "The row is created in `status` `INTAKE` with
    `effective_support_tier` null and `version` 1."

    Design: Corner/entities/participant_create_returns_intake_status_and_null_effective_tier
    """
    create_fee_band()
    response = api_client.create_participant(participant_payload(), COORD)
    data = validate_success(response, expected_status=201)

    assert_participant(data)
    assert data["status"] == "INTAKE", f"Expected INTAKE, got {data['status']}"
    assert data["version"] == 1, f"Expected version 1 on a new row, got {data['version']}"
    assert data["effective_support_tier"] is None, (
        f"Expected null effective_support_tier, got {data['effective_support_tier']}"
    )
    assert data["household_id"] == "HH-1"
    assert data["weight_kg"] == 40

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_participant_age_years_is_computed_from_the_logical_clock():
    """PRD §3.2: "`age_years` is the number of whole years from `date_of_birth`
    to the logical clock's calendar date, discarding any part year — a person
    whose birthday falls tomorrow is still the younger age today."

    Design: Corner/entities/participant_age_years_is_computed_from_the_logical_clock
    """
    participant = create_participant(
        legal_name="Tess Aoki",
        date_of_birth="2008-06-01",
        household_id="HH-9",
        household_size=2,
        income_band="BAND_D",
        weight_kg=60,
        guardianship_status="SELF",
    )

    before = read_participant(participant["id"])
    assert before["age_years"] == 17, (
        f"At the 2026-05-01 default clock a 2008-06-01 birth is 17, got {before['age_years']}"
    )

    set_clock("2026-06-01T00:00:00Z")

    after = read_participant(participant["id"])
    assert after["age_years"] == 18, (
        f"Once the clock reads 2026-06-01 the same row is 18, got {after['age_years']}"
    )


def test_participant_list_paginates_with_total_count_and_has_more():
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and
    `has_more` in the `meta` object, where `total_count` is the number of rows
    matching the filters before paging and `has_more` is true exactly when
    `offset` plus the number of returned rows is still below `total_count`."

    Design: Corner/entities/participant_list_paginates_with_total_count_and_has_more
    """
    create_participant(legal_name="Ada Rivera", household_id="HH-1")
    create_participant(
        legal_name="Ben Osei", date_of_birth="2009-07-15", household_id="HH-2", weight_kg=45
    )
    create_participant(
        legal_name="Cleo Vance", date_of_birth="2008-11-02", household_id="HH-3", weight_kg=50
    )

    first_page, first_meta = validate_paginated(
        api_client.list_participants(ADMIN, params={"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2, f"Expected 2 rows on the first page, got {len(first_page)}"
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert api_client.list_participants(ADMIN, params={"limit": 2, "offset": 0}).json()[
        "response_type"
    ] == "array"

    second_page, second_meta = validate_paginated(
        api_client.list_participants(ADMIN, params={"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1, f"Expected 1 row on the second page, got {len(second_page)}"
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2


def test_get_unknown_participant_returns_participant_not_found():
    """PRD §2.7: "In rung order: a missing participant is
    `ERR_PARTICIPANT_NOT_FOUND`; a missing activity programme is
    `ERR_PROGRAM_NOT_FOUND`; a missing program session is
    `ERR_SESSION_NOT_FOUND`; a missing enrolment is `ERR_ENROLLMENT_NOT_FOUND`
    and a missing enrolment charge is `ERR_CHARGE_NOT_FOUND` at that same rung"

    Design: Corner/entities/participant_get_unknown_id_returns_not_found
    """
    create_fee_band()

    response = api_client.get_participant(NON_EXISTENT_UUID, COORD)
    validate_error(response, ApiErrorId.ERR_PARTICIPANT_NOT_FOUND.value, expected_status=404)
    assert response.json()["response_type"] == "error"


def test_participant_create_missing_weight_kg_returns_validation():
    """PRD §2.10 rung 22: "On every `POST`, `PATCH` and `PUT`, each field the
    endpoint declares required is present, carries the declared JSON type, and
    lies inside its declared numeric range — otherwise `ERR_VALIDATION` (400)."
    PRD §3.2: "An `IntakeCoordinator` opens a participant file with a
    `legal_name`, a `date_of_birth`, a `household_id` — an opaque grouping key
    that siblings share and that is not a foreign key to anything — a
    `household_size` of at least 1, an `income_band` from the same four-value
    enumeration the fee table uses, a `weight_kg` of at least 1 whole kilogram,
    a `mobility_profile` of `WHEELCHAIR` or `AMBULATORY`, and a
    `guardianship_status` of `SELF`, `GUARDIAN_REQUIRED` or `CONSERVATORSHIP`."

    Design: Corner/entities/participant_create_missing_required_field_returns_validation
    """
    create_fee_band()

    payload = participant_payload()
    payload.pop("weight_kg")
    validate_error(
        api_client.create_participant(payload, COORD),
        ApiErrorId.ERR_VALIDATION.value,
        expected_status=400,
    )

    _rows, meta = validate_paginated(api_client.list_participants(ADMIN))
    assert meta["total_count"] == 0, "A rejected create must write nothing"


def test_participant_create_ignores_client_supplied_status_and_version():
    """PRD §3.2: "The row is created in `status` `INTAKE` with
    `effective_support_tier` null and `version` 1."
    PRD §2.6: "`version` is an integer that starts at 1 on every newly created
    row and rises by exactly 1 each time that row is mutated."

    Design: Corner/entities/participant_create_system_fields_input_ignored
    """
    create_fee_band()

    data = validate_success(
        api_client.create_participant(
            participant_payload(status="ACTIVE", version=99), COORD
        ),
        expected_status=201,
    )
    assert data["status"] == "INTAKE", "the submitted ACTIVE must be ignored"
    assert data["version"] == 1, "the submitted 99 must be ignored"


def test_participant_cycles_active_inactive_active():
    """PRD §3.2: "An `ACTIVE` participant may be set `INACTIVE`, during which no
    enrolment may be created or confirmed for them; an `INACTIVE` participant
    may return to `ACTIVE`, again only when an active assessment exists — this
    re-entry is what makes the axis a loop."
    PRD §3.2: "Each move raises the participant's `version` by one."
    PRD §2.6: "Creating an enrolment or a staff assignment bumps the
    `ProgramSession`. Creating a support assessment bumps the `Participant`."

    Design: Corner/state_machines/participant_cycles_active_inactive_active
    """
    who = create_active_participant()
    participant_id = who["participant"]["id"]

    inactive = set_participant_status(participant_id, "INACTIVE")
    assert inactive["status"] == "INACTIVE"

    active_again = set_participant_status(participant_id, "ACTIVE")
    assert active_again["status"] == "ACTIVE"
    assert active_again["version"] == 6, (
        "create 1, assessment create 2, activation 3, ACTIVE 4, INACTIVE 5, ACTIVE 6; "
        f"got {active_again['version']}"
    )
    assert active_again["effective_support_tier"] == "INDEPENDENT"


def test_participant_exit_discontinues_goals_and_withdraws_future_enrollments():
    """PRD §3.2: "Hop 2, caused by hop 1, discontinues every goal of theirs whose
    `status` is `ACTIVE` or `MASTERED`, moving it to `DISCONTINUED`."
    PRD §3.2: "Hop 3, also caused by hop 1, withdraws every enrolment of theirs
    whose `enrollment_status` is `REQUESTED`, `WAITLISTED` or `CONFIRMED` **and**
    whose session starts strictly later than the logical clock, running the full
    withdrawal cascade A for each one"
    PRD §3.4: "Hop 2, caused by hop 1, unwinds everything that row was holding:
    `slots_committed` falls by one and `slots_available` rises by one"

    Design: Corner/state_machines/participant_exit_discontinues_goals_and_withdraws_future_enrollments
    """
    create_fee_band()
    _program, session = create_open_session(slot_capacity=2)
    who = create_active_participant()
    participant_id = who["participant"]["id"]
    goal = create_goal(participant_id, mastery_window_m=3, mastery_hits_n=2)
    enrollment = create_confirmed_enrollment(participant_id, session["id"])

    exited = set_participant_status(participant_id, "EXITED")
    assert exited["status"] == "EXITED"

    assert read_goal(goal["id"])["status"] == "DISCONTINUED"
    assert read_enrollment(enrollment["id"])["enrollment_status"] == "WITHDRAWN"

    after = read_session(session["id"])
    assert after["slots_committed"] == 0
    assert after["slots_available"] == 2
    assert_slot_conservation(after)
    assert charge_for(enrollment["id"])["status"] == "VOIDED"


def test_assessment_activation_supersedes_prior_row_and_reprices_staffing():
    """PRD §3.2: "Any other assessment of the same participant that was `ACTIVE`
    is moved to `SUPERSEDED`, which is terminal for that axis and reachable only
    this way — no client ever supersedes an assessment directly."
    PRD §3.2: "And every enrolment of that participant sitting on a session whose
    `status` is `DRAFT`, `OPEN` or `STAFFING_LOCKED` and whose `start_at` is at
    or after the new assessment's `effective_from` has its
    `effective_support_tier_at_session` recomputed, after which that session's
    `required_group_staff_planned`, `one_to_one_committed`,
    `one_to_one_available` and `staffing_gap` are all recomputed."
    PRD §3.5: "Filter that roster down to the **pooled** participants, meaning
    every enrolment on it whose effective tier at this session is anything other
    than `ONE_TO_ONE`."

    Design: Corner/state_machines/assessment_activation_supersedes_the_prior_row_and_reprices_staffing
    """
    create_fee_band()
    _program, session = create_open_session(
        program_overrides={"name": "Adaptive Climbing", "activity_type": "SPORTS",
                           "risk_tier": "HIGH"},
        slot_capacity=2,
        one_to_one_pool_size=1,
    )
    who = create_active_participant(support_tier="SUBSTANTIAL")
    participant_id = who["participant"]["id"]
    create_confirmed_enrollment(participant_id, session["id"])

    second = create_assessment(
        participant_id,
        assessed_on="2026-05-01",
        effective_from="2026-05-15T00:00:00Z",
        support_tier="ONE_TO_ONE",
    )
    activated = activate_assessment(second["id"])

    assert activated["status"] == "ACTIVE"
    prior = validate_success(api_client.get_support_assessment(who["assessment"]["id"], COORD))
    assert prior["status"] == "SUPERSEDED"
    assert read_participant(participant_id)["effective_support_tier"] == "ONE_TO_ONE"

    summary = staffing_summary(session["id"])
    assert summary["pooled_support_points"] == 0
    assert summary["required_group_staff_planned"] == 0
    assert summary["staffing_gap"] == 1

    after = read_session(session["id"])
    assert after["one_to_one_committed"] == 1
    assert after["one_to_one_available"] == 0


def test_clock_checkpoint_expires_a_signed_consent():
    """PRD §2.4: "First, consent expiry: every `ConsentArtifact` whose status is
    `SIGNED` and whose `expires_on` falls strictly before the new logical clock
    date moves to `EXPIRED`, and `consents_expired` counts those rows."
    PRD §3.2: "A successful signature moves the artifact from
    `PENDING_SIGNATURE` to `SIGNED`, stamps `signed_on` with the logical clock's
    calendar date, stamps `signer_role` with `SELF` or `LEGAL_GUARDIAN` per the
    rule above, and stamps `signed_by_caregiver_id` with the acting caregiver's
    id — or leaves it null when the accepted role was `SELF`."

    Design: Corner/state_machines/clock_checkpoint_expires_a_signed_consent
    """
    participant = create_participant()
    caregiver = create_caregiver(participant["id"])
    signed = create_signed_consent(
        participant["id"], caregiver["id"],
        consent_type="EMERGENCY_MEDICAL", expires_on="2026-05-15",
    )
    assert signed["status"] == "SIGNED"
    assert signed["signed_on"] == "2026-05-01"

    sweep = set_clock("2026-05-20T00:00:00Z")
    assert sweep["consents_expired"] == 1, (
        f"Expected consents_expired 1, got {sweep['consents_expired']}"
    )

    after = validate_success(api_client.get_consent(signed["id"], COORD))
    assert after["status"] == "EXPIRED"
    assert after["signed_by_caregiver_id"] == caregiver["id"]
    assert after["signer_role"] == "LEGAL_GUARDIAN"


def test_eligibility_read_reports_consent_blocked_for_the_nominated_session():
    """PRD §3.2: "The posture itself is the first of five branches that holds,
    tested in this order: `NOT_ACTIVE` when the participant's `status` is
    anything other than `ACTIVE`; otherwise `CONSENT_BLOCKED` when some required
    consent type has no artifact of this participant that is both `SIGNED` and
    carries an `expires_on` on or after the check date"
    PRD §3.2: "The three booleans report the individual gates independently of
    the posture: `consent_gate_ok` is false exactly when the consent branch would
    fire, `assessment_gate_ok` false exactly when the assessment branch would
    fire, and `financial_gate_ok` false exactly when the financial branch would
    fire; when no session is nominated, `consent_gate_ok` is true because no
    consent set applies."

    Design: Corner/calculations/eligibility_read_reports_consent_blocked_for_the_nominated_session
    """
    create_fee_band()
    _program, session = create_open_session(
        program_overrides={
            "name": "Adaptive Aquatics",
            "activity_type": "AQUATICS",
            "required_consent_types": ["EMERGENCY_MEDICAL"],
        },
    )
    who = create_active_participant()

    data = validate_success(
        api_client.get_participant_eligibility(
            who["participant"]["id"], COORD, params={"session_id": session["id"]}
        )
    )
    assert data["enrollment_posture"] == "CONSENT_BLOCKED"
    assert data["consent_gate_ok"] is False
    assert data["assessment_gate_ok"] is True
    assert data["financial_gate_ok"] is True
    assert data["effective_support_tier"] == "INDEPENDENT"
    assert data["age_years"] == 16


def test_confirm_rejects_a_consent_that_expires_before_the_session_date():
    """PRD §3.4: "**Sub-gate A (consent)** demands, for every consent type in the
    session's programme `required_consent_types`, an artifact of this participant
    with that type whose `status` is `SIGNED` — missing one is
    `ERR_REQUIRED_CONSENT_MISSING` — and then demands that each such artifact's
    `expires_on` falls on or after the session's calendar date, failing which it
    is `ERR_CONSENT_EXPIRED`."

    Design: Corner/validations/consent_rungs_reject_an_expired_artifact_and_an_unauthorised_signer
    """
    create_fee_band()
    _program, session = create_open_session(
        program_overrides={
            "name": "Adaptive Aquatics",
            "activity_type": "AQUATICS",
            "required_consent_types": ["EMERGENCY_MEDICAL"],
        },
        slot_capacity=4,
    )
    who = create_active_participant()
    participant_id = who["participant"]["id"]
    caregiver = create_caregiver(participant_id)
    signed = create_signed_consent(
        participant_id, caregiver["id"],
        consent_type="EMERGENCY_MEDICAL", expires_on="2026-06-01",
    )
    assert signed["status"] == "SIGNED", "the clock has not passed 2026-06-01"

    enrollment = request_enrollment(participant_id, session["id"])
    validate_error(
        api_client.confirm_enrollment(enrollment["id"], COORD, {}),
        ApiErrorId.ERR_CONSENT_EXPIRED.value,
        expected_status=422,
    )

    assert read_enrollment(enrollment["id"])["enrollment_status"] == "REQUESTED"
    assert read_session(session["id"])["slots_committed"] == 0


def test_medication_admin_consent_cannot_be_self_signed():
    """PRD §3.2: "If the artifact's `consent_type` is `MEDICATION_ADMIN`, the
    accepted signer role is `LEGAL_GUARDIAN` — a medication-administration
    consent is never self-signed, at any age, whatever the participant's
    guardianship status."
    PRD §3.2: "Any other combination — a self-signature attempted by a caregiver,
    a guardian signature with no caregiver named, a caregiver named who belongs
    to a different participant or who is not a legal guardian, a self-signature
    on a medication consent — is rejected with
    `ERR_CONSENT_SIGNER_NOT_AUTHORIZED` at rung 36."

    Design: Corner/validations/consent_rungs_reject_an_expired_artifact_and_an_unauthorised_signer
    """
    adult = create_participant(
        legal_name="Sam Adult",
        date_of_birth="2005-01-10",
        household_id="HH-5",
        household_size=2,
        weight_kg=70,
        guardianship_status="SELF",
    )
    consent = create_consent(
        adult["id"], consent_type="MEDICATION_ADMIN", expires_on="2026-12-31"
    )

    validate_error(
        api_client.sign_consent(consent["id"], {}, COORD),
        ApiErrorId.ERR_CONSENT_SIGNER_NOT_AUTHORIZED.value,
        expected_status=422,
    )

    after = validate_success(api_client.get_consent(consent["id"], COORD))
    assert after["status"] == "PENDING_SIGNATURE"
    assert after["signer_role"] is None


def test_stale_participant_version_rejects_the_superseding_assessment():
    """PRD §2.9: "Creating a support assessment
    (`POST /recreation/support-assessments`) must carry
    `expected_participant_version` matching the current `version` of the
    `Participant` named by `participant_id`."
    PRD §2.9: "If the echoed number is not equal to the parent's current
    `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412) and
    nothing is written."

    Design: Corner/cross_cutting_complexity_layers/stale_participant_version_rejects_the_superseding_assessment
    """
    participant = create_participant()
    stale_version = participant["version"]

    first = create_assessment(
        participant["id"], expected_participant_version=stale_version, support_tier="INDEPENDENT"
    )
    assert first["status"] == "DRAFT"

    validate_error(
        api_client.create_support_assessment(
            support_assessment_payload(
                participant["id"], stale_version,
                assessed_on="2026-04-15",
                effective_from="2026-04-15T00:00:00Z",
                support_tier="SUBSTANTIAL",
            ),
            COORD,
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
        expected_status=412,
    )

    retry = create_assessment(
        participant["id"],
        expected_participant_version=participant_version(participant["id"]),
        assessed_on="2026-04-15",
        effective_from="2026-04-15T00:00:00Z",
        support_tier="SUBSTANTIAL",
    )
    assert retry["support_tier"] == "SUBSTANTIAL"

    _rows, meta = validate_paginated(
        api_client.list_support_assessments(ADMIN, params={"participant_id": participant["id"]})
    )
    assert meta["total_count"] == 2
