"""Damage claims: report, list, read, assess, charge, dispute, resolve."""
from flask import Blueprint, request

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles, forbid
from response import ok, created, paginate
from services import calc, domain
from validation import validate_body

bp = Blueprint("claims", __name__)


def _load_claim(cid):
    claim = store.claims.get(cid)
    if claim is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Damage claim not found")
    return claim


def _claim_owner_id(claim):
    contract = store.contracts[claim["contract_id"]]
    return contract["customer_id"]


@bp.post("/damage-claims")
def create_claim():
    uid, role = get_context()
    require_roles(["RentalCoordinator", "Customer"])
    body = validate_body({
        "line_id": ("string", True),
        "claim_type": ("enum", True, {"values": ["DAMAGE", "LOST", "STOLEN"]}),
        "description": ("string", True),
    })
    line = store.lines.get(body["line_id"])
    if line is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Rental line not found")
    contract = store.contracts[line["contract_id"]]
    if role == "Customer" and contract["customer_id"] != uid:
        forbid("A Customer may report claims only on its own contracts' lines")
    if line["status"] not in ("OUT_ON_RENT", "OFF_RENT", "RETURNED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Claims require a line that is OUT_ON_RENT, OFF_RENT, or RETURNED")
    claim = db.new_common({
        "id": db.new_id(),
        "line_id": line["id"],
        "contract_id": line["contract_id"],
        "unit_id": line["unit_id"],
        "claim_type": body["claim_type"],
        "description": body["description"],
        "status": "OPEN",
        "repair_estimate_cents": None,
        "chargeback_cents": None,
        "recovery_credit_cents": None,
        "reported_by": uid,
        "resolved_by": None,
    })
    store.claims[claim["id"]] = claim
    return created(domain.view_claim(claim))


@bp.get("/damage-claims")
def list_claims():
    uid, role = get_context()
    require_roles(["BranchManager", "RentalCoordinator", "Customer"])
    rows = list(store.claims.values())
    if role == "Customer":
        # Restricted to claims on the caller's own contracts.
        cid = request.args.get("contract_id")
        if cid is not None and cid in store.contracts \
                and store.contracts[cid]["customer_id"] != uid:
            forbid("A Customer sees only claims on its own contracts")
        lid = request.args.get("line_id")
        if lid is not None and lid in store.lines:
            owner = store.contracts[store.lines[lid]["contract_id"]]["customer_id"]
            if owner != uid:
                forbid("A Customer sees only claims on its own contracts")
        rows = [c for c in rows if _claim_owner_id(c) == uid]
    for f in ("line_id", "unit_id", "contract_id", "status"):
        rows = paginate.filter(rows, f)
    rows = [domain.view_claim(c) for c in rows]
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/damage-claims/<cid>")
def get_claim(cid):
    uid, role = get_context()
    require_roles(["BranchManager", "RentalCoordinator", "Customer"])
    claim = _load_claim(cid)
    if role == "Customer" and _claim_owner_id(claim) != uid:
        forbid("A Customer sees only claims on its own contracts")
    return ok(domain.view_claim(claim))


@bp.post("/damage-claims/<cid>/assess")
def assess_claim(cid):
    uid, role = get_context()
    require_roles(["BranchManager"])
    claim = _load_claim(cid)
    body = validate_body({
        "repair_estimate_cents": ("integer", False, {"min": 0}),
    })
    if claim["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not OPEN")
    if claim["claim_type"] == "DAMAGE":
        if body["repair_estimate_cents"] is None:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "repair_estimate_cents is required for DAMAGE claims")
        claim["repair_estimate_cents"] = body["repair_estimate_cents"]
    else:
        # LOST | STOLEN: the system sets the estimate to the replacement value.
        line = store.lines[claim["line_id"]]
        cls = store.classes[line["class_id"]]
        claim["repair_estimate_cents"] = cls["replacement_value_cents"]
    claim["status"] = "ASSESSED"
    db.touch(claim)
    return ok(domain.view_claim(claim))


@bp.post("/damage-claims/<cid>/charge")
def charge_claim(cid):
    uid, role = get_context()
    require_roles(["BranchManager"])
    claim = _load_claim(cid)
    if claim["status"] != "ASSESSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not ASSESSED")
    contract = store.contracts[claim["contract_id"]]
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract is not ACTIVE")
    line = store.lines[claim["line_id"]]
    cls = store.classes[line["class_id"]]
    claim["chargeback_cents"] = calc.damage_chargeback_cents(claim, contract, cls)
    claim["resolved_by"] = uid
    claim["status"] = "CHARGED"
    db.touch(claim)
    db.touch(contract)  # damage_subtotal_cents recompute
    if claim["claim_type"] in ("LOST", "STOLEN"):
        unit = store.units.get(claim["unit_id"])
        if unit is not None and unit["status"] == "ON_RENT":
            unit["status"] = "LOST"
            db.touch(unit)
    customer = store.customers.get(contract["customer_id"])
    if customer is not None:
        calc.maybe_suspend(customer)
    return ok(domain.view_claim(claim))


@bp.post("/damage-claims/<cid>/dispute")
def dispute_claim(cid):
    uid, role = get_context()
    require_roles(["Customer"])
    claim = _load_claim(cid)
    if _claim_owner_id(claim) != uid:
        forbid("A Customer may dispute only its own contracts' claims")
    if claim["status"] != "CHARGED":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not CHARGED")
    claim["status"] = "DISPUTED"
    db.touch(claim)
    return ok(domain.view_claim(claim))


@bp.post("/damage-claims/<cid>/resolve")
def resolve_claim(cid):
    uid, role = get_context()
    require_roles(["BranchManager"])
    claim = _load_claim(cid)
    body = validate_body({
        "decision": ("enum", True, {"values": ["UPHOLD", "WAIVE"]}),
    })
    if claim["status"] != "DISPUTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not DISPUTED")
    claim["resolved_by"] = uid
    if body["decision"] == "UPHOLD":
        # No monetary change: the chargeback was already applied at charge time.
        claim["status"] = "CHARGED"
        db.touch(claim)
    else:  # WAIVE — compensating action: back the chargeback out of the contract.
        claim["status"] = "WAIVED"
        db.touch(claim)
        contract = store.contracts[claim["contract_id"]]
        db.touch(contract)  # damage_subtotal_cents recompute
        customer = store.customers.get(contract["customer_id"])
        if customer is not None:
            calc.maybe_suspend(customer)
    return ok(domain.view_claim(claim))
