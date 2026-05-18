"""Test-driving endpoints: logical clock + sweeps (PRD §3.6, §3.7, §2.10)."""
from __future__ import annotations

from flask import Blueprint

from config import ROLE_ATTORNEY, ROLE_MANAGING_PARTNER, ROLE_PARALEGAL
from db import store
from errors import raise_error
from middleware import require_auth
from response import success
from routes._helpers import get_json_body
from services.calculations import is_sol_expired
from services.case_engine import now, touch
from utils import iso_now


bp = Blueprint("admin", __name__)


@bp.post("/_clock/advance")
@require_auth([ROLE_MANAGING_PARTNER])
def clock_advance():
    body = get_json_body()
    if "seconds" not in body:
        raise_error("ERR_VALIDATION", "seconds is required.")
    seconds = body["seconds"]
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise_error("ERR_VALIDATION", "seconds must be numeric.")
    if seconds < 0:
        raise_error("ERR_VALIDATION", "seconds must be non-negative.")

    with store.lock:
        store.clock.advance_seconds(seconds)

    return success({"now": iso_now(store.clock.logical_now())}, 200)


@bp.get("/_clock/now")
@require_auth([ROLE_PARALEGAL, ROLE_ATTORNEY, ROLE_MANAGING_PARTNER])
def clock_now():
    return success({"now": iso_now(store.clock.logical_now())}, 200)


@bp.post("/_sweep/settlement_offers")
@require_auth([ROLE_MANAGING_PARTNER])
def sweep_offers():
    expired_ids = []
    current = now()
    with store.lock:
        for offer in store.settlement_offers.values():
            if offer["status"] == "PENDING" and offer["expires_at"] <= current:
                offer["status"] = "EXPIRED"
                touch(offer)
                expired_ids.append(offer["id"])
    return success({"expired_count": len(expired_ids), "expired_ids": expired_ids}, 200)


@bp.post("/_sweep/sol")
@require_auth([ROLE_MANAGING_PARTNER])
def sweep_sol():
    dismissed_ids = []
    current = now()
    with store.lock:
        for case in store.cases.values():
            if case["status"] in ("SETTLED", "TRIAL_AWARDED", "DISMISSED", "CLOSED"):
                continue
            if is_sol_expired(case, current):
                # Cancel open medical-record requests too (matches dismiss cascade).
                for r in store.medical_requests.values():
                    if r["case_id"] == case["id"] and r["status"] in ("DRAFT", "SENT"):
                        r["status"] = "CANCELED"
                        touch(r)
                case["status"] = "DISMISSED"
                touch(case)
                dismissed_ids.append(case["id"])
    return success({"dismissed_count": len(dismissed_ids), "dismissed_ids": dismissed_ids}, 200)
