"""Composite setup helpers for the Community Solar API.

Each fixture builds its preconditions from scratch via PRD-declared endpoints (the
harness restarts the server before every test, so the DB is always empty at entry).
Fixtures use get_success_data() (lenient) internally so setup failures surface as
clear "Setup step failed" errors rather than confusing assertion failures.

Identity threading: a Subscriber's X-User-ID must equal the acting Subscriber.id for
ownership-gated calls, so every subscriber-owned call below uses
make_subscriber_headers(subscriber_id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_grid_operator_headers,
    make_program_admin_headers,
    make_subscriber_headers,
)
from . import factories as f
from .constants import HIGH_ANNUAL_USAGE

GO = make_grid_operator_headers()
PA = make_program_admin_headers()


# ─── Tier 1: atomic resource builders ─────────────────────────────────

def create_project(**overrides) -> dict:
    """POST /projects → fresh OPEN project (GridOperator)."""
    resp = api_client.create_project(f.create_project_payload(**overrides), GO)
    return get_success_data(resp)


def create_subscriber(**overrides) -> dict:
    """POST /subscribers → fresh subscriber (ProgramAdmin)."""
    resp = api_client.create_subscriber(f.create_subscriber_payload(**overrides), PA)
    return get_success_data(resp)


def create_carve_out_adjustment(project_id, new_carve_out_pct, reason="adjust") -> dict:
    resp = api_client.create_carve_out_adjustment(
        project_id, f.carve_out_adjustment_payload(new_carve_out_pct, reason), PA
    )
    return get_success_data(resp)


# ─── Tier 1/2: enrollment lifecycle ───────────────────────────────────

def create_draft_enrollment(project_id, subscriber_id, requested_share_kw=5.0) -> dict:
    """POST /enrollments → DRAFT enrollment owned by subscriber_id."""
    headers = make_subscriber_headers(subscriber_id)
    resp = api_client.create_enrollment(
        f.create_enrollment_payload(project_id, subscriber_id,
                                    requested_share_kw=requested_share_kw),
        headers,
    )
    return get_success_data(resp)


def submit_enrollment(enrollment_id, subscriber_id) -> dict:
    resp = api_client.submit_enrollment(enrollment_id, make_subscriber_headers(subscriber_id))
    return get_success_data(resp)


def approve_enrollment(enrollment_id) -> dict:
    return get_success_data(api_client.approve_enrollment(enrollment_id, PA))


def activate_enrollment(enrollment_id) -> dict:
    """POST /enrollments/{id}/activate → returns the new Subscription (201)."""
    return get_success_data(api_client.activate_enrollment(enrollment_id, PA))


def create_active_subscription(project_id, subscriber_id, requested_share_kw=5.0) -> dict:
    """Full enrollment lifecycle DRAFT→SUBMITTED→APPROVED→ACTIVATED.
    Returns the live ACTIVE Subscription."""
    enr = create_draft_enrollment(project_id, subscriber_id, requested_share_kw)
    submit_enrollment(enr["id"], subscriber_id)
    approve_enrollment(enr["id"])
    return activate_enrollment(enr["id"])


def setup_project_with_active_subscription(
    project_overrides=None, subscriber_overrides=None, requested_share_kw=5.0
):
    """Project + subscriber + one ACTIVE subscription.
    Returns (project, subscriber, subscription)."""
    project = create_project(**(project_overrides or {}))
    subscriber = create_subscriber(**(subscriber_overrides or {}))
    subscription = create_active_subscription(
        project["id"], subscriber["id"], requested_share_kw
    )
    return project, subscriber, subscription


# ─── Tier 1: period lifecycle ─────────────────────────────────────────

def create_open_period(project_id, period_month="2026-01", forecast_production_kwh=1000) -> dict:
    """POST /periods → OPEN period; runs the forecast-basis allocation waterfall."""
    resp = api_client.create_period(
        f.create_period_payload(project_id, period_month,
                                forecast_production_kwh=forecast_production_kwh),
        GO,
    )
    return get_success_data(resp)


def meter_period(period_id, metered_production_kwh, expected_period_version) -> dict:
    """POST /periods/{id}/meter → METERED."""
    resp = api_client.meter_period(
        period_id,
        f.meter_payload(metered_production_kwh, expected_period_version),
        GO,
    )
    return get_success_data(resp)


def reconcile_period(period_id, expected_period_version) -> dict:
    """POST /periods/{id}/reconcile → RECONCILED."""
    resp = api_client.reconcile_period(
        period_id, f.reconcile_payload(expected_period_version), GO
    )
    return get_success_data(resp)


def setup_reconciled_period(
    project_overrides=None,
    subscriber_overrides=None,
    requested_share_kw=5.0,
    period_month="2026-01",
    forecast_production_kwh=1000,
    metered_production_kwh=1000,
):
    """Project + ACTIVE subscription + period walked OPEN→METERED→RECONCILED.
    Returns (project, subscriber, subscription, period_reconciled)."""
    project, subscriber, subscription = setup_project_with_active_subscription(
        project_overrides, subscriber_overrides, requested_share_kw
    )
    period = create_open_period(project["id"], period_month, forecast_production_kwh)
    metered = meter_period(period["id"], metered_production_kwh, period["version"])
    reconciled = reconcile_period(period["id"], metered["version"])
    return project, subscriber, subscription, reconciled


def first_reconciliation(period_id) -> dict:
    """GET /reconciliations?period_id= → first reconciliation of the period."""
    resp = api_client.list_reconciliations(GO, params={"period_id": period_id})
    data = get_success_data(resp)
    assert data, f"expected at least one reconciliation for period {period_id}"
    return data[0]


def first_allocation(period_id) -> dict:
    resp = api_client.list_allocations(GO, params={"period_id": period_id})
    data = get_success_data(resp)
    assert data, f"expected at least one allocation for period {period_id}"
    return data[0]


def first_rec_batch(period_id) -> dict:
    resp = api_client.list_rec_batches(GO, params={"period_id": period_id})
    data = get_success_data(resp)
    assert data, f"expected at least one REC batch for period {period_id}"
    return data[0]


def get_project(project_id) -> dict:
    return get_success_data(api_client.get_project(project_id, GO))


def get_subscriber(subscriber_id) -> dict:
    return get_success_data(api_client.get_subscriber(subscriber_id, GO))


def get_period(period_id) -> dict:
    return get_success_data(api_client.get_period(period_id, GO))


def get_subscription(subscription_id) -> dict:
    return get_success_data(api_client.get_subscription(subscription_id, GO))


# ─── Tier 3: reconciliation credit lifecycle ──────────────────────────

def issue_reconciliation(reconciliation_id) -> dict:
    return get_success_data(api_client.issue_reconciliation(reconciliation_id, GO))


def apply_reconciliation(reconciliation_id) -> dict:
    return get_success_data(api_client.apply_reconciliation(reconciliation_id, GO))


def dispute_reconciliation(reconciliation_id, subscriber_id) -> dict:
    return get_success_data(
        api_client.dispute_reconciliation(reconciliation_id, make_subscriber_headers(subscriber_id))
    )


# ─── Tier 3: REC batch disposition ────────────────────────────────────

def allocate_rec_batch(batch_id) -> dict:
    return get_success_data(api_client.allocate_rec_batch(batch_id, PA))


def setup_allocated_rec_batch(
    period_month="2026-01", metered_production_kwh=10000, requested_share_kw=5.0
):
    """Project + ACTIVE sub + reconciled period → minted REC batch earmarked ALLOCATED.
    Returns (project, subscriber, subscription, period, allocated_batch)."""
    project, subscriber, subscription, reconciled = setup_reconciled_period(
        requested_share_kw=requested_share_kw,
        period_month=period_month,
        forecast_production_kwh=metered_production_kwh,
        metered_production_kwh=metered_production_kwh,
    )
    batch = first_rec_batch(reconciled["id"])
    allocated = allocate_rec_batch(batch["id"])
    return project, subscriber, subscription, reconciled, allocated


# ─── Tier 4: cumulative state for true-up boundary tests ──────────────

def setup_overproduction_period(
    project_overrides=None,
    requested_share_kw=10.0,
    period_month="2026-03",
    metered_production_kwh=10000,
):
    """Project + ONE subscription that is SUSPENDED before the period opens, so it
    earns no allocation and the whole metered pool is overproduction. Walk the
    period OPEN→METERED→RECONCILED. Returns (project, subscriber, subscription, period)."""
    project = create_project(**(project_overrides or {}))
    subscriber = create_subscriber()
    subscription = create_active_subscription(
        project["id"], subscriber["id"], requested_share_kw
    )
    # Suspend so it earns nothing; committed_kw stays counted at requested_share_kw.
    get_success_data(api_client.suspend_subscription(subscription["id"], PA))
    period = create_open_period(project["id"], period_month, metered_production_kwh)
    metered = meter_period(period["id"], metered_production_kwh, period["version"])
    reconciled = reconcile_period(period["id"], metered["version"])
    return project, subscriber, subscription, reconciled


# ─── Tier 5: waitlist setup ───────────────────────────────────────────

def setup_full_project_with_waitlist(
    nameplate_capacity_kw=10, holder_share=10.0, waiter_share=5.0
):
    """Project driven FULL by holder's ACTIVE subscription, plus one QUEUED waitlist
    entry by a second subscriber. Returns (project, holder, holder_subscription,
    waiter, waitlist_entry)."""
    project = create_project(nameplate_capacity_kw=nameplate_capacity_kw)
    holder = create_subscriber()
    waiter = create_subscriber()
    holder_sub = create_active_subscription(project["id"], holder["id"], holder_share)
    wl_resp = api_client.create_waitlist_entry(
        f.create_waitlist_entry_payload(project["id"], waiter["id"],
                                        requested_share_kw=waiter_share),
        make_subscriber_headers(waiter["id"]),
    )
    waitlist_entry = get_success_data(wl_resp)
    return project, holder, holder_sub, waiter, waitlist_entry
