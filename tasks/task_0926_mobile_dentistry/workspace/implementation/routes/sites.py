"""Sites and site holds."""

from flask import Blueprint

import cascades
import clock
import gates
import serializers
import store
import validation as v
from constants import ENUM_HOLD_TYPE, ENUM_ROSTER_DISCLOSURE_LEVEL, ENUM_SITE_TYPE
from envelope import array_response, object_response
from errors import ApiError

bp = Blueprint("sites", __name__)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/sites
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/sites", methods=["POST"])
def create_site():
    v.authenticate(["ProgramAdmin"])
    body = v.body()
    name = v.req_string(body, "name", min_len=1, max_len=160)
    v.enum_type_check(body, "site_type", required=True)
    state_code = v.req_state_code(body, "state_code")
    v.enum_type_check(body, "roster_disclosure_level")
    facility_contact_name = v.opt_string(body, "facility_contact_name")

    site_type = v.check_enum(body, "site_type", ENUM_SITE_TYPE)
    disclosure = v.check_enum(body, "roster_disclosure_level", ENUM_ROSTER_DISCLOSURE_LEVEL)

    row = store.insert("sites", {
        "name": name,
        "site_type": site_type,
        "state_code": state_code,
        "status": "ACTIVE",
        "roster_disclosure_level": disclosure or "SUMMARY_ONLY",
        "facility_contact_name": facility_contact_name,
    })
    v.mark_minted(row)
    return object_response(serializers.site(row), 201)


# --------------------------------------------------------------------------
# GET /mobile-dentistry/sites
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/sites", methods=["GET"])
def list_sites():
    v.authenticate(["ProgramAdmin", "SiteCoordinator", "BillingSpecialist"])
    limit, offset = v.pagination()
    rows = v.apply_filters(store.all_rows("sites"), {"site_type": "site_type", "status": "status"})
    page, total = v.paginate(rows, limit, offset)
    return array_response(serializers.many(serializers.site, page), limit, offset, total)


# --------------------------------------------------------------------------
# GET /mobile-dentistry/sites/{id}
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/sites/<site_id>", methods=["GET"])
def read_site(site_id):
    v.authenticate([
        "ProgramAdmin", "SiteCoordinator", "BillingSpecialist",
        "FieldDentist", "FieldHygienist", "DentalAssistant",
    ])
    row = v.path_row("sites", site_id)
    return object_response(serializers.site(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/site-holds
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/site-holds", methods=["POST"])
def create_site_hold():
    v.authenticate(["ProgramAdmin"])
    body = v.body()
    site = v.fk_row(body, "site_id", "sites")

    v.need(body, "site_id")
    if not isinstance(body.get("site_id"), str):
        raise ApiError("ERR_VALIDATION", "Field 'site_id' must be a string.")
    v.enum_type_check(body, "hold_type", required=True)
    starts_at = v.req_instant(body, "starts_at")
    ends_at = v.req_instant(body, "ends_at")
    reason = v.opt_string(body, "reason")
    if not starts_at < ends_at:
        raise ApiError("ERR_VALIDATION", "starts_at must be strictly before ends_at.")

    hold_type = v.check_enum(body, "hold_type", ENUM_HOLD_TYPE)

    row = store.insert("site_holds", {
        "site_id": site["id"],
        "hold_type": hold_type,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "hold_status": "ACTIVE",
        "reason": reason,
        "released_at": None,
        "blocked_visit_count": 0,
    })
    v.mark_minted(row)
    cascades.run_site_hold_cascade(row, site)
    return object_response(serializers.site_hold(row), 201)


# --------------------------------------------------------------------------
# GET /mobile-dentistry/site-holds
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/site-holds", methods=["GET"])
def list_site_holds():
    v.authenticate(["ProgramAdmin", "SiteCoordinator"])
    limit, offset = v.pagination()
    rows = v.apply_filters(
        store.all_rows("site_holds"),
        {"site_id": "site_id", "hold_status": "hold_status"},
    )
    page, total = v.paginate(rows, limit, offset)
    return array_response(serializers.many(serializers.site_hold, page), limit, offset, total)


# --------------------------------------------------------------------------
# GET /mobile-dentistry/site-holds/{id}
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/site-holds/<hold_id>", methods=["GET"])
def read_site_hold(hold_id):
    v.authenticate(["ProgramAdmin", "SiteCoordinator"])
    row = v.path_row("site_holds", hold_id)
    return object_response(serializers.site_hold(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/site-holds/{id}/release
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/site-holds/<hold_id>/release", methods=["POST"])
def release_site_hold(hold_id):
    v.authenticate(["ProgramAdmin"])
    row = v.path_row("site_holds", hold_id)
    if row["hold_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    site = store.get("sites", row["site_id"])

    row["hold_status"] = "RELEASED"
    row["released_at"] = clock.now()
    v.touch(row)
    cascades.run_site_hold_release_cascade(row, site)
    return object_response(serializers.site_hold(row), 200)
