"""Service routes: create, fetch, list (PRD §3.1)."""
from flask import Blueprint, request

import db
from lookups import get_or_404, get_salon
from response import success
from util import stamp_create, public
import validate as v
from routes.common import auth, json_body, list_response, ALL_ROLES

bp = Blueprint("services", __name__)


@bp.post("/services")
def create_service():
    auth(("SalonOwner",))
    body = json_body()
    v.require_object(body)

    salon_id = v.req_str(body, "salon_id")
    salon = get_salon(salon_id)

    name = v.req_str(body, "name")
    duration_minutes = v.req_int(body, "duration_minutes", minimum=1)
    base_price_cents = v.req_int(body, "base_price_cents", minimum=0)
    deposit_pct = v.opt_number(body, "deposit_pct", default=0.0, minimum=0, maximum=1)
    requires_room = v.opt_bool(body, "requires_room", default=False)

    service = {
        "salon_id": salon["id"],
        "name": name,
        "duration_minutes": duration_minutes,
        "base_price_cents": base_price_cents,
        "deposit_pct": deposit_pct,
        "requires_room": requires_room,
    }
    stamp_create(service)
    db.services[service["id"]] = service
    return success(public(service), status=201)


@bp.get("/services/<service_id>")
def get_service(service_id):
    auth(ALL_ROLES)
    service = get_or_404(db.services, service_id)
    return success(public(service), status=200)


@bp.get("/services")
def list_services():
    auth(ALL_ROLES)
    salon_id = request.args.get("salon_id")

    def pred(s):
        if salon_id is not None and s["salon_id"] != salon_id:
            return False
        return True

    page, meta = list_response(db.services, pred)
    return success(page, status=200, response_type="array", pagination=meta)
