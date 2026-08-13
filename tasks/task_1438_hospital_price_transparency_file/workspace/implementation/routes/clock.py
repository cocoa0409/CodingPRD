"""POST /_clock/set_current_utc — test-driving logical clock (PRD 2.5)."""

from __future__ import annotations

from flask import Blueprint

import db
from middleware import require_roles
from response import success_object
from services.core import cascade_contract_deactivate, compute_penalty
from util import get_json_body, parse_iso8601, require_field

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_current_utc(_user_id: str, _role: str):
    body = get_json_body()
    raw = require_field(body, "to_iso8601")
    new_dt = parse_iso8601(raw, "to_iso8601")
    db.set_clock(new_dt)

    # Consequence 1: expire ACTIVE contracts whose inclusive effective_end date
    # now lies strictly before the new current date (closed-interval semantics).
    for c in list(db.payer_contracts.values()):
        if c["status"] == "ACTIVE" and db.parse_dt(c["effective_end"]).date() < new_dt.date():
            c["status"] = "EXPIRED"
            db.bump(c)
            cascade_contract_deactivate(c)

    # Consequence 2: escalate facilities whose plan deadline has strictly passed.
    for f in db.facilities.values():
        if (
            f["attestation_status"] == "REJECTED"
            and f.get("plan_due_date")
            and new_dt > db.parse_dt(f["plan_due_date"])
        ):
            f["attestation_status"] = "ESCALATED"
            db.bump(f)

    # Consequence 3: recompute accrual for facilities still in an accruing state.
    for f in db.facilities.values():
        if f["attestation_status"] in ("REJECTED", "ESCALATED"):
            f["penalty_accrued_cents"] = compute_penalty(f)

    return success_object({"current_utc": raw}, 200)
