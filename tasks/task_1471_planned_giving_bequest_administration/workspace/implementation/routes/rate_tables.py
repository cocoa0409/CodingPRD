"""Rate tables: create / read / ACTIVATE / RETIRE (PRD 2.7, 3.2)."""
from flask import Blueprint

import store
from domain import lookup, table_window, view, windows_overlap
from envelope import success
from errors import ApiError
from security import ALL_ROLES, require_roles
from store import base_fields, touch
from validate import get_body, validate_body

bp = Blueprint("rate_tables", __name__)

ACTIONS = ("ACTIVATE", "RETIRE")


def _check_window_overlap(candidate, exclude_id=None):
    c_start, c_end = table_window(candidate)
    for other in store.rate_tables.values():
        if other["id"] == exclude_id or other["id"] == candidate.get("id"):
            continue
        if other["status"] not in ("DRAFT", "ACTIVE"):
            continue
        o_start, o_end = table_window(other)
        if windows_overlap(c_start, c_end, o_start, o_end):
            raise ApiError(
                "ERR_RATE_WINDOW_OVERLAP",
                409,
                "Window intersects another DRAFT/ACTIVE rate table",
            )


@bp.post("/giving/rate-tables")
@require_roles("ComplianceOfficer")
def create_rate_table():
    body = get_body()
    validate_body(
        body,
        {
            "label": ("str", True, None),
            "discount_rate_bps": ("int", True, None),
            "effective_from": ("datetime", True, None),
            "effective_to": ("datetime", False, None),
        },
    )
    table = base_fields()
    table.update(
        {
            "label": body["label"],
            "discount_rate_bps": body["discount_rate_bps"],
            "effective_from": body["effective_from"],
            "effective_to": body.get("effective_to"),
            "status": "DRAFT",
        }
    )
    _check_window_overlap(table)
    store.rate_tables[table["id"]] = table
    return success(view(table), 201)


@bp.get("/giving/rate-tables/<rate_table_id>")
@require_roles(*ALL_ROLES)
def get_rate_table(rate_table_id):
    return success(view(lookup(store.rate_tables, rate_table_id, "RateTable")), 200)


@bp.post("/giving/rate-tables/<rate_table_id>/transition")
@require_roles("ComplianceOfficer")
def rate_table_transition(rate_table_id):
    table = lookup(store.rate_tables, rate_table_id, "RateTable")
    body = get_body()
    validate_body(body, {"action": ("str", True, ACTIONS)})
    action = body["action"]

    if action == "ACTIVATE":
        if table["status"] != "DRAFT":
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Cannot ACTIVATE from %s" % table["status"],
            )
        _check_window_overlap(table, exclude_id=table["id"])
        table["status"] = "ACTIVE"
    else:  # RETIRE
        if table["status"] not in ("DRAFT", "ACTIVE"):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Cannot RETIRE from %s" % table["status"],
            )
        table["status"] = "RETIRED"

    touch(table)
    return success(view(table), 200)
