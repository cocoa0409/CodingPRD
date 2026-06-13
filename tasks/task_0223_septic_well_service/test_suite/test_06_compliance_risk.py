"""Site risk score (provisional at finalize vs final after permit decision) and the
two validation-precedence pairs.

Translates queue A `dual_variant_calc` (site-risk variant) and
`priority_pair_validation_conflict`.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS,
    create_account, create_site, create_technician, create_route, create_asset,
    setup_account_site_tech_route, create_completed_inspection_wo,
    create_inspection_report, finalize_inspection_report, create_permit_filing,
    create_completed_work_order, set_clock, get_site,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─── Difficulty: dual_variant_calc (site risk) ─────────

def test_site_risk_provisional_at_finalize_then_final_after_approve(api):
    """PRD §3.8: "Start from a base set by the report result — 0 for PASS, 30 for
    CONDITIONAL, and 60 for FAIL. Add a defect component equal to the report's defect_count
    multiplied by 8 per defect, but capped at 24 ... Add an age penalty of 15 when the
    site's newest active asset is old enough — specifically, when the current year minus the
    newest active asset's install_year is at least 25 years".
    PRD §3.9: "On approval, the score is relieved by its result base — the score becomes the
    larger of 0 and the score minus the result-base relief".

    Design: Difficulty/dual_variant_calc/site_risk_provisional_vs_final_diverge
    """
    set_clock("2026-06-01T00:00:00Z")
    base = setup_account_site_tech_route("2026-06-02")
    create_asset(base["site"]["id"], asset_type="SEPTIC_TANK", capacity_gallons=1200, install_year=1990)
    wo = create_completed_inspection_wo(base, "2026-06-02", 540)
    report = create_inspection_report(wo["id"], defect_count=2)
    report = finalize_inspection_report(report["id"], "CONDITIONAL")
    # Provisional: base 30 + min(2*8,24)=16 + age(2026-1990=36>=25 -> 15) = 61
    assert get_site(base["site"]["id"])["risk_score"] == 61

    filing = create_permit_filing(report["id"], base["site"]["id"])
    set_clock("2026-06-05T00:00:00Z")
    get_success_data(api.submit_permit_filing(filing["id"], COMPLIANCE))
    decided = validate_success(
        api.decide_permit_filing(filing["id"], {"decision": "APPROVE"}, COMPLIANCE), 200
    )
    assert decided["status"] == "APPROVED"
    # Final after APPROVE: relief = base 30 -> max(0, 61-30) = 31
    assert get_site(base["site"]["id"])["risk_score"] == 31


def test_site_risk_provisional_value_on_finalize(api):
    """PRD §3.8: "Sum the base, the defect component, and the age component, then clamp the
    result to no less than 0 and no more than 100. The provisional variant uses the report
    alone and carries no permit-outcome term."
    PRD §3.8: "the site's compliance_status is derived from the result (PASS yields
    COMPLIANT, CONDITIONAL yields CONDITIONAL, and FAIL yields NON_COMPLIANT)".

    Design: Difficulty/dual_variant_calc/site_risk_provisional_vs_final_diverge
    """
    set_clock("2026-06-01T00:00:00Z")
    base = setup_account_site_tech_route("2026-06-02")
    create_asset(base["site"]["id"], asset_type="SEPTIC_TANK", capacity_gallons=1200, install_year=1990)
    wo = create_completed_inspection_wo(base, "2026-06-02", 540)
    report = create_inspection_report(wo["id"], defect_count=2)
    finalize_inspection_report(report["id"], "CONDITIONAL")
    site_after = get_site(base["site"]["id"])
    assert site_after["compliance_status"] == "CONDITIONAL"
    assert site_after["risk_score"] == 61


# ─── Difficulty: priority_pair_validation_conflict ─────

def test_cancel_completed_state_beats_account_hold_fiscal(api):
    """PRD §3.3: "Attempting any transition from a status that does not define it is
    rejected with ERR_INVALID_STATE".
    PRD §2.9: "Only after all of those structural checks pass does the system evaluate
    state-machine legality (ERR_INVALID_STATE) and the domain-specific business rules."

    Design: Difficulty/priority_pair_validation_conflict/cancel_completed_state_beats_account_hold_fiscal
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-16")
    wo = create_completed_work_order(
        site["id"], route["id"], tech["id"], "2026-06-16", 540,
        work_type="PUMPING", estimated_gallons=500, complete_payload={"measured_gallons": 500},
    )
    get_success_data(api.hold_account(account["id"], DISPATCHER))
    # Cancel is not defined from COMPLETED; state check (ERR_INVALID_STATE) wins over the
    # account-on-hold fiscal rule.
    res = api.cancel_work_order(wo["id"], DISPATCHER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_cancel_completed_work_order_rejected_with_invalid_state(api):
    """PRD §3.3: "A Dispatcher may cancel a non-terminal order: cancellation is defined from
    DRAFT, SCHEDULED, and DISPATCHED."
    PRD §3.3: "Attempting any transition from a status that does not define it is rejected
    with ERR_INVALID_STATE".

    Design: Difficulty/priority_pair_validation_conflict/cancel_completed_state_beats_account_hold_fiscal
    """
    # No account hold here: cancel from COMPLETED is still rejected with ERR_INVALID_STATE,
    # confirming the state check owns this outcome independent of the fiscal rule.
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-16")
    wo = create_completed_work_order(
        site["id"], route["id"], tech["id"], "2026-06-16", 540,
        work_type="PUMPING", estimated_gallons=500, complete_payload={"measured_gallons": 500},
    )
    res = api.cancel_work_order(wo["id"], DISPATCHER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_permit_submit_safety_fires_once_report_finalized(api):
    """PRD §3.9: "The site's compliance_status must not be NON_COMPLIANT, or the submit is
    rejected with ERR_SITE_NON_COMPLIANT."
    PRD §3.9: "The linked inspection report must be FINALIZED, or the submit is rejected
    with ERR_REPORT_NOT_FINALIZED."

    Design: Difficulty/priority_pair_validation_conflict/permit_submit_safety_beats_referential
    """
    # When the linked report IS finalized (referential passes) but the site is NON_COMPLIANT,
    # the safety check surfaces ERR_SITE_NON_COMPLIANT — the lower-priority check that the
    # referential check pre-empted in the sibling test.
    set_clock("2026-06-01T00:00:00Z")
    base = setup_account_site_tech_route("2026-06-02")
    site_id = base["site"]["id"]
    wo = create_completed_inspection_wo(base, "2026-06-02", 540)
    report = create_inspection_report(wo["id"], defect_count=3)
    finalize_inspection_report(report["id"], "FAIL")  # FINALIZED + site NON_COMPLIANT
    assert get_site(site_id)["compliance_status"] == "NON_COMPLIANT"
    filing = create_permit_filing(report["id"], site_id)
    set_clock("2026-06-05T00:00:00Z")
    res = api.submit_permit_filing(filing["id"], COMPLIANCE)
    validate_error(res, "ERR_SITE_NON_COMPLIANT", expected_status=409)


def test_permit_submit_referential_beats_safety(api):
    """PRD §3.9: "The linked inspection report must be FINALIZED, or the submit is rejected
    with ERR_REPORT_NOT_FINALIZED. The site's compliance_status must not be NON_COMPLIANT,
    or the submit is rejected with ERR_SITE_NON_COMPLIANT."

    Design: Difficulty/priority_pair_validation_conflict/permit_submit_safety_beats_referential
    """
    # Drive the site NON_COMPLIANT via a FINALIZED FAIL report on WO#1, then open a filing
    # against a SECOND, un-finalized (DRAFT) report on WO#2. Submit must surface the
    # referential check (report-not-finalized) ahead of the safety check.
    set_clock("2026-06-01T00:00:00Z")
    base = setup_account_site_tech_route("2026-06-02")
    site_id = base["site"]["id"]
    # WO#1 -> finalized FAIL -> site NON_COMPLIANT
    wo1 = create_completed_inspection_wo(base, "2026-06-02", 540)
    rep1 = create_inspection_report(wo1["id"], defect_count=3)
    finalize_inspection_report(rep1["id"], "FAIL")
    assert get_site(site_id)["compliance_status"] == "NON_COMPLIANT"
    # WO#2 (same date, distant window so no site-buffer conflict) -> DRAFT report
    wo2 = create_completed_work_order(
        site_id, base["route"]["id"], base["technician"]["id"], "2026-06-02", 720,
        work_type="INSPECTION",
    )
    rep2 = create_inspection_report(wo2["id"], defect_count=0)  # DRAFT, not finalized
    filing = create_permit_filing(rep2["id"], site_id)
    set_clock("2026-06-05T00:00:00Z")
    res = api.submit_permit_filing(filing["id"], COMPLIANCE)
    validate_error(res, "ERR_REPORT_NOT_FINALIZED", expected_status=409)
    assert get_site(site_id)["compliance_status"] == "NON_COMPLIANT"
