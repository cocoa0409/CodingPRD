"""Derived-field calculations (PRD §2.7, §2.11, §3.2, §3.5, §3.7, §3.8, §3.9)."""
from datetime import timedelta
from decimal import Decimal

from store import (ACTIVIST_PENALTY, ENGAGEMENT_CAP, ENGAGEMENT_MULTIPLIER,
                   HOLDER_TYPES, LEAD_BONUS_LONG, LEAD_BONUS_LONG_DAYS,
                   LEAD_BONUS_SHORT, LEAD_BONUS_SHORT_DAYS, NDA_BONUS,
                   OPEN_INQUIRY_STATUSES, SENSITIVITY_BASE, SENSITIVITY_CAP,
                   SLA_HOURS, TIER_1_MIN_PCT, TIER_2_MIN_PCT, TIER_POINTS,
                   TYPE_MULT, ANALYST_TERM, ACTIVIST_TERM,
                   DISCLOSURE_COMMITTEE_MIN_SENSITIVITY, ESCALATED_FOLLOWUP_TERM,
                   NONPUBLIC_TERM, POSTURE_BLACKOUT_TERM, POSTURE_RESTRICTED_TERM,
                   TA_DESK_MAX_SENSITIVITY, rhu, sorted_rows, store, touch)


# ------------------------------------------------- §3.2 ownership_pct / tier
def ownership_pct(shares_held, shares_outstanding):
    if not shares_outstanding:
        return Decimal("0.0000")
    quotient = (Decimal(shares_held) / Decimal(shares_outstanding)) * Decimal(100)
    return rhu(quotient, 4)


def target_tier(pct):
    if pct >= TIER_1_MIN_PCT:
        return "TIER_1"
    if pct >= TIER_2_MIN_PCT:
        return "TIER_2"
    if pct > 0:
        return "TIER_3"
    return "UNTIERED"


def apply_ownership(contact, company):
    contact["ownership_pct"] = ownership_pct(contact["shares_held"], company["shares_outstanding"])
    contact["target_tier"] = target_tier(contact["ownership_pct"])


# ------------------------------------------------- §2.7 company_disclosure_posture
def derive_posture(company):
    now = store.now()
    start = company["blackout_window_start"]
    end = company["blackout_window_end"]
    in_window = start is not None and end is not None and start <= now < end
    levels = set()
    for c in store.contacts.values():
        if c["company_id"] == company["id"] and c["activist_flag"]:
            levels.add(c["threat_level"])
    if in_window or "CRITICAL" in levels:
        return "BLACKOUT"
    if "ELEVATED" in levels:
        return "RESTRICTED"
    return "OPEN"


def count_open_inquiries(company_id):
    n = 0
    for i in store.inquiries.values():
        if i["company_id"] == company_id and i["status"] in OPEN_INQUIRY_STATUSES:
            n += 1
    return n


def refresh_posture(company):
    """Re-derive and store disclosure_posture + posture_recomputed_at (no version bump)."""
    company["disclosure_posture"] = derive_posture(company)
    company["posture_recomputed_at"] = store.now()
    return company["disclosure_posture"]


def recompute_sla(inquiry):
    inquiry["sla_due_at"] = store.now() + timedelta(hours=SLA_HOURS[inquiry["routing_queue"]])


# ------------------------------------------------- blackout draft-blocking chain
def blackout_block_chain(company):
    """Every ResponseDraft of this issuer in IN_REVIEW whose disclosure_class is
    MATERIAL_NONPUBLIC is forced to BLOCKED; its inquiry rewinds to DRAFTING."""
    for draft in sorted_rows(store.drafts):
        if draft["status"] != "IN_REVIEW" or draft["disclosure_class"] != "MATERIAL_NONPUBLIC":
            continue
        inquiry = store.inquiries.get(draft["inquiry_id"])
        if inquiry is None or inquiry["company_id"] != company["id"]:
            continue
        draft["status"] = "BLOCKED"
        draft["blocked_reason"] = "POSTURE_BLACKOUT"
        touch(draft)
        if inquiry["status"] == "AWAITING_APPROVAL":
            inquiry["status"] = "DRAFTING"
            recompute_sla(inquiry)
            touch(inquiry)


def inquiry_count_write(company):
    """Recount open_inquiry_count and bump the issuer's version WITHOUT re-deriving
    posture -- only the four events named in §2.7 may re-derive that."""
    company["open_inquiry_count"] = count_open_inquiries(company["id"])
    touch(company)


def posture_write(company, recount=False):
    """Refresh the stored posture (and optionally open_inquiry_count), bump the
    issuer's version, and fire the draft-blocking chain when it lands on BLACKOUT."""
    if recount:
        company["open_inquiry_count"] = count_open_inquiries(company["id"])
    posture = refresh_posture(company)
    touch(company)
    if posture == "BLACKOUT":
        blackout_block_chain(company)
    return posture


# ------------------------------------------------- §3.4 withdrawal cascade
def withdrawal_cascade(disclosure):
    """Links 2-4 of the PUBLISHED -> WITHDRAWN cascade."""
    touched_company_ids = []
    for draft in sorted_rows(store.drafts):
        if draft["cited_disclosure_id"] != disclosure["id"]:
            continue
        if draft["status"] not in ("IN_REVIEW", "APPROVED"):
            continue
        draft["status"] = "BLOCKED"
        draft["blocked_reason"] = "CITED_DISCLOSURE_WITHDRAWN"
        touch(draft)
        inquiry = store.inquiries.get(draft["inquiry_id"])
        if inquiry is not None and inquiry["status"] == "AWAITING_APPROVAL":
            inquiry["status"] = "DRAFTING"
            recompute_sla(inquiry)
            touch(inquiry)
            if inquiry["company_id"] not in touched_company_ids:
                touched_company_ids.append(inquiry["company_id"])
    for company_id in touched_company_ids:
        company = store.companies.get(company_id)
        if company is None:
            continue
        company["open_inquiry_count"] = count_open_inquiries(company_id)
        refresh_posture(company)
        touch(company)


# ------------------------------------------------- §3.5 inquiry intake scoring
def sensitivity_score(topic_category, requests_nonpublic_detail, contact, company, prior):
    total = SENSITIVITY_BASE[topic_category]
    if requests_nonpublic_detail:
        total += NONPUBLIC_TERM
    if contact["contact_type"] == "SELL_SIDE_ANALYST":
        total += ANALYST_TERM
    if contact["activist_flag"]:
        total += ACTIVIST_TERM
    if prior is not None and prior["status"] == "ESCALATED":
        total += ESCALATED_FOLLOWUP_TERM
    posture = company["disclosure_posture"]
    if posture == "BLACKOUT":
        total += POSTURE_BLACKOUT_TERM
    elif posture == "RESTRICTED":
        total += POSTURE_RESTRICTED_TERM
    return min(SENSITIVITY_CAP, total)


def routing_queue(topic_category, score, contact):
    if topic_category in ("DIVIDEND", "RECORD_DATE") and score < TA_DESK_MAX_SENSITIVITY:
        return "TRANSFER_AGENT_DESK"
    if score >= DISCLOSURE_COMMITTEE_MIN_SENSITIVITY:
        return "DISCLOSURE_COMMITTEE"
    if contact["contact_type"] == "RETAIL_HOLDER":
        return "SHAREHOLDER_SERVICES"
    return "IR_DESK"


# ------------------------------------------------- §3.8 meeting priority score
def priority_score(contact, lead_bonus):
    tier_points = Decimal(TIER_POINTS[contact["target_tier"]])
    nda = NDA_BONUS if contact["nda_on_file"] else Decimal(0)
    engagement = rhu(contact["ownership_pct"] * ENGAGEMENT_MULTIPLIER, 2)
    if engagement > ENGAGEMENT_CAP:
        engagement = ENGAGEMENT_CAP
    penalty = ACTIVIST_PENALTY if (
        contact["activist_flag"] and contact["threat_level"] in ("ELEVATED", "CRITICAL")
    ) else Decimal(0)
    additive = tier_points + nda + engagement + lead_bonus - penalty
    product = additive * TYPE_MULT[contact["contact_type"]]
    if product < 0:
        product = Decimal(0)
    return rhu(product, 2)


def provisional_score(contact):
    return priority_score(contact, Decimal(0))


def lead_time_bonus(requested_slot_start):
    delta = requested_slot_start - store.now()
    days = delta.total_seconds() // 86400
    if days >= LEAD_BONUS_LONG_DAYS:
        return LEAD_BONUS_LONG
    if days >= LEAD_BONUS_SHORT_DAYS:
        return LEAD_BONUS_SHORT
    return Decimal(0)


def final_score(contact, meeting_request):
    return priority_score(contact, lead_time_bonus(meeting_request["requested_slot_start"]))


def allocation_rank_key(meeting_request):
    contact = store.contacts.get(meeting_request["contact_id"])
    shares = contact["shares_held"] if contact else 0
    score = meeting_request["final_priority_score"] or Decimal(0)
    return (-score, -shares, meeting_request["created_at"], meeting_request["_seq"])


def refresh_event_counters(event):
    rows = [m for m in store.meeting_requests.values() if m["event_id"] == event["id"]]
    event["request_ledger_total"] = len(rows)
    event["allocated_count"] = sum(1 for m in rows if m["status"] == "ALLOCATED")
    event["waitlisted_count"] = sum(1 for m in rows if m["status"] == "WAITLISTED")
    event["released_count"] = sum(1 for m in rows if m["status"] == "RELEASED")
    event["declined_count"] = sum(1 for m in rows if m["status"] == "DECLINED")
