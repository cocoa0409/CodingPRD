"""Report endpoints (PRD 3.6): drafting, QC, signature, delivery."""

from flask import request

import webbase as base
import services
import store
from errors import ApiError
from timeutil import clock, parse_date


def _require_signer(report):
    if base.auth.user_id != report["signing_appraiser_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_APPRAISER")


def _require_sod(reviewer_id, report):
    if reviewer_id == report["signing_appraiser_id"] or (
        report["co_signer_appraiser_id"] is not None
        and reviewer_id == report["co_signer_appraiser_id"]
    ):
        raise ApiError("ERR_SOD_REVIEWER_CONFLICT")


def register(app):
    @app.route("/appraisal/reports", methods=["POST"])
    def create_report():
        base.auth.require_roles("Appraiser")
        body = base.read_body()
        services.require_fields(body, ["order_id", "report_type", "condition_rating"])
        report_type = services.require_enum(body, "report_type", services.REPORT_TYPES)
        condition = services.require_enum(body, "condition_rating", services.CONDITION_RATINGS)
        order = services.get_order(body["order_id"])
        # PRD 3.6: the order must be IN_ANALYSIS; the one-report-per-order rule
        # is enforced by the state gate (a second attempt finds DRAFTING).
        if order["status"] != "IN_ANALYSIS":
            raise ApiError("ERR_INVALID_STATE")
        if base.auth.user_id != order["assigned_appraiser_id"]:
            raise ApiError("ERR_NOT_ASSIGNED_APPRAISER")
        value = services.value_conclusion(order["id"])
        row = store.new_row(
            store.reports,
            order_id=order["id"],
            report_type=report_type,
            condition_rating=condition,
            value_conclusion_cents=value,
            signing_appraiser_id=order["assigned_appraiser_id"],
            co_signer_appraiser_id=None,
            reviewer_id=None,
            revision_round=0,
            qc_fail_count=0,
            status="DRAFT",
        )
        order["status"] = "DRAFTING"
        store.touch(order)
        services.file_workfile(order, "COMP_DATA")
        return base.obj(row, 201)

    @app.route("/appraisal/reports/<report_id>", methods=["GET"])
    def get_report(report_id):
        base.auth.require_roles("FirmAdmin", "Appraiser", "QCReviewer", "ClientUser")
        row = services.get_report(report_id)
        if base.auth.role == "ClientUser":
            order = services.get_order(row["order_id"])
            if order["client_id"] != base.auth.user_id:
                raise ApiError("ERR_NOT_RESOURCE_OWNER")
        return base.obj(row)

    @app.route("/appraisal/reports", methods=["GET"])
    def list_reports():
        base.auth.require_roles("FirmAdmin")
        order_id = request.args.get("order_id")
        status = request.args.get("status")
        signer = request.args.get("signing_appraiser_id")
        cosigner = request.args.get("co_signer_appraiser_id")
        reviewer = request.args.get("reviewer_id")
        rows = store.reports.values()
        if order_id is not None:
            rows = [r for r in rows if r["order_id"] == order_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        if signer is not None:
            rows = [r for r in rows if r["signing_appraiser_id"] == signer]
        if cosigner is not None:
            rows = [r for r in rows if r["co_signer_appraiser_id"] == cosigner]
        if reviewer is not None:
            rows = [r for r in rows if r["reviewer_id"] == reviewer]
        return base.listing(rows, request.args)

    @app.route("/appraisal/reports/<report_id>/submit-for-qc", methods=["POST"])
    def submit_for_qc(report_id):
        base.auth.require_roles("Appraiser")
        report = services.get_report(report_id)
        if report["status"] not in ("DRAFT", "UNDER_REVISION"):
            raise ApiError("ERR_INVALID_STATE")
        _require_signer(report)
        # Re-derive the value conclusion over currently LOCKED eligible comps.
        value = services.value_conclusion(report["order_id"])
        report["value_conclusion_cents"] = value
        report["status"] = "PENDING_QC"
        store.touch(report)
        order = services.get_order(report["order_id"])
        # DRAFTING -> QC_REVIEW, or IN_REVISION -> QC_REVIEW on resubmission.
        order["status"] = "QC_REVIEW"
        store.touch(order)
        return base.obj(report)

    @app.route("/appraisal/reports/<report_id>/qc-pass", methods=["POST"])
    def qc_pass(report_id):
        base.auth.require_roles("QCReviewer")
        report = services.get_report(report_id)
        if report["status"] != "PENDING_QC":
            raise ApiError("ERR_INVALID_STATE")
        # The reviewer must resolve to an ACTIVE CERTIFIED_RESIDENTIAL appraiser.
        reviewer = services.get_appraiser(base.auth.user_id)
        if reviewer["status"] != "ACTIVE" or reviewer["license_level"] != "CERTIFIED_RESIDENTIAL":
            raise ApiError("ERR_LICENSE_LEVEL_INSUFFICIENT")
        _require_sod(reviewer["id"], report)
        report["reviewer_id"] = reviewer["id"]
        report["status"] = "QC_PASSED"
        store.touch(report)
        return base.obj(report)

    @app.route("/appraisal/reports/<report_id>/qc-fail", methods=["POST"])
    def qc_fail(report_id):
        base.auth.require_roles("QCReviewer")
        report = services.get_report(report_id)
        if report["status"] != "PENDING_QC":
            raise ApiError("ERR_INVALID_STATE")
        _require_sod(base.auth.user_id, report)
        report["qc_fail_count"] += 1
        report["status"] = "DRAFT"
        store.touch(report)
        order = services.get_order(report["order_id"])
        # QC_REVIEW -> IN_REVISION when an ACCEPTED revision request exists on
        # the order, else QC_REVIEW -> DRAFTING.
        has_accepted = any(
            r["order_id"] == order["id"] and r["status"] == "ACCEPTED"
            for r in store.revision_requests.values()
        )
        order["status"] = "IN_REVISION" if has_accepted else "DRAFTING"
        store.touch(order)
        return base.obj(report)

    @app.route("/appraisal/reports/<report_id>/co-sign", methods=["POST"])
    def co_sign(report_id):
        base.auth.require_roles("Appraiser")
        report = services.get_report(report_id)
        if report["status"] not in ("PENDING_QC", "QC_PASSED"):
            raise ApiError("ERR_INVALID_STATE")
        # The co-signer must be the assignee's declared supervisor, personally
        # ACTIVE and CERTIFIED_RESIDENTIAL.
        signer = services.get_appraiser(report["signing_appraiser_id"])
        actor = store.appraisers.get(base.auth.user_id)
        if (
            actor is None
            or signer["supervisor_id"] != actor["id"]
            or actor["status"] != "ACTIVE"
            or actor["license_level"] != "CERTIFIED_RESIDENTIAL"
        ):
            raise ApiError("ERR_SUPERVISOR_SIGNATURE_MISMATCH")
        report["co_signer_appraiser_id"] = actor["id"]
        store.touch(report)
        return base.obj(report)

    @app.route("/appraisal/reports/<report_id>/deliver", methods=["POST"])
    def deliver(report_id):
        base.auth.require_roles("Appraiser")
        report = services.get_report(report_id)
        if report["status"] != "QC_PASSED":
            raise ApiError("ERR_INVALID_STATE")
        _require_signer(report)
        order = services.get_order(report["order_id"])
        if order["requires_supervisor_cosign"] and report["co_signer_appraiser_id"] is None:
            raise ApiError("ERR_SIGNATURE_COSIGN_REQUIRED")
        signer = services.get_appraiser(report["signing_appraiser_id"])
        expiry = parse_date(signer["license_expiry"])
        if expiry is None or not (expiry > clock.today):
            raise ApiError("ERR_LICENSE_EXPIRED")
        if order["open_complaint_count"] != 0:
            raise ApiError("ERR_COMPLIANCE_HOLD_ACTIVE")
        report["status"] = "DELIVERED"
        store.touch(report)
        # Order QC_REVIEW|IN_REVISION -> DELIVERED; first_delivered_at set once.
        # A delivery that closes a revision cycle (an ACCEPTED revision request
        # exists on the order) resolves that request (PRD 3.6-3.7).
        order["status"] = "DELIVERED"
        if order["first_delivered_at"] is None:
            order["first_delivered_at"] = store.now_string()
            order["_first_delivered_dt"] = clock.now
        store.touch(order)
        services.file_workfile(order, "REPORT_PDF")
        services.file_workfile(order, "CERTIFICATION")
        # retention_expiry: pin every non-PURGED workfile record of the order.
        services.pin_retention(order)
        for req in store.revision_requests.values():
            if req["order_id"] == order["id"] and req["status"] == "ACCEPTED":
                req["status"] = "RESOLVED"
                store.touch(req)
        return base.obj(report)
