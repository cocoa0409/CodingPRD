"""Perfection report routes (client-scoped generation, list, get)."""
from flask import Blueprint

import errors
from db import store
from middleware import auth, body, check_client_ownership, opt_int, pagination_params, req_enum, require_role
from response import ok, ok_list
from services import REPORT_MODES, generate_perfection_report, report_json

bp = Blueprint("reports", __name__)


def _client_or_404(client_id):
    client = store.clients.get(client_id)
    if client is None:
        raise errors.err_not_found("client")
    return client


@bp.post("/client-accounts/<client_id>/perfection-reports")
def create_perfection_report(client_id):
    auth()
    data = body()
    # Priority 2: structural.
    mode = req_enum(data, "mode", REPORT_MODES)
    horizon_days = opt_int(data, "horizon_days", default=90)
    if horizon_days < 0:
        raise errors.err_invalid_request("horizon_days must be >= 0")
    # Priority 3: role.
    user_id, role = auth()
    require_role(role, "ClientManager", "FilingSpecialist")
    # Priority 4: ownership.
    check_client_ownership(role, user_id, client_id)
    # Priority 5: existence.
    _client_or_404(client_id)
    report = generate_perfection_report(client_id, mode, horizon_days)
    return ok(report_json(report), 201)


@bp.get("/client-accounts/<client_id>/perfection-reports")
def list_perfection_reports(client_id):
    user_id, role = auth()
    check_client_ownership(role, user_id, client_id)
    _client_or_404(client_id)
    limit, offset = pagination_params()
    records = [r for r in store.reports.values() if r["client_id"] == client_id]
    items = [report_json(r) for r in records]
    return ok_list(items[offset:offset + limit], len(items), limit, offset)


@bp.get("/perfection-reports/<report_id>")
def get_perfection_report(report_id):
    auth()
    report = store.reports.get(report_id)
    if report is None:
        raise errors.err_not_found("report")
    return ok(report_json(report))
