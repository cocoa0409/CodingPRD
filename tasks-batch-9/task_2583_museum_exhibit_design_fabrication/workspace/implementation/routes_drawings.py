"""ShopDrawing endpoints and the fabrication ledger (PRD §3.7)."""

from flask import Blueprint

import calc
import cascades
import helpers
import serializers
from auth import (ALL_ROLES, ROLE_FABRICATION_LEAD, ROLE_PROJECT_MANAGER, caller_id,
                  check_segregation, endpoint)
from envelope import list_response, object_response, pagination, query_filter
from errors import ApiError
from helpers import touch
from store import db, new_row, order_created
from validate import bad, body_object, v_enum, v_id, v_int, v_num, v_str

bp = Blueprint("drawings", __name__)

COMPLEXITY_TIERS = ("STANDARD", "PRECISION", "CONSERVATION_GRADE")
FINISH_GRADES = ("MILL", "SATIN", "MUSEUM_GLOSS")
DRAWING_DECISIONS = ("APPROVE", "APPROVE_AS_NOTED", "REJECT")
VOIDABLE = ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "APPROVED_AS_NOTED")


@bp.route("/shop-drawings", methods=["POST"])
@endpoint(roles=[ROLE_FABRICATION_LEAD])
def create_drawing():
    body = body_object()
    project_id = v_id(body, "project_id")
    material_spec_id = v_id(body, "material_spec_id")
    subject_case_id = v_id(body, "subject_case_id", required=False, default=None)
    subject_interactive_id = v_id(body, "subject_interactive_id", required=False, default=None)
    drawing_number = v_str(body, "drawing_number", 1, 40)
    revision = v_int(body, "revision", minimum=1, required=False, default=1)
    complexity_tier = v_enum(body, "complexity_tier", COMPLEXITY_TIERS)
    shop_hours = v_num(body, "shop_hours", gt=0)
    material_area = v_num(body, "material_area_m2", gt=0)
    finish_grade = v_enum(body, "finish_grade", FINISH_GRADES)
    named = [s for s in (subject_case_id, subject_interactive_id) if s is not None]
    if len(named) != 1:
        bad("Exactly one of subject_case_id or subject_interactive_id must be supplied.")

    # Step 5: the eleven 404s in the order §2.5 lists them.
    project = helpers.get_project(project_id)
    case = helpers.get_case(subject_case_id) if subject_case_id is not None else None
    interactive = (helpers.get_interactive(subject_interactive_id)
                   if subject_interactive_id is not None else None)
    material = helpers.get_material(material_spec_id)
    # Step 6.
    helpers.require_same_project(project, case)
    helpers.require_same_project(project, interactive)
    helpers.require_same_project(project, material)

    # Step 8: number and revision are unique among the project's non-VOID sheets, so a
    # voided sheet frees its number for re-issue at the same revision.
    for existing in helpers.rows_of_project(db.drawings, project["id"]):
        if (existing["status"] != "VOID"
                and existing["drawing_number"] == drawing_number
                and existing["revision"] == revision):
            raise ApiError("ERR_DUPLICATE_CODE",
                           "Drawing %s revision %d already exists in this project."
                           % (drawing_number, revision))

    helpers.require_phase(project, ("FABRICATION",))
    helpers.require_not_frozen(project)

    # Step 12: the subject case's status.
    if case is not None and case["status"] not in ("APPROVED", "CONDITIONALLY_APPROVED"):
        raise ApiError("ERR_INVALID_CASE_STATE")
    # Step 13: material clearance, then prototype clearance.
    if material["status"] not in ("APPROVED", "CONDITIONAL"):
        raise ApiError("ERR_MATERIAL_NOT_CONSERVATION_APPROVED")
    if interactive is not None and interactive["status"] not in (
            "PROTOTYPE_APPROVED", "FABRICATED", "COMMISSIONED"):
        raise ApiError("ERR_PROTOTYPE_NOT_APPROVED")

    drawing = new_row("drawings", {
        "project_id": project["id"],
        "material_spec_id": material["id"],
        "subject_case_id": subject_case_id,
        "subject_interactive_id": subject_interactive_id,
        "drawing_number": drawing_number,
        "revision": revision,
        "complexity_tier": complexity_tier,
        "shop_hours": shop_hours,
        "material_area_m2": material_area,
        "finish_grade": finish_grade,
        "actual_shop_hours": None,
        "actual_waste_factor": None,
        "actual_labor_cents": None,
        "actual_material_cents": None,
        "actual_finishing_cents": None,
        "actual_cost_cents": None,
        "status": "SUBMITTED",
        "submitted_by_user_id": caller_id(),
        "void_reason": None,
    })
    # The schematic estimate is advisory: no money moves at issue.
    estimate = calc.fabrication_cost_schematic(drawing, material)
    drawing["estimate_labor_cents"] = estimate["labor_cents"]
    drawing["estimate_material_cents"] = estimate["material_cents"]
    drawing["estimate_finishing_cents"] = estimate["finishing_cents"]
    drawing["estimate_total_cents"] = estimate["total_cents"]
    db.drawings[drawing["id"]] = drawing
    return object_response(serializers.drawing_json(drawing), 201)


@bp.route("/shop-drawings", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def list_drawings():
    limit, offset = pagination()
    project_id = query_filter("project_id")
    material_spec_id = query_filter("material_spec_id")
    subject_case_id = query_filter("subject_case_id")
    subject_interactive_id = query_filter("subject_interactive_id")
    status = query_filter("status")
    rows = sorted(db.drawings.values(), key=order_created)
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if material_spec_id is not None:
        rows = [r for r in rows if r["material_spec_id"] == material_spec_id]
    if subject_case_id is not None:
        rows = [r for r in rows if r["subject_case_id"] == subject_case_id]
    if subject_interactive_id is not None:
        rows = [r for r in rows if r["subject_interactive_id"] == subject_interactive_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, serializers.drawing_json, limit, offset)


@bp.route("/exhibit-projects/<pid>/shop-drawings", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def list_project_drawings(pid):
    project = helpers.get_project(pid)
    limit, offset = pagination()
    status = query_filter("status")
    rows = helpers.rows_of_project(db.drawings, project["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, serializers.drawing_json, limit, offset)


@bp.route("/shop-drawings/<drawing_id>", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def get_drawing(drawing_id):
    drawing = helpers.get_drawing(drawing_id)
    return object_response(serializers.drawing_json(drawing))


@bp.route("/shop-drawings/<drawing_id>/start-review", methods=["POST"])
@endpoint(roles=[ROLE_PROJECT_MANAGER])
def start_review(drawing_id):
    drawing = helpers.get_drawing(drawing_id)
    project = helpers.owning_project(drawing)
    # Taking an already-submitted sheet into review is permitted in DESIGN_DEV too.
    helpers.require_phase(project, ("DESIGN_DEV", "FABRICATION"))
    if drawing["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_DRAWING_STATE")
    drawing["status"] = "UNDER_REVIEW"
    touch(drawing)
    return object_response(serializers.drawing_json(drawing))


@bp.route("/shop-drawings/<drawing_id>/decision", methods=["POST"])
@endpoint(roles=[ROLE_PROJECT_MANAGER])
def decide_drawing(drawing_id):
    # Step 3 is the segregation pairing, which can only be judged when the sheet is
    # on file; step 4 (body shape) still precedes step 5 (existence), so the row is
    # resolved without raising here and the 404 is raised after the body is checked.
    drawing = db.drawings.get(drawing_id, None)
    if drawing is not None:
        check_segregation(drawing["submitted_by_user_id"])
    body = body_object()
    decision = v_enum(body, "decision", DRAWING_DECISIONS)
    v_str(body, "note", None, None, required=False, default=None)
    approving = decision in ("APPROVE", "APPROVE_AS_NOTED")
    actual_hours = v_num(body, "actual_shop_hours", gt=0, required=approving, default=None)
    actual_waste = v_num(body, "actual_waste_factor", gt=0, required=approving, default=None)

    # Step 5.
    drawing = helpers.get_drawing(drawing_id)
    project = helpers.owning_project(drawing)

    # Step 11: deciding a shop drawing is frozen-blocked.
    helpers.require_not_frozen(project)
    # Step 12.
    if drawing["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_DRAWING_STATE")

    material = db.materials[drawing["material_spec_id"]]
    if decision == "APPROVE":
        # An APPROVE demands the material be cleared outright.
        if material["status"] != "APPROVED":
            raise ApiError("ERR_MATERIAL_NOT_CONSERVATION_APPROVED")
    elif decision == "APPROVE_AS_NOTED":
        if material["status"] not in ("APPROVED", "CONDITIONAL"):
            raise ApiError("ERR_MATERIAL_NOT_CONSERVATION_APPROVED")

    if not approving:
        # A REJECT moves no money at all.
        drawing["status"] = "REJECTED"
        touch(drawing)
        return object_response(serializers.drawing_json(drawing))

    actual = calc.fabrication_cost_actual(drawing, material, actual_hours, actual_waste)
    # Step 14: fiscal capacity is the very last thing checked.
    if actual["total_cents"] > helpers.uncommitted_cents(project):
        raise ApiError("ERR_FABRICATION_BUDGET_EXCEEDED")

    drawing["actual_shop_hours"] = actual_hours
    drawing["actual_waste_factor"] = actual_waste
    drawing["actual_labor_cents"] = actual["labor_cents"]
    drawing["actual_material_cents"] = actual["material_cents"]
    drawing["actual_finishing_cents"] = actual["finishing_cents"]
    drawing["actual_cost_cents"] = actual["total_cents"]
    drawing["status"] = "APPROVED" if decision == "APPROVE" else "APPROVED_AS_NOTED"
    project["committed_fabrication_cents"] = (project["committed_fabrication_cents"]
                                             + actual["total_cents"])
    touch(drawing)
    touch(project)
    return object_response(serializers.drawing_json(drawing))


@bp.route("/shop-drawings/<drawing_id>/void", methods=["POST"])
@endpoint(roles=[ROLE_PROJECT_MANAGER, ROLE_FABRICATION_LEAD])
def void(drawing_id):
    drawing = helpers.get_drawing(drawing_id)
    body = body_object()
    void_reason = v_str(body, "void_reason", 1, None, non_blank=True)
    if drawing["status"] not in VOIDABLE:
        raise ApiError("ERR_INVALID_DRAWING_STATE")
    # §3.7: voiding a sheet still in SUBMITTED or UNDER_REVIEW moves no money and
    # reverts no case; only a cleared sheet drags its subject case back to DRAFT.
    cascades.void_drawing(drawing, void_reason,
                          revert_case=drawing["status"] in ("APPROVED", "APPROVED_AS_NOTED"))
    return object_response(serializers.drawing_json(drawing))
