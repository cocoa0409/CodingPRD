"""The cure-payment two-bucket waterfall (PRD 3.6)."""

from clock import clock
from db import base_row, db, touch
from money import floor_cents, frac
from services import computed
from services.constants import ON_BOOK_FUNDING
from services.ledger import post_entry
from services.states import reevaluate_restricted


def covered_advances(call):
    """When the call names an advance_id the covered set is that single advance;
    when the call is facility-level it is every advance of the facility whose
    funding_status is FUNDED or SHIPPED, ordered by created_at ascending."""
    if call["advance_id"] is not None:
        advance = db.advances.get(call["advance_id"])
        return [advance] if advance is not None else []
    return [a for a in computed.facility_advances(call["facility_id"])
            if a["funding_status"] in ON_BOOK_FUNDING]


def remaining_obligation(call):
    return max(0, call["call_amount_cents"] - call["cured_amount_cents"])


def apply_cure_payment(call, facility, amount_cents):
    fee_balance = computed.accrued_fee_balance(facility["id"])
    applied_to_fees = min(amount_cents, fee_balance)
    if applied_to_fees < 0:
        applied_to_fees = 0
    obligation = remaining_obligation(call)
    applied_to_principal = min(amount_cents - applied_to_fees, obligation)

    covered = covered_advances(call)
    balances = [(a, computed.advance_outstanding(a)) for a in covered]
    total = sum(b for _, b in balances)

    allocation = []
    if total > 0 and applied_to_principal > 0:
        shares = []
        for advance, balance in balances:
            share = floor_cents(frac(applied_to_principal) * frac(balance)
                                / frac(total))
            shares.append(share)
        leftover = applied_to_principal - sum(shares)
        index = 0
        while leftover > 0 and shares:
            shares[index] += 1
            leftover -= 1
            index = (index + 1) % len(shares)
        for (advance, _balance), share in zip(balances, shares):
            allocation.append({"advance_id": advance["id"], "amount_cents": share})
    else:
        for advance, _balance in balances:
            allocation.append({"advance_id": advance["id"], "amount_cents": 0})

    payment = base_row(with_version=False)
    payment.update({
        "margin_call_id": call["id"],
        "amount_cents": amount_cents,
        "applied_to_fees_cents": applied_to_fees,
        "applied_to_principal_cents": applied_to_principal,
        "principal_allocation": allocation,
        "applied_at": clock.now(),
    })
    db.cure_payments[payment["id"]] = payment

    if applied_to_fees > 0:
        post_entry(facility["id"], None, "FEE_PAYMENT", "CREDIT", applied_to_fees,
                   "Cure payment applied to accrued fees")
    for entry in allocation:
        if entry["amount_cents"] > 0:
            post_entry(facility["id"], entry["advance_id"], "CURE_PRINCIPAL",
                       "CREDIT", entry["amount_cents"],
                       "Cure payment applied to principal")

    call["cured_amount_cents"] += applied_to_principal
    if call["cured_amount_cents"] >= call["call_amount_cents"]:
        call["status"] = "CURED"
    else:
        call["status"] = "PARTIALLY_CURED"
    touch(call)
    touch(facility)

    for advance, _balance in balances:
        computed.store_valuation(advance)

    if call["status"] == "CURED":
        reevaluate_restricted(facility)
    return payment
