"""Diet order intake and the parallel clinical / review axes."""
from flask import Blueprint

import serialize
from auth import authenticate, require_own_indirect, rep_scope
from clock import clock
from constants import (
    CLINICAL_STATUSES, DECISIONS, DIET_CODES, LIQUIDS, MAX_DIET_REVIEW_ROUNDS,
    REVIEW_STATUSES, TEXTURES, TEXTURE_RANK,
)
from db import base_row, db, sort_created, touch
from errors import api_error
from response import created, ok, ok_list
from routes.common import (
    CS, DSM, PA, RD, RR, SKL, get_diet_order, get_resident,
)
from services import derive
from shape import (
    body_json, opt_enum, opt_enum_array, opt_str, paginate, q_enum, q_str,
    req_enum, req_int, req_str,
)

bp = Blueprint("diet_orders", __name__)

READ_ROLES = [PA, CS, RD, DSM, SKL, RR]


def _texture_gate(resident, texture_level):
    active = derive.find_active_order(resident["id"])
    if active is None:
        return
    if TEXTURE_RANK[texture_level] >= TEXTURE_RANK[active["texture_level"]]:
        return
    if derive.has_open_review(resident["id"]) is not None:
        raise api_error(
            "ERR_TEXTURE_REQUIRES_DIETITIAN",
            "Liberalizing the texture requires dietitian involvement while a "
            "plan-of-care review is OPEN",
        )


@bp.get("/diet-orders/<order_id>")
def read_order(order_id):
    ctx = authenticate(READ_ROLES)
    row = get_diet_order(order_id)
    require_own_indirect(ctx, row)
    return ok(serialize.diet_order(row))


@bp.get("/diet-orders")
def list_orders():
    ctx = authenticate(READ_ROLES)
    resident_id = q_str("resident_id")
    supersedes_order_id = q_str("supersedes_order_id")
    clinical_status = q_enum("clinical_status", CLINICAL_STATUSES)
    review_status = q_enum("review_status", REVIEW_STATUSES)

    scope = rep_scope(ctx)
    if scope is not None and resident_id is not None and resident_id != scope:
        raise api_error(
            "ERR_FORBIDDEN_ROLE",
            "A ResidentRepresentative may only list its own resident's orders",
        )

    rows = list(db.diet_orders.values())
    if scope is not None:
        rows = [o for o in rows if o["resident_id"] == scope]
    if resident_id is not None:
        rows = [o for o in rows if o["resident_id"] == resident_id]
    if supersedes_order_id is not None:
        rows = [o for o in rows if o["supersedes_order_id"] == supersedes_order_id]
    if clinical_status is not None:
        rows = [o for o in rows if o["clinical_status"] == clinical_status]
    if review_status is not None:
        rows = [o for o in rows if o["review_status"] == review_status]
    window, pagination = paginate(sort_created(rows))
    return ok_list(serialize.many(serialize.diet_order, window), pagination)


@bp.post("/diet-orders")
def create_order():
    ctx = authenticate([CS])
    body = body_json()
    resident_id = req_str(body, "resident_id")
    texture_level = req_enum(body, "texture_level", TEXTURES)
    liquid_consistency = req_enum(body, "liquid_consistency", LIQUIDS)
    expected_resident_version = req_int(body, "expected_resident_version")
    therapeutic_codes = opt_enum_array(body, "therapeutic_codes", DIET_CODES)
    supersedes_order_id = opt_str(body, "supersedes_order_id")

    resident = get_resident(resident_id)
    predecessor = None
    if supersedes_order_id is not None:
        predecessor = get_diet_order(supersedes_order_id)
        if predecessor["resident_id"] != resident_id:
            raise api_error(
                "ERR_LINKED_RESOURCE_MISMATCH",
                "supersedes_order_id must name an order of the payload's resident",
            )
        if predecessor["clinical_status"] != "ACTIVE":
            raise api_error(
                "ERR_INVALID_STATE",
                "supersedes_order_id must name a clinical_status == ACTIVE order",
            )

    if expected_resident_version != resident["version"]:
        raise api_error(
            "ERR_STALE_VERSION",
            "expected_resident_version %s does not match the resident's current version %s"
            % (expected_resident_version, resident["version"]),
        )

    _texture_gate(resident, texture_level)

    if resident["dining_status"] == "DISCHARGED":
        raise api_error(
            "ERR_RESIDENT_NOT_ACTIVE",
            "A DISCHARGED resident cannot accept a new diet order",
        )

    row = base_row()
    row.update({
        "resident_id": resident_id,
        "supersedes_order_id": supersedes_order_id,
        "texture_level": texture_level,
        "liquid_consistency": liquid_consistency,
        "therapeutic_codes": therapeutic_codes,
        "clinical_status": "PENDING_REVIEW",
        "review_status": "AWAITING_DIETITIAN",
        "review_round": 0,
        "ordered_by_user_id": ctx["user_id"],
        "reviewed_by_user_id": None,
        "reviewer_note": None,
        "activated_at": None,
    })
    db.diet_orders[row["id"]] = row
    touch(resident)
    return created(serialize.diet_order(row))


@bp.post("/diet-orders/<order_id>/dietitian-review")
def dietitian_review(order_id):
    ctx = authenticate([RD])
    body = body_json()
    decision = req_enum(body, "decision", DECISIONS)
    reviewer_note = opt_str(body, "reviewer_note")

    order = get_diet_order(order_id)

    if order["review_status"] not in ("AWAITING_DIETITIAN", "REREVIEW_REQUIRED"):
        raise api_error(
            "ERR_INVALID_STATE",
            "A decision is only accepted while review_status is AWAITING_DIETITIAN or REREVIEW_REQUIRED",
        )
    if ctx["user_id"] == order["ordered_by_user_id"]:
        raise api_error(
            "ERR_SEGREGATION_OF_DUTIES",
            "The reviewing dietitian must differ from the order's ordered_by_user_id",
        )
    if decision == "REQUEST_CHANGES" and order["review_round"] >= MAX_DIET_REVIEW_ROUNDS:
        raise api_error(
            "ERR_REVIEW_ROUND_LIMIT",
            "review_round has reached the ceiling of %d" % MAX_DIET_REVIEW_ROUNDS,
        )

    resident = db.residents.get(order["resident_id"])
    previous_review_status = order["review_status"]

    if decision == "APPROVE":
        order["review_status"] = "APPROVED"
        order["reviewed_by_user_id"] = ctx["user_id"]
        if reviewer_note is not None:
            order["reviewer_note"] = reviewer_note
        if previous_review_status == "AWAITING_DIETITIAN":
            if order["clinical_status"] == "PENDING_REVIEW":
                order["clinical_status"] = "ACTIVE"
                order["activated_at"] = clock.iso()
            if order["supersedes_order_id"] is not None:
                predecessor = db.diet_orders.get(order["supersedes_order_id"])
                if predecessor is not None and predecessor["clinical_status"] == "ACTIVE":
                    predecessor["clinical_status"] = "SUPERSEDED"
                    touch(predecessor)
        touch(order)
        if resident is not None:
            if previous_review_status == "REREVIEW_REQUIRED" and resident["tray_card_state"] == "HOLD_PENDING_REVIEW":
                resident["tray_card_state"] = "CLEAR"
                touch(resident)
            derive.recompute_risk_score(resident)
    else:
        order["review_status"] = "CHANGES_REQUESTED"
        order["review_round"] = order["review_round"] + 1
        order["reviewed_by_user_id"] = ctx["user_id"]
        order["reviewer_note"] = reviewer_note
        touch(order)

    return ok(serialize.diet_order(order))


@bp.post("/diet-orders/<order_id>/resubmit")
def resubmit_order(order_id):
    authenticate([CS])
    body = body_json()
    texture_level = opt_enum(body, "texture_level", TEXTURES)
    liquid_consistency = opt_enum(body, "liquid_consistency", LIQUIDS)
    therapeutic_codes = None
    if "therapeutic_codes" in body and body["therapeutic_codes"] is not None:
        therapeutic_codes = opt_enum_array(body, "therapeutic_codes", DIET_CODES)

    order = get_diet_order(order_id)

    if order["review_status"] != "CHANGES_REQUESTED" or order["clinical_status"] != "PENDING_REVIEW":
        raise api_error(
            "ERR_INVALID_STATE",
            "Resubmission requires review_status CHANGES_REQUESTED and clinical_status PENDING_REVIEW",
        )

    resident = db.residents.get(order["resident_id"])
    effective_texture = texture_level if texture_level is not None else order["texture_level"]
    if resident is not None:
        _texture_gate(resident, effective_texture)

    if texture_level is not None:
        order["texture_level"] = texture_level
    if liquid_consistency is not None:
        order["liquid_consistency"] = liquid_consistency
    if therapeutic_codes is not None:
        order["therapeutic_codes"] = therapeutic_codes
    order["review_status"] = "AWAITING_DIETITIAN"
    touch(order)
    return ok(serialize.diet_order(order))


@bp.post("/diet-orders/<order_id>/discontinue")
def discontinue_order(order_id):
    authenticate([CS])
    body = body_json()
    opt_str(body, "reason")

    order = get_diet_order(order_id)
    if order["clinical_status"] not in ("PENDING_REVIEW", "ACTIVE"):
        raise api_error(
            "ERR_INVALID_STATE",
            "Only a PENDING_REVIEW or ACTIVE order may be discontinued",
        )

    was_active = order["clinical_status"] == "ACTIVE"
    order["clinical_status"] = "DISCONTINUED"
    touch(order)

    if was_active:
        resident = db.residents.get(order["resident_id"])
        if resident is not None:
            derive.recompute_risk_score(resident)

    return ok(serialize.diet_order(order))
