"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is empty at the start of each test.
All setup calls use get_success_data() so a broken precondition surfaces as a
clear "Setup failed" rather than a confusing assertion error downstream.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import TEST_USERS, make_field_tech_headers
from . import factories as F

PA = TEST_USERS["program_admin_headers"]
CARE = TEST_USERS["customer_care_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
ELIG = TEST_USERS["eligibility_worker_headers"]
BILLING = TEST_USERS["billing_headers"]
NOC = TEST_USERS["noc_operator_headers"]


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(api, iso: str):
    return get_success_data(api.set_clock({"to_iso8601": iso}, PA))


# --------------------------------------------------------------------------
# Tier 1 — single-entity builders
# --------------------------------------------------------------------------
def create_grant(api, **overrides):
    return get_success_data(api.create_grant(F.grant_payload(**overrides), PA))


def create_area(api, grant_id, **overrides):
    """Create a PLANNED area (no advance)."""
    return get_success_data(api.create_service_area(F.service_area_payload(grant_id, **overrides), PA))


def create_serviceable_area(api, grant_id, **overrides):
    """Create an area and advance PLANNED -> CONSTRUCTION -> SERVICEABLE."""
    overrides.setdefault("fiber_ready", True)
    area = create_area(api, grant_id, **overrides)
    get_success_data(api.advance_service_area(area["id"], PA))
    return get_success_data(api.advance_service_area(area["id"], PA))


def create_plan(api, **overrides):
    return get_success_data(api.create_service_plan(F.service_plan_payload(**overrides), PA))


def create_subsidy_program(api, **overrides):
    return get_success_data(api.create_subsidy_program(F.subsidy_program_payload(**overrides), PA))


def create_subscriber(api, service_area_id, **overrides):
    return get_success_data(api.create_subscriber(F.subscriber_payload(service_area_id, **overrides), CARE))


def create_technician(api, **overrides):
    return get_success_data(api.create_technician(F.technician_payload(**overrides), PA))


def create_device(api, **overrides):
    return get_success_data(api.create_device(F.device_payload(**overrides), DISPATCH))


# --------------------------------------------------------------------------
# Tier 2 — subscription lifecycle
# --------------------------------------------------------------------------
def create_pending_subscription(api, subscriber_id, plan_id, service_area_id):
    """A subscription in PENDING_INSTALL against a SERVICEABLE area."""
    return get_success_data(
        api.create_subscription(F.subscription_payload(subscriber_id, plan_id, service_area_id), CARE)
    )


def schedule_install(api, subscription_id, technician_id, scheduled_start_at):
    return get_success_data(
        api.create_install_order(
            F.install_order_payload(subscription_id, technician_id, scheduled_start_at), DISPATCH
        )
    )


def complete_install(api, install_id, technician_id, device_id=None):
    payload = {"device_id": device_id} if device_id else {}
    return get_success_data(
        api.complete_install_order(install_id, make_field_tech_headers(technician_id), payload)
    )


def activate_subscription(api, subscription_id):
    return get_success_data(api.activate_subscription(subscription_id, CARE))


def setup_active_subscription(api, homes_passed=100, price=6000, area=None, grant=None,
                              plan=None, technician=None, install_start="2026-06-01T09:00:00Z",
                              subscriber_overrides=None):
    """Full chain to ONE ACTIVE subscription.

    grant -> serviceable area -> plan -> subscriber -> subscription ->
    technician -> install -> complete -> activate.

    Returns a dict with all created entities keyed by role.
    """
    grant = grant or create_grant(api)
    area = area or create_serviceable_area(api, grant["id"], homes_passed=homes_passed)
    plan = plan or create_plan(api, monthly_price_cents=price)
    subscriber = create_subscriber(api, area["id"], **(subscriber_overrides or {}))
    subscription = create_pending_subscription(api, subscriber["id"], plan["id"], area["id"])
    technician = technician or create_technician(api)
    install = schedule_install(api, subscription["id"], technician["id"], install_start)
    complete_install(api, install["id"], technician["id"])
    subscription = activate_subscription(api, subscription["id"])
    return {
        "grant": grant,
        "area": area,
        "plan": plan,
        "subscriber": subscriber,
        "subscription": subscription,
        "technician": technician,
        "install": install,
    }


def add_active_subscription_to_area(api, area, plan, technician, install_start,
                                    subscriber_overrides=None):
    """Create + activate a further subscription in an existing SERVICEABLE area.

    Reuses an existing technician; caller supplies a non-overlapping install_start.
    Returns (subscriber, subscription, install).
    """
    subscriber = create_subscriber(api, area["id"], **(subscriber_overrides or {}))
    subscription = create_pending_subscription(api, subscriber["id"], plan["id"], area["id"])
    install = schedule_install(api, subscription["id"], technician["id"], install_start)
    complete_install(api, install["id"], technician["id"])
    subscription = activate_subscription(api, subscription["id"])
    return subscriber, subscription, install


# --------------------------------------------------------------------------
# Tier 3 — enrollments
# --------------------------------------------------------------------------
def create_enrollment(api, subscriber_id, subsidy_program_id, **overrides):
    return get_success_data(
        api.create_enrollment(F.enrollment_payload(subscriber_id, subsidy_program_id, **overrides), ELIG)
    )


def create_active_enrollment(api, subscriber_id, subsidy_program_id, **overrides):
    """Create an enrollment then verify it to ACTIVE (income defaults keep it eligible)."""
    enrollment = create_enrollment(api, subscriber_id, subsidy_program_id, **overrides)
    return get_success_data(api.verify_enrollment(enrollment["id"], ELIG))


# --------------------------------------------------------------------------
# Tier 4 — billing
# --------------------------------------------------------------------------
def generate_invoice(api, subscription_id, period_start="2026-06-01T00:00:00Z",
                     period_end="2026-07-01T00:00:00Z"):
    return get_success_data(
        api.generate_invoice(subscription_id, F.invoice_period_payload(period_start, period_end), BILLING)
    )


def record_payment(api, invoice_id, amount_cents, expected_invoice_version):
    return get_success_data(
        api.record_payment(invoice_id, F.payment_payload(amount_cents, expected_invoice_version), BILLING)
    )


# --------------------------------------------------------------------------
# Tier 5 — outages
# --------------------------------------------------------------------------
def report_outage(api, service_area_id, started_at, severity="FULL"):
    return get_success_data(
        api.report_outage(F.outage_payload(service_area_id, started_at, severity=severity), NOC)
    )


# --------------------------------------------------------------------------
# Tier 6 — grant claims
# --------------------------------------------------------------------------
def create_claim(api, grant_id, service_area_ids, expected_grant_version,
                 claim_period_start="2026-06-01T00:00:00Z",
                 claim_period_end="2026-07-01T00:00:00Z", analyst_headers=None):
    from .test_users import make_analyst_headers
    headers = analyst_headers or make_analyst_headers("analyst-1")
    return get_success_data(
        api.create_grant_claim(
            grant_id,
            F.grant_claim_payload(claim_period_start, claim_period_end, service_area_ids, expected_grant_version),
            headers,
        )
    )


def submit_claim(api, claim_id, analyst_user_id="analyst-1"):
    from .test_users import make_analyst_headers
    return get_success_data(api.submit_grant_claim(claim_id, make_analyst_headers(analyst_user_id)))
