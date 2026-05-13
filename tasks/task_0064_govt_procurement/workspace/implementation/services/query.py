"""Query lifecycle."""

from flask import g

from clock import clock, parse_iso
from db import bump_version, common_fields_create, db
from errors import (
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_QUERY_WINDOW_CLOSED,
    ERR_REFERENCE_NOT_FOUND,
    ERR_VALIDATION,
    raise_error,
)
from services.project import get_project_or_404
from services.supplier import get_supplier_or_ref_404


def get_query_or_404(query_id: str) -> dict:
    q = db.queries.get(query_id)
    if not q:
        raise_error(ERR_NOT_FOUND, f"query '{query_id}' not found")
    return q


def submit_query(project_id: str, body: dict):
    project = get_project_or_404(project_id)
    supplier_id = body.get("supplier_id")
    if not isinstance(supplier_id, str) or not supplier_id:
        raise_error(ERR_VALIDATION, "supplier_id is required")
    actor_id = getattr(g, "user_id", None)
    if actor_id != supplier_id:
        raise_error(ERR_FORBIDDEN, "supplier may only submit queries on its own behalf")
    get_supplier_or_ref_404(supplier_id)
    question = body.get("question")
    if not isinstance(question, str) or not question:
        raise_error(ERR_VALIDATION, "question must be non-empty string")
    if project["project_status"] not in {"PRESCREEN_OPEN", "BIDDING_OPEN"}:
        raise_error(ERR_INVALID_STATE, "project must be PRESCREEN_OPEN or BIDDING_OPEN")
    # Query window
    try:
        qwc = parse_iso(project["query_window_close_at"])
    except Exception:
        raise_error(ERR_VALIDATION, "invalid query_window_close_at")
    if not (clock.now() < qwc):
        raise_error(ERR_QUERY_WINDOW_CLOSED, "query window closed")
    q = {
        "id": db.new_id(),
        **common_fields_create(),
        "project_id": project_id,
        "supplier_id": supplier_id,
        "question": question,
        "response": None,
        "query_status": "OPEN",
    }
    db.queries[q["id"]] = q
    return q


def respond_to_query(query_id: str, body: dict):
    q = get_query_or_404(query_id)
    if q["query_status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "query must be OPEN")
    response = body.get("response")
    if not isinstance(response, str) or not response:
        raise_error(ERR_VALIDATION, "response must be non-empty string")
    q["response"] = response
    q["query_status"] = "ANSWERED"
    bump_version(q)
    return q


def expire_open_queries():
    """Side-effect of clock advance: any OPEN query past its window closes -> EXPIRED."""
    now = clock.now()
    for q in db.queries.values():
        if q["query_status"] != "OPEN":
            continue
        project = db.projects.get(q["project_id"])
        if not project:
            continue
        try:
            qwc = parse_iso(project["query_window_close_at"])
        except Exception:
            continue
        if now >= qwc:
            q["query_status"] = "EXPIRED"
            bump_version(q)
