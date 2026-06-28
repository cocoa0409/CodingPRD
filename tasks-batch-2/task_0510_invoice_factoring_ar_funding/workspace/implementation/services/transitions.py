"""Invoice money-moving transitions: funding, settlement, short-pay, buyback,
write-off. Each updates the invoice, cascades to client/debtor balances, and
appends ledger entries in the order pinned by PRD §3.5-§3.7."""

import db
import errors
from common import touch
from services import calc, ledger


# ---------------------------------------------------------------------------
# Funding (VERIFIED -> FUNDED). Side-effects applied; caller handles batch
# atomicity. Assumes all funding preconditions already passed.
# ---------------------------------------------------------------------------
def fund_invoice(invoice, client, debtor, program):
    advance_rate = client["approved_advance_rate_pct"]
    fee_rate = program["default_fee_rate_per_day"]
    advance, reserve = calc.advance_split(invoice["face_amount_cents"], advance_rate)

    invoice["advance_rate_pct"] = advance_rate
    invoice["fee_rate_per_day"] = fee_rate
    invoice["advance_amount_cents"] = advance
    invoice["reserve_held_cents"] = reserve
    invoice["advance_outstanding_cents"] = advance
    invoice["funded_at"] = db.clock_now().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    invoice["status"] = "FUNDED"
    invoice["aging_bucket"] = calc.aging_bucket(invoice)
    touch(invoice)

    # Cascade: client + debtor balances.
    ledger.recompute_client_balances(client)
    ledger.recompute_debtor_balance(debtor)

    # Ledger: ADVANCE_DISBURSED then RESERVE_HELD.
    ledger.append_ledger(client, invoice["id"], "ADVANCE_DISBURSED", advance)
    ledger.append_ledger(client, invoice["id"], "RESERVE_HELD", reserve)


# ---------------------------------------------------------------------------
# Settlement (FUNDED/OUTSTANDING -> SETTLED) on full collection.
# ---------------------------------------------------------------------------
def settle_invoice(invoice, client, debtor, program):
    cutoff = calc.latest_posted_received_at(invoice["id"]) or db.clock_now()
    final = calc.final_fee(invoice, program, cutoff)

    collected = calc.amount_collected(invoice["id"])
    wf = calc.settlement_waterfall(collected, invoice["advance_amount_cents"], final)

    invoice["final_fee_cents"] = final
    invoice["accrued_fee_cents"] = final
    invoice["advance_outstanding_cents"] = invoice["advance_amount_cents"] - wf["principal_applied_cents"]
    # Terminalize.
    invoice["status"] = "SETTLED"
    invoice["advance_outstanding_cents"] = 0
    touch(invoice)

    settlement = {
        "invoice_id": invoice["id"],
        "collected_total_cents": collected,
        "principal_applied_cents": wf["principal_applied_cents"],
        "fee_applied_cents": wf["fee_applied_cents"],
        "rebate_cents": wf["rebate_cents"],
        "fee_shortfall_cents": wf["fee_shortfall_cents"],
    }
    from common import stamp_common
    stamp_common(settlement)
    db.settlements[settlement["id"]] = settlement

    # Cascade to client + debtor balances.
    ledger.recompute_client_balances(client)
    ledger.recompute_debtor_balance(debtor)

    # Ledger: FEE_ACCRUED, REBATE_PAID, RESERVE_RELEASED.
    ledger.append_ledger(client, invoice["id"], "FEE_ACCRUED", wf["fee_applied_cents"])
    ledger.append_ledger(client, invoice["id"], "REBATE_PAID", wf["rebate_cents"])
    ledger.append_ledger(client, invoice["id"], "RESERVE_RELEASED", invoice["reserve_held_cents"])

    if wf["fee_shortfall_cents"] > 0:
        _auto_chargeback(invoice, wf["fee_shortfall_cents"])

    return settlement


def _auto_chargeback(invoice, amount):
    from common import stamp_common
    adj = {
        "invoice_id": invoice["id"],
        "type": "CHARGEBACK_FEE",
        "amount_cents": amount,
        "reason": "Automatic chargeback for uncovered factor fee at settlement",
    }
    stamp_common(adj)
    db.adjustments[adj["id"]] = adj
    return adj


# ---------------------------------------------------------------------------
# Short pay (OUTSTANDING -> SHORT_PAID) on close-collection.
# ---------------------------------------------------------------------------
def short_pay_invoice(invoice, client, debtor, program):
    cutoff = calc.latest_posted_received_at(invoice["id"]) or db.clock_now()
    final = calc.final_fee(invoice, program, cutoff)
    collected = calc.amount_collected(invoice["id"])
    wf = calc.settlement_waterfall(collected, invoice["advance_amount_cents"], final)

    invoice["final_fee_cents"] = final
    invoice["accrued_fee_cents"] = final
    invoice["advance_outstanding_cents"] = invoice["advance_amount_cents"] - wf["principal_applied_cents"]
    invoice["status"] = "SHORT_PAID"
    touch(invoice)

    # Client reserve/funded balances stay (residual advance still at risk),
    # but recompute so derived figures reflect that SHORT_PAID is still in the
    # exposure set.
    ledger.recompute_client_balances(client)
    ledger.recompute_debtor_balance(debtor)

    # Ledger: COLLECTION_POSTED then FEE_ACCRUED.
    ledger.append_ledger(client, invoice["id"], "COLLECTION_POSTED", collected)
    ledger.append_ledger(client, invoice["id"], "FEE_ACCRUED", wf["fee_applied_cents"])


def last_settlement(invoice_id):
    """Most-recent Settlement for the invoice (there is at most one)."""
    found = None
    for s in db.settlements.values():
        if s["invoice_id"] == invoice_id:
            if found is None or s["_seq"] > found["_seq"]:
                found = s
    return found


# ---------------------------------------------------------------------------
# Buyback (SHORT_PAID/OUTSTANDING -> BOUGHT_BACK).
# ---------------------------------------------------------------------------
def buyback_invoice(invoice, client, debtor, program, trigger_reason):
    cutoff = db.clock_now()
    final = calc.final_fee(invoice, program, cutoff)

    prior = last_settlement(invoice["id"])
    fee_already_covered = prior["fee_applied_cents"] if prior else 0
    uncovered_fee = max(0, final - fee_already_covered)

    advance_outstanding = invoice["advance_outstanding_cents"]
    buyback_amount = advance_outstanding + uncovered_fee
    reserve_released = invoice["reserve_held_cents"]

    invoice["final_fee_cents"] = final
    invoice["accrued_fee_cents"] = final
    invoice["status"] = "BOUGHT_BACK"
    invoice["advance_outstanding_cents"] = 0
    touch(invoice)

    buyback = {
        "invoice_id": invoice["id"],
        "trigger_reason": trigger_reason,
        "buyback_amount_cents": buyback_amount,
        "reserve_released_cents": reserve_released,
        "status": "COMPLETED",
    }
    from common import stamp_common
    stamp_common(buyback)
    db.buybacks[buyback["id"]] = buyback

    ledger.recompute_client_balances(client)
    ledger.recompute_debtor_balance(debtor)

    # Ledger: BUYBACK_RECEIVED then RESERVE_RELEASED.
    ledger.append_ledger(client, invoice["id"], "BUYBACK_RECEIVED", buyback_amount)
    ledger.append_ledger(client, invoice["id"], "RESERVE_RELEASED", reserve_released)

    return buyback


# ---------------------------------------------------------------------------
# Write-off (OUTSTANDING/SHORT_PAID -> WRITTEN_OFF).
# ---------------------------------------------------------------------------
def write_off_invoice(invoice, client, debtor, program):
    cutoff = db.clock_now()
    final = calc.final_fee(invoice, program, cutoff)
    advance_outstanding = invoice["advance_outstanding_cents"]
    reserve_released = invoice["reserve_held_cents"]

    invoice["final_fee_cents"] = final
    invoice["accrued_fee_cents"] = final
    invoice["status"] = "WRITTEN_OFF"
    invoice["advance_outstanding_cents"] = 0
    touch(invoice)

    ledger.recompute_client_balances(client)
    ledger.recompute_debtor_balance(debtor)

    # Ledger: WRITE_OFF then RESERVE_RELEASED.
    ledger.append_ledger(client, invoice["id"], "WRITE_OFF", advance_outstanding)
    ledger.append_ledger(client, invoice["id"], "RESERVE_RELEASED", reserve_released)


# ---------------------------------------------------------------------------
# Clock advance side-effect: auto FUNDED -> OUTSTANDING for now-past-due.
# ---------------------------------------------------------------------------
def advance_clock_side_effects():
    now = db.clock_now()
    for inv in db.invoices.values():
        if inv["status"] == "FUNDED":
            due = db.parse_iso(inv["due_date"])
            collectible = inv["face_amount_cents"] - calc.dilution_cents(inv["id"])
            collected = calc.amount_collected(inv["id"])
            if now > due and collected < collectible:
                inv["status"] = "OUTSTANDING"
                inv["aging_bucket"] = calc.aging_bucket(inv)
                touch(inv)
        elif inv["status"] == "OUTSTANDING":
            inv["aging_bucket"] = calc.aging_bucket(inv)
