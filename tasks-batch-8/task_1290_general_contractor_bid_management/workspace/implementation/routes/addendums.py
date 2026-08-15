from flask import Blueprint, request

import errors
from db import DB, CLOCK, new_id, stamp_new, touch, iso_now
from middleware import (
    get_context, require_role, get_json_body, require_fields, reject_unexpected,
    require_string, parse_limit_offset,
)
from response import success_object, success_list
from services import bids as bid_svc

bp = Blueprint("addendums", __name__)

ESTIMATORS = {"LeadEstimator", "ChiefEstimator", "PrequalReviewer"}
ALL_READERS = ESTIMATORS | {"Subcontractor"}


def serialize_addendum(add):
    return {
        "id": add["id"],
        "bid_package_id": add["bid_package_id"],
        "number": add["number"],
        "summary": add["summary"],
        "issued_at": add["issued_at"],
        "created_at": add["created_at"],
        "updated_at": add["updated_at"],
        "version": add["version"],
    }


def serialize_ack(ack):
    return {
        "id": ack["id"],
        "addendum_id": ack["addendum_id"],
        "subcontractor_id": ack["subcontractor_id"],
        "status": ack["status"],
        "acknowledged_at": ack["acknowledged_at"],
        "waived_reason": ack["waived_reason"],
        "created_at": ack["created_at"],
        "updated_at": ack["updated_at"],
        "version": ack["version"],
    }


def get_addendum_or_404(add_id):
    add = DB.addendums.get(add_id)
    if add is None:
        raise errors.err_addendum_not_found()
    return add


@bp.post("/addendums")
def create_addendum():
    _, role = get_context()
    require_role(role, {"LeadEstimator"})
    body = get_json_body()
    reject_unexpected(body, {"bid_package_id", "summary"})
    require_fields(body, ["bid_package_id", "summary"])
    pkg_id = body["bid_package_id"]
    if not isinstance(pkg_id, str):
        raise errors.err_invalid_request("bid_package_id must be a string")
    summary = require_string(body, "summary")
    pkg = DB.bid_packages.get(pkg_id)
    if pkg is None:
        raise errors.err_package_not_found()
    if pkg["status"] != "PUBLISHED":
        raise errors.err_package_invalid_state("Addenda may be issued only while PUBLISHED")

    existing_numbers = [a["number"] for a in DB.addendums.values() if a["bid_package_id"] == pkg_id]
    number = (max(existing_numbers) + 1) if existing_numbers else 1
    add = {
        "id": new_id(),
        "bid_package_id": pkg_id,
        "number": number,
        "summary": summary,
        "issued_at": iso_now(),
    }
    stamp_new(add)
    add["_created_at_dt"] = CLOCK.now()
    DB.addendums[add["id"]] = add

    # Cascade: PENDING ack per invitation in {SENT, BIDDING}
    affected_subs = []
    for inv in DB.invitations.values():
        if inv["bid_package_id"] == pkg_id and inv["status"] in ("SENT", "BIDDING"):
            ack = {
                "id": new_id(),
                "addendum_id": add["id"],
                "subcontractor_id": inv["subcontractor_id"],
                "status": "PENDING",
                "acknowledged_at": None,
                "waived_reason": None,
            }
            stamp_new(ack)
            ack["_created_at_dt"] = CLOCK.now()
            DB.acks[ack["id"]] = ack
            affected_subs.append(inv["subcontractor_id"])
    for sub_id in affected_subs:
        bid_svc.recompute_ack_complete_for(pkg_id, sub_id)
    pkg["issued_addendum_count"] += 1
    touch(pkg)
    return success_object(serialize_addendum(add), 201)


@bp.get("/addendums")
def list_addendums():
    _, role = get_context()
    require_role(role, ALL_READERS)
    limit, offset = parse_limit_offset(request.args)
    pkg_f = request.args.get("bid_package_id")
    items = sorted(DB.addendums.values(), key=lambda a: (a["_created_at_dt"], a["id"]))
    if pkg_f is not None:
        items = [a for a in items if a["bid_package_id"] == pkg_f]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_addendum(a) for a in page], limit, offset, total)


@bp.get("/addendums/<add_id>")
def read_addendum(add_id):
    _, role = get_context()
    require_role(role, ALL_READERS)
    add = get_addendum_or_404(add_id)
    return success_object(serialize_addendum(add))


@bp.get("/addendums/<add_id>/acknowledgments")
def list_addendum_acks(add_id):
    user_id, role = get_context()
    require_role(role, ALL_READERS)
    add = get_addendum_or_404(add_id)
    limit, offset = parse_limit_offset(request.args)
    status_f = request.args.get("status")
    sub_f = request.args.get("subcontractor_id")
    items = sorted(
        (a for a in DB.acks.values() if a["addendum_id"] == add_id),
        key=lambda a: (a["_created_at_dt"], a["id"]),
    )
    if role == "Subcontractor":
        items = [a for a in items if a["subcontractor_id"] == user_id]
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    if sub_f is not None:
        items = [a for a in items if a["subcontractor_id"] == sub_f]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_ack(a) for a in page], limit, offset, total)


@bp.post("/addendums/<add_id>/acknowledge")
def acknowledge(add_id):
    user_id, role = get_context()
    require_role(role, {"Subcontractor"})
    add = get_addendum_or_404(add_id)
    pkg = DB.bid_packages.get(add["bid_package_id"])
    if pkg is None or pkg["status"] not in ("PUBLISHED", "BIDDING_CLOSED"):
        raise errors.err_package_invalid_state("Acknowledge requires PUBLISHED or BIDDING_CLOSED")
    ack = next(
        (a for a in DB.acks.values()
         if a["addendum_id"] == add_id and a["subcontractor_id"] == user_id and a["status"] == "PENDING"),
        None,
    )
    if ack is None:
        raise errors.err_ack_not_found()
    ack["status"] = "ACKNOWLEDGED"
    ack["acknowledged_at"] = iso_now()
    touch(ack)
    bid_svc.recompute_ack_complete_for(add["bid_package_id"], user_id)
    return success_object(serialize_ack(ack))


@bp.post("/addendums/<add_id>/waive")
def waive(add_id):
    _, role = get_context()
    require_role(role, {"LeadEstimator"})
    add = get_addendum_or_404(add_id)
    body = get_json_body()
    reject_unexpected(body, {"subcontractor_id", "reason"})
    require_fields(body, ["subcontractor_id"])
    sub_id = body["subcontractor_id"]
    if not isinstance(sub_id, str):
        raise errors.err_invalid_request("subcontractor_id must be a string")
    reason = body.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise errors.err_invalid_request("reason must be a string")
    pkg = DB.bid_packages.get(add["bid_package_id"])
    if pkg is None or pkg["status"] not in ("PUBLISHED", "BIDDING_CLOSED"):
        raise errors.err_package_invalid_state("Waive requires PUBLISHED or BIDDING_CLOSED")
    ack = next(
        (a for a in DB.acks.values()
         if a["addendum_id"] == add_id and a["subcontractor_id"] == sub_id and a["status"] == "PENDING"),
        None,
    )
    if ack is None:
        raise errors.err_ack_not_found()
    ack["status"] = "WAIVED"
    ack["waived_reason"] = reason
    touch(ack)
    bid_svc.recompute_ack_complete_for(add["bid_package_id"], sub_id)
    return success_object(serialize_ack(ack))
