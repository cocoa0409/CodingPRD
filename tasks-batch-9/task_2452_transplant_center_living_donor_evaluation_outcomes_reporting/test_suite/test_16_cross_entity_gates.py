"""Writes refused because of another entity's state: a sibling row and a parent posture."""
from test_helpers import (
    advance_clock,
    build_paired_loop_chain,
    create_donor,
    create_outcome_review,
    determine_evaluation,
    file_improvement_plan,
    finalize_review,
    get_chain,
    get_donor,
    record_disclosure,
    refresh_program,
    setup_paired_loop_participants,
    setup_program_with_staff,
    submit_medical_evaluation,
    submit_psychosocial_evaluation,
    transition_improvement_plan,
    validate_chain,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId

NINE_CLEAN_FINDINGS = {
    "bmi": 24.0,
    "egfr_ml_min": 100.0,
    "systolic_bp": 118,
    "hba1c": 5.0,
    "coercion_flag": False,
    "unmanaged_substance_use": False,
    "decisional_capacity_ok": True,
    "financial_hardship_score": 1,
    "social_support_score": 9,
}


def _attest(env, donor_id):
    return api_client.record_advocacy_determination(
        donor_id, {"outcome": "ATTESTED"}, env["advocate_headers"]
    )


def _setup_donor_with_deferred_psychosocial():
    env = setup_program_with_staff()
    donor = create_donor(env, mrn="D-001", age_years=41)
    medical = submit_medical_evaluation(env, donor["id"])
    determine_evaluation(env, medical["id"], "CLEARED", env["reviewer_med_headers"])
    psychosocial = submit_psychosocial_evaluation(env, donor["id"])
    determine_evaluation(env, psychosocial["id"], "DEFERRED", env["reviewer_psy_headers"])
    disclosed = record_disclosure(env, donor["id"])
    assert disclosed["cooling_off_ends_at"].startswith("2026-08-15T00:00:00")
    advance_clock(env, "2026-08-15T00:00:00Z")
    env["donor"] = donor
    env["psychosocial_evaluation"] = psychosocial
    return env


def test_attestation_is_refused_while_a_sibling_evaluation_row_is_deferred():
    """PRD §3.3: "Attesting requires that the current logical clock has reached
    `cooling_off_ends_at` — the boundary is inclusive, so exactly at that instant the
    attestation succeeds and one second earlier is refused with
    `ERR_COOLING_OFF_NOT_ELAPSED` — and that both `medical_status` and
    `psychosocial_status` are `CLEARED`, failing which the attestation is refused with
    `ERR_CLEARANCE_INCOMPLETE`."
    PRD §3.4: "A `DEFERRED` determination sets that donor dimension to `DEFERRED`,
    increments the donor's `deferral_count` by 1, and recomputes
    `screening_risk_index`; `deferral_count` is cumulative and is never decremented,
    which is what makes a history of deferrals permanently visible in the final
    index."

    Design: Difficulty/cross_entity_state_dependency/attestation_blocked_by_deferred_donor_evaluation
    """
    env = _setup_donor_with_deferred_psychosocial()
    donor_id = env["donor"]["id"]

    validate_error(_attest(env, donor_id), ApiErrorId.ERR_CLEARANCE_INCOMPLETE.value)

    unchanged = get_donor(env, donor_id)
    assert unchanged["advocacy_status"] == "DISCLOSED"
    assert unchanged["medical_status"] == "CLEARED"
    assert unchanged["psychosocial_status"] == "DEFERRED"
    assert unchanged["attestation_at"] is None
    assert unchanged["final_risk_index"] is None
    assert unchanged["overall_status"] == "EVAL_IN_PROGRESS"

    blocking_row = validate_success(
        api_client.get_donor_evaluation(
            env["psychosocial_evaluation"]["id"], env["reviewer_psy_headers"]
        )
    )
    assert blocking_row["status"] == "DEFERRED", "the blocking sibling row is untouched"


def test_attestation_succeeds_once_the_sibling_row_is_resubmitted_and_cleared():
    """PRD §3.4: "A dimension may move `PENDING` to `CLEARED`, `PENDING` to
    `DEFERRED`, `DEFERRED` to `CLEARED` after a resubmission, `PENDING` or `DEFERRED`
    to `EXCLUDED`, and — when a later determination defers a domain that had already
    been cleared — `CLEARED` back to `DEFERRED`, which also increments
    `deferral_count` and re-derives `overall_status` down to `EVAL_IN_PROGRESS`."
    PRD §3.4: "It is one half of `medical_risk_points` plus one half of
    `psychosocial_risk_points`, plus 1.5 for each entry in `deferral_count`, plus a
    further 2.0 when the donor has no `intended_recipient_id`, all rounded half up to
    two decimal places once at the end."
    PRD §3.3: "It sets `attestation_at` to the current logical clock, computes
    `final_risk_index`, and derives the donor's `overall_status` into either
    `APPROVED` or `CONDITIONAL_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/attestation_blocked_by_deferred_donor_evaluation
    """
    env = _setup_donor_with_deferred_psychosocial()
    donor_id = env["donor"]["id"]
    validate_error(_attest(env, donor_id), ApiErrorId.ERR_CLEARANCE_INCOMPLETE.value)

    validate_success(
        api_client.resubmit_evaluation(
            env["psychosocial_evaluation"]["id"],
            dict(NINE_CLEAN_FINDINGS),
            env["reviewer_psy_headers"],
        )
    )
    determine_evaluation(
        env, env["psychosocial_evaluation"]["id"], "CLEARED", env["reviewer_psy_headers"]
    )

    attested = validate_success(_attest(env, donor_id))

    assert attested["advocacy_status"] == "ATTESTED"
    assert attested["attestation_at"].startswith("2026-08-15T00:00:00")
    assert attested["deferral_count"] == 1
    assert attested["final_risk_index"] == 3.5, (
        "0.0 clinical points plus 1.5 for the one deferral plus the 2.0 non-directed "
        "surcharge"
    )
    assert attested["overall_status"] == "APPROVED"


def _setup_frozen_program_with_a_validated_chain():
    env = setup_paired_loop_participants()
    review = create_outcome_review(
        env,
        period_start_on="2025-01-01",
        period_end_on="2025-12-31",
        cohort_size=25,
        observed_survivor_count=16,
    )
    env["review"] = finalize_review(env, review["id"])
    assert refresh_program(env)["compliance_posture"] == "FROZEN"
    build_paired_loop_chain(env)
    env["chain"] = validate_chain(env, env["chain"]["id"])
    assert env["chain"]["status"] == "VALIDATED", (
        "the suspend cascade fired before this chain existed"
    )
    return env


def test_commitment_is_refused_while_the_parent_program_is_frozen():
    """PRD §2.8: "While a program is `FROZEN`, referring a new donor candidate and
    committing an exchange chain are both refused with `ERR_PROGRAM_FROZEN` (HTTP
    409)."
    PRD §2.8: "Then: if an unanswered flagged review exists, the posture is `FROZEN`."
    PRD §2.10: "Program compliance posture gate — `ERR_PROGRAM_FROZEN` or
    `ERR_PROGRAM_RESTRICTED`, 409."

    Design: Difficulty/cross_entity_state_dependency/chain_commitment_blocked_by_frozen_program_posture
    """
    env = _setup_frozen_program_with_a_validated_chain()

    response = api_client.commit_chain(env["chain"]["id"], env["coordinator_headers"])
    validate_error(response, ApiErrorId.ERR_PROGRAM_FROZEN.value)

    unchanged = get_chain(env, env["chain"]["id"])
    assert unchanged["status"] == "VALIDATED"
    assert unchanged["committed_at"] is None
    assert unchanged["committed_donor_count"] == 0
    assert unchanged["segment_count"] == 2
    assert unchanged["is_closed_loop"] is True

    assert get_donor(env, env["donor_one"]["id"])["overall_status"] == "APPROVED"
    assert get_donor(env, env["donor_two"]["id"])["overall_status"] == "APPROVED"
    assert refresh_program(env)["compliance_posture"] == "FROZEN"


def test_commitment_succeeds_once_the_flagged_review_has_an_accepted_plan():
    """PRD §3.8: "Accepting moves the plan from `SUBMITTED` to `ACCEPTED`, stamps
    `decided_at` with the current logical clock, records the reason code, and
    re-derives the program's posture — the parent review's `FLAGGED` level no longer
    forces `FROZEN`, so the posture drops to `RESTRICTED` or `OPEN` and every
    `SUSPENDED` chain returns to `VALIDATED`."
    PRD §3.6: "On success the chain moves to `COMMITTED`, `committed_at` is set to the
    current logical clock, `committed_donor_count` becomes the number of distinct
    donors on non-withdrawn segments, every one of those donors moves from `APPROVED`
    to `CHAIN_COMMITTED`, and the chain's `version` increments."

    Design: Difficulty/cross_entity_state_dependency/chain_commitment_blocked_by_frozen_program_posture
    """
    env = _setup_frozen_program_with_a_validated_chain()
    validate_error(
        api_client.commit_chain(env["chain"]["id"], env["coordinator_headers"]),
        ApiErrorId.ERR_PROGRAM_FROZEN.value,
    )

    plan = file_improvement_plan(env, env["review"]["id"])
    transition_improvement_plan(
        env, plan["id"], "ACCEPT", decision_reason_code="PLAN_ADEQUATE"
    )
    assert refresh_program(env)["compliance_posture"] == "OPEN"

    committed = validate_success(
        api_client.commit_chain(env["chain"]["id"], env["coordinator_headers"])
    )

    assert committed["status"] == "COMMITTED"
    assert committed["committed_at"] is not None
    assert committed["committed_donor_count"] == 2
    assert get_donor(env, env["donor_one"]["id"])["overall_status"] == "CHAIN_COMMITTED"
    assert get_donor(env, env["donor_two"]["id"])["overall_status"] == "CHAIN_COMMITTED"
