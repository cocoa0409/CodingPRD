"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch against an empty database
(the harness restarts the server before each test) using only PRD-declared
endpoints. Setup calls use get_success_data() so failures surface as clear
"Setup step failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS, REQUIRED_DOC_TYPES
from .factories import (
    create_owner_operator_payload,
    create_truck_payload,
    create_lease_payload,
    create_settlement_payload,
    create_lane_payload,
    create_service_bay_payload,
    create_work_order_payload,
    create_compliance_document_payload,
    create_buyout_quote_payload,
)
from .test_users import TEST_USERS, make_driver_headers

ADMIN = TEST_USERS["lease_admin_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
COORD = TEST_USERS["maintenance_coordinator_headers"]


# ─── Tier 1: single-entity creation ──────────────────

def create_operator(**overrides) -> dict:
    """Register an owner-operator. Returns the created operator (PENDING_REVIEW)."""
    res = api_client.create_owner_operator(create_owner_operator_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_truck(**overrides) -> dict:
    """Add a truck to the fleet. Returns the created truck (AVAILABLE)."""
    res = api_client.create_truck(create_truck_payload(**overrides), ADMIN)
    return get_success_data(res)


def submit_and_verify_doc(operator_id: str, doc_type: str,
                          expires_on: str = TEST_DEFAULTS["DOC_EXPIRES_ON"]) -> dict:
    """Submit a compliance document and verify it. Returns the VERIFIED document."""
    doc = get_success_data(api_client.create_compliance_document(
        create_compliance_document_payload(operator_id, doc_type, expires_on=expires_on),
        OFFICER))
    return get_success_data(api_client.verify_compliance_document(doc["id"], OFFICER))


def submit_and_verify_required_docs(operator_id: str,
                                    expires_on: str = TEST_DEFAULTS["DOC_EXPIRES_ON"]) -> list:
    """Submit + verify the full required set (W9, OPERATING_AUTHORITY,
    INSURANCE_CERTIFICATE) so the operator's classification becomes VERIFIED."""
    return [submit_and_verify_doc(operator_id, dt, expires_on) for dt in REQUIRED_DOC_TYPES]


def create_verified_operator(doc_expires_on: str = TEST_DEFAULTS["DOC_EXPIRES_ON"],
                             **operator_overrides) -> dict:
    """Operator whose three required documents are VERIFIED and unexpired.
    Returns the operator (classification VERIFIED)."""
    operator = create_operator(**operator_overrides)
    submit_and_verify_required_docs(operator["id"], doc_expires_on)
    return get_success_data(api_client.get_owner_operator(operator["id"], ADMIN))


# ─── Tier 2: lease hierarchy ─────────────────────────

def create_lease(operator_id: str, truck_id: str, **overrides) -> dict:
    """Create a lease in APPLICATION with its companion escrow account."""
    res = api_client.create_lease_agreement(
        create_lease_payload(operator_id, truck_id, **overrides), ADMIN)
    return get_success_data(res)


def get_escrow_for_lease(lease_id: str) -> dict:
    """Fetch the lease's 1:1 escrow account via the list reverse lookup."""
    data = get_success_data(
        api_client.list_escrow_accounts(ADMIN, params={"lease_id": lease_id}))
    assert isinstance(data, list) and len(data) == 1, (
        f"Expected exactly one escrow account for lease {lease_id}, got {data}")
    return data[0]


def create_active_lease(doc_expires_on: str = TEST_DEFAULTS["DOC_EXPIRES_ON"],
                        **lease_overrides) -> dict:
    """Verified operator + truck + lease activated to ACTIVE.

    Returns {"operator", "truck", "lease", "escrow"}.
    """
    operator = create_verified_operator(doc_expires_on=doc_expires_on)
    truck = create_truck(**lease_overrides.pop("truck_overrides", {}))
    lease = create_lease(operator["id"], truck["id"], **lease_overrides)
    lease = get_success_data(api_client.activate_lease(lease["id"], ADMIN))
    escrow = get_escrow_for_lease(lease["id"])
    return {"operator": operator, "truck": truck, "lease": lease, "escrow": escrow}


def set_clock(to_iso8601: str) -> dict:
    """Move the server's logical clock."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ─── Tier 3: settlement lifecycle shortcuts ──────────

def create_settlement(lease_id: str, week_start_date: str, **overrides) -> dict:
    """Create a weekly settlement (DRAFT, provisional basis)."""
    res = api_client.create_settlement(
        create_settlement_payload(lease_id, week_start_date, **overrides), CLERK)
    return get_success_data(res)


def create_and_issue_settlement(lease_id: str, week_start_date: str, **overrides) -> dict:
    """Create + issue a settlement. Returns the ISSUED settlement."""
    st = create_settlement(lease_id, week_start_date, **overrides)
    return get_success_data(api_client.issue_settlement(st["id"], CLERK))


def finalize_healthy_week(lease_id: str, week_start_date: str, clock_iso: str,
                          **overrides) -> dict:
    """Move the clock past week close, then create -> issue -> finalize a
    healthy settlement (gross 250000 default economics). Returns FINALIZED."""
    set_clock(clock_iso)
    st = create_and_issue_settlement(lease_id, week_start_date, **overrides)
    return get_success_data(api_client.finalize_settlement(st["id"], CLERK))


def finalize_short_week(lease_id: str, week_start_date: str, clock_iso: str) -> dict:
    """Finalize an all-zero, load-declined settlement week: every waterfall line
    is zero, the lease payment falls fully short. Returns FINALIZED settlement."""
    return finalize_healthy_week(
        lease_id, week_start_date, clock_iso,
        gross_revenue_cents=0, fuel_gallons=0, insurance_weekly_cents=0,
        miles_driven=0, load_declined_flag=True)


def setup_lease_with_missed_payments(count: int, **lease_overrides) -> dict:
    """ACTIVE lease with `count` finalized all-zero short payments
    (missed_payment_count == count, arrears == count * weekly_payment_cents).

    Weeks W1.. are used in order; the clock is left at the last week's close.
    Returns the scenario dict from create_active_lease.
    """
    scenario = create_active_lease(**lease_overrides)
    lease_id = scenario["lease"]["id"]
    weeks = ["2026-08-03", "2026-08-10", "2026-08-17", "2026-08-24"]
    clocks = ["2026-08-12T00:00:00Z", "2026-08-19T00:00:00Z",
              "2026-08-26T00:00:00Z", "2026-09-02T00:00:00Z"]
    for i in range(count):
        finalize_short_week(lease_id, weeks[i], clocks[i])
    scenario["lease"] = get_success_data(api_client.get_lease_agreement(lease_id, ADMIN))
    return scenario


def setup_defaulted_lease(**lease_overrides) -> dict:
    """DEFAULTED lease after three short-payment finalizations
    (missed_payment_count 3, arrears 195000 on standard terms)."""
    scenario = setup_lease_with_missed_payments(3, **lease_overrides)
    lease_id = scenario["lease"]["id"]
    scenario["lease"] = get_success_data(api_client.declare_default(lease_id, ADMIN))
    return scenario


# ─── Tier 4: lanes, bays, work orders, quotes ────────

def offer_and_accept_lane(lease_id: str, operator_id: str, **overrides) -> dict:
    """Offer a lane and have the owning Driver accept it. Returns ACCEPTED lane."""
    lane = get_success_data(api_client.create_lane_assignment(
        create_lane_payload(lease_id, **overrides), ADMIN))
    return get_success_data(
        api_client.accept_lane(lane["id"], make_driver_headers(operator_id)))


def create_service_bay(**overrides) -> dict:
    """Register a service bay."""
    return get_success_data(
        api_client.create_service_bay(create_service_bay_payload(**overrides), COORD))


def create_work_order(lease_id: str, bay_id: str, **overrides) -> dict:
    """Book a work order (OPEN) into a bay."""
    return get_success_data(api_client.create_work_order(
        create_work_order_payload(lease_id, bay_id, **overrides), COORD))


def complete_work_order(work_order_id: str, actual_cost_cents: int,
                        odometer_at_service: int) -> dict:
    """Complete an OPEN work order. Returns the COMPLETED work order."""
    return get_success_data(api_client.complete_work_order(
        work_order_id,
        {"actual_cost_cents": actual_cost_cents, "odometer_at_service": odometer_at_service},
        COORD))


def read_lease_version(lease_id: str) -> int:
    """Read the lease's current version (the OCC expectation source)."""
    return get_success_data(api_client.get_lease_agreement(lease_id, ADMIN))["version"]


def create_buyout_quote(lease_id: str, quote_kind: str,
                        expected_lease_version: int = None) -> dict:
    """Create a buyout quote carrying a fresh OCC lease version unless one is
    explicitly supplied. Returns the GENERATED quote."""
    if expected_lease_version is None:
        expected_lease_version = read_lease_version(lease_id)
    return get_success_data(api_client.create_buyout_quote(
        create_buyout_quote_payload(lease_id, quote_kind, expected_lease_version), ADMIN))
