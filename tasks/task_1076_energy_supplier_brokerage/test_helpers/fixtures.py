"""Composite setup helpers.

Every test runs against a freshly-restarted, empty database, so each fixture
builds all of its preconditions from scratch using only PRD-declared endpoints.
Setup calls use the lenient get_success_data() so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: BrokerAgent/BrokerManager/Supplier/Customer are entity-backed
roles — ownership-gated calls always use make_*_headers(entity_id).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_agent_headers, make_manager_headers, make_supplier_headers,
    make_customer_headers, ops_headers,
)
from . import factories as f


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------

def new_agent(api, full_name="Agent A", email="a@brk.co") -> dict:
    r = api.create_broker_user(
        f.create_broker_user_payload(full_name=full_name, email=email, staff_role="AGENT"),
        ops_headers(),
    )
    return get_success_data(r)


def new_manager(api, approval_limit=100000000, full_name="Mgr One", email="m1@brk.co") -> dict:
    r = api.create_broker_user(
        f.create_broker_user_payload(
            full_name=full_name, email=email, staff_role="MANAGER",
            approval_limit_cents=approval_limit,
        ),
        ops_headers(),
    )
    return get_success_data(r)


def new_customer(api, agent_id, **overrides) -> dict:
    r = api.create_customer(f.create_customer_payload(**overrides), make_agent_headers(agent_id))
    return get_success_data(r)


def new_supplier(api, name="PowerCo", service_states=None) -> dict:
    r = api.create_supplier(
        f.create_supplier_payload(name=name, service_states=service_states or ["TX"]),
        ops_headers(),
    )
    return get_success_data(r)


def new_account(api, customer_id, agent_id, **overrides) -> dict:
    r = api.create_account(
        f.create_account_payload(customer_id, agent_id, **overrides),
        make_agent_headers(agent_id),
    )
    return get_success_data(r)


def draft_loa(api, account_id, agent_id, **overrides) -> dict:
    r = api.create_authorization(
        f.create_authorization_payload(account_id, **overrides),
        make_agent_headers(agent_id),
    )
    return get_success_data(r)


def sign_loa(api, loa_id, customer_id) -> dict:
    r = api.sign_authorization(loa_id, make_customer_headers(customer_id))
    return get_success_data(r)


def add_usage(api, account_id, agent_id, period_month, usage_kwh, is_actual) -> dict:
    r = api.create_usage_record(
        f.create_usage_record_payload(account_id, period_month, usage_kwh, is_actual=is_actual),
        make_agent_headers(agent_id),
    )
    return get_success_data(r)


def verify_account(api, account_id, agent_id) -> dict:
    r = api.verify_account(account_id, make_agent_headers(agent_id))
    return get_success_data(r)


def set_clock(api, iso) -> dict:
    r = api.set_clock({"to_iso8601": iso}, ops_headers())
    return get_success_data(r)


def rfp_version(api, rfp_id, headers) -> int:
    r = api.get_rfp(rfp_id, headers)
    return get_success_data(r)["version"]


# ---------------------------------------------------------------------------
# Tier 1/2: verified account
# ---------------------------------------------------------------------------

def setup_verified_account(api, *, est_usage=60000, loa_scope="USAGE_AND_ENROLL",
                           loa_expires="2028-01-01T00:00:00Z", with_manager=False,
                           with_second_manager=False, manager_limit=100000000,
                           account_overrides=None) -> dict:
    """Agent + customer + account (VERIFIED) under a SIGNED LOA and one usage row.

    Returns a ctx dict of entity records and their ownership-threaded headers.
    """
    agent = new_agent(api)
    customer = new_customer(api, agent["id"])
    account = new_account(api, customer["id"], agent["id"],
                          estimated_annual_usage_kwh=est_usage,
                          **(account_overrides or {}))
    loa = draft_loa(api, account["id"], agent["id"], scope=loa_scope, expires_at=loa_expires)
    sign_loa(api, loa["id"], customer["id"])
    add_usage(api, account["id"], agent["id"], "2025-12", 5000, is_actual=False)
    account = verify_account(api, account["id"], agent["id"])

    ctx = {
        "agent": agent, "customer": customer, "account": account, "loa": loa,
        "agent_headers": make_agent_headers(agent["id"]),
        "customer_headers": make_customer_headers(customer["id"]),
        "ops_headers": ops_headers(),
    }
    if with_manager:
        ctx["mgr1"] = new_manager(api, approval_limit=manager_limit, full_name="Mgr One", email="m1@brk.co")
        ctx["mgr1_headers"] = make_manager_headers(ctx["mgr1"]["id"])
    if with_second_manager:
        ctx["mgr2"] = new_manager(api, approval_limit=manager_limit, full_name="Mgr Two", email="m2@brk.co")
        ctx["mgr2_headers"] = make_manager_headers(ctx["mgr2"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 2/3: RFP + quote lifecycle
# ---------------------------------------------------------------------------

def setup_open_rfp_with_shortlisted_quote(api, *, term_months=12, rate=60, adder=5,
                                          est_usage=60000, **verified_kwargs) -> dict:
    """VERIFIED account + ACTIVE supplier + OPEN RFP + one SHORTLISTED quote."""
    ctx = setup_verified_account(api, est_usage=est_usage, **verified_kwargs)
    ctx["supplier"] = new_supplier(api)
    ctx["supplier_headers"] = make_supplier_headers(ctx["supplier"]["id"])

    rfp = get_success_data(api.create_rfp(
        f.create_rfp_payload(ctx["account"]["id"], ctx["agent"]["id"], term_months_requested=term_months),
        ctx["agent_headers"]))
    get_success_data(api.transition_rfp(rfp["id"], {"action": "OPEN"}, ctx["agent_headers"]))
    v = rfp_version(api, rfp["id"], ctx["agent_headers"])
    quote = get_success_data(api.create_quote(
        f.create_quote_payload(rfp["id"], ctx["supplier"]["id"], v,
                               rate_mills_per_kwh=rate, term_months=term_months, broker_adder_mills=adder),
        ctx["supplier_headers"]))
    get_success_data(api.shortlist_quote(quote["id"], ctx["agent_headers"]))
    ctx["rfp"] = get_success_data(api.get_rfp(rfp["id"], ctx["agent_headers"]))
    ctx["quote"] = get_success_data(api.get_quote(quote["id"], ctx["agent_headers"]))
    return ctx


def award_from_ctx(api, ctx, *, est_usage=60000, start_date="2026-07-01T00:00:00Z",
                   requested_switch_date=None, account_id=None) -> dict:
    """Award the shortlisted quote in ctx -> Contract PENDING_CUSTOMER."""
    contract = get_success_data(api.award_contract(
        f.award_contract_payload(ctx["rfp"]["id"], account_id or ctx["account"]["id"],
                                 estimated_annual_usage_kwh=est_usage, start_date=start_date,
                                 requested_switch_date=requested_switch_date or start_date),
        ctx["agent_headers"]))
    ctx["contract"] = contract
    return contract


def setup_contract_pending_customer(api, *, term_months=12, rate=60, adder=5,
                                    est_usage=60000, start_date="2026-07-01T00:00:00Z",
                                    **verified_kwargs) -> dict:
    ctx = setup_open_rfp_with_shortlisted_quote(
        api, term_months=term_months, rate=rate, adder=adder, est_usage=est_usage, **verified_kwargs)
    award_from_ctx(api, ctx, est_usage=est_usage, start_date=start_date)
    return ctx


def setup_contract_pending_approval(api, **kwargs) -> dict:
    ctx = setup_contract_pending_customer(api, **kwargs)
    ctx["contract"] = get_success_data(api.customer_decision(
        ctx["contract"]["id"], {"decision": "ACCEPT"}, ctx["customer_headers"]))
    return ctx


def setup_contract_approved(api, **kwargs) -> dict:
    kwargs.setdefault("with_manager", True)
    ctx = setup_contract_pending_approval(api, **kwargs)
    ctx["contract"] = get_success_data(api.approve_contract(
        ctx["contract"]["id"], ctx["mgr1_headers"]))
    return ctx


def setup_active_contract(api, **kwargs) -> dict:
    """Full happy path through ENROLLMENT_SUBMITTED -> CONFIRM -> ACTIVE.

    Also creates the PROVISIONAL commission statement (submit-enrollment side effect)
    and leaves the account ENROLLED.
    """
    ctx = setup_contract_approved(api, **kwargs)
    get_success_data(api.submit_enrollment(ctx["contract"]["id"], ctx["agent_headers"]))
    ctx["contract"] = get_success_data(api.enrollment_result(
        ctx["contract"]["id"], {"result": "CONFIRM"}, ctx["ops_headers"]))
    ctx["account"] = get_success_data(api.get_account(ctx["account"]["id"], ctx["agent_headers"]))
    return ctx


def get_provisional_statement(api, ctx) -> dict:
    """The commission statement created by submit-enrollment for ctx['contract']."""
    data, _ = _list(api.list_commission_statements(ctx["agent_headers"],
                                                   params={"contract_id": ctx["contract"]["id"]}))
    ctx["statement"] = data[0]
    return data[0]


def _list(resp):
    body = resp.json()
    return body["data"], body.get("meta", {})


# ---------------------------------------------------------------------------
# Tier 4: commission true-up ready
# ---------------------------------------------------------------------------

def add_four_actual_usage_rows(api, ctx, kwh=14985):
    for month in ("2026-01", "2026-02", "2026-03", "2026-04"):
        add_usage(api, ctx["account"]["id"], ctx["agent"]["id"], month, kwh, is_actual=True)


def setup_approved_statement(api, *, actual_kwh=14985, add_actuals=True, **kwargs) -> dict:
    """ACTIVE contract, provisional statement APPROVED by mgr1, optional actual usage rows.

    Includes a second manager (mgr2) so a SoD-compliant true-up is available.
    """
    kwargs.setdefault("with_manager", True)
    kwargs.setdefault("with_second_manager", True)
    ctx = setup_active_contract(api, **kwargs)
    if add_actuals:
        add_four_actual_usage_rows(api, ctx, kwh=actual_kwh)
    stmt = get_provisional_statement(api, ctx)
    ctx["statement"] = get_success_data(api.approve_statement(stmt["id"], ctx["mgr1_headers"]))
    return ctx


# ---------------------------------------------------------------------------
# Tier: DR enrollment
# ---------------------------------------------------------------------------

def setup_active_dr_on_enrolled_account(api, *, committed_kw=100, incentive_per_kw_cents=4500,
                                        season_start="2026-08-01T00:00:00Z",
                                        season_end="2026-10-31T00:00:00Z", **kwargs) -> dict:
    """ENROLLED account (via ACTIVE contract) + a DR enrollment advanced to ACTIVE."""
    ctx = setup_active_contract(api, **kwargs)
    dr = get_success_data(api.create_dr_enrollment(
        f.create_dr_enrollment_payload(
            ctx["account"]["id"], committed_kw=committed_kw,
            incentive_per_kw_cents=incentive_per_kw_cents,
            season_start=season_start, season_end=season_end),
        ctx["agent_headers"]))
    ctx["dr"] = get_success_data(api.activate_dr(dr["id"], ctx["ops_headers"]))
    return ctx
