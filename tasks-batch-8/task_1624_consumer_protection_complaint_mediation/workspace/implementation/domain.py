"""Domain logic: serializers, audit events, derived-signal recomputation
(pattern score / public rating), settlement fee, restitution allocation, the
terminal-closure ritual, and the logical-clock sweep."""

from datetime import timedelta
from decimal import Decimal

from helpers import fmt_clock, fmt_dt3, new_record, round_half_up_int, set_fields, touch
from store import db

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD calculations table)
# ---------------------------------------------------------------------------

FILING_WINDOW_DAYS = 365
RESPONSE_BASE_DAYS = 30
OUT_OF_STATE_EXTENSION_DAYS = 15
OFFER_TTL_DAYS = 14
COOLING_OFF_HOURS = 72
EMBARGO_DAYS = 10
SETTLEMENT_DUE_DAYS = 30
MEDIATOR_BUFFER_MINUTES = 30

W_SETTLED = 10
W_UNRESOLVED = 15
W_REFERRED = 25
OVERDUE_PENALTY = 5
PATTERN_WINDOW_DAYS = 730
WATCHLIST_MIN = 60
FLAGGED_MIN = 100
SCORE_CAP = 1000
SIZE_MULT = {"SMALL": Decimal("1.0"), "MEDIUM": Decimal("0.75"), "LARGE": Decimal("0.5")}

DEMERIT = {"SETTLED": 5, "CLOSED_UNRESOLVED": 15, "REFERRED_ENFORCEMENT": 25}
RECENCY_WINDOW_DAYS = 365
OLD_WEIGHT = Decimal("0.25")

TIER1_LIMIT = 100000
TIER2_LIMIT = 500000
TIER2_RATE = Decimal("0.02")
TIER3_RATE = Decimal("0.01")

TERMINAL_CASE_STATUSES = {"SETTLED", "CLOSED_UNRESOLVED", "REFERRED_ENFORCEMENT"}

CATEGORIES = {
    "DECEPTIVE_PRACTICE",
    "REFUND_REFUSAL",
    "DEFECTIVE_PRODUCT",
    "BILLING_DISPUTE",
    "WARRANTY_DENIED",
    "CONTRACT_VIOLATION",
    "OTHER",
}
SIZE_TIERS = {"SMALL", "MEDIUM", "LARGE"}
RATING_METHODS = {"LIFETIME", "ROLLING_12M"}
DECISIONS = {"ACCEPT", "DECLINE"}
DECLINE_REASONS = {"NO_JURISDICTION", "OUT_OF_AUTHORITY", "DUPLICATE"}
VERDICTS = {"SUFFICIENT", "INSUFFICIENT"}
OFFERED_BY_ROLES = {"CONSUMER", "BUSINESS"}
OUTCOMES = {"PROGRESS", "IMPASSE", "SETTLEMENT_REACHED"}
ALLOCATION_METHODS = {"CHRONOLOGICAL", "PRO_RATA"}
REFERRAL_DECISIONS = {"ACCEPT", "RETURN"}
SCAM_CATEGORIES = {
    "PHISHING",
    "IMPERSONATION",
    "ADVANCE_FEE",
    "FAKE_CHARITY",
    "TECH_SUPPORT",
    "ROMANCE",
    "OTHER",
}
SEVERITIES = {"LOW", "ELEVATED", "HIGH", "CRITICAL"}
ALTERNATIVE_OPTIONS = {
    "SMALL_CLAIMS",
    "PRIVATE_ATTORNEY",
    "BBB",
    "FEDERAL_AGENCY",
    "CLASS_ACTION",
}

# ---------------------------------------------------------------------------
# Audit trail (PRD section 2.4) -- append-only; id + created_at only.
# ---------------------------------------------------------------------------

def write_event(complaint_id, event_type, from_status, to_status,
                actor_role, actor_id, note=""):
    ev = {
        "id": new_record()["id"],
        "created_at": db.now,
        "complaint_id": complaint_id,
        "event_type": event_type,
        "from_status": from_status,
        "to_status": to_status,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "note": note,
    }
    db.events[ev["id"]] = ev
    return ev


# ---------------------------------------------------------------------------
# Derived business signals (PRD sections 2.11 / 3.8 / 3.9)
# ---------------------------------------------------------------------------

def recompute_pattern_score(business):
    """Rolling 730-day, severity-weighted terminal-complaint score; single
    rounding point after the size multiplier; clamped to [0, 1000]. Also
    derives the watch band (60/100, lower bounds inclusive)."""
    now = db.now
    window_start = now - timedelta(days=PATTERN_WINDOW_DAYS)
    raw = 0
    for c in db.complaints.values():
        if c["business_id"] != business["id"]:
            continue
        if c["closed_at"] is None or c["case_status"] not in TERMINAL_CASE_STATUSES:
            continue
        if not (window_start <= c["closed_at"] <= now):
            continue
        raw += {"SETTLED": W_SETTLED, "CLOSED_UNRESOLVED": W_UNRESOLVED,
                "REFERRED_ENFORCEMENT": W_REFERRED}[c["case_status"]]
        if c["ever_response_overdue"]:
            raw += OVERDUE_PENALTY
    score = round_half_up_int(Decimal(raw) * SIZE_MULT[business["size_tier"]])
    score = max(0, min(SCORE_CAP, score))
    if score >= FLAGGED_MIN:
        watch = "FLAGGED"
    elif score >= WATCHLIST_MIN:
        watch = "WATCHLIST"
    else:
        watch = "CLEAR"
    set_fields(business, pattern_score=score, watch_status=watch)


def _rating_tier(score):
    if score >= 90:
        return "A"
    if score >= 70:
        return "B"
    if score >= 40:
        return "C"
    return "D"


def recompute_rating(business):
    """Published-complaint demerits under the active rating_method variant.
    ROLLING_12M rounds the weighted demerit sum half-up BEFORE subtracting
    from 100; LIFETIME sums raw integer demerits."""
    published = [
        c for c in db.complaints.values()
        if c["business_id"] == business["id"] and c["publication_status"] == "PUBLISHED"
    ]
    if business["rating_method"] == "ROLLING_12M":
        now = db.now
        window_start = now - timedelta(days=RECENCY_WINDOW_DAYS)
        weighted = Decimal(0)
        for c in published:
            demerit = Decimal(DEMERIT[c["case_status"]])
            published_at = db.published_at.get(c["id"])
            if published_at is not None and window_start <= published_at <= now:
                weighted += demerit
            else:
                weighted += demerit * OLD_WEIGHT
        effective = round_half_up_int(weighted)
    else:
        effective = sum(DEMERIT[c["case_status"]] for c in published)
    score = max(0, 100 - effective)
    set_fields(business, rating_score=score, rating_tier=_rating_tier(score))


# ---------------------------------------------------------------------------
# Terminal-closure ritual (PRD section 3.8)
# ---------------------------------------------------------------------------

def run_closure_ritual(complaint, to_status):
    """Shared closing ritual for SETTLED / CLOSED_UNRESOLVED / REFERRED_ENFORCEMENT:
    stamp closed_at, move the publication axis, recompute the pattern score."""
    complaint["case_status"] = to_status
    complaint["closed_at"] = db.now
    if complaint["publication_status"] == "UNPUBLISHED":
        complaint["publication_status"] = (
            "EMBARGOED" if complaint["publication_consent"] else "SUPPRESSED"
        )
    business = db.businesses.get(complaint["business_id"])
    if business is not None:
        recompute_pattern_score(business)


# ---------------------------------------------------------------------------
# Settlement fee (PRD section 3.6) -- keyed on the restitution subtotal ONLY.
# ---------------------------------------------------------------------------

def settlement_fee_cents(restitution):
    if restitution < TIER1_LIMIT:
        return 0
    if restitution < TIER2_LIMIT:
        return round_half_up_int(TIER2_RATE * Decimal(restitution))
    return round_half_up_int(
        TIER2_RATE * Decimal(TIER2_LIMIT) + TIER3_RATE * Decimal(restitution - TIER2_LIMIT)
    )


# ---------------------------------------------------------------------------
# Restitution allocation (PRD section 3.7)
# ---------------------------------------------------------------------------

def eligible_obligations(business_id):
    """Open settlements of the business, ordered by complaint filing_seq ASC
    (filing_seq is unique per business, so no tie is possible)."""
    rows = []
    for s in db.settlements.values():
        if s["business_id"] != business_id:
            continue
        if s["settlement_status"] not in ("EXECUTED", "BREACHED"):
            continue
        if s["outstanding_cents"] <= 0:
            continue
        complaint = db.complaints[s["complaint_id"]]
        rows.append((complaint["filing_seq"], s))
    rows.sort(key=lambda r: r[0])
    return rows


def compute_allocations(payment, obligations):
    """Returns [(settlement, complaint, filing_seq, cents)]. Per-line
    round_half_up BEFORE remainder reconciliation (pinned rounding order)."""
    amount = payment["amount_cents"]
    if payment["allocation_method"] == "CHRONOLOGICAL":
        remaining = amount
        out = []
        for filing_seq, settlement in obligations:
            if remaining <= 0:
                break
            take = min(settlement["outstanding_cents"], remaining)
            if take > 0:
                out.append((settlement, db.complaints[settlement["complaint_id"]],
                            filing_seq, take))
                remaining -= take
        return out

    # PRO_RATA: provisional shares, then cent-by-cent reconciliation.
    total = sum(s["outstanding_cents"] for _, s in obligations)
    shares = [
        round_half_up_int(Decimal(amount) * Decimal(s["outstanding_cents"]) / Decimal(total))
        for _, s in obligations
    ]
    diff = amount - sum(shares)
    if diff > 0:
        # Add 1 cent per line in filing_seq ASC, cycling, until exhausted.
        i = 0
        while diff > 0:
            if shares[i] < obligations[i][1]["outstanding_cents"]:
                shares[i] += 1
                diff -= 1
            i = (i + 1) % len(shares)
    elif diff < 0:
        # Remove 1 cent per line in filing_seq DESC until balanced.
        i = len(shares) - 1
        while diff < 0:
            if shares[i] > 0:
                shares[i] -= 1
                diff += 1
            i = (i - 1) % len(shares)
    out = []
    for (filing_seq, settlement), share in zip(obligations, shares):
        if share > 0:
            out.append((settlement, db.complaints[settlement["complaint_id"]],
                        filing_seq, share))
    return out


# ---------------------------------------------------------------------------
# Logical-clock sweep (PRD section 2.6) -- ordered, filing order per complaint.
# ---------------------------------------------------------------------------

def _filing_order(complaints):
    return sorted(complaints, key=lambda c: (c["filed_at"], c["filing_seq"]))


def run_clock_sweep():
    now = db.now

    # (1) BUSINESS_NOTIFIED complaints whose deadline has strictly passed flip
    # to RESPONSE_OVERDUE.
    overdue = [
        c for c in db.complaints.values()
        if c["case_status"] == "BUSINESS_NOTIFIED"
        and c["response_deadline"] is not None
        and now > c["response_deadline"]
    ]
    for c in _filing_order(overdue):
        c["case_status"] = "RESPONSE_OVERDUE"
        c["ever_response_overdue"] = True
        touch(c)
        business = db.businesses.get(c["business_id"])
        if business is not None:
            business["overdue_response_count"] += 1
            touch(business)
        write_event(c["id"], "STATE_CHANGED", "BUSINESS_NOTIFIED",
                    "RESPONSE_OVERDUE", "system", "system",
                    "response deadline passed without a response")

    # (2) TENDERED offers whose expires_at has strictly passed become EXPIRED.
    expiring = [
        o for o in db.offers.values()
        if o["offer_status"] == "TENDERED" and now > o["expires_at"]
    ]
    expiring.sort(key=lambda o: (o["tendered_at"], o["offer_seq"]))
    for o in expiring:
        o["offer_status"] = "EXPIRED"
        touch(o)
        write_event(o["complaint_id"], "STATE_CHANGED", "TENDERED", "EXPIRED",
                    "system", "system", "offer expiry sweep")

    # (3) EMBARGOED complaints whose ten-day embargo has matured (inclusive
    # boundary) become PUBLISHED.
    maturing = [
        c for c in db.complaints.values()
        if c["publication_status"] == "EMBARGOED"
        and c["closed_at"] is not None
        and now >= c["closed_at"] + timedelta(days=EMBARGO_DAYS)
    ]
    for c in _filing_order(maturing):
        c["publication_status"] = "PUBLISHED"
        touch(c)
        db.published_at[c["id"]] = now
        business = db.businesses.get(c["business_id"])
        if business is not None:
            business["published_complaint_count"] += 1
            touch(business)
            recompute_rating(business)
        write_event(c["id"], "PUBLISHED", "EMBARGOED", "PUBLISHED",
                    "system", "system", "embargo matured")


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _common(rec):
    return {
        "created_at": fmt_dt3(rec["created_at"]),
        "updated_at": fmt_dt3(rec["updated_at"]),
        "version": rec["version"],
    }


def consumer_view(r):
    out = {
        "id": r["id"],
        "full_name": r["full_name"],
        "email": r["email"],
        "state_code": r["state_code"],
        "phone": r["phone"],
    }
    out.update(_common(r))
    return out


def business_view(r):
    out = {
        "id": r["id"],
        "legal_name": r["legal_name"],
        "dba_name": r["dba_name"],
        "home_state": r["home_state"],
        "operates_in_states": list(r["operates_in_states"]),
        "naics_code": r["naics_code"],
        "size_tier": r["size_tier"],
        "rating_method": r["rating_method"],
        "watch_status": r["watch_status"],
        "pattern_score": r["pattern_score"],
        "published_complaint_count": r["published_complaint_count"],
        "rating_score": r["rating_score"],
        "rating_tier": r["rating_tier"],
        "overdue_response_count": r["overdue_response_count"],
        "next_filing_seq": r["next_filing_seq"],
    }
    out.update(_common(r))
    return out


def complaint_view(r):
    out = {
        "id": r["id"],
        "consumer_id": r["consumer_id"],
        "business_id": r["business_id"],
        "incident_date": r["incident_date"],
        "incident_state": r["incident_state"],
        "category": r["category"],
        "description": r["description"],
        "amount_in_dispute_cents": r["amount_in_dispute_cents"],
        "publication_consent": r["publication_consent"],
        "filing_seq": r["filing_seq"],
        "filed_at": fmt_clock(r["filed_at"]),
        "case_status": r["case_status"],
        "publication_status": r["publication_status"],
        "decline_reason": r["decline_reason"],
        "appeal_used": r["appeal_used"],
        "jurisdiction_factors": dict(r["jurisdiction_factors"]),
        "accepted_by_officer_id": r["accepted_by_officer_id"],
        "closed_by_officer_id": r["closed_by_officer_id"],
        "closed_at": fmt_clock(r["closed_at"]),
        "response_deadline": fmt_clock(r["response_deadline"]),
        "response_received_at": fmt_clock(r["response_received_at"]),
        "response_attempts": r["response_attempts"],
        "latest_response_id": r["latest_response_id"],
        "ever_response_overdue": r["ever_response_overdue"],
        "active_settlement_id": r["active_settlement_id"],
        "alternative_options": r["alternative_options"],
        "closure_summary": r["closure_summary"],
    }
    out.update(_common(r))
    return out


def event_view(r):
    # Append-only: id + created_at only, no updated_at / version (PRD 2.4).
    return {
        "id": r["id"],
        "created_at": fmt_dt3(r["created_at"]),
        "complaint_id": r["complaint_id"],
        "event_type": r["event_type"],
        "from_status": r["from_status"],
        "to_status": r["to_status"],
        "actor_role": r["actor_role"],
        "actor_id": r["actor_id"],
        "note": r["note"],
    }


def response_view(r):
    out = {
        "id": r["id"],
        "complaint_id": r["complaint_id"],
        "business_id": r["business_id"],
        "response_text": r["response_text"],
        "submitted_at": fmt_clock(r["submitted_at"]),
        "is_late": r["is_late"],
        "response_status": r["response_status"],
        "attempt_number": r["attempt_number"],
    }
    out.update(_common(r))
    return out


def mediator_view(r):
    out = {
        "id": r["id"],
        "full_name": r["full_name"],
        "employee_ref": r["employee_ref"],
        "mediator_status": r["mediator_status"],
        "conflicted_business_ids": list(r["conflicted_business_ids"]),
        "max_concurrent_cases": r["max_concurrent_cases"],
        "active_case_count": r["active_case_count"],
    }
    out.update(_common(r))
    return out


def room_view(r):
    out = {
        "id": r["id"],
        "room_name": r["room_name"],
        "capacity": r["capacity"],
        "location": r["location"],
        "room_status": r["room_status"],
    }
    out.update(_common(r))
    return out


def session_view(r):
    out = {
        "id": r["id"],
        "complaint_id": r["complaint_id"],
        "mediator_id": r["mediator_id"],
        "room_id": r["room_id"],
        "starts_at": fmt_clock(r["starts_at"]),
        "ends_at": fmt_clock(r["ends_at"]),
        "session_status": r["session_status"],
        "consumer_confirmed": r["consumer_confirmed"],
        "business_confirmed": r["business_confirmed"],
        "outcome": r["outcome"],
    }
    out.update(_common(r))
    return out


def offer_view(r):
    out = {
        "id": r["id"],
        "complaint_id": r["complaint_id"],
        "parent_offer_id": r["parent_offer_id"],
        "offer_seq": r["offer_seq"],
        "offered_by_role": r["offered_by_role"],
        "offered_by_id": r["offered_by_id"],
        "restitution_amount_cents": r["restitution_amount_cents"],
        "non_monetary_terms": r["non_monetary_terms"],
        "offer_status": r["offer_status"],
        "tendered_at": fmt_clock(r["tendered_at"]),
        "expires_at": fmt_clock(r["expires_at"]),
        "accepted_at": fmt_clock(r["accepted_at"]),
        "cooling_off_until": fmt_clock(r["cooling_off_until"]),
    }
    out.update(_common(r))
    return out


def settlement_view(r):
    out = {
        "id": r["id"],
        "complaint_id": r["complaint_id"],
        "source_offer_id": r["source_offer_id"],
        "business_id": r["business_id"],
        "consumer_id": r["consumer_id"],
        "restitution_amount_cents": r["restitution_amount_cents"],
        "mediation_fee_cents": r["mediation_fee_cents"],
        "total_due_cents": r["total_due_cents"],
        "fulfilled_cents": r["fulfilled_cents"],
        "outstanding_cents": r["outstanding_cents"],
        "settlement_status": r["settlement_status"],
        "executed_at": fmt_clock(r["executed_at"]),
        "due_date": fmt_clock(r["due_date"]),
        "fulfilled_at": fmt_clock(r["fulfilled_at"]),
    }
    out.update(_common(r))
    return out


def payment_view(r):
    out = {
        "id": r["id"],
        "business_id": r["business_id"],
        "amount_cents": r["amount_cents"],
        "allocation_method": r["allocation_method"],
        "payment_status": r["payment_status"],
        "allocations": [dict(a) for a in r["allocations"]],
        "received_at": fmt_clock(r["received_at"]),
    }
    out.update(_common(r))
    return out


def referral_view(r):
    out = {
        "id": r["id"],
        "complaint_id": r["complaint_id"],
        "business_id": r["business_id"],
        "referred_by_user_id": r["referred_by_user_id"],
        "referred_by_role": r["referred_by_role"],
        "reason": r["reason"],
        "pattern_score_at_referral": r["pattern_score_at_referral"],
        "referral_status": r["referral_status"],
        "reviewed_by_user_id": r["reviewed_by_user_id"],
    }
    out.update(_common(r))
    return out


def alert_view(r):
    out = {
        "id": r["id"],
        "title": r["title"],
        "body": r["body"],
        "scam_category": r["scam_category"],
        "severity": r["severity"],
        "related_business_id": r["related_business_id"],
        "related_complaint_id": r["related_complaint_id"],
        "education_topics": list(r["education_topics"]),
        "drafted_by_user_id": r["drafted_by_user_id"],
        "alert_status": r["alert_status"],
        "published_at": fmt_clock(r["published_at"]),
    }
    out.update(_common(r))
    return out
