"""Compliance reports."""
from __future__ import annotations

from flask import Blueprint, g, request

from app.auth import require_auth
from app.errors import make_error
from app.responses import success_array, success_object
from app.services.compliance import file_report
from app.services.serializers import compliance_report_dto
from app.store import store
from app.validation import (
    get_json_body,
    parse_pagination,
    paginate,
    require_enum,
    require_str,
)


bp = Blueprint("compliance", __name__, url_prefix="/fx-risk")

VALID_REPORT_TYPES = {"LARGE_TRADE", "SUSPICIOUS_TRANSACTION", "INTERNAL_CONTROL"}


@bp.route("/reports", methods=["GET"])
@require_auth(["ComplianceOfficer", "RiskOfficer"])
def list_reports():
    with store.lock:
        limit, offset = parse_pagination()
        report_type = request.args.get("report_type")
        reference_trade_id = request.args.get("reference_trade_id")
        if report_type is not None and report_type not in VALID_REPORT_TYPES:
            raise make_error("ERR_VALIDATION", "Unknown report_type.")
        rows = list(store.compliance_reports.values())
        if report_type:
            rows = [r for r in rows if r["report_type"] == report_type]
        if reference_trade_id is not None:
            rows = [r for r in rows if r.get("reference_trade_id") == reference_trade_id]
        # Latest version per (report_type, reference_trade_id) pair
        latest: dict[tuple, dict] = {}
        for r in rows:
            key = (r["report_type"], r.get("reference_trade_id"))
            current = latest.get(key)
            if current is None or r["version"] > current["version"]:
                latest[key] = r
        final = list(latest.values())
        page, total = paginate(final, limit, offset)
        return success_array(
            [compliance_report_dto(r) for r in page],
            limit=limit, offset=offset, total_count=total,
        )


@bp.route("/reports", methods=["POST"])
@require_auth(["ComplianceOfficer"])
def file_compliance_report():
    with store.lock:
        body = get_json_body()
        report_type = require_enum(body, "report_type", VALID_REPORT_TYPES)
        reference_trade_id = body.get("reference_trade_id")
        if reference_trade_id is not None and not isinstance(reference_trade_id, str):
            raise make_error("ERR_VALIDATION", "reference_trade_id must be string or null.")
        payload = body.get("payload")
        if payload is None or not isinstance(payload, dict):
            raise make_error("ERR_VALIDATION", "payload must be an object.")
        row = file_report(
            store,
            report_type=report_type,
            reference_trade_id=reference_trade_id,
            payload=payload,
            filed_by_user_id=g.user_id,
        )
        store.audit(
            event_type="REPORT_FILED",
            actor_user_id=g.user_id,
            actor_role=g.role,
            subject_entity="ComplianceReport",
            subject_id=row["id"],
            before_snapshot=None,
            after_snapshot={"report_type": report_type, "version": row["version"]},
        )
        return success_object(compliance_report_dto(row), status=201)
