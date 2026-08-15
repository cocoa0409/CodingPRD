"""Client endpoints (PRD 3.1)."""

from flask import request

import webbase as base
import services
import store
from errors import ApiError


def register(app):
    @app.route("/appraisal/clients", methods=["POST"])
    def create_client():
        base.auth.require_roles("FirmAdmin")
        body = base.read_body()
        services.require_fields(body, ["name", "client_type", "contact_email", "default_turn_time_days"])
        name = services.require_string(body, "name")
        client_type = services.require_enum(body, "client_type", services.CLIENT_TYPES)
        contact_email = services.require_string(body, "contact_email")
        turn_days = services.require_int(body, "default_turn_time_days", minimum=1)
        row = store.new_row(
            store.clients,
            name=name,
            client_type=client_type,
            contact_email=contact_email,
            default_turn_time_days=turn_days,
            status="ACTIVE",
        )
        return base.obj(row, 201)

    @app.route("/appraisal/clients/<client_id>", methods=["GET"])
    def get_client(client_id):
        base.auth.require_roles("FirmAdmin", "ClientUser")
        row = services.get_client(client_id)
        if base.auth.role == "ClientUser" and base.auth.user_id != row["id"]:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")
        return base.obj(row)

    @app.route("/appraisal/clients", methods=["GET"])
    def list_clients():
        base.auth.require_roles("FirmAdmin")
        status = request.args.get("status")
        rows = [r for r in store.clients.values() if status is None or r["status"] == status]
        return base.listing(rows, request.args)

    @app.route("/appraisal/clients/<client_id>/suspend", methods=["POST"])
    def suspend_client(client_id):
        base.auth.require_roles("FirmAdmin")
        row = services.get_client(client_id)
        if row["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")
        row["status"] = "SUSPENDED"
        store.touch(row)
        return base.obj(row)

    @app.route("/appraisal/clients/<client_id>/reactivate", methods=["POST"])
    def reactivate_client(client_id):
        base.auth.require_roles("FirmAdmin")
        row = services.get_client(client_id)
        if row["status"] != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE")
        row["status"] = "ACTIVE"
        store.touch(row)
        return base.obj(row)

    @app.route("/appraisal/clients/<client_id>/terminate", methods=["POST"])
    def terminate_client(client_id):
        base.auth.require_roles("FirmAdmin")
        row = services.get_client(client_id)
        if row["status"] not in ("ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE")
        row["status"] = "TERMINATED"
        store.touch(row)
        # PRD 3.1: termination removes every ACTIVE panel membership of the client.
        for membership in store.panel_memberships.values():
            if membership["client_id"] == row["id"] and membership["status"] == "ACTIVE":
                membership["status"] = "REMOVED"
                store.touch(membership)
        return base.obj(row)
