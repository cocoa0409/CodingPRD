"""Entity serializers: stored records -> JSON-safe dicts with computed fields.

Computed-on-read derivations live here (never persisted, never bump version):
- Community.closed_unit_pct
- TakedownTranche.accrued_penalty_cents (live while MISSED)
- AssociationBudget.total_expense_cents / reserve_cents (from line items)
- ReimbursementDistrict advance_principal / outstanding / provisional /
  certified_interest_to_date / available_funds
- InfrastructureAdvance.status
- DesignViolation.days_late (live until frozen)
- CommunityEvent.confirmed_count
"""
from datetime import timezone
from decimal import Decimal

from core import (
    DB, iso, calendar_days, round_half_up, round_half_up_int, dec_num,
    PENALTY_CAP_PCT,
)


def _base(e):
    return {
        "id": e["id"],
        "created_at": iso(e["created_at"]),
        "updated_at": iso(e["updated_at"]),
        "version": e["version"],
    }


# ---------------------------------------------------------------------------
# Calculation helpers used by serializers
# ---------------------------------------------------------------------------
def tranche_accrued_penalty(tranche):
    """accrued_penalty_cents: live-computed while MISSED; stored (frozen) otherwise."""
    if tranche["status"] == "MISSED":
        return compute_tranche_penalty(tranche, DB.now())
    return tranche.get("accrued_penalty_cents", 0)


def compute_tranche_penalty(tranche, at):
    agreement = DB.agreements.get(tranche["agreement_id"])
    if agreement is None:
        return 0
    days_late = calendar_days(tranche["due_date"], at)
    if days_late < 0:
        days_late = 0
    deficit = tranche["lot_count_due"] - tranche["lots_credited"]
    raw = deficit * agreement["penalty_per_lot_per_day_cents"] * days_late
    cap = round_half_up_int(
        PENALTY_CAP_PCT / Decimal(100)
        * tranche["lot_count_due"] * agreement["base_price_per_lot_cents"]
    )
    return min(raw, cap)


def budget_total_expense(budget):
    return sum(
        li["amount_cents"]
        for li in DB.line_items.values()
        if li["budget_id"] == budget["id"]
    )


def budget_reserve(budget):
    return sum(
        li["amount_cents"]
        for li in DB.line_items.values()
        if li["budget_id"] == budget["id"] and li["is_reserve"]
    )


def district_advances(district_id):
    return [a for a in DB.advances.values() if a["district_id"] == district_id]


def advance_derived_status(advance):
    if advance["reimbursed_principal_cents"] <= 0:
        return "OUTSTANDING"
    if advance["reimbursed_principal_cents"] >= advance["amount_cents"]:
        return "REIMBURSED"
    return "PARTIALLY_REIMBURSED"


def district_certified_interest_at(district, at):
    """Daily-compound interest over ALL advances to timestamp `at`, per-advance
    round-half-up, summed."""
    rate = Decimal(str(district["interest_rate_annual_pct"])) / Decimal(100) / Decimal(365)
    total = 0
    for adv in district_advances(district["id"]):
        days = calendar_days(adv["advance_date"], at)
        if days <= 0:
            continue
        acc = Decimal(adv["amount_cents"]) * ((Decimal(1) + rate) ** days - 1)
        total += round_half_up_int(acc)
    return total


def district_provisional_interest(district, at):
    """Simple interest per advance, round-half-up per advance, summed."""
    total = 0
    rate = Decimal(str(district["interest_rate_annual_pct"]))
    for adv in district_advances(district["id"]):
        days = calendar_days(adv["advance_date"], at)
        if days <= 0:
            continue
        acc = Decimal(adv["amount_cents"]) * rate / Decimal(100) * days / Decimal(365)
        total += round_half_up_int(acc)
    return total


def event_confirmed_count(event_id):
    return sum(
        r["party_size"]
        for r in DB.rsvps.values()
        if r["event_id"] == event_id and r["status"] == "CONFIRMED"
    )


def violation_live_days_late(violation):
    """days_late from cure_deadline to min(cured_at, fined_at, now); 0 while
    not past deadline."""
    cure_deadline = violation.get("cure_deadline")
    if cure_deadline is None:
        return 0
    endpoints = [DB.now()]
    if violation.get("cured_at") is not None:
        endpoints.append(violation["cured_at"])
    if violation.get("_fined_at") is not None:
        endpoints.append(violation["_fined_at"])
    end = min(endpoints)
    days = calendar_days(cure_deadline, end)
    return days if days > 0 else 0


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def community_out(c):
    d = _base(c)
    pct = round_half_up(
        Decimal(c["closed_unit_count"]) / Decimal(c["total_planned_units"]) * 100, 2
    )
    d.update({
        "community_name": c["community_name"],
        "total_planned_units": c["total_planned_units"],
        "status": c["status"],
        "closed_unit_count": c["closed_unit_count"],
        "closed_unit_pct": dec_num(pct),
        "transition_stage": c["transition_stage"],
    })
    return d


def phase_out(p):
    d = _base(p)
    d.update({
        "community_id": p["community_id"],
        "phase_name": p["phase_name"],
        "sequence_no": p["sequence_no"],
        "planned_lot_count": p["planned_lot_count"],
        "closed_lot_count": p["closed_lot_count"],
        "status": p["status"],
    })
    return d


def amenity_out(a):
    d = _base(a)
    d.update({
        "community_id": a["community_id"],
        "amenity_type": a["amenity_type"],
        "trigger_phase_id": a["trigger_phase_id"],
        "trigger_unit_count": a["trigger_unit_count"],
        "hard_deadline_date": iso(a["hard_deadline_date"]),
        "budgeted_cost_cents": a["budgeted_cost_cents"],
        "delinquency_recorded_at": iso(a["delinquency_recorded_at"]),
        "status": a["status"],
    })
    return d


def builder_out(b):
    d = _base(b)
    d.update({
        "community_id": b["community_id"],
        "legal_name": b["legal_name"],
        "credit_tier": b["credit_tier"],
        "standing": b["standing"],
        "total_lots_purchased": b["total_lots_purchased"],
    })
    return d


def agreement_out(a):
    d = _base(a)
    d.update({
        "community_id": a["community_id"],
        "builder_id": a["builder_id"],
        "phase_id": a["phase_id"],
        "base_price_per_lot_cents": a["base_price_per_lot_cents"],
        "annual_escalation_pct": a["annual_escalation_pct"],
        "penalty_per_lot_per_day_cents": a["penalty_per_lot_per_day_cents"],
        "earnest_money_cents": a["earnest_money_cents"],
        "total_lots_committed": a["total_lots_committed"],
        "execution_date": iso(a["execution_date"]),
        "lots_closed_count": a["lots_closed_count"],
        "forfeited_earnest_money_cents": a["forfeited_earnest_money_cents"],
        "status": a["status"],
    })
    return d


def tranche_out(t):
    d = _base(t)
    d.update({
        "agreement_id": t["agreement_id"],
        "tranche_no": t["tranche_no"],
        "due_date": iso(t["due_date"]),
        "lot_count_due": t["lot_count_due"],
        "lots_credited": t["lots_credited"],
        "cure_deadline": iso(t["cure_deadline"]),
        "accrued_penalty_cents": tranche_accrued_penalty(t),
        "status": t["status"],
    })
    return d


def lot_out(l):
    d = _base(l)
    d.update({
        "community_id": l["community_id"],
        "phase_id": l["phase_id"],
        "parcel_number": l["parcel_number"],
        "lot_premium_cents": l["lot_premium_cents"],
        "status": l["status"],
    })
    return d


def closing_out(c):
    d = _base(c)
    d.update({
        "community_id": c["community_id"],
        "agreement_id": c["agreement_id"],
        "lot_id": c["lot_id"],
        "owner_resident_id": c["owner_resident_id"],
        "closing_date": iso(c["closing_date"]),
        "escalated_base_cents": c["escalated_base_cents"],
        "premium_cents": c["premium_cents"],
        "price_cents": c["price_cents"],
        "credited_tranche_id": c["credited_tranche_id"],
        "is_surplus": c["is_surplus"],
        "status": c["status"],
    })
    return d


def budget_out(b):
    d = _base(b)
    d.update({
        "community_id": b["community_id"],
        "fiscal_year": b["fiscal_year"],
        "amendment_of_id": b["amendment_of_id"],
        "non_assessment_income_cents": b["non_assessment_income_cents"],
        "total_expense_cents": budget_total_expense(b),
        "reserve_cents": budget_reserve(b),
        "adopted_by_user_id": b["adopted_by_user_id"],
        "status": b["status"],
    })
    return d


def line_item_out(li):
    d = _base(li)
    d.update({
        "budget_id": li["budget_id"],
        "category": li["category"],
        "amount_cents": li["amount_cents"],
        "is_reserve": li["is_reserve"],
    })
    return d


def rate_out(r):
    d = _base(r)
    d.update({
        "community_id": r["community_id"],
        "budget_id": r["budget_id"],
        "fiscal_year": r["fiscal_year"],
        "subsidy_elected": r["subsidy_elected"],
        "per_unit_annual_cents": r["per_unit_annual_cents"],
        "quarterly_installments_cents": list(r["quarterly_installments_cents"]),
        "prior_rate_id": r["prior_rate_id"],
        "prior_per_unit_cents": r["prior_per_unit_cents"],
        "increase_pct": r["increase_pct"],
        "declarant_subsidy_cents": r["declarant_subsidy_cents"],
        "cap_override_approved_by": r["cap_override_approved_by"],
        "cap_override_ratified_by": r["cap_override_ratified_by"],
        "status": r["status"],
    })
    return d


def district_out(d):
    out = _base(d)
    advances = district_advances(d["id"])
    advance_principal = sum(a["amount_cents"] for a in advances)
    certified_principal = sum(
        p["certified_principal_cents"]
        for p in DB.payments.values()
        if p["district_id"] == d["id"] and p["status"] in ("CERTIFIED", "PAID")
    )
    certified_interest = sum(
        p["certified_interest_cents"]
        for p in DB.payments.values()
        if p["district_id"] == d["id"] and p["status"] in ("CERTIFIED", "PAID")
    )
    collected = sum(
        l["amount_cents"]
        for l in DB.levies.values()
        if l["district_id"] == d["id"] and l["status"] == "COLLECTED"
    )
    paid = sum(
        p["amount_cents"]
        for p in DB.payments.values()
        if p["district_id"] == d["id"] and p["status"] == "PAID"
    )
    out.update({
        "community_id": d["community_id"],
        "district_name": d["district_name"],
        "interest_rate_annual_pct": d["interest_rate_annual_pct"],
        "advance_principal_cents": advance_principal,
        "outstanding_principal_cents": advance_principal - certified_principal,
        "provisional_interest_cents": district_provisional_interest(d, DB.now()),
        "certified_interest_to_date_cents": certified_interest,
        "available_funds_cents": collected - paid,
    })
    return out


def advance_out(a):
    d = _base(a)
    d.update({
        "district_id": a["district_id"],
        "amount_cents": a["amount_cents"],
        "advance_date": iso(a["advance_date"]),
        "description": a["description"],
        "reimbursed_principal_cents": a["reimbursed_principal_cents"],
        "status": advance_derived_status(a),
    })
    return d


def levy_out(l):
    d = _base(l)
    d.update({
        "district_id": l["district_id"],
        "levy_year": l["levy_year"],
        "amount_cents": l["amount_cents"],
        "collected_at": iso(l["collected_at"]),
        "status": l["status"],
    })
    return d


def payment_out(p):
    d = _base(p)
    d.update({
        "district_id": p["district_id"],
        "requested_by_user_id": p["requested_by_user_id"],
        "amount_cents": p["amount_cents"],
        "certified_interest_cents": p["certified_interest_cents"],
        "certified_principal_cents": p["certified_principal_cents"],
        "certified_at": iso(p["certified_at"]),
        "paid_at": iso(p["paid_at"]),
        "status": p["status"],
    })
    return d


def application_out(a):
    d = _base(a)
    d.update({
        "community_id": a["community_id"],
        "lot_id": a["lot_id"],
        "applicant_builder_id": a["applicant_builder_id"],
        "applicant_resident_id": a["applicant_resident_id"],
        "project_type": a["project_type"],
        "submission_round": a["submission_round"],
        "review_fee_cents": a["review_fee_cents"],
        "reviewer_user_id": a["reviewer_user_id"],
        "denied_by_user_id": a["denied_by_user_id"],
        "conditions_text": a["conditions_text"],
        "construction_start_by": iso(a["construction_start_by"]),
        "status": a["status"],
    })
    return d


def violation_out(v):
    d = _base(v)
    d.update({
        "community_id": v["community_id"],
        "lot_id": v["lot_id"],
        "respondent_resident_id": v["respondent_resident_id"],
        "respondent_builder_id": v["respondent_builder_id"],
        "violation_type": v["violation_type"],
        "cure_deadline": iso(v["cure_deadline"]),
        "days_late": violation_live_days_late(v),
        "fine_cents": v["fine_cents"],
        "cured_at": iso(v["cured_at"]),
        "fined_by_user_id": v["fined_by_user_id"],
        "status": v["status"],
    })
    return d


def event_out(e):
    d = _base(e)
    d.update({
        "community_id": e["community_id"],
        "title": e["title"],
        "venue": e["venue"],
        "start_at": iso(e["start_at"]),
        "end_at": iso(e["end_at"]),
        "capacity": e["capacity"],
        "cost_cents": e["cost_cents"],
        "charged_budget_id": e["charged_budget_id"],
        "confirmed_count": event_confirmed_count(e["id"]),
        "status": e["status"],
    })
    return d


def rsvp_out(r):
    d = _base(r)
    d.update({
        "event_id": r["event_id"],
        "resident_id": r["resident_id"],
        "party_size": r["party_size"],
        "status": r["status"],
    })
    return d


def appointment_out(a):
    d = _base(a)
    d.update({
        "community_id": a["community_id"],
        "agent_name": a["agent_name"],
        "visitor_name": a["visitor_name"],
        "start_at": iso(a["start_at"]),
        "end_at": iso(a["end_at"]),
        "status": a["status"],
    })
    return d


def resident_out(r):
    d = _base(r)
    d.update({
        "community_id": r["community_id"],
        "lot_id": r["lot_id"],
        "full_name": r["full_name"],
        "email": r["email"],
        "owner_since": iso(r["owner_since"]),
        "status": r["status"],
    })
    return d


def notice_out(n):
    d = _base(n)
    d.update({
        "community_id": n["community_id"],
        "notice_type": n["notice_type"],
        "subject": n["subject"],
        "body": n["body"],
        "send_at": iso(n["send_at"]),
        "sent_at": iso(n["sent_at"]),
        "effective_date": iso(n["effective_date"]),
        "budget_id": n["budget_id"],
        "assessment_rate_id": n["assessment_rate_id"],
        "supersedes_notice_id": n["supersedes_notice_id"],
        "status": n["status"],
    })
    return d


def board_seat_out(s):
    d = _base(s)
    d.update({
        "community_id": s["community_id"],
        "seat_no": s["seat_no"],
        "seat_class": s["seat_class"],
        "holder_name": s["holder_name"],
        "holder_resident_id": s["holder_resident_id"],
        "eligible_voter_count": s["eligible_voter_count"],
        "election_deadline": iso(s["election_deadline"]),
        "status": s["status"],
    })
    return d
