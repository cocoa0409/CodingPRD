"""Discipline taxonomy endpoints (PRD 3.1)."""

from decimal import Decimal

from flask import Blueprint

import db
import middleware
import response
import serialize
import validate
from constants import READ_ROLES, SYSTEM_ADMIN, TERMINAL_DEGREE_LEVELS
from db import store, touch
from errors import ApiError
from routes.common import list_response, match
from services import lookup

bp = Blueprint("disciplines", __name__)

DEFAULT_MIN_HOURS = Decimal(18)


def _closes_cycle(node_id, parent_id):
    """True when pointing node_id at parent_id would close a loop."""
    if parent_id is None:
        return False
    if parent_id == node_id:
        return True
    seen = set()
    current = parent_id
    while current is not None:
        if current == node_id:
            return True
        if current in seen:
            return True
        seen.add(current)
        node = store.disciplines.get(current)
        current = node.get("parent_discipline_id") if node else None
    return False


def _require_unique_code(code, skip_id=None):
    for row in db.ordered(store.disciplines):
        if row["id"] == skip_id:
            continue
        if row["code"] == code:
            raise ApiError("ERR_DUPLICATE_DISCIPLINE_CODE")


@bp.route("/disciplines", methods=["POST"])
def create_discipline():
    middleware.require_role(SYSTEM_ADMIN)
    payload = validate.body()

    code = validate.req_str(payload, "code")
    name = validate.req_str(payload, "name")
    parent_id = validate.opt_str(payload, "parent_discipline_id")
    min_hours = validate.opt_num(payload, "min_graduate_credit_hours",
                                default=DEFAULT_MIN_HOURS, minimum=0)
    level = validate.req_enum(payload, "required_terminal_degree_level",
                              TERMINAL_DEGREE_LEVELS)

    if parent_id is not None:
        lookup.discipline(parent_id)

    _require_unique_code(code)

    row = db.new_row(
        code=code,
        name=name,
        parent_discipline_id=parent_id,
        min_graduate_credit_hours=min_hours,
        required_terminal_degree_level=level,
    )
    store.disciplines[row["id"]] = row
    return response.created(serialize.discipline(row))


@bp.route("/disciplines/<discipline_id>", methods=["POST"])
def update_discipline(discipline_id):
    middleware.require_role(SYSTEM_ADMIN)
    payload = validate.body()

    name = validate.opt_str(payload, "name", allow_empty=False)
    parent_given = "parent_discipline_id" in payload
    parent_id = validate.opt_str(payload, "parent_discipline_id")
    min_hours = validate.opt_num(payload, "min_graduate_credit_hours", minimum=0)
    level = validate.opt_enum(payload, "required_terminal_degree_level",
                              TERMINAL_DEGREE_LEVELS)

    row = lookup.discipline(discipline_id)

    if parent_id is not None:
        lookup.discipline(parent_id)

    if parent_given and _closes_cycle(row["id"], parent_id):
        raise ApiError("ERR_DISCIPLINE_CYCLE")

    if name is not None:
        row["name"] = name
    if parent_given:
        row["parent_discipline_id"] = parent_id
    if min_hours is not None:
        row["min_graduate_credit_hours"] = min_hours
    if level is not None:
        row["required_terminal_degree_level"] = level
    touch(row)
    return response.ok(serialize.discipline(row))


@bp.route("/disciplines/<discipline_id>", methods=["GET"])
def read_discipline(discipline_id):
    middleware.require_role(*READ_ROLES)
    row = lookup.discipline(discipline_id)
    return response.ok(serialize.discipline(row))


@bp.route("/disciplines", methods=["GET"])
def list_disciplines():
    middleware.require_role(*READ_ROLES)
    parent_id = validate.q_str("parent_discipline_id")
    code = validate.q_str("code")
    level = validate.q_enum("required_terminal_degree_level", TERMINAL_DEGREE_LEVELS)
    rows = [r for r in db.ordered(store.disciplines)
            if match(r, "parent_discipline_id", parent_id)
            and match(r, "code", code)
            and match(r, "required_terminal_degree_level", level)]
    return list_response(rows, serialize.discipline)
