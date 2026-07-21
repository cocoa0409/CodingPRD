"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is reset before each test. Setup calls use
the lenient get_success_data() so setup failures surface as clear "Setup failed".
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS, make_renter_headers, make_agent_headers,
)
from . import factories as F

ADMIN = TEST_USERS["platform_admin_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------

def set_clock(iso, api=api_client):
    return get_success_data(api.set_clock(iso, ADMIN))


def create_property(api=api_client, **overrides):
    """Register a property (ACTIVE by default). Returns the property dict."""
    return get_success_data(api.create_property(F.create_property_payload(**overrides), ADMIN))


def create_renter(property_id, api=api_client, **overrides):
    """Create a PROSPECT renter attached to a property. Returns the renter dict."""
    return get_success_data(
        api.create_renter(F.create_renter_payload(property_id, **overrides), ADMIN))


def submit_application(renter_id, api=api_client, **overrides):
    """Submit an application for a renter. Returns the application dict."""
    return get_success_data(
        api.submit_application(renter_id, F.submit_application_payload(**overrides), ADMIN))


def approve_application(application_id, api=api_client):
    return get_success_data(
        api.decide_application(application_id, {"decision": "APPROVE"}, UNDERWRITER))


def decline_application(application_id, api=api_client):
    return get_success_data(
        api.decide_application(application_id, {"decision": "DECLINE"}, UNDERWRITER))


# --------------------------------------------------------------------------
# Tier 1/2 — enrolled renter (property ACTIVE + renter ENROLLED via approval)
# --------------------------------------------------------------------------

def create_enrolled_renter(api=api_client, portion_cents=100000, income_cents=300000,
                           requested_split_count=2, prior_delinquency_count=0,
                           full_rent_cents=120000, integration_status="ACTIVE",
                           email="renter@example.com", unit_label="Maple #1",
                           remittance_account_ref="acct_1"):
    """Property (ACTIVE by default) + renter approved to ENROLLED.

    Returns dict: property, renter (re-fetched post-cascade), application.
    A PAUSED AutopayMandate is auto-created by the approval cascade.
    """
    prop = create_property(api, full_rent_cents=full_rent_cents,
                           integration_status=integration_status,
                           unit_label=unit_label,
                           remittance_account_ref=remittance_account_ref)
    renter = create_renter(prop["id"], api, portion_rent_cents=portion_cents, email=email)
    app = submit_application(renter["id"], api,
                             reported_monthly_income_cents=income_cents,
                             requested_split_count=requested_split_count,
                             prior_delinquency_count=prior_delinquency_count)
    approve_application(app["id"], api)
    renter = get_success_data(api.get_renter(renter["id"], ADMIN))
    return {"property": prop, "renter": renter, "application": app}


def create_declined_renter(api=api_client, portion_cents=100000, income_cents=120000,
                           requested_split_count=4, prior_delinquency_count=2,
                           full_rent_cents=120000, unit_label="Maple #9",
                           remittance_account_ref="acct_9"):
    """Property ACTIVE + renter DECLINED (SUSPENDED, approved_limit 0).

    Defaults produce risk_score 19 / ratio 1.0 -> declined. Returns property, renter,
    application.
    """
    prop = create_property(api, full_rent_cents=full_rent_cents, integration_status="ACTIVE",
                           unit_label=unit_label, remittance_account_ref=remittance_account_ref)
    renter = create_renter(prop["id"], api, portion_rent_cents=portion_cents)
    app = submit_application(renter["id"], api,
                             reported_monthly_income_cents=income_cents,
                             requested_split_count=requested_split_count,
                             prior_delinquency_count=prior_delinquency_count)
    decline_application(app["id"], api)
    renter = get_success_data(api.get_renter(renter["id"], ADMIN))
    return {"property": prop, "renter": renter, "application": app}


# --------------------------------------------------------------------------
# Tier 2/3 — billing cycles
# --------------------------------------------------------------------------

def create_scheduled_cycle(api=api_client, mode="SPLIT", split_count=2,
                           enrolled=None, **cycle_overrides):
    """Enrolled renter + a SCHEDULED billing cycle. Returns dict:
    property, renter, application, cycle."""
    if enrolled is None:
        enrolled = create_enrolled_renter(api)
    renter = enrolled["renter"]
    if mode == "SPLIT":
        payload = F.create_cycle_payload(renter["id"], mode="SPLIT",
                                         split_count=split_count, **cycle_overrides)
    else:
        payload = F.defer_cycle_payload(renter["id"], **cycle_overrides)
    cycle = get_success_data(api.create_billing_cycle(payload, ADMIN))
    return {**enrolled, "cycle": cycle}


def create_remitted_cycle(api=api_client, mode="SPLIT", split_count=2,
                          enrolled=None, **cycle_overrides):
    """Enrolled renter + SCHEDULED cycle + remit -> REMITTED. Returns dict:
    property, renter, application, cycle, remittance, installments."""
    ctx = create_scheduled_cycle(api, mode=mode, split_count=split_count,
                                 enrolled=enrolled, **cycle_overrides)
    remittance = get_success_data(api.remit_cycle(ctx["cycle"]["id"], ADMIN))
    installments = get_installments(ctx["cycle"]["id"], api)
    cycle = get_success_data(api.get_billing_cycle(ctx["cycle"]["id"], ADMIN))
    return {**ctx, "cycle": cycle, "remittance": remittance, "installments": installments}


def get_installments(cycle_id, api=api_client):
    """Return the cycle's installments as a list (sorted by created_at ascending)."""
    return get_success_data(api.list_cycle_installments(cycle_id, ADMIN))


def charge_installment(installment_id, api=api_client, method="MANUAL", outcome="SUCCEED"):
    return get_success_data(
        api.charge_installment(installment_id, F.charge_payload(method, outcome), ADMIN))


# --------------------------------------------------------------------------
# Tier 4/5 — delinquency
# --------------------------------------------------------------------------

def create_delinquent_case(api=api_client, pay_first_installment=True,
                           assess_clock="2026-07-21T00:00:00Z", enrolled=None):
    """Remitted SPLIT n=2 cycle, optionally pay installment1, advance clock, and
    assess-delinquency to open an OPEN case. Returns dict:
    property, renter, application, cycle, installments, case."""
    set_clock("2026-07-01T00:00:00Z", api)
    ctx = create_remitted_cycle(api, mode="SPLIT", split_count=2, enrolled=enrolled)
    installments = ctx["installments"]
    if pay_first_installment:
        charge_installment(installments[0]["id"], api, "MANUAL", "SUCCEED")
    set_clock(assess_clock, api)
    get_success_data(api.assess_delinquency(ctx["cycle"]["id"], ADMIN))
    cases = get_success_data(
        api.list_delinquency_cases(ADMIN, params={"cycle_id": ctx["cycle"]["id"]}))
    case = cases[0]
    return {**ctx, "installments": installments, "case": case}


def open_outreach_case(api=api_client, agent_id="agent_a", assess_clock="2026-07-21T00:00:00Z"):
    """Delinquent case advanced to IN_OUTREACH by an agent's OUTREACH action.
    Returns dict including case (re-fetched) and agent_id."""
    ctx = create_delinquent_case(api, pay_first_installment=True, assess_clock=assess_clock)
    case_id = ctx["case"]["id"]
    get_success_data(api.record_recovery_action(
        case_id, {"action_type": "OUTREACH", "note": "first contact"},
        make_agent_headers(agent_id)))
    case = get_success_data(api.get_delinquency_case(case_id, ADMIN))
    return {**ctx, "case": case, "agent_id": agent_id}


def renter_headers(renter_id):
    return make_renter_headers(renter_id)
