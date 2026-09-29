"""The five-step assessment liability rollup driven off an Audit (PRD 3.6)."""
import db
from services import calc, derive


def interest_days(audit, exclude_assessment_id=None):
    scope_end = db.parse_date(audit.get("scope_period_end"))
    base = 0
    if scope_end is not None:
        base = max(0, db.days_between(scope_end, db.clock_date()))
    tolled = 0
    for asmt in derive.assessments_of_audit(audit["id"]):
        if exclude_assessment_id is not None and asmt["id"] == exclude_assessment_id:
            continue
        for prc in derive.proceedings_of_assessment(asmt["id"]):
            if prc["status"] == "DECIDED":
                tolled += int(prc.get("tolled_days") or 0)
    return base + tolled


def compute(audit, exclude_assessment_id=None):
    return calc.rollup(
        audit.get("projected_deficiency_cents") or 0,
        audit.get("certificate_deficiency_cents") or 0,
        audit.get("use_tax_deficiency_cents") or 0,
        bool(audit.get("fraud_indicator")),
        interest_days(audit, exclude_assessment_id),
    )


def apply_to(assessment, audit):
    figures = compute(audit, exclude_assessment_id=assessment["id"])
    assessment.update(figures)
    derive.refresh_assessment(assessment)
    return assessment
