"""Composite setup helpers for multi-step test prerequisites.

The harness restarts the server (empty DB) before every test, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. All setup calls use
get_success_data() (lenient) so a broken precondition surfaces as a clear "Setup step
failed" error rather than a confusing assertion failure.

Identity threading: an ownership-gated Customer or CrewLead call always uses
make_customer_headers(cust_id) / make_crewlead_headers(crew_id) with the real entity id,
never a shared TEST_USERS constant (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload, create_contract_payload, renew_contract_payload,
    create_estimate_payload, create_crew_payload, create_route_day_payload,
    create_route_assignment_payload, create_job_payload, create_service_call_payload,
    create_storage_bin_payload, create_storage_record_payload,
    create_financing_plan_payload, create_payment_payload, create_invoice_payload,
)
from .test_users import TEST_USERS, make_customer_headers, make_crewlead_headers

SALES = TEST_USERS["salesrep_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billingadmin_headers"]


# ── Logical clock ────────────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the logical server clock (SalesRep/Dispatcher/BillingAdmin may set it)."""
    return get_success_data(api_client.set_clock(to_iso8601, SALES))


# ── Tier 1: Single-entity creators ───────────────────────────────────────────

def create_customer(**overrides):
    return get_success_data(api_client.create_customer(
        create_customer_payload(**overrides), SALES))


def create_draft_contract(customer_id, **overrides):
    return get_success_data(api_client.create_contract(
        create_contract_payload(customer_id, **overrides), SALES))


def sign_contract(contract_id):
    return get_success_data(api_client.sign_contract(contract_id, SALES))


def create_crew(**overrides):
    return get_success_data(api_client.create_crew(create_crew_payload(**overrides), DISPATCH))


def create_route_day(crew_id, **overrides):
    return get_success_data(api_client.create_route_day(
        create_route_day_payload(crew_id, **overrides), DISPATCH))


def create_job(contract_id, **overrides):
    return get_success_data(api_client.create_job(
        create_job_payload(contract_id, **overrides), DISPATCH))


def create_estimate(customer_id, **overrides):
    return get_success_data(api_client.create_estimate(
        create_estimate_payload(customer_id, **overrides), SALES))


def create_storage_bin(**overrides):
    return get_success_data(api_client.create_storage_bin(
        create_storage_bin_payload(**overrides), BILLING))


def create_financing_plan(contract_id, **overrides):
    return get_success_data(api_client.create_financing_plan(
        create_financing_plan_payload(contract_id, **overrides), BILLING))


def create_invoice(customer_id, **overrides):
    return get_success_data(api_client.create_invoice(
        create_invoice_payload(customer_id, **overrides), BILLING))


# ── Tier 2: Contract state progression ───────────────────────────────────────

def setup_active_contract(contract_type="SEASONAL_RENTAL", base_season_fee_cents=50000,
                          early_bird_cutoff="2027-01-01T00:00:00Z",
                          customer_overrides=None, **contract_overrides):
    """Create a customer + sign a contract to ACTIVE. Returns (customer, contract).

    The returned contract dict is the ACTIVE (post-sign) resource.
    """
    customer = create_customer(**(customer_overrides or {}))
    draft = create_draft_contract(
        customer["id"], contract_type=contract_type,
        base_season_fee_cents=base_season_fee_cents,
        early_bird_cutoff=early_bird_cutoff, **contract_overrides)
    active = sign_contract(draft["id"])
    return customer, active


# ── Tier 2: Estimate lifecycle ───────────────────────────────────────────────

def setup_quoted_estimate(customer_id=None, contract_id=None, **estimate_overrides):
    """Create + quote an estimate. Returns (customer_id, quoted_estimate)."""
    if customer_id is None:
        customer_id = create_customer()["id"]
    extra = {}
    if contract_id is not None:
        extra["contract_id"] = contract_id
    est = create_estimate(customer_id, **extra, **estimate_overrides)
    quoted = get_success_data(api_client.quote_estimate(est["id"], SALES))
    return customer_id, quoted


def setup_accepted_estimate(customer_id=None, contract_id=None, **estimate_overrides):
    """Create + quote + accept an estimate (accept as the owning customer).
    Returns (customer_id, accepted_estimate)."""
    if customer_id is None:
        customer_id = create_customer()["id"]
    customer_id, quoted = setup_quoted_estimate(
        customer_id=customer_id, contract_id=contract_id, **estimate_overrides)
    accepted = get_success_data(
        api_client.accept_estimate(quoted["id"], make_customer_headers(customer_id)))
    return customer_id, accepted


# ── Tier 3: Route day + booked job ───────────────────────────────────────────

def book_assignment(route_day_id, job_id, window_start, window_end,
                    expected_route_day_version):
    return get_success_data(api_client.create_route_assignment(
        create_route_assignment_payload(
            route_day_id, job_id, window_start, window_end,
            expected_route_day_version), DISPATCH))


def setup_booked_install_job(job_type="INSTALL", scheduled_date="2026-11-15T09:00:00Z",
                             window_start="2026-11-15T09:00:00Z",
                             window_end="2026-11-15T11:00:00Z",
                             max_stops=5, estimate_id=None, service_date="2026-11-15T00:00:00Z"):
    """ACTIVE contract + one job booked (BOOKED) onto a PLANNED route day (booked_stops 1).

    Returns dict: customer, contract, crew, route_day (as read after booking),
    job, assignment.
    """
    customer, contract = setup_active_contract()
    job_extra = {"estimate_id": estimate_id} if estimate_id else {}
    job = create_job(contract["id"], job_type=job_type,
                     scheduled_date=scheduled_date, **job_extra)
    crew = create_crew(name="Crew", home_zone="N", daily_stop_capacity=max_stops)
    route_day = create_route_day(crew["id"], service_date=service_date,
                                 zone="N", max_stops=max_stops)
    assignment = book_assignment(route_day["id"], job["id"], window_start,
                                 window_end, route_day["version"])
    route_day = get_success_data(api_client.get_route_day(route_day["id"], DISPATCH))
    return {
        "customer": customer, "contract": contract, "crew": crew,
        "route_day": route_day, "job": job, "assignment": assignment,
    }


def dispatch_route_day(route_day_id):
    return get_success_data(api_client.dispatch_route_day(route_day_id, DISPATCH))


def setup_started_install_job(estimate_id=None,
                              scheduled_date="2026-11-01T09:00:00Z",
                              window_start="2026-11-01T09:00:00Z",
                              window_end="2026-11-01T11:00:00Z",
                              service_date="2026-11-01T00:00:00Z",
                              contract=None):
    """Full field path to an IN_PROGRESS INSTALL job: book onto a route day, dispatch
    the day, then start the job as the owning crew lead.

    If `contract` is provided (an already-ACTIVE contract dict), the job is created
    against it; otherwise a fresh ACTIVE contract is created. Returns dict with
    customer, contract, crew, route_day, job (IN_PROGRESS), assignment.
    """
    if contract is None:
        customer, contract = setup_active_contract(contract_type="PERMANENT_PURCHASE",
                                                   base_season_fee_cents=80000)
    else:
        customer = None
    job_extra = {"estimate_id": estimate_id} if estimate_id else {}
    job = create_job(contract["id"], job_type="INSTALL",
                     scheduled_date=scheduled_date, **job_extra)
    crew = create_crew(name="Crew A", home_zone="N", daily_stop_capacity=5)
    route_day = create_route_day(crew["id"], service_date=service_date,
                                 zone="N", max_stops=5)
    book_assignment(route_day["id"], job["id"], window_start, window_end,
                    route_day["version"])
    dispatch_route_day(route_day["id"])
    started = get_success_data(
        api_client.start_job(job["id"], make_crewlead_headers(crew["id"])))
    return {
        "customer": customer, "contract": contract, "crew": crew,
        "route_day": route_day, "job": started,
    }


# ── Tier 3: Service-call lifecycle ───────────────────────────────────────────

def setup_scheduled_service_call(classification="BILLABLE", service_fee_cents=8000,
                                 cause="WEATHER",
                                 scheduled_date="2026-12-10T09:00:00Z"):
    """ACTIVE contract + a service call classified and scheduled (SERVICE job spawned).
    Returns dict: customer, contract, service_call (SCHEDULED)."""
    customer, contract = setup_active_contract()
    sc = get_success_data(api_client.create_service_call(
        create_service_call_payload(contract["id"], reported_issue="issue", cause=cause,
                                    service_fee_cents=service_fee_cents), BILLING))
    get_success_data(api_client.classify_service_call(
        sc["id"], {"classification": classification}, BILLING))
    scheduled = get_success_data(api_client.schedule_service_call(
        sc["id"], {"scheduled_date": scheduled_date}, DISPATCH))
    return {"customer": customer, "contract": contract, "service_call": scheduled}


# ── Tier 3: Financing ─────────────────────────────────────────────────────────

def setup_financing_plan(original_principal_cents=1200000, apr_bps=1000,
                         term_months=12):
    """ACTIVE PERMANENT_PURCHASE contract + an ACTIVE financing plan.
    Returns (customer, contract, plan)."""
    customer, contract = setup_active_contract(contract_type="PERMANENT_PURCHASE",
                                               base_season_fee_cents=80000)
    plan = create_financing_plan(contract["id"],
                                 original_principal_cents=original_principal_cents,
                                 apr_bps=apr_bps, term_months=term_months)
    return customer, contract, plan


def post_payment(plan_id, amount_cents=110000):
    return get_success_data(api_client.create_payment(
        plan_id, create_payment_payload(amount_cents=amount_cents), BILLING))


def reverse_payment(payment_id):
    return get_success_data(api_client.reverse_payment(payment_id, BILLING))


# ── Tier 3: Storage ───────────────────────────────────────────────────────────

def setup_stored_record(buffer_days=0, stored_from="2026-01-15T00:00:00Z",
                        stored_until="2026-10-15T00:00:00Z"):
    """ACTIVE contract + a bin + a STORED storage record.
    Returns dict: customer, contract, bin, storage_record."""
    customer, contract = setup_active_contract()
    bin_ = create_storage_bin(bin_code="B-01", warehouse_zone="A",
                              buffer_days=buffer_days)
    record = get_success_data(api_client.create_storage_record(
        create_storage_record_payload(contract["id"], bin_["id"], stored_from,
                                      stored_until), BILLING))
    return {"customer": customer, "contract": contract, "bin": bin_,
            "storage_record": record}
