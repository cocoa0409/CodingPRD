"""Composite setup helpers for multi-step test prerequisites.

All helpers use get_success_data() (lenient validator) so setup failures
surface as clear "Setup failed" errors rather than confusing assertion
failures. Every helper builds its preconditions from scratch using only
PRD-declared endpoints; each test runs against a fresh server.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_consignor_payload, create_customer_payload, create_instrument_payload,
    create_appraisal_payload, evaluate_appraisal_payload, counter_appraisal_payload,
    bid_line, create_bid_package_payload, bid_revision_payload,
    order_line, create_order_payload, payment_payload,
    create_delivery_crew_payload, create_technician_payload, create_delivery_job_payload,
    create_service_plan_payload, create_service_visit_payload,
    create_financing_agreement_payload, financing_payment_payload,
    create_warranty_registration_payload, create_referral_payload,
    assess_referral_payload, create_showroom_event_payload,
)
from .test_users import (
    TEST_USERS, make_customer_headers, make_consignor_headers,
    make_bid_officer_headers, make_compliance_officer_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
ASSOCIATE = TEST_USERS["sales_associate_headers"]
COORDINATOR = TEST_USERS["service_coordinator_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
BID_OFFICER = TEST_USERS["bid_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

DEFAULT_JOB_WINDOW = ("2026-06-01T09:00:00Z", "2026-06-01T12:00:00Z")


# ─── Tier 0: clock ──────────────────────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD §2.5). Returns the clock payload."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ─── Tier 1: single-resource creation ───────────────────────────────────────

def create_consignor(**overrides) -> dict:
    return get_success_data(api_client.create_consignor(create_consignor_payload(**overrides), MANAGER))


def create_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), ASSOCIATE))


def create_instrument(**overrides) -> dict:
    return get_success_data(api_client.create_instrument(create_instrument_payload(**overrides), MANAGER))


def list_instrument_for_sale(instrument_id: str) -> dict:
    return get_success_data(api_client.list_instrument_for_sale(instrument_id, MANAGER))


def create_available_instrument(**overrides) -> dict:
    """Instrument intake + list-for-sale. Returns the AVAILABLE instrument."""
    instrument = create_instrument(**overrides)
    return list_instrument_for_sale(instrument["id"])


def create_delivery_crew(**overrides) -> dict:
    return get_success_data(api_client.create_delivery_crew(create_delivery_crew_payload(**overrides), MANAGER))


def create_technician(**overrides) -> dict:
    return get_success_data(api_client.create_technician(create_technician_payload(**overrides), MANAGER))


def get_instrument(instrument_id: str) -> dict:
    return get_success_data(api_client.get_instrument(instrument_id, MANAGER))


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_sales_order(order_id, ASSOCIATE))


def get_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, ASSOCIATE))


def get_consignor(consignor_id: str) -> dict:
    return get_success_data(api_client.get_consignor(consignor_id, MANAGER))


# ─── Tier 2: orders and payments ────────────────────────────────────────────

def create_order(customer_id: str, items: list, **overrides) -> dict:
    return get_success_data(api_client.create_sales_order(
        create_order_payload(customer_id, items, **overrides), ASSOCIATE))


def post_payment(order_id: str, amount_cents: int, method: str = "CARD") -> dict:
    return get_success_data(api_client.post_payment(
        order_id, payment_payload(amount_cents, method), ASSOCIATE))


def pay_order_in_full(order: dict, method: str = "CARD") -> dict:
    """Post a payment exactly equal to the order's balance (full settlement)."""
    return post_payment(order["id"], order["balance_cents"], method)


def create_paid_order(customer_id: str, items: list, **overrides) -> dict:
    """Create an order and settle it in full. Returns the PAID_IN_FULL order."""
    order = create_order(customer_id, items, **overrides)
    return pay_order_in_full(order)


def create_simple_available_instrument(serial_number: str, list_price_cents: int = 500_000,
                                       floor_price_cents: int = 400_000, **overrides) -> dict:
    payload = dict(serial_number=serial_number, list_price_cents=list_price_cents,
                   floor_price_cents=floor_price_cents)
    payload.update(overrides)
    return create_available_instrument(**payload)


# ─── Tier 3: delivery / installation lifecycle ──────────────────────────────

def create_delivery_job(order_id: str, crew_id: str,
                        window_start: str = DEFAULT_JOB_WINDOW[0],
                        window_end: str = DEFAULT_JOB_WINDOW[1]) -> dict:
    return get_success_data(api_client.create_delivery_job(
        create_delivery_job_payload(order_id, crew_id, window_start, window_end), COORDINATOR))


def run_delivery_job(job_id: str) -> dict:
    """Start then complete a SCHEDULED job. Returns the COMPLETED job."""
    get_success_data(api_client.start_delivery_job(job_id, COORDINATOR))
    return get_success_data(api_client.complete_delivery_job(job_id, COORDINATOR))


def deliver_order(order_id: str, crew_id: str = None,
                  window_start: str = DEFAULT_JOB_WINDOW[0],
                  window_end: str = DEFAULT_JOB_WINDOW[1]) -> tuple:
    """Schedule + run a delivery job for a paid order. Returns (job, order)."""
    if crew_id is None:
        crew_id = create_delivery_crew()["id"]
    job = create_delivery_job(order_id, crew_id, window_start, window_end)
    job = run_delivery_job(job["id"])
    return job, get_order(order_id)


def install_order(order_id: str, customer_id: str = None) -> dict:
    """Confirm installation (StoreManager). Returns the INSTALLED order."""
    return get_success_data(api_client.confirm_installation(order_id, MANAGER))


def setup_installed_order(customer_overrides: dict = None,
                          instrument_overrides: dict = None,
                          order_overrides: dict = None,
                          serial_number: str = "SN-FIX-1",
                          unit_price_cents: int = 100_000,
                          job_window: tuple = ("2026-05-03T09:00:00Z", "2026-05-03T11:00:00Z")) -> tuple:
    """Full path: customer + AVAILABLE instrument + PAID_IN_FULL order + delivery
    + installation. Returns (customer, instrument, order)."""
    customer = create_customer(**(customer_overrides or {}))
    inst_defaults = dict(serial_number=serial_number, list_price_cents=unit_price_cents,
                         floor_price_cents=max(1, unit_price_cents - 100_000))
    inst_defaults.update(instrument_overrides or {})
    instrument = create_available_instrument(**inst_defaults)
    order = create_paid_order(customer["id"], [order_line(instrument["id"], unit_price_cents)],
                              **(order_overrides or {}))
    crew = create_delivery_crew()
    deliver_order(order["id"], crew["id"], job_window[0], job_window[1])
    order = install_order(order["id"])
    return customer, instrument, order


# ─── Tier 3: trade-in appraisals ────────────────────────────────────────────

def create_appraisal(customer_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_trade_in_appraisal(
        create_appraisal_payload(customer_id, **overrides), ASSOCIATE))


def evaluate_appraisal(appraisal_id: str, reconditioning_cost_cents: int = 0,
                       market_adjustment_pct: float = 0.0) -> dict:
    return get_success_data(api_client.evaluate_appraisal(
        appraisal_id,
        evaluate_appraisal_payload(reconditioning_cost_cents=reconditioning_cost_cents,
                                   market_adjustment_pct=market_adjustment_pct),
        MANAGER))


def accept_appraisal(appraisal_id: str, customer_id: str) -> dict:
    return get_success_data(api_client.accept_appraisal(
        appraisal_id, make_customer_headers(customer_id)))


def create_offered_appraisal(customer_id: str, reconditioning_cost_cents: int = 0,
                             market_adjustment_pct: float = 0.0, **overrides) -> dict:
    """Create + evaluate. Returns the OFFERED appraisal."""
    appraisal = create_appraisal(customer_id, **overrides)
    return evaluate_appraisal(appraisal["id"], reconditioning_cost_cents, market_adjustment_pct)


def create_accepted_appraisal(customer_id: str, reconditioning_cost_cents: int = 0,
                              market_adjustment_pct: float = 0.0, **overrides) -> dict:
    """Create + evaluate + accept (as the owning customer). Returns ACCEPTED appraisal."""
    appraisal = create_offered_appraisal(
        customer_id, reconditioning_cost_cents, market_adjustment_pct, **overrides)
    return accept_appraisal(appraisal["id"], customer_id)


# ─── Tier 3: institutional bids ─────────────────────────────────────────────

def create_bid(customer_id: str, lines: list, officer_user_id: str = None) -> dict:
    headers = make_bid_officer_headers(officer_user_id) if officer_user_id else BID_OFFICER
    return get_success_data(api_client.create_bid_package(
        create_bid_package_payload(customer_id, lines), headers))


def submit_bid(bid_id: str, officer_user_id: str = None) -> dict:
    headers = make_bid_officer_headers(officer_user_id) if officer_user_id else BID_OFFICER
    return get_success_data(api_client.submit_bid_package(bid_id, headers))


def create_submitted_bid(customer_id: str, lines: list, officer_user_id: str = None) -> dict:
    bid = create_bid(customer_id, lines, officer_user_id)
    return submit_bid(bid["id"], officer_user_id)


def create_approved_bid(customer_id: str, lines: list, officer_user_id: str = "officer-bid-fix",
                        compliance_user_id: str = "officer-compliance-fix") -> dict:
    bid = create_submitted_bid(customer_id, lines, officer_user_id)
    return get_success_data(api_client.compliance_approve_bid(
        bid["id"], make_compliance_officer_headers(compliance_user_id)))


# ─── Tier 3: financing ──────────────────────────────────────────────────────

def create_financing(order_id: str, program: str, principal_cents: int,
                     term_months: int, apr: float = None) -> dict:
    overrides = {}
    if apr is not None:
        overrides["apr"] = apr
    return get_success_data(api_client.create_financing_agreement(
        create_financing_agreement_payload(order_id, program, principal_cents, term_months, **overrides),
        FINANCE))


def approve_financing(agreement_id: str) -> dict:
    return get_success_data(api_client.approve_financing_agreement(agreement_id, FINANCE))


def create_active_financing(order: dict, program: str, term_months: int, apr: float = None) -> dict:
    """Apply + approve financing for the order's full total. Returns ACTIVE agreement."""
    agreement = create_financing(order["id"], program, order["total_cents"], term_months, apr)
    return approve_financing(agreement["id"])


def post_financing_payment(agreement_id: str, amount_cents: int) -> dict:
    return get_success_data(api_client.post_financing_payment(
        agreement_id, financing_payment_payload(amount_cents), FINANCE))


def get_financing(agreement_id: str) -> dict:
    return get_success_data(api_client.get_financing_agreement(agreement_id, FINANCE))


# ─── Tier 3: service plans & visits ─────────────────────────────────────────

def create_service_plan(order_id: str, tier: str = "STANDARD") -> dict:
    return get_success_data(api_client.create_service_plan(
        create_service_plan_payload(order_id, tier), COORDINATOR))


def get_service_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_service_plan(plan_id, COORDINATOR))


def book_visit(plan_id: str, technician_id: str, window_start: str, window_end: str) -> dict:
    return get_success_data(api_client.create_service_visit(
        create_service_visit_payload(plan_id, technician_id, window_start, window_end), COORDINATOR))


def complete_visit(visit_id: str) -> dict:
    return get_success_data(api_client.complete_service_visit(visit_id, COORDINATOR))


def setup_plan_with_visits(tier: str = "STANDARD", completed_visits: int = 0,
                           serial_number: str = "SN-PLAN-1",
                           job_window: tuple = ("2026-05-05T09:00:00Z", "2026-05-05T11:00:00Z"),
                           visit_day: str = "2026-06-10") -> tuple:
    """INSTALLED order with a plan that already has `completed_visits` COMPLETED
    visits. Returns (customer, order, plan, technician)."""
    customer, instrument, order = setup_installed_order(
        serial_number=serial_number, job_window=job_window)
    plan = create_service_plan(order["id"], tier)
    technician = create_technician()
    for i in range(completed_visits):
        visit = book_visit(plan["id"], technician["id"],
                           f"{visit_day}T{8 + i:02d}:00:00Z", f"{visit_day}T{9 + i:02d}:00:00Z")
        complete_visit(visit["id"])
    return customer, order, get_service_plan(plan["id"]), technician


# ─── Tier 3: warranties ─────────────────────────────────────────────────────

def create_warranty(order_id: str, instrument_id: str) -> dict:
    return get_success_data(api_client.create_warranty_registration(
        create_warranty_registration_payload(order_id, instrument_id), ASSOCIATE))


def confirm_warranty(warranty_id: str) -> dict:
    return get_success_data(api_client.confirm_warranty(warranty_id, MANAGER))


# ─── Tier 3: restoration referrals ──────────────────────────────────────────

def create_referral(instrument_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_restoration_referral(
        create_referral_payload(instrument_id, **overrides), MANAGER))


def assess_referral(referral_id: str, **overrides) -> dict:
    return get_success_data(api_client.assess_referral(
        referral_id, assess_referral_payload(**overrides), MANAGER))


def quote_referral(referral_id: str, final_quote_cents: int = 300_000) -> dict:
    return get_success_data(api_client.quote_referral(
        referral_id, {"final_quote_cents": final_quote_cents}, MANAGER))


def create_quoted_referral(instrument_id: str) -> dict:
    """Referral walked REFERRED -> ASSESSED -> QUOTED."""
    referral = create_referral(instrument_id)
    assess_referral(referral["id"])
    return quote_referral(referral["id"])


# ─── Tier 3: showroom events ────────────────────────────────────────────────

def create_event(**overrides) -> dict:
    return get_success_data(api_client.create_showroom_event(
        create_showroom_event_payload(**overrides), MANAGER))


def open_event_rsvp(event_id: str) -> dict:
    return get_success_data(api_client.open_rsvp(event_id, MANAGER))


def get_event(event_id: str) -> dict:
    return get_success_data(api_client.get_showroom_event(event_id, MANAGER))
