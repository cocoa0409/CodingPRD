"""Blockage event endpoints: report, read, assess, pay, close."""
import uuid

from flask import Blueprint

from db import STORE, now, next_seq
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_NO_CONTRIBUTORS,
    ERR_WEIGHTS_INVALID,
    ERR_SOD_VIOLATION,
    ERR_COST_SHARE_UNPAID,
)
from middleware import auth, require_roles, forbid_unless, get_or_404
from response import success
from services.calculations import apportion_shares
from services.serializers import ser_blockage
from validation import body_json, v_str, v_int

bp = Blueprint("blockages", __name__)

READERS = ["ProgramAdmin", "Inspector", "ComplianceOfficer", "FseContact"]


@bp.post("/blockage-events")
def create_blockage():
    uid, role = auth()
    body = body_json()
    location = v_str(body, "location_description")
    require_roles(role, ["Inspector"])
    current = now()
    be = {
        "id": str(uuid.uuid4()),
        "location_description": location,
        "status": "REPORTED",
        "total_cleanup_cost_cents": None,
        "contributions": [],
        "reported_by_user_id": uid,
        "assessed_by_user_id": None,
        "closed_by_user_id": None,
        "created_at": current,
        "updated_at": current,
        "version": 1,
        "_seq": next_seq(),
    }
    STORE["blockages"][be["id"]] = be
    return success(ser_blockage(be), 201)


@bp.get("/blockage-events/<bid>")
def get_blockage(bid):
    uid, role = auth()
    require_roles(role, READERS)
    be = get_or_404("blockages", bid)
    if role == "FseContact" and be["contributions"]:
        forbid_unless(any(c["establishment_id"] == uid for c in be["contributions"]))
    return success(ser_blockage(be))


def _validate_contributions(body):
    if "contributions" not in body or body["contributions"] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: contributions")
    contributions = body["contributions"]
    if not isinstance(contributions, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'contributions' must be an array")
    normalized = []
    for entry in contributions:
        if not isinstance(entry, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Each contribution must be an object")
        est_id = entry.get("establishment_id")
        weight = entry.get("weight_percent")
        if not isinstance(est_id, str):
            raise ApiError(ERR_INVALID_REQUEST, 400, "contribution.establishment_id must be a string")
        if isinstance(weight, bool) or not isinstance(weight, int) or weight < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "contribution.weight_percent must be a non-negative integer")
        normalized.append({"establishment_id": est_id, "weight_percent": weight})
    return normalized


@bp.post("/blockage-events/<bid>/assess")
def assess_blockage(bid):
    uid, role = auth()
    body = body_json()
    total = v_int(body, "total_cleanup_cost_cents", min_val=1)
    contributions = _validate_contributions(body)
    require_roles(role, ["Inspector"])
    be = get_or_404("blockages", bid)
    # Priority 5: every contribution establishment id must exist.
    for c in contributions:
        if c["establishment_id"] not in STORE["establishments"]:
            raise ApiError(ERR_NOT_FOUND, 404, f"Establishment not found: {c['establishment_id']}")
    if be["status"] != "REPORTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Blockage event is not in REPORTED status")
    if len(contributions) == 0:
        raise ApiError(ERR_NO_CONTRIBUTORS, 422, "contributions must not be empty")
    if sum(c["weight_percent"] for c in contributions) != 100:
        raise ApiError(ERR_WEIGHTS_INVALID, 422, "weight_percent values must sum to 100")
    shares = apportion_shares(total, contributions)
    current = now()
    be["contributions"] = [
        {
            "establishment_id": c["establishment_id"],
            "weight_percent": c["weight_percent"],
            "share_cents": shares[idx],
            "paid_at": None,
        }
        for idx, c in enumerate(contributions)
    ]
    be["total_cleanup_cost_cents"] = total
    be["assessed_by_user_id"] = uid
    be["status"] = "ASSESSED"
    be["updated_at"] = current
    be["version"] += 1
    return success(ser_blockage(be))


@bp.post("/blockage-events/<bid>/pay")
def pay_blockage_share(bid):
    uid, role = auth()
    body = body_json()
    est_id = v_str(body, "establishment_id")
    require_roles(role, ["FseContact"])
    forbid_unless(uid == est_id)
    be = get_or_404("blockages", bid)
    get_or_404("establishments", est_id)
    if be["status"] != "ASSESSED":
        raise ApiError(ERR_INVALID_STATE, 409, "Blockage event is not in ASSESSED status")
    contribution = next((c for c in be["contributions"] if c["establishment_id"] == est_id), None)
    if contribution is None:
        raise ApiError(ERR_NOT_FOUND, 404, "No contribution for this establishment on this blockage event")
    if contribution["paid_at"] is not None:
        raise ApiError(ERR_INVALID_STATE, 409, "Contribution has already been paid")
    contribution["paid_at"] = now()
    be["updated_at"] = contribution["paid_at"]
    be["version"] += 1
    return success(ser_blockage(be))


@bp.post("/blockage-events/<bid>/close")
def close_blockage(bid):
    uid, role = auth()
    require_roles(role, ["ComplianceOfficer"])
    be = get_or_404("blockages", bid)
    if be["status"] != "ASSESSED":
        raise ApiError(ERR_INVALID_STATE, 409, "Blockage event is not in ASSESSED status")
    if uid == be["assessed_by_user_id"]:
        raise ApiError(ERR_SOD_VIOLATION, 403, "Closing officer must differ from the assessing inspector")
    if any(c["paid_at"] is None for c in be["contributions"]):
        raise ApiError(ERR_COST_SHARE_UNPAID, 409, "All cost shares must be paid before closing")
    be["status"] = "CLOSED"
    be["closed_by_user_id"] = uid
    be["updated_at"] = now()
    be["version"] += 1
    return success(ser_blockage(be))
