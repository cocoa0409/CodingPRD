"""Derived-field maintenance, clearance, valuation and offer economics."""

from datetime import timedelta
from decimal import Decimal as D

import calculations as calc
import lookups as lk
from db import db, set_fields, sorted_rows

ZERO = calc.ZERO


# ------------------------------------------------------------------------
# conserved-quantity maintenance (PRD 2.8) -- always agrees with the
# definitions, so no release path can drift.
# ------------------------------------------------------------------------

def sync_group_ledger(group):
    reserved = ZERO
    committed = ZERO
    for offer in db.offers.values():
        candidate = db.candidates.get(offer["candidate_id"])
        if candidate is None or candidate["target_practice_group_id"] != group["id"]:
            continue
        # PRD 3.6: COMMITTEE_REVIEW and APPROVED are "the two statuses that hold
        # a live reservation" -- approval neither releases nor commits the money.
        if offer["status"] in ("COMMITTEE_REVIEW", "APPROVED"):
            reserved += offer["guaranteed_comp_usd"]
        elif offer["status"] == "ACCEPTED":
            committed += offer["guaranteed_comp_usd"]
    available = group["guarantee_budget_total_usd"] - reserved - committed
    set_fields(group,
               reserved_guarantee_budget_usd=reserved,
               committed_guarantee_total_usd=committed,
               available_guarantee_budget_usd=available)


def sync_group_for_offer(offer):
    candidate = db.candidates.get(offer["candidate_id"])
    if candidate is None:
        return
    group = db.practice_groups.get(candidate["target_practice_group_id"])
    if group is not None:
        sync_group_ledger(group)


def sync_group_onboarding(group):
    count = len([p for p in db.integration_plans.values()
                 if p["practice_group_id"] == group["id"] and p["status"] == "ACTIVE"])
    set_fields(group, active_onboarding_count=count)


def sync_firm_engagement_count(firm):
    count = len([e for e in db.engagements.values()
                 if e["search_firm_id"] == firm["id"]])
    set_fields(firm, engagement_count=count)


def sync_questionnaire_entry_count(questionnaire):
    count = len(lk.entries_of_questionnaire(questionnaire["id"], active_only=True))
    set_fields(questionnaire, entry_count=count)


def sync_vote_counters(offer):
    rows = lk.votes_of_offer(offer["id"])
    active = len([v for v in rows if v["status"] == "ACTIVE"])
    voided = len([v for v in rows if v["status"] == "VOIDED"])
    set_fields(offer,
               votes_cast_total=len(rows),
               active_vote_count=active,
               voided_vote_count=voided)


def sync_plan_counters(plan):
    rows = lk.introductions_of_plan(plan["id"])
    live = len([i for i in rows if i["status"] in ("PROPOSED", "COMPLETED")])
    completed = len([i for i in rows if i["status"] == "COMPLETED"])
    set_fields(plan,
               introduction_count=live,
               completed_introduction_count=completed)


# ------------------------------------------------------------------------
# clearance dimension (PRD 3.5)
# ------------------------------------------------------------------------

def candidate_checks(candidate):
    """Every check on every ACTIVE entry of the candidate's questionnaires."""
    out = []
    for questionnaire in lk.questionnaires_of_candidate(candidate["id"]):
        for entry in lk.entries_of_questionnaire(questionnaire["id"], active_only=True):
            out.extend(lk.checks_of_entry(entry["id"]))
    return out


def candidate_entry_count(candidate):
    total = 0
    for questionnaire in lk.questionnaires_of_candidate(candidate["id"]):
        total += questionnaire["entry_count"]
    return total


def recompute_clearance(candidate):
    checks = candidate_checks(candidate)
    if not checks:
        status = "NOT_STARTED"
    elif any(c["status"] == "BLOCKED" for c in checks):
        status = "BLOCKED"
    elif all(c["status"] == "CLEAR" for c in checks) and candidate_entry_count(candidate) >= 1:
        status = "CLEARED"
    else:
        status = "IN_PROGRESS"
    set_fields(candidate, clearance_status=status)


def candidate_of_questionnaire(questionnaire):
    return db.candidates.get(questionnaire["candidate_id"])


def candidate_of_entry(entry):
    questionnaire = db.questionnaires.get(entry["questionnaire_id"])
    if questionnaire is None:
        return None
    return candidate_of_questionnaire(questionnaire)


# ------------------------------------------------------------------------
# portable book valuation (PRD 3.4)
# ------------------------------------------------------------------------

def minus_years(moment, years):
    try:
        return moment.replace(year=moment.year - years)
    except ValueError:  # 29 February
        return moment.replace(year=moment.year - years, day=28)


def verified_historical_in_window(entry_id, lookback_start, baseline_date):
    rows = []
    for record in lk.records_of_entry(entry_id):
        if record["record_type"] != "HISTORICAL" or record["status"] != "VERIFIED":
            continue
        if lookback_start <= record["period_end_date"] < baseline_date:
            rows.append(record)
    return rows


def scope_entries(questionnaire_id):
    return sorted_rows(lk.entries_of_questionnaire(questionnaire_id, active_only=True))


def value_entries(scope, lookback_start, baseline_date):
    for entry in scope:
        records = verified_historical_in_window(entry["id"], lookback_start, baseline_date)
        historical_base = sum((r["amount_usd"] for r in records), ZERO)
        baseline = calc.entry_baseline_portable_amount(entry, historical_base)
        if entry["portable_status"] == "DECLINED":
            set_fields(entry,
                       baseline_portable_amount_usd=baseline,
                       validated_portable_amount_usd=ZERO)
        else:
            set_fields(entry,
                       baseline_portable_amount_usd=baseline,
                       validated_portable_amount_usd=baseline,
                       portable_status="VALIDATED")


def aggregate_totals(scope):
    gross = sum((e["baseline_portable_amount_usd"] for e in scope), ZERO)
    validated = sum((e["validated_portable_amount_usd"] for e in scope), ZERO)
    declined = sum((e["baseline_portable_amount_usd"] for e in scope
                    if e["portable_status"] == "DECLINED"), ZERO)
    self_reported = sum((calc.self_reported_line(e) for e in scope), ZERO)
    return gross, validated, declined, self_reported


def ranked_baselines(scope):
    ranked = sorted(scope,
                    key=lambda e: (-e["baseline_portable_amount_usd"],
                                   e["created_at"], e["_seq"]))
    return [e["baseline_portable_amount_usd"] for e in ranked]


def assessment_fields(questionnaire, baseline_date, governing_basis):
    """Full valuation; also advances each in-scope entry's portable_status."""
    lookback_start = minus_years(baseline_date, 3)
    scope = scope_entries(questionnaire["id"])
    value_entries(scope, lookback_start, baseline_date)
    gross, validated, declined, self_reported = aggregate_totals(scope)
    top, top3 = calc.concentration_shares(ranked_baselines(scope), gross)
    grade = calc.concentration_grade(top)
    haircut = calc.HAIRCUT[grade]
    governing = self_reported if governing_basis == "SELF_REPORTED" else validated
    return {
        "questionnaire_id": questionnaire["id"],
        "baseline_date": baseline_date,
        "lookback_start_date": lookback_start,
        "governing_basis": governing_basis,
        "entry_count_in_scope": len(scope),
        "self_reported_total_usd": self_reported,
        "validated_portable_total_usd": validated,
        "gross_baseline_total_usd": gross,
        "declined_portable_total_usd": declined,
        "variance_pct": calc.variance_pct(self_reported, validated),
        "top_client_share": top,
        "top3_client_share": top3,
        "concentration_grade": grade,
        "concentration_haircut_pct": haircut,
        "adjusted_portable_total_usd": calc.adjusted_total(governing, haircut),
        "status": "CURRENT",
    }


def recompute_assessment_totals(assessment, new_status=None):
    """PRD 3.4: recompute exactly the three moving totals.

    gross_baseline_total_usd stays exactly as it was.
    """
    scope = scope_entries(assessment["questionnaire_id"])
    validated = sum((e["validated_portable_amount_usd"] for e in scope), ZERO)
    declined = sum((e["baseline_portable_amount_usd"] for e in scope
                    if e["portable_status"] == "DECLINED"), ZERO)
    if assessment["governing_basis"] == "SELF_REPORTED":
        governing = assessment["self_reported_total_usd"]
    else:
        governing = validated
    adjusted = calc.adjusted_total(governing, assessment["concentration_haircut_pct"])
    fields = {
        "validated_portable_total_usd": validated,
        "declined_portable_total_usd": declined,
        "adjusted_portable_total_usd": adjusted,
    }
    if new_status is not None:
        fields["status"] = new_status
    set_fields(assessment, **fields)


def stale_current_assessments(questionnaire_id):
    """CURRENT -> STALE with the fifth hop onto committee-review offers."""
    for assessment in sorted_rows(lk.assessments_of_questionnaire(questionnaire_id)):
        if assessment["status"] != "CURRENT":
            continue
        recompute_assessment_totals(assessment, new_status="STALE")
        for offer in sorted_rows(lk.offers_of_assessment(assessment["id"])):
            if offer["status"] == "COMMITTEE_REVIEW":
                offer_to_reprice(offer)


def offer_to_reprice(offer):
    """Hop 5: void live votes, release the reservation, keep round/roll."""
    for vote in sorted_rows(lk.votes_of_offer(offer["id"])):
        if vote["status"] == "ACTIVE":
            set_fields(vote, status="VOIDED")
    set_fields(offer, status="REPRICE_REQUIRED")
    sync_vote_counters(offer)
    sync_group_for_offer(offer)


# ------------------------------------------------------------------------
# search fee (PRD 3.6)
# ------------------------------------------------------------------------

def search_fee_liability(engagement, total_first_year_comp, guaranteed_comp, hire_probe):
    if engagement is None:
        return "NONE", ZERO
    if engagement["status"] == "TERMINATED":
        return "NONE", ZERO
    start = engagement["exclusivity_start_date"]
    end = engagement["exclusivity_end_date"]
    tail_end = end + timedelta(days=engagement["tail_off_days"])
    fee_pct = engagement["fee_pct"]
    if start <= hire_probe < end:
        basis = "DIRECT_PLACEMENT"
        raw = calc.r2(total_first_year_comp * fee_pct)
    elif end <= hire_probe < tail_end:
        basis = "TAIL_OFF_CLAIM"
        raw = calc.r2(guaranteed_comp * fee_pct * calc.TAIL_OFF_DISCOUNT)
    else:
        return "NONE", ZERO
    return basis, min(raw, engagement["fee_cap_usd"])


def offer_economics(offer, candidate, group):
    """The five pinned steps of PRD 3.6."""
    snapshot = offer["adjusted_portable_total_snapshot_usd"]
    contribution = calc.expected_contribution(
        snapshot,
        candidate["notice_period_days"],
        group["leverage_ratio"],
        group["target_standard_rate_usd"],
        candidate["current_standard_rate_usd"],
    )
    total_comp = calc.r2(offer["guaranteed_comp_usd"] + offer["signing_bonus_usd"])
    engagement = db.engagements.get(candidate["sourcing_engagement_id"])
    _basis, fee = search_fee_liability(engagement, total_comp,
                                      offer["guaranteed_comp_usd"], db.clock)
    integration = (fee + calc.OFFICE_BUILDOUT_COST_USD
                   + calc.PARALEGAL_SUPPORT_COST_USD
                   + calc.r2(calc.ONBOARDING_OVERHEAD_PCT * total_comp))
    net = calc.r2(contribution - total_comp - integration)
    if net >= calc.TRUE_UP_HIGH_NET_THRESHOLD:
        true_up = calc.r2(calc.TRUE_UP_HIGH_PCT * offer["guaranteed_comp_usd"])
    elif net >= ZERO:
        true_up = calc.r2(calc.TRUE_UP_LOW_PCT * offer["guaranteed_comp_usd"])
    else:
        true_up = ZERO
    return {
        "expected_contribution_usd": contribution,
        "total_first_year_comp_usd": total_comp,
        "search_fee_amount_usd": fee,
        "integration_cost_total_usd": integration,
        "net_first_year_economics_usd": net,
        "guarantee_true_up_amount_usd": true_up,
    }
