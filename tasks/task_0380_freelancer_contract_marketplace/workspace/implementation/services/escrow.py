"""Escrow ledger writes and the release/refund cascades (PRD 2.9, 3.5-3.7)."""
import db
from response import now_iso
from services import calc, derive


def _new_txn(contract_id, milestone_id, txn_type, amount_cents, status):
    rec = {
        "id": db.new_id(),
        "created_at": now_iso(),
        "_seq": db.next_seq(),
        "contract_id": contract_id,
        "milestone_id": milestone_id,
        "txn_type": txn_type,
        "amount_cents": amount_cents,
        "status": status,
    }
    db.escrow_transactions[rec["id"]] = rec
    return rec


def fund(contract, milestone, amount_cents):
    """FUND: debit wallet, write HELD ledger row, bump lifetime_funded (PRD 3.5)."""
    client = db.clients[contract["client_id"]]
    client["wallet_balance_cents"] -= amount_cents
    client["lifetime_funded_cents"] += amount_cents
    db.touch(client)
    _new_txn(contract["id"], milestone["id"], "FUND", amount_cents, "HELD")


def _settle_funds(milestone_id):
    """Move this milestone's HELD FUND rows to SETTLED (on release)."""
    for txn in db.escrow_transactions.values():
        if txn["milestone_id"] == milestone_id and txn["txn_type"] == "FUND" \
                and txn["status"] == "HELD":
            txn["status"] = "SETTLED"


def _reverse_funds(milestone_id):
    """Move this milestone's HELD FUND rows to REVERSED (on refund)."""
    for txn in db.escrow_transactions.values():
        if txn["milestone_id"] == milestone_id and txn["txn_type"] == "FUND" \
                and txn["status"] == "HELD":
            txn["status"] = "REVERSED"


def create_payout(contract, milestone, gross_cents):
    """Create a PENDING Payout, computing platform fee and net (PRD 3.6)."""
    freelancer = db.freelancers[contract["freelancer_id"]]
    # fee keyed on pre-payout lifetime_earnings_cents and current dispute losses
    fee, net = calc.platform_fee(
        gross_cents,
        freelancer["lifetime_earnings_cents"],
        derive.freelancer_dispute_loss_count(freelancer["id"]),
    )
    rec = db.new_common()
    year = int(now_iso()[:4])
    rec.update({
        "freelancer_id": freelancer["id"],
        "milestone_id": milestone["id"],
        "gross_cents": gross_cents,
        "platform_fee_cents": fee,
        "net_cents": net,
        "tax_year": year,
        "status": "PENDING",
    })
    db.payouts[rec["id"]] = rec
    # lifetime_gross_billed is derived from payouts; reputation/fee_tier follow
    # lifetime_earnings which only changes on PAID, but recompute to keep tier
    # consistent if anything shifted.
    derive.recompute_freelancer_reputation(freelancer)
    return rec


def release_full(contract, milestone):
    """Standard release of full funded escrow on an APPROVED milestone (PRD 3.5).

    Returns nothing; mutates ledger, milestone, freelancer, contract version.
    """
    funded = derive.milestone_funded_cents(milestone["id"])
    _new_txn(contract["id"], milestone["id"], "RELEASE", funded, "SETTLED")
    _settle_funds(milestone["id"])
    milestone["status"] = "RELEASED"
    db.touch(milestone)
    create_payout(contract, milestone, funded)
    contract["version"] += 1
    contract["updated_at"] = now_iso()


def release_award(contract, milestone, award_cents):
    """Dispute resolution with award > 0: release award, refund remainder (PRD 3.7)."""
    funded = derive.milestone_funded_cents(milestone["id"])
    _new_txn(contract["id"], milestone["id"], "RELEASE", award_cents, "SETTLED")
    remainder = funded - award_cents
    if remainder > 0:
        client = db.clients[contract["client_id"]]
        client["wallet_balance_cents"] += remainder
        db.touch(client)
        _new_txn(contract["id"], milestone["id"], "REFUND", remainder, "SETTLED")
    _settle_funds(milestone["id"])
    milestone["status"] = "RELEASED"
    db.touch(milestone)
    create_payout(contract, milestone, award_cents)


def refund_full(contract, milestone):
    """Refund the full held escrow to the client wallet (PRD 3.7 / terminate)."""
    funded = derive.milestone_funded_cents(milestone["id"])
    if funded > 0:
        client = db.clients[contract["client_id"]]
        client["wallet_balance_cents"] += funded
        db.touch(client)
        _new_txn(contract["id"], milestone["id"], "REFUND", funded, "SETTLED")
        _reverse_funds(milestone["id"])
