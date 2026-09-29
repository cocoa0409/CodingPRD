"""One request, unchanged, refused or accepted purely on another entity's state."""

from test_helpers import (
    ERR_AUTHORIZATION_NOT_GRANTED,
    ERR_INCREASED_RISK_ACK_REQUIRED,
    ERR_POSTURE_RESTRICTED,
    RISK_TIER_INCREASED,
    candidate_sequence,
    chart_observation,
    cleared_referral,
    converted_case,
    create_case,
    create_hospital,
    create_referral,
    donor_case_payload,
    evaluate_organ,
    finalize_authorization,
    list_offers,
    observation_payload,
    offer_response_payload,
    open_match_run,
    open_registry_authorization,
    open_screening,
    organ_evaluation_payload,
    read_authorization,
    read_case,
    read_hospital,
    read_organ,
    read_referral,
    read_run,
    register_organ,
    respond_to_offer,
    rule_screening,
    submit_assessment,
    validate_error,
    validate_success,
)

CONVERSION_CLOCK = "2026-08-22T09:00:00Z"
EVALUATION_CLOCK = "2026-08-23T09:00:00Z"
ACCEPTANCE_CLOCK = "2026-08-24T09:00:00Z"


# ---------------------------------------------------------------------------
# DonorCase depends on Authorization state
# ---------------------------------------------------------------------------
def _cleared_referral_with_an_unfinalized_packet(env):
    bundle = cleared_referral(env, CONVERSION_CLOCK, patient_mrn="MRN-8601")
    bundle.authorization = open_registry_authorization(
        env, bundle.referral_id, registry_document_ref="REG-8601"
    )
    assert bundle.authorization["status"] == "REGISTRY_CONFIRMED"
    return bundle


def _conversion_body(bundle):
    return donor_case_payload(
        bundle.referral_id, bundle.authorization_id, donor_code="D-8601"
    )


def test_conversion_is_refused_while_the_packet_is_only_registry_confirmed(env):
    """A confirmed but unfinalized packet does not yet permit recovery.

    PRD 3.4: "The named authorization must be in `AUTHORIZED`, otherwise
    `ERR_AUTHORIZATION_NOT_GRANTED`."
    PRD 3.3: "The packet moves `PENDING_REGISTRY → REGISTRY_CONFIRMED`, its
    `authorization_basis` becomes `FIRST_PERSON_REGISTRY`".

    Design: Difficulty/cross_entity_state_dependency/donor_case_creation_gated_by_authorization_state
    """
    bundle = _cleared_referral_with_an_unfinalized_packet(env)

    refused = env.api.create_donor_case(_conversion_body(bundle), env.donor)
    validate_error(refused, ERR_AUTHORIZATION_NOT_GRANTED)

    assert read_referral(env, bundle.referral_id)["status"] == "AUTH_PENDING"


def test_the_identical_conversion_body_succeeds_once_the_packet_is_authorized(env):
    """Only the packet's state moved between the refusal and the acceptance.

    PRD 3.3: "Finalizing is accepted from `REGISTRY_CONFIRMED`, `NOK_CONSENTED`
    or `DOCUMENT_DEFICIENT`".
    PRD 3.4: "The new case starts with `physiologic_status` at `STABILIZING`,
    `allocation_status` at `NOT_STARTED` and `case_posture` at `OPEN`".

    Design: Difficulty/cross_entity_state_dependency/donor_case_creation_gated_by_authorization_state
    """
    bundle = _cleared_referral_with_an_unfinalized_packet(env)
    env.api.create_donor_case(_conversion_body(bundle), env.donor)

    finalized = finalize_authorization(env, bundle.authorization_id, as_user="auth-2")
    assert finalized["status"] == "AUTHORIZED"

    created = env.api.create_donor_case(_conversion_body(bundle), env.donor)
    case = validate_success(created, 201)
    assert case["case_posture"] == "OPEN"
    assert case["physiologic_status"] == "STABILIZING"
    assert case["allocation_status"] == "NOT_STARTED"


def test_conversion_advances_the_referral_and_the_hospital_counter(env):
    """The successful conversion is the one that moves the parent rows.

    PRD 3.4: "On success the referral advances `AUTH_PENDING → CONVERTED` and
    the hospital's `converted_donor_count` increases by one."

    Design: Difficulty/cross_entity_state_dependency/donor_case_creation_gated_by_authorization_state
    """
    bundle = _cleared_referral_with_an_unfinalized_packet(env)
    finalize_authorization(env, bundle.authorization_id, as_user="auth-2")

    validate_success(
        env.api.create_donor_case(_conversion_body(bundle), env.donor), 201
    )

    assert read_referral(env, bundle.referral_id)["status"] == "CONVERTED"
    assert read_hospital(env, bundle.hospital_id)["converted_donor_count"] == 1
    assert read_authorization(env, bundle.authorization_id)["status"] == "AUTHORIZED"


# ---------------------------------------------------------------------------
# Organ evaluation depends on DonorCase posture
# ---------------------------------------------------------------------------
def _restricted_case_with_two_unevaluated_organs(env):
    bundle = converted_case(
        env,
        EVALUATION_CLOCK,
        organ_types=["LUNG_LEFT", "PANCREAS"],
        patient_mrn="MRN-8701",
        cause_of_death_category="HEAD_TRAUMA",
    )
    chart_observation(
        env,
        bundle.case_id,
        observation_payload(
            "2026-08-23T08:35:00Z",
            map_mmhg=65,
            pao2_fio2_ratio=320,
            sodium=148,
            urine_output_ml_per_kg_hr=0.7,
            pressor_count=2,
        ),
    )
    chart_observation(
        env,
        bundle.case_id,
        observation_payload(
            "2026-08-23T08:45:00Z",
            map_mmhg=55,
            pao2_fio2_ratio=180,
            sodium=160,
            urine_output_ml_per_kg_hr=0.3,
            pressor_count=3,
        ),
    )
    case = read_case(env, bundle.case_id)
    assert case["case_posture"] == "RESTRICTED"
    assert case["viability_index"] == 20
    return bundle


def test_thoracic_evaluation_is_refused_while_the_case_is_restricted(env):
    """The lung cannot be ruled allocatable while the donor is decompensating.

    PRD 3.5: "Declaring an organ `ALLOCATABLE` additionally requires
    `viability_hold` to be false — a still-held organ yields
    `ERR_VIABILITY_HOLD_ACTIVE` — and requires the case's posture to be `OPEN`."

    Design: Difficulty/cross_entity_state_dependency/organ_evaluation_gated_by_donor_case_posture
    """
    bundle = _restricted_case_with_two_unevaluated_organs(env)

    refused = env.api.submit_organ_evaluation(
        bundle.organ_id("LUNG_LEFT"),
        organ_evaluation_payload("ALLOCATABLE"),
        env.director,
    )
    validate_error(refused, ERR_POSTURE_RESTRICTED)

    assert read_organ(env, bundle.organ_id("LUNG_LEFT"))["status"] == "PENDING_EVAL"


def test_abdominal_evaluation_passes_under_the_very_same_posture(env):
    """The pancreas on the identical case is untouched by the restriction.

    PRD 2.8: "`RESTRICTED` refuses organ evaluation and match-run generation for
    any organ whose `organ_type` is one of the three thoracic types — `HEART`,
    `LUNG_LEFT` or `LUNG_RIGHT` — with `ERR_POSTURE_RESTRICTED` (409 Conflict);
    abdominal organs proceed untouched."

    Design: Difficulty/cross_entity_state_dependency/organ_evaluation_gated_by_donor_case_posture
    """
    bundle = _restricted_case_with_two_unevaluated_organs(env)

    pancreas = evaluate_organ(env, bundle.organ_id("PANCREAS"), "ALLOCATABLE")
    assert pancreas["status"] == "ALLOCATABLE"
    assert read_case(env, bundle.case_id)["case_posture"] == "RESTRICTED"


def test_thoracic_evaluation_succeeds_once_a_recovery_reopens_the_posture(env):
    """A recovering observation reopens the case and the unchanged body is accepted.

    PRD 3.4: "A subsequent observation whose snapshot reaches at least 70 moves
    the case `DECOMPENSATING → OPTIMIZED` and returns `case_posture` from
    `RESTRICTED` to `OPEN`."
    PRD 3.4: "Every organ on the case whose `viability_hold` is true has that
    flag reset to false".

    Design: Difficulty/cross_entity_state_dependency/organ_evaluation_gated_by_donor_case_posture
    """
    bundle = _restricted_case_with_two_unevaluated_organs(env)
    env.api.submit_organ_evaluation(
        bundle.organ_id("LUNG_LEFT"),
        organ_evaluation_payload("ALLOCATABLE"),
        env.director,
    )

    recovering = chart_observation(
        env,
        bundle.case_id,
        observation_payload(
            "2026-08-23T08:55:00Z",
            map_mmhg=72,
            pao2_fio2_ratio=320,
            sodium=140,
            urine_output_ml_per_kg_hr=0.6,
            pressor_count=1,
        ),
    )
    assert recovering["viability_index_snapshot"] == 90

    case = read_case(env, bundle.case_id)
    assert case["physiologic_status"] == "OPTIMIZED"
    assert case["case_posture"] == "OPEN"

    lung = evaluate_organ(env, bundle.organ_id("LUNG_LEFT"), "ALLOCATABLE")
    assert lung["status"] == "ALLOCATABLE"
    assert lung["viability_hold"] is False


# ---------------------------------------------------------------------------
# Offer acceptance depends on the screening's risk tier, two entities away
# ---------------------------------------------------------------------------
def _increased_risk_kidney_with_one_pending_offer(env):
    env.set_clock(ACCEPTANCE_CLOCK)
    hospital = create_hospital(env, timely_referral_window_minutes=60)
    referral = create_referral(
        env,
        hospital["id"],
        "2026-08-24T08:30:00Z",
        patient_mrn="MRN-8801",
        age_years=29,
    )
    screening = open_screening(env, referral["id"])
    scored = submit_assessment(
        env,
        screening["id"],
        screening["version"],
        risk_factors=["IV_DRUG_USE_12MO"],
        informant_reliability="MEDICAL_RECORD_ONLY",
        unresolved_factors=[
            "INCARCERATION_72H_12MO",
            "NEW_SEX_PARTNER_HIGH_RISK_12MO",
            "HEMODIALYSIS_12MO",
        ],
    )
    assert float(scored["risk_score"]) == 15.28
    assert scored["risk_tier"] == RISK_TIER_INCREASED
    rule_screening(env, screening["id"], "CLEARED")

    authorization = open_registry_authorization(
        env, referral["id"], registry_document_ref="REG-8801"
    )
    finalize_authorization(env, authorization["id"], as_user="auth-2")
    case = create_case(
        env, referral["id"], authorization["id"], donor_code="D-8801"
    )
    organ = register_organ(env, case["id"], "KIDNEY_LEFT")
    evaluate_organ(env, organ["id"], "ALLOCATABLE")
    run = open_match_run(
        env, organ["id"], candidate_sequence(1, 120), primary_offer_slots=1
    )
    offer = list_offers(env, run["id"])[0]
    return case, organ, run, offer


def test_the_case_pins_the_increased_risk_tier_from_its_screening(env):
    """The tier travels from the screening onto the case at conversion.

    PRD 3.4: "`risk_tier_snapshot` is pinned from the screening's `risk_tier` at
    this moment, taking the value `STANDARD` or `INCREASED_RISK`, and never
    changes thereafter".

    Design: Difficulty/cross_entity_state_dependency/offer_acceptance_gated_by_screening_risk_tier
    """
    case, _organ, _run, _offer = _increased_risk_kidney_with_one_pending_offer(env)

    assert case["risk_tier_snapshot"] == RISK_TIER_INCREASED
    assert read_case(env, case["id"])["risk_tier_snapshot"] == RISK_TIER_INCREASED


def test_acceptance_without_the_acknowledgement_is_refused(env):
    """An increased-risk donor cannot be accepted silently.

    PRD 3.6: "when the donor case's `risk_tier_snapshot` is `INCREASED_RISK`,
    the accepting centre must have set `increased_risk_ack` to true, and omitting
    it yields `ERR_INCREASED_RISK_ACK_REQUIRED`; a `STANDARD` donor needs no
    acknowledgement".

    Design: Difficulty/cross_entity_state_dependency/offer_acceptance_gated_by_screening_risk_tier
    """
    _case, organ, run, offer = _increased_risk_kidney_with_one_pending_offer(env)

    refused = env.api.respond_to_offer(
        run["id"], offer["id"], offer_response_payload("ACCEPT"), env.alloc
    )
    validate_error(refused, ERR_INCREASED_RISK_ACK_REQUIRED)

    assert list_offers(env, run["id"])[0]["status"] == "PENDING"
    assert read_organ(env, organ["id"])["status"] == "OFFERING"


def test_the_acknowledged_acceptance_settles_offer_organ_run_and_case(env):
    """With the acknowledgement the same response places the organ.

    PRD 3.6: "On success the offer moves `PENDING → ACCEPTED`, the run's
    `pending_offer_count` decreases by one, the organ moves `OFFERING →
    ACCEPTED` with its `accepted_offer_id` set to the accepting offer, the run
    moves `OPEN → CLOSED` with `closed_reason` `ACCEPTED`".
    PRD 3.6: "The case's `allocation_status` advances `OFFERS_IN_FLIGHT →
    ALLOCATED` and its `organs_accepted_count` increases by one."

    Design: Difficulty/cross_entity_state_dependency/offer_acceptance_gated_by_screening_risk_tier
    """
    case, organ, run, offer = _increased_risk_kidney_with_one_pending_offer(env)

    accepted = respond_to_offer(
        env, run["id"], offer["id"], "ACCEPT", increased_risk_ack=True
    )
    assert accepted["status"] == "ACCEPTED"

    settled_organ = read_organ(env, organ["id"])
    assert settled_organ["status"] == "ACCEPTED"
    assert settled_organ["accepted_offer_id"] == offer["id"]

    settled_run = read_run(env, run["id"])
    assert settled_run["status"] == "CLOSED"
    assert settled_run["closed_reason"] == "ACCEPTED"

    settled_case = read_case(env, case["id"])
    assert settled_case["allocation_status"] == "ALLOCATED"
    assert settled_case["organs_accepted_count"] == 1
