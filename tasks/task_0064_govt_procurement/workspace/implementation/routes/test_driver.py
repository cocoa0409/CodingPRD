"""Test-driving endpoints: clock advance and event emission."""

from flask import Blueprint

from clock import clock, parse_iso
from common import get_json_body, require_non_empty_string
from db import bump_version, db
from errors import ERR_VALIDATION, raise_error
from middleware import require_roles
from response import success
from services.query import expire_open_queries


bp = Blueprint("test_driver", __name__)


@bp.post("/_clock/advance")
@require_roles("ProcurementOfficer", "Regulator", "Supplier", "EvaluationExpert")
def advance_clock():
    body = get_json_body()
    target_iso = require_non_empty_string(body, "target_iso")
    try:
        parse_iso(target_iso)
    except Exception:
        raise_error(ERR_VALIDATION, "target_iso must be valid ISO timestamp")
    clock.advance_to(target_iso)
    # Side effects: expire OPEN queries past their window
    expire_open_queries()
    state = {
        "current_time": clock.now_iso(),
    }
    return success(state, 200)


@bp.post("/_events/emit")
@require_roles("Regulator")
def emit_event():
    body = get_json_body()
    system = body.get("system")
    payload = body.get("payload") or {}
    if not isinstance(system, str) or not system:
        raise_error(ERR_VALIDATION, "system must be non-empty string")
    if not isinstance(payload, dict):
        raise_error(ERR_VALIDATION, "payload must be object")
    # Supported updates: credit_score, blacklist_until on a Supplier
    sid = payload.get("supplier_id")
    if sid and sid in db.suppliers:
        s = db.suppliers[sid]
        if "credit_score" in payload:
            cs = payload["credit_score"]
            if isinstance(cs, bool) or not isinstance(cs, int) or not (0 <= cs <= 1000):
                raise_error(ERR_VALIDATION, "credit_score must be integer in [0,1000]")
            s["credit_score"] = cs
            bump_version(s)
        if "blacklist_until" in payload:
            bu = payload["blacklist_until"]
            if bu is not None:
                if not isinstance(bu, str) or not bu:
                    raise_error(ERR_VALIDATION, "blacklist_until must be ISO string or null")
                try:
                    parse_iso(bu)
                except Exception:
                    raise_error(ERR_VALIDATION, "blacklist_until must be valid ISO")
            s["blacklist_until"] = bu
            if bu:
                s["registration_status"] = "BLACKLISTED"
                # Disqualify SUBMITTED bids by this supplier
                for bid in db.bids.values():
                    if bid["supplier_id"] == sid and bid["bid_status"] == "SUBMITTED":
                        bid["bid_status"] = "DISQUALIFIED"
                        bump_version(bid)
            bump_version(s)
    return success({"emitted": True, "system": system}, 200)
