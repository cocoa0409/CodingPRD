"""The creative review loop and the wrap-up cascade (PRD 3.4)."""
from flask import Blueprint

import calc
import db
import response
import services
import validate
from auth import endpoint
from errors import ApiError

bp = Blueprint("deliverables", __name__)


@bp.post("/deliverables")
@endpoint(["CreativeLead"])
def create_deliverable():
    b = validate.body()
    campaign_id = validate.req_str(b, "campaign_id")
    title = validate.req_str(b, "title")

    services.must("campaign", campaign_id)

    obj = db.base_entity()
    obj.update(
        {
            "campaign_id": campaign_id,
            "title": title,
            "current_asset_version": 0,
            "approved_asset_version": None,
            "revision_round": 0,
            "last_feedback": None,
            "status": "DRAFT",
        }
    )
    db.DELIVERABLES[obj["id"]] = obj
    return response.created(db.public(obj))


@bp.post("/deliverables/<did>/submit")
@endpoint(["CreativeLead"])
def submit_deliverable(did):
    deliverable = services.must("deliverable", did)

    if deliverable["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE")
    campaign = services.must("campaign", deliverable["campaign_id"])
    services.campaign_gate(campaign)

    deliverable["current_asset_version"] += 1
    deliverable["status"] = "SUBMITTED"
    services.touch(deliverable)
    return response.ok(db.public(deliverable))


@bp.post("/deliverables/<did>/request-changes")
@endpoint(["ClientReviewer"])
def request_changes(did):
    b = validate.body()
    feedback = validate.req_str(b, "feedback")

    deliverable = services.must("deliverable", did)
    campaign = services.must("campaign", deliverable["campaign_id"])
    services.must_own_client(campaign["client_id"])

    if deliverable["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")
    services.campaign_gate(campaign)
    if deliverable["revision_round"] >= calc.MAX_REVISION_ROUNDS:
        raise ApiError("ERR_REVISION_LIMIT_EXCEEDED")

    deliverable["revision_round"] += 1
    deliverable["last_feedback"] = feedback
    deliverable["status"] = "CHANGES_REQUESTED"
    services.touch(deliverable)
    return response.ok(db.public(deliverable))


@bp.post("/deliverables/<did>/approve")
@endpoint(["ClientReviewer"])
def approve_deliverable(did):
    deliverable = services.must("deliverable", did)
    campaign = services.must("campaign", deliverable["campaign_id"])
    services.must_own_client(campaign["client_id"])

    if deliverable["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")
    services.campaign_gate(campaign)

    deliverable["status"] = "APPROVED"
    deliverable["approved_asset_version"] = deliverable["current_asset_version"]
    services.touch(deliverable)

    services.wrap_up_cascade(campaign)
    return response.ok(db.public(deliverable))
