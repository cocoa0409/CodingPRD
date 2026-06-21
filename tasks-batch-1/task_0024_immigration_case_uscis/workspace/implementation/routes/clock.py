"""Test-driving endpoints: clock + RFE deadline sweep."""
from __future__ import annotations

from datetime import datetime
from typing import List, Dict, Any

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import require_auth, get_json_body
from response import ok_object
from services.validation import require_fields
from services.events import append_event


bp = Blueprint("clock", __name__)


@bp.post("/uscis/_clock/set_current_utc")
def set_clock():
    require_auth(["FieldOfficeAdmin"])()
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    iso = body["to_iso8601"]
    try:
        # Validate parse-able.
        db.parse_iso_dt(iso)
    except (ValueError, TypeError, AttributeError):
        raise APIError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be ISO 8601")
    state = db.set_current_utc(iso)
    return ok_object(state, 200)


@bp.post("/uscis/_ops/sweep-rfe-deadlines")
def sweep_rfe_deadlines():
    require_auth(["FieldOfficeAdmin"])()

    now_iso = db.get_current_utc()
    now_date = now_iso[:10]  # whole-day comparison for deadline boundary

    expired_rfe_count = 0
    abandoned_cases: Dict[str, bool] = {}

    # Iterate over a stable snapshot in case mutations are made.
    rfe_list: List[Dict[str, Any]] = list(db.rfes.values())
    for rfe in rfe_list:
        if rfe.get("status") != "ISSUED":
            continue
        deadline = rfe.get("response_deadline")
        if not deadline:
            continue
        # Strict less-than at submission means: now >= deadline => expired.
        if now_date >= deadline:
            # Set RFE -> EXPIRED
            rfe["status"] = "EXPIRED"
            db.bump(rfe)
            expired_rfe_count += 1

            case = db.cases.get(rfe.get("case_id"))
            if case is None:
                continue
            prior_status = case.get("status")
            # Only cascade the parent case if it is still in RFE_PENDING.
            if prior_status == "RFE_PENDING":
                case["status"] = "ABANDONED"
                db.bump(case)
                append_event(
                    case["id"],
                    "RFE_EXPIRED",
                    payload_json={"rfe_id": rfe["id"]},
                )
                append_event(
                    case["id"],
                    "STATUS_CHANGE",
                    from_status=prior_status,
                    to_status="ABANDONED",
                )
                abandoned_cases[case["id"]] = True

    return ok_object(
        {
            "expired_rfe_count": expired_rfe_count,
            "abandoned_case_count": len(abandoned_cases),
        },
        200,
    )
