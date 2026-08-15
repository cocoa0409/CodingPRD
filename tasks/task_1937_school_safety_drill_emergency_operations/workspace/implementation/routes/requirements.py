"""DrillTypeRequirement endpoints (PRD 3.1, 2.7 OCC)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_REQUIREMENT_EXISTS, ERR_STALE_VERSION,
)
from middleware import authorized, ALL_ROLES, ROLE_COORDINATOR
from response import success_object
from services.core import (
    new_record, public, refresh_site, stale_all_draft_reports, apply_changes,
)
from validate import (
    get_body, reject_unknown, req_enum, req_int, opt_int, opt_str, req_str,
)
from routes.helpers import check_site_fk, get_path, list_query

bp = Blueprint("requirements", __name__)

DRILL_TYPES = ["FIRE", "LOCKDOWN", "EVACUATION", "SHELTER_IN_PLACE", "EARTHQUAKE"]


@bp.post("/drill-requirements")
def create_requirement():
    authorized([ROLE_COORDINATOR])
    body = get_body()
    check_site_fk(body)  # priority 3
    reject_unknown(body, ["site_id", "drill_type", "required_per_year",
                          "min_spacing_days", "target_evac_seconds", "notes"])
    site_id = req_str(body, "site_id")
    drill_type = req_enum(body, "drill_type", DRILL_TYPES)
    required_per_year = req_int(body, "required_per_year", minimum=1)
    min_spacing_days = req_int(body, "min_spacing_days", minimum=0)
    target_evac_seconds = req_int(body, "target_evac_seconds", minimum=1)
    notes = opt_str(body, "notes")

    # priority 9: one requirement per (site, drill_type)
    for r in db["requirements"].values():
        if r["site_id"] == site_id and r["drill_type"] == drill_type:
            raise_error(ERR_REQUIREMENT_EXISTS,
                        "a requirement already exists for this site and drill type")

    rec = new_record("requirements", {
        "site_id": site_id,
        "drill_type": drill_type,
        "required_per_year": required_per_year,
        "min_spacing_days": min_spacing_days,
        "target_evac_seconds": target_evac_seconds,
        "notes": notes,
    })
    stale_all_draft_reports(site_id)
    refresh_site(site_id)
    return success_object(public(rec), 201)


@bp.get("/sites/<rid>/drill-requirements")
def list_requirements(rid):
    authorized(ALL_ROLES)
    get_path("sites", rid)
    filters = {"site_id": rid, "drill_type": request.args.get("drill_type")}
    return list_query("requirements", filters)


@bp.put("/drill-requirements/<rid>")
def update_requirement(rid):
    authorized([ROLE_COORDINATOR])
    rec = get_path("requirements", rid)
    body = get_body()
    reject_unknown(body, ["required_per_year", "min_spacing_days",
                          "target_evac_seconds", "notes", "expected_requirement_version"])
    required_per_year = opt_int(body, "required_per_year", minimum=1)
    min_spacing_days = opt_int(body, "min_spacing_days", minimum=0)
    target_evac_seconds = opt_int(body, "target_evac_seconds", minimum=1)
    notes = opt_str(body, "notes")
    expected = req_int(body, "expected_requirement_version")

    # priority 10: OCC
    if expected != rec["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_requirement_version does not match the current version")

    changes = {}
    if required_per_year is not None:
        changes["required_per_year"] = required_per_year
    if min_spacing_days is not None:
        changes["min_spacing_days"] = min_spacing_days
    if target_evac_seconds is not None:
        changes["target_evac_seconds"] = target_evac_seconds
    if "notes" in body:
        changes["notes"] = notes
    # A successful update always increments version, even a no-op payload.
    apply_changes(rec, changes, force=True)
    stale_all_draft_reports(rec["site_id"])
    refresh_site(rec["site_id"])
    return success_object(public(rec))
