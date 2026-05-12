"""Labs endpoints."""
from flask import Blueprint, request, g

import db
from errors import err
from middleware import require_auth
from response import success
from services import audit


bp = Blueprint("labs", __name__)


def _get_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        raise err("ERR_BAD_REQUEST", "JSON body required")
    if not isinstance(body, dict):
        raise err("ERR_BAD_REQUEST", "JSON object required")
    return body


def _require_str(d, key):
    v = d.get(key)
    if not isinstance(v, str) or not v:
        raise err("ERR_BAD_REQUEST", f"{key} is required and must be a string")
    return v


def _require_int(d, key, lo=None, hi=None):
    v = d.get(key)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err("ERR_BAD_REQUEST", f"{key} is required and must be an integer")
    if lo is not None and v < lo:
        raise err("ERR_BAD_REQUEST", f"{key} must be >= {lo}")
    if hi is not None and v > hi:
        raise err("ERR_BAD_REQUEST", f"{key} must be <= {hi}")
    return v


@bp.post("/labs")
@require_auth(roles={"PlatformAdmin"})
def create_lab():
    body = _get_body()
    name = _require_str(body, "name")
    institution = _require_str(body, "institution")
    department = _require_str(body, "department")
    contact_user_id = _require_str(body, "contact_user_id")
    revenue_share_bps = _require_int(body, "revenue_share_bps", lo=0, hi=10000)

    lab = {
        "name": name,
        "institution": institution,
        "department": department,
        "contact_user_id": contact_user_id,
        "revenue_share_bps": revenue_share_bps,
        "settlement_balance_cents": 0,
        "lifetime_settled_cents": 0,
    }
    db.stamp_create(lab)
    db.labs[lab["id"]] = lab
    return success(db.public(lab), status=201)


@bp.get("/labs/<lab_id>")
@require_auth(roles={"PlatformAdmin", "LabOwner"})
def get_lab(lab_id):
    lab = db.labs.get(lab_id)
    if lab is None:
        raise err("ERR_NOT_FOUND", "lab not found")
    # LabOwner can only see their own lab
    if g.user_role == "LabOwner" and lab["contact_user_id"] != g.user_id:
        raise err("ERR_FORBIDDEN", "not the lab owner")
    return success(db.public(lab))


@bp.post("/labs/<lab_id>/settle")
@require_auth(roles={"PlatformAdmin"})
def settle_lab(lab_id):
    lab = db.labs.get(lab_id)
    if lab is None:
        raise err("ERR_NOT_FOUND", "lab not found")
    balance = int(lab["settlement_balance_cents"])
    if balance <= 0:
        raise err("ERR_NOTHING_TO_SETTLE", "settlement_balance_cents is not positive")
    lab["lifetime_settled_cents"] = int(lab["lifetime_settled_cents"]) + balance
    lab["settlement_balance_cents"] = 0
    db.stamp_update(lab)
    audit.record(
        subject_type="RESERVATION",  # No LAB subject_type defined; we use LAB
        subject_id=lab["id"],
        actor_role=g.user_role,
        actor_user_id=g.user_id,
        action="SETTLE",
        from_state=None,
        to_state=None,
        payload_json={"amount_cents": balance},
    )
    return success(db.public(lab))
