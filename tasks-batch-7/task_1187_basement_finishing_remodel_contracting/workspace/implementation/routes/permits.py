"""Permit endpoints (PRD §3.4)."""
from flask import Blueprint

from db import stores, now_ts, clock_now
from errors import fail
from response import ok
from serializers import ser_permit
from services import (
    PERMIT_TERMINAL, egress_r1, ceiling_r2_r3, advance_project, touch,
)
from validation import auth, require_role, get_body, v_str, v_num, v_int, v_arr, v_enum, v_item_object
from routes.common import (
    project_or_404, get_or_404, require_contractor_owner, new_entity, list_response,
)

bp = Blueprint("permits", __name__)

DECISION_OUTCOMES = {"ISSUED", "CORRECTIONS_REQUIRED"}


def _windows_shape(body):
    windows = v_arr(body, "windows")
    for w in windows:
        v_item_object(w, "windows")
        v_num(w, "net_clear_sqft")
        v_num(w, "sill_height_in")
    return windows


def _stale(project, permit):
    """Priority 11: the pinned pair must still equal the project's currently
    APPROVED package identity and revision_number."""
    approved_id = project["approved_design_id"]
    if approved_id is None or approved_id != permit["pinned_design_id"]:
        return True
    pkg = stores["designs"].get(approved_id)
    if pkg is None or pkg["status"] != "APPROVED":
        return True
    return pkg["revision_number"] != permit["pinned_design_revision"]


@bp.post("/api/projects/<project_id>/permits")
def create_permit(project_id):
    role, uid = auth()
    require_role(role, "Contractor")
    project = project_or_404(project_id)
    require_contractor_owner(project, uid)
    body = get_body()
    if project["status"] != "PERMITTING":
        fail("ERR_PROJECT_STATE_FORBIDS", "Permits open only while the project is PERMITTING")
    bedroom_count = v_int(body, "bedroom_count")
    windows = _windows_shape(body)
    ceiling_height_in = v_num(body, "ceiling_height_in")
    finished_area_sqft = v_int(body, "finished_area_sqft")
    low_area_sqft = v_int(body, "low_area_sqft")
    prohibited_area_sqft = v_int(body, "prohibited_area_sqft")
    # Pin the project's currently APPROVED package identity and revision.
    pinned_id = project["approved_design_id"]
    pinned_rev = None
    if pinned_id is not None:
        pkg = stores["designs"].get(pinned_id)
        pinned_rev = pkg["revision_number"] if pkg is not None else None
    e = new_entity({
        "project_id": project_id,
        "bedroom_count": bedroom_count,
        "windows": windows,
        "ceiling_height_in": ceiling_height_in,
        "finished_area_sqft": finished_area_sqft,
        "low_area_sqft": low_area_sqft,
        "prohibited_area_sqft": prohibited_area_sqft,
        "pinned_design_id": pinned_id,
        "pinned_design_revision": pinned_rev,
        "egress_compliant": None,
        "ceiling_compliant": None,
        "amendment_count": 0,
        "issued_at": None,
        "_issued_date": None,
        "status": "DRAFT",
    })
    stores["permits"][e["id"]] = e
    return ok(ser_permit(e), 201)


@bp.get("/api/projects/<project_id>/permits")
def list_permits(project_id):
    auth()
    project_or_404(project_id)
    items = [p for p in stores["permits"].values() if p["project_id"] == project_id]
    return list_response(items, ser_permit)


@bp.post("/api/permits/<permit_id>/submit")
def submit_permit(permit_id):
    role, uid = auth()
    require_role(role, "Contractor")
    p = get_or_404("permits", permit_id, "Permit")
    project = project_or_404(p["project_id"])
    require_contractor_owner(project, uid)
    if p["status"] in PERMIT_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "Permit is terminal and refuses further mutation")
    if p["status"] not in ("DRAFT", "CORRECTIONS_REQUIRED"):
        fail("ERR_INVALID_STATE", "Only a DRAFT or CORRECTIONS_REQUIRED permit can be submitted")
    # Priority 11: pinned-revision freshness first.
    if _stale(project, p):
        fail("ERR_DESIGN_REVISION_STALE", "Pinned design revision no longer matches the APPROVED package")
    # Priority 12: egress R1 evaluated and reported before ceiling rules.
    r1 = egress_r1(p["bedroom_count"], p["windows"])
    p["egress_compliant"] = r1
    if not r1:
        p["ceiling_compliant"] = ceiling_r2_r3(
            p["finished_area_sqft"], p["low_area_sqft"], p["prohibited_area_sqft"]
        )
        touch(p)
        fail("ERR_EGRESS_NONCOMPLIANT", "Insufficient compliant egress windows for bedroom_count")
    # Priority 13: ceiling R2 + R3.
    ceil_ok = ceiling_r2_r3(p["finished_area_sqft"], p["low_area_sqft"], p["prohibited_area_sqft"])
    p["ceiling_compliant"] = ceil_ok
    if not ceil_ok:
        touch(p)
        fail("ERR_CEILING_NONCOMPLIANT", "Ceiling rules R2/R3 failed")
    if p["status"] == "CORRECTIONS_REQUIRED":
        p["amendment_count"] += 1
    p["status"] = "UNDER_REVIEW"
    touch(p)
    return ok(ser_permit(p))


@bp.post("/api/permits/<permit_id>/record-decision")
def record_decision(permit_id):
    role, uid = auth()
    require_role(role, "Inspector")
    p = get_or_404("permits", permit_id, "Permit")
    project = project_or_404(p["project_id"])
    if p["status"] in PERMIT_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "Permit is terminal and refuses further mutation")
    if p["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "Only an UNDER_REVIEW permit can receive a decision")
    body = get_body()
    outcome = v_enum(body, "outcome", DECISION_OUTCOMES)
    v_str(body, "notes", required=False)
    if outcome == "ISSUED":
        p["status"] = "ISSUED"
        p["issued_at"] = now_ts()
        p["_issued_date"] = clock_now().date()
        touch(p)
        if project["status"] == "PERMITTING":
            advance_project(project, "SCHEDULING")
    else:
        p["status"] = "CORRECTIONS_REQUIRED"
        touch(p)
    return ok(ser_permit(p))
