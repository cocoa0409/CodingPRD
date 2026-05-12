"""Clock advance with deferred sweeps."""

from datetime import datetime, timedelta, timezone
import math

import db
from errors import raise_error, ERR_INVALID_REQUEST
from services import audit
from services.banking import banking_days_between
from services.settlement import _compute_proceeds, _recompute_lc_drawn_and_avail


def get_clock():
    return db.get_clock_record()


def advance(payload):
    if not isinstance(payload, dict):
        raise_error(ERR_INVALID_REQUEST, "JSON body required")
    seconds = payload.get("seconds")
    if not isinstance(seconds, int) or isinstance(seconds, bool):
        raise_error(ERR_INVALID_REQUEST, "seconds must be integer")
    if seconds < 0:
        raise_error(ERR_INVALID_REQUEST, "seconds must be non-negative")

    db.advance_clock(seconds)

    # Run sweeps in order: refusal-deadline, maturity, expiry, alerts
    _refusal_deadline_sweep()
    _maturity_sweep()
    _expiry_sweep()
    _alert_sweep()
    _auto_close_sweep()

    return db.get_clock_record()


def _refusal_deadline_sweep():
    """Auto-promote EXAMINED_DISCREPANT presentations whose 5-banking-day refusal window has elapsed."""
    now = db.now()
    for p in list(db.all_rows("presentations")):
        if p["status"] != "EXAMINED_DISCREPANT":
            continue
        if p.get("refusal_notified_at") is not None:
            continue
        presented = db.parse_dt(p.get("presented_at"))
        if presented is None:
            continue
        elapsed = banking_days_between(presented, now)
        if elapsed > 5:
            db.update("presentations", p["id"], {"status": "EXAMINED_CLEAN"})
            audit.append("presentation.auto_promote_clean", "PRESENTATION", p["id"],
                         lc_id=p["lc_id"], before_state="EXAMINED_DISCREPANT",
                         after_state="EXAMINED_CLEAN",
                         payload={"reason": "refusal_deadline_elapsed"},
                         actor_role="system", actor_id=None)


def _maturity_sweep():
    """USANCE settlements past maturity_date: ACCEPTED → PAID."""
    now = db.now()
    for s in list(db.all_rows("payment_settlements")):
        if s["status"] != "ACCEPTED":
            continue
        if s.get("settlement_type") != "USANCE_ACCEPTANCE":
            continue
        maturity = db.parse_dt(s.get("maturity_date"))
        if maturity is None:
            continue
        if now < maturity:
            continue
        # Compute proceeds at sweep instant
        lc = db.get_by_id("letters_of_credit", s["lc_id"])
        p = db.get_by_id("presentations", s["presentation_id"])
        proceeds = _compute_proceeds(s, lc, p)
        db.update("payment_settlements", s["id"], {
            **proceeds,
            "status": "PAID",
            "paid_at": db.now_iso(),
        })
        if p is not None:
            db.update("presentations", p["id"], {"status": "SETTLED"})
        _recompute_lc_drawn_and_avail(lc["id"])
        audit.append("settlement.maturity_payment", "SETTLEMENT", s["id"], lc_id=lc["id"],
                     before_state="ACCEPTED", after_state="PAID", payload={"sweep": True},
                     actor_role="system", actor_id=None)


def _expiry_sweep():
    """ACTIVE LCs past expiry_date → EXPIRED, with cascade on open presentations."""
    now = db.now()
    for lc in list(db.all_rows("letters_of_credit")):
        if lc["lifecycle_status"] not in ("ACTIVE", "ADVISED", "ISSUED"):
            continue
        expiry = db.parse_dt(lc.get("expiry_date"))
        if expiry is None:
            continue
        if now > expiry:
            db.update("letters_of_credit", lc["id"], {"lifecycle_status": "EXPIRED"})
            for p in db.find_many("presentations", lc_id=lc["id"]):
                if p["status"] in ("SUBMITTED", "UNDER_EXAMINATION"):
                    db.update("presentations", p["id"], {"status": "RETURNED"})
                    audit.append("presentation.force_return", "PRESENTATION", p["id"],
                                 lc_id=lc["id"], before_state=p["status"], after_state="RETURNED",
                                 payload={"sweep": "expiry"},
                                 actor_role="system", actor_id=None)
            audit.append("lc.expired", "LC", lc["id"], lc_id=lc["id"],
                         before_state="ACTIVE", after_state="EXPIRED",
                         payload={"sweep": True}, actor_role="system", actor_id=None)


def _ceil_days(seconds_total):
    return math.ceil(seconds_total / 86400.0)


def _alert_sweep():
    """Emit ExpiryAlert rows in deterministic order (lc_id ASC, alert_kind alphabetic)."""
    now = db.now()
    pending = []
    lcs = sorted(db.all_rows("letters_of_credit"), key=lambda r: r["id"])
    for lc in lcs:
        if lc["lifecycle_status"] in ("CANCELLED", "CLOSED"):
            continue

        existing_kinds = {a.get("alert_kind") for a in db.find_many("expiry_alerts", lc_id=lc["id"])}

        expiry = db.parse_dt(lc.get("expiry_date"))
        if expiry is None:
            continue
        diff_seconds = (expiry - now).total_seconds()
        days_to_expiry = _ceil_days(diff_seconds)

        # Only emit T_MINUS alerts when LC is still pre-expiry (lifecycle ACTIVE/ADVISED/ISSUED)
        if lc["lifecycle_status"] in ("ACTIVE", "ADVISED", "ISSUED"):
            if days_to_expiry == 15 and "T_MINUS_15" not in existing_kinds:
                pending.append(("T_MINUS_15", lc, expiry))
            if days_to_expiry == 5 and "T_MINUS_5" not in existing_kinds:
                pending.append(("T_MINUS_5", lc, expiry))
            if days_to_expiry <= 0 and "EXPIRED" not in existing_kinds:
                pending.append(("EXPIRED", lc, expiry))
        elif lc["lifecycle_status"] == "EXPIRED" and "EXPIRED" not in existing_kinds:
            # Already transitioned in expiry sweep; emit EXPIRED alert
            pending.append(("EXPIRED", lc, expiry))

        # Per-presentation period lapsed
        for p in db.find_many("presentations", lc_id=lc["id"]):
            if p["status"] not in ("EXAMINED_DISCREPANT", "REFUSED"):
                continue
            ship = db.parse_dt(p.get("shipment_date"))
            if ship is None:
                continue
            cutoff = ship + timedelta(days=int(lc.get("presentation_period_days") or 21))
            if cutoff < now:
                # has alert?
                already = False
                for a in db.find_many("expiry_alerts", lc_id=lc["id"], alert_kind="PRESENTATION_PERIOD_LAPSED"):
                    if a.get("details", {}).get("presentation_id") == p["id"]:
                        already = True
                        break
                if not already:
                    pending.append(("PRESENTATION_PERIOD_LAPSED", lc, expiry, p))

    # Sort: by lc_id ASC then alert_kind alphabetic
    def sort_key(item):
        kind, lc = item[0], item[1]
        return (lc["id"], kind)
    pending.sort(key=sort_key)

    for item in pending:
        kind = item[0]
        lc = item[1]
        details = {
            "expiry_date": lc.get("expiry_date"),
            "latest_shipment_date": lc.get("latest_shipment_date"),
            "lifecycle_status": lc.get("lifecycle_status"),
        }
        if kind == "PRESENTATION_PERIOD_LAPSED":
            p = item[3]
            details["presentation_id"] = p["id"]
        db.insert("expiry_alerts", {
            "lc_id": lc["id"],
            "alert_kind": kind,
            "triggered_at": db.now_iso(),
            "details": details,
        }, with_version=False)


def _auto_close_sweep():
    """ACTIVE → CLOSED when available=0 and no open pres. EXPIRED → CLOSED 30d post-expiry with all-terminal."""
    now = db.now()
    for lc in list(db.all_rows("letters_of_credit")):
        if lc["lifecycle_status"] == "ACTIVE":
            if lc.get("available_amount_minor_units", 0) == 0:
                has_open = False
                for p in db.find_many("presentations", lc_id=lc["id"]):
                    if p["status"] not in ("SETTLED", "RETURNED"):
                        has_open = True
                        break
                if not has_open:
                    db.update("letters_of_credit", lc["id"], {"lifecycle_status": "CLOSED"})
                    audit.append("lc.close", "LC", lc["id"], lc_id=lc["id"],
                                 before_state="ACTIVE", after_state="CLOSED",
                                 payload={"sweep": "auto_close"},
                                 actor_role="system", actor_id=None)
        elif lc["lifecycle_status"] == "EXPIRED":
            expiry = db.parse_dt(lc.get("expiry_date"))
            if expiry is None:
                continue
            if now < expiry + timedelta(days=30):
                continue
            all_terminal = True
            for p in db.find_many("presentations", lc_id=lc["id"]):
                if p["status"] not in ("SETTLED", "RETURNED"):
                    all_terminal = False
                    break
            if all_terminal:
                db.update("letters_of_credit", lc["id"], {"lifecycle_status": "CLOSED"})
                audit.append("lc.close", "LC", lc["id"], lc_id=lc["id"],
                             before_state="EXPIRED", after_state="CLOSED",
                             payload={"sweep": "auto_close_post_expiry"},
                             actor_role="system", actor_id=None)


def list_expiry_alerts(lc_id, limit, offset):
    lc = db.get_by_id("letters_of_credit", lc_id)
    if lc is None:
        from errors import raise_error, ERR_NOT_FOUND
        raise_error(ERR_NOT_FOUND, "lc not found")
    rows, total = db.list_table("expiry_alerts", filters={"lc_id": lc_id},
                                sort_keys=("created_at", "id"), limit=limit, offset=offset)
    return rows, total
