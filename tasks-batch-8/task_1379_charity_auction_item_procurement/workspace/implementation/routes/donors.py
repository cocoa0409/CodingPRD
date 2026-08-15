"""Donor routes."""

from flask import Blueprint

import middleware as mw
import response
from db import stores

bp = Blueprint("donors", __name__)

READ = mw.ALL_ROLES


@bp.post("/donors")
def create_donor():
    mw.require_auth(["ProcurementOfficer"])
    body = mw.get_json_body()
    rec = mw.new_record()
    rec["full_name"] = mw.require_string(body, "full_name")
    rec["email"] = mw.require_string(body, "email")
    rec["donor_type"] = mw.require_enum(body, "donor_type", {"INDIVIDUAL", "BUSINESS"})
    rec["tax_id"] = mw.optional_string(body, "tax_id")
    stores["donors"][rec["id"]] = rec
    return response.success_object(mw.serialize(rec), 201)


@bp.get("/donors/<rid>")
def get_donor(rid):
    mw.require_auth(READ)
    return response.success_object(mw.serialize(mw.get_or_404("donors", rid)))


@bp.get("/donors/<rid>/solicitations")
def list_donor_solicitations(rid):
    mw.require_auth(READ)
    donor = mw.get_or_404("donors", rid)
    limit, offset = mw.parse_pagination()
    items = [s for s in stores["solicitations"].values() if s["donor_id"] == donor["id"]]
    page, total = mw.sort_and_page(items, limit, offset)
    return response.success_array([mw.serialize(s) for s in page], limit, offset, total)
