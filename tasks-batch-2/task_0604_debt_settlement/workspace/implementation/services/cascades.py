"""Cascade and compensation operations across aggregates."""
from decimal import Decimal

from db import store, touch, round_half_up
from services import core


def withdraw_debt_cascade(debt):
    """A debt moves to WITHDRAWN as part of a program drop."""
    prior_status = debt["status"]
    debt["status"] = "WITHDRAWN"
    touch(debt)
    # PENDING offers -> EXPIRED
    for o in core.debt_offers(debt["id"]):
        if o["status"] == "PENDING":
            o["status"] = "EXPIRED"
            touch(o)
    # open REFERRED lawsuit on a litigated debt -> RESOLVED_DISMISSED
    if prior_status == "LAWSUIT":
        for lw in core.debt_lawsuits(debt["id"]):
            if lw["status"] == "REFERRED":
                lw["status"] = "RESOLVED_DISMISSED"
                touch(lw)


def refund_account(program, client):
    """Refund residual account balance to the client (cents); set balance to 0
    by recording a settled offset is NOT how this works — balance is derived from
    the ledger. We refund the current derived balance and then must ensure the
    derived balance reads 0 thereafter. We do that by stamping a refunded marker."""
    bal = core.account_balance(program["id"])
    if bal > 0:
        cents = int(round_half_up(bal * 100, 0))
        client["refunded_to_client_cents"] = client.get("refunded_to_client_cents", 0) + cents
        touch(client)
    # Zero the derived balance: record the refund as a ledger reduction by
    # marking the account with a refunded_total that account_balance subtracts.
    acct = core.account_for_program(program["id"])
    if acct is not None:
        acct["_refunded"] = acct.get("_refunded", Decimal("0")) + bal
        touch(acct)


def drop_program_cascade(program, client):
    """CASCADE for POST /programs/{id}/drop."""
    for d in core.program_debts(program["id"]):
        if d["status"] in ("ENROLLED", "IN_NEGOTIATION", "LAWSUIT"):
            withdraw_debt_cascade(d)
    refund_account(program, client)


def complete_settlement_cascade(settlement):
    """CASCADE when a Settlement -> COMPLETED (§3.7)."""
    debt = store.debts[settlement["debt_id"]]
    funded = Decimal(str(settlement["funded_amount"]))
    orig = Decimal(str(debt["original_balance"]))
    forgiven = orig - funded

    # Debt -> SETTLED
    debt["settled_amount"] = funded
    debt["forgiven_amount"] = forgiven
    debt["status"] = "SETTLED"
    debt["settled_offer_id"] = settlement["offer_id"]
    touch(debt)

    # SettlementFee OUTSTANDING -> PAID
    for f in store.fees.values():
        if f["settlement_id"] == settlement["id"] and f["status"] == "OUTSTANDING":
            f["status"] = "PAID"
            touch(f)
            break

    # TaxEvent: always issued when forgiven > 0
    if forgiven > 0:
        from db import stamp_new
        tax_year = core.clock.get().year
        reportable = forgiven >= core.REPORTABLE_FLOOR
        t = stamp_new({
            "program_id": settlement["program_id"],
            "source_settlement_id": settlement["id"],
            "forgiven_amount": forgiven,
            "tax_year": tax_year,
            "reportable": reportable,
            "status": "ISSUED",
        })
        store.tax_events[t["id"]] = t

    # Lawsuit (if REFERRED) -> RESOLVED_SETTLED
    for lw in core.debt_lawsuits(debt["id"]):
        if lw["status"] == "REFERRED":
            lw["status"] = "RESOLVED_SETTLED"
            touch(lw)


def void_settlement_cascade(settlement):
    """COMPENSATION for POST /settlements/{id}/void (§3.8)."""
    debt = store.debts[settlement["debt_id"]]

    # Linked fee (still OUTSTANDING) -> WAIVED
    for f in store.fees.values():
        if f["settlement_id"] == settlement["id"] and f["status"] == "OUTSTANDING":
            f["status"] = "WAIVED"
            touch(f)
            break

    # Debt reverts to IN_NEGOTIATION; reset settled fields
    debt["status"] = "IN_NEGOTIATION"
    debt["settled_amount"] = Decimal("0")
    debt["forgiven_amount"] = Decimal("0")
    debt["settled_offer_id"] = None
    touch(debt)

    # Source offer ACCEPTED -> PENDING
    offer = store.offers.get(settlement["offer_id"])
    if offer is not None and offer["status"] == "ACCEPTED":
        offer["status"] = "PENDING"
        touch(offer)

    # ISSUED TaxEvent for this settlement -> VOIDED
    for t in store.tax_events.values():
        if t["source_settlement_id"] == settlement["id"] and t["status"] == "ISSUED":
            t["status"] = "VOIDED"
            touch(t)

    # Settlement funded_amount credit-back happens because the settlement leaves
    # FUNDED/COMPLETED (its status becomes VOIDED), so account_balance no longer
    # subtracts it; the fee is WAIVED so no fee debit. Balance is conserved.
