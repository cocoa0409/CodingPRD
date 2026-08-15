"""Logical clock + Lessee endpoints."""
from datetime import datetime, timezone

from flask import Blueprint, g

import domain
from envelope import ok
from errors import ApiError, invalid_state, not_found, validation
from http_util import CREDIT_TIERS, get_body, require_roles, v_enum, v_int, v_str
from store import db, new_entity, touch

bp_clock = Blueprint("clock", __name__)
bp_lessees = Blueprint("lessees", __name__)


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------
@bp_clock.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("SystemAdmin")
def set_clock():
    body = get_body()
    raw = v_str(body, "to_iso8601")
    text = raw.strip()
    parsed = None
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        raise validation("Field to_iso8601 must be a valid ISO 8601 timestamp")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    db.clock_dt = parsed.astimezone(timezone.utc)
    db.clock_raw = text
    return ok({"current_utc": db.clock_raw})


# ---------------------------------------------------------------------------
# Lessees (PRD 3.1)
# ---------------------------------------------------------------------------
def _load_lessee(lessee_id):
    lessee = db.lessees.get(lessee_id)
    if lessee is None:
        raise not_found("ERR_LESSEE_NOT_FOUND", f"Lessee {lessee_id} not found")
    return lessee


@bp_lessees.route("/lessees", methods=["POST"])
@require_roles("LeaseAdmin")
def create_lessee():
    body = get_body()
    company_name = v_str(body, "company_name")
    credit_tier = v_enum(body, "credit_tier", CREDIT_TIERS)
    credit_limit = v_int(body, "credit_limit_cents", min=0)
    deposit = v_int(body, "security_deposit_cents", min=0)
    lessee = new_entity(
        {
            "company_name": company_name,
            "credit_tier": credit_tier,
            "credit_limit_cents": credit_limit,
            "security_deposit_cents": deposit,
            "outstanding_balance_cents": 0,
            "status": "ACTIVE",
        }
    )
    db.lessees[lessee["id"]] = lessee
    return ok(domain.serialize_lessee(lessee), status=201)


@bp_lessees.route("/lessees/<lessee_id>", methods=["GET"])
@require_roles(
    "SystemAdmin", "LeaseAdmin", "FleetPlanner", "MaintenanceController",
    "BillingAnalyst", "ComplianceOfficer", "LesseeRep",
)
def get_lessee(lessee_id):
    lessee = _load_lessee(lessee_id)
    if g.user_role == "LesseeRep" and g.user_id != lessee["id"]:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE", 403,
            "LesseeRep may only read its own lessee record",
        )
    return ok(domain.serialize_lessee(lessee))


@bp_lessees.route("/lessees/<lessee_id>/reinstate", methods=["POST"])
@require_roles("LeaseAdmin")
def reinstate_lessee(lessee_id):
    lessee = _load_lessee(lessee_id)
    if lessee["status"] != "SUSPENDED":
        raise invalid_state(f"Lessee in status {lessee['status']} cannot be reinstated")
    if lessee["outstanding_balance_cents"] > lessee["credit_limit_cents"]:
        raise ApiError(
            "ERR_CREDIT_LIMIT_EXCEEDED", 422,
            "Outstanding balance still exceeds the credit limit",
        )
    lessee["status"] = "ACTIVE"
    touch(lessee)
    return ok(domain.serialize_lessee(lessee))


@bp_lessees.route("/lessees/<lessee_id>/terminate", methods=["POST"])
@require_roles("LeaseAdmin")
def terminate_lessee(lessee_id):
    lessee = _load_lessee(lessee_id)
    if lessee["status"] not in ("ACTIVE", "SUSPENDED"):
        raise invalid_state(f"Lessee in status {lessee['status']} cannot be terminated")
    open_leases = [
        l
        for l in db.leases.values()
        if l["lessee_id"] == lessee_id
        and l["status"] in ("DRAFT", "PENDING_APPROVAL", "ACTIVE")
    ]
    if open_leases:
        raise ApiError(
            "ERR_LESSEE_HAS_OPEN_LEASES", 409,
            "Lessee has leases in DRAFT, PENDING_APPROVAL, or ACTIVE",
        )
    lessee["status"] = "TERMINATED"
    touch(lessee)
    return ok(domain.serialize_lessee(lessee))
