"""Composite setup helpers (multi-step preconditions).

Fixtures use get_success_data() (lenient) so setup failures produce clear
"Setup failed" errors instead of confusing assertion failures. Every fixture
returns the server-parsed entity dict(s).

Identity threading: Customer and Technician are entity-backed roles — any
ownership-gated call MUST use make_customer_headers(customer.id) /
make_technician_headers(technician.id), never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_customer_payload,
    create_yard_payload,
    create_access_profile_payload,
    create_subscription_plan_payload,
    create_service_addon_payload,
    create_subscription_payload,
    create_technician_payload,
    create_service_route_payload,
    create_visit_payload,
    create_vacation_window_payload,
    create_invoice_payload,
    create_satisfaction_report_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_technician_headers,
)


OPS = TEST_USERS["ops_headers"]
BILLING = TEST_USERS["billing_headers"]


# =========================================================================
# Tier 1: Single-entity state progression
# =========================================================================

def create_customer(**overrides) -> dict:
    """Create a Customer. Returns the customer dict."""
    resp = api_client.create_customer(create_customer_payload(**overrides), OPS)
    return get_success_data(resp)


def create_yard(customer_id: str, **overrides) -> dict:
    """Create a Yard for the given customer."""
    resp = api_client.create_yard(create_yard_payload(customer_id, **overrides), OPS)
    return get_success_data(resp)


def create_access_profile(yard_id: str, **overrides) -> dict:
    """Create a PropertyAccessProfile (1:1 with Yard). Returns profile (VERIFICATION_PENDING)."""
    resp = api_client.create_access_profile(
        yard_id, create_access_profile_payload(**overrides), OPS
    )
    return get_success_data(resp)


def create_verified_access_profile(yard_id: str, **overrides) -> dict:
    """Create a profile then verify it (VERIFIED)."""
    profile = create_access_profile(yard_id, **overrides)
    resp = api_client.verify_access_profile(profile["id"], OPS)
    return get_success_data(resp)


def create_subscription_plan(**overrides) -> dict:
    resp = api_client.create_subscription_plan(create_subscription_plan_payload(**overrides), OPS)
    return get_success_data(resp)


def create_service_addon(**overrides) -> dict:
    resp = api_client.create_service_addon(create_service_addon_payload(**overrides), OPS)
    return get_success_data(resp)


def create_technician(**overrides) -> dict:
    resp = api_client.create_technician(create_technician_payload(**overrides), OPS)
    return get_success_data(resp)


def create_service_route(**overrides) -> dict:
    resp = api_client.create_service_route(create_service_route_payload(**overrides), OPS)
    return get_success_data(resp)


def create_invoice(customer_id: str, **overrides) -> dict:
    resp = api_client.create_invoice(create_invoice_payload(customer_id, **overrides), BILLING)
    return get_success_data(resp)


# =========================================================================
# Tier 2: Entity hierarchy — customer + yard + verified profile + plan
# =========================================================================

def setup_customer_with_verified_yard(
    yard_overrides=None,
    profile_overrides=None,
    customer_overrides=None,
):
    """Returns (customer, yard, verified_profile)."""
    customer = create_customer(**(customer_overrides or {}))
    yard = create_yard(customer["id"], **(yard_overrides or {}))
    profile = create_verified_access_profile(yard["id"], **(profile_overrides or {}))
    return customer, yard, profile


def setup_active_subscription(
    plan_overrides=None,
    yard_overrides=None,
    profile_overrides=None,
    customer_overrides=None,
    clock_iso: str = "2026-05-01T00:00:00Z",
):
    """Full happy-path setup: customer + yard + verified access profile + plan
    + subscription, then activate. Returns (customer, yard, profile, plan, subscription).

    The activation is performed by the owning Customer using the
    entity-backed identity threading rule.
    """
    api_client.set_current_utc(clock_iso, OPS)
    customer, yard, profile = setup_customer_with_verified_yard(
        yard_overrides=yard_overrides,
        profile_overrides=profile_overrides,
        customer_overrides=customer_overrides,
    )
    plan = create_subscription_plan(**(plan_overrides or {}))
    sub_resp = api_client.create_subscription(
        create_subscription_payload(customer["id"], yard["id"], plan["id"]),
        make_customer_headers(customer["id"]),
    )
    subscription = get_success_data(sub_resp)
    act_resp = api_client.activate_subscription(
        subscription["id"], make_customer_headers(customer["id"])
    )
    subscription = get_success_data(act_resp)
    return customer, yard, profile, plan, subscription


# =========================================================================
# Tier 3: Full lifecycle shortcuts (visit + route through to specific states)
# =========================================================================

def create_scheduled_visit(subscription_id: str, route_id: str = None, **overrides) -> dict:
    payload = create_visit_payload(subscription_id, **overrides)
    if route_id is not None:
        payload["service_route_id"] = route_id
    resp = api_client.create_visit(payload, OPS)
    return get_success_data(resp)


def setup_route_with_assigned_tech(
    technician=None,
    route_overrides=None,
    technician_overrides=None,
):
    """Returns (technician, route PLANNED)."""
    if technician is None:
        technician = create_technician(**(technician_overrides or {}))
    route = create_service_route(
        assigned_technician_id=technician["id"],
        **(route_overrides or {}),
    )
    return technician, route


def setup_in_progress_route_with_visit(
    plan_overrides=None,
    yard_overrides=None,
    profile_overrides=None,
    technician_overrides=None,
    route_overrides=None,
    visit_overrides=None,
    service_date: str = "2026-05-04T00:00:00Z",
    start_clock_iso: str = "2026-05-04T08:00:00Z",
):
    """Full path to a route IN_PROGRESS with one visit EN_ROUTE.

    Returns (customer, yard, profile, plan, subscription, technician, route, visit).
    Route is published, clock moved to service_date morning, route started, visit departed.
    """
    # Setup subscription on the service date so visits scheduled on that date
    # are not in the past relative to the activation clock.
    customer, yard, profile, plan, subscription = setup_active_subscription(
        plan_overrides=plan_overrides,
        yard_overrides=yard_overrides,
        profile_overrides=profile_overrides,
        clock_iso=service_date,
    )
    technician, route = setup_route_with_assigned_tech(
        technician_overrides=technician_overrides,
        route_overrides={"service_date": service_date, **(route_overrides or {})},
    )
    visit = create_scheduled_visit(
        subscription["id"],
        route_id=route["id"],
        scheduled_date=service_date,
        **({"scheduled_window_start": f"{service_date[:10]}T09:00:00Z",
            "scheduled_window_end": f"{service_date[:10]}T10:00:00Z"}),
        **(visit_overrides or {}),
    )
    api_client.publish_service_route(route["id"], OPS)
    api_client.set_current_utc(start_clock_iso, OPS)
    api_client.start_service_route(route["id"], make_technician_headers(technician["id"]))
    api_client.depart_visit(visit["id"], make_technician_headers(technician["id"]))
    return customer, yard, profile, plan, subscription, technician, route, visit


def complete_visit_through_workflow(visit_id: str, technician_id: str) -> dict:
    """arrive + complete on an EN_ROUTE visit. Returns final Visit dict."""
    headers = make_technician_headers(technician_id)
    api_client.arrive_visit(visit_id, headers)
    resp = api_client.complete_visit(visit_id, headers)
    return get_success_data(resp)


# =========================================================================
# Tier 4: Accumulation / Threshold Targeting
# =========================================================================

def setup_route_at_committed_count(
    target_committed: int,
    max_capacity: int,
    service_date: str = "2026-05-08T00:00:00Z",
):
    """Build a route with `target_committed` SCHEDULED visits. Returns
    (customer, yard, profile, plan, subscription, technician, route, [visit_ids]).
    """
    customer, yard, profile, plan, subscription = setup_active_subscription(
        clock_iso="2026-05-01T00:00:00Z"
    )
    technician, route = setup_route_with_assigned_tech(
        route_overrides={"service_date": service_date, "max_visit_capacity": max_capacity}
    )
    visit_ids = []
    for i in range(target_committed):
        # space visits 2h apart to dodge the 15-min window-conflict buffer
        start_h = 8 + i * 2
        v = create_scheduled_visit(
            subscription["id"],
            route_id=route["id"],
            scheduled_date=service_date,
            scheduled_window_start=f"{service_date[:10]}T{start_h:02d}:00:00Z",
            scheduled_window_end=f"{service_date[:10]}T{start_h + 1:02d}:00:00Z",
        )
        visit_ids.append(v["id"])
    return customer, yard, profile, plan, subscription, technician, route, visit_ids


# =========================================================================
# Tier 5: Finalization / Terminal State
# =========================================================================

def setup_finalized_invoice(customer_id: str = None, **invoice_overrides):
    """Create a customer (if not given) and an invoice in FINALIZED state.
    Clock is set to the period-end so the finalize passes the
    billing_period_end <= current_utc check.
    Returns (customer, invoice_finalized).
    """
    if customer_id is None:
        customer = create_customer()
        customer_id = customer["id"]
    else:
        customer = get_success_data(api_client.get_customer(customer_id, OPS))
    api_client.set_current_utc("2026-06-01T00:00:00Z", OPS)
    invoice = create_invoice(customer_id, **invoice_overrides)
    finalize_resp = api_client.finalize_invoice(
        invoice["id"], {"expected_invoice_version": invoice["version"]}, BILLING
    )
    return customer, get_success_data(finalize_resp)


def setup_paid_invoice(customer_id: str = None, **invoice_overrides):
    """Invoice through to PAID. Returns (customer, invoice_paid)."""
    customer, finalized = setup_finalized_invoice(customer_id, **invoice_overrides)
    pay_resp = api_client.record_payment_invoice(
        finalized["id"], {"amount_cents": finalized["total_due_cents"]}, BILLING
    )
    return customer, get_success_data(pay_resp)


def setup_completed_visit_with_report(
    rating: int = 3,
    issue_category: str = "OTHER",
    report_in_review: bool = True,
):
    """Run a visit all the way to COMPLETED, then file a satisfaction report.
    Returns (customer, visit, report). If report_in_review, the report is moved
    to UNDER_REVIEW.
    """
    customer, yard, profile, plan, subscription, technician, route, visit = (
        setup_in_progress_route_with_visit()
    )
    completed = complete_visit_through_workflow(visit["id"], technician["id"])
    report_resp = api_client.create_satisfaction_report(
        create_satisfaction_report_payload(
            customer["id"], completed["id"], rating=rating, issue_category=issue_category
        ),
        make_customer_headers(customer["id"]),
    )
    report = get_success_data(report_resp)
    if report_in_review:
        api_client.begin_review_satisfaction_report(report["id"], OPS)
        report = get_success_data(api_client.get_satisfaction_report(report["id"], OPS))
    return customer, completed, report
