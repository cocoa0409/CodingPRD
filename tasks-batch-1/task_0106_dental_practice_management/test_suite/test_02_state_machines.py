"""Non-linear state-machine behavior: the treatment-plan revision loop and the
claim's two independent status dimensions.

Difficulty queue A: non_linear_state_machine instances.
"""
from test_helpers import (
    setup_practice,
    create_plan_with_items,
    propose_plan,
    accept_plan,
    complete_item_via_visit,
    create_claim,
    attach_and_submit,
    validate_success,
    get_success_data,
    TEST_USERS,
)
from test_helpers import api_client

BILL = TEST_USERS["billing_headers"]


# ─── non_linear_state_machine / treatment_plan_revision_cycle ─────────────────

def test_plan_revision_cycle_returns_to_proposed():
    """PRD §3.3: "From `PROPOSED`, a `Clinician` may revise the plan back to
    `DRAFT`, which requires it to be in `PROPOSED` (otherwise `ERR_INVALID_STATE`)
    and reopens it so items may be added or removed; revising and re-proposing may
    repeat."

    Propose -> revise -> add a second item -> re-propose lands back in PROPOSED
    with both items counted (total_fee 12000+8000=20000).

    Design: Difficulty/non_linear_state_machine/treatment_plan_revision_cycle_proposed_back_to_draft
    """
    ctx = setup_practice()
    patient, provider = ctx["patient"], ctx["provider"]
    clin = ctx["clinician_headers"]
    plan, _ = create_plan_with_items(
        patient["id"], provider["id"],
        [{"cdt_code": "D1110", "category": "PREVENTIVE", "fee_cents": 12_000, "phase_number": 1}],
    )
    propose_plan(plan["id"], provider["id"])
    revised = validate_success(api_client.revise_treatment_plan(plan["id"], clin))
    assert revised["status"] == "DRAFT"
    get_success_data(api_client.add_treatment_plan_item(
        plan["id"], {"cdt_code": "D0220", "category": "PREVENTIVE", "fee_cents": 8_000,
                     "phase_number": 1}, clin))
    reproposed = propose_plan(plan["id"], provider["id"])
    assert reproposed["status"] == "PROPOSED"
    assert reproposed["total_fee_cents"] == 20000


def test_plan_revision_reestimates_newly_added_item():
    """PRD §3.3: "On proposal, the system recomputes `estimated_insurance_cents`
    and `estimated_patient_portion_cents` on every `PLANNED` item using the
    forward-looking estimate of §3.8".

    After revising back to DRAFT and adding a second PREVENTIVE item (fee 8000,
    100% coinsurance, deductible already accounted on the larger first item), the
    re-propose estimates the new item; with no coverage the estimate is 0 but the
    re-estimation pass runs on every PLANNED item including the late addition.

    Design: Difficulty/non_linear_state_machine/treatment_plan_revision_cycle_proposed_back_to_draft
    """
    # No coverage so the estimate path is deterministic (estimated_insurance == 0
    # for every item, including the one added after the revision).
    ctx = setup_practice(with_coverage=False)
    patient, provider = ctx["patient"], ctx["provider"]
    clin = ctx["clinician_headers"]
    plan, _ = create_plan_with_items(
        patient["id"], provider["id"],
        [{"cdt_code": "D1110", "category": "PREVENTIVE", "fee_cents": 12_000, "phase_number": 1}],
    )
    propose_plan(plan["id"], provider["id"])
    validate_success(api_client.revise_treatment_plan(plan["id"], clin))
    item2 = get_success_data(api_client.add_treatment_plan_item(
        plan["id"], {"cdt_code": "D0220", "category": "PREVENTIVE", "fee_cents": 8_000,
                     "phase_number": 1}, clin))
    propose_plan(plan["id"], provider["id"])
    item2_after = validate_success(api_client.get_treatment_plan_item(item2["id"], clin))
    # No active coverage => estimated_insurance_cents == 0 for the re-estimated item.
    assert item2_after["estimated_insurance_cents"] == 0
    assert item2_after["estimated_patient_portion_cents"] == 8000


# ─── non_linear_state_machine / claim_parallel_dimensions ─────────────────────

def test_claim_submission_dimension_independent_of_adjudication():
    """PRD §3.6: "A claim tracks two **independent** status dimensions. The
    `submission_status` dimension is `DRAFT` or `SUBMITTED`; the
    `adjudication_status` dimension is `PENDING`, `PAID`, `PARTIALLY_PAID`,
    `DENIED`, or `VOID`. They advance separately, and a claim must be submitted
    before it can be adjudicated."

    After submit then deny, the claim holds SUBMITTED × DENIED — a combined state
    no single-axis machine could express.

    Design: Difficulty/non_linear_state_machine/claim_parallel_dimensions_submission_independent_of_adjudication
    """
    ctx = setup_practice()
    patient, provider, operatory, coverage = (
        ctx["patient"], ctx["provider"], ctx["operatory"], ctx["coverage"]
    )
    plan, items = create_plan_with_items(
        patient["id"], provider["id"],
        [{"cdt_code": "D2393", "category": "BASIC", "fee_cents": 50_000,
          "phase_number": 1, "tooth_number": 20}],
    )
    item = items[0]
    propose_plan(plan["id"], provider["id"])
    accept_plan(plan["id"])
    complete_item_via_visit(patient["id"], provider["id"], operatory["id"], item["id"],
                            start_at="2026-06-01T09:00:00Z", end_at="2026-06-01T10:00:00Z")
    claim = create_claim(patient["id"], item["id"], coverage["id"])
    submitted = attach_and_submit(claim["id"], attachment_type="NARRATIVE", document_ref="ref://n2")
    assert submitted["submission_status"] == "SUBMITTED"

    denied = validate_success(api_client.deny_claim(claim["id"], BILL))
    assert denied["submission_status"] == "SUBMITTED"
    assert denied["adjudication_status"] == "DENIED"


def test_claim_denial_makes_patient_owe_full_billed_fee():
    """PRD §3.6: "A carrier denial is a separate `BillingSpecialist` action moving
    `adjudication_status` from `PENDING` to `DENIED`; it requires the claim to be
    `PENDING` (otherwise `ERR_INVALID_STATE`), sets `carrier_paid_cents` to zero
    and `patient_responsibility_cents` to the full `billed_fee_cents`".

    A BASIC claim fee 50000 denied => carrier_paid 0, patient_responsibility 50000,
    while submission_status stays SUBMITTED.

    Design: Difficulty/non_linear_state_machine/claim_parallel_dimensions_submission_independent_of_adjudication
    """
    ctx = setup_practice()
    patient, provider, operatory, coverage = (
        ctx["patient"], ctx["provider"], ctx["operatory"], ctx["coverage"]
    )
    plan, items = create_plan_with_items(
        patient["id"], provider["id"],
        [{"cdt_code": "D2393", "category": "BASIC", "fee_cents": 50_000,
          "phase_number": 1, "tooth_number": 20}],
    )
    item = items[0]
    propose_plan(plan["id"], provider["id"])
    accept_plan(plan["id"])
    complete_item_via_visit(patient["id"], provider["id"], operatory["id"], item["id"],
                            start_at="2026-06-02T09:00:00Z", end_at="2026-06-02T10:00:00Z")
    claim = create_claim(patient["id"], item["id"], coverage["id"])
    attach_and_submit(claim["id"], attachment_type="NARRATIVE", document_ref="ref://n3")
    denied = validate_success(api_client.deny_claim(claim["id"], BILL))
    assert denied["carrier_paid_cents"] == 0
    assert denied["patient_responsibility_cents"] == 50000
