"""Derived-field recomputation and the cascade chains (PRD section 2.12).

Every derived field is recomputed inside the same request that changed its
inputs, and every resource a cascade reaches gets its updated_at refreshed and
its version incremented by 1.
"""

from decimal import Decimal

import calc
from core import (
    ZERO2, ZERO4, get, insert, now_logical, q2, q4, rows, touch, whole_days,
)

ONE = Decimal("1")
ONE4 = Decimal("1.0000")

OUTSTANDING_STATES = ("DEFERRED", "STEPPED_UP", "INCLUDED_PARTIAL")
INCLUDED_STATES = ("INCLUDED_PARTIAL", "INCLUDED_FULL")


# ---------------------------------------------------------------------------
# EligibleGain -> elected / unelected / status
# ---------------------------------------------------------------------------

def recompute_gain(gain):
    live = rows("deferral_elections", lambda e: (
        e["eligible_gain_id"] == gain["id"] and e["status"] != "REVOKED"))
    elected = q2(sum((e["elected_amount"] for e in live), ZERO2))
    unelected = max(ZERO2, q2(gain["eligible_amount"] - elected))
    changed = (elected != gain["elected_amount"]
               or unelected != gain["unelected_amount"])
    gain["elected_amount"] = elected
    gain["unelected_amount"] = unelected
    if gain["status"] != "EXPIRED":
        if elected == ZERO2:
            status = "ELIGIBLE"
        elif unelected == ZERO2:
            status = "FULLY_INVESTED"
        else:
            status = "PARTIALLY_INVESTED"
        if status != gain["status"]:
            changed = True
        gain["status"] = status
    if changed:
        touch(gain)
    return gain


# ---------------------------------------------------------------------------
# DeferralElection -> included_amount / included_fraction_total /
#                     deferred_remaining / holding_tier
# ---------------------------------------------------------------------------

def recompute_election(election):
    events = rows("inclusion_events",
                  lambda v: v["deferral_election_id"] == election["id"])
    total = q4(sum((v["included_fraction"] for v in events), ZERO4))
    if total > ONE4:
        total = ONE4
    included = q2(sum((v["net_inclusion_amount"] for v in events), ZERO2))
    if election["status"] == "REVOKED":
        remaining = ZERO2
    else:
        remaining = max(ZERO2, q2(election["elected_amount"] * (ONE - total)))

    granted = rows("step_up_elections", lambda s: (
        s["deferral_election_id"] == election["id"] and s["status"] == "GRANTED"))
    if granted:
        tier = "TEN_YEAR"
    else:
        tier = calc.holding_tier(
            whole_days(now_logical(), election["investment_date"]))

    changed = (total != election["included_fraction_total"]
               or included != election["included_amount"]
               or remaining != election["deferred_remaining"]
               or tier != election["holding_tier"])
    election["included_fraction_total"] = total
    election["included_amount"] = included
    election["deferred_remaining"] = remaining
    election["holding_tier"] = tier
    if changed:
        touch(election)
    return election


# ---------------------------------------------------------------------------
# Investor rollups
# ---------------------------------------------------------------------------

def recompute_investor(investor):
    gains = rows("eligible_gains", lambda g: g["investor_id"] == investor["id"])
    elections = rows("deferral_elections",
                     lambda e: e["investor_id"] == investor["id"])
    eligible_total = q2(sum((g["eligible_amount"] for g in gains), ZERO2))
    outstanding = q2(sum((e["deferred_remaining"] for e in elections
                          if e["status"] in OUTSTANDING_STATES), ZERO2))
    included = q2(sum((e["included_amount"] for e in elections
                       if e["status"] in INCLUDED_STATES), ZERO2))
    changed = (eligible_total != investor["eligible_gain_total"]
               or outstanding != investor["deferred_gain_outstanding"]
               or included != investor["included_gain_total"])
    investor["eligible_gain_total"] = eligible_total
    investor["deferred_gain_outstanding"] = outstanding
    investor["included_gain_total"] = included
    if changed:
        touch(investor)
    return investor


def recompute_investor_of(election):
    investor = get("investors", election["investor_id"])
    if investor is not None:
        recompute_investor(investor)
    return investor


# ---------------------------------------------------------------------------
# Fund aggregates
# ---------------------------------------------------------------------------

LIVE_ASSET_STATES = ("HELD", "IMPROVING")


def recompute_fund_aggregates(fund):
    assets = rows("fund_assets", lambda a: (
        a["fund_id"] == fund["id"] and a["status"] in LIVE_ASSET_STATES))
    basis = q2(sum((a["unadjusted_cost_basis"] for a in assets), ZERO2))
    afs = q2(sum((a["afs_fair_value"] for a in assets), ZERO2))
    q_basis = q2(sum((a["unadjusted_cost_basis"] for a in assets
                      if a["qualification"] == "QUALIFIED"), ZERO2))
    q_afs = q2(sum((a["afs_fair_value"] for a in assets
                    if a["qualification"] == "QUALIFIED"), ZERO2))
    changed = (basis != fund["aggregate_asset_basis"]
               or afs != fund["aggregate_afs_value"]
               or q_basis != fund["aggregate_qualified_basis"]
               or q_afs != fund["aggregate_qualified_afs_value"])
    fund["aggregate_asset_basis"] = basis
    fund["aggregate_afs_value"] = afs
    fund["aggregate_qualified_basis"] = q_basis
    fund["aggregate_qualified_afs_value"] = q_afs
    if changed:
        touch(fund)
    return fund


def recompute_fund_committed(fund):
    live = rows("deferral_elections", lambda e: (
        e["fund_id"] == fund["id"] and e["status"] != "REVOKED"))
    committed = q2(sum((e["elected_amount"] for e in live), ZERO2))
    if committed != fund["deferred_gain_committed"]:
        fund["deferred_gain_committed"] = committed
        touch(fund)
    return fund


# ---------------------------------------------------------------------------
# FundAsset adjusted_basis and qualification
# ---------------------------------------------------------------------------

def recompute_asset_basis(asset):
    projects = rows("improvement_projects",
                    lambda p: p["fund_asset_id"] == asset["id"])
    project_ids = set(p["id"] for p in projects)
    additions = ZERO2
    if project_ids:
        spends = rows("capital_expenditures", lambda e: (
            e["improvement_project_id"] in project_ids
            and e["counts_toward_basis"] is True))
        additions = q2(sum((e["amount"] for e in spends), ZERO2))
    adjusted = q2(asset["unadjusted_cost_basis"] + additions)
    if adjusted != asset["adjusted_basis"]:
        asset["adjusted_basis"] = adjusted
        touch(asset)
    return asset


def initial_qualification(asset_class, original_use_in_zone, business):
    if asset_class == "QOZ_BUSINESS_PROPERTY":
        return "QUALIFIED" if original_use_in_zone else "IMPROVEMENT_PENDING"
    if asset_class == "QOZB_EQUITY":
        if business is not None and business["qualification_status"] == "QUALIFIED":
            return "QUALIFIED"
        return "NONQUALIFIED"
    return "NONQUALIFIED"


def set_asset_qualification(asset, qualification, status=None):
    changed = False
    if asset["qualification"] != qualification:
        asset["qualification"] = qualification
        changed = True
    if status is not None and asset["status"] != status:
        asset["status"] = status
        changed = True
    if changed:
        touch(asset)
    return changed


# ---------------------------------------------------------------------------
# QOZBusiness NQFP shelter arithmetic
# ---------------------------------------------------------------------------

def recompute_business_nqfp(business):
    plans = rows("wcsh_plans", lambda p: p["qoz_business_id"] == business["id"])
    protected = q2(sum((q2(p["covered_amount"] - p["spent_total"])
                        for p in plans if p["status"] == "ACTIVE"), ZERO2))
    blown = q2(sum((p["unspent_amount"] for p in plans
                    if p["status"] == "BLOWN"), ZERO2))
    nqfp = max(ZERO2, q2(business["declared_nqfp_amount"] + blown - protected))
    changed = (protected != business["wcsh_protected_amount"]
               or blown != business["blown_unspent_amount"]
               or nqfp != business["nqfp_amount"])
    business["wcsh_protected_amount"] = protected
    business["blown_unspent_amount"] = blown
    business["nqfp_amount"] = nqfp
    if changed:
        touch(business)
    return business


# ---------------------------------------------------------------------------
# Cascade chain 1 -- fund decertification drives full inclusion
# ---------------------------------------------------------------------------

def full_inclusion_cascade(fund):
    """Every outstanding election of this fund is included in full."""
    elections = rows("deferral_elections", lambda e: (
        e["fund_id"] == fund["id"] and e["status"] in OUTSTANDING_STATES))
    event_date = now_logical()
    for election in elections:
        fraction = q4(ONE4 - election["included_fraction_total"])
        if fraction <= ZERO4:
            continue
        amounts = calc.inclusion_amounts(election, fraction, event_date)
        insert("inclusion_events", {
            "deferral_election_id": election["id"],
            "event_type": "FUND_DECERTIFICATION",
            "included_fraction": fraction,
            "event_date": event_date,
            "holding_days": amounts["holding_days"],
            "holding_tier_applied": amounts["holding_tier_applied"],
            "gross_inclusion_amount": amounts["gross_inclusion_amount"],
            "basis_offset_amount": amounts["basis_offset_amount"],
            "net_inclusion_amount": amounts["net_inclusion_amount"],
            "is_full": True,
        })
        election["status"] = "INCLUDED_FULL"
        touch(election)
        recompute_election(election)
        recompute_investor_of(election)


def decertify_fund(fund):
    """certification_status -> DECERTIFIED, compliance_posture -> FAILED_FINAL.

    The inclusion cascade only fires from SELF_CERTIFIED: a DRAFT fund never
    accepted an election, so there is nothing to include.
    """
    was_certified = fund["certification_status"] == "SELF_CERTIFIED"
    fund["certification_status"] = "DECERTIFIED"
    fund["compliance_posture"] = "FAILED_FINAL"
    touch(fund)
    if was_certified:
        full_inclusion_cascade(fund)
    return fund


# ---------------------------------------------------------------------------
# Cascade chain 2 -- asset-test certification
# ---------------------------------------------------------------------------

def asset_test_certified_pass(fund):
    fund["compliance_posture"] = "COMPLIANT"
    fund["consecutive_failed_tests"] = 0
    touch(fund)
    return fund


def asset_test_certified_fail(fund, test, user_id):
    fund["consecutive_failed_tests"] = fund["consecutive_failed_tests"] + 1
    fund["cumulative_penalty_months"] = (fund["cumulative_penalty_months"]
                                         + test["failed_month_count"])
    penalty = calc.failed_test_penalty(test["shortfall_amount"],
                                       test["failed_month_count"])
    assessment = insert("penalty_assessments", {
        "fund_id": fund["id"],
        "asset_test_id": test["id"],
        "failed_month_count": test["failed_month_count"],
        "shortfall_amount": test["shortfall_amount"],
        "monthly_penalty_amount": penalty["monthly_penalty_amount"],
        "gross_penalty_amount": penalty["gross_penalty_amount"],
        "cure_credit_amount": penalty["cure_credit_amount"],
        "net_penalty_amount": penalty["net_penalty_amount"],
        "cure_attempt_count": 0,
        "cure_basis": "NONE",
        "narrative_reference": None,
        "status": "ASSESSED",
        "requested_by_user_id": None,
        "decided_by_user_id": None,
    })
    if fund["consecutive_failed_tests"] >= 2:
        decertify_fund(fund)
    else:
        fund["compliance_posture"] = "DEFICIENT"
    touch(fund)
    return assessment


# ---------------------------------------------------------------------------
# Cascade chain 3 -- business-test certification
# ---------------------------------------------------------------------------

def latest_measured_asset_test(fund):
    measured = rows("asset_tests", lambda t: (
        t["fund_id"] == fund["id"] and t["status"] == "MEASURED"))
    if not measured:
        return None
    measured.sort(key=lambda t: (t["measurement_date"], t["created_at"], t["_seq"]))
    return measured[-1]


def remeasure_asset_test(test):
    figures = calc.asset_test_ratio(test)
    test.update(figures)
    touch(test)
    return test


def business_disqualify_cascade(business, fund, counter):
    business["qualification_status"] = "DISQUALIFIED"
    business["consecutive_failed_business_tests"] = counter
    touch(business)
    for asset in rows("fund_assets", lambda a: (
            a["qoz_business_id"] == business["id"]
            and a["status"] in LIVE_ASSET_STATES)):
        set_asset_qualification(asset, "NONQUALIFIED")
    recompute_fund_aggregates(fund)
    test = latest_measured_asset_test(fund)
    if test is not None:
        remeasure_asset_test(test)
        if test["result"] == "FAIL":
            fund["compliance_posture"] = "DEFICIENT"
            touch(fund)
    return business


def business_qualify_cascade(business, fund):
    business["qualification_status"] = "QUALIFIED"
    business["consecutive_failed_business_tests"] = 0
    touch(business)
    for asset in rows("fund_assets", lambda a: (
            a["qoz_business_id"] == business["id"]
            and a["asset_class"] == "QOZB_EQUITY"
            and a["status"] == "HELD")):
        set_asset_qualification(asset, "QUALIFIED")
    recompute_fund_aggregates(fund)
    return business


def business_test_certified(test, business, fund):
    """Fork out of MEASURED into PASSED or FAILED with divergent side effects."""
    prongs = (test["gross_income_prong"], test["intangibles_prong"],
              test["nqfp_prong"])
    if all(p == "PASS" for p in prongs):
        test["status"] = "PASSED"
        business_qualify_cascade(business, fund)
        return test
    test["status"] = "FAILED"
    prior = business["consecutive_failed_business_tests"]
    if test["nqfp_prong"] == "FAIL":
        business_disqualify_cascade(business, fund, prior + 1)
    elif business["qualification_status"] == "AT_RISK":
        business_disqualify_cascade(business, fund, 2)
    else:
        business["qualification_status"] = "AT_RISK"
        business["consecutive_failed_business_tests"] = prior + 1
        touch(business)
    return test


# ---------------------------------------------------------------------------
# Cascade chain 4 -- a blown working-capital plan withdraws the shelter
# ---------------------------------------------------------------------------

def latest_measured_business_test(business):
    measured = rows("business_tests", lambda t: (
        t["qoz_business_id"] == business["id"] and t["status"] == "MEASURED"))
    if not measured:
        return None
    measured.sort(key=lambda t: (t["testing_date"], t["created_at"], t["_seq"]))
    return measured[-1]


def plan_blown_cascade(plan, business, fund):
    """ACTIVE -> BLOWN: shelter falls, nqfp rises, prong re-derived."""
    plan["status"] = "BLOWN"
    touch(plan)
    recompute_business_nqfp(business)
    test = latest_measured_business_test(business)
    if test is None:
        if business["qualification_status"] == "QUALIFIED":
            business["qualification_status"] = "AT_RISK"
            touch(business)
        return plan
    figures = calc.prong_evaluation(test, business["nqfp_amount"])
    test["nqfp_amount_measured"] = figures["nqfp_amount_measured"]
    test["nqfp_pct"] = figures["nqfp_pct"]
    test["nqfp_prong"] = figures["nqfp_prong"]
    touch(test)
    if (figures["nqfp_pct"] > calc.NQFP_MAX_PCT
            and business["qualification_status"] != "DISQUALIFIED"):
        business_disqualify_cascade(
            business, fund, business["consecutive_failed_business_tests"] + 1)
    return plan


def plan_completed(plan, business):
    """ACTIVE -> COMPLETED: the shelter simply ends; nothing is treated as blown."""
    plan["status"] = "COMPLETED"
    touch(plan)
    recompute_business_nqfp(business)
    return plan


# ---------------------------------------------------------------------------
# Cascade chain 5 -- penalty cure lifecycle
# ---------------------------------------------------------------------------

def penalty_cure_requested(assessment, fund, cure_basis, narrative, user_id):
    assessment["status"] = "CURE_REQUESTED"
    assessment["cure_attempt_count"] = assessment["cure_attempt_count"] + 1
    assessment["cure_basis"] = cure_basis
    assessment["narrative_reference"] = narrative
    assessment["requested_by_user_id"] = user_id
    touch(assessment)
    if fund["compliance_posture"] == "DEFICIENT":
        fund["compliance_posture"] = "CURE_PENDING"
        touch(fund)
    return assessment


def penalty_cure_approved(assessment, fund, user_id):
    credit = calc.cure_credit(assessment["gross_penalty_amount"])
    assessment["cure_credit_amount"] = credit["cure_credit_amount"]
    assessment["net_penalty_amount"] = credit["net_penalty_amount"]
    assessment["status"] = "CURED"
    assessment["decided_by_user_id"] = user_id
    touch(assessment)
    fund["cumulative_penalty_months"] = max(
        0, fund["cumulative_penalty_months"] - assessment["failed_month_count"])
    fund["compliance_posture"] = "COMPLIANT"
    fund["consecutive_failed_tests"] = 0
    touch(fund)
    return assessment


def penalty_cure_denied(assessment, fund, user_id):
    if assessment["cure_basis"] == "TREATED_AS_FAILURE":
        assessment["status"] = "UPHELD"
    else:
        assessment["status"] = "ASSESSED"
    assessment["decided_by_user_id"] = user_id
    touch(assessment)
    fund["compliance_posture"] = "DEFICIENT"
    touch(fund)
    return assessment


# ---------------------------------------------------------------------------
# ImprovementProject outcomes (shared by evaluate and the deadline sweep)
# ---------------------------------------------------------------------------

def _promote_asset(project, qualification):
    asset = get("fund_assets", project["fund_asset_id"])
    if asset is None:
        return
    status = "HELD" if asset["status"] == "IMPROVING" else None
    set_asset_qualification(asset, qualification, status)
    fund = get("funds", asset["fund_id"])
    if fund is not None:
        recompute_fund_aggregates(fund)


def project_lapse(project):
    project["status"] = "LAPSED"
    project["evaluated_at"] = now_logical()
    touch(project)
    _promote_asset(project, "NONQUALIFIED")
    return project


def project_satisfy(project):
    project["status"] = "SATISFIED"
    project["evaluated_at"] = now_logical()
    touch(project)
    _promote_asset(project, "QUALIFIED")
    if project["aggregation_method"] == "AGGREGATED_GROUP":
        siblings = rows("improvement_projects", lambda p: (
            p["id"] != project["id"]
            and p["aggregation_method"] == "AGGREGATED_GROUP"
            and p["group_key"] == project["group_key"]
            and p["status"] == "OPEN"))
        for sibling in siblings:
            sibling["status"] = "SATISFIED"
            touch(sibling)
            _promote_asset(sibling, "QUALIFIED")
    return project


def refresh_project(project):
    figures = calc.improvement_ratio(project)
    changed = (figures["qualified_additions_total"]
               != project["qualified_additions_total"]
               or figures["improvement_ratio_pct"]
               != project["improvement_ratio_pct"])
    project.update(figures)
    if changed:
        touch(project)
    return project
