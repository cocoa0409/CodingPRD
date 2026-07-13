"""Invoice per-line rounding and the payment-settlement cascade."""
from test_helpers import (
    validate_success, make_billing_clerk_headers,
    create_facility, create_cell, create_hauler, create_ticket, weigh_out, inspect,
    post_ticket, create_invoice, create_payment,
    setup_suspended_hauler_with_invoice,
)

INSPECT_USER = "op_insp"
POST_USER = "op_post"


def _three_posted_debris_invoice(api):
    facility = create_facility(1000)
    create_cell(facility["id"], 1000)
    hauler = create_hauler(100_000_000)
    for _ in range(3):
        tk = create_ticket(facility["id"], hauler["id"], material="CONSTRUCTION_DEBRIS",
                           gross_weight_tons=1.5, op_id=INSPECT_USER)
        weigh_out(tk["id"], 1.0, op_id=INSPECT_USER)
        inspect(tk["id"], "PASS", op_id=INSPECT_USER)
        post_ticket(tk["id"], facility["id"], op_id=POST_USER)
    return create_invoice(hauler["id"])


def test_invoice_total_rounds_host_fee_per_line_then_sums(api):
    """PRD §3.9: "The billed `total_cents` layers on the host fee of 8.75 percent, with the
    rounding order pinned: for each line ticket, the ticket's `tipping_fee_cents` is
    multiplied by 1.0875 and rounded half up to whole cents, and only then are those per-line
    amounts summed."

    Design: Difficulty/combinatorial_formula/invoice_rounding_per_line_then_sum
    """
    invoice = _three_posted_debris_invoice(api)
    assert invoice["total_cents"] == 8484


def test_invoice_tipping_subtotal_is_plain_sum(api):
    """PRD §3.9: "The `tipping_subtotal_cents` is the plain sum of `tipping_fee_cents` across
    the line tickets — the amount that will be released from the hauler's balance when the
    invoice is paid."

    Design: Difficulty/combinatorial_formula/invoice_rounding_per_line_then_sum
    """
    invoice = _three_posted_debris_invoice(api)
    assert invoice["tipping_subtotal_cents"] == 7800


def test_full_payment_settles_invoice_to_paid(api):
    """PRD §3.9: "When the cumulative `amount_paid_cents` reaches the invoice's `total_cents`,
    the invoice transitions `ISSUED → PAID`, and a cascade releases the hauler's exposure: for
    each line ticket the hauler's `balance_cents` is decreased by that ticket's
    `tipping_fee_cents`, and if the resulting balance is below the credit limit while the
    account is `SUSPENDED`, the account transitions back to `ACTIVE`."

    Design: Difficulty/transitive_cascade/payment_settles_invoice_reactivates_hauler
    """
    ctx = setup_suspended_hauler_with_invoice()
    create_payment(ctx["invoice"]["id"], 5656, method="ACH")
    invoice = validate_success(
        api.get_invoice(ctx["invoice"]["id"], make_billing_clerk_headers("bc1")))
    assert invoice["status"] == "PAID"


def test_payment_releases_balance_and_reactivates_hauler(api):
    """PRD §3.9: "When the cumulative `amount_paid_cents` reaches the invoice's `total_cents`,
    the invoice transitions `ISSUED → PAID`, and a cascade releases the hauler's exposure: for
    each line ticket the hauler's `balance_cents` is decreased by that ticket's
    `tipping_fee_cents`, and if the resulting balance is below the credit limit while the
    account is `SUSPENDED`, the account transitions back to `ACTIVE`."

    Design: Difficulty/transitive_cascade/payment_settles_invoice_reactivates_hauler
    """
    ctx = setup_suspended_hauler_with_invoice()
    suspended = validate_success(
        api.get_hauler_account(ctx["hauler"]["id"], make_billing_clerk_headers("bc1")))
    assert suspended["status"] == "SUSPENDED"
    create_payment(ctx["invoice"]["id"], 5656, method="ACH")
    hauler = validate_success(
        api.get_hauler_account(ctx["hauler"]["id"], make_billing_clerk_headers("bc1")))
    assert hauler["balance_cents"] == 0
    assert hauler["status"] == "ACTIVE"
