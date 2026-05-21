"""Clock advance + expiration / abatement / reviews sweeps."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from app import clock, store
from app.errors import validation
from app.services.common import touch
from app.util import parse_iso


def advance_clock(payload: dict) -> dict:
    payload = payload or {}
    try:
        target = parse_iso(payload.get("to_timestamp"))
        if target is None:
            raise ValueError("to_timestamp is required")
        new_now = clock.advance_to(target)
    except ValueError as exc:
        raise validation(str(exc))
    return {"now": new_now}


def sweep_expirations() -> List[str]:
    expired: List[str] = []
    now = clock.now()
    for voucher in store.vouchers.values():
        if voucher["status"] not in ("SEARCHING", "SEARCHING_REISSUED"):
            continue
        if now <= voucher["search_deadline"]:
            continue
        has_pending_or_active = any(
            tn.get("voucher_id") == voucher["id"]
            and tn.get("status") in ("ACTIVE", "ABATED", "PENDING_INSPECTION", "PENDING_RENT_REASONABLE")
            for tn in store.tenancies.values()
        )
        if has_pending_or_active:
            continue
        voucher["status"] = "EXPIRED"
        touch(voucher)
        expired.append(voucher["id"])
    return expired


def sweep_abatements() -> List[str]:
    terminated: List[str] = []
    now = clock.now()
    for tenancy in list(store.tenancies.values()):
        if tenancy["status"] != "ABATED":
            continue
        # Find the originating failed inspection.
        source = _find_abatement_source(tenancy["id"])
        if source is None:
            continue
        if source.get("cure_deadline") is None or now <= source["cure_deadline"]:
            continue
        # No CURED reinspection since.
        if _has_cure_since(tenancy["id"], source["completed_at"]):
            continue
        # Cascade: tenancy → TERMINATED(HQS_UNCURED), voucher → TERMINATED.
        tenancy["status"] = "TERMINATED"
        tenancy["termination_reason"] = "HQS_UNCURED"
        tenancy["terminated_at"] = now
        touch(tenancy)
        source["status"] = "EXPIRED_UNCURED"
        touch(source)
        voucher = store.vouchers.get(tenancy["voucher_id"])
        if voucher is not None and voucher["status"] in ("LEASED",):
            voucher["status"] = "TERMINATED"
            touch(voucher)
        terminated.append(tenancy["id"])
    return terminated


def sweep_reviews() -> List[str]:
    """Close DEFICIENT reviews past 14-day cure window as DENIED."""
    denied: List[str] = []
    now = clock.now()
    from app.services.annual_reviews import _cascade_denial

    for ar in list(store.annual_reviews.values()):
        if ar["status"] != "DEFICIENT":
            continue
        deficient_since = ar.get("deficient_since")
        if deficient_since is None:
            continue
        if now <= deficient_since + timedelta(days=14):
            continue
        ar["status"] = "DENIED"
        touch(ar)
        _cascade_denial(ar)
        denied.append(ar["id"])
    return denied


def _find_abatement_source(tenancy_id: str):
    best = None
    for insp in store.inspections.values():
        if insp.get("tenancy_id") != tenancy_id:
            continue
        if not insp.get("abatement_source"):
            continue
        if insp.get("status") in ("COMPLETED_FAIL_CURABLE", "COMPLETED_FAIL_LIFETHREAT"):
            if best is None or insp["completed_at"] > best["completed_at"]:
                best = insp
    return best


def _has_cure_since(tenancy_id: str, since: datetime) -> bool:
    for insp in store.inspections.values():
        if insp.get("tenancy_id") != tenancy_id:
            continue
        if insp.get("inspection_type") != "REINSPECTION":
            continue
        if insp.get("outcome") != "CURED":
            continue
        if insp.get("completed_at") and insp["completed_at"] >= since:
            return True
    return False
