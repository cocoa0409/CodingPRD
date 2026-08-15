"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: ClientAdmin calls use make_client_admin_headers(client_id)
and Broker calls use make_broker_headers(broker_id) built from the real entity
ids created earlier in the chain — never the shared fallback constants.

Photo captured_at values must satisfy ">= order creation and <= now" against
the logical clock, so helpers default captured_at to the clock instant that is
active when the order is created (CLOCK_START unless the test advanced it).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_START,
    COMPARABLE_FLOOR,
    DEFAULT_AGREED_FEE_CENTS,
    DEFAULT_COMP_SALE_PRICE_CENTS,
    INTERIOR_PHOTO_KINDS,
    DRIVE_BY_PHOTO_KINDS,
)
from .factories import (
    create_broker_payload,
    create_client_account_payload,
    create_comparable_payload,
    create_fee_line_payload,
    create_license_payload,
    create_photo_payload,
    create_property_payload,
    create_payout_batch_payload,
    create_qc_verdict_payload,
    create_state_regulation_payload,
    create_valuation_order_payload,
)
from .test_users import TEST_USERS, make_broker_headers, make_client_admin_headers

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["operations_manager_headers"]
DISPATCH = TEST_USERS["dispatch_coordinator_headers"]
QC = TEST_USERS["qc_reviewer_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=CLOCK_START):
    """Advance the server-side logical clock (PlatformAdmin only)."""
    return api_client.set_clock(to_iso8601, ADMIN)


def create_state_regulation(state_code="CA", **overrides):
    payload = create_state_regulation_payload(state_code=state_code, **overrides)
    return get_success_data(api_client.create_state_regulation(payload, COMPLIANCE))


def create_client(client_code="CLAA", **overrides):
    payload = create_client_account_payload(client_code=client_code, **overrides)
    return get_success_data(api_client.create_client_account(payload, ADMIN))


def create_broker(broker_code="BRKA", **overrides):
    payload = create_broker_payload(broker_code=broker_code, **overrides)
    return get_success_data(api_client.create_broker(payload, COMPLIANCE))


def attach_license(broker_id, state_code, license_kind="BPO",
                   license_number="LIC-0001", **overrides):
    payload = create_license_payload(
        state_code=state_code, license_kind=license_kind,
        license_number=license_number, **overrides)
    return get_success_data(api_client.create_broker_license(broker_id, payload, COMPLIANCE))


def activate_broker(broker_id):
    return get_success_data(api_client.activate_broker(broker_id, COMPLIANCE))


def create_broker_with_license(state_code, broker_code="BRKA", license_kind="BPO",
                               max_concurrent_orders=5, activate=True):
    """Broker + one license for state_code (+ activation). Returns the broker."""
    broker = create_broker(broker_code=broker_code,
                           max_concurrent_orders=max_concurrent_orders)
    attach_license(broker["id"], state_code, license_kind=license_kind)
    if activate:
        broker = activate_broker(broker["id"])
    return broker


def create_property(state_code="CA", street_address="1 Main St", postal_code="90001",
                    **overrides):
    payload = create_property_payload(
        state_code=state_code, street_address=street_address,
        postal_code=postal_code, **overrides)
    return get_success_data(api_client.create_property(payload, OPS))


def get_broker(broker_id):
    return get_success_data(api_client.get_broker(broker_id, COMPLIANCE))


def get_order(order_id):
    return get_success_data(api_client.get_valuation_order(order_id, OPS))


def list_order_revisions(order_id):
    return get_success_data(api_client.list_order_revisions(order_id, QC))


def list_fee_lines(order_id):
    return get_success_data(api_client.list_fee_lines(order_id, OPS))


def list_broker_licenses(broker_id):
    return get_success_data(api_client.list_broker_licenses(broker_id, COMPLIANCE))


# ---------------------------------------------------------------------------
# Tier 2: the market workspace (regulation + client + licensed broker + props)
# ---------------------------------------------------------------------------

def setup_market(state_code="CA", client_code="CLAA", broker_code="BRKA",
                 license_kind="BPO", max_concurrent_orders=5,
                 client_overrides=None, reg_overrides=None,
                 num_comp_properties=4, activate_broker_flag=True):
    """Clock + state regulation + client + broker (licensed, activated) +
    one subject property + N comparable-source properties.

    Returns a dict carried through every downstream helper.
    """
    set_clock()
    regulation = create_state_regulation(state_code, **(reg_overrides or {}))
    client = create_client(client_code, **(client_overrides or {}))
    broker = create_broker_with_license(
        state_code, broker_code=broker_code, license_kind=license_kind,
        max_concurrent_orders=max_concurrent_orders, activate=activate_broker_flag)
    subject = create_property(state_code, street_address="100 Subject Rd",
                              postal_code="90001")
    comp_properties = [
        create_property(state_code, street_address=f"20{i} Comparable Ln",
                        postal_code=f"9001{i}")
        for i in range(num_comp_properties)
    ]
    return {
        "regulation": regulation,
        "client": client,
        "client_headers": make_client_admin_headers(client["id"]),
        "broker": broker,
        "broker_headers": make_broker_headers(broker["id"]),
        "subject": subject,
        "comp_properties": comp_properties,
    }


# ---------------------------------------------------------------------------
# Tier 3: order lifecycle walkers
# ---------------------------------------------------------------------------

def new_order(env, property_id=None, order_kind="BPO", inspection_level="DRIVE_BY",
              priority="STANDARD", agreed_fee_cents=DEFAULT_AGREED_FEE_CENTS,
              client=None):
    """Create an order in INTAKE as the owning ClientAdmin."""
    client = client or env["client"]
    client_headers = make_client_admin_headers(client["id"])
    payload = create_valuation_order_payload(
        property_id=property_id or env["subject"]["id"],
        order_kind=order_kind, inspection_level=inspection_level,
        priority=priority, agreed_fee_cents=agreed_fee_cents,
        client_id=client["id"])
    return get_success_data(api_client.create_valuation_order(payload, client_headers))


def submit_order(env, order):
    """INTAKE -> READY_FOR_DISPATCH by the owning ClientAdmin."""
    client_headers = make_client_admin_headers(order["client_id"])
    return get_success_data(api_client.submit_order(order["id"], client_headers))


def dispatch_to_broker(env, order, broker=None):
    """READY_FOR_DISPATCH -> DISPATCHED. Threads expected_order_version from
    the most recently observed order representation."""
    broker = broker or env["broker"]
    payload = {"broker_id": broker["id"], "expected_order_version": order["version"]}
    return get_success_data(api_client.dispatch_order(order["id"], payload, DISPATCH))


def broker_accept(env, order, broker=None):
    """DISPATCHED -> IN_PROGRESS as the assigned broker."""
    broker = broker or env["broker"]
    return get_success_data(
        api_client.accept_order(order["id"], make_broker_headers(broker["id"])))


def broker_decline(env, order, broker=None):
    """DISPATCHED -> READY_FOR_DISPATCH as the assigned broker."""
    broker = broker or env["broker"]
    return get_success_data(
        api_client.decline_order(order["id"], make_broker_headers(broker["id"])))


def cancel_order(env, order):
    """Cancel as the owning ClientAdmin."""
    client_headers = make_client_admin_headers(order["client_id"])
    return get_success_data(api_client.cancel_order(order["id"], client_headers))


# ---------------------------------------------------------------------------
# Tier 3b: field work (comparables, photos, fee lines)
# ---------------------------------------------------------------------------

def add_comparable(env, order, source_property_id=None, index=0,
                   sale_price_cents=DEFAULT_COMP_SALE_PRICE_CENTS,
                   distance_miles=1.5, adjustment_cents=0,
                   sale_date="2026-06-01T00:00:00Z"):
    """Add a DRAFT comparable as the assigned broker."""
    source_property_id = (source_property_id
                          or env["comp_properties"][index % len(env["comp_properties"])]["id"])
    payload = create_comparable_payload(
        source_property_id=source_property_id, sale_price_cents=sale_price_cents,
        sale_date=sale_date, distance_miles=distance_miles,
        adjustment_cents=adjustment_cents)
    return get_success_data(
        api_client.create_comparable(order["id"], payload, env["broker_headers"]))


def select_comp(env, order, comp):
    return get_success_data(
        api_client.select_comparable(order["id"], comp["id"], env["broker_headers"]))


def add_selected_comps(env, order, count=None, **comp_kw):
    """Add `count` comparables and mark each SELECTED. Defaults to the
    report-submission floor for the order's inspection level."""
    if count is None:
        count = COMPARABLE_FLOOR[order["inspection_level"]]
    comps = [add_comparable(env, order, index=i, **comp_kw) for i in range(count)]
    for comp in comps:
        select_comp(env, order, comp)
    return comps


def add_photo(env, order, photo_kind, captured_at=CLOCK_START, suffix="a"):
    broker_headers = make_broker_headers(order["assigned_broker_id"])
    payload = create_photo_payload(
        photo_kind=photo_kind,
        file_url=f"https://evidence.example.com/{order['id']}-{photo_kind}-{suffix}.jpg",
        captured_at=captured_at)
    return get_success_data(api_client.create_photo(order["id"], payload, broker_headers))


def add_photo_set_for_order(env, order, captured_at=CLOCK_START):
    """Upload the minimum photo set for the order's inspection level."""
    if order["inspection_level"] == "INTERIOR":
        kinds = INTERIOR_PHOTO_KINDS
    else:
        kinds = DRIVE_BY_PHOTO_KINDS
    return [add_photo(env, order, kind, captured_at=captured_at, suffix=str(i))
            for i, kind in enumerate(kinds)]


def add_fee(env, order, amount_cents, fee_kind="BASE", description="Fee",
            as_role="broker"):
    payload = create_fee_line_payload(
        fee_kind=fee_kind, description=description, amount_cents=amount_cents)
    headers = {"broker": env["broker_headers"], "ops": OPS,
                   "billing": BILLING}[as_role]
    return get_success_data(api_client.create_fee_line(order["id"], payload, headers))


def reconcile_fees(env, order, as_role="broker"):
    """Add one BASE fee line exactly equal to agreed_fee_cents."""
    return add_fee(env, order, order["agreed_fee_cents"], fee_kind="BASE",
                   description="Base fee", as_role=as_role)


# ---------------------------------------------------------------------------
# Tier 3c: report, QC, revision, completion
# ---------------------------------------------------------------------------

def submit_report(env, order):
    broker_headers = make_broker_headers(order["assigned_broker_id"])
    return get_success_data(api_client.submit_report(order["id"], broker_headers))


def open_qc(order, reviewer_headers=None):
    return get_success_data(
        api_client.open_qc_review(order["id"], reviewer_headers or QC))


def record_verdict(order, qc_review, verdict="APPROVE", defects_found=0,
                   notes="Reviewed.", reviewer_headers=None):
    payload = create_qc_verdict_payload(
        verdict=verdict, defects_found=defects_found, notes=notes)
    return get_success_data(
        api_client.record_qc_verdict(order["id"], qc_review["id"], payload,
                                     reviewer_headers or QC))


def resubmit(order, revision, broker=None):
    broker_headers = make_broker_headers(order["assigned_broker_id"])
    return get_success_data(
        api_client.resubmit_revision(order["id"], revision["id"], broker_headers))


def complete(order):
    return get_success_data(api_client.complete_order(order["id"], OPS))


# ---------------------------------------------------------------------------
# Tier 4: full-lifecycle drivers
# ---------------------------------------------------------------------------

def drive_order_to_in_progress(env, **order_kw):
    """INTAKE -> READY_FOR_DISPATCH -> DISPATCHED -> IN_PROGRESS."""
    order = new_order(env, **order_kw)
    order = submit_order(env, order)
    order = dispatch_to_broker(env, order)
    return broker_accept(env, order)


def drive_order_to_report_submitted(env, captured_at=CLOCK_START, **order_kw):
    """Full field-work chain ending in REPORT_SUBMITTED."""
    order = drive_order_to_in_progress(env, **order_kw)
    add_selected_comps(env, order)
    add_photo_set_for_order(env, order, captured_at=captured_at)
    reconcile_fees(env, order)
    return submit_report(env, order)


def drive_order_to_accepted(env, **order_kw):
    """REPORT_SUBMITTED + QC cycle 1 APPROVE -> ACCEPTED. Returns (order, qc)."""
    order = drive_order_to_report_submitted(env, **order_kw)
    qc_review = open_qc(order)
    record_verdict(order, qc_review, verdict="APPROVE", defects_found=0)
    return get_order(order["id"]), qc_review


def drive_order_to_completed(env, complete_clock=None, **order_kw):
    """Full happy path to COMPLETED. Optionally advance the clock first."""
    order, _qc = drive_order_to_accepted(env, **order_kw)
    if complete_clock is not None:
        set_clock(complete_clock)
    return complete(order)


def drive_order_to_revision_requested(env, defects_found=1, **order_kw):
    """REPORT_SUBMITTED + REVISE verdict -> REVISION_REQUESTED.
    Returns (order, qc_review, revision_request)."""
    order = drive_order_to_report_submitted(env, **order_kw)
    qc_review = open_qc(order)
    record_verdict(order, qc_review, verdict="REVISE", defects_found=defects_found)
    order = get_order(order["id"])
    revisions = list_order_revisions(order["id"])
    assert len(revisions) == 1, f"Expected exactly one revision request, got {revisions}"
    return order, qc_review, revisions[0]


# ---------------------------------------------------------------------------
# Tier 5: payout batches
# ---------------------------------------------------------------------------

def create_batch(broker_id, period_start=CLOCK_START,
                 period_end="2026-09-01T00:00:00Z"):
    payload = create_payout_batch_payload(
        broker_id=broker_id, period_start=period_start, period_end=period_end)
    return get_success_data(api_client.create_payout_batch(payload, BILLING))


def approve_batch(batch):
    payload = {"expected_batch_version": batch["version"]}
    return get_success_data(api_client.approve_payout_batch(batch["id"], payload, BILLING))


def disburse_batch(batch):
    return get_success_data(api_client.disburse_payout_batch(batch["id"], BILLING))
