"""Revision request endpoints (PRD 3.7): corrections and reconsiderations."""

from datetime import timedelta

from flask import request

import webbase as base
import services
import store
from errors import ApiError
from timeutil import clock


def register(app):
    @app.route("/appraisal/orders/<order_id>/revision-requests", methods=["POST"])
    def create_revision_request(order_id):
        base.auth.require_roles("ClientUser", "FirmAdmin")
        body = base.read_body()
        # PRD 2.7 rung 2 (ownership): evaluated when the path id resolves, so
        # a ClientUser touching another client's order is refused before any
        # body inspection; an unresolvable id defers to rungs 3 then 4.
        order = store.orders.get(order_id)
        if (
            base.auth.role == "ClientUser"
            and order is not None
            and order["client_id"] != base.auth.user_id
        ):
            raise ApiError("ERR_NOT_RESOURCE_OWNER")
        # PRD 2.7 rung 3 (request shape) precedes rung 4 (reference resolution).
        services.require_fields(body, ["kind", "detail", "expected_order_version"])
        kind = services.require_enum(body, "kind", services.REVISION_KINDS)
        services.require_string(body, "detail")
        expected = body.get("expected_order_version")
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise ApiError("ERR_VALIDATION", "expected_order_version must be an integer.")
        if order is None:
            raise ApiError("ERR_ORDER_NOT_FOUND")

        # State overlay (PRD 2.7 rung 5): the order must be DELIVERED.
        if order["status"] != "DELIVERED":
            raise ApiError("ERR_ORDER_NOT_DELIVERED")

        # OCC (rung 6): the caller's view of the order must be current.
        if expected != order["version"]:
            raise ApiError("ERR_STALE_ORDER_VERSION")

        submitted_value = None
        if kind == "RECONSIDERATION_OF_VALUE":
            if "submitted_value_cents" not in body or body["submitted_value_cents"] is None:
                raise ApiError("ERR_VALIDATION", "submitted_value_cents is required for RECONSIDERATION_OF_VALUE.")
            submitted_value = services.require_int(body, "submitted_value_cents", strictly_positive=True)
            report = services.report_for_order(order["id"])
            current_value = report["value_conclusion_cents"] if report else None
            if current_value is not None and submitted_value == current_value:
                raise ApiError("ERR_VALIDATION", "submitted_value_cents must differ from the report's value conclusion.")
            # ROV window: within 90 days of first_delivered_at (PRD 3.7).
            first = order["_first_delivered_dt"]
            if first is None or clock.now > first + timedelta(days=services.ROV_WINDOW_DAYS):
                raise ApiError("ERR_ROV_WINDOW_EXPIRED")
        elif "submitted_value_cents" in body and body["submitted_value_cents"] is not None:
            submitted_value = services.require_int(body, "submitted_value_cents", strictly_positive=True)

        # A new OPEN request supersedes any previously OPEN one on the order.
        for req in store.revision_requests.values():
            if req["order_id"] == order["id"] and req["status"] == "OPEN":
                req["status"] = "SUPERSEDED"
                store.touch(req)

        row = store.new_row(
            store.revision_requests,
            order_id=order["id"],
            kind=kind,
            detail=body["detail"],
            submitted_value_cents=submitted_value,
            status="OPEN",
            revision_fee_charged_cents=None,
            rebuttal=None,
        )
        # Creating the request advances the order's version (PRD 2.10).
        store.touch(order)
        return base.obj(row, 201)

    @app.route("/appraisal/revision-requests/<req_id>", methods=["GET"])
    def get_revision_request(req_id):
        base.auth.require_roles("FirmAdmin", "ClientUser", "Appraiser")
        row = services.get_revision_request(req_id)
        if base.auth.role == "ClientUser":
            order = services.get_order(row["order_id"])
            if order["client_id"] != base.auth.user_id:
                raise ApiError("ERR_NOT_RESOURCE_OWNER")
        return base.obj(row)

    @app.route("/appraisal/revision-requests", methods=["GET"])
    def list_revision_requests():
        base.auth.require_roles("FirmAdmin", "ClientUser")
        order_id = request.args.get("order_id")
        status = request.args.get("status")
        rows = store.revision_requests.values()
        if base.auth.role == "ClientUser":
            own_orders = {o["id"] for o in store.orders.values() if o["client_id"] == base.auth.user_id}
            rows = [r for r in rows if r["order_id"] in own_orders]
        if order_id is not None:
            rows = [r for r in rows if r["order_id"] == order_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        return base.listing(rows, request.args)

    @app.route("/appraisal/revision-requests/<req_id>/accept", methods=["POST"])
    def accept_revision_request(req_id):
        base.auth.require_roles("FirmAdmin")
        req = services.get_revision_request(req_id)
        if req["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE")
        order = services.get_order(req["order_id"])
        if order["status"] != "DELIVERED":
            raise ApiError("ERR_INVALID_STATE")
        client = services.get_client(order["client_id"])
        # Fee from the (client, tier) schedule effective as-of first delivery;
        # retail fallback 15000 when no window covers that instant.
        fee = services.revision_fee_for(order, client)
        req["revision_fee_charged_cents"] = fee
        req["status"] = "ACCEPTED"
        store.touch(req)
        order["fee_current_cents"] = (order["fee_current_cents"] or 0) + fee
        order["revision_fees_collected_cents"] += fee
        order["status"] = "IN_REVISION"
        store.touch(order)
        report = services.report_for_order(order["id"])
        if report is not None and report["status"] == "DELIVERED":
            report["status"] = "UNDER_REVISION"
            report["revision_round"] += 1
            store.touch(report)
        # Every LOCKED comparable returns to VERIFIED so the analysis can be
        # reworked.
        for comp in store.comparables.values():
            if comp["order_id"] == order["id"] and comp["status"] == "LOCKED":
                comp["status"] = "VERIFIED"
                store.touch(comp)
        services.file_workfile(order, "REVISION_CORRESPONDENCE")
        return base.obj(req)

    @app.route("/appraisal/revision-requests/<req_id>/rebut", methods=["POST"])
    def rebut_revision_request(req_id):
        base.auth.require_roles("FirmAdmin")
        req = services.get_revision_request(req_id)
        if req["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE")
        body = base.read_body()
        services.require_fields(body, ["rebuttal"])
        rebuttal = services.require_string(body, "rebuttal")
        req["rebuttal"] = rebuttal
        req["status"] = "REBUTTED"
        store.touch(req)
        # No fee change; order and report remain DELIVERED.
        return base.obj(req)
