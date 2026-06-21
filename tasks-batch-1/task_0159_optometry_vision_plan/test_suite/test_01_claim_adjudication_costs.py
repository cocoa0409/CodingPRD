"""Claim adjudication cost: routine vs medical billing, statement totals.

Covers the dual-variant claim cost calculation (PRD §3.8) and the round-then-sum
patient statement (PRD §3.10).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    setup_finalized_routine_encounter,
    setup_active_rx,
    draft_claim,
)

BILLER = TEST_USERS["biller_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


def test_routine_claim_adjudication_diverges_from_medical(api):
    """PRD §3.8: "For a routine claim, the billed amount is the encounter's
    `exam_fee_cents` plus its `refraction_fee_cents`; the carrier covers the exam
    slot so that the plan-paid portion is the billed amount minus the eligibility's
    `exam_copay_cents` but never less than zero, and the patient responsibility is
    the smaller of the billed amount and the `exam_copay_cents` — the refraction is
    bundled into the covered exam benefit."

    Design: Difficulty/dual_variant_calc/claim_routine_vs_medical_diverges_on_encounter_domain
    """
    ctx = setup_finalized_routine_encounter(
        elig=True,
        patient_overrides={"plan_carrier": "VSP", "medical_insurance_on_file": True},
        elig_overrides={"exam_copay_cents": 2500, "materials_allowance_cents": 40000},
        encounter_overrides={"encounter_type": "ROUTINE_VISION", "chief_complaint_code": "Z01",
                             "exam_fee_cents": 12000, "refraction_fee_cents": 3000},
    )
    claim = draft_claim(ctx["enc"]["id"], eligibility_id=ctx["elig"]["id"])
    adj = validate_success(api.adjudicate_claim(claim["id"], BILLER), 200)

    assert adj["billing_route"] == "ROUTINE"
    assert adj["billed_amount_cents"] == 15000
    assert adj["plan_paid_cents"] == 12500
    assert adj["patient_responsibility_cents"] == 2500


def test_medical_claim_coinsurance_on_exam_only(api):
    """PRD §3.8: "The covered amount is the encounter's `exam_fee_cents`; the plan
    pays 80 percent of that covered amount — the product of the covered amount and a
    medical coinsurance rate of 0.80, rounded half up to whole cents — and this is the
    claim's `plan_paid_cents`. The patient's coinsurance share is the covered amount
    minus the plan-paid amount, and the patient's total `patient_responsibility_cents`
    is that coinsurance share plus the encounter's full `refraction_fee_cents`, which
    the patient bears entirely."

    Design: Difficulty/dual_variant_calc/claim_routine_vs_medical_diverges_on_encounter_domain
    """
    ctx = setup_finalized_routine_encounter(
        elig=False,
        patient_overrides={"plan_carrier": "NONE", "medical_insurance_on_file": True},
        encounter_overrides={"encounter_type": "MEDICAL_EYE", "chief_complaint_code": "H40",
                             "exam_fee_cents": 12000, "refraction_fee_cents": 3000},
    )
    claim = draft_claim(ctx["enc"]["id"])
    adj = validate_success(api.adjudicate_claim(claim["id"], BILLER), 200)

    # plan_paid = round(12000 * 0.80) = 9600; patient_coins = 12000 - 9600 = 2400;
    # patient_responsibility = 2400 + 3000 refraction = 5400; billed = 12000 + 3000 = 15000.
    assert adj["billing_route"] == "MEDICAL"
    assert adj["plan_paid_cents"] == 9600
    assert adj["patient_responsibility_cents"] == 5400
    assert adj["billed_amount_cents"] == 15000


def test_medical_claim_coinsurance_correct_result_no_refraction(api):
    """PRD §3.8: "the plan pays 80 percent of that covered amount — the product of
    the covered amount and a medical coinsurance rate of 0.80, rounded half up to
    whole cents — and this is the claim's `plan_paid_cents`."

    Design: Corner/calculations/medical_claim_coinsurance_correct_result
    """
    ctx = setup_finalized_routine_encounter(
        elig=False,
        patient_overrides={"plan_carrier": "NONE", "medical_insurance_on_file": True},
        encounter_overrides={"encounter_type": "MEDICAL_EYE", "chief_complaint_code": "H40",
                             "exam_fee_cents": 18000, "refraction_fee_cents": 0},
    )
    claim = draft_claim(ctx["enc"]["id"])
    adj = validate_success(api.adjudicate_claim(claim["id"], BILLER), 200)

    assert adj["billing_route"] == "MEDICAL"
    assert adj["plan_paid_cents"] == 14400          # round(18000 * 0.80)
    assert adj["patient_responsibility_cents"] == 3600  # 18000 - 14400 + 0
    assert adj["billed_amount_cents"] == 18000


def test_patient_statement_round_then_sum(api):
    """PRD §3.10: "that per-claim outstanding amount is rounded to whole dollars —
    that is, rounded half up to the nearest multiple of 100 cents — first, before any
    summation. The `statement_total_cents` is the sum of these individually rounded
    per-claim figures; the rounding is applied to each line and then the rounded lines
    are summed, never the reverse, and the `line_count` reports how many claims fell
    in scope."

    Two MEDICAL claims, each outstanding 2550 -> rounds to 2600 -> sum 5200 (not 5100).

    Design: Difficulty/combinatorial_formula/patient_statement_round_then_sum_mode_b
    """
    # Patient with medical insurance; two MEDICAL_EYE encounters, exam 12750, refraction 0.
    # plan_paid = round(12750 * 0.80) = 10200; patient_resp = 12750 - 10200 = 2550 each.
    from test_helpers import setup_clinic, create_open_encounter, issue_prescription
    ctx = setup_clinic(with_optician=False,
                       patient_overrides={"plan_carrier": "NONE", "medical_insurance_on_file": True})
    pat_id = ctx["pat"]["id"]

    claim_ids = []
    for sphere in (-1.25, -1.50):
        enc = create_open_encounter(pat_id, ctx["od"]["id"], encounter_type="MEDICAL_EYE",
                                    chief_complaint_code="H40", exam_fee_cents=12750,
                                    refraction_fee_cents=0)
        issue_prescription(pat_id, enc["id"], ctx["od_h"], sphere_od=sphere, sphere_os=sphere)
        get_success_data(api.finalize_encounter(enc["id"], ctx["od_h"]))
        claim = draft_claim(enc["id"])
        adj = validate_success(api.adjudicate_claim(claim["id"], BILLER), 200)
        assert adj["patient_responsibility_cents"] == 2550
        claim_ids.append(claim["id"])

    stmt = validate_success(api.get_patient_statement(pat_id, BILLER), 200)
    assert stmt["statement_total_cents"] == 5200
    assert stmt["line_count"] == 2


def test_patient_statement_single_line_rounds_to_whole_dollar(api):
    """PRD §3.10: "For each such claim, the outstanding amount is its
    `patient_responsibility_cents` minus its `settled_cents`, and that per-claim
    outstanding amount is rounded to whole dollars — that is, rounded half up to the
    nearest multiple of 100 cents — first, before any summation."

    A single MEDICAL claim outstanding 2550 rounds to a 2600 whole-dollar line; the
    statement reports that rounded line and a line_count of 1.

    Design: Difficulty/combinatorial_formula/patient_statement_round_then_sum_mode_b
    """
    from test_helpers import setup_adjudicated_medical_claim
    ctx = setup_adjudicated_medical_claim(exam_fee=12750, refraction_fee=0, complaint="H40")
    assert ctx["claim"]["patient_responsibility_cents"] == 2550

    stmt = validate_success(api.get_patient_statement(ctx["pat"]["id"], BILLER), 200)
    assert stmt["statement_total_cents"] == 2600
    assert stmt["line_count"] == 1
