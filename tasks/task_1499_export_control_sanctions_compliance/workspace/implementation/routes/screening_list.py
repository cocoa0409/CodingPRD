"""Screening list entry administration (ComplianceDirector only)."""

from flask import Blueprint

import db
from errors import ApiError, ERR_INVALID_STATE
from middleware import auth, get_body, no_unknown, need, v_str, v_enum, find
from response import ok
from services.screening import rescreen_sweep

bp = Blueprint("screening_list", __name__)

LIST_SOURCES = ("SDN", "DENIED_PERSONS", "ENTITY_LIST", "EMBARGOED_COUNTRY")
SEVERITIES = ("PROHIBITED", "RESTRICTED")


@bp.post("/compliance/screening-list-entries")
def create_entry():
    auth("ComplianceDirector")
    body = get_body()
    no_unknown(body, {"list_source", "match_name", "country_code", "severity"})
    list_source = v_enum(need(body, "list_source"), "list_source", LIST_SOURCES)
    match_name = v_str(need(body, "match_name"), "match_name")
    country_code = v_str(need(body, "country_code"), "country_code")
    severity = v_enum(need(body, "severity"), "severity", SEVERITIES)
    entry = {
        "list_source": list_source,
        "match_name": match_name,
        "country_code": country_code,
        "severity": severity,
        "status": "ACTIVE",
    }
    db.stamp_new(entry)
    db.LIST_ENTRIES[entry["id"]] = entry
    # Born ACTIVE: triggers the same re-screen sweep as re-activation.
    rescreen_sweep(entry)
    return ok(db.pub(entry), "object", 201)


@bp.post("/compliance/screening-list-entries/<eid>/set-status")
def set_entry_status(eid):
    auth("ComplianceDirector")
    entry = find(db.LIST_ENTRIES, eid, "ScreeningListEntry")
    body = get_body()
    no_unknown(body, {"to"})
    to = v_enum(need(body, "to"), "to", ("ACTIVE", "INACTIVE"))
    if to == "ACTIVE":
        if entry["status"] != "INACTIVE":
            raise ApiError(ERR_INVALID_STATE, "Entry is not INACTIVE", 409)
        entry["status"] = "ACTIVE"
        db.touch(entry)
        rescreen_sweep(entry)
    else:  # INACTIVE
        if entry["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, "Entry is not ACTIVE", 409)
        entry["status"] = "INACTIVE"
        db.touch(entry)
    return ok(db.pub(entry), "object", 200)
