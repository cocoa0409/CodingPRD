"""Party registry (foresters, landowners, buyers, contractors) + clock."""
from flask import Blueprint, g

from core import (
    db, new_light, pub, success, require_roles, get_body, check_known,
    f_str, f_int, bad_request, parse_iso_datetime, set_clock,
)

bp = Blueprint("party", __name__)


@bp.route("/forestry/foresters", methods=["POST"])
@require_roles("PlatformAdmin")
def create_forester():
    body = get_body()
    check_known(body, {"license_no", "full_name", "email"})
    license_no = f_str(body, "license_no")
    full_name = f_str(body, "full_name")
    email = f_str(body, "email")
    for f in db["foresters"].values():
        if f["license_no"] == license_no:
            bad_request("license_no already registered: %s" % license_no)
    ent = new_light({
        "license_no": license_no,
        "full_name": full_name,
        "email": email,
    })
    db["foresters"][ent["id"]] = ent
    return success(pub(ent), 201)


@bp.route("/forestry/landowners", methods=["POST"])
@require_roles("PlatformAdmin")
def create_landowner():
    body = get_body()
    check_known(body, {"full_name", "email", "tax_id"})
    ent = new_light({
        "full_name": f_str(body, "full_name"),
        "email": f_str(body, "email"),
        "tax_id": f_str(body, "tax_id"),
    })
    db["landowners"][ent["id"]] = ent
    return success(pub(ent), 201)


@bp.route("/forestry/buyers", methods=["POST"])
@require_roles("PlatformAdmin")
def create_buyer():
    body = get_body()
    check_known(body, {"company_name", "license_no", "prior_defaults"})
    ent = new_light({
        "company_name": f_str(body, "company_name"),
        "license_no": f_str(body, "license_no"),
        "prior_defaults": f_int(body, "prior_defaults", required=False,
                                 default=0, minv=0),
    })
    db["buyers"][ent["id"]] = ent
    return success(pub(ent), 201)


@bp.route("/forestry/contractors", methods=["POST"])
@require_roles("PlatformAdmin")
def create_contractor():
    body = get_body()
    check_known(body, {"company_name", "license_no"})
    ent = new_light({
        "company_name": f_str(body, "company_name"),
        "license_no": f_str(body, "license_no"),
    })
    db["contractors"][ent["id"]] = ent
    return success(pub(ent), 201)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("PlatformAdmin")
def set_current_utc():
    body = get_body()
    check_known(body, {"to_iso8601"})
    raw = f_str(body, "to_iso8601")
    dt = parse_iso_datetime(raw)
    set_clock(dt)
    return success({"current_utc": raw}, 200)
