"""Customer parallel postures: the independent credit_status and
collection_stage dimensions, and the credit-hold gate on invoice creation.

Queue A (Difficulty): manual hold moves credit_status to HOLD without touching
collection_stage; invoice creation is gated by the customer's credit hold.
"""
from test_helpers import (
    validate_success,
    validate_error,
    create_customer,
    create_invoice_payload,
)


# --------------------------------------------------------------------------- #
# Queue A — parallel, independent dimensions
# --------------------------------------------------------------------------- #
def test_manual_hold_sets_credit_hold_leaves_collection_stage_current(api, ar_manager_headers):
    """PRD §2.7: "An `AR_MANAGER` may place a manual credit hold on a customer,
    which sets `manual_hold` to true and forces `credit_status` to `HOLD`
    regardless of exposure".
    PRD §2.6: "The two customer postures are **parallel and independent**.
    `credit_status` answers "may we extend more credit?"; `collection_stage`
    answers "how far gone is recovery?"."

    Design: Difficulty/non_linear_state_machine/customer_parallel_credit_and_collection_dimensions_independent
    """
    customer = create_customer(name="PAR")
    held = validate_success(api.hold_customer(customer["id"], ar_manager_headers), 200)
    assert held["credit_status"] == "HOLD"
    assert held["collection_stage"] == "CURRENT", "collection axis untouched by the credit hold"


def test_release_hold_restores_credit_good_collection_stage_still_current(api, ar_manager_headers):
    """PRD §2.7: "releasing the hold clears `manual_hold` and recomputes
    `credit_status` from exposure."
    PRD §2.6: "The two customer postures are **parallel and independent**...
    one never substitutes for the other."

    Holding then releasing moves credit_status HOLD -> GOOD while
    collection_stage never leaves CURRENT, proving the two axes evolve on their
    own triggers.

    Design: Difficulty/non_linear_state_machine/customer_parallel_credit_and_collection_dimensions_independent
    """
    customer = create_customer(name="PAR2")
    validate_success(api.hold_customer(customer["id"], ar_manager_headers), 200)
    released = validate_success(api.release_hold_customer(customer["id"], ar_manager_headers), 200)
    assert released["credit_status"] == "GOOD"
    assert released["collection_stage"] == "CURRENT"


# --------------------------------------------------------------------------- #
# Queue A — invoice creation gated by credit hold
# --------------------------------------------------------------------------- #
def test_invoice_create_blocked_by_manual_credit_hold(api, ar_manager_headers, ar_clerk_headers):
    """PRD §3.1: "Creation runs the credit gate of §2.7: if the customer is on
    `HOLD`, the invoice is refused with `ERR_CREDIT_HOLD`."
    PRD §2.7: "Creating an invoice for a customer whose `credit_status` is `HOLD`
    at request time — whether because `manual_hold` is active or because current
    `exposure_cents` is at or above `credit_limit_cents` — is rejected with
    `ERR_CREDIT_HOLD` (HTTP 402)."

    Design: Difficulty/cross_entity_state_dependency/invoice_create_blocked_by_customer_credit_hold
    """
    customer = create_customer(name="CE2")
    validate_success(api.hold_customer(customer["id"], ar_manager_headers), 200)
    res = api.create_invoice(
        create_invoice_payload(
            customer["id"], face_amount_cents=1000,
            invoice_date="2026-01-01T00:00:00Z", due_date="2026-02-01T00:00:00Z",
        ),
        ar_clerk_headers,
    )
    validate_error(res, "ERR_CREDIT_HOLD")


def test_invoice_create_allowed_after_hold_released(api, ar_manager_headers, ar_clerk_headers):
    """PRD §2.7: "releasing the hold clears `manual_hold` and recomputes
    `credit_status` from exposure. A manual hold holds the account until it is
    explicitly released."
    PRD §3.1: "Creation runs the credit gate of §2.7: if the customer is on
    `HOLD`, the invoice is refused with `ERR_CREDIT_HOLD`."

    Once the manual hold is released (exposure low, credit_status GOOD), invoice
    creation passes the gate.

    Design: Difficulty/cross_entity_state_dependency/invoice_create_blocked_by_customer_credit_hold
    """
    customer = create_customer(name="CE2b")
    validate_success(api.hold_customer(customer["id"], ar_manager_headers), 200)
    validate_success(api.release_hold_customer(customer["id"], ar_manager_headers), 200)
    res = api.create_invoice(
        create_invoice_payload(
            customer["id"], face_amount_cents=1000,
            invoice_date="2026-01-01T00:00:00Z", due_date="2026-02-01T00:00:00Z",
        ),
        ar_clerk_headers,
    )
    invoice = validate_success(res, 201)
    assert invoice["status"] == "OPEN"
