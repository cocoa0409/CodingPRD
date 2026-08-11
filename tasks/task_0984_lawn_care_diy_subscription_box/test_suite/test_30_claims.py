"""Satisfaction claim resolution branches and terminal lockdown (PRD 3.9)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]
AGRONOMIST = th.TEST_USERS["agronomist_headers"]


def _setup_filed_claim(api, email, qty=1, claim_reason="OTHER",
                       deliver_clock=None):
    ctx = th.setup_active_subscription(email=email)
    box, invoice = th.setup_delivered_box(
        ctx, lines=[th.shipment_line("FERT-01", qty)],
        deliver_clock=deliver_clock,
    )
    claim = th.file_claim(ctx, box, claim_reason=claim_reason)
    return ctx, box, invoice, claim


def test_claim_deny_branch_has_no_side_effects(api):
    """PRD 3.9: "A `DENY` selection moves the claim to `DENIED` with no further effects."

    Design: Corner/state_machines/claim_deny_branch_has_no_side_effects
    """
    ctx, box, _, claim = _setup_filed_claim(api, email="s10@x.com")

    resolved = th.validate_success(
        api.resolve_claim(claim["id"], {"resolution_type": "DENY"}, AGRONOMIST)
    )
    assert resolved["status"] == "DENIED"

    replacements, _ = th.validate_paginated(
        api.list_shipments(ADMIN, params={"source_claim_id": claim["id"]})
    )
    assert replacements == [], "DENY mints no REPLACEMENT box"
    assert th.list_ledger(customer_id=ctx["customer"]["id"]) == [], (
        "DENY posts no ledger entries"
    )
    assert th.get_customer_balance(ctx["customer"]["id"]) == 0


def test_claim_credit_branch_posts_capped_credit(api):
    """PRD 3.9: "A `CREDIT` resolution sets `credit_amount_cents` to the smaller of the shipment's `final_charge_cents` and a 10,000-cent cap, and posts an `EARN_SATISFACTION` ledger entry of that amount to the customer."

    Design: Corner/state_machines/claim_credit_branch_posts_capped_credit
    """
    # 5 x 800 = 4000 final charge (delivered 2026-06-05, outside [03-01, 06-01)
    # so no early-season discount) — below the 10,000-cent cap.
    ctx, box, _, claim = _setup_filed_claim(
        api, email="s11@x.com", qty=5, claim_reason="INEFFECTIVE",
        deliver_clock="2026-06-05T00:00:00Z",
    )
    assert box["final_charge_cents"] == 4000

    resolved = th.validate_success(
        api.resolve_claim(claim["id"], {"resolution_type": "CREDIT"}, AGRONOMIST)
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["credit_amount_cents"] == 4000, (
        "credit_amount_cents = min(final_charge_cents 4000, cap 10000)"
    )

    entries = th.list_ledger(customer_id=ctx["customer"]["id"],
                             entry_type="EARN_SATISFACTION")
    assert len(entries) == 1
    assert entries[0]["amount_cents"] == 4000
    assert entries[0]["reference_id"] == claim["id"]
    assert th.get_customer_balance(ctx["customer"]["id"]) == 4000


def test_claim_resolve_terminal_lockdown(api):
    """PRD 3.9: "An Agronomist resolves a `FILED` claim — any other state is rejected with `ERR_CLAIM_NOT_FILED` (HTTP 409) — by choosing a `resolution_type`, and the choice selects one of three divergent side-effect branches."
    PRD 3.9: "Resolutions move the claim to the terminal `RESOLVED` (or `DENIED`) state and increment its `version` by 1."

    Design: Corner/state_machines/claim_resolve_terminal_lockdown
    """
    ctx, _, _, claim = _setup_filed_claim(api, email="s12@x.com",
                                          claim_reason="DAMAGED")
    th.validate_success(
        api.resolve_claim(claim["id"], {"resolution_type": "DENY"}, AGRONOMIST)
    )
    # DENIED is terminal: a second resolution is a state error and posts no
    # double credit.
    th.validate_error(
        api.resolve_claim(claim["id"], {"resolution_type": "CREDIT"}, AGRONOMIST),
        th.ApiErrorId.ERR_CLAIM_NOT_FILED,
    )
    assert th.list_ledger(customer_id=ctx["customer"]["id"]) == []


def test_claim_refund_requires_paid_invoice(api):
    """PRD 3.9: "A `REFUND` resolution is permitted only when the shipment's `billing_status` is `PAID` — otherwise `ERR_SHIPMENT_NOT_PAID` (HTTP 409) — and flips that billing status from `PAID` to `VOID`, posting a `RESTORE_VOID_INVOICE` ledger entry only for the invoice's `credit_applied_cents`; money already collected is returned out of band."

    Design: Corner/state_machines/claim_refund_requires_paid_invoice
    """
    # The box is DELIVERED but its invoice was never paid (still ISSUED).
    ctx, _, _, claim = _setup_filed_claim(api, email="s13@x.com")
    th.validate_error(
        api.resolve_claim(claim["id"], {"resolution_type": "REFUND"}, AGRONOMIST),
        th.ApiErrorId.ERR_SHIPMENT_NOT_PAID,
    )
    after = th.validate_success(api.get_claim(claim["id"], ADMIN))
    assert after["status"] == "FILED", "a rejected resolution leaves the claim FILED"
