"""Engineering change notices and WIP disposition (PRD 3.8)."""
from flask import Blueprint, request

from db import db
from errors import (raise_error, ERR_INVALID_REQUEST, ERR_DRAWING_NOT_RELEASED,
                    ERR_ECN_ALREADY_OPEN, ERR_ECN_REVISION_UNCHANGED,
                    ERR_ECN_NOT_OPEN)
from middleware import authenticate, ALL_ROLES
from response import success_object
from services import (WIP_DISPOSITIONS, common_fields, touch, apply_ecn,
                      ser_ecn, paginated)
from validate import get_body, req_str, req_enum, require_path, require_fk

bp = Blueprint("ecns", __name__)

HARNESS_ENGINEER = {"HarnessEngineer"}


@bp.route("/plant/ecns", methods=["POST"])
def create_ecn():
    body = get_body()
    # Tier 1 (ecn_code is supplied per PRD 3.8).
    ecn_code = req_str(body, "ecn_code")
    drawing_id = req_str(body, "drawing_id")
    to_revision = req_str(body, "to_revision")
    wip_disposition = req_enum(body, "wip_disposition", WIP_DISPOSITIONS)
    # Tiers 2-3
    authenticate(HARNESS_ENGINEER)
    # Tier 4
    drawing = require_fk("drawings", drawing_id, "drawing_id")
    # Tier 6
    if drawing["status"] != "RELEASED":
        raise_error(ERR_DRAWING_NOT_RELEASED, "ECNs require a RELEASED drawing")
    # Tier 9, scaffold order: single open ECN per drawing, then changed revision.
    for e in db["ecns"].values():
        if e["drawing_id"] == drawing["id"] and e["status"] == "OPEN":
            raise_error(ERR_ECN_ALREADY_OPEN,
                        "another OPEN ECN exists for this drawing")
    if to_revision == drawing["revision"]:
        raise_error(ERR_ECN_REVISION_UNCHANGED,
                    "to_revision must differ from from_revision")
    for e in db["ecns"].values():
        if e["ecn_code"] == ecn_code:
            raise_error(ERR_INVALID_REQUEST, f"duplicate ecn_code: {ecn_code}")

    ecn = common_fields()
    ecn.update({
        "ecn_code": ecn_code,
        "drawing_id": drawing["id"],
        "from_revision": drawing["revision"],
        "to_revision": to_revision,
        "wip_disposition": wip_disposition,
        "status": "OPEN",
        "applied_at": None,
        "new_drawing_id": None,
    })
    db["ecns"][ecn["id"]] = ecn
    return success_object(ser_ecn(ecn), 201)


@bp.route("/plant/ecns/<eid>", methods=["GET"])
def get_ecn(eid):
    authenticate(ALL_ROLES)
    ecn = require_path("ecns", eid)
    return success_object(ser_ecn(ecn), 200)


@bp.route("/plant/ecns", methods=["GET"])
def list_ecns():
    authenticate(ALL_ROLES)
    items = list(db["ecns"].values())
    drawing_id = request.args.get("drawing_id")
    if drawing_id is not None:
        items = [e for e in items if e["drawing_id"] == drawing_id]
    new_drawing_id = request.args.get("new_drawing_id")
    if new_drawing_id is not None:
        items = [e for e in items if e["new_drawing_id"] == new_drawing_id]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return paginated(items, ser_ecn)


@bp.route("/plant/ecns/<eid>/apply", methods=["POST"])
def apply_ecn_endpoint(eid):
    get_body()
    authenticate(HARNESS_ENGINEER)
    ecn = require_path("ecns", eid)
    if ecn["status"] != "OPEN":
        raise_error(ERR_ECN_NOT_OPEN, "only an OPEN ECN may be applied")
    apply_ecn(ecn)
    return success_object(ser_ecn(ecn), 200)


@bp.route("/plant/ecns/<eid>/cancel", methods=["POST"])
def cancel_ecn(eid):
    get_body()
    authenticate(HARNESS_ENGINEER)
    ecn = require_path("ecns", eid)
    if ecn["status"] != "OPEN":
        raise_error(ERR_ECN_NOT_OPEN, "only an OPEN ECN may be cancelled")
    ecn["status"] = "CANCELLED"
    touch(ecn)
    return success_object(ser_ecn(ecn), 200)
