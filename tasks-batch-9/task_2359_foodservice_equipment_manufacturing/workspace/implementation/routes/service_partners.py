"""ServicePartner endpoints (PRD Section 3.9)."""
from flask import Blueprint

import validate
from db import db, insert, touch, ordered
from errors import ApiError
from middleware import authorize, partner_scope
from response import ok, created, ok_list
from routes.helpers import find, filter_by, unique_code
from services import calc, derive

bp = Blueprint("service_partners", __name__)

STATUSES = ("APPLIED", "PROVISIONAL", "AUTHORIZED", "SUSPENDED", "TERMINATED")
ACTIONS = ("PROVISION", "AUTHORIZE", "SUSPEND", "REINSTATE", "TERMINATE")
REQUIRED_FROM = {
    "PROVISION": ("APPLIED",),
    "AUTHORIZE": ("PROVISIONAL",),
    "SUSPEND": ("AUTHORIZED",),
    "REINSTATE": ("SUSPENDED",),
    "TERMINATE": ("PROVISIONAL", "SUSPENDED"),
}
NEXT_STATUS = {
    "PROVISION": "PROVISIONAL",
    "AUTHORIZE": "AUTHORIZED",
    "SUSPEND": "SUSPENDED",
    "REINSTATE": "AUTHORIZED",
    "TERMINATE": "TERMINATED",
}


@bp.post("/service-partners")
def create_partner():
    authorize("ChannelManager", "PlatformAdmin")
    payload = validate.body()
    partner_code = validate.string_field(payload, "partner_code", min_len=1, max_len=32)
    name = validate.string_field(payload, "name", min_len=1, max_len=200)
    region_code = validate.string_field(payload, "region_code", min_len=1, max_len=32)
    parts_stocking_level = validate.enum_field(payload, "parts_stocking_level",
                                              calc.PARTS_STOCKING_LEVELS)

    unique_code(db.service_partners, partner_code=partner_code)

    partner = insert(db.service_partners, {
        "partner_code": partner_code,
        "name": name,
        "region_code": region_code,
        "parts_stocking_level": parts_stocking_level,
        "status": "APPLIED",
        "authorized_model_ids": [],
    })
    return created(partner)


@bp.get("/service-partners")
def list_partners():
    authorize("ChannelManager", "WarrantyAdjudicator", "PlatformAdmin")
    limit, offset = validate.pagination()
    region_code = validate.str_arg("region_code")
    status = validate.enum_arg("status", STATUSES)

    items = ordered(db.service_partners)
    items = filter_by(items, "region_code", region_code)
    items = filter_by(items, "status", status)
    return ok_list(items, limit, offset)


@bp.get("/service-partners/<partner_id>")
def get_partner(partner_id):
    actor = authorize("ChannelManager", "WarrantyAdjudicator", "ServicePartnerUser",
                      "PlatformAdmin")
    partner_scope(actor, partner_id)
    partner = find(db.service_partners, partner_id, "ERR_CHANNEL_RESOURCE_NOT_FOUND")
    return ok(partner)


@bp.post("/service-partners/<partner_id>/authorization")
def authorization(partner_id):
    authorize("ChannelManager", "PlatformAdmin")
    payload = validate.body()
    action = validate.enum_field(payload, "action", ACTIONS)

    partner = find(db.service_partners, partner_id, "ERR_CHANNEL_RESOURCE_NOT_FOUND")

    if partner["status"] not in REQUIRED_FROM[action]:
        raise ApiError("ERR_CHANNEL_STATE_INVALID",
                       "%s is not permitted from %s" % (action, partner["status"]))

    if action == "TERMINATE":
        open_claims = [c for c in db.warranty_claims.values()
                       if c["service_partner_id"] == partner["id"] and c["status"] == "SUBMITTED"]
        if open_claims:
            raise ApiError("ERR_CHANNEL_STATE_INVALID",
                           "the partner still has %d SUBMITTED claim(s)" % len(open_claims))

    if action == "PROVISION":
        passed = [c for c in derive.certifications_for_partner(partner["id"])
                  if c["status"] == "PASSED"]
        if not passed:
            raise ApiError("ERR_INSUFFICIENT_CERTIFIED_TECHNICIANS",
                           "the partner has no PASSED technician certification")
    elif action in ("AUTHORIZE", "REINSTATE"):
        if not derive.compute_authorized_model_ids(partner):
            raise ApiError("ERR_INSUFFICIENT_CERTIFIED_TECHNICIANS",
                           "no model has %d unexpired PASSED certifications"
                           % calc.MIN_CERTIFIED_TECHS_PER_MODEL)

    if action == "AUTHORIZE" and partner["parts_stocking_level"] != "FULL":
        raise ApiError("ERR_PARTS_STOCKING_INSUFFICIENT",
                       "an authorized partner must carry the FULL parts kit")

    partner["status"] = NEXT_STATUS[action]
    touch(partner)

    if action == "TERMINATE":
        partner["authorized_model_ids"] = []
    else:
        derive.refresh_partner_authority(partner)
    return ok(partner)
