"""IncentiveAccrual (read) + PayoutRequest endpoints (PRD §3.5, §3.7, §2.10)."""
from flask import Blueprint, request

import db
import errors
import lookup
import response
import validation
from middleware import get_identity, require_roles, require_owner
from services import calc, core

bp = Blueprint("payouts", __name__)


# ----- Incentive accruals (read-only) -----
@bp.get("/incentive-accruals")
def list_accruals():
    user_id, role = get_identity()
    require_roles(role, {"PanelOps", "ResearchManager"})
    panelist_id = request.args.get("panelist_id")
    participation_id = request.args.get("participation_id")
    records = []
    for a in db.incentive_accruals.values():
        if panelist_id is not None and a["panelist_id"] != panelist_id:
            continue
        if participation_id is not None and a["participation_id"] != participation_id:
            continue
        records.append(a)
    window, limit, offset, total = validation.paginate(records)
    return response.array_response(
        [core.serialize_accrual(a) for a in window], limit, offset, total)


@bp.get("/incentive-accruals/<aid>")
def get_accrual(aid):
    user_id, role = get_identity()
    require_roles(role, {"PanelOps", "ResearchManager"})
    a = lookup.accrual(aid)
    return response.object_response(core.serialize_accrual(a))


# ----- Payout requests -----
@bp.post("/payout-requests")
def create_payout_request():
    user_id, role = get_identity()
    require_roles(role, {"Panelist", "PanelOps"})
    body = validation.get_json_body()
    panelist_id = validation.require_str(body, "panelist_id")
    payout_method = validation.require_enum(body, "payout_method", {"CASH", "GIFT_CARD"})
    points_requested = validation.require_int(body, "points_requested", minimum=1)
    expected_version = validation.require_int(body, "expected_panelist_version")

    panelist = lookup.panelist(panelist_id)
    # Ownership (priority 4) before business rules.
    require_owner(user_id, role, panelist["id"])

    # Minimum payout (priority 13, 422).
    if points_requested < calc.MIN_PAYOUT_POINTS:
        errors.fail(errors.ERR_PAYOUT_BELOW_MINIMUM,
                    "points_requested below minimum payout")
    # OCC (priority 16, 412): expected_panelist_version must match current version.
    if expected_version != panelist["version"]:
        errors.fail(errors.ERR_STALE_PANELIST_VERSION, "Stale panelist version")

    rec = db.base_record(common_fields=True)
    rec.update({
        "panelist_id": panelist_id,
        "payout_method": payout_method,
        "points_requested": points_requested,
        "cash_cents": points_requested * calc.CENTS_PER_POINT,
        "expected_panelist_version": expected_version,
        "status": "REQUESTED",
    })
    db.payout_requests[rec["id"]] = rec
    return response.object_response(core.serialize_payout_request(rec), status=201)


@bp.get("/payout-requests")
def list_payout_requests():
    user_id, role = get_identity()
    require_roles(role, {"PanelOps", "ResearchManager", "Panelist"})
    panelist_id = request.args.get("panelist_id")
    status = request.args.get("status")
    records = []
    for pr in db.payout_requests.values():
        if panelist_id is not None and pr["panelist_id"] != panelist_id:
            continue
        if status is not None and pr["status"] != status:
            continue
        records.append(pr)
    window, limit, offset, total = validation.paginate(records)
    return response.array_response(
        [core.serialize_payout_request(pr) for pr in window], limit, offset, total)


@bp.get("/payout-requests/<rid>")
def get_payout_request(rid):
    user_id, role = get_identity()
    require_roles(role, {"PanelOps", "Panelist"})
    pr = lookup.payout_request(rid)
    return response.object_response(core.serialize_payout_request(pr))


@bp.post("/payout-requests/<rid>/approve")
def approve_payout(rid):
    user_id, role = get_identity()
    require_roles(role, {"PanelOps"})
    pr = lookup.payout_request(rid)
    if pr["status"] != "REQUESTED":
        errors.fail(errors.ERR_INVALID_STATE, "PayoutRequest is not REQUESTED")
    panelist = lookup.panelist(pr["panelist_id"])
    # Sufficient balance at approval (priority 14, 422).
    if core.points_balance(panelist) < pr["points_requested"]:
        errors.fail(errors.ERR_INSUFFICIENT_POINTS, "Insufficient points")
    pr["status"] = "APPROVED"
    db.touch(pr)
    # Approval consumes points (balance derived) and bumps the panelist version.
    db.touch(panelist)
    return response.object_response(core.serialize_payout_request(pr))


@bp.post("/payout-requests/<rid>/pay")
def pay_payout(rid):
    user_id, role = get_identity()
    require_roles(role, {"PanelOps"})
    pr = lookup.payout_request(rid)
    if pr["status"] != "APPROVED":
        errors.fail(errors.ERR_INVALID_STATE, "PayoutRequest is not APPROVED")
    pr["status"] = "PAID"
    db.touch(pr)
    return response.object_response(core.serialize_payout_request(pr))


@bp.post("/payout-requests/<rid>/reject")
def reject_payout(rid):
    user_id, role = get_identity()
    require_roles(role, {"PanelOps"})
    pr = lookup.payout_request(rid)
    if pr["status"] != "REQUESTED":
        errors.fail(errors.ERR_INVALID_STATE, "PayoutRequest is not REQUESTED")
    pr["status"] = "REJECTED"
    db.touch(pr)
    return response.object_response(core.serialize_payout_request(pr))


@bp.post("/payout-requests/<rid>/cancel")
def cancel_payout(rid):
    user_id, role = get_identity()
    require_roles(role, {"Panelist"})
    pr = lookup.payout_request(rid)
    require_owner(user_id, role, pr["panelist_id"])
    if pr["status"] != "REQUESTED":
        errors.fail(errors.ERR_INVALID_STATE, "PayoutRequest is not REQUESTED")
    pr["status"] = "CANCELLED"
    db.touch(pr)
    return response.object_response(core.serialize_payout_request(pr))
