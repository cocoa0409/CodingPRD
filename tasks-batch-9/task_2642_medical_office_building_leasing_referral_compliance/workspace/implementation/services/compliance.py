"""Compliance case creation and the watch flag (PRD Section 3.8)."""

from datetime import timedelta

from db import clock_date, db, stamp_new, touch
from services import calc


def open_case(
    tenant,
    case_type,
    scoring_variant,
    risk_score_at_open,
    opened_by_user_id,
    basis,
    severity=None,
):
    today = clock_date()
    row = {
        "tenant_id": tenant["id"],
        "case_type": case_type,
        "basis": basis,
        "status": "OPEN",
        "severity": severity or calc.severity_for(risk_score_at_open),
        "scoring_variant": scoring_variant,
        "risk_score_at_open": risk_score_at_open,
        "opened_on": today,
        "opened_by_user_id": opened_by_user_id,
        "reopen_count": 0,
        "remediation_summary": None,
        "remediation_due_on": today + timedelta(days=calc.REMEDIATION_WINDOW_DAYS),
        "report_reference": None,
        "closed_on": None,
    }
    stamp_new(row)
    db.compliance_cases[row["id"]] = row
    return row


def open_fmv_deviation_case(lease, severity=None, basis=None):
    tenant = db.tenants[lease["tenant_id"]]
    rolling, _strict = calc.risk_scores(tenant["id"])
    return open_case(
        tenant,
        "FMV_DEVIATION",
        "ROLLING_12M",
        rolling,
        "system",
        basis or "Fair-market-value deviation detected on lease %s." % lease["id"],
        severity=severity,
    )
