"""Composite setup helpers for the Dental Practice Management API.

Tests need the system in a specific state (an ACCEPTED plan, a COMPLETED item, a
PAID claim, an ACTIVE payment plan) that takes many API calls to reach. These
helpers encapsulate those chains. They use get_success_data() (lenient 2xx
validator) internally so setup failures surface as clear "Setup step failed"
errors.

Identity threading: Clinician is entity_backed:Provider, so every ownership-gated
clinician call (charting, plan create/items/propose/revise/complete, appointment
complete) uses make_clinician_headers(provider_id) with the real Provider.id.
FrontDesk and BillingSpecialist are opaque operator roles.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_patient_payload,
    create_provider_payload,
    create_operatory_payload,
    create_insurance_plan_payload,
    create_patient_coverage_payload,
    create_treatment_plan_payload,
    create_treatment_plan_item_payload,
    create_appointment_payload,
    create_claim_payload,
    create_claim_attachment_payload,
    create_predetermination_payload,
    approve_predetermination_payload,
    create_payment_plan_payload,
)
from .test_users import (
    TEST_USERS,
    make_clinician_headers,
)


FD = TEST_USERS["front_desk_headers"]
BILL = TEST_USERS["billing_headers"]


# ─── Tier 0: foundational records ─────────────────────────────────────────────

def create_patient(**overrides) -> dict:
    return get_success_data(api_client.create_patient(create_patient_payload(**overrides), FD))


def create_provider(**overrides) -> dict:
    return get_success_data(api_client.create_provider(create_provider_payload(**overrides), FD))


def create_operatory(**overrides) -> dict:
    return get_success_data(api_client.create_operatory(create_operatory_payload(**overrides), FD))


def create_insurance_plan(**overrides) -> dict:
    return get_success_data(api_client.create_insurance_plan(create_insurance_plan_payload(**overrides), BILL))


def create_coverage(patient_id, insurance_plan_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_patient_coverage(
            create_patient_coverage_payload(patient_id, insurance_plan_id, **overrides), BILL
        )
    )


def setup_practice(plan_overrides=None, coverage_overrides=None, with_coverage=True):
    """Patient + DENTIST provider + operatory + (optional) insurance plan + coverage.

    Returns a dict with keys: patient, provider, operatory, clinician_headers,
    and (when with_coverage) insurance_plan, coverage.
    """
    patient = create_patient()
    provider = create_provider(provider_type="DENTIST")
    operatory = create_operatory()
    ctx = {
        "patient": patient,
        "provider": provider,
        "operatory": operatory,
        "clinician_headers": make_clinician_headers(provider["id"]),
    }
    if with_coverage:
        plan = create_insurance_plan(**(plan_overrides or {}))
        coverage = create_coverage(patient["id"], plan["id"], **(coverage_overrides or {}))
        ctx["insurance_plan"] = plan
        ctx["coverage"] = coverage
    return ctx


# ─── Tier 1/2: plans and items ────────────────────────────────────────────────

def create_plan_with_items(patient_id, provider_id, items):
    """Create a DRAFT plan and add each item dict in `items`. Returns
    (plan, [item, ...])."""
    clin = make_clinician_headers(provider_id)
    plan = get_success_data(
        api_client.create_treatment_plan(create_treatment_plan_payload(patient_id, provider_id), clin)
    )
    created = []
    for item in items:
        created.append(
            get_success_data(
                api_client.add_treatment_plan_item(
                    plan["id"], create_treatment_plan_item_payload(**item), clin
                )
            )
        )
    return plan, created


def propose_plan(plan_id, provider_id) -> dict:
    return get_success_data(
        api_client.propose_treatment_plan(plan_id, make_clinician_headers(provider_id))
    )


def accept_plan(plan_id) -> dict:
    return get_success_data(api_client.accept_treatment_plan(plan_id, FD))


def setup_accepted_plan(patient_id, provider_id, items):
    """DRAFT plan + items -> PROPOSED -> ACCEPTED. Returns (plan, [items])."""
    plan, created = create_plan_with_items(patient_id, provider_id, items)
    propose_plan(plan["id"], provider_id)
    accept_plan(plan["id"])
    return plan, created


# ─── Tier 3: appointments and item completion ─────────────────────────────────

def book_appointment(patient_id, provider_id, operatory_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_appointment(
            create_appointment_payload(patient_id, provider_id, operatory_id, **overrides), FD
        )
    )


def complete_item_via_visit(patient_id, provider_id, operatory_id, item_id, **appt_overrides) -> dict:
    """Book an appointment for `item_id`, check in, and complete it so the item
    bubbles to COMPLETED. Returns the completed appointment."""
    appt = book_appointment(
        patient_id, provider_id, operatory_id,
        treatment_plan_item_id=item_id, appointment_type="OPERATIVE", **appt_overrides
    )
    get_success_data(api_client.check_in_appointment(appt["id"], FD))
    get_success_data(api_client.complete_appointment(appt["id"], make_clinician_headers(provider_id)))
    return appt


# ─── Tier 4: claims ───────────────────────────────────────────────────────────

def create_claim(patient_id, item_id, coverage_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_claim(create_claim_payload(patient_id, item_id, coverage_id, **overrides), BILL)
    )


def attach_and_submit(claim_id, **attach_overrides) -> dict:
    get_success_data(
        api_client.add_claim_attachment(claim_id, create_claim_attachment_payload(**attach_overrides), BILL)
    )
    return get_success_data(api_client.submit_claim(claim_id, BILL))


def adjudicate_claim(claim_id) -> dict:
    return get_success_data(api_client.adjudicate_claim(claim_id, BILL))


def setup_completed_item_claim(ctx, item_fee_cents, category="BASIC", cdt_code="D2740",
                               tooth_number=5, start_at="2026-03-01T09:00:00Z",
                               end_at="2026-03-01T10:00:00Z"):
    """From a setup_practice ctx (with coverage): build an ACCEPTED plan with one
    item, complete it via a visit, and create a DRAFT/PENDING claim for it.

    Returns (item, claim).
    """
    patient = ctx["patient"]
    provider = ctx["provider"]
    operatory = ctx["operatory"]
    coverage = ctx["coverage"]
    _, items = setup_accepted_plan(
        patient["id"], provider["id"],
        [{"cdt_code": cdt_code, "category": category, "fee_cents": item_fee_cents,
          "phase_number": 1, "tooth_number": tooth_number}],
    )
    item = items[0]
    complete_item_via_visit(
        patient["id"], provider["id"], operatory["id"], item["id"],
        start_at=start_at, end_at=end_at,
    )
    claim = create_claim(patient["id"], item["id"], coverage["id"])
    return item, claim


def setup_adjudicated_claim(ctx, item_fee_cents, category="MAJOR", cdt_code="D2740",
                            tooth_number=8, attachment_type="XRAY", document_ref="ref://a",
                            start_at="2026-03-01T09:00:00Z", end_at="2026-03-01T10:00:00Z"):
    """Full chain to a PAID/PARTIALLY_PAID claim: ACCEPTED plan + completed item +
    claim + attachment + submit + adjudicate.

    Returns (item, adjudicated_claim).
    """
    item, claim = setup_completed_item_claim(
        ctx, item_fee_cents, category=category, cdt_code=cdt_code, tooth_number=tooth_number,
        start_at=start_at, end_at=end_at,
    )
    attach_and_submit(claim["id"], attachment_type=attachment_type, document_ref=document_ref)
    adjudicated = adjudicate_claim(claim["id"])
    return item, adjudicated


# ─── Tier 5: payment plans ────────────────────────────────────────────────────

def create_payment_plan(patient_id, claim_id, expected_claim_version, **overrides) -> dict:
    return get_success_data(
        api_client.create_payment_plan(
            create_payment_plan_payload(patient_id, claim_id, expected_claim_version, **overrides), BILL
        )
    )


def setup_payment_plan(ctx, item_fee_cents=120_000, installment_count=7,
                       category="MAJOR", cdt_code="D2740", tooth_number=8):
    """Full chain to an ACTIVE payment plan financing an adjudicated claim's
    patient responsibility. Returns (claim, payment_plan)."""
    _, claim = setup_adjudicated_claim(
        ctx, item_fee_cents, category=category, cdt_code=cdt_code, tooth_number=tooth_number
    )
    pp = create_payment_plan(
        ctx["patient"]["id"], claim["id"], claim["version"], installment_count=installment_count
    )
    return claim, pp


# ─── Predeterminations ────────────────────────────────────────────────────────

def create_predetermination(item_id, coverage_id) -> dict:
    return get_success_data(
        api_client.create_predetermination(
            create_predetermination_payload(item_id, coverage_id), BILL
        )
    )


def approve_predetermination(pred_id, **overrides) -> dict:
    return get_success_data(
        api_client.approve_predetermination(pred_id, approve_predetermination_payload(**overrides), BILL)
    )


# ─── Clock ────────────────────────────────────────────────────────────────────

def set_clock(now_iso8601: str, headers=None) -> dict:
    return get_success_data(api_client.set_clock({"now_iso8601": now_iso8601}, headers or BILL))
