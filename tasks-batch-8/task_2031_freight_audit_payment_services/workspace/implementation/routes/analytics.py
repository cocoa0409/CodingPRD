"""AnalyticsExport endpoints."""

from db import STORE, create_entity, touch, public, sort_default, parse_date
from errors import ApiError, ERR_EXPORT_RANGE_INVALID, ERR_INVALID_REQUEST
from middleware import (authenticate, require_roles, guard_read_scope,
                        require_client_active, resolve, READ_ROLES)
from response import success_object, success_list
from services import compute_export
from validate import get_body, check_shape, parse_pagination

AUDIT_STATUSES = ["RECEIVED", "CAPTURED", "RATED", "CLEARED", "EXCEPTION", "VOIDED"]


def register(app):

    @app.route("/fap/clients/<cid>/analytics-exports", methods=["POST"])
    def create_export(cid):
        uid, role = authenticate()
        require_roles(role, {"FinanceController"})
        client = resolve(STORE.clients, cid)
        require_client_active(client)
        body = get_body(allow_empty=False)
        include_statuses = body.get("include_statuses")
        check_shape(body, {
            "date_from": {"kind": "date", "required": True},
            "date_to": {"kind": "date", "required": True},
            "include_statuses": {"kind": "array", "required": False},
        })
        if include_statuses is not None:
            for value in include_statuses:
                if value not in AUDIT_STATUSES:
                    raise ApiError(ERR_INVALID_REQUEST, 400,
                                   "Invalid audit_status in include_statuses")
        if parse_date(body["date_to"]) < parse_date(body["date_from"]):
            raise ApiError(ERR_EXPORT_RANGE_INVALID, 422,
                           "date_to earlier than date_from")
        rows = [inv for inv in STORE.invoices.values()
                if inv["client_id"] == cid
                and body["date_from"] <= inv["invoice_date"] <= body["date_to"]]
        if include_statuses is not None:
            rows = [inv for inv in rows if inv["audit_status"] in include_statuses]
        row_count, checksum = compute_export(rows)
        export = create_entity(STORE.exports, {
            "client_id": cid,
            "date_from": body["date_from"],
            "date_to": body["date_to"],
            "include_statuses": include_statuses,
            "row_count": row_count,
            "checksum": checksum,
            "status": "COMPLETED",
        })
        return success_object(public(export), status=201)

    @app.route("/fap/clients/<cid>/analytics-exports", methods=["GET"])
    def list_exports(cid):
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        client = guard_read_scope(role, uid, "client", STORE.clients.get(cid))
        limit, offset = parse_pagination()
        rows = [e for e in STORE.exports.values() if e["client_id"] == cid]
        rows = sort_default(rows)
        total = len(rows)
        page = rows[offset:offset + limit]
        return success_list([public(e) for e in page], limit, offset, total)
