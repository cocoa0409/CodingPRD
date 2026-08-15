"""ShopDrawing endpoints (PRD §3.3): version-pinned revisions, architect review."""

from flask import Blueprint, request

import db
from errors import err
from middleware import (get_context, require_role, raw_body, validate_fields,
                        req_string, req_int, require_existence)
from response import success, list_response, parse_pagination
from services import cascade

bp = Blueprint("drawings", __name__)

DRAWING_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED", "VOID")
TARGET_ACTORS = {
    "SUBMITTED": ("Estimator",),
    "VOID": ("Estimator",),
    "APPROVED": ("Architect",),
    "REJECTED": ("Architect",),
}
ALL_STATUS_ACTORS = ("Estimator", "Architect")


def serialize(d):
    return {
        "id": d["id"],
        "order_id": d["order_id"],
        "revision_no": d["revision_no"],
        "pinned_species": d["pinned_species"],
        "pinned_profile_code": d["pinned_profile_code"],
        "pinned_sheen_target": d["pinned_sheen_target"],
        "pinned_fire_rating_required": d["pinned_fire_rating_required"],
        "pinned_hardware_prep_mode": d["pinned_hardware_prep_mode"],
        "supersedes_drawing_id": d["supersedes_drawing_id"],
        "submitted_by": d["submitted_by"],
        "reviewed_by": d["reviewed_by"],
        "review_note": d["review_note"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


@bp.post("/shop-drawings")
def create_drawing():
    _, role = get_context()
    require_role(role, "Estimator")
    body = raw_body()
    # Rung 3: body FK existence.
    if body.get("order_id") is not None:
        order = require_existence(db.orders, body["order_id"], "ERR_ORDER_NOT_FOUND", "MillworkOrder")
    else:
        order = None
    # Rung 4: payload well-formedness.
    validate_fields(body, required=("order_id", "expected_order_version"))
    expected = req_int(body, "expected_order_version")
    # Rung 5 (OCC): expected_order_version must equal the order's current version.
    if expected != order["version"]:
        raise err("ERR_STALE_ORDER_VERSION",
                  "expected_order_version differs from the order's current version")
    # Rung 6: creation only against a CONFIGURED order.
    if order["status"] != "CONFIGURED":
        raise err("ERR_ORDER_NOT_CONFIGURED", "Drawing creation requires order CONFIGURED")
    # Rung 8: no other drawing of the order in DRAFT or SUBMITTED.
    siblings = [d for d in db.shop_drawings.values() if d["order_id"] == order["id"]]
    for sibling in siblings:
        if sibling["status"] in ("DRAFT", "SUBMITTED"):
            raise err("ERR_ACTIVE_DRAWING_EXISTS",
                      "Another drawing of the order is DRAFT or SUBMITTED")
    previous = max(siblings, key=lambda d: d["revision_no"], default=None)
    rec = db.new_record()
    rec.update({
        "order_id": order["id"],
        "revision_no": len(siblings) + 1,
        "pinned_species": order["species"],
        "pinned_profile_code": order["profile_code"],
        "pinned_sheen_target": order["sheen_target"],
        "pinned_fire_rating_required": order["fire_rating_required"],
        "pinned_hardware_prep_mode": order["hardware_prep_mode"],
        "supersedes_drawing_id": previous["id"] if previous else None,
        "submitted_by": None,
        "reviewed_by": None,
        "review_note": None,
        "status": "DRAFT",
    })
    db.shop_drawings[rec["id"]] = rec
    # Creating a revision is itself an order mutation.
    db.touch(order)
    return success(serialize(rec), status=201)


@bp.get("/shop-drawings")
def list_drawings():
    get_context()
    limit, offset = parse_pagination(request.args)
    order_id = request.args.get("order_id")
    supersedes = request.args.get("supersedes_drawing_id")
    status = request.args.get("status")
    items = [d for d in db.shop_drawings.values()
             if (order_id is None or d["order_id"] == order_id)
             and (supersedes is None or d["supersedes_drawing_id"] == supersedes)
             and (status is None or d["status"] == status)]
    return list_response(items, limit, offset, serialize)


@bp.get("/shop-drawings/<did>")
def get_drawing(did):
    get_context()
    drawing = require_existence(db.shop_drawings, did, "ERR_DRAWING_NOT_FOUND", "ShopDrawing")
    return success(serialize(drawing))


@bp.put("/shop-drawings/<did>/status")
def transition_drawing(did):
    user_id, role = get_context()
    body = raw_body()
    # Peek at target_status for per-target authorization (rung 2) without
    # validating payload — existence (rung 3) must precede payload errors (rung 4).
    target = body.get("target_status")
    allowed = TARGET_ACTORS.get(target, ALL_STATUS_ACTORS)
    require_role(role, *allowed)
    drawing = require_existence(db.shop_drawings, did, "ERR_DRAWING_NOT_FOUND", "ShopDrawing")
    validate_fields(body, required=("target_status",), optional=("review_note",))
    review_note = body.get("review_note")
    if review_note is not None and not isinstance(review_note, str):
        raise err("ERR_INVALID_REQUEST", "review_note must be a string")
    current = drawing["status"]
    order = db.orders.get(drawing["order_id"])

    if target == "SUBMITTED":
        if current != "DRAFT":
            raise err("ERR_INVALID_DRAWING_STATUS_TRANSITION",
                      "Drawing cannot transition from %s to SUBMITTED" % current)
        if order is None or order["status"] != "CONFIGURED":
            raise err("ERR_ORDER_NOT_CONFIGURED", "Submit requires order CONFIGURED")
        for sibling in db.shop_drawings.values():
            if (sibling["order_id"] == drawing["order_id"] and sibling["id"] != did
                    and sibling["status"] == "SUBMITTED"):
                raise err("ERR_ACTIVE_DRAWING_EXISTS",
                          "Another drawing of the order is SUBMITTED")
        drawing["submitted_by"] = user_id
        drawing["status"] = "SUBMITTED"
        if order is not None:
            order["status"] = "SUBMITTED"
            db.touch(order)

    elif target == "APPROVED":
        if current != "SUBMITTED":
            raise err("ERR_INVALID_DRAWING_STATUS_TRANSITION",
                      "Drawing cannot transition from %s to APPROVED" % current)
        if user_id == drawing["submitted_by"]:
            raise err("ERR_SELF_APPROVAL_FORBIDDEN",
                      "Approver must differ from the submitter")
        drawing["reviewed_by"] = user_id
        drawing["review_note"] = review_note
        drawing["status"] = "APPROVED"
        # Supersede any earlier APPROVED revision of the same order.
        for sibling in db.shop_drawings.values():
            if (sibling["order_id"] == drawing["order_id"] and sibling["id"] != did
                    and sibling["status"] == "APPROVED"):
                cascade.supersede_drawing(sibling)
        if order is not None:
            order["status"] = "APPROVED"
            order["config_locked"] = True
            cascade.compute_contract_into_order(order)
            db.touch(order)

    elif target == "REJECTED":
        if current != "SUBMITTED":
            raise err("ERR_INVALID_DRAWING_STATUS_TRANSITION",
                      "Drawing cannot transition from %s to REJECTED" % current)
        drawing["reviewed_by"] = user_id
        drawing["review_note"] = review_note
        drawing["status"] = "REJECTED"
        if order is not None:
            order["status"] = "CONFIGURED"
            db.touch(order)

    elif target == "VOID":
        if current != "DRAFT":
            raise err("ERR_INVALID_DRAWING_STATUS_TRANSITION",
                      "Drawing cannot transition from %s to VOID" % current)
        drawing["status"] = "VOID"

    elif target in DRAWING_STATUSES:
        raise err("ERR_INVALID_DRAWING_STATUS_TRANSITION",
                  "Drawing cannot transition from %s to %s" % (current, target))
    else:
        raise err("ERR_INVALID_DRAWING_STATUS_TRANSITION",
                  "Unknown drawing status: %s" % target)

    db.touch(drawing)
    return success(serialize(drawing))
