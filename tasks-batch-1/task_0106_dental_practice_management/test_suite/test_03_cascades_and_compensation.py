"""Depth-3 cascades and conserved-quantity compensation.

Difficulty queue A: transitive_cascade, compensating_invariant instances.
"""
from test_helpers import (
    setup_practice,
    create_plan_with_items,
    propose_plan,
    accept_plan,
    complete_item_via_visit,
    book_appointment,
    create_claim,
    attach_and_submit,
    adjudicate_claim,
    create_predetermination,
    approve_predetermination,
    create_payment_plan,
    setup_adjudicated_claim,
    validate_success,
    get_success_data,
    TEST_USERS,
)
from test_helpers import api_client

BILL = TEST_USERS["billing_headers"]
FD = TEST_USERS["front_desk_headers"]


# ─── transitive_cascade / claim_payment_cascade_to_predetermination_revalidation

def test_adjudication_cascades_to_annual_max_reached():
    """PRD §3.6: "at depth two, if `annual_benefit_used_cents` has reached or
    exceeded the plan's `annual_maximum_cents`, the coverage's `annual_max_reached`
    is set true".

    A BASIC claim fee=130000 adjudicates to exactly 100000 carrier-paid (the max),
    so annual_benefit_used reaches 100000 and annual_max_reached flips true.

    Design: Difficulty/transitive_cascade/claim_payment_cascade_to_predetermination_revalidation_depth3
    """
    ctx = setup_practice()
    patient, provider, operatory, coverage = (
        ctx["patient"], ctx["provider"], ctx["operatory"], ctx["coverage"]
    )
    clin = ctx["clinician_headers"]

    # APPROVED predetermination on a MAJOR item (no waiting/frequency, plan=0/0).
    plan = get_success_data(api_client.create_treatment_plan(
        {"patient_id": patient["id"], "provider_id": provider["id"]}, clin))
    item_x = get_success_data(api_client.add_treatment_plan_item(
        plan["id"], {"cdt_code": "D2950", "category": "MAJOR", "fee_cents": 90_000,
                     "phase_number": 1, "tooth_number": 30, "requires_predetermination": True}, clin))
    pred = create_predetermination(item_x["id"], coverage["id"])
    approve_predetermination(pred["id"], approved_benefit_cents=42_500, valid_until_date="2027-01-01")

    item_y = get_success_data(api_client.add_treatment_plan_item(
        plan["id"], {"cdt_code": "D2394", "category": "BASIC", "fee_cents": 130_000,
                     "phase_number": 1, "tooth_number": 19}, clin))
    propose_plan(plan["id"], provider["id"])
    accept_plan(plan["id"])
    complete_item_via_visit(patient["id"], provider["id"], operatory["id"], item_y["id"],
                            start_at="2026-07-01T09:00:00Z", end_at="2026-07-01T10:00:00Z")
    claim = create_claim(patient["id"], item_y["id"], coverage["id"])
    attach_and_submit(claim["id"], attachment_type="XRAY", document_ref="ref://x4")
    adjudicated = adjudicate_claim(claim["id"])
    assert adjudicated["carrier_paid_cents"] == 100000

    cov_after = validate_success(api_client.get_patient_coverage(coverage["id"], BILL))
    assert cov_after["annual_benefit_used_cents"] == 100000
    assert cov_after["annual_max_reached"] is True


def test_annual_max_flip_revalidates_approved_predetermination():
    """PRD §3.6: "at depth three, if that flag has just flipped from false to true,
    every `APPROVED` predetermination on that coverage moves to
    `REQUIRES_REVALIDATION`".

    The same adjudication that trips annual_max_reached cascades (depth 3) into the
    APPROVED predetermination on item X, moving it to REQUIRES_REVALIDATION.

    Design: Difficulty/transitive_cascade/claim_payment_cascade_to_predetermination_revalidation_depth3
    """
    ctx = setup_practice()
    patient, provider, operatory, coverage = (
        ctx["patient"], ctx["provider"], ctx["operatory"], ctx["coverage"]
    )
    clin = ctx["clinician_headers"]
    plan = get_success_data(api_client.create_treatment_plan(
        {"patient_id": patient["id"], "provider_id": provider["id"]}, clin))
    item_x = get_success_data(api_client.add_treatment_plan_item(
        plan["id"], {"cdt_code": "D2950", "category": "MAJOR", "fee_cents": 90_000,
                     "phase_number": 1, "tooth_number": 30, "requires_predetermination": True}, clin))
    pred = create_predetermination(item_x["id"], coverage["id"])
    approve_predetermination(pred["id"], approved_benefit_cents=42_500, valid_until_date="2027-01-01")

    item_y = get_success_data(api_client.add_treatment_plan_item(
        plan["id"], {"cdt_code": "D2394", "category": "BASIC", "fee_cents": 130_000,
                     "phase_number": 1, "tooth_number": 19}, clin))
    propose_plan(plan["id"], provider["id"])
    accept_plan(plan["id"])
    complete_item_via_visit(patient["id"], provider["id"], operatory["id"], item_y["id"],
                            start_at="2026-07-02T09:00:00Z", end_at="2026-07-02T10:00:00Z")
    claim = create_claim(patient["id"], item_y["id"], coverage["id"])
    attach_and_submit(claim["id"], attachment_type="XRAY", document_ref="ref://x4b")
    adjudicate_claim(claim["id"])

    pred_after = validate_success(api_client.get_predetermination(pred["id"], BILL))
    assert pred_after["status"] == "REQUIRES_REVALIDATION"


# ─── transitive_cascade / treatment_plan_cancel_cascade_to_appointment_depth3 ──

def test_plan_cancel_cascades_to_item():
    """PRD §3.4: "at the first cascade depth, transitions every non-terminal item
    — those in `PLANNED` or `SCHEDULED` — to `CANCELLED`".

    Cancelling an ACCEPTED plan whose item is SCHEDULED moves the item to CANCELLED
    (cascade depth 1).

    Design: Difficulty/transitive_cascade/treatment_plan_cancel_cascade_to_appointment_depth3
    """
    ctx = setup_practice(with_coverage=False)
    patient, provider, operatory = ctx["patient"], ctx["provider"], ctx["operatory"]
    clin = ctx["clinician_headers"]
    plan, items = create_plan_with_items(
        patient["id"], provider["id"],
        [{"cdt_code": "D1110", "category": "PREVENTIVE", "fee_cents": 12_000, "phase_number": 1}],
    )
    item = items[0]
    propose_plan(plan["id"], provider["id"])
    accept_plan(plan["id"])
    book_appointment(patient["id"], provider["id"], operatory["id"],
                     treatment_plan_item_id=item["id"], appointment_type="PREVENTIVE",
                     start_at="2026-08-01T09:00:00Z", end_at="2026-08-01T09:45:00Z")
    cancelled = validate_success(api_client.cancel_treatment_plan(plan["id"], FD))
    assert cancelled["status"] == "CANCELLED"
    item_after = validate_success(api_client.get_treatment_plan_item(item["id"], clin))
    assert item_after["status"] == "CANCELLED"


def test_plan_cancel_cascades_through_item_to_appointment():
    """PRD §3.4: "at the second cascade depth, for each item just cancelled that
    has a linked `SCHEDULED` appointment, that appointment is moved to
    `CANCELLED`."

    The depth-3 chain: plan cancel -> item CANCELLED -> the item's SCHEDULED
    appointment CANCELLED (caused by the item cancel, not the plan cancel directly).

    Design: Difficulty/transitive_cascade/treatment_plan_cancel_cascade_to_appointment_depth3
    """
    ctx = setup_practice(with_coverage=False)
    patient, provider, operatory = ctx["patient"], ctx["provider"], ctx["operatory"]
    plan, items = create_plan_with_items(
        patient["id"], provider["id"],
        [{"cdt_code": "D1110", "category": "PREVENTIVE", "fee_cents": 12_000, "phase_number": 1}],
    )
    item = items[0]
    propose_plan(plan["id"], provider["id"])
    accept_plan(plan["id"])
    appt = book_appointment(patient["id"], provider["id"], operatory["id"],
                            treatment_plan_item_id=item["id"], appointment_type="PREVENTIVE",
                            start_at="2026-08-02T09:00:00Z", end_at="2026-08-02T09:45:00Z")
    validate_success(api_client.cancel_treatment_plan(plan["id"], FD))
    appt_after = validate_success(api_client.get_appointment(appt["id"], FD))
    assert appt_after["status"] == "CANCELLED"


# ─── compensating_invariant / claim_void_restores_annual_benefit_used ─────────

def test_void_restores_annual_benefit_used_accumulator():
    """PRD §3.6: "As compensation, the void subtracts the claim's
    `carrier_paid_cents` back out of the coverage's `annual_benefit_used_cents`,
    restores `deductible_met_cents` to its pre-adjudication value, recomputes
    `annual_max_reached` (which may flip from true back to false)".

    A BASIC claim paid 100000 (==max) then voided restores annual_benefit_used to
    0 — the conserved benefit pool nets to zero drift.

    Design: Difficulty/compensating_invariant/claim_void_restores_annual_benefit_used_accumulator
    """
    ctx = setup_practice()
    _, claim = setup_adjudicated_claim(ctx, 130_000, category="BASIC", cdt_code="D2396",
                                       tooth_number=12, document_ref="ref://x6",
                                       attachment_type="XRAY")
    assert claim["carrier_paid_cents"] == 100000
    voided = validate_success(api_client.void_claim(claim["id"], BILL))
    assert voided["adjudication_status"] == "VOID"
    cov_after = validate_success(api_client.get_patient_coverage(ctx["coverage"]["id"], BILL))
    assert cov_after["annual_benefit_used_cents"] == 0


def test_void_flips_annual_max_reached_back_to_false():
    """PRD §3.8: "The coverage's `annual_max_reached` is true exactly when that sum
    has reached or exceeded the plan's `annual_maximum_cents`".
    PRD §3.6: "recomputes `annual_max_reached` (which may flip from true back to
    false)".

    Voiding the claim that tripped the max returns annual_benefit_used below the
    ceiling, so annual_max_reached recomputes back to false.

    Design: Difficulty/compensating_invariant/claim_void_restores_annual_benefit_used_accumulator
    """
    ctx = setup_practice()
    _, claim = setup_adjudicated_claim(ctx, 130_000, category="BASIC", cdt_code="D2396",
                                       tooth_number=13, document_ref="ref://x6b",
                                       attachment_type="XRAY")
    cov_before = validate_success(api_client.get_patient_coverage(ctx["coverage"]["id"], BILL))
    assert cov_before["annual_max_reached"] is True
    validate_success(api_client.void_claim(claim["id"], BILL))
    cov_after = validate_success(api_client.get_patient_coverage(ctx["coverage"]["id"], BILL))
    assert cov_after["annual_max_reached"] is False


# ─── compensating_invariant / payment_plan_reverse_installment_restores_balance ─

def test_reverse_installment_restores_remaining_balance():
    """PRD §3.7: "Reversing the most recent installment is a `BillingSpecialist`
    compensation supplying an `amount_cents`: it decreases `amount_posted_cents` by
    that amount, recomputes `remaining_balance_cents` and the patient's
    `balance_owed_cents`".

    Post 62500 (=> amount_posted 62500, remaining 0) then reverse 62500 returns
    amount_posted to 0 and remaining_balance to the principal 62500.

    Design: Difficulty/compensating_invariant/payment_plan_reverse_installment_restores_remaining_balance
    """
    ctx = setup_practice()
    _, claim = setup_adjudicated_claim(ctx, 120_000, category="MAJOR", cdt_code="D2740",
                                       tooth_number=8, document_ref="ref://p2",
                                       attachment_type="PHOTO")
    pp = create_payment_plan(ctx["patient"]["id"], claim["id"], claim["version"],
                             installment_count=7)
    validate_success(api_client.post_installment(pp["id"], {"amount_cents": 62500}, BILL))
    reversed_pp = validate_success(api_client.reverse_installment(pp["id"], {"amount_cents": 62500}, BILL))
    assert reversed_pp["amount_posted_cents"] == 0
    assert reversed_pp["remaining_balance_cents"] == 62500


def test_reverse_installment_flips_paid_off_back_to_active():
    """PRD §3.7: "if the plan was `PAID_OFF` and the reversal drops
    `amount_posted_cents` back below `principal_cents`, the plan reverts to
    `ACTIVE`."

    The lump post flips the plan PAID_OFF; reversing it drops amount_posted below
    principal, so status reverts to ACTIVE.

    Design: Difficulty/compensating_invariant/payment_plan_reverse_installment_restores_remaining_balance
    """
    ctx = setup_practice()
    _, claim = setup_adjudicated_claim(ctx, 120_000, category="MAJOR", cdt_code="D2740",
                                       tooth_number=8, document_ref="ref://p2b",
                                       attachment_type="PHOTO")
    pp = create_payment_plan(ctx["patient"]["id"], claim["id"], claim["version"],
                             installment_count=7)
    posted = validate_success(api_client.post_installment(pp["id"], {"amount_cents": 62500}, BILL))
    assert posted["status"] == "PAID_OFF"
    reversed_pp = validate_success(api_client.reverse_installment(pp["id"], {"amount_cents": 62500}, BILL))
    assert reversed_pp["status"] == "ACTIVE"
