"""Infusion chairs (PRD 3.7)."""
from flask import Blueprint

from db import db, next_seq
from middleware import authorized
from response import success_object
from routes.helpers import SITE_TYPES, get_chair, list_response
from serializers import serialize
from util import new_id, CLOCK
from validate import get_body, req_str, req_enum, opt_int

bp = Blueprint("chairs", __name__)

CHAIR_READ_ROLES = ["PolicyAdmin", "Scheduler", "AuthCoordinator"]


@bp.post("/infusion/infusion-chairs")
def create_chair():
    authorized(["PolicyAdmin"])
    body = get_body()
    site_type = req_enum(body, "site_type", sorted(SITE_TYPES))
    label = req_str(body, "label")
    turnover_buffer_minutes = opt_int(body, "turnover_buffer_minutes", 15)
    now = CLOCK.now()
    rec = {
        "id": new_id(),
        "site_type": site_type,
        "label": label,
        "turnover_buffer_minutes": turnover_buffer_minutes,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db["infusion_chairs"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.get("/infusion/infusion-chairs/<cid>")
def read_chair(cid):
    authorized(CHAIR_READ_ROLES)
    return success_object(serialize(get_chair(cid)))


@bp.get("/infusion/infusion-chairs/<cid>/appointments")
def list_chair_appointments(cid):
    authorized(CHAIR_READ_ROLES)
    get_chair(cid)
    items = [a for a in db["appointments"].values() if a["chair_id"] == cid]
    return list_response(items)
