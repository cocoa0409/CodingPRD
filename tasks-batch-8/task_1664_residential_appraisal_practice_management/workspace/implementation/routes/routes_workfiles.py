"""Workfile record endpoints (PRD 3.8): manual filing and retention purge."""

from flask import request

import webbase as base
import services
import store
from errors import ApiError
from timeutil import clock


def register(app):
    @app.route("/appraisal/workfile-records", methods=["POST"])
    def create_workfile_record():
        base.auth.require_roles("FirmAdmin")
        body = base.read_body()
        services.require_fields(body, ["order_id", "snapshot_type"])
        snapshot_type = services.require_enum(body, "snapshot_type", services.SNAPSHOT_TYPES)
        order = services.get_order(body["order_id"])
        # Manual filing is only possible while the order is non-terminal.
        if order["status"] in ("COMPLETED", "CANCELLED"):
            raise ApiError("ERR_INVALID_STATE")
        row = services.file_workfile(order, snapshot_type)
        return base.obj(row, 201)

    @app.route("/appraisal/workfile-records/<record_id>", methods=["GET"])
    def get_workfile_record(record_id):
        base.auth.require_roles("FirmAdmin", "ComplianceOfficer")
        return base.obj(services.get_workfile(record_id))

    @app.route("/appraisal/workfile-records", methods=["GET"])
    def list_workfile_records():
        base.auth.require_roles("FirmAdmin", "ComplianceOfficer")
        order_id = request.args.get("order_id")
        snapshot_type = request.args.get("snapshot_type")
        status = request.args.get("status")
        rows = store.workfile_records.values()
        if order_id is not None:
            rows = [r for r in rows if r["order_id"] == order_id]
        if snapshot_type is not None:
            rows = [r for r in rows if r["snapshot_type"] == snapshot_type]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        return base.listing(rows, request.args)

    @app.route("/appraisal/workfile-records/<record_id>/purge", methods=["POST"])
    def purge_workfile_record(record_id):
        base.auth.require_roles("ComplianceOfficer")
        record = services.get_workfile(record_id)
        if record["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")
        # retention_until must be set and strictly before the logical clock.
        retention = record["_retention_dt"]
        if retention is None or not (retention < clock.now):
            raise ApiError("ERR_RETENTION_NOT_EXPIRED")
        order = services.get_order(record["order_id"])
        if order["open_complaint_count"] != 0:
            raise ApiError("ERR_COMPLIANCE_HOLD_ACTIVE")
        record["status"] = "PURGED"
        record["purged_at"] = store.now_string()
        store.touch(record)
        return base.obj(record)
