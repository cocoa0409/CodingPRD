"""Foundries (casting/forging suppliers) — PRD 3.2."""

from flask import Blueprint

import domain
from auth import ANY, require_roles
from db import db, new_row, sort_rows
from errors import api_error
from response import list_response, object_response
from validation import (
    filter_value,
    get_body,
    get_string,
    paginate,
    parse_pagination,
)

bp = Blueprint("foundries", __name__)


@bp.post("/valve-mfg/foundries")
def create_foundry():
    require_roles(["ProcurementSpecialist"])
    body = get_body()
    foundry_code = get_string(body, "foundry_code")
    name = get_string(body, "name")
    country_code = get_string(body, "country_code")

    for row in db.foundries.values():
        if row["foundry_code"] == foundry_code:
            raise api_error(
                "ERR_DUPLICATE_CODE",
                "foundry_code '%s' is already in use" % foundry_code,
            )

    row = new_row(
        {
            "foundry_code": foundry_code,
            "name": name,
            "country_code": country_code,
        }
    )
    db.foundries[row["id"]] = row
    return object_response(domain.serialize_foundry(row), 201)


@bp.get("/valve-mfg/foundries")
def list_foundries():
    require_roles(ANY)
    limit, offset = parse_pagination()
    rows = sort_rows(list(db.foundries.values()))
    serialized = [domain.serialize_foundry(r) for r in rows]
    status = filter_value("status")
    country_code = filter_value("country_code")
    if status is not None:
        serialized = [r for r in serialized if r["status"] == status]
    if country_code is not None:
        serialized = [r for r in serialized if r["country_code"] == country_code]
    page, total = paginate(serialized, limit, offset)
    return list_response(page, limit, offset, total)


@bp.get("/valve-mfg/foundries/<foundry_id>")
def get_foundry(foundry_id):
    user_id, role = require_roles(ANY)
    row = domain.find_foundry(foundry_id)
    if role == "SupplierRep" and row["id"] != user_id:
        raise api_error(
            "ERR_FOUNDRY_SCOPE_VIOLATION",
            "a SupplierRep may only read its own foundry record",
        )
    return object_response(domain.serialize_foundry(row))
