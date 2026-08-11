"""Composite setup helpers for the low-vision assistive-technology service.

Every fixture builds its preconditions from scratch against an empty database,
using only PRD-declared endpoints. Setup calls use the lenient get_success_data
validator so a setup failure surfaces as a clear error rather than a confusing
assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_client_payload,
    create_referral_payload,
    create_evaluation_payload,
    create_device_model_payload,
    create_device_unit_payload,
    create_device_order_payload,
    create_training_plan_payload,
    create_training_session_payload,
    create_funding_authorization_payload,
    create_claim_payload,
    claim_line,
    create_repair_ticket_payload,
    create_subscription_payload,
    create_outcome_assessment_payload,
)
from .test_users import (
    TEST_USERS,
    make_funding_coordinator_headers,
    make_payer_adjudicator_headers,
    make_billing_specialist_headers,
)

INTAKE = TEST_USERS["intake_coordinator_headers"]
SPECIALIST = TEST_USERS["vision_specialist_headers"]
ADMIN = TEST_USERS["clinic_admin_headers"]
TECH = TEST_USERS["repair_technician_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]


# ---------------------------------------------------------------------------
# Tier 1: intake / clinical spine
# ---------------------------------------------------------------------------

def create_client(**overrides):
    """Create a client (starts INTAKE). Returns the client dict."""
    resp = api_client.create_client(create_client_payload(**overrides), INTAKE)
    return get_success_data(resp)


def create_client_with_accepted_referral(source_type="SELF", referring_party="self", **client_overrides):
    """Client + referral decided ACCEPT; the client is ACTIVE afterwards.

    Returns (client, referral)."""
    client = create_client(**client_overrides)
    ref = get_success_data(api_client.create_referral(
        create_referral_payload(client["id"], source_type=source_type, referring_party=referring_party),
        INTAKE,
    ))
    get_success_data(api_client.decide_referral(ref["id"], {"decision": "ACCEPT"}, INTAKE))
    client = get_success_data(api_client.get_client(client["id"], INTAKE))
    return client, ref


def create_evaluation(client_id, referral_id, **overrides):
    """Create a DRAFT evaluation under the OCC guard (fetches the live client
    version first). Returns the evaluation dict."""
    client = get_success_data(api_client.get_client(client_id, SPECIALIST))
    payload = create_evaluation_payload(client_id, referral_id, client["version"], **overrides)
    return get_success_data(api_client.create_evaluation(payload, SPECIALIST))


def create_finalized_evaluation(client_id, referral_id, **overrides):
    """Create + finalize an evaluation. Returns the FINALIZED evaluation."""
    ev = create_evaluation(client_id, referral_id, **overrides)
    return get_success_data(api_client.finalize_evaluation(ev["id"], SPECIALIST))


# ---------------------------------------------------------------------------
# Tier 2: catalog / stock
# ---------------------------------------------------------------------------

def create_device_model(**overrides):
    resp = api_client.create_device_model(create_device_model_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_device_unit(device_model_id, **overrides):
    resp = api_client.create_device_unit(create_device_unit_payload(device_model_id, **overrides), ADMIN)
    return get_success_data(resp)


def create_model_with_units(model_overrides=None, units=()):
    """Model plus a list of units. `units` is an iterable of unit override dicts.

    Returns (model, [unit, ...])."""
    model = create_device_model(**(model_overrides or {}))
    created = [create_device_unit(model["id"], **u) for u in units]
    return model, created


# ---------------------------------------------------------------------------
# Tier 3: orders
# ---------------------------------------------------------------------------

def setup_client_with_finalized_evaluation(category="MAGNIFIER", source_type="SELF"):
    """ACTIVE client + ACCEPTED referral + FINALIZED evaluation.

    Returns (client, referral, evaluation)."""
    client, ref = create_client_with_accepted_referral(source_type=source_type)
    ev = create_finalized_evaluation(client["id"], ref["id"], recommended_category=category)
    return client, ref, ev


def place_order(client_id, evaluation_id, device_model_id, **overrides):
    """Place a device order (PLACED). Returns the order dict."""
    payload = create_device_order_payload(client_id, evaluation_id, device_model_id, **overrides)
    return get_success_data(api_client.create_device_order(payload, SPECIALIST))


def place_and_allocate_order(client_id, evaluation_id, device_model_id, unit_id=None, **overrides):
    """Place + allocate an order (ACTIVE). Explicit unit when unit_id given,
    deterministic auto-select otherwise. Returns the allocated order."""
    order = place_order(client_id, evaluation_id, device_model_id, **overrides)
    payload = {"device_unit_id": unit_id} if unit_id else {}
    return get_success_data(api_client.allocate_device_order(order["id"], payload, SPECIALIST))


def setup_allocated_purchase(category="MAGNIFIER", unit_condition="NEW", **model_overrides):
    """Full spine: ACTIVE client, FINALIZED evaluation, model with one unit,
    PURCHASE order allocated. Returns dict of the key entities."""
    client, ref, ev = setup_client_with_finalized_evaluation(category=category)
    model = create_device_model(category=category, **model_overrides)
    unit = create_device_unit(model["id"], condition=unit_condition)
    order = place_and_allocate_order(client["id"], ev["id"], model["id"], unit_id=unit["id"])
    return {"client": client, "referral": ref, "evaluation": ev,
            "model": model, "unit": unit, "order": order}


# ---------------------------------------------------------------------------
# Tier 4: funding spine
# ---------------------------------------------------------------------------

def create_authorization(client_id, coordinator_id="fc-1", **overrides):
    """Create a DRAFT funding authorization. Returns the authorization."""
    resp = api_client.create_funding_authorization(
        create_funding_authorization_payload(client_id, **overrides),
        make_funding_coordinator_headers(coordinator_id),
    )
    return get_success_data(resp)


def create_submitted_authorization(client_id, coordinator_id="fc-1", **overrides):
    """Create + submit. Returns the SUBMITTED authorization."""
    auth = create_authorization(client_id, coordinator_id=coordinator_id, **overrides)
    return get_success_data(api_client.submit_funding_authorization(
        auth["id"], make_funding_coordinator_headers(coordinator_id)))


def create_approved_authorization(client_id, coordinator_id="fc-1", adjudicator_id="pa-1", **overrides):
    """Create + submit + adjudicate APPROVE. Returns the APPROVED authorization."""
    auth = create_submitted_authorization(client_id, coordinator_id=coordinator_id, **overrides)
    return get_success_data(api_client.adjudicate_funding_authorization(
        auth["id"], {"decision": "APPROVE"}, make_payer_adjudicator_headers(adjudicator_id)))


def create_claim(funding_authorization_id, device_order_id, **overrides):
    """Create a DRAFT claim. Returns the claim."""
    resp = api_client.create_claim(
        create_claim_payload(funding_authorization_id, device_order_id, **overrides), BILLING)
    return get_success_data(resp)


def create_submitted_claim(funding_authorization_id, device_order_id, billing_id="bs-1", **overrides):
    """Create + submit a claim. Returns the SUBMITTED claim."""
    claim = create_claim(funding_authorization_id, device_order_id, **overrides)
    return get_success_data(api_client.submit_claim(claim["id"], make_billing_specialist_headers(billing_id)))


def setup_approved_funding_scenario(payer_type="INSURANCE", authorized_amount_cents=50000,
                                    category="MAGNIFIER", valid_from="2026-05-01T00:00:00Z",
                                    valid_until="2026-12-31T23:59:59Z"):
    """Allocated PURCHASE order plus an APPROVED authorization for its client.

    Returns dict with client/referral/evaluation/model/unit/order/authorization."""
    ctx = setup_allocated_purchase(category=category)
    auth = create_approved_authorization(
        ctx["client"]["id"], payer_type=payer_type,
        authorized_amount_cents=authorized_amount_cents,
        valid_from=valid_from, valid_until=valid_until)
    ctx["authorization"] = auth
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: training
# ---------------------------------------------------------------------------

def setup_training_plan(total_sessions=3, category="MAGNIFIER"):
    """Allocated PURCHASE order plus a PLANNED training plan.

    Returns dict with the order spine plus plan."""
    ctx = setup_allocated_purchase(category=category)
    plan = get_success_data(api_client.create_training_plan(
        create_training_plan_payload(ctx["client"]["id"], ctx["order"]["id"], total_sessions=total_sessions),
        SPECIALIST))
    ctx["plan"] = plan
    return ctx


def schedule_session(plan_id, instructor_user_id="inst-1",
                     scheduled_start="2026-05-04T10:00:00Z", scheduled_end="2026-05-04T11:00:00Z"):
    """Schedule one session. Returns the SCHEDULED session."""
    return get_success_data(api_client.create_training_session(
        plan_id,
        create_training_session_payload(instructor_user_id=instructor_user_id,
                                        scheduled_start=scheduled_start,
                                        scheduled_end=scheduled_end),
        SPECIALIST))


# ---------------------------------------------------------------------------
# Tier 6: repair
# ---------------------------------------------------------------------------

def create_repair_ticket(device_unit_id, **overrides):
    resp = api_client.create_repair_ticket(create_repair_ticket_payload(device_unit_id, **overrides), TECH)
    return get_success_data(resp)


def advance_ticket(ticket_id, action, needs_loaner=None):
    payload = {"action": action}
    if needs_loaner is not None:
        payload["needs_loaner"] = needs_loaner
    return get_success_data(api_client.advance_repair_ticket(ticket_id, payload, TECH))


def setup_diagnosed_ticket(with_loaner_unit=False, model_overrides=None):
    """Model with a broken NEW unit (and optionally a LOANER unit) plus a
    repair ticket advanced to DIAGNOSED.

    Returns dict with model/broken_unit/loaner_unit/ticket."""
    model = create_device_model(**(model_overrides or {"category": "CCTV", "list_price_cents": 100000,
                                                       "name": "CCTV Pro 24"}))
    broken = create_device_unit(model["id"], condition="NEW")
    loaner = create_device_unit(model["id"], condition="LOANER") if with_loaner_unit else None
    ticket = create_repair_ticket(broken["id"])
    advance_ticket(ticket["id"], "DIAGNOSE")
    return {"model": model, "broken_unit": broken, "loaner_unit": loaner, "ticket": ticket}


# ---------------------------------------------------------------------------
# Tier 7: subscriptions / clock
# ---------------------------------------------------------------------------

def create_screen_reader_model(monthly=25000):
    return create_device_model(name="ReadAloud SR", category="SCREEN_READER",
                               list_price_cents=0, subscription_monthly_cents=monthly)


def create_subscription(client_id, device_model_id, **overrides):
    resp = api_client.create_subscription(
        create_subscription_payload(client_id, device_model_id, **overrides), BILLING)
    return get_success_data(resp)


def setup_active_subscription(monthly=25000, period_start="2026-05-01T00:00:00Z"):
    """Client + screen-reader model + ACTIVE subscription. Returns dict."""
    client = create_client()
    model = create_screen_reader_model(monthly=monthly)
    sub = create_subscription(client["id"], model["id"], period_start=period_start)
    return {"client": client, "model": model, "subscription": sub}


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def run_daily():
    return get_success_data(api_client.run_daily(ADMIN))
