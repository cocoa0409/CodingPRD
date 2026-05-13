"""Handler service."""

from errors import (
    AppError, ERR_VALIDATION, ERR_RESOURCE_NOT_FOUND, ERR_REFERENCE_NOT_FOUND,
    ERR_VERSION_CONFLICT, ERROR_STATUS,
)
import db
import validators as V


VALID_STATUSES = {"ACTIVE", "ON_LEAVE", "DISABLED"}


def create_handler(body: dict) -> dict:
    full_name = V.is_str(body, "full_name", min_len=1, max_len=80)

    # department_id presence + foreign key
    if "department_id" not in body or body["department_id"] is None:
        raise AppError(ERR_VALIDATION, "department_id is required", ERROR_STATUS[ERR_VALIDATION])
    dept_id = body["department_id"]
    if not isinstance(dept_id, str):
        raise AppError(ERR_VALIDATION, "department_id must be string", ERROR_STATUS[ERR_VALIDATION])
    dept = db.find_by_id("departments", dept_id)
    if dept is None:
        raise AppError(ERR_REFERENCE_NOT_FOUND, "department_id does not resolve", ERROR_STATUS[ERR_REFERENCE_NOT_FOUND])
    if dept["status"] != "ACTIVE":
        raise AppError(ERR_REFERENCE_NOT_FOUND, "department is not ACTIVE", ERROR_STATUS[ERR_REFERENCE_NOT_FOUND])

    status = V.is_enum(body, "status", VALID_STATUSES, optional=True, default="ACTIVE")

    rec = db.insert("handlers", {
        "full_name": full_name,
        "department_id": dept_id,
        "status": status,
        "open_assignment_count": 0,
    })
    return rec


def get_handler(handler_id: str) -> dict:
    h = db.find_by_id("handlers", handler_id)
    if not h:
        raise AppError(ERR_RESOURCE_NOT_FOUND, "Handler not found", ERROR_STATUS[ERR_RESOURCE_NOT_FOUND])
    return h


def update_handler(handler_id: str, body: dict) -> dict:
    h = get_handler(handler_id)
    if "version" in body and body["version"] is not None:
        if int(body["version"]) != int(h.get("version", 0)):
            raise AppError(ERR_VERSION_CONFLICT, "Version conflict", ERROR_STATUS[ERR_VERSION_CONFLICT])

    updates = {}
    if "status" in body and body["status"] is not None:
        updates["status"] = V.is_enum(body, "status", VALID_STATUSES)
    if updates:
        db.update_fields(h, updates)
    return h
