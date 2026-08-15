"""GovernancePolicy + Physician routes."""
from flask import Blueprint

import db
from middleware import get_auth, require_roles
from response import success_object, success_list
from errors import (
    raise_err, ERR_POLICY_ALREADY_EXISTS, ERR_NOT_FOUND, ERR_STALE_VERSION,
    ERR_INVALID_STATE, ERR_INSUFFICIENT_TREASURY_SHARES, ERR_INVALID_REQUEST,
)
from services.core import (
    get_body, check_unknown_fields, req_str, opt_str, opt_bool, opt_int,
    req_int, req_datetime, opt_number, req_number,
    new_entity, touch, get_or_404, pagination_params, paginate,
    serialize_policy, serialize_physician, recalc_ownership,
    POLICY_DEFAULTS, POLICY_INT_FIELDS, POLICY_NUM_FIELDS, POLICY_ALL_FIELDS,
    tenure_years,
)

bp = Blueprint("policy_physicians", __name__)

ALL_ROLES = ("BoardAdmin", "Physician", "ComplianceOfficer")


# ---------------- GovernancePolicy ----------------

@bp.post("/governance/policy")
def create_policy():
    role, _ = get_auth()
    body = get_body()
    check_unknown_fields(body, list(POLICY_ALL_FIELDS))
    require_roles(role, ("BoardAdmin",))
    if db.policy is not None:
        raise_err(ERR_POLICY_ALREADY_EXISTS, "GovernancePolicy singleton already exists")

    if "total_shares_authorized" not in body:
        raise_err(ERR_INVALID_REQUEST, "total_shares_authorized is required")
    fields = {}
    for f in POLICY_INT_FIELDS:
        if f in body:
            fields[f] = req_int(body, f)
    for f in POLICY_NUM_FIELDS:
        if f in body:
            fields[f] = req_number(body, f)
    merged = dict(POLICY_DEFAULTS)
    merged.update(fields)
    merged["singleton_key"] = "GLOBAL"
    merged["comp_policy_version"] = 0
    merged["treasury_shares"] = merged["total_shares_authorized"]

    from db import new_id as _new_id, now_iso as _now_iso
    ts = _now_iso()
    pol = {
        "id": _new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    pol.update(merged)
    db.policy = pol
    recalc_ownership()
    return success_object(serialize_policy(db.policy), 201)


@bp.get("/governance/policy")
def read_policy():
    role, _ = get_auth()
    require_roles(role, ALL_ROLES)
    if db.policy is None:
        raise_err(ERR_NOT_FOUND, "GovernancePolicy not found")
    return success_object(serialize_policy(db.policy))


@bp.patch("/governance/policy")
def update_policy():
    role, _ = get_auth()
    body = get_body()
    check_unknown_fields(body, list(POLICY_ALL_FIELDS) + ["expected_policy_version"])
    require_roles(role, ("BoardAdmin",))
    if db.policy is None:
        raise_err(ERR_NOT_FOUND, "GovernancePolicy not found")
    if "expected_policy_version" not in body:
        raise_err(ERR_INVALID_REQUEST, "expected_policy_version is required")
    expected = body["expected_policy_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "expected_policy_version must be an integer")
    if expected != db.policy["version"]:
        raise_err(ERR_STALE_VERSION, "Policy version mismatch")

    for f in POLICY_INT_FIELDS:
        if f in body:
            db.policy[f] = req_int(body, f)
    for f in POLICY_NUM_FIELDS:
        if f in body:
            db.policy[f] = req_number(body, f)
    touch(db.policy)
    recalc_ownership()
    return success_object(serialize_policy(db.policy))


# ---------------- Physician ----------------

@bp.post("/governance/physicians")
def create_physician():
    role, _ = get_auth()
    body = get_body()
    check_unknown_fields(body, ["full_name", "hire_date", "specialty",
                                "founding_shareholder", "initial_shares"])
    # PRD §2.7 priority: request shape (second) is validated before role
    # permission (third) — a malformed body yields ERR_INVALID_REQUEST even
    # from a caller who would also fail the role check.
    full_name = req_str(body, "full_name")
    hire_dt = req_datetime(body, "hire_date")
    specialty = opt_str(body, "specialty")
    founding = opt_bool(body, "founding_shareholder", False)
    initial_shares = opt_int(body, "initial_shares", 0)
    if initial_shares is None:
        initial_shares = 0

    if founding and initial_shares < 1:
        raise_err(ERR_INVALID_REQUEST,
                  "initial_shares must be >= 1 when founding_shareholder is true")

    require_roles(role, ("BoardAdmin",))

    if founding:
        if db.policy is None:
            raise_err(ERR_INSUFFICIENT_TREASURY_SHARES, "No policy")
        treasury = db.policy["total_shares_authorized"] - sum(
            p["shares_held"] for p in db.physicians.values())
        if initial_shares > treasury:
            raise_err(ERR_INSUFFICIENT_TREASURY_SHARES,
                      "Share issuance exceeds treasury_shares")

    from db import _format_iso
    p = new_entity(db.physicians, {
        "full_name": full_name,
        "hire_date": _format_iso(hire_dt),
        "specialty": specialty,
        "founding_shareholder": founding,
        "initial_shares": initial_shares if founding else 0,
        "partnership_status": "SHAREHOLDER" if founding else "ASSOCIATE",
        "standing": "GOOD_STANDING",
        "shares_held": initial_shares if founding else 0,
        "capital_account_balance_cents": 0,
        "ownership_pct": 0.0,
    })
    recalc_ownership()
    return success_object(serialize_physician(p), 201)


@bp.get("/governance/physicians")
def list_physicians():
    role, _ = get_auth()
    require_roles(role, ALL_ROLES)
    from flask import request
    items = list(db.physicians.values())
    ps = request.args.get("partnership_status")
    st = request.args.get("standing")
    if ps is not None:
        items = [p for p in items if p["partnership_status"] == ps]
    if st is not None:
        items = [p for p in items if p["standing"] == st]
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_physician(p) for p in page], limit, offset, total)


@bp.get("/governance/physicians/<pid>")
def get_physician(pid):
    role, _ = get_auth()
    require_roles(role, ALL_ROLES)
    p = get_or_404(db.physicians, pid, "Physician")
    return success_object(serialize_physician(p))


@bp.post("/governance/physicians/<pid>/standing")
def set_standing(pid):
    role, _ = get_auth()
    body = get_body()
    check_unknown_fields(body, ["standing", "note"])
    require_roles(role, ("BoardAdmin",))
    p = get_or_404(db.physicians, pid, "Physician")
    target = body.get("standing")
    if target not in ("GOOD_STANDING", "PROBATION", "SUSPENDED"):
        raise_err(ERR_INVALID_REQUEST, "Invalid standing")
    if p["partnership_status"] == "EXITED":
        raise_err(ERR_INVALID_STATE, "EXITED physician is immutable")
    p["standing"] = target
    touch(p)
    return success_object(serialize_physician(p))
