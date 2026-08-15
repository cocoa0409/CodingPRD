"""Client endpoints."""
from flask import Blueprint, request

import db
from middleware import require_roles
from response import success_object, success_list
from routes.common import (
    apply_pagination,
    get_json_body,
    lookup_or_404,
    parse_pagination,
    require_date,
    require_str,
)
from services.calculations import compute_age_years, SENIOR_AGE
from services.serializers import client_view, contract_view

bp = Blueprint("clients", __name__)

ALL_ROLES = (
    "CarrierAdmin", "Producer", "SuitabilityReviewer",
    "Principal", "ComplianceOfficer", "OperationsDesk",
)


@bp.route("/clients", methods=["POST"])
def create_client():
    require_roles("Producer", "CarrierAdmin")
    body = get_json_body()
    full_name = require_str(body, "full_name")
    date_of_birth = require_date(body, "date_of_birth")
    state_code = require_str(body, "state_code")

    now_dt = db.parse_iso(db.now_iso())
    age_years = compute_age_years(date_of_birth, now_dt)
    is_senior = age_years >= SENIOR_AGE

    now = db.now_formatted()
    client = {
        "id": db.new_id(),
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "state_code": state_code,
        "age_years": age_years,
        "is_senior": is_senior,
        "last_rescinded_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.clients[client["id"]] = client
    return success_object(client_view(client), 201)


@bp.route("/clients/<cid>", methods=["GET"])
def get_client(cid):
    require_roles(*ALL_ROLES)
    c = lookup_or_404(db.clients, cid, "Client")
    return success_object(client_view(c), 200)


@bp.route("/clients/<cid>/contracts", methods=["GET"])
def list_client_contracts(cid):
    require_roles(*ALL_ROLES)
    c = lookup_or_404(db.clients, cid, "Client")
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    items = [ct for ct in db.contracts.values() if ct["client_id"] == c["id"]]
    if status_filter:
        items = [ct for ct in items if ct["status"] == status_filter]
    page, total = apply_pagination(items, limit, offset)
    return success_list([contract_view(ct) for ct in page], limit, offset, total, 200)
