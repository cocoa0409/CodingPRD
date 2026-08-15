"""Complaint endpoints (PRD 3.8): intake, response workflow, sanction cascade."""

from datetime import timedelta

from flask import request

import webbase as base
import services
import store
from errors import ApiError
from timeutil import clock, render_instant


def _release_holds_if_clear(order):
    """When the last open complaint closes, every LEGAL_HOLD record returns to
    ACTIVE."""
    if order["open_complaint_count"] == 0:
        for record in store.workfile_records.values():
            if record["order_id"] == order["id"] and record["status"] == "LEGAL_HOLD":
                record["status"] = "ACTIVE"
                store.touch(record)


def register(app):
    @app.route("/appraisal/complaints", methods=["POST"])
    def create_complaint():
        base.auth.require_roles("FirmAdmin", "ComplianceOfficer")
        body = base.read_body()
        services.require_fields(body, ["order_id", "respondent_appraiser_id", "description"])
        services.require_string(body, "description")
        order = services.get_order(body["order_id"])
        respondent = services.get_appraiser(body["respondent_appraiser_id"])
        # State overlay (PRD 2.7 rung 5): DELIVERED or COMPLETED orders only.
        if order["status"] not in ("DELIVERED", "COMPLETED"):
            raise ApiError("ERR_ORDER_NOT_DELIVERED")
        received = clock.now
        due = received + timedelta(days=services.RESPONSE_DUE_DAYS)
        row = store.new_row(
            store.complaints,
            order_id=order["id"],
            respondent_appraiser_id=respondent["id"],
            description=body["description"],
            received_at=render_instant(received),
            response_due_at=render_instant(due),
            response_text=None,
            status="RECEIVED",
            closed_at=None,
            _received_dt=received,
            _response_due_dt=due,
            _closed_dt=None,
        )
        # Intake sweeps every ACTIVE workfile record of the order to LEGAL_HOLD
        # and raises the order's open-complaint count.
        for record in store.workfile_records.values():
            if record["order_id"] == order["id"] and record["status"] == "ACTIVE":
                record["status"] = "LEGAL_HOLD"
                store.touch(record)
        order["open_complaint_count"] += 1
        store.touch(order)
        return base.obj(row, 201)

    @app.route("/appraisal/complaints/<complaint_id>", methods=["GET"])
    def get_complaint(complaint_id):
        base.auth.require_roles("FirmAdmin", "ComplianceOfficer")
        return base.obj(services.get_complaint(complaint_id))

    @app.route("/appraisal/complaints", methods=["GET"])
    def list_complaints():
        base.auth.require_roles("FirmAdmin", "ComplianceOfficer")
        order_id = request.args.get("order_id")
        respondent = request.args.get("respondent_appraiser_id")
        status = request.args.get("status")
        rows = store.complaints.values()
        if order_id is not None:
            rows = [r for r in rows if r["order_id"] == order_id]
        if respondent is not None:
            rows = [r for r in rows if r["respondent_appraiser_id"] == respondent]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        return base.listing(rows, request.args)

    @app.route("/appraisal/complaints/<complaint_id>/draft-response", methods=["POST"])
    def draft_response(complaint_id):
        base.auth.require_roles("ComplianceOfficer")
        complaint = services.get_complaint(complaint_id)
        if complaint["status"] != "RECEIVED":
            raise ApiError("ERR_INVALID_STATE")
        body = base.read_body()
        services.require_fields(body, ["response_text"])
        complaint["response_text"] = services.require_string(body, "response_text")
        complaint["status"] = "RESPONSE_DRAFTED"
        store.touch(complaint)
        return base.obj(complaint)

    @app.route("/appraisal/complaints/<complaint_id>/submit-response", methods=["POST"])
    def submit_response(complaint_id):
        base.auth.require_roles("ComplianceOfficer")
        complaint = services.get_complaint(complaint_id)
        if complaint["status"] != "RESPONSE_DRAFTED":
            raise ApiError("ERR_INVALID_STATE")
        # Hard deadline: the clock must be at or before response_due_at.
        if not (clock.now <= complaint["_response_due_dt"]):
            raise ApiError("ERR_RESPONSE_DEADLINE_PASSED")
        complaint["status"] = "RESPONSE_SUBMITTED"
        store.touch(complaint)
        return base.obj(complaint)

    @app.route("/appraisal/complaints/<complaint_id>/close", methods=["POST"])
    def close_complaint(complaint_id):
        base.auth.require_roles("ComplianceOfficer")
        complaint = services.get_complaint(complaint_id)
        if complaint["status"] != "RESPONSE_SUBMITTED":
            raise ApiError("ERR_INVALID_STATE")
        body = base.read_body()
        services.require_fields(body, ["outcome"])
        outcome = services.require_enum(body, "outcome", services.COMPLAINT_OUTCOMES)
        complaint["status"] = "CLOSED_NO_ACTION" if outcome == "NO_ACTION" else "CLOSED_SANCTIONED"
        complaint["closed_at"] = store.now_string()
        complaint["_closed_dt"] = clock.now
        store.touch(complaint)
        order = services.get_order(complaint["order_id"])
        order["open_complaint_count"] -= 1
        store.touch(order)
        _release_holds_if_clear(order)

        if outcome == "SANCTIONED":
            # The sanction cascade, links in order (PRD 3.8).
            respondent = services.get_appraiser(complaint["respondent_appraiser_id"])
            # Link 1: sanction override forces standing = PANEL_SUSPENDED.
            respondent["sanction_override"] = True
            store.touch(respondent)
            # Link 2a: every ACTIVE panel membership of the respondent is removed.
            for membership in store.panel_memberships.values():
                if membership["appraiser_id"] == respondent["id"] and membership["status"] == "ACTIVE":
                    membership["status"] = "REMOVED"
                    store.touch(membership)
            # Links 2 and 3: working orders fall back to ACCEPTED, unassigned;
            # each such order's open appointments are cancelled.
            for other in store.ordered(store.orders.values()):
                if (
                    other["assigned_appraiser_id"] == respondent["id"]
                    and other["status"] in services.WORKING_ORDER_STATES
                ):
                    services.cascade_unassign(other)
            # Link 4: judicial retention recompute on the complaint's order.
            services.pin_retention(order)
        return base.obj(complaint)
