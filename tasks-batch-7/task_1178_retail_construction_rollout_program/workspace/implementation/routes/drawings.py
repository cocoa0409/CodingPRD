"""DrawingSet endpoints (§3.2): revision numbering, approval supersession,
the cyclic revise loop."""
from flask import Blueprint

from db import store
from middleware import ALL_ROLES, authed
from response import ok
from routes import list_response, require_state
from util import bump, new_entity, serialize
from validate import body_fk, get_or_404, json_body, opt_str, req_str

bp = Blueprint("drawings", __name__)

TERMINAL = ("SUPERSEDED",)


@bp.route("/rollout/drawing-sets", methods=["POST"], strict_slashes=False)
@authed(["DesignManager"])
def create_drawing_set():
    body = json_body()
    program = body_fk(body, "program_id", store.programs)
    jurisdiction = req_str(body, "jurisdiction_code")
    notes = opt_str(body, "variance_notes")
    if program is None:
        from errors import invalid_request
        invalid_request("field 'program_id' is required")
    siblings = [
        d for d in store.drawings.values()
        if d["program_id"] == program["id"] and d["jurisdiction_code"] == jurisdiction
    ]
    revision = 1 + max((d["revision"] for d in siblings), default=0)
    drawing = new_entity(store)
    drawing.update({
        "program_id": program["id"],
        "jurisdiction_code": jurisdiction,
        "revision": revision,
        "review_round": 1,
        "supersedes_set_id": None,
        "variance_notes": notes,
        "rejection_reason": None,
        "status": "DRAFT",
    })
    store.drawings[drawing["id"]] = drawing
    return ok(serialize(drawing), status=201)


@bp.route("/rollout/drawing-sets", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def list_drawing_sets():
    return list_response(store.drawings, [
        ("program_id", "program_id", "str"),
        ("jurisdiction_code", "jurisdiction_code", "str"),
        ("status", "status", "str"),
        ("supersedes_set_id", "supersedes_set_id", "str"),
    ])


@bp.route("/rollout/drawing-sets/<drawingSetId>", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def get_drawing_set(drawingSetId):
    return ok(serialize(get_or_404(store.drawings, drawingSetId, "drawing set")))


@bp.route("/rollout/drawing-sets/<drawingSetId>/submit", methods=["POST"], strict_slashes=False)
@authed(["DesignManager"])
def submit_drawing_set(drawingSetId):
    drawing = get_or_404(store.drawings, drawingSetId, "drawing set")
    require_state(drawing, ("DRAFT",), TERMINAL)
    drawing["status"] = "SUBMITTED"
    bump(drawing)
    return ok(serialize(drawing))


@bp.route("/rollout/drawing-sets/<drawingSetId>/approve", methods=["POST"], strict_slashes=False)
@authed(["DesignManager"])
def approve_drawing_set(drawingSetId):
    drawing = get_or_404(store.drawings, drawingSetId, "drawing set")
    require_state(drawing, ("SUBMITTED",), TERMINAL)
    predecessors = [
        d for d in store.drawings.values()
        if d["id"] != drawing["id"]
        and d["program_id"] == drawing["program_id"]
        and d["jurisdiction_code"] == drawing["jurisdiction_code"]
        and d["status"] == "APPROVED"
    ]
    supersedes_id = None
    if predecessors:
        chosen = max(predecessors, key=lambda d: (d["revision"], d["_seq"]))
        supersedes_id = chosen["id"]
        for d in predecessors:
            d["status"] = "SUPERSEDED"
            bump(d)
    drawing["status"] = "APPROVED"
    drawing["supersedes_set_id"] = supersedes_id
    bump(drawing)
    return ok(serialize(drawing))


@bp.route("/rollout/drawing-sets/<drawingSetId>/reject", methods=["POST"], strict_slashes=False)
@authed(["DesignManager"])
def reject_drawing_set(drawingSetId):
    body = json_body()
    drawing = get_or_404(store.drawings, drawingSetId, "drawing set")
    require_state(drawing, ("SUBMITTED",), TERMINAL)
    reason = req_str(body, "rejection_reason")
    drawing["status"] = "REJECTED"
    drawing["rejection_reason"] = reason
    bump(drawing)
    return ok(serialize(drawing))


@bp.route("/rollout/drawing-sets/<drawingSetId>/revise", methods=["POST"], strict_slashes=False)
@authed(["DesignManager"])
def revise_drawing_set(drawingSetId):
    drawing = get_or_404(store.drawings, drawingSetId, "drawing set")
    require_state(drawing, ("REJECTED",), TERMINAL)
    drawing["status"] = "DRAFT"
    drawing["review_round"] += 1
    bump(drawing)
    return ok(serialize(drawing))
