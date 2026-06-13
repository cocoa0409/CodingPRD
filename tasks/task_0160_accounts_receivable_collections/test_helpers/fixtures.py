"""Composite setup helpers.

These encapsulate the multi-step API sequences that the design instances reach
for, so tests can focus on the assertion under test rather than the plumbing.

The test harness restarts the server (empty database) before every test, so each
fixture builds its preconditions from scratch using only PRD-declared endpoints.
All setup calls use get_success_data() (lenient) so a setup failure surfaces as a
clear "Setup failed" rather than a confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .test_users import (
    TEST_USERS,
    make_ar_manager_headers,
    make_collections_agent_headers,
)
from .factories import (
    create_customer_payload,
    create_invoice_payload,
    create_payment_payload,
    create_payment_application_payload,
    create_dispute_payload,
    create_promise_payload,
    create_write_off_payload,
    create_dunning_sequence_payload,
    create_dunning_run_payload,
    create_dunning_pause_payload,
)

MGR = TEST_USERS["ar_manager_headers"]
CLERK = TEST_USERS["ar_clerk_headers"]
AGENT = TEST_USERS["collections_agent_headers"]


# --------------------------------------------------------------------------- #
# Clock
# --------------------------------------------------------------------------- #
def set_clock(to_iso8601: str):
    """Set the server's current UTC instant (AR_MANAGER test-driving capability)."""
    return get_success_data(api.set_clock(to_iso8601, MGR))


# --------------------------------------------------------------------------- #
# Tier 1: single-entity creation shortcuts
# --------------------------------------------------------------------------- #
def create_customer(name="Test Customer", credit_limit_cents=1_000_000, **overrides):
    """Create a customer; returns the created Customer object."""
    payload = create_customer_payload(
        name=name, credit_limit_cents=credit_limit_cents, **overrides
    )
    return get_success_data(api.create_customer(payload, MGR))


def create_invoice(customer_id, face_amount_cents=50_000,
                   invoice_date="2026-01-01T00:00:00Z",
                   due_date="2026-02-01T00:00:00Z", **overrides):
    """Create an OPEN invoice for a customer; returns the Invoice object."""
    payload = create_invoice_payload(
        customer_id,
        face_amount_cents=face_amount_cents,
        invoice_date=invoice_date,
        due_date=due_date,
        **overrides,
    )
    return get_success_data(api.create_invoice(payload, CLERK))


def create_payment(customer_id, amount_cents=50_000,
                   received_at="2026-03-01T00:00:00Z", **overrides):
    """Record a cash receipt; returns the UNAPPLIED Payment object."""
    payload = create_payment_payload(
        customer_id, amount_cents=amount_cents, received_at=received_at, **overrides
    )
    return get_success_data(api.create_payment(payload, CLERK))


def create_dunning_sequence(name="S", steps=None):
    """Define a dunning sequence; returns the DunningSequence object."""
    if steps is None:
        steps = [{"min_days_overdue": 1, "channel": "EMAIL", "severity": 1}]
    payload = create_dunning_sequence_payload(name=name, steps=steps)
    return get_success_data(api.create_dunning_sequence(payload, MGR))


# --------------------------------------------------------------------------- #
# Tier 2: customer + invoice combinations
# --------------------------------------------------------------------------- #
def setup_customer_with_invoice(face_amount_cents=50_000, credit_limit_cents=1_000_000,
                                invoice_date="2026-01-01T00:00:00Z",
                                due_date="2026-02-01T00:00:00Z", name="C"):
    """Active customer + one OPEN invoice. Returns (customer, invoice)."""
    customer = create_customer(name=name, credit_limit_cents=credit_limit_cents)
    invoice = create_invoice(
        customer["id"],
        face_amount_cents=face_amount_cents,
        invoice_date=invoice_date,
        due_date=due_date,
    )
    return customer, invoice


def current_customer_version(customer_id):
    """Read the customer's live version (needed for the promise OCC token)."""
    data = get_success_data(api.get_customer(customer_id, MGR))
    return data["version"]


# --------------------------------------------------------------------------- #
# Tier 3: payment application lifecycle
# --------------------------------------------------------------------------- #
def apply_payment(payment_id, invoice_id, applied_cents, settle_in_full=None):
    """Apply part of a payment to one invoice; returns the PaymentApplication."""
    payload = create_payment_application_payload(invoice_id, applied_cents)
    if settle_in_full is not None:
        payload["settle_in_full"] = settle_in_full
    return get_success_data(api.create_payment_application(payment_id, payload, CLERK))


def setup_applied_payment(invoice_face=20_000, applied=15_000,
                          credit_limit_cents=1_000_000):
    """Customer + OPEN invoice + a payment with one application posted.
    Returns (customer, invoice, payment, application)."""
    customer, invoice = setup_customer_with_invoice(
        face_amount_cents=invoice_face, credit_limit_cents=credit_limit_cents, name="AP"
    )
    payment = create_payment(customer["id"], amount_cents=applied)
    application = apply_payment(payment["id"], invoice["id"], applied)
    return customer, invoice, payment, application


# --------------------------------------------------------------------------- #
# Tier 4: dispute lifecycle
# --------------------------------------------------------------------------- #
def create_dispute(invoice_id, amount_cents, reason_code="PRICING"):
    """Raise a dispute against an invoice; returns the OPEN Dispute object."""
    payload = create_dispute_payload(
        invoice_id, amount_cents=amount_cents, reason_code=reason_code
    )
    return get_success_data(api.create_dispute(payload, AGENT))


def setup_dispute_under_review(invoice_face=60_000, dispute_amount=10_000,
                              reason_code="PRICING"):
    """Customer + OPEN invoice + a dispute moved to UNDER_REVIEW.
    Returns (customer, invoice, dispute)."""
    customer, invoice = setup_customer_with_invoice(
        face_amount_cents=invoice_face, name="DUR"
    )
    dispute = create_dispute(invoice["id"], dispute_amount, reason_code)
    get_success_data(api.start_review_dispute(dispute["id"], MGR))
    return customer, invoice, dispute


def setup_dispute_reopened_once(invoice_face=50_000, dispute_amount=20_000):
    """Dispute taken OPEN -> UNDER_REVIEW -> RESOLVED_CREDIT(0) -> reopened.
    Returns (customer, invoice, dispute) where the dispute is back UNDER_REVIEW
    with reopen_count incremented. The reopen itself is the trigger, so this
    helper stops BEFORE reopen and returns the resolved dispute.
    Returns (customer, invoice, dispute) with dispute in RESOLVED_CREDIT."""
    customer, invoice = setup_customer_with_invoice(
        face_amount_cents=invoice_face,
        invoice_date="2026-01-01T00:00:00Z",
        due_date="2026-02-01T00:00:00Z",
        name="DR",
    )
    dispute = create_dispute(invoice["id"], dispute_amount, "PRICING")
    get_success_data(api.start_review_dispute(dispute["id"], MGR))
    get_success_data(api.resolve_dispute(dispute["id"], {"resolve_credit_cents": 0}, MGR))
    return customer, invoice, dispute


# --------------------------------------------------------------------------- #
# Tier 5: write-off lifecycle (segregation of duties aware)
# --------------------------------------------------------------------------- #
def create_pending_write_off(invoice_id, amount_cents, reason_code="UNCOLLECTIBLE",
                             creator_user_id="agent-1"):
    """Create a pending write-off as COLLECTIONS_AGENT with a specific operator id.
    Returns the WriteOff object (approved=false)."""
    payload = create_write_off_payload(invoice_id, amount_cents, reason_code=reason_code)
    headers = make_collections_agent_headers(creator_user_id)
    return get_success_data(api.create_write_off(payload, headers))


def approve_write_off(write_off_id, approver_user_id="manager-1"):
    """Approve a write-off as an AR_MANAGER bound to a distinct operator id."""
    headers = make_ar_manager_headers(approver_user_id)
    return get_success_data(api.approve_write_off(write_off_id, headers))


def setup_written_off_invoice(invoice_face=80_000, credit_limit_cents=200_000,
                              name="WO"):
    """Customer + OPEN invoice + a write-off created (agent-1) and approved
    (manager-1) so the invoice reaches WRITTEN_OFF. Returns (customer, invoice,
    write_off)."""
    customer, invoice = setup_customer_with_invoice(
        face_amount_cents=invoice_face, credit_limit_cents=credit_limit_cents, name=name
    )
    write_off = create_pending_write_off(
        invoice["id"], invoice_face, creator_user_id="agent-1"
    )
    approve_write_off(write_off["id"], approver_user_id="manager-1")
    return customer, invoice, write_off


# --------------------------------------------------------------------------- #
# Tier 6: promises
# --------------------------------------------------------------------------- #
def create_promise(customer_id, promised_amount_cents,
                   coverage_start, coverage_end, expected_version=None):
    """Create an ACTIVE promise. If expected_version is None, reads the live
    customer version first. Returns the PromiseToPay object."""
    if expected_version is None:
        expected_version = current_customer_version(customer_id)
    payload = create_promise_payload(
        customer_id,
        expected_version,
        promised_amount_cents=promised_amount_cents,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
    )
    return get_success_data(api.create_promise(payload, AGENT))


# --------------------------------------------------------------------------- #
# Tier 7: dunning runs
# --------------------------------------------------------------------------- #
def run_dunning(customer_id, sequence_id):
    """Trigger a dunning run; returns the emitted DunningNotice[] list."""
    payload = create_dunning_run_payload(customer_id, sequence_id)
    return get_success_data(api.create_dunning_run(payload, AGENT))


def create_pause(customer_id, pause_start, pause_end):
    """Schedule a dunning pause; returns the DunningPause object."""
    payload = create_dunning_pause_payload(
        customer_id, pause_start=pause_start, pause_end=pause_end
    )
    return get_success_data(api.create_dunning_pause(payload, AGENT))


# --------------------------------------------------------------------------- #
# Tier 8: composite scenarios for transitive cascade tests
# --------------------------------------------------------------------------- #
def setup_overdue_invoice_dunned(clock="2026-05-01T00:00:00Z",
                                 credit_limit_cents=100_000,
                                 face_amount_cents=100_000,
                                 invoice_date="2026-01-15T00:00:00Z",
                                 due_date="2026-03-01T00:00:00Z"):
    """Clock set; customer; one overdue invoice; a dunning sequence + run so the
    invoice has been dunned. Returns (customer, invoice, sequence). The invoice
    is overdue at the set clock and the customer has had a dunning run applied."""
    set_clock(clock)
    customer = create_customer(name="CAS", credit_limit_cents=credit_limit_cents)
    invoice = create_invoice(
        customer["id"],
        face_amount_cents=face_amount_cents,
        invoice_date=invoice_date,
        due_date=due_date,
    )
    sequence = create_dunning_sequence(name="S1")
    run_dunning(customer["id"], sequence["id"])
    return customer, invoice, sequence
