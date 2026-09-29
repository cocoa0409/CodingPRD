"""Declared transitions, their side effects, and the refusals that guard them."""

from test_helpers import (
    AUTH_USER_1,
    DIRECTOR_USER,
    ERR_ALREADY_TERMINAL,
    ERR_OPERATION_NOT_SCHEDULED,
    ERR_REFERRAL_NOT_SCREENABLE,
    ERR_RISK_ASSESSMENT_MISSING,
    ERR_SCREENING_NOT_PENDING,
    accepted_organ,
    assert_instant_equals,
    assert_slot_conservation,
    assert_team_ledger,
    assert_two_decimal_value,
    book_operation,
    cancel_operation,
    candidate_sequence,
    cleared_referral,
    converted_case,
    create_team,
    cross_clamp,
    evaluate_organ,
    find_offer,
    get_success_data,
    list_offers,
    list_serology,
    offering_organ,
    open_match_run,
    open_nok_authorization,
    open_screening,
    read_authorization,
    read_case,
    read_hospital,
    read_operation,
    read_organ,
    read_referral,
    read_run,
    read_screening,
    read_team,
    received_referral,
    record_disposition,
    record_nok_contact,
    respond_to_offer,
    rule_screening,
    screened_referral,
    screening_decision_payload,
    serology_result_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-09-03T08:00:00Z"
ALLOCATION_CLOCK = "2026-09-03T09:00:00Z"
THEATRE_CLOCK = "2026-09-03T07:00:00Z"


# ---------------------------------------------------------------------------
# EligibilityScreening: initial state, the clearance side effect, the guards
# ---------------------------------------------------------------------------
def test_new_screening_starts_pending_with_zero_info_requests(env):
    """Opening screening mints a blank row and moves the referral in one request.

    PRD 3.2: "the referral advances `RECEIVED → SCREENING` and a new
    `EligibilityScreening` is created in status `PENDING` with
    `info_request_count` at zero, carrying the `referral_id` of the referral it
    screens".

    Design: Corner/state_machines/new_screening_starts_pending_with_zero_info_requests
    """
    bundle = received_referral(env, CLOCK, patient_mrn="MRN-2001", age_years=40,
                              gcs_score=3)

    screening = validate_success(
        env.api.create_screening(bundle.referral_id, env.coordinator), 201
    )

    assert screening["status"] == "PENDING"
    assert screening["version"] == 1
    assert screening["info_request_count"] == 0
    assert screening["risk_score"] is None
    assert screening["risk_tier"] is None
    assert screening["absolute_contraindication"] is False
    assert screening["risk_variant_applied"] is None
    assert screening["risk_assessed_by_user_id"] is None
    assert screening["referral_id"] == bundle.referral_id

    assert read_referral(env, bundle.referral_id)["status"] == "SCREENING"


def test_clearing_the_screening_propagates_the_referral_to_screen_cleared(env):
    """The director's clearance walks the parent referral in the same request.

    PRD 3.2: "A clearance moves the screening `PENDING → CLEARED` and propagates
    the referral `SCREENING → SCREEN_CLEARED`".
    PRD 3.2: "On success the ruling operator is recorded in `decided_by_user_id`."
    PRD 3.2: "the unresolved factors are ignored entirely and
    `risk_variant_applied` is set to `INTERVIEW_BASED`".

    Design: Corner/state_machines/clearing_the_screening_propagates_the_referral_to_screen_cleared
    """
    bundle = screened_referral(
        env,
        CLOCK,
        risk_factors=["HEMODIALYSIS_12MO"],
        informant_reliability="PRIMARY_NEXT_OF_KIN",
        patient_mrn="MRN-2101",
    )
    assert_two_decimal_value(bundle.screening["risk_score"], 2.50)
    assert bundle.screening["risk_variant_applied"] == "INTERVIEW_BASED"
    assert bundle.screening["version"] == 2

    cleared = rule_screening(env, bundle.screening_id, "CLEARED")

    assert cleared["status"] == "CLEARED"
    assert cleared["decided_by_user_id"] == DIRECTOR_USER
    assert cleared["ruled_out_reason"] is None
    assert read_referral(env, bundle.referral_id)["status"] == "SCREEN_CLEARED"


def test_second_screening_on_the_same_referral_is_rejected(env):
    """The RECEIVED to SCREENING step is one-shot, and no duplicate row appears.

    PRD 3.2: "If the referral is in any other status, or a screening already
    exists for it, the attempt is rejected with `ERR_REFERRAL_NOT_SCREENABLE`."
    PRD 3.2: "The screening may be reached either by its own identifier or by
    reverse lookup from the referral, which returns an array of length zero or
    one."

    Design: Corner/state_machines/second_screening_on_the_same_referral_is_rejected
    """
    bundle = received_referral(env, CLOCK, patient_mrn="MRN-2201")
    bundle.screening = open_screening(env, bundle.referral_id)

    validate_error(
        env.api.create_screening(bundle.referral_id, env.coordinator),
        ERR_REFERRAL_NOT_SCREENABLE,
        409,
    )

    rows, meta = validate_paginated(
        env.api.list_screenings_for_referral(bundle.referral_id, env.coordinator)
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [bundle.screening_id]
    assert read_referral(env, bundle.referral_id)["status"] == "SCREENING"


def test_request_info_on_an_info_requested_screening_is_rejected(env):
    """A second bounce does not stack, and the rejected call spends no budget.

    PRD 3.2: "The screening moves `PENDING → INFO_REQUESTED` and its
    `info_request_count` increases by one."
    PRD 2.10: "10. **Screening action status** — `ERR_SCREENING_NOT_PENDING`, on
    `POST /opo/eligibility-screenings/{id}/risk-assessment`, `POST
    /opo/eligibility-screenings/{id}/request-info` and `POST
    /opo/eligibility-screenings/{id}/decision`."

    Design: Corner/state_machines/request_info_on_an_info_requested_screening_is_rejected
    """
    bundle = screened_referral(
        env,
        CLOCK,
        risk_factors=["TATTOO_UNREGULATED_12MO"],
        informant_reliability="SECONDARY_CONTACT",
        patient_mrn="MRN-2301",
    )

    bounced = get_success_data(
        env.api.request_info(
            bundle.screening_id,
            env.director,
            {"info_request_note": "Confirm tattoo timing with the sister."},
        )
    )
    assert bounced["status"] == "INFO_REQUESTED"
    assert bounced["info_request_count"] == 1

    validate_error(
        env.api.request_info(
            bundle.screening_id, env.director, {"info_request_note": "Still waiting."}
        ),
        ERR_SCREENING_NOT_PENDING,
        409,
    )

    screening = read_screening(env, bundle.screening_id)
    assert screening["info_request_count"] == 1
    assert screening["status"] == "INFO_REQUESTED"


def test_decision_before_any_risk_assessment_is_rejected(env):
    """State and role are both right; the missing score alone stops the ruling.

    PRD 3.2: "It requires that `risk_score` be non-null — that is, that an
    assessment has actually been submitted — and otherwise fails with
    `ERR_RISK_ASSESSMENT_MISSING`."

    Design: Corner/state_machines/decision_before_any_risk_assessment_is_rejected
    """
    bundle = received_referral(env, CLOCK, patient_mrn="MRN-2401")
    bundle.screening = open_screening(env, bundle.referral_id)

    validate_error(
        env.api.submit_screening_decision(
            bundle.screening_id, screening_decision_payload("CLEARED"), env.director
        ),
        ERR_RISK_ASSESSMENT_MISSING,
        409,
    )

    screening = read_screening(env, bundle.screening_id)
    assert screening["status"] == "PENDING"
    assert screening["decided_by_user_id"] is None
    assert read_referral(env, bundle.referral_id)["status"] == "SCREENING"


def test_serology_on_a_ruled_out_screening_returns_already_terminal(env):
    """A late laboratory result on a ruled-out screening is refused outright.

    PRD 3.2: "A screening in `RULED_OUT` is the one terminal state that does
    refuse further results, with `ERR_ALREADY_TERMINAL`, since no further clinical
    decision can turn on them."
    PRD 3.2: "a rule-out moves the screening `PENDING → RULED_OUT` and propagates
    the referral `SCREENING → RULED_OUT`".

    Design: Corner/state_machines/serology_on_a_ruled_out_screening_returns_already_terminal
    """
    bundle = screened_referral(
        env,
        CLOCK,
        risk_factors=["BLOOD_TRANSFUSION_12MO"],
        patient_mrn="MRN-2501",
        age_years=82,
    )
    ruled = rule_screening(
        env, bundle.screening_id, "RULED_OUT", ruled_out_reason="AGE_CRITERIA"
    )
    assert ruled["status"] == "RULED_OUT"
    assert ruled["ruled_out_reason"] == "AGE_CRITERIA"

    validate_error(
        env.api.file_serology_result(
            bundle.screening_id,
            serology_result_payload(
                "HIV_NAT", "POSITIVE", "2026-09-03T07:55:00Z", nat_confirmed=True
            ),
            env.lab,
        ),
        ERR_ALREADY_TERMINAL,
        409,
    )

    assert list_serology(env, bundle.screening_id) == []
    assert read_screening(env, bundle.screening_id)["absolute_contraindication"] is False
    assert read_referral(env, bundle.referral_id)["status"] == "RULED_OUT"


# ---------------------------------------------------------------------------
# RecoveryOperation: the compensating cancel is not idempotent
# ---------------------------------------------------------------------------
def _liver_case_with_a_cancelled_theatre(env):
    bundle = accepted_organ(
        env, "LIVER", THEATRE_CLOCK, candidate_count=1, primary_offer_slots=1
    )
    bundle.team = create_team(
        env, team_code="ABD-7", specialty="ABDOMINAL", turnaround_buffer_minutes=60
    )
    bundle.operation = book_operation(
        env,
        bundle.case_id,
        bundle.team["id"],
        "2026-09-03T08:00:00Z",
        "2026-09-03T11:00:00Z",
    )
    bundle.operation = cancel_operation(env, bundle.operation["id"])
    return bundle


def test_cancelling_an_already_cancelled_operation_is_rejected(env):
    """The status guard answers before the terminal guard, and the ledger moves once.

    PRD 3.7: "Cancelling requires the operation to be in `SCHEDULED`; it moves
    `SCHEDULED → CANCELLED` with `cancelled_reason` `LOGISTICS_WITHDRAWN`,
    decreases the team's `booked_or_minutes` by that operation's `or_minutes`, and
    decreases its `scheduled_operation_count` by one."
    PRD 2.10: "20. **Operation, run and disposition status** —
    `ERR_OPERATION_NOT_SCHEDULED` on `POST
    /opo/recovery-operations/{id}/cross-clamp` and `POST
    /opo/recovery-operations/{id}/cancel`".

    Design: Corner/state_machines/cancelling_an_already_cancelled_operation_is_rejected
    """
    bundle = _liver_case_with_a_cancelled_theatre(env)
    assert bundle.operation["status"] == "CANCELLED"
    assert bundle.operation["cancelled_reason"] == "LOGISTICS_WITHDRAWN"

    validate_error(
        env.api.cancel_recovery_operation(bundle.operation["id"], env.logistics),
        ERR_OPERATION_NOT_SCHEDULED,
        409,
    )

    assert_team_ledger(read_team(env, bundle.team["id"]), 0, 0)
    assert read_organ(env, bundle.only_organ_id)["status"] == "ACCEPTED"
    assert read_case(env, bundle.case_id)["allocation_status"] == "ALLOCATED"


# ---------------------------------------------------------------------------
# Authorization: the two terminal branches of the next-of-kin fork
# ---------------------------------------------------------------------------
def test_rank_one_decline_declines_the_packet_and_stops_the_referral(env):
    """A spouse's refusal ends the packet and the referral together.

    PRD 3.3: "A `DECLINE` **from rank 1** ends the packet: it moves `NOK_REQUIRED
    → DECLINED`, which is terminal, and propagates the referral `AUTH_PENDING →
    NOT_CONVERTED`, also terminal."
    PRD 3.3: "the packet moves `PENDING_REGISTRY → NOK_REQUIRED`, its
    `authorization_basis` becomes `LEGAL_NEXT_OF_KIN`, its
    `required_document_types` becomes the two-member list containing
    `SIGNED_CONSENT_FORM` and `WITNESS_ATTESTATION`".
    PRD 3.3: "It also stamps `contacted_at` from the logical clock and records the
    acting specialist in `recorded_by_user_id`."

    Design: Corner/state_machines/rank_one_decline_declines_the_packet_and_stops_the_referral
    """
    bundle = cleared_referral(env, CLOCK, patient_mrn="MRN-2701")
    bundle.authorization = open_nok_authorization(env, bundle.referral_id)
    assert bundle.authorization["status"] == "NOK_REQUIRED"
    assert bundle.authorization["authorization_basis"] == "LEGAL_NEXT_OF_KIN"
    assert bundle.authorization["required_document_types"] == [
        "SIGNED_CONSENT_FORM",
        "WITNESS_ATTESTATION",
    ]

    contact = record_nok_contact(
        env,
        bundle.authorization_id,
        "SPOUSE",
        "DECLINE",
        contact_note="Family declines donation.",
    )
    assert contact["rank"] == 1
    assert_instant_equals(contact["contacted_at"], CLOCK)
    assert contact["recorded_by_user_id"] == AUTH_USER_1

    packet = read_authorization(env, bundle.authorization_id)
    assert packet["status"] == "DECLINED"
    assert packet["consenting_rank"] is None
    assert read_referral(env, bundle.referral_id)["status"] == "NOT_CONVERTED"
    assert read_hospital(env, bundle.hospital_id)["converted_donor_count"] == 0


def test_every_rank_unreachable_ends_in_unable_to_locate(env):
    """Five unreachable classes are not enough; the sixth exhausts the hierarchy.

    PRD 3.3: "An `UNREACHABLE` that leaves every one of the six relationship
    classes with a contact row on this packet, none of them a `CONSENT`, exhausts
    the hierarchy: the packet moves `NOK_REQUIRED → UNABLE_TO_LOCATE`, which is
    terminal, and the referral moves `AUTH_PENDING → NOT_CONVERTED`."
    PRD 3.3: "The packet's `highest_rank_attempted` — the numerically lowest rank
    for which a contact row exists, updated as the smaller of its current value
    and the new contact's rank — is a reporting field only".

    Design: Corner/state_machines/every_rank_unreachable_ends_in_unable_to_locate
    """
    bundle = cleared_referral(env, CLOCK, patient_mrn="MRN-2801")
    bundle.authorization = open_nok_authorization(env, bundle.referral_id)
    for relationship in ("SPOUSE", "ADULT_CHILD", "PARENT", "SIBLING", "GRANDPARENT"):
        record_nok_contact(
            env, bundle.authorization_id, relationship, "UNREACHABLE"
        )

    after_five = read_authorization(env, bundle.authorization_id)
    assert after_five["status"] == "NOK_REQUIRED"
    assert after_five["highest_rank_attempted"] == 1

    last = record_nok_contact(
        env, bundle.authorization_id, "LEGAL_GUARDIAN", "UNREACHABLE"
    )
    assert last["rank"] == 6

    packet = read_authorization(env, bundle.authorization_id)
    assert packet["status"] == "UNABLE_TO_LOCATE"
    assert packet["consenting_rank"] is None
    assert packet["documentation_complete"] is False
    assert read_referral(env, bundle.referral_id)["status"] == "NOT_CONVERTED"

    rows, meta = validate_paginated(
        env.api.list_nok_contacts(bundle.authorization_id, env.auth_one)
    )
    assert meta["total_count"] == 6
    assert rows[0]["rank"] == 1


# ---------------------------------------------------------------------------
# OrganOffer and MatchRun: promotion after a decline, and supersede
# ---------------------------------------------------------------------------
def test_decline_promotes_the_next_queued_candidate(env):
    """The declining response runs the selector inside the very same request.

    PRD 3.6: "The offer moves `PENDING → DECLINED`, which is terminal for the
    offer, the run's `pending_offer_count` decreases by one and its `slots_free`
    increases by one, and the promotion selector immediately re-runs on that run,
    promoting the next queued candidate if one exists."
    PRD 3.6: "its status set to `PENDING`, its `offered_at` stamped from the
    logical clock, its `expires_at` set to that instant plus its own
    `acceptance_clock_minutes`".

    Design: Corner/state_machines/decline_promotes_the_next_queued_candidate
    """
    bundle = offering_organ(
        env,
        "LIVER",
        ALLOCATION_CLOCK,
        candidate_count=2,
        primary_offer_slots=1,
        acceptance_clock_minutes=120,
    )
    assert find_offer(bundle.offers, 2)["status"] == "QUEUED"

    env.set_clock("2026-09-03T09:30:00Z")
    declined = respond_to_offer(
        env,
        bundle.run_id,
        find_offer(bundle.offers, 1)["id"],
        "DECLINE",
        decline_reason="SIZE_MISMATCH",
    )
    assert declined["status"] == "DECLINED"
    assert declined["decline_reason"] == "SIZE_MISMATCH"
    assert_instant_equals(declined["responded_at"], "2026-09-03T09:30:00Z")

    promoted = find_offer(list_offers(env, bundle.run_id), 2)
    assert promoted["status"] == "PENDING"
    assert_instant_equals(promoted["offered_at"], "2026-09-03T09:30:00Z")
    assert_instant_equals(promoted["expires_at"], "2026-09-03T11:30:00Z")

    run = read_run(env, bundle.run_id)
    assert run["status"] == "OPEN"
    assert run["pending_offer_count"] == 1
    assert run["slots_free"] == 0
    assert_slot_conservation(run)

    assert read_organ(env, bundle.only_organ_id)["status"] == "OFFERING"
    assert read_case(env, bundle.case_id)["allocation_status"] == "OFFERS_IN_FLIGHT"


def test_a_later_run_supersedes_the_previous_run_and_bypasses_its_offers(env):
    """Re-listing the organ is legal, and the older run drains without an error.

    PRD 3.5: "If the organ already had a run in `OPEN`, that prior run moves `OPEN
    → SUPERSEDED` with `closed_reason` `SUPERSEDED_BY_NEW_RUN`, and its offers in
    `QUEUED` or `PENDING` move to `BYPASSED`; note carefully that a superseded
    run's bypassed offers take `bypass_reason` **null**".
    PRD 3.5: "assigns `run_number` as one more than the highest existing run
    number on that organ — so the first run on an organ is number 1".

    Design: Corner/state_machines/a_later_run_supersedes_the_previous_run_and_bypasses_its_offers
    """
    bundle = offering_organ(
        env,
        "KIDNEY_LEFT",
        ALLOCATION_CLOCK,
        candidate_count=1,
        primary_offer_slots=1,
        acceptance_clock_minutes=120,
    )
    first_run_id = bundle.run_id
    assert bundle.run["run_number"] == 1
    before = read_organ(env, bundle.only_organ_id)
    assert before["status"] == "OFFERING"

    second_run = open_match_run(
        env,
        bundle.only_organ_id,
        candidate_sequence(1, 120),
        primary_offer_slots=1,
    )

    assert second_run["run_number"] == 2
    assert second_run["pending_offer_count"] == 1
    assert read_organ(env, bundle.only_organ_id)["version"] == before["version"] + 1

    superseded = read_run(env, first_run_id)
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["closed_reason"] == "SUPERSEDED_BY_NEW_RUN"
    assert superseded["pending_offer_count"] == 0
    assert superseded["slots_free"] == 1
    assert_slot_conservation(superseded)

    stale_offer = list_offers(env, first_run_id)[0]
    assert stale_offer["status"] == "BYPASSED"
    assert stale_offer["bypass_reason"] is None
    assert stale_offer["responded_at"] is None

    assert read_organ(env, bundle.only_organ_id)["status"] == "OFFERING"
    assert read_case(env, bundle.case_id)["allocation_status"] == "OFFERS_IN_FLIGHT"


# ---------------------------------------------------------------------------
# Cross-clamp, and the disposition that closes the case
# ---------------------------------------------------------------------------
def _liver_case_recovered_at_eight_fifteen(env):
    bundle = accepted_organ(
        env, "LIVER", THEATRE_CLOCK, candidate_count=1, primary_offer_slots=1
    )
    bundle.team = create_team(
        env, team_code="ABD-8", specialty="ABDOMINAL", turnaround_buffer_minutes=60
    )
    bundle.operation = book_operation(
        env,
        bundle.case_id,
        bundle.team["id"],
        "2026-09-03T08:00:00Z",
        "2026-09-03T11:00:00Z",
    )
    assert bundle.operation["organ_types_covered"] == ["LIVER"]
    assert bundle.operation["or_minutes"] == 180

    env.set_clock("2026-09-03T08:15:00Z")
    bundle.operation = cross_clamp(env, bundle.operation["id"])
    return bundle


def test_cross_clamp_recovers_the_accepted_organ_and_completes_the_operation(env):
    """One trigger completes the operation, recovers the organ and moves the case.

    PRD 3.7: "The operation moves `SCHEDULED → COMPLETED`, its `cross_clamp_at`
    stamped from the logical clock, and the team's `scheduled_operation_count`
    decreases by one while its `booked_or_minutes` stays **unchanged** — a
    completed window remains on the ledger, because the theatre time was genuinely
    consumed."
    PRD 3.7: "Every organ of the case in status `ACCEPTED` moves to `RECOVERED`
    with the operation's `cross_clamp_at` copied onto it, and the case's
    `organs_recovered_count` is refreshed, counting organs whose status is
    `RECOVERED`, `TRANSPLANTED` or `DISCARDED`. The case's `allocation_status`
    advances `ALLOCATED → RECOVERED`."

    Design: Corner/state_machines/cross_clamp_recovers_the_accepted_organ_and_completes_the_operation
    """
    bundle = _liver_case_recovered_at_eight_fifteen(env)

    assert bundle.operation["status"] == "COMPLETED"
    assert_instant_equals(bundle.operation["cross_clamp_at"], "2026-09-03T08:15:00Z")

    organ = read_organ(env, bundle.only_organ_id)
    assert organ["status"] == "RECOVERED"
    assert_instant_equals(organ["cross_clamp_at"], "2026-09-03T08:15:00Z")

    case = read_case(env, bundle.case_id)
    assert case["allocation_status"] == "RECOVERED"
    assert case["organs_recovered_count"] == 1
    assert case["case_posture"] == "OPEN"

    assert_team_ledger(read_team(env, bundle.team["id"]), 180, 0)


def test_last_disposition_closes_the_donor_case(env):
    """The parent closes only when its final child reaches a terminal state.

    PRD 3.8: "When a disposition leaves **every** organ of the case in one of its
    terminal states — `TRANSPLANTED`, `DISCARDED`, `RESEARCH_REFERRED` or
    `TISSUE_REFERRED` — the case's `allocation_status` advances `RECOVERED →
    CLOSED` with `closed_reason` `RECOVERY_COMPLETE`, and `case_posture` becomes
    `FROZEN`."
    PRD 3.8: "An organ in `RECOVERED` may be dispositioned `TRANSPLANTED` or
    `DISCARDED`."

    Design: Corner/state_machines/last_disposition_closes_the_donor_case
    """
    bundle = _liver_case_recovered_at_eight_fifteen(env)
    env.set_clock(ALLOCATION_CLOCK)

    transplanted = record_disposition(env, bundle.only_organ_id, "TRANSPLANTED")
    assert transplanted["status"] == "TRANSPLANTED"

    case = read_case(env, bundle.case_id)
    assert case["allocation_status"] == "CLOSED"
    assert case["closed_reason"] == "RECOVERY_COMPLETE"
    assert case["case_posture"] == "FROZEN"
    assert case["physiologic_status"] == "STABILIZING"
    assert case["organs_recovered_count"] == 1
    assert case["organs_nontransplantable_count"] == 0
    assert read_operation(env, bundle.operation["id"])["status"] == "COMPLETED"


def test_non_transplantable_organs_are_referred_to_research_and_tissue(env):
    """The two referral arms each demand and store their own code.

    PRD 3.8: "An organ in `NON_TRANSPLANTABLE` may be referred onward:
    `RESEARCH_REFERRED` requires a non-null `research_protocol_code`, which is
    stored on the organ, and `TISSUE_REFERRED` requires a non-null
    `tissue_processor_code`, likewise stored."
    PRD 3.8: "The case's `organs_recovered_count` and
    `organs_nontransplantable_count` are refreshed after every disposition, the
    former counting organs in `RECOVERED`, `TRANSPLANTED` or `DISCARDED` and the
    latter counting organs in `NON_TRANSPLANTABLE`, `RESEARCH_REFERRED` or
    `TISSUE_REFERRED`."

    Design: Corner/state_machines/non_transplantable_organs_are_referred_to_research_and_tissue
    """
    bundle = converted_case(
        env,
        ALLOCATION_CLOCK,
        organ_types=["PANCREAS", "INTESTINE"],
        patient_mrn="MRN-3301",
    )
    pancreas = evaluate_organ(
        env,
        bundle.organ_id("PANCREAS"),
        "NON_TRANSPLANTABLE",
        nontransplantable_reason="ANATOMIC_ANOMALY",
    )
    assert pancreas["status"] == "NON_TRANSPLANTABLE"
    assert pancreas["nontransplantable_reason"] == "ANATOMIC_ANOMALY"
    evaluate_organ(
        env,
        bundle.organ_id("INTESTINE"),
        "NON_TRANSPLANTABLE",
        nontransplantable_reason="ANATOMIC_ANOMALY",
    )

    referred = record_disposition(
        env,
        bundle.organ_id("PANCREAS"),
        "RESEARCH_REFERRED",
        research_protocol_code="IRB-4471",
    )
    assert referred["status"] == "RESEARCH_REFERRED"
    assert referred["research_protocol_code"] == "IRB-4471"

    banked = record_disposition(
        env,
        bundle.organ_id("INTESTINE"),
        "TISSUE_REFERRED",
        tissue_processor_code="TP-88",
    )
    assert banked["status"] == "TISSUE_REFERRED"
    assert banked["tissue_processor_code"] == "TP-88"

    case = read_case(env, bundle.case_id)
    assert case["organs_nontransplantable_count"] == 2
    assert case["organs_recovered_count"] == 0
    assert case["allocation_status"] == "NOT_STARTED"
    assert case["case_posture"] == "OPEN"
