"""Compliance verification of accepted filings (PRD §3.7)."""

from flask import Blueprint, g

import clock
import db
import lookup
import response
import serializers
import validators as V
from errors import (
    ApiError,
    ERR_INVALID_AUDIT_STATE,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import (
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_MARKET_ANALYST,
    ROLE_PENALTY_OFFICER,
    ROLE_PROGRAM_ADMIN,
    roles,
)
from numeric import money
from services import calculations, cascades

bp = Blueprint("audits", __name__)

READ_ROLES = (
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_PROGRAM_ADMIN,
    ROLE_PENALTY_OFFICER,
    ROLE_MARKET_ANALYST,
)

MATERIAL_FINDINGS = ("MATERIAL_HEAD", "MATERIAL_VALUE", "MATERIAL_BOTH")


def _require_state(case, *allowed):
    if case["status"] not in allowed:
        raise ApiError(
            ERR_INVALID_AUDIT_STATE,
            "An audit case in status %s does not permit this action." % case["status"],
        )


@bp.post("/audit-cases")
@roles(ROLE_COMPLIANCE_AUDITOR)
def create_audit_case():
    payload = V.body()
    submission_id = V.get_string(payload, "submission_id")
    materiality = V.get_decimal(
        payload,
        "materiality_pct",
        required=False,
        minimum="0.01",
        maximum="100.00",
        default=money("2.00"),
    )

    lookup.submission(submission_id)

    rec = db.insert(
        db.audit_cases,
        {
            "submission_id": submission_id,
            "materiality_pct": money(materiality),
            "status": "OPEN",
            "opened_by_user_id": g.user_id,
            "finalized_by_user_id": None,
            "verified_head": None,
            "verified_value_dollars": None,
            "head_discrepancy_rate_pct": None,
            "value_discrepancy_rate_pct": None,
            "finding": None,
            "closed_at": None,
        },
    )
    return response.object_response(serializers.audit_case(rec), 201)


@bp.post("/audit-cases/<case_id>/start-fieldwork")
@roles(ROLE_COMPLIANCE_AUDITOR)
def start_fieldwork(case_id):
    rec = lookup.audit_case(case_id)
    _require_state(rec, "OPEN")
    rec["status"] = "FIELDWORK"
    db.touch(rec)
    return response.object_response(serializers.audit_case(rec))


@bp.post("/audit-cases/<case_id>/finalize")
@roles(ROLE_COMPLIANCE_AUDITOR)
def finalize(case_id):
    payload = V.body()
    verified_head = V.get_int(payload, "verified_head", minimum=0)
    verified_value = V.get_decimal(payload, "verified_value_dollars", minimum=0)

    rec = lookup.audit_case(case_id)

    if g.user_id == rec["opened_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "The finalizing user must differ from the user who opened the case.",
        )

    _require_state(rec, "FIELDWORK")

    sub = db.submissions[rec["submission_id"]]
    rec["verified_head"] = verified_head
    rec["verified_value_dollars"] = money(verified_value)

    head_rate, value_rate, finding = calculations.compute_audit_discrepancy(rec, sub)
    rec["head_discrepancy_rate_pct"] = head_rate
    rec["value_discrepancy_rate_pct"] = value_rate
    rec["finding"] = finding
    rec["finalized_by_user_id"] = g.user_id
    rec["status"] = "DISCREPANCY" if finding in MATERIAL_FINDINGS else "RECONCILED"
    db.touch(rec)

    if finding in MATERIAL_FINDINGS:
        window = db.reporting_windows[sub["reporting_window_id"]]
        if sub["status"] == "ACCEPTED":
            sub["status"] = "UNDER_CORRECTION"
            sub["correction_reason"] = "AUDIT_%s" % finding
            db.touch(sub)
            cascades.submission_acceptance_changed(window)

    return response.object_response(serializers.audit_case(rec))


@bp.post("/audit-cases/<case_id>/close")
@roles(ROLE_COMPLIANCE_AUDITOR)
def close(case_id):
    rec = lookup.audit_case(case_id)
    _require_state(rec, "RECONCILED", "DISCREPANCY")
    rec["status"] = "CLOSED"
    rec["closed_at"] = clock.iso_now()
    db.touch(rec)
    return response.object_response(serializers.audit_case(rec))


@bp.get("/audit-cases/<case_id>")
@roles(*READ_ROLES)
def get_audit_case(case_id):
    rec = lookup.audit_case(case_id)
    return response.object_response(serializers.audit_case(rec))


@bp.get("/audit-cases")
@roles(*READ_ROLES)
def list_audit_cases():
    limit, offset = V.pagination()
    submission_id = V.query_str("submission_id")
    status = V.query_str("status")
    finding = V.query_str("finding")

    records = db.ordered(db.audit_cases.values())
    if submission_id is not None:
        records = [r for r in records if r["submission_id"] == submission_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if finding is not None:
        records = [r for r in records if r["finding"] == finding]

    page, total = V.paginate(records, limit, offset)
    return response.array_response(
        [serializers.audit_case(r) for r in page], limit, offset, total
    )
