"""Interop policy endpoints."""
from flask import Blueprint, request

from ..auth import require_roles
from ..errors import raise_api_error
from ..responses import paginate, parse_pagination, success_array, success_object
from ..serializers import serialize_interop
from ..store import store
from ..validators import AGENCIES, optional_int, require_enum, require_json


interop_bp = Blueprint("interop", __name__)


@interop_bp.route("/interop-policies", methods=["POST"])
@require_roles("AgencyAdmin")
def create_policy():
    payload = require_json(request.get_json(silent=True))
    home_agency = require_enum(payload, "home_agency", AGENCIES)
    gantry_agency = require_enum(payload, "gantry_agency", AGENCIES)
    surcharge_bps = optional_int(payload, "surcharge_bps", 0, 5000, default=0)
    discount_bps = optional_int(payload, "discount_bps", 0, 5000, default=0)
    policy = store.stamp_event({
        "home_agency": home_agency,
        "gantry_agency": gantry_agency,
        "surcharge_bps": surcharge_bps,
        "discount_bps": discount_bps,
    })
    store.interop_policies[policy["id"]] = policy
    return success_object(serialize_interop(policy), status=201)


@interop_bp.route("/interop-policies", methods=["GET"])
@require_roles("AgencyAdmin", "GantryOperator")
def list_policies():
    limit, offset = parse_pagination(request.args)
    home = request.args.get("home_agency")
    gantry = request.args.get("gantry_agency")
    if home is not None and home not in AGENCIES:
        raise_api_error("ERR_VALIDATION", "Invalid home_agency filter.")
    if gantry is not None and gantry not in AGENCIES:
        raise_api_error("ERR_VALIDATION", "Invalid gantry_agency filter.")
    rows = list(store.interop_policies.values())
    if home:
        rows = [r for r in rows if r["home_agency"] == home]
    if gantry:
        rows = [r for r in rows if r["gantry_agency"] == gantry]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return success_array([serialize_interop(r) for r in page], limit, offset, total)
