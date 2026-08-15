"""Panel membership endpoints (PRD 3.1)."""

from flask import request

import webbase as base
import services
import store
from errors import ApiError


def register(app):
    @app.route("/appraisal/panel-memberships", methods=["POST"])
    def create_membership():
        base.auth.require_roles("FirmAdmin")
        body = base.read_body()
        services.require_fields(body, ["client_id", "appraiser_id"])
        client_id = body["client_id"]
        appraiser_id = body["appraiser_id"]
        client = services.get_client(client_id)
        appraiser = services.get_appraiser(appraiser_id)
        # At most one ACTIVE row per (client, appraiser) pair.
        for membership in store.panel_memberships.values():
            if (
                membership["client_id"] == client["id"]
                and membership["appraiser_id"] == appraiser["id"]
                and membership["status"] == "ACTIVE"
            ):
                raise ApiError("ERR_DUPLICATE_PANEL_MEMBERSHIP")
        row = store.new_row(
            store.panel_memberships,
            client_id=client["id"],
            appraiser_id=appraiser["id"],
            status="ACTIVE",
        )
        return base.obj(row, 201)

    @app.route("/appraisal/panel-memberships/<membership_id>", methods=["GET"])
    def get_membership(membership_id):
        base.auth.require_roles("FirmAdmin")
        return base.obj(services.get_membership(membership_id))

    @app.route("/appraisal/panel-memberships/<membership_id>/remove", methods=["POST"])
    def remove_membership(membership_id):
        base.auth.require_roles("FirmAdmin")
        row = services.get_membership(membership_id)
        if row["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")
        row["status"] = "REMOVED"
        store.touch(row)
        return base.obj(row)

    @app.route("/appraisal/panel-memberships", methods=["GET"])
    def list_memberships():
        base.auth.require_roles("FirmAdmin")
        client_id = request.args.get("client_id")
        appraiser_id = request.args.get("appraiser_id")
        status = request.args.get("status")
        rows = store.panel_memberships.values()
        if client_id is not None:
            rows = [r for r in rows if r["client_id"] == client_id]
        if appraiser_id is not None:
            rows = [r for r in rows if r["appraiser_id"] == appraiser_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        return base.listing(rows, request.args)
