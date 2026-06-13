"""Package routes: create, fetch, list (PRD §3.1)."""
from flask import Blueprint, request

import db
from lookups import get_or_404, get_salon, get_scoped
from response import success
from util import stamp_create, public
import validate as v
from routes.common import auth, json_body, list_response

bp = Blueprint("packages", __name__)


@bp.post("/packages")
def create_package():
    auth(("SalonOwner",))
    body = json_body()
    v.require_object(body)

    salon_id = v.req_str(body, "salon_id")
    salon = get_salon(salon_id)

    service_id = v.req_str(body, "service_id")
    # The package's service must belong to the same salon.
    service = get_scoped(db.services, service_id, salon["id"])

    session_count = v.req_int(body, "session_count", minimum=1)
    price_cents = v.req_int(body, "price_cents", minimum=0)

    package = {
        "salon_id": salon["id"],
        "service_id": service["id"],
        "session_count": session_count,
        "price_cents": price_cents,
    }
    stamp_create(package)
    db.packages[package["id"]] = package
    return success(public(package), status=201)


@bp.get("/packages/<package_id>")
def get_package(package_id):
    auth(("SalonOwner", "FrontDesk", "Client"))
    package = get_or_404(db.packages, package_id)
    return success(public(package), status=200)


@bp.get("/packages")
def list_packages():
    auth(("SalonOwner", "FrontDesk", "Client"))
    salon_id = request.args.get("salon_id")
    service_id = request.args.get("service_id")

    def pred(p):
        if salon_id is not None and p["salon_id"] != salon_id:
            return False
        if service_id is not None and p["service_id"] != service_id:
            return False
        return True

    page, meta = list_response(db.packages, pred)
    return success(page, status=200, response_type="array", pagination=meta)
