"""Composite setup helpers.

Each helper builds preconditions from scratch using only PRD-declared endpoints,
because the server database is reset before every test. All setup calls use
get_success_data() so a setup failure surfaces as a clear "Setup failed".

Identity threading: the Patient role is entity-backed. Any Patient-owned,
ownership-gated call uses make_patient_headers(patient["id"]) with the real id.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_patient_headers,
)
from . import factories

ADMIN = TEST_USERS["clinic_admin_headers"]
AUD = TEST_USERS["audiologist_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]

CLOCK_BASE = "2026-03-01T00:00:00Z"
CLOCK_AFTER_TRIAL = "2026-05-01T00:00:00Z"

_model_code_counter = itertools.count(1)


def _unique_model_code(prefix="DV-AUTO"):
    return f"{prefix}-{next(_model_code_counter)}"


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------

def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_patient(**overrides):
    payload = factories.create_patient_payload(**overrides)
    return get_success_data(api_client.create_patient(payload, ADMIN))


def create_device_model(**overrides):
    if "model_code" not in overrides:
        overrides["model_code"] = _unique_model_code()
    payload = factories.create_device_model_payload(**overrides)
    return get_success_data(api_client.create_device_model(payload, ADMIN))


def create_allowance_benefit(patient_id, **overrides):
    payload = factories.create_allowance_benefit_payload(patient_id, **overrides)
    return get_success_data(api_client.create_allowance_benefit(payload, CLERK))


def create_finalized_evaluation(patient_id, pure_tone_avg_db=50, **overrides):
    payload = factories.create_evaluation_payload(
        patient_id, pure_tone_avg_db=pure_tone_avg_db, **overrides)
    ev = get_success_data(api_client.create_evaluation(payload, AUD))
    return get_success_data(api_client.finalize_evaluation(ev["id"], AUD))


def create_draft_order(patient_id, evaluation_id, device_model_id, **overrides):
    payload = factories.create_order_payload(
        patient_id, evaluation_id, device_model_id, **overrides)
    return get_success_data(api_client.create_order(payload, AUD))


# --------------------------------------------------------------------------
# Tier 1/2: build a patient + finalized eval + active model + an order in a
# requested lifecycle stage.
# --------------------------------------------------------------------------

def setup_order_in_trial(
    *,
    ptag=50,
    model_overrides=None,
    order_overrides=None,
    benefit_overrides=None,
    use_benefit=False,
    clock=CLOCK_BASE,
    dob="1960-01-01",
):
    """Patient + FINALIZED eval + ACTIVE model + order advanced to TRIAL.

    Returns dict: patient, model, evaluation, order, benefit (or None).
    """
    set_clock(clock)
    patient = create_patient(date_of_birth=dob)
    model = create_device_model(**(model_overrides or {}))
    benefit = None
    if use_benefit:
        benefit = create_allowance_benefit(patient["id"], **(benefit_overrides or {}))
    evaluation = create_finalized_evaluation(patient["id"], pure_tone_avg_db=ptag)
    oo = dict(order_overrides or {})
    if use_benefit:
        oo.setdefault("allowance_benefit_id", benefit["id"])
    order = create_draft_order(patient["id"], evaluation["id"], model["id"], **oo)
    order = get_success_data(api_client.start_trial(order["id"], AUD))
    return {
        "patient": patient,
        "model": model,
        "evaluation": evaluation,
        "order": order,
        "benefit": benefit,
    }


def setup_order_purchased(**kwargs):
    """As setup_order_in_trial, then purchase. Returns the same dict with order
    refreshed to PURCHASED."""
    ctx = setup_order_in_trial(**kwargs)
    ctx["order"] = get_success_data(api_client.purchase_order(ctx["order"]["id"], CLERK))
    return ctx


def setup_order_warranty_active(
    *,
    ptag=50,
    model_overrides=None,
    order_overrides=None,
    clock=CLOCK_BASE,
    clock_after=CLOCK_AFTER_TRIAL,
    patch_firmware=None,
):
    """Self-pay order taken through PURCHASED then WARRANTY_ACTIVE (clock advanced
    past the trial window). Optionally PATCH the model firmware before activation.

    Returns dict: patient, model, evaluation, order.
    """
    ctx = setup_order_purchased(
        ptag=ptag, model_overrides=model_overrides, order_overrides=order_overrides,
        clock=clock)
    if patch_firmware is not None:
        get_success_data(api_client.patch_device_model(
            ctx["model"]["id"], {"firmware_version": patch_firmware}, ADMIN))
    set_clock(clock_after)
    ctx["order"] = get_success_data(api_client.activate_warranty(ctx["order"]["id"], CLERK))
    return ctx


# --------------------------------------------------------------------------
# Tier 3: warranty-claim lifecycle shortcuts
# --------------------------------------------------------------------------

def setup_submitted_claim(
    *,
    claim_type="DEFECT",
    assessed_value_cents=50_000,
    incident_date="2026-04-10",
    ptag=50,
    model_overrides=None,
):
    """WARRANTY_ACTIVE order + one SUBMITTED claim. Returns (ctx, claim)."""
    ctx = setup_order_warranty_active(ptag=ptag, model_overrides=model_overrides)
    claim = get_success_data(api_client.create_warranty_claim(
        ctx["order"]["id"],
        factories.create_warranty_claim_payload(
            claim_type=claim_type,
            assessed_value_cents=assessed_value_cents,
            incident_date=incident_date),
        CLERK))
    return ctx, claim


def setup_approved_claim(**kwargs):
    """WARRANTY_ACTIVE order + APPROVED claim. Returns (ctx, claim)."""
    ctx, claim = setup_submitted_claim(**kwargs)
    claim = get_success_data(api_client.approve_warranty_claim(claim["id"], CLERK))
    return ctx, claim


# --------------------------------------------------------------------------
# Tier 4: subscription + cycles
# --------------------------------------------------------------------------

def setup_subscription(
    *,
    unit_price_cents=5_000,
    cadence_days=30,
    by_patient=False,
    clock=CLOCK_BASE,
):
    """PURCHASED order + ACTIVE subscription (first cycle auto-scheduled).

    Returns dict: patient, model, evaluation, order, subscription, cycle1.
    """
    ctx = setup_order_purchased(clock=clock, ptag=45)
    sub_payload = factories.create_subscription_payload(
        ctx["patient"]["id"], ctx["order"]["id"],
        unit_price_cents=unit_price_cents, cadence_days=cadence_days)
    if by_patient:
        sub_headers = make_patient_headers(ctx["patient"]["id"])
    else:
        sub_headers = CLERK
    subscription = get_success_data(api_client.create_subscription(sub_payload, sub_headers))
    cycles, _ = _list_cycles(subscription["id"])
    ctx["subscription"] = subscription
    ctx["cycle1"] = cycles[0] if cycles else None
    return ctx


def _list_cycles(subscription_id):
    from prd_bench_local_runner.testing import validate_paginated
    resp = api_client.list_subscription_cycles(subscription_id, CLERK)
    return validate_paginated(resp)


def schedule_additional_cycles(subscription_id, count):
    """Schedule `count` additional cycles via the next-cycle endpoint. Returns the
    full ordered cycle list afterward."""
    for _ in range(count):
        get_success_data(api_client.schedule_cycle(subscription_id, CLERK))
    cycles, _ = _list_cycles(subscription_id)
    return cycles
