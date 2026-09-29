"""CollectionPlanEntry: creation with supersede, reads and status actions."""

from flask import Blueprint

import db
import middleware as M
import response
import serializers as S
import validators as V
from errors import ApiError
from services import engine

bp = Blueprint("plan_entries", __name__)

REQUIREMENTS = ("GREEN_ONLY", "GREEN_OR_YELLOW", "ANY_WITH_JUSTIFICATION")
STATUSES = ("DRAFT", "APPROVED", "SUSPENDED", "RETIRED")
ACTIONS = ("APPROVE", "SUSPEND", "REINSTATE", "RETIRE")

ENTRY_COMPUTED = (
    "status", "approved_by_user_id", "approved_at", "superseded_by_entry_id", "suspension_reason",
)

LEGAL_ACTIONS = {
    "DRAFT": ("APPROVE", "RETIRE"),
    "APPROVED": ("SUSPEND", "RETIRE"),
    "SUSPENDED": ("REINSTATE", "RETIRE"),
}


@bp.route("/aquarium/collection-plan-entries", methods=["POST"])
def create_entry():
    M.authenticate({M.CURATOR})
    body = M.json_body()
    exhibit = M.fetch_body_fk(body, "exhibit_id", "exhibits")
    species = M.fetch_body_fk(body, "species_id", "species")

    V.reject_computed(body, ENTRY_COMPUTED)
    V.as_id(body, "exhibit_id", required=True)
    V.as_id(body, "species_id", required=True)
    planned_count = V.as_int(body, "planned_count", required=True, minimum=1)
    requirement = V.as_enum(body, "sustainability_requirement", REQUIREMENTS, required=True)
    expected_version = V.as_int(body, "expected_exhibit_version", required=True, minimum=0)

    if expected_version != exhibit["version"]:
        raise ApiError("ERR_STALE_EXHIBIT_VERSION")

    row = db.new_row()
    row.update({
        "exhibit_id": exhibit["id"],
        "species_id": species["id"],
        "planned_count": planned_count,
        "sustainability_requirement": requirement,
        "status": "DRAFT",
        "approved_by_user_id": None,
        "approved_at": None,
        "superseded_by_entry_id": None,
        "suspension_reason": None,
    })
    db.insert("collection_plan_entries", row)

    predecessor = engine.approved_plan_entry(exhibit["id"], species["id"])
    if predecessor is not None:
        predecessor["status"] = "RETIRED"
        predecessor["superseded_by_entry_id"] = row["id"]
        db.touch(predecessor)
        db.touch(exhibit)
    return response.object_response(S.collection_plan_entry(row), 201)


@bp.route("/aquarium/collection-plan-entries", methods=["GET"])
def list_entries():
    M.authenticate(M.NON_LIAISON)
    exhibit_id = M.str_param("exhibit_id")
    species_id = M.str_param("species_id")
    superseded_by = M.str_param("superseded_by_entry_id")
    status = M.enum_param("status", STATUSES)
    limit, offset = M.pagination()

    def keep(row):
        if exhibit_id is not None and row["exhibit_id"] != exhibit_id:
            return False
        if species_id is not None and row["species_id"] != species_id:
            return False
        if superseded_by is not None and row["superseded_by_entry_id"] != superseded_by:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    rows = db.ordered("collection_plan_entries", keep)
    page, total = M.paginate(rows, limit, offset)
    return response.list_response(
        [S.collection_plan_entry(r) for r in page], limit, offset, total)


@bp.route("/aquarium/collection-plan-entries/<row_id>", methods=["GET"])
def get_entry(row_id):
    M.authenticate(M.NON_LIAISON)
    row = M.fetch("collection_plan_entries", row_id)
    return response.object_response(S.collection_plan_entry(row))


@bp.route("/aquarium/collection-plan-entries/<row_id>/status-actions", methods=["POST"])
def status_action(row_id):
    user_id, _role = M.authenticate({M.DIRECTOR})
    entry = M.fetch("collection_plan_entries", row_id)
    body = M.json_body()
    V.reject_computed(body, ENTRY_COMPUTED)
    action = V.as_enum(body, "action", ACTIONS, required=True)
    reason = V.as_str(body, "reason")

    if entry["status"] == "RETIRED":
        raise ApiError("ERR_ENTITY_TERMINAL")
    if action not in LEGAL_ACTIONS.get(entry["status"], ()):
        # PRD §2.8 rank 10 — "The requested transition is declared from the target
        # entity's current state — `ERR_INVALID_STATE` (409). Applies to plan-entry
        # status actions" — and the ladder is total, so rank 10 answers before the
        # rank 12 `ERR_INVALID_ACTION` complaint about the same action value.
        raise ApiError("ERR_INVALID_STATE")

    exhibit = db.db.exhibits.get(entry["exhibit_id"])
    system = engine.serving_system(exhibit) if exhibit is not None else None
    if exhibit is not None and system is not None:
        if exhibit["habitat_type"] != system["design_habitat"]:
            raise ApiError("ERR_HABITAT_MISMATCH")

    if action == "REINSTATE":
        for other in db.ordered(
            "collection_plan_entries",
            lambda e: e["exhibit_id"] == entry["exhibit_id"]
            and e["species_id"] == entry["species_id"]
            and e["id"] != entry["id"],
        ):
            if other["status"] in ("DRAFT", "APPROVED"):
                raise ApiError("ERR_DUPLICATE_ACTIVE_PLAN_ENTRY")

    if action == "APPROVE":
        entry["status"] = "APPROVED"
        entry["approved_by_user_id"] = user_id
        entry["approved_at"] = db.db.clock
        db.touch(entry)
    elif action == "REINSTATE":
        entry["status"] = "APPROVED"
        entry["suspension_reason"] = None
        entry["approved_by_user_id"] = user_id
        entry["approved_at"] = db.db.clock
        db.touch(entry)
    elif action == "RETIRE":
        entry["status"] = "RETIRED"
        db.touch(entry)
    else:
        engine.suspend_plan_entry(entry, "DIRECTOR_ACTION")

    return response.object_response(S.collection_plan_entry(entry))
