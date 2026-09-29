"""Development permit lifecycle: draft, submit, review, issue, closeout."""

from flask import Blueprint

from db import base_fields, db, iso, iso_now, now, plus_days, touch
from errors import fail
from middleware import ALL_ROLES, require
from response import list_response, object_response
from services import calc, engine
from validation import (body, fk, find, lookup, opt_bool, opt_num, opt_str,
                        pagination, paginate, query_filters, req_enum, req_num)

bp = Blueprint("permits", __name__)

_DECISIONS = ("APPROVE", "REQUEST_REVISION", "DENY")


def _owner_guard(user_id, role, property_id):
    """PRD 2.8 step 4 — skipped when the owning property cannot be resolved."""
    if role != "PropertyOwner":
        return
    if not property_id or property_id not in db.properties:
        return
    if user_id != property_id:
        fail("ERR_NOT_PROPERTY_OWNER")


@bp.post("/permits")
def create_permit():
    user_id, role = require("PropertyOwner")
    data = body()
    _owner_guard(user_id, role, data.get("property_id"))

    property_id = fk(data, "property_id", "property")
    structure_id = fk(data, "structure_id", "structure")
    project_type = req_enum(data, "project_type", calc.PROJECT_TYPES)
    cost = req_num(data, "declared_project_cost_usd", minimum=0)
    proposed = req_num(data, "proposed_lowest_floor_elevation_ft")
    floodproofing = opt_bool(data, "floodproofing_requested", default=False)

    lookup("property", property_id)
    structure = lookup("structure", structure_id)
    if structure["property_id"] != property_id:
        fail("ERR_STRUCTURE_PROPERTY_MISMATCH")

    row = base_fields()
    row.update({
        "property_id": property_id,
        "structure_id": structure_id,
        "project_type": project_type,
        "declared_project_cost_usd": calc.money(cost),
        "proposed_lowest_floor_elevation_ft": calc.r1(proposed),
        "floodproofing_requested": floodproofing,
        "determined_zone": None,
        "determined_bfe_ft": None,
        "freeboard_applied_ft": None,
        "required_lowest_floor_elevation_ft": None,
        "si_determination_case_id": None,
        "status": "DRAFT",
        "revision_round": 0,
        "issued_at": None,
        "expires_at": None,
    })
    db.permits[row["id"]] = row
    return object_response(row, 201)


@bp.get("/permits/<permit_id>")
def read_permit(permit_id):
    require(*ALL_ROLES)
    return object_response(lookup("permit", permit_id))


@bp.get("/permits")
def list_permits():
    require(*ALL_ROLES)
    limit, offset = pagination()
    rows = query_filters(list(db.permits.values()), {
        "property_id": ("property_id", None),
        "structure_id": ("structure_id", None),
        "si_determination_case_id": ("si_determination_case_id", None),
        "status": ("status", None),
    })
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/permits/<permit_id>/submit")
def submit_permit(permit_id):
    user_id, role = require("PropertyOwner")
    permit = lookup("permit", permit_id)
    _owner_guard(user_id, role, permit["property_id"])

    data = body()
    proposed = opt_num(data, "proposed_lowest_floor_elevation_ft")
    cost = opt_num(data, "declared_project_cost_usd", minimum=0)
    floodproofing = opt_bool(data, "floodproofing_requested")

    if permit["status"] not in ("DRAFT", "REVISION_REQUIRED"):
        fail("ERR_PERMIT_NOT_SUBMITTABLE")

    prop = db.properties.get(permit["property_id"])
    panel = db.firm_panels.get(prop["firm_panel_id"]) if prop else None
    if panel is None or panel["status"] != "EFFECTIVE":
        fail("ERR_PANEL_NOT_EFFECTIVE")
    if panel["flood_zone"] == "X":
        fail("ERR_OUTSIDE_FLOOD_HAZARD_AREA")
    if panel["base_flood_elevation_ft"] is None:
        fail("ERR_BFE_UNDETERMINED")

    resubmission = permit["status"] == "REVISION_REQUIRED"
    if resubmission and permit["revision_round"] >= calc.MAX_REVISION_ROUNDS:
        fail("ERR_REVISION_LIMIT_EXCEEDED")

    if proposed is not None:
        permit["proposed_lowest_floor_elevation_ft"] = calc.r1(proposed)
    if cost is not None:
        permit["declared_project_cost_usd"] = calc.money(cost)
    if floodproofing is not None:
        permit["floodproofing_requested"] = floodproofing

    if resubmission:
        permit["revision_round"] += 1

    community = db.communities.get(prop["community_id"])
    structure = db.structures.get(permit["structure_id"])
    permit["determined_zone"] = panel["flood_zone"]
    permit["determined_bfe_ft"] = panel["base_flood_elevation_ft"]
    permit["freeboard_applied_ft"] = community["freeboard_ft"] if community else calc.ZERO
    permit["required_lowest_floor_elevation_ft"] = engine.required_elevation(permit, structure)
    permit["status"] = "UNDER_REVIEW"
    touch(permit)
    engine.refresh_submitted_certificates(permit)
    return object_response(permit)


@bp.post("/permits/<permit_id>/review")
def review_permit(permit_id):
    require("FloodplainAdministrator")
    permit = lookup("permit", permit_id)
    data = body()
    decision = req_enum(data, "decision", _DECISIONS)
    opt_str(data, "review_note")

    if permit["status"] != "UNDER_REVIEW":
        fail("ERR_PERMIT_NOT_UNDER_REVIEW")

    structure = db.structures.get(permit["structure_id"])

    if decision == "APPROVE":
        required = permit["required_lowest_floor_elevation_ft"]
        if (required is not None
                and calc.dec(permit["proposed_lowest_floor_elevation_ft"]) < calc.dec(required)):
            fail("ERR_ELEVATION_BELOW_REQUIRED")

        gate_applies = False
        if permit["project_type"] in ("IMPROVEMENT", "REPAIR") and structure is not None:
            ratio = calc.pct(permit["declared_project_cost_usd"], structure["market_value_usd"])
            gate_applies = ratio >= calc.SI_THRESHOLD_PCT
        resolved = engine.newest_resolved_case(permit["structure_id"]) if structure else None
        if gate_applies and resolved is None:
            fail("ERR_DETERMINATION_REQUIRED")

        permit["status"] = "APPROVED"
        permit["si_determination_case_id"] = resolved["id"] if gate_applies else None
    elif decision == "REQUEST_REVISION":
        if permit["revision_round"] >= calc.MAX_REVISION_ROUNDS:
            fail("ERR_REVISION_LIMIT_EXCEEDED")
        permit["status"] = "REVISION_REQUIRED"
    else:
        permit["status"] = "DENIED"

    touch(permit)
    return object_response(permit)


@bp.post("/permits/<permit_id>/issue")
def issue_permit(permit_id):
    require("FloodplainAdministrator")
    permit = lookup("permit", permit_id)
    if permit["status"] != "APPROVED":
        fail("ERR_PERMIT_NOT_APPROVED")

    prop = db.properties.get(permit["property_id"])
    community = db.communities.get(prop["community_id"]) if prop else None
    structure = db.structures.get(permit["structure_id"])
    posture = community["compliance_posture"] if community else "GOOD_STANDING"
    if posture == "SUSPENDED":
        fail("ERR_COMMUNITY_SUSPENDED")
    if posture == "ON_PROBATION" and structure is not None and structure["substantial_status"] != "NONE":
        fail("ERR_COMMUNITY_ON_PROBATION")

    permit["status"] = "ISSUED"
    permit["issued_at"] = iso_now()
    permit["expires_at"] = iso(plus_days(now(), calc.PERMIT_VALIDITY_DAYS))
    touch(permit)
    return object_response(permit)


@bp.post("/permits/<permit_id>/close")
def close_permit(permit_id):
    require("FloodplainAdministrator")
    permit = lookup("permit", permit_id)
    if permit["status"] != "ISSUED":
        fail("ERR_PERMIT_NOT_ISSUED")

    finished = [c for c in engine.certificates_of_permit(permit["id"])
                if c["certificate_type"] == "FINISHED_CONSTRUCTION"
                and c["status"] == "ACCEPTED"]
    if not finished:
        fail("ERR_FINISHED_CERTIFICATE_REQUIRED")

    permit["status"] = "CLOSED_COMPLIANT"
    touch(permit)

    if permit["project_type"] in ("IMPROVEMENT", "REPAIR"):
        structure = db.structures.get(permit["structure_id"])
        if structure is not None:
            record = engine.create_record(
                structure, "IMPROVEMENT", "PERMIT_CLOSEOUT", now(),
                permit["declared_project_cost_usd"], 0, permit_id=permit["id"])
            engine.ledger_effects(structure, record)
    return object_response(permit)
