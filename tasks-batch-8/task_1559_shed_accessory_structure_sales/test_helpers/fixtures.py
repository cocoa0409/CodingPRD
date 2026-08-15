"""Composite setup helpers for multi-step test prerequisites.

All helpers build preconditions from scratch via PRD-declared endpoints and use
get_success_data() so setup failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_jurisdiction_payload,
    create_model_payload,
    create_customer_payload,
    create_order_payload,
    create_site_check_payload,
    create_report_payload,
    create_payment_payload,
    create_schedule_payload,
    create_service_ticket_payload,
)
from .test_users import TEST_USERS, make_customer_headers

SALES = TEST_USERS["sales_rep_headers"]
PERMIT = TEST_USERS["permit_coordinator_headers"]
CREW = TEST_USERS["install_crew_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]
OPS = TEST_USERS["operations_admin_headers"]


# --- Tier 2: Entity hierarchy base -------------------------------------------

def setup_book(jurisdiction_overrides=None, model_overrides=None, customer_overrides=None):
    """Create the rule book + catalog row + buyer. Returns (jurisdiction, model, customer)."""
    jur = get_success_data(
        api_client.create_jurisdiction(
            create_jurisdiction_payload(**(jurisdiction_overrides or {})), PERMIT
        )
    )
    model = get_success_data(
        api_client.create_model(create_model_payload(**(model_overrides or {})), SALES)
    )
    cust = get_success_data(
        api_client.create_customer(create_customer_payload(**(customer_overrides or {})), SALES)
    )
    return jur, model, cust


def create_draft_order(customer_id, model_id, jurisdiction_id, **overrides):
    """Create an order in DRAFT. Defaults: 10x12 PRE_BUILT GRAVEL_PAD AUGER_STRAP CASH,
    no options. Returns the created order."""
    return get_success_data(
        api_client.create_order(
            create_order_payload(customer_id, model_id, jurisdiction_id, **overrides), SALES
        )
    )


def get_order(order_id):
    return get_success_data(api_client.get_order(order_id, SALES))


# --- Tier 1/3: Order lifecycle progression ------------------------------------

def submit_site_check(order_id, assessor_id="asr-1", scheduled_date="2026-08-02",
                      window_start_hour=10):
    """POST submit-site-check as SalesRep. Returns the REQUESTED SiteAssessment."""
    return get_success_data(
        api_client.submit_site_check(
            order_id,
            create_site_check_payload(
                assessor_id=assessor_id,
                scheduled_date=scheduled_date,
                window_start_hour=window_start_hour,
            ),
            SALES,
        )
    )


def file_report(assessment_id, **overrides):
    """File the assessor's report as InstallCrew. Defaults pass every check
    (SUITABLE for the reference rule book). Returns the REPORTED assessment."""
    return get_success_data(
        api_client.report_site_assessment(
            assessment_id, create_report_payload(**overrides), CREW
        )
    )


def list_order_applications(order_id):
    """Return the order's permit application rows (list envelope data)."""
    body = get_success_data(api_client.list_order_permit_applications(order_id, PERMIT))
    return body if isinstance(body, list) else body.get("data", body)


def get_only_application(order_id):
    """Return the order's first permit application row."""
    apps = list_order_applications(order_id)
    assert len(apps) >= 1, f"expected a permit application for order {order_id}"
    return apps[0]


def approve_application(application_id):
    """Approve a SUBMITTED application as PermitCoordinator."""
    return get_success_data(api_client.approve_permit_application(application_id, PERMIT))


def deny_application(application_id, decision_note=None):
    """Deny a SUBMITTED application as PermitCoordinator."""
    payload = {} if decision_note is None else {"decision_note": decision_note}
    return get_success_data(api_client.deny_permit_application(application_id, payload, PERMIT))


def record_order_payment(order_id, amount_cents, idempotency_key, method="CARD"):
    """Record an order-level payment as FinanceManager. Returns the Payment row."""
    return get_success_data(
        api_client.record_order_payment(
            order_id, create_payment_payload(amount_cents, idempotency_key, method), FINANCE
        )
    )


def record_rto_payment(contract_id, amount_cents, idempotency_key, method="CARD"):
    """Record a contract payment as FinanceManager. Returns the Payment row."""
    return get_success_data(
        api_client.record_rto_payment(
            contract_id, create_payment_payload(amount_cents, idempotency_key, method), FINANCE
        )
    )


def advance_clock(to_iso8601):
    """Advance the logical clock as OperationsAdmin (PRD §2.6)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, OPS))


def run_billing_sweep():
    """Run the delinquency sweep as FinanceManager. Returns the summary payload."""
    return get_success_data(api_client.run_billing(FINANCE))


def get_order_contract(order_id):
    """Return the order's RTO contract row (array of 0 or 1 per PRD §3.7)."""
    body = get_success_data(api_client.get_order_rto_contract(order_id, FINANCE))
    rows = body if isinstance(body, list) else body.get("data", body)
    assert len(rows) == 1, f"expected exactly one RTO contract for order {order_id}"
    return rows[0]


def get_contract(contract_id):
    return get_success_data(api_client.get_rto_contract(contract_id, FINANCE))


def drive_order_to_permit_review(order, report_overrides=None):
    """submit-site-check + passing report. Returns (assessment, application).
    Order lands in PERMIT_REVIEW when a permit is required, or advances straight
    to READY_TO_SCHEDULE when the application is recorded NOT_REQUIRED."""
    asm = submit_site_check(order["id"])
    filed = file_report(asm["id"], **(report_overrides or {}))
    app = get_only_application(order["id"])
    return filed, app


def drive_order_to_ready(order, report_overrides=None):
    """Drive the order to READY_TO_SCHEDULE, approving the permit when one is
    required. Returns the permit application row."""
    _, app = drive_order_to_permit_review(order, report_overrides=report_overrides)
    if app["status"] == "SUBMITTED":
        app = approve_application(app["id"])
    return app


def drive_order_to_scheduled(order, deposit_cents=None, crew_id="crew-1",
                             scheduled_date="2026-08-01", report_overrides=None):
    """Drive to READY_TO_SCHEDULE, pay the deposit for CASH orders when given
    (RTO orders are exempt from the deposit gate), then book the build.
    Returns the SCHEDULED order."""
    drive_order_to_ready(order, report_overrides=report_overrides)
    if deposit_cents is not None:
        record_order_payment(order["id"], deposit_cents, f"dep-{order['id'][:8]}")
    return get_success_data(
        api_client.schedule_order(
            order["id"], create_schedule_payload(scheduled_date, crew_id), SALES
        )
    )


def complete_ready_order(order, crew_id="crew-1", scheduled_date="2026-08-01"):
    """Order already in READY_TO_SCHEDULE: schedule -> start -> complete.
    Returns the COMPLETED order."""
    scheduled = get_success_data(
        api_client.schedule_order(
            order["id"], create_schedule_payload(scheduled_date, crew_id), SALES
        )
    )
    get_success_data(api_client.start_order(scheduled["id"], CREW))
    return get_success_data(api_client.complete_order(scheduled["id"], CREW))


def drive_order_to_completed(order, deposit_cents=None, crew_id="crew-1",
                             scheduled_date="2026-08-01"):
    """Full lifecycle DRAFT -> COMPLETED. Returns the COMPLETED order."""
    drive_order_to_ready(order)
    if deposit_cents is not None:
        record_order_payment(order["id"], deposit_cents, f"dep-{order['id'][:8]}")
    return complete_ready_order(order, crew_id=crew_id, scheduled_date=scheduled_date)


def drive_rto_order_to_contract(order, crew_id="crew-1", scheduled_date="2026-08-01"):
    """Full lifecycle for an RTO order (no deposit gate). Completing creates the
    ACTIVE contract and closes the order. Returns (closed_order, contract)."""
    completed = drive_order_to_completed(
        order, deposit_cents=None, crew_id=crew_id, scheduled_date=scheduled_date
    )
    contract = get_order_contract(order["id"])
    return completed, contract
