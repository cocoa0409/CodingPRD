"""CUSO investment review and capital caps (PRD 3.2)."""
from flask import Blueprint, request

import db
import serialize as ser
from errors import not_found, invalid_state, raise_err, ERR_NOT_OWNER, ERR_INVESTMENT_CAP, ERR_ENHANCED_BASIS, ERR_INVALID_REQUEST
from middleware import (
    auth_context, require_role, body, req_int, opt_enum, touch, paginate, ALL_ROLES,
)
from response import success
from services import calc

bp = Blueprint("investments", __name__)


def _get_investment(iid):
    inv = db.investments.get(iid)
    if inv is None:
        not_found("CUSOInvestment")
    return inv


@bp.post("/network/cuso-investments")
def create_investment():
    uid, role = auth_context()
    require_role(role, {"TreasuryUser"})
    b = body()
    # ownership (priority 3): caller X-User-ID must equal credit_union_id
    cu_id = b.get("credit_union_id")
    if cu_id is not None and cu_id != uid:
        raise_err(ERR_NOT_OWNER, "credit_union_id must equal the caller's X-User-ID")
    # existence (priority 4)
    if cu_id is not None and cu_id not in db.credit_unions:
        not_found("CreditUnion")
    cuso_id = b.get("cuso_id")
    if cuso_id is not None and cuso_id not in db.cusos:
        not_found("CUSO")
    # shape (priority 5)
    if cu_id is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: credit_union_id")
    if cuso_id is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: cuso_id")
    amount = req_int(b, "amount_cents", minimum=1)
    basis = opt_enum(b, "approval_basis", {"STANDARD", "ENHANCED"}, "STANDARD")
    inv = db.insert("investment", {
        "credit_union_id": cu_id,
        "cuso_id": cuso_id,
        "amount_cents": amount,
        "approval_basis": basis,
        "status": "PENDING_REVIEW",
        "post_approval_aggregate_cents": None,
        "decided_at": None,
    })
    return success(ser.investment(inv), 201)


@bp.get("/network/cuso-investments/<iid>")
def get_investment(iid):
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    return success(ser.investment(_get_investment(iid)))


@bp.get("/network/cuso-investments")
def list_investments():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = list(db.investments.values())
    cu = request.args.get("credit_union_id")
    if cu is not None:
        items = [i for i in items if i["credit_union_id"] == cu]
    co = request.args.get("cuso_id")
    if co is not None:
        items = [i for i in items if i["cuso_id"] == co]
    st = request.args.get("status")
    if st is not None:
        items = [i for i in items if i["status"] == st]
    page, meta = paginate(items, ser.investment)
    return success(page, 200, meta)


@bp.post("/network/cuso-investments/<iid>/approve")
def approve_investment(iid):
    uid, role = auth_context()
    require_role(role, {"RegulatorUser"})
    inv = _get_investment(iid)
    if inv["status"] != "PENDING_REVIEW":
        invalid_state("Investment must be PENDING_REVIEW to approve")
    # investment_cap_check (priority 8)
    cu = db.credit_unions[inv["credit_union_id"]]
    cuso = db.cusos[inv["cuso_id"]]
    base_cap, extended_cap = calc.investment_caps(cu["total_assets_cents"])
    aggregate = sum(
        i["amount_cents"]
        for i in db.investments.values()
        if i["credit_union_id"] == cu["id"] and i["status"] == "APPROVED" and i["id"] != inv["id"]
    ) + inv["amount_cents"]
    if aggregate <= base_cap:
        pass  # permitted under either basis
    elif inv["approval_basis"] == "STANDARD":
        raise_err(ERR_INVESTMENT_CAP, "Aggregate approved investment exceeds the base cap")
    else:
        # ENHANCED basis above the base cap
        if aggregate > extended_cap:
            raise_err(ERR_INVESTMENT_CAP, "Aggregate approved investment exceeds the extended cap")
        eligible = (
            calc.net_worth_ratio(cu) >= calc.WELL_CAPITALIZED_MIN_RATIO
            and ser.cuso_open_critical(cuso["id"]) == 0
        )
        if not eligible:
            raise_err(
                ERR_ENHANCED_BASIS,
                "ENHANCED basis requires net_worth_ratio >= 0.07 and zero open CRITICAL findings",
            )
    inv["status"] = "APPROVED"
    inv["post_approval_aggregate_cents"] = aggregate
    inv["decided_at"] = db.clock_now()
    touch("investment", inv)
    touch("cuso", cuso)  # total_approved_investment_cents recomputed
    return success(ser.investment(inv))


@bp.post("/network/cuso-investments/<iid>/reject")
def reject_investment(iid):
    uid, role = auth_context()
    require_role(role, {"RegulatorUser"})
    inv = _get_investment(iid)
    if inv["status"] != "PENDING_REVIEW":
        invalid_state("Investment must be PENDING_REVIEW to reject")
    inv["status"] = "REJECTED"
    inv["decided_at"] = db.clock_now()
    touch("investment", inv)
    return success(ser.investment(inv))


@bp.post("/network/cuso-investments/<iid>/rescind")
def rescind_investment(iid):
    uid, role = auth_context()
    require_role(role, {"TreasuryUser"})
    inv = _get_investment(iid)
    if inv["credit_union_id"] != uid:
        raise_err(ERR_NOT_OWNER, "TreasuryUser must own the investing credit union")
    if inv["status"] != "APPROVED":
        invalid_state("Investment must be APPROVED to rescind")
    inv["status"] = "RESCINDED"
    touch("investment", inv)
    cuso = db.cusos.get(inv["cuso_id"])
    if cuso is not None:
        touch("cuso", cuso)  # total_approved_investment_cents recomputed
    return success(ser.investment(inv))
