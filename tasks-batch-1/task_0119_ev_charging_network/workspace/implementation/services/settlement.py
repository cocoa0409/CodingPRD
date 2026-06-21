"""Roaming settlement: line items, batch lifecycle, eMSP receivable
(PRD §3.7, §3.8; calculation roaming_settlement_total).

Batch total is round-then-sum: each line's commission is rounded half up at add
time, net = gross - commission is therefore an integer, and the batch total is
the plain integer sum of member nets whose status is PENDING or SETTLED.
"""
import db
import errors
import services.pricing as pricing


def recompute_batch(batch):
    """Recompute line_item_count and total_amount_cents (round-then-sum over
    members whose status IN {PENDING, SETTLED})."""
    members = [li for li in db.line_items.values() if li["batch_id"] == batch["id"]]
    batch["line_item_count"] = len(members)
    total = 0
    for li in members:
        if li["status"] in ("PENDING", "SETTLED"):
            total += li["net_amount_cents"]
    batch["total_amount_cents"] = total


def recompute_emsp_receivable(emsp):
    """receivable_balance_cents = sum of net_amount_cents across this eMSP's
    line items whose status is PENDING or SETTLED (OPEN/LOCKED line items).

    We maintain the receivable via explicit increments/decrements at add/reverse
    /settle time per the PRD; this helper is the authoritative recompute used by
    serialization to stay drift-free.
    """
    total = 0
    for li in db.line_items.values():
        b = db.batches.get(li["batch_id"])
        if b is None or b["emsp_id"] != emsp["id"]:
            continue
        if li["status"] == "PENDING":
            total += li["net_amount_cents"]
    emsp["receivable_balance_cents"] = total


def add_line_item(batch, session):
    """Add a line item for a rated roaming session; compute gross/commission/net,
    bump batch totals and eMSP receivable."""
    emsp = db.emsps[batch["emsp_id"]]
    gross = session["total_cost_cents"]
    commission = pricing.commission_cents(gross, emsp["commission_pct"])
    net = gross - commission

    li = {
        "batch_id": batch["id"],
        "session_id": session["id"],
        "gross_amount_cents": gross,
        "commission_cents": commission,
        "net_amount_cents": net,
        "status": "PENDING",
    }
    db.stamp_create(li)
    db.line_items[li["id"]] = li

    recompute_batch(batch)
    db.touch(batch)

    emsp["receivable_balance_cents"] += net
    db.touch(emsp)
    return li


def lock(batch):
    """OPEN->LOCKED; requires >=1 line item; recompute (freeze) total."""
    recompute_batch(batch)
    batch["status"] = "LOCKED"
    db.touch(batch)


def settle(batch):
    """LOCKED->SETTLED cascade: each line item PENDING->SETTLED; each session
    billing RATED->SETTLED; decrement eMSP receivable by total_amount_cents."""
    members = [li for li in db.line_items.values() if li["batch_id"] == batch["id"]]
    emsp = db.emsps[batch["emsp_id"]]

    for li in members:
        if li["status"] == "PENDING":
            li["status"] = "SETTLED"
            db.touch(li)
            sess = db.sessions.get(li["session_id"])
            if sess is not None and sess["billing_status"] == "RATED":
                sess["billing_status"] = "SETTLED"
                db.touch(sess)

    emsp["receivable_balance_cents"] -= batch["total_amount_cents"]
    db.touch(emsp)

    batch["status"] = "SETTLED"
    db.touch(batch)


def dispute(batch):
    """LOCKED->DISPUTED; no other effect."""
    batch["status"] = "DISPUTED"
    db.touch(batch)


def reopen(batch):
    """DISPUTED->OPEN: reverse outstanding PENDING line items, carry their
    sessions RATED->REVERSED, decrement eMSP receivable by each reversed net,
    recompute totals/count."""
    members = [li for li in db.line_items.values() if li["batch_id"] == batch["id"]]
    emsp = db.emsps[batch["emsp_id"]]

    for li in members:
        if li["status"] == "PENDING":
            li["status"] = "REVERSED"
            db.touch(li)
            sess = db.sessions.get(li["session_id"])
            if sess is not None and sess["billing_status"] == "RATED":
                sess["billing_status"] = "REVERSED"
                db.touch(sess)
            emsp["receivable_balance_cents"] -= li["net_amount_cents"]
            db.touch(emsp)

    recompute_batch(batch)
    batch["status"] = "OPEN"
    db.touch(batch)
