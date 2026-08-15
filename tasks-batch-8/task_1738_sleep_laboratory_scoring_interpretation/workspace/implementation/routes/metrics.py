"""Accreditation quality metrics dashboard (PRD 3.8)."""
from decimal import Decimal

from flask import Blueprint

from db import db
from middleware import authorized
from response import success_object
from util import num, ratio_round_half_up

bp = Blueprint("metrics", __name__)


@bp.get("/quality-metrics/summary")
def quality_metrics_summary():
    authorized(["LabDirector"])
    signed = [r for r in db["interpretation_reports"].values() if r["signed_at"] is not None]
    reports_signed_total = len(signed)
    sla_breached_total = sum(1 for r in signed if r["sla_breached"])
    if reports_signed_total == 0:
        sla_compliance_percent = 100.0
    else:
        sla_compliance_percent = num(ratio_round_half_up(
            100 * (reports_signed_total - sla_breached_total), reports_signed_total, 2))

    adjudicated = [c for c in db["inter_rater_cases"].values() if c["status"] == "ADJUDICATED"]
    cases_adjudicated_total = len(adjudicated)
    cases_concordant_total = sum(1 for c in adjudicated if c["concordant"])
    if cases_adjudicated_total == 0:
        inter_rater_concordant_percent = 100.0
    else:
        inter_rater_concordant_percent = num(ratio_round_half_up(
            100 * cases_concordant_total, cases_adjudicated_total, 2))

    scorers_in_remediation_total = sum(
        1 for s in db["scorers"].values() if s["reliability_status"] == "REMEDIATION")

    return success_object({
        "reports_signed_total": reports_signed_total,
        "sla_breached_total": sla_breached_total,
        "sla_compliance_percent": sla_compliance_percent,
        "cases_adjudicated_total": cases_adjudicated_total,
        "cases_concordant_total": cases_concordant_total,
        "inter_rater_concordant_percent": inter_rater_concordant_percent,
        "scorers_in_remediation_total": scorers_in_remediation_total,
    })
