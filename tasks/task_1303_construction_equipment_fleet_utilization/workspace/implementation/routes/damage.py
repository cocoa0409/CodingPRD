from flask import Blueprint, request

from db import new_common, pub, store, touch
from errors import ApiError, invalid_request, invalid_state, not_found
from logic import damage_charge
from middleware import require_roles
from response import ok, ok_list
from util import (as_bool, as_line_items, as_str, body_json, check_body_fks,
                  paginate, req_field)

bp = Blueprint("damage", __name__)
READERS = ("FleetAdmin", "ProjectManager", "Mechanic", "Dispatcher")


def get_report_or_404(did):
    d = store.damage_reports.get(did)
    if d is None:
        raise not_found("DamageReport")
    return d


@bp.post("/fleet/damage-reports")
@require_roles("FleetAdmin")
def create_damage_report():
    body = body_json()
    # priority 4: body FK existence
    check_body_fks([(store.equipment, body, "equipment_id"),
                    (store.projects, body, "project_id")])
    # priority 5: well-formedness
    equipment_id = as_str(req_field(body, "equipment_id"), "equipment_id")
    project_id = as_str(req_field(body, "project_id"), "project_id")
    description = as_str(req_field(body, "description"), "description", allow_empty=True)
    abuse = as_bool(req_field(body, "abuse_flag"), "abuse_flag")
    items = as_line_items(req_field(body, "line_items"))
    # priority 12: project alignment with the unit's current rental
    e = store.equipment[equipment_id]
    if e["current_project_id"] != project_id:
        raise ApiError("ERR_PROJECT_MISMATCH", 422,
                       "project_id must equal the equipment's current_project_id at filing")
    d = new_common()
    d.update({
        "equipment_id": equipment_id,
        "project_id": project_id,
        "description": description,
        "abuse_flag": abuse,
        "line_items": items,
        "status": "FILED",
        "assessed_charge_cents": None,
        "confirmed_charge_cents": None,
        "dispute_note": None,
    })
    store.damage_reports[d["id"]] = d
    return ok(pub(d), "object", 201)


@bp.get("/fleet/damage-reports/<did>")
@require_roles(*READERS)
def get_damage_report(did):
    return ok(pub(get_report_or_404(did)), "object", 200)


@bp.get("/fleet/damage-reports")
@require_roles(*READERS)
def list_damage_reports():
    rows = list(store.damage_reports.values())
    for f in ("equipment_id", "project_id", "status"):
        v = request.args.get(f)
        if v is not None:
            rows = [d for d in rows if d.get(f) == v]
    items, meta = paginate(rows)
    return ok_list([pub(d) for d in items], meta)


@bp.post("/fleet/damage-reports/<did>/assess")
@require_roles("FleetAdmin")
def assess(did):
    d = get_report_or_404(did)
    if d["status"] != "FILED":
        raise invalid_state("Only a FILED damage report can be assessed")
    d["assessed_charge_cents"] = damage_charge(d["line_items"], d["abuse_flag"])
    d["status"] = "ASSESSED"
    touch(d)
    return ok(pub(d), "object", 200)


@bp.post("/fleet/damage-reports/<did>/dispute")
@require_roles("ProjectManager")
def dispute(did):
    d = get_report_or_404(did)
    body = body_json()
    note = as_str(req_field(body, "dispute_note"), "dispute_note")
    if d["status"] != "ASSESSED":
        raise invalid_state("Only an ASSESSED damage report can be disputed")
    d["dispute_note"] = note
    d["status"] = "DISPUTED"
    touch(d)
    return ok(pub(d), "object", 200)


@bp.post("/fleet/damage-reports/<did>/reassess")
@require_roles("FleetAdmin")
def reassess(did):
    d = get_report_or_404(did)
    body = body_json()
    items = as_line_items(req_field(body, "line_items"))
    expected = req_field(body, "expected_damage_report_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise invalid_request("expected_damage_report_version must be an integer")
    if d["status"] != "DISPUTED":
        raise invalid_state("Only a DISPUTED damage report can be reassessed")
    if expected != d["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_damage_report_version does not match the report version")
    d["line_items"] = items
    d["assessed_charge_cents"] = damage_charge(items, d["abuse_flag"])
    d["status"] = "ASSESSED"
    touch(d)
    return ok(pub(d), "object", 200)


@bp.post("/fleet/damage-reports/<did>/confirm")
@require_roles("FleetAdmin")
def confirm(did):
    d = get_report_or_404(did)
    if d["status"] != "ASSESSED":
        raise invalid_state("Only an ASSESSED damage report can be confirmed")
    p = store.projects[d["project_id"]]
    # budget guard (inclusive cap), checked before the project-open gate
    if p["billed_total_cents"] + d["assessed_charge_cents"] > p["equipment_budget_cents"]:
        raise ApiError("ERR_BUDGET_EXCEEDED", 422,
                       "Confirmed charge would exceed the project equipment budget")
    if p["status"] != "OPEN":
        raise ApiError("ERR_PROJECT_NOT_OPEN", 409, "Project must be OPEN for damage confirm")
    d["confirmed_charge_cents"] = d["assessed_charge_cents"]
    d["status"] = "CONFIRMED"
    touch(d)
    p["billed_total_cents"] += d["confirmed_charge_cents"]
    touch(p)
    return ok(pub(d), "object", 200)


@bp.post("/fleet/damage-reports/<did>/void")
@require_roles("FleetAdmin")
def void(did):
    d = get_report_or_404(did)
    if d["status"] not in ("FILED", "ASSESSED"):
        raise invalid_state("Only a FILED or ASSESSED damage report can be voided")
    d["status"] = "VOIDED"
    touch(d)
    return ok(pub(d), "object", 200)
