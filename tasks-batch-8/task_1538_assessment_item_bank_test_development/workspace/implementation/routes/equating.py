"""EquatingLink endpoints (PRD §3.7)."""
from flask import Blueprint, request

from db import db, next_seq
from errors import (
    raise_error,
    ERR_ANCHOR_SET_INVALID,
    ERR_INVALID_STATE,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services.common import touch
from services.equating import compute_scaling
from util import new_id, now_ts, program_clock_iso
from validate import get_body, req_str, req_str_list, require_path_resource, require_body_ref

bp = Blueprint("equating", __name__)

READ_ROLES = ["ProgramDirector", "Psychometrician"]


@bp.post("/api/equating-links")
def create_link():
    caller = authorized(["Psychometrician"])
    body = get_body()
    program_id = req_str(body, "program_id")
    source_form_id = req_str(body, "source_form_id")
    target_form_id = req_str(body, "target_form_id")
    anchor_item_ids = req_str_list(body, "anchor_item_ids")

    program = require_body_ref("assessment_programs", program_id, "program_id")
    source_form = require_body_ref("test_forms", source_form_id, "source_form_id")
    target_form = require_body_ref("test_forms", target_form_id, "target_form_id")

    # Anchor-set validity (priority 13): size 3..10 and every anchor flagged
    # is_anchor on BOTH forms.
    if len(anchor_item_ids) < 3 or len(anchor_item_ids) > 10:
        raise_error(ERR_ANCHOR_SET_INVALID, "anchor_item_ids must hold between 3 and 10 items")

    def anchor_slot(form_id, item_id):
        for s in db["form_item_slots"].values():
            if s["form_id"] == form_id and s["item_id"] == item_id:
                return s
        return None

    for item_id in anchor_item_ids:
        s_src = anchor_slot(source_form_id, item_id)
        s_tgt = anchor_slot(target_form_id, item_id)
        if (
            s_src is None or not s_src["is_anchor"]
            or s_tgt is None or not s_tgt["is_anchor"]
        ):
            raise_error(
                ERR_ANCHOR_SET_INVALID,
                f"anchor item {item_id} must be an is_anchor slot on both forms",
            )

    if target_form["status"] != "ASSEMBLED":
        raise_error(ERR_INVALID_STATE, "target form must be ASSEMBLED to be equated")

    slope, intercept = compute_scaling(anchor_item_ids, program["_clock_dt"])

    now = now_ts()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "program_id": program_id,
        "source_form_id": source_form_id,
        "target_form_id": target_form_id,
        "anchor_item_ids": anchor_item_ids,
        "scaling_slope": slope,
        "scaling_intercept": intercept,
        "equated_at": program_clock_iso(program),
        "_seq": next_seq(),
    }
    db["equating_links"][rec["id"]] = rec

    # Target form advances ASSEMBLED -> EQUATED.
    target_form["status"] = "EQUATED"
    touch(target_form)

    return success_object(public(rec), status=201)


@bp.get("/api/equating-links")
def list_links():
    authorized(READ_ROLES)
    filters = {
        "program_id": request.args.get("program_id"),
        "source_form_id": request.args.get("source_form_id"),
        "target_form_id": request.args.get("target_form_id"),
    }
    return list_response("equating_links", filters)


@bp.get("/api/equating-links/<eid>")
def get_link(eid):
    authorized(READ_ROLES)
    rec = require_path_resource("equating_links", eid)
    return get_one(rec)
