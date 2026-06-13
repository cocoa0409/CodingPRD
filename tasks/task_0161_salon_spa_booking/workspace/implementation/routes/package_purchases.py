"""PackagePurchase routes: purchase, fetch, list (PRD §3.2)."""
from flask import Blueprint, request

import db
from lookups import get_or_404
from response import success
from util import stamp_create, public
import validate as v
from middleware import require_owns_client
from routes.common import auth, json_body, list_response

bp = Blueprint("package_purchases", __name__)


@bp.post("/package-purchases")
def purchase():
    caller = auth(("SalonOwner", "FrontDesk", "Client"))
    body = json_body()
    v.require_object(body)

    client_id = v.req_str(body, "client_id")
    # A Client may only buy a package for themselves (PRD §2.1).
    require_owns_client(caller, client_id)
    package_id = v.req_str(body, "package_id")
    client = get_or_404(db.clients, client_id)
    package = get_or_404(db.packages, package_id)

    pp = {
        "client_id": client["id"],
        "package_id": package["id"],
        "sessions_remaining": package["session_count"],
        "status": "ACTIVE",
    }
    stamp_create(pp)
    db.package_purchases[pp["id"]] = pp
    return success(public(pp), status=201)


@bp.get("/package-purchases/<pp_id>")
def get_purchase(pp_id):
    auth(("SalonOwner", "FrontDesk", "Client"))
    pp = get_or_404(db.package_purchases, pp_id)
    return success(public(pp), status=200)


@bp.get("/package-purchases")
def list_purchases():
    auth(("SalonOwner", "FrontDesk", "Client"))
    client_id = request.args.get("client_id")
    package_id = request.args.get("package_id")

    def pred(p):
        if client_id is not None and p["client_id"] != client_id:
            return False
        if package_id is not None and p["package_id"] != package_id:
            return False
        return True

    page, meta = list_response(db.package_purchases, pred)
    return success(page, status=200, response_type="array", pagination=meta)
