"""Which of two live violations surfaces when the priority ladder is exercised."""
from test_helpers import (
    add_segment,
    advance_clock,
    clear_both_domains,
    create_active_recipient,
    create_chain,
    create_donor,
    determine_evaluation,
    get_chain,
    get_donor,
    get_recipient,
    get_segment,
    record_disclosure,
    setup_program_with_staff,
    submit_medical_evaluation,
    update_recipient_status,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId

MEDICAL_TEN_POINTS = {
    "bmi": 31.0,
    "egfr_ml_min": 84.0,
    "systolic_bp": 145,
    "hba1c": 6.0,
}
PSYCHOSOCIAL_FIVE_POINTS = {
    "financial_hardship_score": 8,
    "social_support_score": 2,
}


def _attest(env, donor_id):
    return validate_success(
        api_client.record_advocacy_determination(
            donor_id, {"outcome": "ATTESTED"}, env["advocate_headers"]
        )
    )


def test_second_attestation_reports_the_state_error_not_the_missing_clearance():
    """PRD §2.10: "The requested transition exists for the target's current state,
    and no transition at all is accepted out of a terminal state —
    `ERR_INVALID_STATE_TRANSITION`, 409."
    PRD §2.10: "Informed-consent safety — `ERR_COOLING_OFF_NOT_ELAPSED`,
    `ERR_CLEARANCE_INCOMPLETE` or `ERR_HARD_EXCLUSION_PRESENT`, 422."
    PRD §2.10: "Validation rules are evaluated strictly in ascending priority order,
    and the **first** rule violated determines the response. A request that breaks
    several rules always reports the lowest-numbered one."
    PRD §3.3: "Attestation is only reachable from `DISCLOSED`. It sets
    `attestation_at` to the current logical clock, computes `final_risk_index`, and
    derives the donor's `overall_status` into either `APPROVED` or
    `CONDITIONAL_APPROVED`."

    Design: Difficulty/priority_pair_validation_conflict/state_transition_precedes_clearance_safety_on_reattestation
    """
    env = setup_program_with_staff()
    recipient = create_active_recipient(env, mrn="R-001")
    donor = create_donor(env, intended_recipient_id=recipient["id"], mrn="D-001")
    clear_both_domains(env, donor["id"])
    record_disclosure(env, donor["id"])
    advance_clock(env, "2026-08-08T00:00:00Z")
    attested = _attest(env, donor["id"])
    assert attested["advocacy_status"] == "ATTESTED"
    assert attested["overall_status"] == "APPROVED"

    second_medical = submit_medical_evaluation(env, donor["id"])
    determine_evaluation(env, second_medical["id"], "DEFERRED", env["reviewer_med_headers"])
    regressed = get_donor(env, donor["id"])
    assert regressed["medical_status"] == "DEFERRED", (
        "a later determination may defer a domain that had already been cleared"
    )
    assert regressed["advocacy_status"] == "ATTESTED"

    response = api_client.record_advocacy_determination(
        donor["id"], {"outcome": "ATTESTED"}, env["advocate_headers"]
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)

    unchanged = get_donor(env, donor["id"])
    assert unchanged["advocacy_status"] == "ATTESTED"
    assert unchanged["attestation_at"].startswith("2026-08-08T00:00:00")
    assert unchanged["medical_status"] == "DEFERRED"
    assert unchanged["deferral_count"] == 1
    assert unchanged["overall_status"] == "EVAL_IN_PROGRESS"


def test_first_attestation_from_disclosed_reports_the_missing_clearance():
    """PRD §3.3: "Attesting requires that the current logical clock has reached
    `cooling_off_ends_at` — the boundary is inclusive, so exactly at that instant the
    attestation succeeds and one second earlier is refused with
    `ERR_COOLING_OFF_NOT_ELAPSED` — and that both `medical_status` and
    `psychosocial_status` are `CLEARED`, failing which the attestation is refused
    with `ERR_CLEARANCE_INCOMPLETE`."
    PRD §2.10: "Informed-consent safety — `ERR_COOLING_OFF_NOT_ELAPSED`,
    `ERR_CLEARANCE_INCOMPLETE` or `ERR_HARD_EXCLUSION_PRESENT`, 422."

    Design: Difficulty/priority_pair_validation_conflict/state_transition_precedes_clearance_safety_on_reattestation
    """
    env = setup_program_with_staff()
    recipient = create_active_recipient(env, mrn="R-001")
    donor = create_donor(env, intended_recipient_id=recipient["id"], mrn="D-001")
    medical = submit_medical_evaluation(env, donor["id"])
    determine_evaluation(env, medical["id"], "CLEARED", env["reviewer_med_headers"])
    disclosed = record_disclosure(env, donor["id"])
    assert disclosed["advocacy_status"] == "DISCLOSED"
    assert disclosed["psychosocial_status"] == "PENDING"
    advance_clock(env, "2026-08-08T00:00:00Z")

    response = api_client.record_advocacy_determination(
        donor["id"], {"outcome": "ATTESTED"}, env["advocate_headers"]
    )
    validate_error(response, ApiErrorId.ERR_CLEARANCE_INCOMPLETE.value)

    unchanged = get_donor(env, donor["id"])
    assert unchanged["advocacy_status"] == "DISCLOSED", (
        "the transition itself was legal, so the safety rule is the one that bites"
    )
    assert unchanged["attestation_at"] is None
    assert unchanged["final_risk_index"] is None


def test_chain_validation_reports_the_held_recipient_before_the_abo_defect():
    """PRD §3.5: "Every segment's recipient must have `listing_status` exactly
    `ACTIVE`, failing which the rejection is `ERR_RECIPIENT_NOT_ACTIVE`."
    PRD §2.10: "Participant eligibility — `ERR_DONOR_NOT_APPROVED`,
    `ERR_RECIPIENT_NOT_ACTIVE`, `ERR_DONOR_NOT_COMMITTED` or
    `ERR_DONOR_NOT_DONATED`, 422."
    PRD §2.10: "Chain topology — `ERR_CHAIN_TOO_SHORT`,
    `ERR_CHAIN_POSITIONS_NOT_CONTIGUOUS`, `ERR_CHAIN_LINKAGE_BROKEN`,
    `ERR_DUPLICATE_PARTICIPANT`, `ERR_ABO_INCOMPATIBLE`, `ERR_LOOP_NOT_CLOSED` or
    `ERR_NDD_START_INVALID`, 422."
    PRD §3.5: "A donor of type `A` may give to `A` or `AB`."

    Design: Difficulty/priority_pair_validation_conflict/participant_eligibility_precedes_topology_on_chain_validation
    """
    env = setup_program_with_staff()
    recipient_one = create_active_recipient(env, mrn="R-001", abo_blood_type="B")
    recipient_two = create_active_recipient(env, mrn="R-002", abo_blood_type="B")
    donor_one = create_donor(
        env, intended_recipient_id=recipient_one["id"], mrn="D-001", abo_blood_type="O"
    )
    donor_two = create_donor(env, mrn="D-002", abo_blood_type="A", age_years=38)
    clear_both_domains(env, donor_one["id"])
    clear_both_domains(env, donor_two["id"])
    record_disclosure(env, donor_one["id"])
    record_disclosure(env, donor_two["id"])
    advance_clock(env, "2026-08-15T00:00:00Z")
    assert _attest(env, donor_one["id"])["overall_status"] == "APPROVED"
    assert _attest(env, donor_two["id"])["overall_status"] == "APPROVED"

    held = update_recipient_status(
        env,
        recipient_one["id"],
        "INACTIVE_HOLD",
        "MEDICALLY_UNSUITABLE",
        "2026-08-15T00:00:00Z",
    )
    assert held["listing_status"] == "INACTIVE_HOLD"

    chain = create_chain(env, "PAIRED_LOOP")
    segment_one = add_segment(
        env, chain["id"], 1, donor_one["id"], recipient_two["id"]
    )
    segment_two = add_segment(
        env,
        chain["id"],
        2,
        donor_two["id"],
        recipient_one["id"],
        predecessor_segment_id=segment_one["id"],
    )

    response = api_client.validate_chain(chain["id"], env["coordinator_headers"])
    validate_error(response, ApiErrorId.ERR_RECIPIENT_NOT_ACTIVE.value)

    unchanged_chain = get_chain(env, chain["id"])
    assert unchanged_chain["status"] == "DRAFT"
    assert unchanged_chain["validated_at"] is None
    assert get_segment(env, segment_one["id"])["status"] == "PLANNED"
    assert get_segment(env, segment_two["id"])["status"] == "PLANNED"
    assert get_recipient(env, recipient_one["id"])["listing_status"] == "INACTIVE_HOLD"


def test_chain_validation_reports_the_conditional_donor_before_the_abo_defect():
    """PRD §3.5: "Every segment's donor must have `overall_status` exactly
    `APPROVED` — `CONDITIONAL_APPROVED` is explicitly not enough, and the rejection
    is `ERR_DONOR_NOT_APPROVED`."
    PRD §3.4: "The final index alone is compared against the ceiling of 8.0: a value
    at or above 8.0 yields `CONDITIONAL_APPROVED`, and a value below — 7.99 included
    — yields `APPROVED`."
    PRD §2.10: "Chain topology — `ERR_CHAIN_TOO_SHORT`,
    `ERR_CHAIN_POSITIONS_NOT_CONTIGUOUS`, `ERR_CHAIN_LINKAGE_BROKEN`,
    `ERR_DUPLICATE_PARTICIPANT`, `ERR_ABO_INCOMPATIBLE`, `ERR_LOOP_NOT_CLOSED` or
    `ERR_NDD_START_INVALID`, 422."

    Design: Difficulty/priority_pair_validation_conflict/participant_eligibility_precedes_topology_on_chain_validation
    """
    env = setup_program_with_staff()
    recipient_one = create_active_recipient(env, mrn="R-001", abo_blood_type="B")
    recipient_two = create_active_recipient(env, mrn="R-002", abo_blood_type="B")
    donor_one = create_donor(
        env, intended_recipient_id=recipient_one["id"], mrn="D-001", abo_blood_type="O"
    )
    donor_two = create_donor(env, mrn="D-002", abo_blood_type="A", age_years=62)
    clear_both_domains(env, donor_one["id"])
    clear_both_domains(
        env,
        donor_two["id"],
        medical=MEDICAL_TEN_POINTS,
        psychosocial=PSYCHOSOCIAL_FIVE_POINTS,
    )
    record_disclosure(env, donor_one["id"])
    record_disclosure(env, donor_two["id"])
    advance_clock(env, "2026-08-15T00:00:00Z")
    _attest(env, donor_one["id"])
    conditional = _attest(env, donor_two["id"])
    assert conditional["final_risk_index"] == 9.5, "5.0 + 2.5 plus the 2.0 non-directed surcharge"
    assert conditional["overall_status"] == "CONDITIONAL_APPROVED"

    chain = create_chain(env, "PAIRED_LOOP")
    segment_one = add_segment(env, chain["id"], 1, donor_one["id"], recipient_two["id"])
    add_segment(
        env,
        chain["id"],
        2,
        donor_two["id"],
        recipient_one["id"],
        predecessor_segment_id=segment_one["id"],
    )

    response = api_client.validate_chain(chain["id"], env["coordinator_headers"])
    validate_error(response, ApiErrorId.ERR_DONOR_NOT_APPROVED.value)

    unchanged_chain = get_chain(env, chain["id"])
    assert unchanged_chain["status"] == "DRAFT"
    assert unchanged_chain["validated_at"] is None
