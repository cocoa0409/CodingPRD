"""Compliance cases, the watch cascade and remediation (PRD Section 3.8)."""

from datetime import timedelta

from flask import Blueprint

import enums
import serializers as ser
import validators as v
from db import clock_date, db, stamp_new, touch
from errors import ApiError
from lookups import get_resource, get_tenant
from middleware import acting_user_id, endpoint
from response import object_response
from services import calc

bp = Blueprint("cases", __name__)

CASE_ACTIONS = ("REMEDIATION_PLAN", "CURE", "REPORT")
FMV_CURE_LEASE_STATUSES = ("FMV_CERTIFIED", "EXECUTED", "ACTIVE", "HOLDOVER")
BLOCKING_CASE_STATUSES = ("OPEN", "REMEDIATION_PLANNED")


def _case_state_guard(case, allowed):
    """Ladder rung 15."""
    if case["status"] not in allowed:
        raise ApiError(
            "ERR_INVALID_RECORD_STATE",
            "Case '%s' is in status %s; this action requires one of %s."
            % (case["id"], case["status"], ", ".join(allowed)),
        )


def _other_blocking_cases(tenant_id, case_id, case_type=None):
    for other in calc.cases_of_tenant(tenant_id):
        if other["id"] == case_id:
            continue
        if case_type is not None and other["case_type"] != case_type:
            continue
        if other["status"] in BLOCKING_CASE_STATUSES:
            return other
    return None


@bp.post("/compliance-cases")
@endpoint("ComplianceOfficer")
def open_case():
    body = v.json_body()
    tenant_id = v.get_string(body, "tenant_id")
    case_type = v.get_enum(body, "case_type", enums.CASE_TYPES)
    basis = v.get_string(body, "basis")
    # severity is accepted but the stored value is always derived from the
    # frozen score, so it is validated and then deliberately discarded.
    v.get_enum(body, "severity", enums.CASE_SEVERITIES)
    scoring_variant = v.get_enum(body, "scoring_variant", enums.SCORING_VARIANTS)

    tenant = get_tenant(tenant_id)
    if scoring_variant == "STRICT_CUMULATIVE":
        frozen = tenant["strict_cumulative_risk_score"]
    else:
        frozen = tenant["referral_compliance_risk_score"]

    row = {
        "tenant_id": tenant["id"],
        "case_type": case_type,
        "basis": basis,
        "status": "OPEN",
        "severity": calc.severity_for(frozen),
        "scoring_variant": scoring_variant,
        "risk_score_at_open": frozen,
        "opened_on": clock_date(),
        "opened_by_user_id": acting_user_id(),
        "reopen_count": 0,
        "remediation_summary": None,
        "remediation_due_on": clock_date() + timedelta(days=calc.REMEDIATION_WINDOW_DAYS),
        "report_reference": None,
        "closed_on": None,
    }
    stamp_new(row)
    db.compliance_cases[row["id"]] = row

    # A hand-opened case puts the practice on watch whatever the score says.
    tenant["compliance_watch_status"] = "WATCH"
    touch(tenant)
    return object_response(ser.compliance_case_out(row), 201)


@bp.post("/compliance-cases/<case_id>/transitions")
@endpoint("ComplianceOfficer")
def transition_case(case_id):
    body = v.json_body()
    action = v.get_enum(body, "action", CASE_ACTIONS)
    remediation_summary = None
    report_reference = None
    if action == "REMEDIATION_PLAN":
        remediation_summary = v.get_string(body, "remediation_summary")
    elif action == "REPORT":
        report_reference = v.get_string(body, "report_reference")

    case = get_resource(db.compliance_cases, case_id, "Compliance case")
    tenant = db.tenants[case["tenant_id"]]

    if action == "REMEDIATION_PLAN":
        _case_state_guard(case, ("OPEN",))
        case["remediation_summary"] = remediation_summary
        case["remediation_due_on"] = clock_date() + timedelta(
            days=calc.REMEDIATION_WINDOW_DAYS
        )
        case["status"] = "REMEDIATION_PLANNED"
        touch(case)
        return object_response(ser.compliance_case_out(case))

    if action == "REPORT":
        _case_state_guard(case, ("OPEN",))
        if case["severity"] != "HIGH":
            raise ApiError(
                "ERR_INVALID_RECORD_STATE",
                "Case '%s' carries severity %s; only a HIGH case may be reported."
                % (case["id"], case["severity"]),
            )
        case["report_reference"] = report_reference
        case["closed_on"] = clock_date()
        case["status"] = "REPORTED"
        touch(case)
        # A self-disclosure keeps the practice on watch permanently: the watch
        # flag is pointedly not reconsidered here.
        return object_response(ser.compliance_case_out(case))

    # --- CURE -----------------------------------------------------------
    _case_state_guard(case, ("OPEN", "REMEDIATION_PLANNED"))
    if case["case_type"] == "RENT_DELINQUENCY":
        for lease in calc.leases_of_tenant(tenant["id"]):
            for invoice in calc.invoices_of_lease(lease["id"]):
                if invoice["status"] == "DELINQUENT":
                    raise ApiError(
                        "ERR_INVALID_RECORD_STATE",
                        "Invoice '%s' is still DELINQUENT; the arrears must be "
                        "settled or written off before the case can be cured."
                        % invoice["id"],
                    )
    elif case["case_type"] == "FMV_DEVIATION":
        for lease in calc.leases_of_tenant(tenant["id"]):
            if lease["status"] not in FMV_CURE_LEASE_STATUSES:
                continue
            if lease["fmv_certification_status"] != "CERTIFIED":
                raise ApiError(
                    "ERR_INVALID_RECORD_STATE",
                    "Lease '%s' carries fmv_certification_status %s; every live "
                    "lease must be CERTIFIED before the case can be cured."
                    % (lease["id"], lease["fmv_certification_status"]),
                )

    case["closed_on"] = clock_date()
    case["status"] = "CURED"
    touch(case)

    # The concession lock unwinds only once no rent-delinquency case is live.
    if case["case_type"] == "RENT_DELINQUENCY" and not _other_blocking_cases(
        tenant["id"], case["id"], "RENT_DELINQUENCY"
    ):
        for lease in calc.leases_of_tenant(tenant["id"]):
            if lease["status"] in calc.CLOSED_LEASE_STATUSES:
                continue
            lease["rent_concession_locked"] = False
            # after_hours_authorized is deliberately never restored here.
            touch(lease)

    if not _other_blocking_cases(tenant["id"], case["id"]):
        tenant["compliance_watch_status"] = "CLEAR"
        touch(tenant)
    return object_response(ser.compliance_case_out(case))
