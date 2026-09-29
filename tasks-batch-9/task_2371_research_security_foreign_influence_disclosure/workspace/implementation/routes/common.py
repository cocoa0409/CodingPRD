"""Shared route helpers: path resolution and list rendering."""

import db
import response
import validate
from errors import ApiError

NOT_FOUND = {
    "investigator": "ERR_INVESTIGATOR_NOT_FOUND",
    "organization": "ERR_ORGANIZATION_NOT_FOUND",
    "project": "ERR_PROJECT_NOT_FOUND",
    "personnel": "ERR_PERSONNEL_NOT_FOUND",
    "disclosure": "ERR_DISCLOSURE_NOT_FOUND",
    "item": "ERR_DISCLOSURE_ITEM_NOT_FOUND",
    "statement": "ERR_SUPPORT_STATEMENT_NOT_FOUND",
    "travel": "ERR_TRAVEL_REGISTRATION_NOT_FOUND",
    "grant": "ERR_ACCESS_GRANT_NOT_FOUND",
    "incident": "ERR_INCIDENT_NOT_FOUND",
    "training": "ERR_TRAINING_ASSIGNMENT_NOT_FOUND",
    "subaward": "ERR_SUBAWARD_NOT_FOUND",
}

STORES = {
    "investigator": lambda: db.investigators,
    "organization": lambda: db.organizations,
    "project": lambda: db.projects,
    "personnel": lambda: db.personnel,
    "disclosure": lambda: db.disclosures,
    "item": lambda: db.items,
    "statement": lambda: db.statements,
    "travel": lambda: db.travel,
    "grant": lambda: db.grants,
    "incident": lambda: db.incidents,
    "training": lambda: db.trainings,
    "subaward": lambda: db.subawards,
}


def must_exist(kind, record_id):
    store = STORES[kind]()
    record = store.get(record_id) if isinstance(record_id, str) else None
    if record is None:
        raise ApiError(NOT_FOUND[kind], "%s '%s' was not found." % (kind, record_id))
    return record


def render_list(rows, serializer):
    limit, offset = validate.pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return response.list_response([serializer(row) for row in page],
                                  limit, offset, total)
