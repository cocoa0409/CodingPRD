"""Editor assignment: explicit or selector-driven, conflict declaration, recusal."""

from flask import Blueprint

import calc
import serializers as ser
import services as svc
import validate as v
from auth import authorise, require_editor_journal
from db import ordered, store, touch
from errors import ApiError
from response import list_response, object_response
from routes.manuscripts import find_manuscript

bp = Blueprint("assignments", __name__)

CONFLICT_TYPES = ("CO_AUTHOR", "SAME_INSTITUTION", "FINANCIAL", "PERSONAL")
EDITORIAL_ROLES = ("SystemAdmin", "EditorInChief", "HandlingEditor")


def find_assignment(aid):
    assignment = store.assignments.get(aid)
    if assignment is None:
        raise ApiError("ERR_EDITOR_ASSIGNMENT_NOT_FOUND")
    return assignment


def _declared_conflict_editor_ids(manuscript_id):
    ids = set()
    for row in calc.assignments_of_manuscript(manuscript_id):
        if row["declared_conflict"] is True or row["state"] == "RECUSED":
            ids.add(row["editor_id"])
    return ids


@bp.post("/editor-assignments")
def create_editor_assignment():
    actor = authorise("EditorInChief")
    data = v.body()

    manuscript_id = v.req_id(data, "manuscript_id")
    manuscript = store.manuscripts.get(manuscript_id)
    if manuscript is None:
        raise ApiError("ERR_MANUSCRIPT_NOT_FOUND")
    editor_id = v.opt_id(data, "editor_id")
    editor = None
    if editor_id is not None:
        editor = store.editors.get(editor_id)
        if editor is None:
            raise ApiError("ERR_EDITOR_NOT_FOUND")

    require_editor_journal(actor, manuscript)

    expected = v.req_int(data, "expected_manuscript_version")
    if expected != int(manuscript["version"]):
        raise ApiError("ERR_STALE_MANUSCRIPT_VERSION")

    svc.guard_manuscript_terminal(manuscript)

    if editor is not None:
        if editor["id"] in _declared_conflict_editor_ids(manuscript_id):
            raise ApiError("ERR_EDITOR_CONFLICT_DECLARED")
        if manuscript["subject_area"] not in (editor["subject_areas"] or []):
            raise ApiError(
                "ERR_EDITOR_WORKLOAD_EXCEEDED",
                "The named editor does not serve this manuscript's subject area.",
            )
        if int(editor["active_assignment_count"]) >= int(editor["max_concurrent_assignments"]):
            raise ApiError("ERR_EDITOR_WORKLOAD_EXCEEDED")
        assignment = svc.create_assignment(manuscript, editor, "EXPLICIT")
    else:
        chosen = calc.select_editor(manuscript, _declared_conflict_editor_ids(manuscript_id))
        if chosen is None:
            raise ApiError("ERR_NO_ELIGIBLE_EDITOR")
        assignment = svc.create_assignment(manuscript, chosen, "SELECTOR")

    touch(manuscript)
    return object_response(ser.assignment_out(assignment), 201)


@bp.post("/editor-assignments/<aid>/conflict-declaration")
def conflict_declaration(aid):
    actor = authorise("HandlingEditor")
    assignment = find_assignment(aid)
    manuscript = store.manuscripts.get(assignment["manuscript_id"])
    data = v.body()
    declared = v.req_bool(data, "declared_conflict")
    conflict_type = v.opt_enum(data, "conflict_type", CONFLICT_TYPES)

    if assignment["editor_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    svc.guard_assignment_terminal(assignment)
    if assignment["state"] != "PROPOSED":
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE")

    if declared:
        if conflict_type is None:
            v.bad("conflict_type", "is required when declared_conflict is true")
        assignment["declared_conflict"] = True
        assignment["conflict_type"] = conflict_type
        svc.recuse_assignment(assignment, manuscript)
    else:
        assignment["declared_conflict"] = False
        assignment["state"] = "ACTIVE"
        touch(assignment)
        if manuscript is not None:
            svc.set_field(manuscript, "handling_gap_flag", False)
    return object_response(ser.assignment_out(assignment), 200)


@bp.post("/editor-assignments/<aid>/recusal")
def recusal(aid):
    actor = authorise("HandlingEditor", "EditorInChief")
    assignment = find_assignment(aid)
    manuscript = store.manuscripts.get(assignment["manuscript_id"])
    data = v.body()
    v.opt_string(data, "reason")

    if actor.role == "HandlingEditor":
        if assignment["editor_id"] != actor.user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")
    else:
        require_editor_journal(actor, manuscript)

    svc.guard_assignment_terminal(assignment)
    if assignment["state"] != "ACTIVE":
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE")
    if manuscript is not None:
        svc.guard_manuscript_terminal(manuscript)

    svc.recuse_assignment(assignment, manuscript)
    return object_response(ser.assignment_out(assignment), 200)


@bp.get("/editor-assignments/<aid>")
def get_assignment(aid):
    authorise(*EDITORIAL_ROLES)
    return object_response(ser.assignment_out(find_assignment(aid)), 200)


@bp.get("/editor-assignments")
def list_assignments():
    authorise(*EDITORIAL_ROLES)
    limit, offset = v.pagination()
    manuscript_id = v.query_str("manuscript_id")
    editor_id = v.query_str("editor_id")
    replaced_id = v.query_str("replaced_assignment_id")
    state = v.query_str("state")
    rows = []
    for row in store.assignments.values():
        if manuscript_id is not None and row["manuscript_id"] != manuscript_id:
            continue
        if editor_id is not None and row["editor_id"] != editor_id:
            continue
        if replaced_id is not None and row["replaced_assignment_id"] != replaced_id:
            continue
        if state is not None and row["state"] != state:
            continue
        rows.append(row)
    rows = ordered(rows)
    page = v.window(rows, limit, offset)
    return list_response(ser.many(page, ser.assignment_out), limit, offset, len(rows))
