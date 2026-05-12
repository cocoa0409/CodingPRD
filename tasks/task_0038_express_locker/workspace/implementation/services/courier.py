"""Courier service: registration, blacklist transitions, rating computation."""

from datetime import timedelta

from clock import now, parse_iso
from constants import (
    BLACKLIST_THRESHOLD_RATE,
    BLACKLIST_COMPLAINT_THRESHOLD,
    W_SUCCESS,
    W_LOW_WRONG,
    W_LOW_COMPLAINT,
    COMPLAINT_NORM,
)
from db import DB, new_id
from errors import APIError, invalid_request, not_found
from services.audit import append_audit
from services.util import stamp_create, stamp_update


def get_courier(courier_id: str):
    c = DB.couriers.get(courier_id)
    if not c:
        raise not_found(f"Courier not found: {courier_id}")
    return c


def create_courier(payload: dict) -> dict:
    phone = payload.get("phone")
    company_id = payload.get("company_id")
    if not phone or not company_id:
        raise invalid_request("phone and company_id required")
    rid = new_id()
    base = stamp_create()
    record = {
        "id": rid,
        "phone": phone,
        "company_id": company_id,
        "blacklist_status": "ACTIVE",
        "blacklist_reason": None,
        **base,
    }
    DB.couriers[rid] = record
    return record


# ---------------- computed metrics -----------------------------------------


def lifetime_deposit_count(courier_id: str) -> int:
    n = 0
    for p in DB.parcels.values():
        if p.get("courier_id") == courier_id and p.get("status") != "DRAFT":
            n += 1
    return n


def lifetime_failed_attempts(courier_id: str) -> int:
    """Count of DEPOSIT_OPEN_FAILED CompartmentEvents tied to parcels owned by this courier."""
    parcels_owned = {p["id"] for p in DB.parcels.values() if p.get("courier_id") == courier_id}
    n = 0
    for ev in DB.compartment_events:
        if ev.get("event_type") == "DEPOSIT_OPEN_FAILED" and ev.get("parcel_id") in parcels_owned:
            n += 1
    return n


def lifetime_wrong_deposit_count(courier_id: str) -> int:
    """Count of parcels by this courier whose successor parcel has correction_origin=WRONG_DEPOSIT."""
    parcels_owned = {p["id"] for p in DB.parcels.values() if p.get("courier_id") == courier_id}
    n = 0
    for p in DB.parcels.values():
        if (
            p.get("correction_origin") == "WRONG_DEPOSIT"
            and p.get("replaces_parcel_id") in parcels_owned
        ):
            n += 1
    return n


def _round_4(x: float) -> float:
    # Half-up to 4 decimals
    from decimal import Decimal, ROUND_HALF_UP
    q = Decimal(str(x)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


def lifetime_success_rate(courier_id: str) -> float:
    deposits = lifetime_deposit_count(courier_id)
    fails = lifetime_failed_attempts(courier_id)
    denom = max(deposits + fails, 1)
    return _round_4((deposits - fails) / denom)


def window_30d_metrics(courier_id: str):
    """Return (window_deposits, window_wrong_deposits, window_wrong_deposit_rate)."""
    cutoff = now() - timedelta(days=30)
    parcels_in_window = []
    for p in DB.parcels.values():
        if p.get("courier_id") != courier_id:
            continue
        if p.get("status") == "DRAFT":
            continue
        dep = p.get("deposited_at")
        if not dep:
            continue
        try:
            dep_dt = parse_iso(dep)
        except Exception:
            continue
        if dep_dt >= cutoff:
            parcels_in_window.append(p)

    parcel_ids = {p["id"] for p in parcels_in_window}
    wrong = 0
    for q in DB.parcels.values():
        if (
            q.get("correction_origin") == "WRONG_DEPOSIT"
            and q.get("replaces_parcel_id") in parcel_ids
        ):
            wrong += 1
    deposits = len(parcels_in_window)
    rate = _round_4(wrong / max(deposits, 1))
    return deposits, wrong, rate


def window_wrong_deposit_rate(courier_id: str) -> float:
    return window_30d_metrics(courier_id)[2]


def complaint_count(courier_id: str) -> int:
    """Resolved disputes with COURIER_AT_FAULT outcome whose target parcel's courier_id == this courier
    (in last 30 days)."""
    cutoff = now() - timedelta(days=30)
    n = 0
    for d in DB.disputes.values():
        if d.get("status") != "RESOLVED_COURIER_AT_FAULT":
            continue
        parcel = DB.parcels.get(d.get("parcel_id"))
        if not parcel or parcel.get("courier_id") != courier_id:
            continue
        u = d.get("updated_at")
        try:
            udt = parse_iso(u)
        except Exception:
            continue
        if udt >= cutoff:
            n += 1
    return n


def courier_quality_score(courier_id: str) -> float:
    success = lifetime_success_rate(courier_id)
    wrong_rate = window_wrong_deposit_rate(courier_id)
    complaints = complaint_count(courier_id)
    score = (
        W_SUCCESS * success
        + W_LOW_WRONG * (1 - wrong_rate)
        + W_LOW_COMPLAINT * (1 - min(complaints / COMPLAINT_NORM, 1))
    )
    return _round_4(score)


def serialize_courier(c: dict) -> dict:
    cid = c["id"]
    deposits = lifetime_deposit_count(cid)
    fails = lifetime_failed_attempts(cid)
    return {
        "id": cid,
        "phone": c.get("phone"),
        "company_id": c.get("company_id"),
        "lifetime_deposit_count": deposits,
        "lifetime_wrong_deposit_count": lifetime_wrong_deposit_count(cid),
        "lifetime_deposit_success_rate": lifetime_success_rate(cid),
        "window_wrong_deposit_rate": window_wrong_deposit_rate(cid),
        "complaint_count": complaint_count(cid),
        "blacklist_status": c.get("blacklist_status"),
        "blacklist_reason": c.get("blacklist_reason"),
        "created_at": c.get("created_at"),
        "updated_at": c.get("updated_at"),
        "version": c.get("version", 0),
    }


def serialize_rating(courier_id: str) -> dict:
    deposits, wrong, w_rate = window_30d_metrics(courier_id)
    return {
        "courier_id": courier_id,
        "lifetime": {
            "lifetime_deposit_count": lifetime_deposit_count(courier_id),
            "lifetime_failed_attempts": lifetime_failed_attempts(courier_id),
            "lifetime_success_rate": lifetime_success_rate(courier_id),
            "complaint_count": complaint_count(courier_id),
            "score": courier_quality_score(courier_id),
        },
        "window_30d": {
            "window_deposits": deposits,
            "window_wrong_deposits": wrong,
            "window_wrong_deposit_rate": w_rate,
        },
    }


# ---------------- blacklist transitions ------------------------------------


def maybe_auto_restrict(courier_id: str, actor_role: str, actor_id: str):
    """If rolling rate >= 0.10 and currently ACTIVE, auto-flip to RESTRICTED."""
    c = get_courier(courier_id)
    if c.get("blacklist_status") != "ACTIVE":
        return
    rate = window_wrong_deposit_rate(courier_id)
    if rate >= BLACKLIST_THRESHOLD_RATE:
        c["blacklist_status"] = "RESTRICTED"
        c["blacklist_reason"] = (
            f"Auto-restricted: window_wrong_deposit_rate={rate:.4f} >= {BLACKLIST_THRESHOLD_RATE}"
        )
        stamp_update(c)
        append_audit(actor_role, actor_id, "BLACKLIST_CHANGE", "Courier", courier_id,
                     {"from": "ACTIVE", "to": "RESTRICTED",
                      "reason": c["blacklist_reason"],
                      "window_wrong_deposit_rate": rate})


def maybe_auto_blacklist(courier_id: str, actor_role: str, actor_id: str):
    """If complaint_count >= 5 and currently RESTRICTED, auto-flip to BLACKLISTED."""
    c = get_courier(courier_id)
    if c.get("blacklist_status") != "RESTRICTED":
        return
    cnt = complaint_count(courier_id)
    if cnt >= BLACKLIST_COMPLAINT_THRESHOLD:
        c["blacklist_status"] = "BLACKLISTED"
        c["blacklist_reason"] = (
            f"Auto-blacklisted: complaint_count={cnt} >= {BLACKLIST_COMPLAINT_THRESHOLD}"
        )
        stamp_update(c)
        append_audit(actor_role, actor_id, "BLACKLIST_CHANGE", "Courier", courier_id,
                     {"from": "RESTRICTED", "to": "BLACKLISTED",
                      "reason": c["blacklist_reason"],
                      "complaint_count": cnt})


def restrict(courier_id: str, payload: dict, actor_role: str, actor_id: str) -> dict:
    c = get_courier(courier_id)
    reason = payload.get("reason") or "manual restrict"
    prev = c.get("blacklist_status")
    c["blacklist_status"] = "RESTRICTED"
    c["blacklist_reason"] = reason
    stamp_update(c)
    append_audit(actor_role, actor_id, "BLACKLIST_CHANGE", "Courier", courier_id,
                 {"from": prev, "to": "RESTRICTED", "reason": reason})
    return c


def blacklist(courier_id: str, payload: dict, actor_role: str, actor_id: str) -> dict:
    c = get_courier(courier_id)
    reason = payload.get("reason") or "manual blacklist"
    prev = c.get("blacklist_status")
    c["blacklist_status"] = "BLACKLISTED"
    c["blacklist_reason"] = reason
    stamp_update(c)
    append_audit(actor_role, actor_id, "BLACKLIST_CHANGE", "Courier", courier_id,
                 {"from": prev, "to": "BLACKLISTED", "reason": reason})
    return c


def reinstate(courier_id: str, actor_role: str, actor_id: str) -> dict:
    c = get_courier(courier_id)
    rate = window_wrong_deposit_rate(courier_id)
    cnt = complaint_count(courier_id)
    if rate >= BLACKLIST_THRESHOLD_RATE or cnt >= BLACKLIST_COMPLAINT_THRESHOLD:
        from errors import APIError
        raise APIError(
            "ERR_INVALID_REQUEST",
            f"Reinstatement requires window_wrong_deposit_rate < {BLACKLIST_THRESHOLD_RATE} "
            f"AND complaint_count < {BLACKLIST_COMPLAINT_THRESHOLD} "
            f"(currently rate={rate}, complaints={cnt})",
            400,
        )
    prev = c.get("blacklist_status")
    c["blacklist_status"] = "ACTIVE"
    c["blacklist_reason"] = None
    stamp_update(c)
    append_audit(actor_role, actor_id, "BLACKLIST_CHANGE", "Courier", courier_id,
                 {"from": prev, "to": "ACTIVE"})
    return c
