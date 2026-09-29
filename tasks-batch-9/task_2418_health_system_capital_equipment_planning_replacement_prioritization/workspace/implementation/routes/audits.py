"""Utilization audits and business_case_variance (PRD section 3.10)."""

from decimal import Decimal

from flask import Blueprint

import lookups
import serializers
from db import db, new_row, touch
from errors import ApiError
from middleware import COMPLIANCE_AUDITOR, guard
from numeric import dec, r2
from response import created_response, object_response
from services import cascades
from validation import (body, dt_field, int_field, pagination, q_str, raw_ref,
                        str_field)

bp = Blueprint("audits", __name__)

VOLUME_ATTAINMENT_FLOOR_PCT = Decimal("80.00")
OPEX_VARIANCE_CEILING_PCT = Decimal("10.00")
PENALTY_POINTS_PER_UNDERPERFORMANCE = 10
PENALTY_POINTS_CAP = 20


@bp.route("/capital/requests/<request_id>/audits", methods=["POST"])
@guard(COMPLIANCE_AUDITOR)
def create_audit(request_id):
    request_row = lookups.request_row(request_id)
    data = body()
    ref = raw_ref(data, "installation_project_id")
    if ref is not None:
        lookups.project(ref)

    project_id = str_field(data, "installation_project_id", 1, None)
    start_raw, start = dt_field(data, "audit_window_start")
    end_raw, end = dt_field(data, "audit_window_end")

    project = lookups.project(project_id)

    if request_row["status"] != "IMPLEMENTED":
        raise ApiError("ERR_REQUEST_INVALID_STATE")

    if end <= start:
        raise ApiError("ERR_INVALID_INTERVAL")

    if (project["request_id"] != request_row["id"]
            or project["go_live_at"] is None
            or start < project["_go_live_at"]):
        raise ApiError("ERR_AUDIT_WINDOW_INVALID")

    row = new_row({
        "request_id": request_row["id"],
        "installation_project_id": project["id"],
        "audit_window_start": start_raw,
        "_audit_window_start": start,
        "audit_window_end": end_raw,
        "_audit_window_end": end,
        "projected_annual_volume_snapshot":
            request_row["projected_annual_volume"],
        "baseline_year1_opex_snapshot": request_row["baseline_year1_opex_cents"],
        "actual_annual_volume": None,
        "actual_annual_opex_cents": None,
        "volume_attainment_pct": None,
        "opex_variance_pct": None,
        "status": "SCHEDULED",
    })
    db.audits[row["id"]] = row
    return created_response(serializers.audit(row))


@bp.route("/capital/audits/<audit_id>/collect", methods=["POST"])
@guard(COMPLIANCE_AUDITOR)
def collect_audit(audit_id):
    audit = lookups.audit(audit_id)
    data = body()
    actual_volume = int_field(data, "actual_annual_volume", 0)
    actual_opex = int_field(data, "actual_annual_opex_cents", 0)

    if audit["status"] != "SCHEDULED":
        raise ApiError("ERR_AUDIT_INVALID_STATE")

    request_row = lookups.request_row(audit["request_id"])
    if request_row["status"] != "IMPLEMENTED":
        raise ApiError("ERR_REQUEST_INVALID_STATE")

    # Step 1 — volume attainment against the pinned projection.
    projected = audit["projected_annual_volume_snapshot"]
    volume_pct = r2(dec(actual_volume) / dec(projected if projected else 1)
                    * Decimal(100))

    # Step 2 — the year-one operating variance against the pinned baseline.
    baseline = audit["baseline_year1_opex_snapshot"]
    opex_pct = r2(dec(actual_opex - baseline)
                  / dec(baseline if baseline else 1) * Decimal(100))

    # Step 3 — both bars are read after the two-decimal rounding.
    passed = (volume_pct >= VOLUME_ATTAINMENT_FLOOR_PCT
              and opex_pct <= OPEX_VARIANCE_CEILING_PCT)

    audit["actual_annual_volume"] = actual_volume
    audit["actual_annual_opex_cents"] = actual_opex
    audit["volume_attainment_pct"] = volume_pct
    audit["opex_variance_pct"] = opex_pct
    audit["status"] = "PASSED" if passed else "UNDERPERFORMING"
    touch(audit)

    request_row["status"] = "AUDITED"
    touch(request_row)

    if not passed:
        # Step 4 — hop 2: the department carries the penalty.
        department = db.departments.get(request_row["department_id"])
        if department is not None:
            department["utilization_penalty_points"] = min(
                PENALTY_POINTS_CAP,
                department["utilization_penalty_points"]
                + PENALTY_POINTS_PER_UNDERPERFORMANCE)
            department["underperformance_flag"] = True
            touch(department)
            # Hop 3: every live SCORED request of the department is re-scored.
            cascades.rescore_department_requests(department)

    return object_response(serializers.audit(audit))


@bp.route("/capital/audits/<audit_id>", methods=["GET"])
@guard()
def get_audit(audit_id):
    return object_response(serializers.audit(lookups.audit(audit_id)))


@bp.route("/capital/audits", methods=["GET"])
@guard()
def list_audits():
    limit, offset = pagination()
    rows = lookups.filtered(db.audits.values(), [
        ("request_id", q_str("request_id")),
        ("installation_project_id", q_str("installation_project_id")),
        ("status", q_str("status")),
    ])
    return lookups.paginate(rows, limit, offset, serializers.audit)
