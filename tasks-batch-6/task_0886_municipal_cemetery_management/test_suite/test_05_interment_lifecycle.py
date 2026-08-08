"""Opening, closing, cancelling, and the two independent interment axes."""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, setup_scheduled_interment, pay_invoice, set_clock,
)

REG = TEST_USERS["registrar_headers"]
GF = TEST_USERS["grounds_foreman_headers"]


# ── Difficulty: non_linear_state_machine / interment_parallel_billing_vs_operational_axes ──

def test_service_payment_advances_billing_status(api):
    """PRD §3.4: "The billing_status axis tracks money — INVOICED, PAID, and VOIDED —
    and moves on its own: it becomes PAID when the service invoice is paid and VOIDED
    when the service invoice is voided on cancellation, entirely independently of where
    the operational axis stands."

    Design: Difficulty/non_linear_state_machine/interment_parallel_billing_vs_operational_axes
    """
    r = setup_scheduled_interment()
    pay_invoice(r["service_invoice_id"])
    interment = validate_success(api.get_interment(r["interment"]["id"], REG), 200)
    assert interment["billing_status"] == "PAID"


def test_service_payment_leaves_operational_scheduled(api):
    """PRD §3.4: "The billing_status axis tracks money — INVOICED, PAID, and VOIDED —
    and moves on its own: it becomes PAID when the service invoice is paid and VOIDED
    when the service invoice is voided on cancellation, entirely independently of where
    the operational axis stands."

    Design: Difficulty/non_linear_state_machine/interment_parallel_billing_vs_operational_axes
    """
    r = setup_scheduled_interment()
    pay_invoice(r["service_invoice_id"])
    interment = validate_success(api.get_interment(r["interment"]["id"], REG), 200)
    assert interment["operational_status"] == "SCHEDULED"


# ── Difficulty: cross_entity_state_dependency / open_requires_paid_service_invoice ──

def test_open_with_unpaid_service_invoice_rejected(api):
    """PRD §3.4: "A GroundsForeman opens a grave, moving operational_status from
    SCHEDULED to OPENED, only after two conditions hold: the interment's service invoice
    has been paid, meaning its billing_status is PAID (otherwise ERR_INVOICE_UNPAID),
    and the current logical-clock date is on or after the scheduled_date (otherwise
    ERR_TOO_EARLY_TO_OPEN)."

    Design: Difficulty/cross_entity_state_dependency/open_requires_paid_service_invoice
    """
    r = setup_scheduled_interment(scheduled_date="2026-06-01")
    set_clock("2026-06-01T00:00:00Z")  # on/after scheduled_date, isolating the fiscal gate
    res = api.open_interment(r["interment"]["id"], GF)
    validate_error(res, "ERR_INVOICE_UNPAID")


def test_open_after_service_payment_succeeds(api):
    """PRD §3.4: "A GroundsForeman opens a grave, moving operational_status from
    SCHEDULED to OPENED, only after two conditions hold: the interment's service invoice
    has been paid, meaning its billing_status is PAID (otherwise ERR_INVOICE_UNPAID),
    and the current logical-clock date is on or after the scheduled_date (otherwise
    ERR_TOO_EARLY_TO_OPEN)."

    Design: Difficulty/cross_entity_state_dependency/open_requires_paid_service_invoice
    """
    r = setup_scheduled_interment(scheduled_date="2026-06-01", pay_service=True)
    set_clock("2026-06-01T00:00:00Z")
    opened = validate_success(api.open_interment(r["interment"]["id"], GF), 200)
    assert opened["operational_status"] == "OPENED"


# ── Corner: validations / open_before_scheduled_date_too_early ──

def test_open_before_scheduled_date_rejected(api):
    """PRD §3.4: "the current logical-clock date is on or after the scheduled_date
    (otherwise ERR_TOO_EARLY_TO_OPEN)."

    Design: Corner/validations/open_before_scheduled_date_too_early
    """
    r = setup_scheduled_interment(scheduled_date="2026-06-01", pay_service=True)
    set_clock("2026-05-15T00:00:00Z")  # before scheduled_date
    res = api.open_interment(r["interment"]["id"], GF)
    validate_error(res, "ERR_TOO_EARLY_TO_OPEN")


# ── Corner: state_machines / cancel_already_cancelled_interment_invalid_state ──

def test_cancel_already_cancelled_interment_invalid_state(api):
    """PRD §3.4: "A Registrar may cancel an interment while it is SCHEDULED or OPENED,
    moving it to the terminal CANCELLED." PRD §3.4: "A schedule paired with its
    cancellation leaves the plot's occupancy count exactly where it started."

    Design: Corner/state_machines/cancel_already_cancelled_interment_invalid_state
    """
    r = setup_scheduled_interment()
    validate_success(api.cancel_interment(r["interment"]["id"], REG), 200)
    res = api.cancel_interment(r["interment"]["id"], REG)
    validate_error(res, "ERR_INVALID_STATE")
    plot = validate_success(api.get_plot(r["plot"]["id"], REG), 200)
    assert plot["interments_used"] == 0
