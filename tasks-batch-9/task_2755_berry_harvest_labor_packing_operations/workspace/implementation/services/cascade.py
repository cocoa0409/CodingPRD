"""Ordered, deterministic cascades (PRD §2.9, §3.1, §3.6).

Every row touched at any depth has its version incremented by exactly 1 per
request, so a Touched set dedupes repeated visits to the same row.
"""

import config
import db
import util
from services import calc


class Touched(object):
    def __init__(self):
        self._seen = {}
        self._order = []

    def add(self, record):
        if record is None:
            return record
        key = id(record)
        if key not in self._seen:
            self._seen[key] = record
            self._order.append(record)
        return record

    def flush(self):
        for record in self._order:
            db.touch(record)


# ---------------------------------------------------------------------------
# the four-level block quarantine cascade
# ---------------------------------------------------------------------------
def quarantine_block(block, user_id, reason_code):
    touched = Touched()
    block["manual_quarantine_active"] = True
    block["quarantined_by_user_id"] = user_id
    block["quarantine_reason_code"] = reason_code
    calc.recompute_posture(block)

    # Level 1 — live windows of the block, (start_at ASC, created_at ASC)
    candidates = sorted(
        [
            w
            for w in db.windows_of_block(block["id"])
            if w["status"] in ("CONFIRMED", "OPEN")
        ],
        key=lambda w: (w["_start_at"], w["created_at"], w["_seq"]),
    )
    for window in candidates:
        window["status"] = "SUSPENDED"
        window["suspended_reason_code"] = config.REASON_BLOCK_QUARANTINE
        touched.add(window)

        # Level 2 — that window's sessions in created_at ASC order
        for session in db.sessions_of_window(window["id"]):
            prior = session["status"]
            if prior in ("OPEN", "TALLIED"):
                session["status"] = "VOIDED"
                session["void_reason_code"] = config.REASON_WINDOW_SUSPENDED
                touched.add(session)
            elif prior == "APPROVED":
                session["status"] = "DISPUTED"
                session["dispute_reason_code"] = config.REASON_WINDOW_SUSPENDED
                session["approved_by_user_id"] = None
                touched.add(session)
                # Level 3 — exact ledger compensation plus derived recomputes
                crew = db.crew_of_session(session)
                if crew is not None:
                    calc.reverse_accrual(crew, session["net_cents"])
                    touched.add(crew)
                picker = db.pickers.get(session["picker_id"])
                if picker is not None:
                    calc.recompute_picker_productivity(picker)
                    touched.add(picker)
            if prior in ("OPEN", "TALLIED", "APPROVED"):
                calc.recompute_window_harvested(window)

    # independently of the window chain: hold every live lot of the block
    for lot in db.lots_of_block(block["id"]):
        if lot["disposition_status"] in ("UNCOMMITTED", "RESERVED"):
            if not lot["food_safety_hold"]:
                lot["food_safety_hold"] = True
                touched.add(lot)

    touched.flush()
    db.touch(block)
    return block


def clear_block(block):
    touched = Touched()
    block["manual_quarantine_active"] = False
    calc.recompute_posture(block)
    for lot in db.lots_of_block(block["id"]):
        if lot["disposition_status"] in ("UNCOMMITTED", "RESERVED"):
            if lot["food_safety_hold"]:
                lot["food_safety_hold"] = False
                touched.add(lot)
    touched.flush()
    db.touch(block)
    return block


# ---------------------------------------------------------------------------
# the two-level lot rejection cascade
# ---------------------------------------------------------------------------
def reject_lot(lot, reason_code):
    touched = Touched()
    prior_disposition = lot["disposition_status"]
    lot["food_safety_hold"] = True
    lot["disposition_status"] = "REJECTED"
    lot["reject_reason_code"] = reason_code
    lot["available_lbs"] = util.q2(0)

    if prior_disposition == "RESERVED":
        affected = []
        for line in db.allocations_of_lot(lot["id"]):
            if line["status"] != "RESERVED":
                continue
            line["status"] = "RELEASED"
            line["release_reason_code"] = config.REASON_LOT_REJECTED
            touched.add(line)
            commitment = db.buyer_commitments.get(line["buyer_commitment_id"])
            if commitment is not None and commitment not in affected:
                affected.append(commitment)
                touched.add(commitment)
        for commitment in affected:
            calc.recompute_commitment_exposure(commitment)

    calc.recompute_lot_balance(lot)

    window = db.harvest_windows.get(lot["harvest_window_id"])
    if window is not None:
        calc.recompute_window_packed(window)
        touched.add(window)

    touched.flush()
    db.touch(lot)
    return lot
