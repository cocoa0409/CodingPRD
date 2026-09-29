"""The two weighted donor risk figures and the money they do not share."""
from test_helpers import (
    attest_donor,
    clear_both_domains,
    create_active_recipient,
    create_donor,
    determine_evaluation,
    file_claim,
    get_donor,
    refresh_program,
    setup_donor_with_exhausted_lifetime_headroom,
    setup_program_with_staff,
    submit_medical_evaluation,
    submit_psychosocial_evaluation,
    validate_success,
)
from test_helpers.api_client import api_client

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


def test_screening_and_final_index_diverge_on_one_donor_at_one_instant():
    """PRD §3.4: "A donor with `medical_risk_points` of 10 and
    `psychosocial_risk_points` of 5 and no deferrals has a screening index of 8.0
    but a final index of 7.5, and is approved; add a single deferral and the
    screening index is unchanged while the final index reaches 9.0 and the donor
    is only conditionally approved."
    PRD §3.4: "It is six tenths of `medical_risk_points` plus four tenths of
    `psychosocial_risk_points`, rounded half up to two decimal places once,
    applied to the whole weighted sum."
    PRD §3.4: "It is one half of `medical_risk_points` plus one half of
    `psychosocial_risk_points`, plus 1.5 for each entry in `deferral_count`, plus
    a further 2.0 when the donor has no `intended_recipient_id`, all rounded half
    up to two decimal places once at the end."

    Design: Difficulty/dual_variant_calc/donor_risk_index_screening_vs_final_on_same_donor
    """
    env = setup_program_with_staff()
    recipient = create_active_recipient(env, mrn="R-001")
    donor = create_donor(
        env, intended_recipient_id=recipient["id"], mrn="D-001", age_years=62
    )
    clear_both_domains(
        env,
        donor["id"],
        medical=MEDICAL_TEN_POINTS,
        psychosocial=PSYCHOSOCIAL_FIVE_POINTS,
    )

    before_attestation = get_donor(env, donor["id"])
    assert before_attestation["medical_risk_points"] == 10
    assert before_attestation["psychosocial_risk_points"] == 5
    assert before_attestation["deferral_count"] == 0
    assert before_attestation["screening_risk_index"] == 8.0, (
        "0.6 * 10 + 0.4 * 5 is 8.0 before any attestation exists"
    )
    assert before_attestation["final_risk_index"] is None, (
        "final_risk_index stays null until the donor is attested"
    )

    attested = attest_donor(env, donor["id"])
    assert attested["advocacy_status"] == "ATTESTED"
    assert attested["attestation_at"].startswith("2026-08-08T00:00:00")
    assert attested["screening_risk_index"] == 8.0
    assert attested["final_risk_index"] == 7.5, (
        "0.5 * 10 + 0.5 * 5 with no deferral and no non-directed surcharge is 7.5"
    )
    assert attested["final_risk_index"] != attested["screening_risk_index"]
    assert attested["overall_status"] == "APPROVED", (
        "7.5 is below the ceiling of 8.0, so the variant choice decides approval"
    )


def test_one_deferral_lifts_only_the_final_index_into_conditional_approval():
    """PRD §3.4: "A donor with `medical_risk_points` of 10 and
    `psychosocial_risk_points` of 5 and no deferrals has a screening index of 8.0
    but a final index of 7.5, and is approved; add a single deferral and the
    screening index is unchanged while the final index reaches 9.0 and the donor
    is only conditionally approved."
    PRD §3.4: "The final index alone is compared against the ceiling of 8.0: a
    value at or above 8.0 yields `CONDITIONAL_APPROVED`, and a value below — 7.99
    included — yields `APPROVED`."

    Design: Difficulty/dual_variant_calc/donor_risk_index_screening_vs_final_on_same_donor
    """
    env = setup_program_with_staff()
    recipient = create_active_recipient(env, mrn="R-001")
    donor = create_donor(
        env, intended_recipient_id=recipient["id"], mrn="D-001", age_years=62
    )

    medical = submit_medical_evaluation(env, donor["id"], **MEDICAL_TEN_POINTS)
    determine_evaluation(env, medical["id"], "DEFERRED", env["reviewer_med_headers"])
    validate_success(
        api_client.resubmit_evaluation(
            medical["id"], dict(MEDICAL_TEN_POINTS), env["reviewer_med_headers"]
        )
    )
    determine_evaluation(env, medical["id"], "CLEARED", env["reviewer_med_headers"])
    psychosocial = submit_psychosocial_evaluation(
        env, donor["id"], **PSYCHOSOCIAL_FIVE_POINTS
    )
    determine_evaluation(env, psychosocial["id"], "CLEARED", env["reviewer_psy_headers"])

    deferred_once = get_donor(env, donor["id"])
    assert deferred_once["deferral_count"] == 1, (
        "deferral_count is cumulative and is never decremented"
    )
    assert deferred_once["screening_risk_index"] == 8.0, (
        "the screening index is unchanged by the deferral history"
    )

    attested = attest_donor(env, donor["id"])
    assert attested["final_risk_index"] == 9.0, "5.0 + 2.5 + 1.5 for one deferral"
    assert attested["screening_risk_index"] == 8.0
    assert attested["overall_status"] == "CONDITIONAL_APPROVED"


def test_estimated_claim_amount_survives_the_pessimistic_adjudication_untouched():
    """PRD §3.9: "`estimated_reimbursement_cents` is written once, at filing, and
    is never revised. It applies only the per-claim cap and deliberately ignores
    the donor's lifetime cap, the coverage buckets and the program fund balance."
    PRD §3.9: "A new claim starts in `SUBMITTED` with `insurance_part_cents`,
    `grant_part_cents` and `fund_part_cents` all 0 and with
    `adjudicated_reimbursement_cents`, `unfunded_cents`, `adjudicated_at`,
    `adjudicated_by_user_id` and `reversal_reason_code` all null."

    Design: Difficulty/dual_variant_calc/donor_cost_claim_estimated_vs_adjudicated_waterfall
    """
    env = setup_donor_with_exhausted_lifetime_headroom()
    donor_id = env["donor_one"]["id"]

    filed = file_claim(
        env,
        donor_id,
        claim_type="MEDICAL",
        coverage_source="PROGRAM_FUND",
        submitted_amount_cents=800000,
        service_from_on="2026-08-11",
        service_to_on="2026-08-12",
    )
    assert filed["status"] == "SUBMITTED"
    assert filed["estimated_reimbursement_cents"] == 800000, (
        "800000 is below the 1,000,000-cent medical cap, so the submitted amount stands"
    )
    assert filed["insurance_part_cents"] == 0
    assert filed["grant_part_cents"] == 0
    assert filed["fund_part_cents"] == 0
    assert filed["adjudicated_reimbursement_cents"] is None
    assert filed["unfunded_cents"] is None
    assert filed["adjudicated_at"] is None
    assert filed["adjudicated_by_user_id"] is None
    assert filed["reversal_reason_code"] is None

    adjudicated = validate_success(
        api_client.adjudicate_claim(
            filed["id"], {"decision": "APPROVE"}, env["finance_headers"]
        )
    )
    assert adjudicated["estimated_reimbursement_cents"] == 800000, (
        "the estimate is never revised by the adjudication"
    )
    assert adjudicated["adjudicated_reimbursement_cents"] == 150000


def test_adjudication_waterfall_pays_only_the_remaining_lifetime_headroom():
    """PRD §3.9: "Sum `adjudicated_reimbursement_cents` over this donor's claims
    whose `status` is `ADJUDICATED`; the donor's lifetime cap is 1,500,000 cents
    (fifteen thousand dollars), and the headroom is the cap minus that prior
    total."
    PRD §3.9: "The insurance bucket has a per-claim ceiling of 600,000 cents (six
    thousand dollars), but only when the claim's `coverage_source` is
    `RECIPIENT_INSURANCE`; for any other coverage source the insurance headroom is
    zero, so a claim filed against the program fund never touches insurance even
    where a ceiling would have existed."
    PRD §3.9: "The grant bucket is only open to claims whose `claim_type` is
    `TRAVEL` or `LOST_WAGES`; for a `MEDICAL` claim the grant headroom is zero."
    PRD §3.9: "`adjudicated_reimbursement_cents` is the sum of the three parts,
    and `unfunded_cents` is `estimated_reimbursement_cents` less
    `adjudicated_reimbursement_cents` — the shortfall between what the caps
    allowed and what the pockets could actually pay, recorded and never silently
    dropped, and the figure an improvement-plan narrative reports."

    Design: Difficulty/dual_variant_calc/donor_cost_claim_estimated_vs_adjudicated_waterfall
    """
    env = setup_donor_with_exhausted_lifetime_headroom()
    donor_id = env["donor_one"]["id"]

    filed = file_claim(
        env,
        donor_id,
        claim_type="MEDICAL",
        coverage_source="PROGRAM_FUND",
        submitted_amount_cents=800000,
        service_from_on="2026-08-11",
        service_to_on="2026-08-12",
    )
    adjudicated = validate_success(
        api_client.adjudicate_claim(
            filed["id"], {"decision": "APPROVE"}, env["finance_headers"]
        )
    )

    assert adjudicated["status"] == "ADJUDICATED"
    assert adjudicated["estimated_reimbursement_cents"] == 800000
    assert adjudicated["adjudicated_reimbursement_cents"] == 150000, (
        "only 150000 of the 1,500,000-cent lifetime cap remained"
    )
    assert adjudicated["insurance_part_cents"] == 0
    assert adjudicated["grant_part_cents"] == 0
    assert adjudicated["fund_part_cents"] == 150000
    assert adjudicated["unfunded_cents"] == 650000

    program = refresh_program(env)
    assert program["donor_fund_committed_cents"] == 550000
    assert program["donor_fund_remaining_cents"] == 4450000
