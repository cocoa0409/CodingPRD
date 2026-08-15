"""Business logic: derived counters, rating, tiers, schedules, waterfalls,
campaign totals, recognition, endowment allowance, and clock sweeps."""

from datetime import timedelta
from decimal import Decimal

from core import (
    now, iso, touch, dec_floor_cents, dec_rhu_int, add_frequency_step, fy_start,
)
from db import store
from errors import fail, ERR_NOT_PROSPECT_OWNER

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD calculations)
# ---------------------------------------------------------------------------

EVIDENCE_MULTIPLIER = {
    "SELF_REPORTED": Decimal("0.6"),
    "PUBLIC_RECORD": Decimal("0.8"),
    "VERIFIED_DOCUMENT": Decimal("1.0"),
}
BAND_A_MIN = 1_000_000_000
BAND_B_MIN = 100_000_000
BAND_C_MIN = 25_000_000
BAND_D_MIN = 5_000_000

TYPE_MULTIPLIER = {"OUTRIGHT": Decimal("1.0"), "PLEDGE": Decimal("1.0"), "PLANNED": Decimal("0.5")}
TIER_MAJOR_MIN = 25_000_000
TIER_PRINCIPAL_MIN = 100_000_000

MATCHED_GIFT_FACTOR = Decimal("0.5")
MINIMUM_ACTIVATION_CENTS = 2_500_000
MAX_REMINDERS = 3
MAX_INSTALLMENTS = 120
SPENDING_RATE = Decimal("0.045")
MIN_QUARTERS = 4
MAX_QUARTERS = 12

OPEN_PROPOSAL_STATES = {"UNDER_REVIEW", "NEGOTIATING", "APPROVED"}
LEVEL_RANK = {"BRONZE": 0, "SILVER": 1, "GOLD": 2, "PLATINUM": 3}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def find(collection, entity_id):
    return store[collection].get(entity_id)


def all_of(collection):
    return list(store[collection].values())


# ---------------------------------------------------------------------------
# Fundraiser derived counters (recomputed from the graph)
# ---------------------------------------------------------------------------

def active_assignment_for(fundraiser_id, prospect_id):
    for a in store["assignments"].values():
        if a["fundraiser_id"] == fundraiser_id and a["prospect_id"] == prospect_id and a["status"] == "ACTIVE":
            return a
    return None


def active_assignment_of_prospect(prospect_id):
    for a in store["assignments"].values():
        if a["prospect_id"] == prospect_id and a["status"] == "ACTIVE":
            return a
    return None


def fundraiser_current_prospect_count(fundraiser_id):
    return sum(
        1 for a in store["assignments"].values()
        if a["fundraiser_id"] == fundraiser_id and a["status"] == "ACTIVE"
    )


def fundraiser_current_open_ask_cents(fundraiser_id):
    total = 0
    for p in store["proposals"].values():
        if p["status"] not in OPEN_PROPOSAL_STATES:
            continue
        assignment = active_assignment_of_prospect(p["prospect_id"])
        if assignment is not None and assignment["fundraiser_id"] == fundraiser_id:
            total += p["ask_amount_cents"]
    return total


def require_prospect_owner(user_id, prospect_id):
    """Priority 5: acting GiftOfficer must hold an ACTIVE assignment."""
    if active_assignment_for(user_id, prospect_id) is None:
        fail(ERR_NOT_PROSPECT_OWNER, "Acting GiftOfficer does not hold an ACTIVE assignment for this prospect")


def owner_fundraiser_id(prospect_id):
    assignment = active_assignment_of_prospect(prospect_id)
    return assignment["fundraiser_id"] if assignment else None


def bump_owner_fundraiser(prospect_id):
    """Recompute counters (derived on read) and advance the owner's version."""
    fid = owner_fundraiser_id(prospect_id)
    if fid is not None:
        touch(store["fundraisers"][fid])


# ---------------------------------------------------------------------------
# Prospect derived aggregates
# ---------------------------------------------------------------------------

def prospect_lifetime_given_cents(prospect_id):
    return sum(
        g["amount_cents"] for g in store["payments"].values()
        if g["donor_prospect_id"] == prospect_id and not g["reversed"]
    )


def pledge_outstanding_cents(pledge):
    total = 0
    for inst in store["installments"].values():
        if inst["pledge_id"] == pledge["id"]:
            total += inst["amount_cents"] - inst["paid_cents"] - inst["written_off_cents"]
    return total


def pledge_written_off_cents(pledge):
    return sum(
        inst["written_off_cents"] for inst in store["installments"].values()
        if inst["pledge_id"] == pledge["id"]
    )


def prospect_outstanding_pledge_cents(prospect_id):
    return sum(
        pledge_outstanding_cents(p) for p in store["pledges"].values()
        if p["prospect_id"] == prospect_id and p["status"] == "ACTIVE"
    )


def prospect_soft_credit_cents(prospect_id):
    total = 0
    for s in store["credit_splits"].values():
        if s["prospect_id"] == prospect_id and s["credit_type"] == "SOFT":
            payment = store["payments"].get(s["gift_payment_id"])
            if payment is not None and not payment["reversed"]:
                total += s["amount_cents"]
    return total


# ---------------------------------------------------------------------------
# Recognition societies
# ---------------------------------------------------------------------------

def pick_society(total_cents):
    """Highest threshold <= total; ties: lower level rank wins, then created_at ASC."""
    candidates = [s for s in store["societies"].values() if s["threshold_cash_cents"] <= total_cents]
    if not candidates:
        return None
    candidates.sort(key=lambda s: (-s["threshold_cash_cents"], LEVEL_RANK[s["level"]], s["created_at"], s["id"]))
    return candidates[0]


def recognition_read(prospect):
    cash = prospect_lifetime_given_cents(prospect["id"])
    soft = prospect_soft_credit_cents(prospect["id"])
    comprehensive = cash + prospect_outstanding_pledge_cents(prospect["id"]) + soft
    member = pick_society(cash)
    projected = pick_society(comprehensive)
    return {
        "cash_total_cents": cash,
        "comprehensive_total_cents": comprehensive,
        "soft_credit_cents": soft,
        "member_level": member["level"] if member else None,
        "projected_level": projected["level"] if projected else None,
    }


def refresh_prospect_recognition(prospect):
    read = recognition_read(prospect)
    member = pick_society(read["cash_total_cents"])
    prospect["recognition_society_id"] = member["id"] if member else None


# ---------------------------------------------------------------------------
# Campaign totals (FACE_VALUE_BOOKING and CASH_RECEIPTS variants)
# ---------------------------------------------------------------------------

def _matched_amount(payment):
    if payment["corporate_matched"]:
        return dec_floor_cents(Decimal(payment["amount_cents"]) * MATCHED_GIFT_FACTOR)
    return payment["amount_cents"]


def _counted_amount(payment):
    """The amount a payment contributes to campaign counting.

    PRD §3.7: "Only the `HARD` split's amount enters campaign counting (§3.9)" —
    when the payment carries splits, the HARD split's computed amount is the
    base; otherwise the payment's own amount. The corporate_matched halving
    (floor, per payment) then applies to that base per §3.9.
    """
    base = payment["amount_cents"]
    if payment["splits"]:
        hard = next(
            (s for s in store["credit_splits"].values()
             if s["gift_payment_id"] == payment["id"] and s["credit_type"] == "HARD"),
            None,
        )
        if hard is not None:
            base = hard["amount_cents"]
    if payment["corporate_matched"]:
        return dec_floor_cents(Decimal(base) * MATCHED_GIFT_FACTOR)
    return base


def _in_window(campaign, moment):
    return campaign["counting_start"] <= moment <= campaign["counting_end"]


def recompute_campaign_totals(campaign):
    """Recompute both variants. CLOSED/REPORTED campaigns are frozen."""
    if campaign["status"] not in ("DRAFT", "ACTIVE"):
        return
    face = 0
    cash = 0
    for p in store["pledges"].values():
        if (
            p["campaign_id"] == campaign["id"]
            and p["status"] in ("ACTIVE", "FULFILLED", "WRITTEN_OFF")
            and _in_window(campaign, p["created_at"])
        ):
            face += p["total_amount_cents"] - pledge_written_off_cents(p)
    for g in store["payments"].values():
        if g["campaign_id"] == campaign["id"] and not g["reversed"] and _in_window(campaign, g["received_at"]):
            if g["pledge_id"] is None:
                face += _counted_amount(g)
            cash += _counted_amount(g)
    campaign["face_value_counted_cents"] = face
    campaign["cash_counted_cents"] = cash


# ---------------------------------------------------------------------------
# Capacity / affinity rating (assessment approval)
# ---------------------------------------------------------------------------

def capacity_affinity_rating(assessment):
    mult = EVIDENCE_MULTIPLIER[assessment["evidence_tier"]]
    adjusted = dec_floor_cents(Decimal(assessment["assessed_capacity_cents"]) * mult)
    if adjusted >= BAND_A_MIN:
        band = "A"
    elif adjusted >= BAND_B_MIN:
        band = "B"
    elif adjusted >= BAND_C_MIN:
        band = "C"
    elif adjusted >= BAND_D_MIN:
        band = "D"
    else:
        band = "E"
    affinity = dec_rhu_int(
        Decimal("0.5") * assessment["engagement_score"]
        + Decimal("0.3") * assessment["philanthropy_score"]
        + Decimal("0.2") * assessment["recency_score"]
    )
    return adjusted, band, affinity


# ---------------------------------------------------------------------------
# Approval tier determination (proposal submit)
# ---------------------------------------------------------------------------

def approval_tier_determination(proposal, prospect):
    effective = dec_rhu_int(Decimal(proposal["ask_amount_cents"]) * TYPE_MULTIPLIER[proposal["proposal_type"]])
    if effective < TIER_MAJOR_MIN:
        base = "STANDARD"
    elif effective < TIER_PRINCIPAL_MIN:
        base = "MAJOR"
    else:
        base = "PRINCIPAL"
    if prospect["prospect_type"] == "INDIVIDUAL" and prospect["capacity_band"] == "A":
        tier = {"PRINCIPAL": "MAJOR", "MAJOR": "STANDARD", "STANDARD": "STANDARD"}[base]
    else:
        tier = base
    return tier, effective


# ---------------------------------------------------------------------------
# Installment schedule generation (front-loaded remainder, month-end clamp)
# ---------------------------------------------------------------------------

def generate_installments(pledge):
    count = pledge["installment_count"]
    base = pledge["total_amount_cents"] // count
    remainder = pledge["total_amount_cents"] - base * count
    rows = []
    for i in range(1, count + 1):
        amount = base + (1 if i <= remainder else 0)
        due = add_frequency_step(pledge["first_due_date"], pledge["frequency"], i - 1)
        rows.append({
            "pledge_id": pledge["id"],
            "sequence_number": i,
            "due_date": due,
            "amount_cents": amount,
            "paid_cents": 0,
            "written_off_cents": 0,
            "reminder_count": 0,
            "status": "SCHEDULED",
        })
    return rows


def open_installments(pledge):
    return [
        inst for inst in store["installments"].values()
        if inst["pledge_id"] == pledge["id"]
        and (inst["amount_cents"] - inst["paid_cents"] - inst["written_off_cents"]) > 0
    ]


def reevaluate_pledge_status(pledge):
    """ACTIVE <-> FULFILLED / WRITTEN_OFF re-evaluation (never undoes CANCELLED)."""
    if pledge["status"] == "CANCELLED":
        return
    insts = [i for i in store["installments"].values() if i["pledge_id"] == pledge["id"]]
    all_paid = all(i["status"] == "PAID" for i in insts)
    any_open = any(i["status"] in ("SCHEDULED", "REMINDED", "OVERDUE") for i in insts)
    any_written = any(i["written_off_cents"] > 0 for i in insts)
    if all_paid and not any_written:
        pledge["status"] = "FULFILLED"
    elif not any_open and any_written:
        pledge["status"] = "WRITTEN_OFF"
    else:
        pledge["status"] = "ACTIVE"


# ---------------------------------------------------------------------------
# Endowment spending allowance
# ---------------------------------------------------------------------------

def fund_allowances(fund):
    """Return (spendable_fy_cents, allowance_remaining_cents) for the current FY."""
    if not fund["is_endowed"]:
        return 0, 0
    start = fy_start(now())
    qualifying = [v for v in fund["trailing_market_values"] if v["quarter_end"] < start]
    qualifying.sort(key=lambda v: v["quarter_end"], reverse=True)
    quarters = qualifying[:MAX_QUARTERS]
    if len(quarters) < MIN_QUARTERS:
        spendable = 0
    else:
        avg = sum(Decimal(v["value_cents"]) for v in quarters) / Decimal(len(quarters))
        spendable = dec_rhu_int(SPENDING_RATE * avg)
    fy_end = datetime_next_fy(start)
    disbursed = sum(
        d["amount_cents"] for d in fund["disbursements"]
        if start <= d["created_at"] < fy_end
    )
    return spendable, spendable - disbursed


def datetime_next_fy(start):
    year = start.year + 1
    from datetime import datetime as _dt
    from datetime import timezone as _tz
    return _dt(year, 7, 1, 0, 0, 0, tzinfo=_tz.utc)


# ---------------------------------------------------------------------------
# Clock sweeps (run on every set_current_utc)
# ---------------------------------------------------------------------------

def run_sweeps(current):
    # (a) installments past due_date + 30 days -> OVERDUE (strict >)
    for inst in store["installments"].values():
        if inst["status"] in ("SCHEDULED", "REMINDED") and current > inst["due_date"] + timedelta(days=30):
            inst["status"] = "OVERDUE"
            touch(inst)

    # (b) APPROVED proposals older than 90 days with no agreement -> EXPIRED (strict >)
    for prop in store["proposals"].values():
        if prop["status"] != "APPROVED" or prop["approved_at"] is None:
            continue
        if current <= prop["approved_at"] + timedelta(days=90):
            continue
        referenced = any(a["proposal_id"] == prop["id"] for a in store["agreements"].values())
        if referenced:
            continue
        prop["status"] = "EXPIRED"
        touch(prop)
        bump_owner_fundraiser(prop["prospect_id"])

    # (c) naming reservations whose reserved_until has been reached -> AVAILABLE
    for opp in store["naming_opportunities"].values():
        if opp["status"] == "RESERVED" and opp["reserved_until"] is not None and current >= opp["reserved_until"]:
            opp["status"] = "AVAILABLE"
            opp["reserved_by_agreement_id"] = None
            opp["reserved_until"] = None
            touch(opp)

    # (d) DRAFT stewardship reports past due_date -> OVERDUE with cascades (strict >)
    for report in store["reports"].values():
        if report["status"] == "DRAFT" and current > report["due_date"]:
            report["status"] = "OVERDUE"
            touch(report)
            fund = store["funds"].get(report["fund_id"])
            if fund is not None:
                if fund["status"] == "ACTIVE":
                    fund["status"] = "SPENDING_FROZEN"
                    touch(fund)
                agreement = store["agreements"].get(fund["agreement_id"])
                if agreement is not None and agreement["compliance_status"] == "COMPLIANT":
                    agreement["compliance_status"] = "STEWARDSHIP_LAPSED"
                    touch(agreement)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _common(e):
    return {
        "id": e["id"],
        "created_at": iso(e["created_at"]),
        "updated_at": iso(e["updated_at"]),
        "version": e["version"],
    }


def ser_fundraiser(f):
    out = _common(f)
    out.update({
        "display_name": f["display_name"],
        "email": f["email"],
        "max_prospect_count": f["max_prospect_count"],
        "max_open_ask_cents": f["max_open_ask_cents"],
        "current_prospect_count": fundraiser_current_prospect_count(f["id"]),
        "current_open_ask_cents": fundraiser_current_open_ask_cents(f["id"]),
        "status": f["status"],
    })
    return out


def ser_prospect(p):
    out = _common(p)
    out.update({
        "full_name": p["full_name"],
        "prospect_type": p["prospect_type"],
        "contact_email": p["contact_email"],
        "spouse_prospect_id": p["spouse_prospect_id"],
        "research_status": p["research_status"],
        "moves_stage": p["moves_stage"],
        "capacity_band": p["capacity_band"],
        "affinity_score": p["affinity_score"],
        "rated_assessment_id": p["rated_assessment_id"],
        "rated_adjusted_capacity_cents": p["rated_adjusted_capacity_cents"],
        "lifetime_given_cents": prospect_lifetime_given_cents(p["id"]),
        "outstanding_pledge_cents": prospect_outstanding_pledge_cents(p["id"]),
        "recognition_society_id": p["recognition_society_id"],
    })
    return out


def ser_assessment(a):
    out = _common(a)
    out.update({
        "prospect_id": a["prospect_id"],
        "assessed_capacity_cents": a["assessed_capacity_cents"],
        "engagement_score": a["engagement_score"],
        "philanthropy_score": a["philanthropy_score"],
        "recency_score": a["recency_score"],
        "evidence_tier": a["evidence_tier"],
        "adjusted_capacity_cents": a["adjusted_capacity_cents"],
        "capacity_band_result": a["capacity_band_result"],
        "affinity_score_result": a["affinity_score_result"],
        "created_by": a["created_by"],
        "reviewed_by": a["reviewed_by"],
        "review_rationale": a["review_rationale"],
        "status": a["status"],
    })
    return out


def ser_assignment(a):
    out = _common(a)
    out.update({
        "fundraiser_id": a["fundraiser_id"],
        "prospect_id": a["prospect_id"],
        "status": a["status"],
        "released_reason": a["released_reason"],
    })
    return out


def ser_proposal(p):
    out = _common(p)
    out.update({
        "prospect_id": p["prospect_id"],
        "proposal_type": p["proposal_type"],
        "ask_amount_cents": p["ask_amount_cents"],
        "designation_purpose": p["designation_purpose"],
        "approval_tier": p["approval_tier"],
        "effective_ask_cents": p["effective_ask_cents"],
        "pinned_capacity_band": p["pinned_capacity_band"],
        "submitted_by": p["submitted_by"],
        "approvals_received": p["approvals_received"],
        "approver_ids": list(p["approver_ids"]),
        "decided_by": p["decided_by"],
        "decision_rationale": p["decision_rationale"],
        "approved_at": iso(p["approved_at"]) if p["approved_at"] else None,
        "status": p["status"],
    })
    return out


def ser_naming_opportunity(o):
    out = _common(o)
    out.update({
        "name": o["name"],
        "category": o["category"],
        "price_floor_cents": o["price_floor_cents"],
        "status": o["status"],
        "reserved_by_agreement_id": o["reserved_by_agreement_id"],
        "reserved_until": iso(o["reserved_until"]) if o["reserved_until"] else None,
    })
    return out


def ser_agreement(a):
    out = _common(a)
    out.update({
        "proposal_id": a["proposal_id"],
        "prospect_id": a["prospect_id"],
        "restriction_type": a["restriction_type"],
        "purpose_code": a["purpose_code"],
        "naming_opportunity_id": a["naming_opportunity_id"],
        "agreement_amount_cents": a["agreement_amount_cents"],
        "reservation_expires_at": iso(a["reservation_expires_at"]) if a["reservation_expires_at"] else None,
        "signature_status": a["signature_status"],
        "compliance_status": a["compliance_status"],
    })
    return out


def ser_fund(f):
    out = _common(f)
    spendable, remaining = fund_allowances(f)
    out.update({
        "agreement_id": f["agreement_id"],
        "purpose_code": f["purpose_code"],
        "is_endowed": f["is_endowed"],
        "balance_cents": f["balance_cents"],
        "minimum_activation_cents": f["minimum_activation_cents"],
        "trailing_market_values": [
            {"quarter_end": iso(v["quarter_end"]), "value_cents": v["value_cents"]}
            for v in f["trailing_market_values"]
        ],
        "spendable_fy_cents": spendable,
        "allowance_remaining_cents": remaining,
        "status": f["status"],
    })
    return out


def ser_pledge(p):
    out = _common(p)
    out.update({
        "agreement_id": p["agreement_id"],
        "prospect_id": p["prospect_id"],
        "fund_id": p["fund_id"],
        "campaign_id": p["campaign_id"],
        "total_amount_cents": p["total_amount_cents"],
        "installment_count": p["installment_count"],
        "frequency": p["frequency"],
        "first_due_date": iso(p["first_due_date"]),
        "written_off_cents": pledge_written_off_cents(p),
        "outstanding_cents": pledge_outstanding_cents(p),
        "status": p["status"],
    })
    return out


def ser_installment(i):
    out = _common(i)
    out.update({
        "pledge_id": i["pledge_id"],
        "sequence_number": i["sequence_number"],
        "due_date": iso(i["due_date"]),
        "amount_cents": i["amount_cents"],
        "paid_cents": i["paid_cents"],
        "written_off_cents": i["written_off_cents"],
        "reminder_count": i["reminder_count"],
        "status": i["status"],
    })
    return out


def ser_write_off(w):
    out = _common(w)
    out.update({
        "pledge_id": w["pledge_id"],
        "amount_cents": w["amount_cents"],
        "reason": w["reason"],
        "requested_by": w["requested_by"],
        "decided_by": w["decided_by"],
        "status": w["status"],
    })
    return out


def ser_payment(g):
    out = _common(g)
    out.update({
        "donor_prospect_id": g["donor_prospect_id"],
        "pledge_id": g["pledge_id"],
        "fund_id": g["fund_id"],
        "campaign_id": g["campaign_id"],
        "amount_cents": g["amount_cents"],
        "received_at": iso(g["received_at"]),
        "payment_method": g["payment_method"],
        "corporate_matched": g["corporate_matched"],
        "splits": g["splits"],
        "applied_allocations": list(g["applied_allocations"]),
        "reversed": g["reversed"],
        "reversed_at": iso(g["reversed_at"]) if g["reversed_at"] else None,
    })
    return out


def ser_campaign(c):
    out = _common(c)
    out.update({
        "name": c["name"],
        "goal_cents": c["goal_cents"],
        "counting_start": iso(c["counting_start"]),
        "counting_end": iso(c["counting_end"]),
        "face_value_counted_cents": c["face_value_counted_cents"],
        "cash_counted_cents": c["cash_counted_cents"],
        "status": c["status"],
    })
    return out


def ser_credit_split(s):
    out = _common(s)
    out.update({
        "campaign_id": s["campaign_id"],
        "gift_payment_id": s["gift_payment_id"],
        "prospect_id": s["prospect_id"],
        "credit_type": s["credit_type"],
        "split_pct": s["split_pct"],
        "amount_cents": s["amount_cents"],
    })
    return out


def ser_report(r):
    out = _common(r)
    out.update({
        "fund_id": r["fund_id"],
        "period_start": iso(r["period_start"]),
        "period_end": iso(r["period_end"]),
        "due_date": iso(r["due_date"]),
        "narrative": r["narrative"],
        "submitted_by": r["submitted_by"],
        "status": r["status"],
    })
    return out


def ser_society(s):
    out = _common(s)
    out.update({
        "name": s["name"],
        "level": s["level"],
        "threshold_cash_cents": s["threshold_cash_cents"],
        "benefits_text": s["benefits_text"],
    })
    return out
