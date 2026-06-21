"""Nutritional risk assessment: factor scoring, the high-priority short-circuit,
and the risk-eligibility gate at approval (PRD §3.4 / §3.5).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_risk_assessed_application,
    make_cpa_headers,
)


def test_risk_below_threshold_is_ineligible_and_blocks_approval(api):
    """PRD §3.4: "The application's risk_eligible flag is set true when at least
    one submitted code is a high-priority factor, or when the total_risk_score is
    greater than or equal to the threshold for the participant's category. The
    category thresholds are 30 for PREGNANT, 30 for POSTPARTUM, 30 for
    BREASTFEEDING, 25 for INFANT, and 35 for CHILD".
    PRD §3.5: "its risk_eligible must be true (otherwise ERR_RISK_INELIGIBLE)".

    Design: Corner/calculations/risk_ineligible_below_threshold_blocks_approval
    """
    # CHILD threshold 35; INADEQUATE_DIET worth 20 (no high-priority factor)
    ctx = setup_risk_assessed_application(
        category="CHILD", adjunctive_program="SNAP", household_size=3,
        income_records=[(100000, "MONTHLY")], risk_factor_codes=["INADEQUATE_DIET"],
        ssn_last4="4441",
    )
    ra = ctx["risk_assessed"]
    assert ra["total_risk_score"] == 20
    assert ra["risk_eligible"] is False
    resp = api.approve_application(ctx["application"]["id"], make_cpa_headers("cpa-1"))
    validate_error(resp, ApiErrorId.ERR_RISK_INELIGIBLE.value)


def test_high_priority_factor_is_eligible_regardless_of_threshold(api):
    """PRD §3.4: "Two of these — ELEVATED_LEAD and GEST_DIABETES — are
    high-priority factors."
    PRD §3.4: "The presence of any high-priority factor makes the participant
    risk-eligible regardless of the total."
    PRD §3.4: "ELEVATED_LEAD 50".

    Design: Corner/calculations/risk_high_priority_factor_eligible_below_threshold
    """
    ctx = setup_risk_assessed_application(
        category="INFANT", adjunctive_program="MEDICAID", household_size=3,
        income_records=[(100000, "MONTHLY")], risk_factor_codes=["ELEVATED_LEAD"],
        ssn_last4="4442",
    )
    ra = ctx["risk_assessed"]
    assert ra["total_risk_score"] == 50
    assert ra["risk_eligible"] is True
