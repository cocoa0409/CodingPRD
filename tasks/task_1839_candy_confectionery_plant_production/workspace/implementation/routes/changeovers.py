"""The swab-and-release changeover protocol (PRD §3.3).

PENDING_SWAB -> PENDING_QA -> RELEASED, with segregated duties: the operator
who records the swab may not be the one who releases the line.
"""
from flask import Blueprint, request

from db import new_id, stamp_new, store, touch
from errors import ApiError
from middleware import (ALLERGEN_VOCAB, ALL_ROLES, auth, body, is_int,
                        paginate, require_fields)
from response import success_list, success_object
from serializers import changeover_json
from routes.lines import get_line_or_404

changeovers_bp = Blueprint("changeovers", __name__)

CHANGEOVER_TYPES = ("SHAPE_ONLY", "FULL", "ALLERGEN_WASH")


def get_changeover_or_404(cid):
    c = store.changeovers.get(cid)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", "Changeover not found: %s" % cid)
    return c


@changeovers_bp.route("/production-lines/<lid>/changeovers", methods=["POST"])
def create_changeover(lid):
    auth(("LineOperator",))
    # Nested resource retrieval: path identifiers validated left to right.
    line = get_line_or_404(lid)
    b = body()
    # Existence: to_mold_id, when provided, must reference an existing mold.
    to_mold_id = b.get("to_mold_id")
    to_mold = None
    if to_mold_id is not None:
        to_mold = store.molds.get(to_mold_id)
        if to_mold is None:
            raise ApiError("ERR_NOT_FOUND", "to_mold_id references a non-existent resource.")
    # Request shape (ERR_INVALID_REQUEST).
    require_fields(b, ["changeover_type", "expected_line_version"])
    if b["changeover_type"] not in CHANGEOVER_TYPES:
        raise ApiError("ERR_INVALID_REQUEST",
                       "changeover_type must be one of SHAPE_ONLY, FULL, ALLERGEN_WASH.")
    target_allergens = b.get("target_allergens")
    if b["changeover_type"] == "ALLERGEN_WASH":
        # An ALLERGEN_WASH must declare a non-empty target_allergens set.
        if not isinstance(target_allergens, list) or len(target_allergens) == 0:
            raise ApiError("ERR_INVALID_REQUEST",
                           "ALLERGEN_WASH requires a non-empty target_allergens set.")
        if any(a not in ALLERGEN_VOCAB for a in target_allergens):
            raise ApiError("ERR_INVALID_REQUEST", "target_allergens entries must be declared allergens.")
    else:
        # The other two types forbid the field entirely.
        if target_allergens is not None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "target_allergens is forbidden unless changeover_type is ALLERGEN_WASH.")
    if not is_int(b["expected_line_version"]):
        raise ApiError("ERR_INVALID_REQUEST", "expected_line_version must be an integer.")
    # State gates: the line must be AVAILABLE, then the OCC check.
    if line["status"] != "AVAILABLE":
        raise ApiError("ERR_LINE_NOT_AVAILABLE", "The line is not AVAILABLE (changeover in progress).")
    if b["expected_line_version"] != line["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_line_version does not match the line's current version.")
    # Structural: a named mold must be AVAILABLE in inventory.
    if to_mold is not None and to_mold["status"] != "AVAILABLE":
        raise ApiError("ERR_MOLD_NOT_AVAILABLE", "to_mold_id references a mold that is not AVAILABLE.")
    c = {
        "id": new_id(),
        "line_id": line["id"],
        "changeover_type": b["changeover_type"],
        "to_mold_id": to_mold_id,
        "target_allergens": (list(target_allergens)
                             if b["changeover_type"] == "ALLERGEN_WASH" else None),
        "swab_recorded_by": None,
        "swab_passed": None,
        "qa_released_by": None,
        "status": "PENDING_SWAB",
    }
    stamp_new(c)
    store.changeovers[c["id"]] = c
    # The line flips to CHANGEOVER — it cannot start runs — version incrementing.
    line["status"] = "CHANGEOVER"
    touch(line)
    return success_object(changeover_json(c), 201)


@changeovers_bp.route("/changeovers", methods=["GET"])
def list_changeovers():
    auth(ALL_ROLES)
    items = list(store.changeovers.values())
    f = request.args.get("line_id")
    if f is not None:
        items = [c for c in items if c["line_id"] == f]
    f = request.args.get("to_mold_id")
    if f is not None:
        items = [c for c in items if c["to_mold_id"] == f]
    items.sort(key=lambda c: c["created_at"])
    page, meta = paginate(items)
    return success_list([changeover_json(c) for c in page], meta)


@changeovers_bp.route("/changeovers/<cid>", methods=["GET"])
def get_changeover(cid):
    auth(ALL_ROLES)
    return success_object(changeover_json(get_changeover_or_404(cid)))


@changeovers_bp.route("/changeovers/<cid>/swab", methods=["POST"])
def record_swab(cid):
    uid = auth(("SanitationLead",))
    c = get_changeover_or_404(cid)
    b = body()
    if "swab_passed" not in b or b["swab_passed"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: swab_passed.")
    if not isinstance(b["swab_passed"], bool):
        raise ApiError("ERR_INVALID_REQUEST", "swab_passed must be a boolean.")
    # State gate: the changeover must still be PENDING_SWAB.
    if c["status"] != "PENDING_SWAB":
        raise ApiError("ERR_INVALID_STATE", "Changeover is not PENDING_SWAB.")
    # A failed swab is rejected and the changeover remains PENDING_SWAB,
    # awaiting re-wash and a new swab.
    if b["swab_passed"] is not True:
        raise ApiError("ERR_SWAB_FAILED", "Swab recorded as failed; the changeover remains PENDING_SWAB.")
    c["swab_recorded_by"] = uid
    c["swab_passed"] = True
    c["status"] = "PENDING_QA"
    touch(c)
    return success_object(changeover_json(c))


@changeovers_bp.route("/changeovers/<cid>/release", methods=["POST"])
def release_changeover(cid):
    uid = auth(("QualityManager",))
    c = get_changeover_or_404(cid)
    # State gate: release is only from PENDING_QA.
    if c["status"] != "PENDING_QA":
        raise ApiError("ERR_INVALID_STATE", "Changeover is not PENDING_QA.")
    # Segregation of duties: the releasing operator must differ from the swab
    # recorder.
    if uid == c["swab_recorded_by"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The releasing operator must differ from the operator who recorded the swab.")
    c["qa_released_by"] = uid
    c["status"] = "RELEASED"
    touch(c)
    line = store.production_lines[c["line_id"]]
    line["status"] = "AVAILABLE"
    if c["to_mold_id"] is not None:
        # The previously installed mold (if any) returns to AVAILABLE; the new
        # mold becomes INSTALLED; each affected mold's version increments.
        previous = store.molds.get(line["current_mold_id"]) if line["current_mold_id"] else None
        if previous is not None and previous["id"] != c["to_mold_id"]:
            previous["status"] = "AVAILABLE"
            touch(previous)
        new_mold = store.molds[c["to_mold_id"]]
        new_mold["status"] = "INSTALLED"
        touch(new_mold)
        line["current_mold_id"] = c["to_mold_id"]
    # Clearance is set by changeover type: an ALLERGEN_WASH release sets the
    # line's cleared set to exactly the target; the other types reset it.
    if c["changeover_type"] == "ALLERGEN_WASH":
        line["cleared_allergens"] = list(c["target_allergens"])
    else:
        line["cleared_allergens"] = []
    touch(line)
    return success_object(changeover_json(c))
