"""Client registration and reads (PRD 3.1)."""

import re

from flask import Blueprint

from db import base_row, db
from middleware import (
    ROLE_CLIENT_COUNSEL,
    ROLE_ENGAGEMENT_MANAGER,
    ROLE_QC_LEAD,
    ROLE_STAFFING_COORDINATOR,
    body,
    require_roles,
)
from response import created_response, object_response
from services import compute
from validation import bad, req_str

bp = Blueprint("clients", __name__)

TWO_LETTER = re.compile(r"^[A-Z]{2}$")


@bp.route("/clients", methods=["POST"])
def create_client():
    require_roles(ROLE_ENGAGEMENT_MANAGER)
    payload = body()
    legal_name = req_str(payload, "legal_name", 1, 200)
    primary_state = req_str(payload, "primary_state", 1, 2)
    if not TWO_LETTER.match(primary_state):
        raise bad("'primary_state' must be exactly two uppercase letters.")
    row = base_row()
    row.update({
        "legal_name": legal_name,
        "primary_state": primary_state,
    })
    db.clients[row["id"]] = row
    return created_response(compute.client_out(row))


@bp.route("/clients/<client_id>", methods=["GET"])
def read_client(client_id):
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR,
                  ROLE_QC_LEAD, ROLE_CLIENT_COUNSEL)
    client = compute.get_client(client_id)
    return object_response(compute.client_out(client))
