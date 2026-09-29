"""Flat reads over the price sheet (PRD 3.3)."""

from flask import Blueprint

from db import db, ordered, serialize
from middleware import (ROLE_AUDITOR, ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY,
                        ROLE_MEMBER, ROLE_SUPPLIER, require_roles)
from response import object_response
from routes.common import (LINE_ITEM_ORIGIN, LINE_ITEM_STATUS, fetch,
                           list_endpoint)

bp = Blueprint("line_items", __name__)

READ_ROLES = (ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY, ROLE_SUPPLIER, ROLE_MEMBER,
              ROLE_AUDITOR)


@bp.route("/coop/contract-line-items", methods=["GET"])
@require_roles(*READ_ROLES)
def list_line_items():
    return list_endpoint(
        lambda: ordered(db.line_items),
        {"contract_id": ("contract_id", None),
         "status": ("status", LINE_ITEM_STATUS),
         "origin": ("origin", LINE_ITEM_ORIGIN)},
    )


@bp.route("/coop/contract-line-items/<line_item_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def read_line_item(line_item_id):
    row = fetch(db.line_items, line_item_id, "ERR_LINE_ITEM_NOT_FOUND")
    return object_response(serialize(row))
