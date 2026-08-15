"""ClientAccount endpoints: lifecycle, savings rollup, daily sweep."""

import db
from db import STORE, create_entity, touch, public, sort_default, today, parse_date
from errors import ApiError, ERR_INVALID_STATE, ERR_CLIENT_NOT_SETTLED
from middleware import (authenticate, require_roles, guard_read_scope,
                        in_read_scope, require_client_active, resolve,
                        READ_ROLES)
from response import success_object, success_list
from services import savings_rollup
from validate import get_body, check_shape, parse_pagination


def serialize_client(client):
    out = public(client)
    rollup = savings_rollup(client)
    out["savings_realized_minor"] = rollup["savings_realized_minor"]
    out["outstanding_liability_minor"] = rollup["outstanding_liability_minor"]
    return out


def register(app):

    @app.route("/fap/clients", methods=["POST"])
    def create_client():
        uid, role = authenticate()
        require_roles(role, {"FapAdmin"})
        body = get_body(allow_empty=False)
        check_shape(body, {
            "name": {"kind": "string", "required": True},
            "home_country": {"kind": "string", "required": True},
            "home_currency": {"kind": "string", "required": True},
            "audit_tolerance_minor": {"kind": "integer", "required": False},
            "audit_tolerance_pct_bp": {"kind": "integer", "required": False},
            "dispute_window_days": {"kind": "integer", "required": False},
        })
        client = create_entity(STORE.clients, {
            "name": body["name"],
            "home_country": body["home_country"],
            "home_currency": body["home_currency"],
            "audit_tolerance_minor": body.get("audit_tolerance_minor", 500),
            "audit_tolerance_pct_bp": body.get("audit_tolerance_pct_bp", 200),
            "dispute_window_days": body.get("dispute_window_days", 30),
            "status": "ONBOARDING",
        })
        return success_object(serialize_client(client), status=201)

    @app.route("/fap/clients", methods=["GET"])
    def list_clients():
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        limit, offset = parse_pagination()
        rows = [c for c in STORE.clients.values()
                if in_read_scope(role, uid, "client", c)]
        rows = sort_default(rows)
        total = len(rows)
        page = rows[offset:offset + limit]
        return success_list([serialize_client(c) for c in page], limit, offset, total)

    @app.route("/fap/clients/<cid>", methods=["GET"])
    def get_client(cid):
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        client = guard_read_scope(role, uid, "client", STORE.clients.get(cid))
        return success_object(serialize_client(client))

    @app.route("/fap/clients/<cid>/activate", methods=["POST"])
    def activate_client(cid):
        uid, role = authenticate()
        require_roles(role, {"FapAdmin"})
        client = resolve(STORE.clients, cid)
        body = get_body()
        check_shape(body, {})
        if client["status"] not in ("ONBOARDING", "SUSPENDED"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Client cannot be activated from %s" % client["status"])
        client["status"] = "ACTIVE"
        touch(client)
        return success_object(serialize_client(client))

    @app.route("/fap/clients/<cid>/suspend", methods=["POST"])
    def suspend_client(cid):
        uid, role = authenticate()
        require_roles(role, {"FapAdmin"})
        client = resolve(STORE.clients, cid)
        body = get_body()
        check_shape(body, {})
        if client["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Client cannot be suspended from %s" % client["status"])
        client["status"] = "SUSPENDED"
        touch(client)
        return success_object(serialize_client(client))

    @app.route("/fap/clients/<cid>/terminate", methods=["POST"])
    def terminate_client(cid):
        uid, role = authenticate()
        require_roles(role, {"FapAdmin"})
        client = resolve(STORE.clients, cid)
        body = get_body()
        check_shape(body, {})
        if client["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Client cannot be terminated from %s" % client["status"])
        rollup = savings_rollup(client)
        open_invoices = any(
            inv["client_id"] == cid
            and inv["payment_status"] in ("UNPAID", "SCHEDULED")
            for inv in STORE.invoices.values()
        )
        if rollup["outstanding_liability_minor"] != 0 or open_invoices:
            raise ApiError(ERR_CLIENT_NOT_SETTLED, 409,
                           "Terminate attempted with outstanding liability or unpaid invoices")
        client["status"] = "TERMINATED"
        touch(client)
        return success_object(serialize_client(client))

    @app.route("/fap/clients/<cid>/savings", methods=["GET"])
    def get_savings(cid):
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        client = guard_read_scope(role, uid, "client", STORE.clients.get(cid))
        return success_object(savings_rollup(client))

    @app.route("/fap/clients/<cid>/run_daily_sweep", methods=["POST"])
    def run_daily_sweep(cid):
        uid, role = authenticate()
        require_roles(role, {"FapAdmin", "System"})
        client = resolve(STORE.clients, cid)
        require_client_active(client)
        body = get_body()
        check_shape(body, {})
        today_d = today()

        expired_contract_ids = []
        for contract in list(STORE.contracts.values()):
            if contract["client_id"] != cid:
                continue
            if contract["status"] != "ACTIVE":
                continue
            if parse_date(contract["effective_to"]) <= today_d:
                contract["status"] = "EXPIRED"
                touch(contract)
                expired_contract_ids.append(contract["id"])

        expired_exception_ids = []
        window = client["dispute_window_days"]
        for exc in list(STORE.exceptions.values()):
            if exc["client_id"] != cid:
                continue
            if exc["status"] not in ("OPEN", "CARRIER_NOTIFIED", "CARRIER_RESPONDED"):
                continue
            deadline = parse_date(db.add_days(exc["opened_date"], window))
            if today_d > deadline:
                exc["status"] = "EXPIRED"
                touch(exc)
                expired_exception_ids.append(exc["id"])

        expired_contract_ids.sort()
        expired_exception_ids.sort()
        return success_object({
            "expired_contract_ids": expired_contract_ids,
            "expired_exception_ids": expired_exception_ids,
        })
