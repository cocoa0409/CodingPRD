"""Dormancy sweep (PRD §3.9)."""
import db
from services import budget


def _candidates(program):
    out = []
    for payout in db.payouts.values():
        if payout["status"] != "RELEASED":
            continue
        prog = db.program_of_payout(payout)
        if prog is None or prog["id"] != program["id"]:
            continue
        out.append(payout)
    # ordered by released_at ASC then created_at ASC, never by id
    return sorted(out, key=lambda p: (p["released_at"], p["created_at"], p["_seq"]))


def sweep(program):
    clock = db.now()
    created = []

    for payout in _candidates(program):
        claim = db.claims.get(payout["claim_id"])
        if claim is None:
            continue
        card = None
        if payout["method"] == "CHECK":
            anchor = payout["released_at"]
            limit = db.ESCHEAT_DORMANCY_DAYS
            amount = payout["net_cents"]
        else:
            cards = db.cards_of_payout(payout["id"])
            card = cards[0] if cards else None
            if card is None:
                continue
            anchor = card["last_activity_at"]
            limit = db.CARD_DORMANCY_DAYS
            amount = card["remaining_balance_cents"]
        if anchor is None:
            continue

        dormancy_days = db.whole_days(clock, anchor)
        if dormancy_days < limit:
            continue

        claimant = db.claimants.get(claim["claimant_id"])
        mailing_state = claimant["mailing_state"] if claimant else ""
        jurisdiction = mailing_state if mailing_state else program["escheat_jurisdiction"]

        record = db.base_record(versioned=False)
        record.update({
            "payout_id": payout["id"],
            "program_id": program["id"],
            "amount_cents": amount,
            "jurisdiction": jurisdiction,
            "dormancy_days": dormancy_days,
            "swept_at": clock,
        })
        db.escheat_records[record["id"]] = record
        created.append(record)

        payout["status"] = "ESCHEATED"
        db.touch(payout)
        claim["payment_status"] = "ESCHEATED"
        db.touch(claim)
        for c in db.cards_of_payout(payout["id"]):
            if c["status"] in ("ISSUED", "ACTIVATED", "PARTIALLY_USED"):
                c["status"] = "ESCHEATED"
                c["remaining_balance_cents"] = 0
                db.touch(c)

        budget.append_entry(
            program, "ESCHEAT_REVERSAL", claim["final_rebate_cents"] or 0,
            claim_id=claim["id"],
        )

    if created:
        budget.recompute(program, trigger="ESCHEAT_REVERSAL")
    return created
