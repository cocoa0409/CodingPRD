"""Performer endpoints."""
from flask import Blueprint

from db import store, new_id, next_seq
from errors import ERR_PERFORMER_NOT_FOUND
from middleware import (
    require_roles,
    get_body,
    load,
    parse_pagination,
    sorted_by_creation,
)
from response import obj_response, list_response
from util import req, check_unknown, new_record, public_view

bp = Blueprint("performers", __name__)

ACT_TYPES = {"MUSIC", "COMBAT", "COMEDY", "ACROBATICS", "ROVING"}
CREATE_FIELDS = {"stage_name", "act_type", "base_day_rate_cents"}


@bp.route("/performers", methods=["POST"])
def create_performer():
    require_roles("CastDirector")
    body = get_body()
    check_unknown(body, CREATE_FIELDS)
    performer = new_record()
    performer.update(
        {
            "id": new_id(),
            "_seq": next_seq(),
            "stage_name": req(body, "stage_name", "str"),
            "act_type": req(body, "act_type", "enum", enum=ACT_TYPES),
            "base_day_rate_cents": req(body, "base_day_rate_cents", "int", lo=0),
        }
    )
    store.performers[performer["id"]] = performer
    return obj_response(public_view(performer), 201)


@bp.route("/performers", methods=["GET"])
def list_performers():
    require_roles()
    limit, offset = parse_pagination()
    items = sorted_by_creation(store.performers)
    total = len(items)
    page = items[offset : offset + limit]
    return list_response([public_view(p) for p in page], limit, offset, total)


@bp.route("/performers/<pid>", methods=["GET"])
def get_performer(pid):
    require_roles()
    return obj_response(public_view(load(store.performers, pid, ERR_PERFORMER_NOT_FOUND, "performer")))
