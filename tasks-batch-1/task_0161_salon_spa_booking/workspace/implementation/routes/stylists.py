"""Stylist routes: create, fetch, list, update (PRD §3.1)."""
from flask import Blueprint, request

import db
from lookups import get_or_404, get_salon
from response import success
from util import stamp_create, touch, public
import validate as v
from routes.common import auth, json_body, list_response, ALL_ROLES

bp = Blueprint("stylists", __name__)

STATUSES = {"ACTIVE", "INACTIVE"}
COMP_MODELS = {"COMMISSION", "BOOTH_RENT"}


@bp.post("/stylists")
def create_stylist():
    auth(("SalonOwner",))
    body = json_body()
    v.require_object(body)

    salon_id = v.req_str(body, "salon_id")
    salon = get_salon(salon_id)  # existence + scoping

    full_name = v.req_str(body, "full_name")
    compensation_model = v.req_enum(body, "compensation_model", COMP_MODELS)
    status = v.opt_enum(body, "status", STATUSES, default="ACTIVE")
    commission_pct = v.opt_number(body, "commission_pct", default=0.40, minimum=0, maximum=1)
    booth_rent_per_appt_cents = v.opt_int(body, "booth_rent_per_appt_cents", default=1500, minimum=0)
    buffer_minutes = v.opt_int(body, "buffer_minutes", default=10, minimum=0)

    stylist = {
        "salon_id": salon["id"],
        "full_name": full_name,
        "status": status,
        "compensation_model": compensation_model,
        "commission_pct": commission_pct,
        "booth_rent_per_appt_cents": booth_rent_per_appt_cents,
        "buffer_minutes": buffer_minutes,
    }
    stamp_create(stylist)
    db.stylists[stylist["id"]] = stylist
    return success(public(stylist), status=201)


@bp.get("/stylists/<stylist_id>")
def get_stylist(stylist_id):
    auth(ALL_ROLES)
    stylist = get_or_404(db.stylists, stylist_id)
    return success(public(stylist), status=200)


@bp.get("/stylists")
def list_stylists():
    auth(ALL_ROLES)
    salon_id = request.args.get("salon_id")
    status = request.args.get("status")

    def pred(s):
        if salon_id is not None and s["salon_id"] != salon_id:
            return False
        if status is not None and s["status"] != status:
            return False
        return True

    page, meta = list_response(db.stylists, pred)
    return success(page, status=200, response_type="array", pagination=meta)


@bp.patch("/stylists/<stylist_id>")
def update_stylist(stylist_id):
    auth(("SalonOwner",))
    stylist = get_or_404(db.stylists, stylist_id)
    body = json_body()
    v.require_object(body)

    if "status" in body and body["status"] is not None:
        stylist["status"] = v.req_enum(body, "status", STATUSES)
    if "compensation_model" in body and body["compensation_model"] is not None:
        stylist["compensation_model"] = v.req_enum(body, "compensation_model", COMP_MODELS)
    if "commission_pct" in body and body["commission_pct"] is not None:
        stylist["commission_pct"] = v.req_number(body, "commission_pct", minimum=0, maximum=1)
    if "booth_rent_per_appt_cents" in body and body["booth_rent_per_appt_cents"] is not None:
        stylist["booth_rent_per_appt_cents"] = v.req_int(body, "booth_rent_per_appt_cents", minimum=0)
    if "buffer_minutes" in body and body["buffer_minutes"] is not None:
        stylist["buffer_minutes"] = v.req_int(body, "buffer_minutes", minimum=0)

    touch(stylist)  # version +1 on update (PRD §3.1)
    return success(public(stylist), status=200)
