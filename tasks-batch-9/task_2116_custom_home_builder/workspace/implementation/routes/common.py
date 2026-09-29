"""Shared lookup / ownership helpers used by every route module."""
from errors import AppError
from store import db

NOT_FOUND = {
    "projects": "ERR_PROJECT_NOT_FOUND",
    "clients": "ERR_CLIENT_NOT_FOUND",
    "lenders": "ERR_LENDER_NOT_FOUND",
    "staff_members": "ERR_STAFF_NOT_FOUND",
    "subcontractors": "ERR_SUBCONTRACTOR_NOT_FOUND",
    "allowance_items": "ERR_ALLOWANCE_ITEM_NOT_FOUND",
    "selections": "ERR_SELECTION_NOT_FOUND",
    "change_orders": "ERR_CHANGE_ORDER_NOT_FOUND",
    "schedule_tasks": "ERR_SCHEDULE_TASK_NOT_FOUND",
    "cost_entries": "ERR_COST_ENTRY_NOT_FOUND",
    "draw_requests": "ERR_DRAW_REQUEST_NOT_FOUND",
    "lien_waivers": "ERR_LIEN_WAIVER_NOT_FOUND",
    "defect_tickets": "ERR_DEFECT_TICKET_NOT_FOUND",
    "photo_documents": "ERR_PHOTO_NOT_FOUND",
}


def fetch(collection, row_id):
    """Resolve a row or raise the family-specific 404 (PRD 2.9)."""
    store = getattr(db, collection)
    row = store.get(row_id) if row_id is not None else None
    if row is None:
        raise AppError(NOT_FOUND[collection])
    return row


def project_of(row):
    return db.projects.get(row.get("project_id"))


def own_project(project, user_id, role):
    """Ladder step 8 - entity-backed ownership (PRD 2.1 / 2.10)."""
    if role == "Client":
        if project is None or project.get("client_id") != user_id:
            raise AppError("ERR_NOT_RESOURCE_OWNER")
    elif role == "Lender":
        if project is None or project.get("lender_id") != user_id:
            raise AppError("ERR_NOT_RESOURCE_OWNER")


def own_subcontractor(row_value, user_id, role):
    if role == "Subcontractor" and row_value != user_id:
        raise AppError("ERR_NOT_RESOURCE_OWNER")
