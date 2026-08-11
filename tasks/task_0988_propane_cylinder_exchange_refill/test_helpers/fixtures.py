"""Composite setup helpers for multi-step test prerequisites.

Every test runs against a freshly restarted server with an empty database, so
each helper builds its preconditions from scratch using only PRD-declared
endpoints. Setup calls use get_success_data() (lenient) so setup failures
surface as clear errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_certification_record_payload,
    create_commission_statement_payload,
    create_cylinder_payload,
    create_driver_payload,
    create_exchange_order_payload,
    create_leak_report_payload,
    create_pricing_policy_payload,
    create_reconciliation_session_payload,
    create_refill_ticket_payload,
    create_restock_run_payload,
    create_site_payload,
    create_technician_payload,
)
from .test_users import (
    TEST_USERS,
    make_driver_headers,
    make_technician_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK1 = TEST_USERS["site_clerk_headers"]
CLERK2 = TEST_USERS["site_clerk_2_headers"]
OFFICER1 = TEST_USERS["compliance_officer_headers"]

STARTUP_DATE = TEST_DEFAULTS["STARTUP_DATE"]  # logical clock at boot: 2026-05-01


# ─── Tier 0: primitives ────────────────────────────────

def advance_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PlatformAdmin only, PRD §2.4)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_site(**overrides) -> dict:
    return get_success_data(api_client.create_site(create_site_payload(**overrides), ADMIN))


def get_site(site_id: str) -> dict:
    return get_success_data(api_client.get_site(site_id, ADMIN))


def get_site_version(site_id: str) -> int:
    return get_site(site_id)["version"]


def add_policy(site_id: str, **policy_overrides) -> dict:
    """Create a pricing policy against the site's CURRENT version (OCC, PRD §2.6)."""
    version = get_site_version(site_id)
    payload = create_pricing_policy_payload(site_id, version, **policy_overrides)
    return get_success_data(api_client.create_pricing_policy(payload, ADMIN))


def create_priced_site(site_overrides: dict = None, policy_overrides: dict = None):
    """Site + active pricing policy P. Returns (site, policy)."""
    site = create_site(**(site_overrides or {}))
    policy = add_policy(site["id"], **(policy_overrides or {}))
    return site, policy


# ─── Tier 1: entity registration ───────────────────────

def register_fleet_cylinders(site_id: str = None, count: int = 1, fill: str = "FULL",
                             manufacture_date: str = TEST_DEFAULTS["MANUFACTURE_DATE"],
                             serial_prefix: str = "F") -> list:
    """Register `count` FLEET cylinders (PlatformAdmin), optionally into a site's cage."""
    out = []
    for i in range(count):
        payload = create_cylinder_payload(
            owner_kind="FLEET", initial_fill=fill, manufacture_date=manufacture_date,
        )
        if site_id is not None:
            payload["current_site_id"] = site_id
        out.append(get_success_data(api_client.create_cylinder(payload, ADMIN)))
    return out


def register_customer_cylinder(fill: str = "EMPTY",
                               manufacture_date: str = TEST_DEFAULTS["MANUFACTURE_DATE"],
                               clerk_headers=None, **overrides) -> dict:
    """Register a CUSTOMER cylinder (SiteClerk; always off-site, PRD §3.2)."""
    payload = create_cylinder_payload(
        owner_kind="CUSTOMER", initial_fill=fill, manufacture_date=manufacture_date, **overrides,
    )
    return get_success_data(api_client.create_cylinder(payload, clerk_headers or CLERK1))


def create_technician(cert_level: str = "FULL", **overrides) -> dict:
    return get_success_data(api_client.create_technician(
        create_technician_payload(cert_level=cert_level, **overrides), ADMIN))


def create_driver(**overrides) -> dict:
    return get_success_data(api_client.create_driver(create_driver_payload(**overrides), ADMIN))


# ─── Tier 2: exchange counter ──────────────────────────

def create_order(site_id: str, clerk_headers=None, returned_cylinder_id: str = None,
                 idempotency_key: str = None) -> dict:
    overrides = {}
    if returned_cylinder_id is not None:
        overrides["returned_cylinder_id"] = returned_cylinder_id
    if idempotency_key is not None:
        overrides["idempotency_key"] = idempotency_key
    return get_success_data(api_client.create_exchange_order(
        create_exchange_order_payload(site_id, **overrides), clerk_headers or CLERK1))


def complete_order(order_id: str, clerk_headers=None, payment_cash_cents: int = None) -> dict:
    """Complete a DRAFT order. Defaults to exact payment of the pinned total."""
    if payment_cash_cents is None:
        order = get_success_data(api_client.get_exchange_order(order_id, ADMIN))
        payment_cash_cents = order["total_cents"]
    return get_success_data(api_client.complete_exchange_order(
        order_id, {"payment_cash_cents": payment_cash_cents}, clerk_headers or CLERK1))


def swap_completed(site_id: str, clerk_headers=None, returned_cylinder_id: str = None) -> dict:
    """Create + complete a swap order. Returns the COMPLETED order."""
    clerk = clerk_headers or CLERK1
    order = create_order(site_id, clerk, returned_cylinder_id=returned_cylinder_id)
    return complete_order(order["id"], clerk)


# ─── Tier 3: refill bay ────────────────────────────────

def create_ticket(site_id: str, cylinder_id: str, clerk_headers=None,
                  pre_weight_lbs: float = 17.00) -> dict:
    return get_success_data(api_client.create_refill_ticket(
        create_refill_ticket_payload(site_id, cylinder_id, pre_weight_lbs=pre_weight_lbs),
        clerk_headers or CLERK1))


def weigh_ticket(ticket_id: str, measured_tare_lbs: float = 17.00, clerk_headers=None) -> dict:
    return get_success_data(api_client.weigh_refill_ticket(
        ticket_id, {"measured_tare_lbs": measured_tare_lbs}, clerk_headers or CLERK1))


def fill_ticket(ticket_id: str, post_weight_lbs: float, clerk_headers=None) -> dict:
    return get_success_data(api_client.fill_refill_ticket(
        ticket_id, {"post_weight_lbs": post_weight_lbs}, clerk_headers or CLERK1))


def close_ticket(ticket_id: str, payment_cash_cents: int = None, clerk_headers=None) -> dict:
    if payment_cash_cents is None:
        ticket = get_success_data(api_client.get_refill_ticket(ticket_id, ADMIN))
        payment_cash_cents = ticket["total_cents"]
    return get_success_data(api_client.close_refill_ticket(
        ticket_id, {"payment_cash_cents": payment_cash_cents}, clerk_headers or CLERK1))


def ticket_in_state(site_id: str, cylinder_id: str, state: str, clerk_headers=None,
                    pre_weight_lbs: float = 17.00, measured_tare_lbs: float = 17.00,
                    post_weight_lbs: float = 35.50, payment_cash_cents: int = None) -> dict:
    """Walk a refill ticket to OPEN / WEIGHED / FILLED / CLOSED. Returns the ticket."""
    clerk = clerk_headers or CLERK1
    ticket = create_ticket(site_id, cylinder_id, clerk, pre_weight_lbs=pre_weight_lbs)
    if state == "OPEN":
        return ticket
    ticket = weigh_ticket(ticket["id"], measured_tare_lbs, clerk)
    if state == "WEIGHED":
        return ticket
    ticket = fill_ticket(ticket["id"], post_weight_lbs, clerk)
    if state == "FILLED":
        return ticket
    ticket = close_ticket(ticket["id"], payment_cash_cents, clerk)
    return ticket


# ─── Tier 4: reconciliation ────────────────────────────

def open_session(site_id: str, business_date: str = STARTUP_DATE, clerk_headers=None,
                 idempotency_key: str = None) -> dict:
    overrides = {}
    if idempotency_key is not None:
        overrides["idempotency_key"] = idempotency_key
    return get_success_data(api_client.create_reconciliation_session(
        create_reconciliation_session_payload(site_id, business_date, **overrides),
        clerk_headers or CLERK1))


def count_session(session_id: str, counted_cash_cents: int, counted_full_cylinders: int,
                  counted_empty_cylinders: int, clerk_headers=None) -> dict:
    return get_success_data(api_client.count_reconciliation_session(
        session_id,
        {
            "counted_cash_cents": counted_cash_cents,
            "counted_full_cylinders": counted_full_cylinders,
            "counted_empty_cylinders": counted_empty_cylinders,
        },
        clerk_headers or CLERK1))


def balanced_session(site_id: str, business_date: str = STARTUP_DATE, clerk_headers=None,
                     counted_cash_cents: int = TEST_DEFAULTS["OPENING_FLOAT_CENTS"],
                     counted_full_cylinders: int = 0, counted_empty_cylinders: int = 0) -> dict:
    """Open a session and count it to BALANCED with exact expected values."""
    clerk = clerk_headers or CLERK1
    session = open_session(site_id, business_date, clerk)
    counted = count_session(session["id"], counted_cash_cents,
                            counted_full_cylinders, counted_empty_cylinders, clerk)
    assert counted["status"] == "BALANCED", (
        f"Setup failed: expected BALANCED, got {counted['status']} "
        f"(cash variance {counted.get('cash_variance_cents')})"
    )
    return counted


# ─── Tier 5: certification / condemnation ──────────────

def record_certification(cylinder_id: str, technician: dict, method: str = "VISUAL",
                         outcome: str = "PASS", note: str = None) -> dict:
    overrides = {}
    if note is not None:
        overrides["note"] = note
    return get_success_data(api_client.create_certification_record(
        create_certification_record_payload(cylinder_id, method=method, outcome=outcome,
                                            **overrides),
        make_technician_headers(technician["id"])))


def condemn_cylinder(cylinder_id: str, tech1: dict = None, tech2: dict = None) -> dict:
    """Two-signature CONDEMN flow: T1 requests, T2 confirms. Returns the CONFIRMED record."""
    tech1 = tech1 or create_technician(cert_level="FULL", name="Condemn Tech 1")
    tech2 = tech2 or create_technician(cert_level="FULL", name="Condemn Tech 2")
    record = record_certification(cylinder_id, tech1, method="VISUAL", outcome="CONDEMN")
    assert record["status"] == "PENDING_SECOND", "Setup failed: CONDEMN must land PENDING_SECOND"
    confirmed = get_success_data(api_client.confirm_certification_record(
        record["id"], {}, make_technician_headers(tech2["id"])))
    assert confirmed["status"] == "CONFIRMED", "Setup failed: confirm must land CONFIRMED"
    return confirmed


# ─── Tier 6: leak lifecycle ────────────────────────────

def report_leak(site_id: str, clerk_headers=None, severity: str = "MINOR",
                quarantine_cage: bool = False, cylinder_id: str = None,
                note: str = None) -> dict:
    overrides = {"severity": severity}
    if quarantine_cage:
        overrides["quarantine_cage"] = True
    if cylinder_id is not None:
        overrides["cylinder_id"] = cylinder_id
    if note is not None:
        overrides["note"] = note
    return get_success_data(api_client.create_leak_report(
        create_leak_report_payload(site_id, **overrides), clerk_headers or CLERK1))


def confirm_leak(report_id: str, officer_headers=None) -> dict:
    return get_success_data(api_client.confirm_leak_report(report_id, officer_headers or OFFICER1))


def resolve_leak(report_id: str, resolution_note: str, officer_headers=None) -> dict:
    return get_success_data(api_client.resolve_leak_report(
        report_id, {"resolution_note": resolution_note}, officer_headers or OFFICER1))


# ─── Tier 7: restock logistics ─────────────────────────

def create_restock_run(site_id: str, driver_id: str, planned_date: str) -> dict:
    """Create a run against the site's CURRENT version (OCC, PRD §2.6)."""
    version = get_site_version(site_id)
    return get_success_data(api_client.create_restock_run(
        create_restock_run_payload(site_id, driver_id, planned_date, version), ADMIN))


def setup_dispatch_scenario(site_full: int = 3, depot_full: int = 9,
                            vehicle_max_payload_lbs: int = 2000,
                            dot_medical_expires_on: str = "2027-01-01",
                            planned_date: str = "2026-05-20",
                            site_overrides: dict = None):
    """Site with `site_full` FULL fleet cylinders, driver, `depot_full` FULL depot
    cylinders, and a DRAFT run for `planned_date`. Returns (site, driver, run)."""
    driver = create_driver(dot_medical_expires_on=dot_medical_expires_on,
                           vehicle_max_payload_lbs=vehicle_max_payload_lbs)
    site = create_site(**(site_overrides or {}))
    if site_full:
        register_fleet_cylinders(site_id=site["id"], count=site_full, fill="FULL",
                                 serial_prefix="S")
    if depot_full:
        register_fleet_cylinders(site_id=None, count=depot_full, fill="FULL",
                                 serial_prefix="D")
    run = create_restock_run(site["id"], driver["id"], planned_date)
    return site, driver, run


def dispatch_run(run_id: str) -> dict:
    return get_success_data(api_client.dispatch_restock_run(run_id, ADMIN))


# ─── Tier 8: commission settlement ─────────────────────

def create_statement(site_id: str, period_start: str, period_end: str) -> dict:
    return get_success_data(api_client.create_commission_statement(
        create_commission_statement_payload(site_id, period_start, period_end), ADMIN))


def finalize_statement(statement_id: str) -> dict:
    return get_success_data(api_client.finalize_commission_statement(statement_id, ADMIN))


def setup_single_swap_day(site_overrides: dict = None, clerk_headers=None):
    """Priced site + 1 FULL fleet + 1 EMPTY customer cylinder; one swap-with-return
    completed on the startup date (2026-05-01). Returns (site, customer_cylinder, order)."""
    clerk = clerk_headers or CLERK1
    site, _policy = create_priced_site(site_overrides=site_overrides)
    register_fleet_cylinders(site_id=site["id"], count=1, fill="FULL", serial_prefix="FS")
    customer = register_customer_cylinder(fill="EMPTY", clerk_headers=clerk)
    order = swap_completed(site["id"], clerk, returned_cylinder_id=customer["id"])
    return site, customer, order


def setup_swap_day_balanced(site_overrides: dict = None, clerk_headers=None):
    """setup_single_swap_day + the day's session counted to BALANCED.
    After one swap-with-return (total 2705): expected cash 22705, cage 0 full / 1 empty.
    Returns (site, order, session)."""
    clerk = clerk_headers or CLERK1
    site, _customer, order = setup_single_swap_day(site_overrides, clerk)
    session = balanced_session(site["id"], STARTUP_DATE, clerk,
                               counted_cash_cents=22705,
                               counted_full_cylinders=0, counted_empty_cylinders=1)
    return site, order, session
