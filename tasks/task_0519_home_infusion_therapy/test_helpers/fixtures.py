"""Composite setup helpers.

Each helper builds a multi-step precondition state from scratch using only
PRD-declared endpoints, returning the captured ids tests need. All setup calls
go through get_success_data() (lenient 2xx validator) so a broken precondition
surfaces as a clear "Setup failed" rather than an opaque assertion error.

The test harness restarts the server (empty database) before every test, so every
helper here builds its world from nothing.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_visiting_nurse_headers
from . import factories as F


# Convenience header aliases (opaque roles use shared constants).
INTAKE = TEST_USERS["intake_coordinator_headers"]
PHARM = TEST_USERS["pharmacist_headers"]
AUTH = TEST_USERS["auth_specialist_headers"]
MD = TEST_USERS["medical_director_headers"]
BILLER = TEST_USERS["biller_headers"]
WAREHOUSE = TEST_USERS["warehouse_clerk_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock + reference data
# ---------------------------------------------------------------------------
def set_clock(iso="2026-06-09T00:00:00Z"):
    """Advance the logical clock. Reference-data tests that touch temporal
    windows pin the clock first."""
    get_success_data(api_client.set_clock(iso, PHARM))


def create_drug(**overrides) -> dict:
    return get_success_data(api_client.create_drug(F.create_drug_payload(**overrides), PHARM))


def create_payer_plan(**overrides) -> dict:
    return get_success_data(
        api_client.create_payer_plan(F.create_payer_plan_payload(**overrides), BILLER)
    )


def create_nurse(**overrides) -> dict:
    return get_success_data(api_client.create_nurse(F.create_nurse_payload(**overrides), INTAKE))


def create_pump(**overrides) -> dict:
    return get_success_data(api_client.create_pump(F.create_pump_payload(**overrides), WAREHOUSE))


def create_patient(plan_id, **overrides) -> dict:
    payload = F.create_patient_payload(payer_plan_id=plan_id, **overrides)
    return get_success_data(api_client.create_patient(payload, INTAKE))


def create_accepted_referral(patient_id, **overrides) -> dict:
    ref = get_success_data(
        api_client.create_referral(
            F.create_referral_payload(patient_id=patient_id, **overrides), INTAKE
        )
    )
    get_success_data(api_client.accept_referral(ref["id"], INTAKE))
    return get_success_data(api_client.get_referral(ref["id"], INTAKE))


# ---------------------------------------------------------------------------
# Tier 1: order in a target lifecycle state
# ---------------------------------------------------------------------------
def setup_draft_order(
    drug_overrides=None,
    plan_overrides=None,
    order_overrides=None,
    service_state="CA",
    clock="2026-06-09T00:00:00Z",
):
    """Reference data + ACCEPTED referral + a DRAFT infusion order.

    Returns a dict with keys: drug, plan, patient, referral, order (and nurse=None).
    """
    set_clock(clock)
    drug = create_drug(**(drug_overrides or {}))
    plan = create_payer_plan(**(plan_overrides or {}))
    patient = create_patient(plan["id"], service_state=service_state)
    referral = create_accepted_referral(patient["id"])
    order = get_success_data(
        api_client.create_order(
            F.create_order_payload(
                referral_id=referral["id"], drug_id=drug["id"], **(order_overrides or {})
            ),
            PHARM,
        )
    )
    return {
        "drug": drug,
        "plan": plan,
        "patient": patient,
        "referral": referral,
        "order": order,
    }


def setup_released_nonspecialty_order(
    drug_overrides=None, plan_overrides=None, order_overrides=None, clock="2026-06-09T00:00:00Z"
):
    """A non-specialty order submitted straight to RELEASED.

    Returns the dict from setup_draft_order with the order refreshed to RELEASED.
    """
    ctx = setup_draft_order(
        drug_overrides={"is_specialty": False, **(drug_overrides or {})},
        plan_overrides=plan_overrides,
        order_overrides=order_overrides,
        clock=clock,
    )
    get_success_data(api_client.submit_order(ctx["order"]["id"], PHARM))
    ctx["order"] = get_success_data(api_client.get_order(ctx["order"]["id"], PHARM))
    return ctx


def setup_pending_auth_order(
    drug_overrides=None, plan_overrides=None, order_overrides=None, clock="2026-06-09T00:00:00Z"
):
    """A specialty order submitted to PENDING_AUTH with a SUBMITTED prior auth.

    Returns the setup dict plus 'auth'.
    """
    ctx = setup_draft_order(
        drug_overrides={"is_specialty": True, **(drug_overrides or {})},
        plan_overrides=plan_overrides,
        order_overrides=order_overrides,
        clock=clock,
    )
    get_success_data(api_client.submit_order(ctx["order"]["id"], PHARM))
    ctx["order"] = get_success_data(api_client.get_order(ctx["order"]["id"], PHARM))
    auth = get_success_data(
        api_client.create_prior_auth(
            F.create_prior_auth_payload(order_id=ctx["order"]["id"], requested_units=10), AUTH
        )
    )
    ctx["auth"] = auth
    return ctx


def setup_released_specialty_order(
    approved_units=14,
    requested_units=14,
    drug_overrides=None,
    plan_overrides=None,
    order_overrides=None,
    clock="2026-06-09T00:00:00Z",
):
    """A specialty order RELEASED via an approved prior authorization.

    Returns the setup dict plus 'auth'.
    """
    ctx = setup_draft_order(
        drug_overrides={"is_specialty": True, **(drug_overrides or {})},
        plan_overrides=plan_overrides,
        order_overrides=order_overrides,
        clock=clock,
    )
    get_success_data(api_client.submit_order(ctx["order"]["id"], PHARM))
    auth = get_success_data(
        api_client.create_prior_auth(
            F.create_prior_auth_payload(
                order_id=ctx["order"]["id"], requested_units=requested_units
            ),
            AUTH,
        )
    )
    get_success_data(
        api_client.approve_prior_auth(auth["id"], {"approved_units": approved_units}, AUTH)
    )
    ctx["auth"] = get_success_data(api_client.get_prior_auth(auth["id"], AUTH))
    ctx["order"] = get_success_data(api_client.get_order(ctx["order"]["id"], PHARM))
    return ctx


# ---------------------------------------------------------------------------
# Tier 2: visits and order activation
# ---------------------------------------------------------------------------
def add_nurse(ctx, license_state="CA", **overrides) -> dict:
    """Register a nurse and stash it on the context under 'nurse'."""
    nurse = create_nurse(license_state=license_state, **overrides)
    ctx["nurse"] = nurse
    return nurse


def schedule_visit(order_id, nurse_id, **overrides) -> dict:
    """Schedule a nursing visit (acting as the entity-backed VisitingNurse)."""
    headers = make_visiting_nurse_headers(nurse_id)
    return get_success_data(
        api_client.create_visit(
            F.create_visit_payload(order_id=order_id, nurse_id=nurse_id, **overrides), headers
        )
    )


def complete_visit(visit_id, nurse_id) -> dict:
    headers = make_visiting_nurse_headers(nurse_id)
    return get_success_data(api_client.complete_visit(visit_id, headers))


def setup_active_order_with_completed_visits(
    num_completed=1,
    scheduled_days=5,
    drug_overrides=None,
    plan_overrides=None,
    order_overrides=None,
    specialty=False,
    approved_units=14,
    clock="2026-06-09T00:00:00Z",
):
    """A RELEASED order brought to ACTIVE by completing `num_completed` visits.

    Visits are spaced one day apart starting 2026-06-10T09:00Z, durations 120 min,
    so the symmetric nurse travel buffer never collides. After the first completion
    the order is ACTIVE; administered_days equals num_completed.

    Returns a dict: drug, plan, patient, referral, nurse, order (ACTIVE), visits, auth?
    """
    order_overrides = {"scheduled_days": scheduled_days, **(order_overrides or {})}
    if specialty:
        ctx = setup_released_specialty_order(
            approved_units=approved_units,
            requested_units=approved_units,
            drug_overrides=drug_overrides,
            plan_overrides=plan_overrides,
            order_overrides=order_overrides,
            clock=clock,
        )
    else:
        ctx = setup_released_nonspecialty_order(
            drug_overrides=drug_overrides,
            plan_overrides=plan_overrides,
            order_overrides=order_overrides,
            clock=clock,
        )
    nurse = add_nurse(ctx, license_state=ctx["patient"]["service_state"])
    visits = []
    for i in range(num_completed):
        day = 10 + i
        v = schedule_visit(
            ctx["order"]["id"],
            nurse["id"],
            start_at=f"2026-06-{day:02d}T09:00:00Z",
            duration_min=120,
        )
        visits.append(v)
    for v in visits:
        complete_visit(v["id"], nurse["id"])
    ctx["visits"] = visits
    ctx["order"] = get_success_data(api_client.get_order(ctx["order"]["id"], PHARM))
    return ctx


def get_order_version(order_id) -> int:
    return get_success_data(api_client.get_order(order_id, BILLER))["version"]


# ---------------------------------------------------------------------------
# Tier 3: compounding
# ---------------------------------------------------------------------------
def setup_compounded_order(
    daily_dose_mg=2000,
    scheduled_days=7,
    lot_total_vials=100,
    drug_overrides=None,
    plan_overrides=None,
    clock="2026-06-09T00:00:00Z",
    activate=True,
):
    """A non-specialty order with one COMPOUNDED compound (vials drawn).

    With daily_dose_mg=2000, scheduled_days=7, vial_size_mg=1000 the batch reserves
    14 vials (ceil(2000*7/1000)). The compound occupies pump [2026-06-10T09:00Z,
    2026-06-17T09:00Z). If activate is True, one visit is completed (order ACTIVE).

    Returns dict: drug, plan, patient, referral, nurse, pump, order, compound, visits.
    """
    drug_overrides = {"vial_size_mg": 1000, "lot_total_vials": lot_total_vials, **(drug_overrides or {})}
    ctx = setup_released_nonspecialty_order(
        drug_overrides=drug_overrides,
        plan_overrides=plan_overrides,
        order_overrides={"daily_dose_mg": daily_dose_mg, "scheduled_days": scheduled_days},
        clock=clock,
    )
    pump = create_pump()
    ctx["pump"] = pump
    compound = get_success_data(
        api_client.create_compound(
            F.create_compound_payload(
                order_id=ctx["order"]["id"],
                pump_id=pump["id"],
                delivery_at="2026-06-10T09:00:00Z",
                retrieval_at="2026-06-17T09:00:00Z",
            ),
            PHARM,
        )
    )
    get_success_data(api_client.compound_compound(compound["id"], PHARM))
    ctx["compound"] = get_success_data(api_client.get_compound(compound["id"], PHARM))

    ctx["visits"] = []
    if activate:
        nurse = add_nurse(ctx, license_state=ctx["patient"]["service_state"])
        v = schedule_visit(
            ctx["order"]["id"],
            nurse["id"],
            start_at="2026-06-10T11:00:00Z",
            duration_min=120,
        )
        complete_visit(v["id"], nurse["id"])
        ctx["visits"].append(v)
    ctx["order"] = get_success_data(api_client.get_order(ctx["order"]["id"], PHARM))
    ctx["drug"] = get_success_data(api_client.get_drug(ctx["drug"]["id"], PHARM))
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: adverse-event hold
# ---------------------------------------------------------------------------
def report_adverse_event(order_id, nurse_id=None, reporter_headers=None, **overrides) -> dict:
    """Report an adverse event. Defaults to reporting as the entity-backed nurse;
    pass reporter_headers to report under a different identity (e.g. MedicalDirector)."""
    if reporter_headers is None:
        reporter_headers = make_visiting_nurse_headers(nurse_id)
    return get_success_data(
        api_client.create_adverse_event(
            F.create_adverse_event_payload(order_id=order_id, **overrides), reporter_headers
        )
    )


def setup_order_on_hold_via_ae(
    scheduled_days=5,
    severity_grade=3,
    reaction_count=2,
    vital_instability=1,
    drug_overrides=None,
    plan_overrides=None,
    reporter="nurse",
    clock="2026-06-09T00:00:00Z",
):
    """An ACTIVE order driven to ON_HOLD by a high-severity adverse event.

    One visit is completed (order ACTIVE), then an adverse event scoring >= 7 is
    reported, auto-holding the order with hold_reason ADVERSE_EVENT. The reporter is
    the entity-backed nurse by default ('nurse') or the MedicalDirector md-001
    ('md') so segregation-of-duties tests can vary the reporting identity.

    Returns dict: ..., order (ON_HOLD), nurse, adverse_event.
    """
    ctx = setup_active_order_with_completed_visits(
        num_completed=1,
        scheduled_days=scheduled_days,
        drug_overrides=drug_overrides,
        plan_overrides=plan_overrides,
        clock=clock,
    )
    nurse = ctx["nurse"]
    first_visit_id = ctx["visits"][0]["id"]
    if reporter == "md":
        reporter_headers = MD
        ae = report_adverse_event(
            ctx["order"]["id"],
            reporter_headers=reporter_headers,
            visit_id=first_visit_id,
            severity_grade=severity_grade,
            reaction_count=reaction_count,
            vital_instability=vital_instability,
        )
    else:
        ae = report_adverse_event(
            ctx["order"]["id"],
            nurse_id=nurse["id"],
            visit_id=first_visit_id,
            severity_grade=severity_grade,
            reaction_count=reaction_count,
            vital_instability=vital_instability,
        )
    ctx["adverse_event"] = get_success_data(
        api_client.get_adverse_event(ae["id"], MD)
    )
    ctx["order"] = get_success_data(api_client.get_order(ctx["order"]["id"], MD))
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: claims / billing
# ---------------------------------------------------------------------------
def create_estimate_claim(order_id) -> dict:
    """Create a DRAFT ESTIMATE claim pinning the current order version."""
    ver = get_order_version(order_id)
    return get_success_data(
        api_client.create_claim(
            F.create_claim_payload(order_id=order_id, expected_order_version=ver), BILLER
        )
    )


def setup_posted_claim(
    daily_dose_mg=2000,
    scheduled_days=1,
    num_completed=1,
    drug_overrides=None,
    plan_overrides=None,
    clock="2026-06-09T00:00:00Z",
):
    """An order billed by a POSTED (FINAL) claim that debited the accumulators.

    Returns dict: ..., order, plan, claim (POSTED).
    """
    ctx = setup_active_order_with_completed_visits(
        num_completed=num_completed,
        scheduled_days=scheduled_days,
        drug_overrides={"vial_size_mg": 1000, **(drug_overrides or {})},
        plan_overrides=plan_overrides,
        order_overrides={"daily_dose_mg": daily_dose_mg},
        clock=clock,
    )
    claim = create_estimate_claim(ctx["order"]["id"])
    get_success_data(api_client.post_claim(claim["id"], BILLER))
    ctx["claim"] = get_success_data(api_client.get_claim(claim["id"], BILLER))
    ctx["plan"] = get_success_data(api_client.get_payer_plan(ctx["plan"]["id"], BILLER))
    return ctx
