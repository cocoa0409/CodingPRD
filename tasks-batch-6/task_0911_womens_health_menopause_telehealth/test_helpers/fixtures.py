"""Composite setup helpers.

These encapsulate the multi-step preambles that most test claims require:
onboarding a patient/provider, submitting an intake, completing a visit,
writing a prescription, walking refills through the lifecycle, adjudicating
charges, and driving the logical clock.

All setup calls use get_success_data() (lenient) so a broken precondition
surfaces as a clear "Setup failed" rather than a confusing assertion later.
Identity is threaded: entity-backed Patient/Provider calls use the actual
entity id via make_patient_headers / make_provider_headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .factories import (
    create_patient_payload,
    create_provider_payload,
    create_insurance_policy_payload,
    create_intake_payload,
    create_visit_payload,
    create_prescription_payload,
    create_lab_order_payload,
    create_subscription_payload,
)
from .test_users import (
    make_patient_headers,
    make_provider_headers,
    billing_admin_headers,
    care_coordinator_headers,
)


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------
def set_clock(api, iso: str):
    return get_success_data(api.set_clock(iso, billing_admin_headers()))


def register_patient(api, **overrides) -> dict:
    return get_success_data(
        api.create_patient(create_patient_payload(**overrides), care_coordinator_headers()))


def register_provider(api, **overrides) -> dict:
    return get_success_data(
        api.create_provider(create_provider_payload(**overrides), care_coordinator_headers()))


def attach_policy(api, patient_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_insurance_policy(patient_id, create_insurance_policy_payload(**overrides),
                                    billing_admin_headers()))


def create_draft_intake(api, patient_id: str, **overrides) -> dict:
    ph = make_patient_headers(patient_id)
    return get_success_data(
        api.create_intake_assessment(patient_id, create_intake_payload(**overrides), ph))


def create_submitted_intake(api, patient_id: str, **overrides) -> dict:
    """Create + submit an intake. Returns the submitted (CLEARED/FLAGGED) intake."""
    ph = make_patient_headers(patient_id)
    intake = create_draft_intake(api, patient_id, **overrides)
    return get_success_data(api.submit_intake(intake["id"], ph))


def create_completed_visit(api, patient_id, provider_id, intake_id,
                           scheduled_start=None, scheduled_end=None) -> dict:
    ph = make_patient_headers(patient_id)
    payload = create_visit_payload(
        patient_id=patient_id, provider_id=provider_id, intake_assessment_id=intake_id,
        **{k: v for k, v in (("scheduled_start", scheduled_start),
                             ("scheduled_end", scheduled_end)) if v is not None})
    visit = get_success_data(api.create_visit(payload, ph))
    return get_success_data(api.complete_visit(visit["id"], make_provider_headers(provider_id)))


# --------------------------------------------------------------------------
# Tier 2/3: full active-prescription scenario
# --------------------------------------------------------------------------
def setup_active_prescription(api, *, billing_mode="CASH", policy=None,
                              rx_overrides=None, patient_overrides=None,
                              provider_overrides=None,
                              scheduled_start=None, scheduled_end=None) -> dict:
    """Onboard patient (+optional policy) and provider, submit a clean intake,
    complete a visit, and write an ACTIVE prescription with an auto CarePlan.

    Returns a context dict with the created entities and threaded headers.
    """
    patient = register_patient(api, billing_mode=billing_mode, **(patient_overrides or {}))
    if policy is not None:
        attach_policy(api, patient["id"], **policy)
    provider = register_provider(api, **(provider_overrides or {}))
    ph = make_patient_headers(patient["id"])
    prov_h = make_provider_headers(provider["id"])

    intake = create_submitted_intake(api, patient["id"])
    visit = create_completed_visit(api, patient["id"], provider["id"], intake["id"],
                                   scheduled_start, scheduled_end)
    rx = get_success_data(
        api.create_prescription(create_prescription_payload(visit_id=visit["id"],
                                                             **(rx_overrides or {})), prov_h))
    return {
        "patient": patient,
        "provider": provider,
        "intake": intake,
        "visit": visit,
        "prescription": rx,
        "care_plan_id": rx.get("care_plan_id"),
        "patient_headers": ph,
        "provider_headers": prov_h,
    }


# --------------------------------------------------------------------------
# Tier 3: refill lifecycle shortcuts
# --------------------------------------------------------------------------
def request_refill(api, ctx) -> dict:
    return get_success_data(api.request_refill(ctx["prescription"]["id"], ctx["patient_headers"]))


def add_approved_refill(api, ctx) -> dict:
    refill = request_refill(api, ctx)
    return get_success_data(api.approve_refill(refill["id"], ctx["provider_headers"]))


def add_fulfilled_refill(api, ctx) -> dict:
    """Request -> approve -> fulfill one refill. Returns the FULFILLED refill
    (which carries charge_id)."""
    refill = request_refill(api, ctx)
    get_success_data(api.approve_refill(refill["id"], ctx["provider_headers"]))
    return get_success_data(api.fulfill_refill(refill["id"], ctx["provider_headers"]))


def add_adjudicated_refill_charge(api, ctx) -> dict:
    """Fulfill a refill then adjudicate its charge. Returns the ADJUDICATED
    charge."""
    fulfilled = add_fulfilled_refill(api, ctx)
    return get_success_data(api.adjudicate_charge(fulfilled["charge_id"],
                                                  billing_admin_headers()))


def add_lab_order(api, ctx, panel_type="HORMONE") -> dict:
    return get_success_data(
        api.create_lab_order(ctx["prescription"]["id"],
                             create_lab_order_payload(panel_type=panel_type),
                             ctx["provider_headers"]))


def resolve_lab(api, ctx, lab_id, result="NORMAL") -> dict:
    return get_success_data(
        api.resolve_lab_order(lab_id, {"result": result}, ctx["provider_headers"]))


# --------------------------------------------------------------------------
# Subscriptions
# --------------------------------------------------------------------------
def create_subscription(api, patient_id, expected_version, plan_tier="ESSENTIAL") -> dict:
    return get_success_data(
        api.create_subscription(
            create_subscription_payload(patient_id=patient_id, plan_tier=plan_tier,
                                        expected_patient_version=expected_version),
            make_patient_headers(patient_id)))
