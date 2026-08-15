from flask import Blueprint, request

from db import DB
from errors import err_not_found, err_invalid_request
from middleware import get_actor, require_role
from response import success_object
from serializers import serialize_vendor
from services.ledger import touch_entity
from services.vendor_perf import recompute_vendor

bp = Blueprint("vendors", __name__)

ALL_ROLES = ["MobilityCoordinator", "FinanceSpecialist", "ProgramManager", "Employee", "Vendor"]


@bp.route("/vendors", methods=["POST"])
def create_vendor():
    actor = get_actor()
    require_role(actor, ["MobilityCoordinator"])
    payload = request.get_json(silent=True) or {}
    name = payload.get("name")
    if not isinstance(name, str) or not name:
        raise err_invalid_request("name must be a non-empty string")
    regions = payload.get("service_regions")
    if not isinstance(regions, list) or not all(isinstance(r, str) for r in regions):
        raise err_invalid_request("service_regions must be an array of strings")

    with DB.lock:
        now = DB.now()
        v = {
            "id": DB.new_id(),
            "name": name,
            "service_regions": list(regions),
            "status": "ACTIVE",
            "rating_count": 0,
            "rating_sum": 0,
            "avg_rating_lifetime": None,
            "avg_rating_rolling_12m": None,
            "completed_moves": 0,
            "created_at": now,
            "updated_at": now,
            "version": 0,
            "_seq": DB.next_seq(),
        }
        DB.vendors[v["id"]] = v
        return success_object(serialize_vendor(v), status=201)


@bp.route("/vendors/<id>", methods=["GET"])
def get_vendor(id):
    actor = get_actor()
    require_role(actor, ALL_ROLES)
    with DB.lock:
        v = DB.vendors.get(id)
        if v is None:
            raise err_not_found("Vendor not found")
        # recompute rolling aggregates against the current logical clock on read
        recompute_vendor(id)
        return success_object(serialize_vendor(v))


@bp.route("/vendors/<id>/suspend", methods=["POST"])
def suspend_vendor(id):
    actor = get_actor()
    require_role(actor, ["MobilityCoordinator"])
    with DB.lock:
        v = DB.vendors.get(id)
        if v is None:
            raise err_not_found("Vendor not found")
        if v["status"] == "SUSPENDED":
            # Idempotent-ish: spec doesn't declare; treat re-suspend as a state violation
            # but PRD lists no ERR for repeat suspend. We keep state and bump version.
            pass
        v["status"] = "SUSPENDED"
        touch_entity(v)
        return success_object(serialize_vendor(v))
