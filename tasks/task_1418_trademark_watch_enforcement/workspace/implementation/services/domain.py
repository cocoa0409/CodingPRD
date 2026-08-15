"""Domain logic: calculations, computed fields, cascades, sweep, serializers.

All `source: computed` fields are derived at read time from stored state, so
derived values are always consistent by construction (ledger invariant,
exposure index, posture, counters). All monetary values are integer cents.
"""

from decimal import Decimal, ROUND_HALF_UP

import db
from util import (
    parse_dt, fmt_business, touch, stamp_new,
    business_day_count, calendar_roll_forward, add_months,
)

# ---------------------------------------------------------------------------
# Constants (scaffold 1.3 calculations)
# ---------------------------------------------------------------------------

ISSUE_FEE_CENTS = 75000
REISSUE_FEE_CENTS = 25000
PLATFORM_FEE_CENTS = {
    "AMAZON": 15000,
    "EBAY": 12000,
    "ALIBABA": 18000,
    "META": 9000,
    "DOMAIN_REGISTRAR": 25000,
}
MATTER_WEIGHT = {"OPPOSITION": 10, "CANCELLATION": 15, "INFRINGEMENT": 20, "COUNTERFEIT": 25}
JEOPARDY_MULTIPLIER = Decimal("1.5")
ELEVATED_THRESHOLD = 100

PER_CLASS_FEE_CENTS = 40000
BAND_HIGH_MIN_CENTS = 240000
SURCHARGE_RATE_HIGH = Decimal("0.25")
SURCHARGE_RATE_STANDARD = Decimal("0.10")
LATE_PER_CLASS_CENTS = 10000

STATUTORY_MULTIPLIER = Decimal("1.5")

PROVISIONAL_WEIGHT_MARK = Decimal("0.5")
PROVISIONAL_WEIGHT_GOODS = Decimal("0.3")
PROVISIONAL_WEIGHT_CHANNELS = Decimal("0.2")
FLOOR_MIN_SCORE = Decimal(85)
TIER_HIGH_MIN = Decimal(70)
TIER_MEDIUM_MIN = Decimal(40)

OPPOSITION_WINDOW_DAYS = 30

LIVE_AGREEMENT_STATES = ("EXECUTED", "MONITORING", "BREACH_ALLEGED", "CURE_PERIOD")
OPEN_DEADLINE_STATES = ("DOCKETED", "PENDING", "EXTENDED")


# ---------------------------------------------------------------------------
# confusion_score (scaffold 1.3)
# ---------------------------------------------------------------------------

def confusion_score(similarity_mark, similarity_goods, similarity_channels,
                    weight_mark, weight_goods, weight_channels, fame_adjustment):
    """raw = weighted sum; round half-up to 2dp; + fame (assessed only);
    clamp 0..100; identical-presumption floor 85 when mark>=90 and goods>=90."""
    raw = (Decimal(str(weight_mark)) * similarity_mark
           + Decimal(str(weight_goods)) * similarity_goods
           + Decimal(str(weight_channels)) * similarity_channels)
    score = raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    score = score + Decimal(fame_adjustment)
    score = min(Decimal(100), max(Decimal(0), score))
    if similarity_mark >= 90 and similarity_goods >= 90:
        score = max(score, FLOOR_MIN_SCORE)
    return score


def provisional_score(similarity_mark, similarity_goods, similarity_channels):
    return confusion_score(similarity_mark, similarity_goods, similarity_channels,
                           PROVISIONAL_WEIGHT_MARK, PROVISIONAL_WEIGHT_GOODS,
                           PROVISIONAL_WEIGHT_CHANNELS, 0)


def tier_of(score):
    if score >= TIER_HIGH_MIN:
        return "HIGH"
    if score >= TIER_MEDIUM_MIN:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# maintenance_filing_fee (scaffold 1.3) — pinned order:
# (1) base, (2) band from BASE ONLY, (3) surcharge, (4) late, (5) total.
# ---------------------------------------------------------------------------

def maintenance_fees(record, is_late):
    classes_count = len(record["nice_classes"])
    base = classes_count * PER_CLASS_FEE_CENTS
    band_high = base >= BAND_HIGH_MIN_CENTS
    rate = SURCHARGE_RATE_HIGH if band_high else SURCHARGE_RATE_STANDARD
    surcharge = int((Decimal(base) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    late_fee = classes_count * LATE_PER_CLASS_CENTS if is_late else 0
    return base, surcharge, late_fee, base + surcharge + late_fee


# ---------------------------------------------------------------------------
# counterfeit_damages (scaffold 1.3) — round each line to whole cents FIRST.
# ---------------------------------------------------------------------------

def statutory_damages_cents(seizure_lines):
    total = 0
    for line in seizure_lines:
        line_value = (Decimal(line["units"]) * Decimal(line["unit_value_cents"])
                      * STATUTORY_MULTIPLIER).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        total += int(line_value)
    return total


# ---------------------------------------------------------------------------
# settlement_installments (scaffold 1.3) — floor division; remainder on FINAL.
# ---------------------------------------------------------------------------

def settlement_installments(settlement_amount_cents, installment_count):
    base = settlement_amount_cents // installment_count
    remainder = settlement_amount_cents - base * installment_count
    schedule = [base] * (installment_count - 1)
    schedule.append(base + remainder)
    return schedule


# ---------------------------------------------------------------------------
# Computed / derived fields
# ---------------------------------------------------------------------------

def verified_evidence_count(record_id):
    return sum(1 for e in db.evidence_items.values()
               if e["trademark_record_id"] == record_id and e["status"] == "VERIFIED")


def confirmed_counterfeit_count(alert_id):
    return sum(1 for f in db.takedown_filings.values()
               if f["watch_alert_id"] == alert_id and f["basis"] == "COUNTERFEIT"
               and f["status"] == "REMOVED")


def matter_posture(matter):
    """JEOPARDY iff any linked Deadline has status == MISSED."""
    for d in db.deadlines.values():
        if d["enforcement_matter_id"] == matter["id"] and d["status"] == "MISSED":
            return "JEOPARDY"
    return "NORMAL"


def open_deadline_count(matter_id):
    return sum(1 for d in db.deadlines.values()
               if d["enforcement_matter_id"] == matter_id and d["status"] in OPEN_DEADLINE_STATES)


def letter_accrued_fees(letter):
    """Fees a letter contributes: issue fee (if ever issued) + reissue fee per
    reissue; reversed entirely (excluded) once the letter is VOID."""
    if letter["status"] == "VOID" or not letter.get("_ever_issued"):
        return 0
    return ISSUE_FEE_CENTS + REISSUE_FEE_CENTS * letter["reissue_count"]


def matter_accrued_fees(matter_id):
    return sum(letter_accrued_fees(l) for l in db.cease_desist_letters.values()
               if l["enforcement_matter_id"] == matter_id)


def _client_alert_ids(client_id):
    record_ids = {r["id"] for r in db.trademark_records.values() if r["client_id"] == client_id}
    return {a["id"] for a in db.watch_alerts.values() if a["trademark_record_id"] in record_ids}


def client_budget_spent(client_id):
    """fee_accrual_ledger: non-VOID letter fees + non-DRAFT takedown fees."""
    total = 0
    for m in db.enforcement_matters.values():
        if m["client_id"] == client_id:
            total += matter_accrued_fees(m["id"])
    alert_ids = _client_alert_ids(client_id)
    for f in db.takedown_filings.values():
        if f["watch_alert_id"] in alert_ids and f["status"] != "DRAFT":
            total += f["fee_cents"]
    return total


def client_exposure_index(client_id):
    """portfolio_exposure_index: sum over ACTIVE matters of weight (* 1.5 when
    JEOPARDY); round half-up ONCE on the final sum."""
    total = Decimal(0)
    for m in db.enforcement_matters.values():
        if m["client_id"] == client_id and m["status"] == "ACTIVE":
            weight = Decimal(MATTER_WEIGHT[m["matter_type"]])
            if matter_posture(m) == "JEOPARDY":
                total += weight * JEOPARDY_MULTIPLIER
            else:
                total += weight
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def client_watch_posture(client_id):
    return "ELEVATED" if client_exposure_index(client_id) >= ELEVATED_THRESHOLD else "STANDARD"


def search_unresolved_hit_count(search):
    return sum(1 for h in search["conflict_hits"] if h["disposition"] == "OPEN")


def search_risk_rating(search):
    """Max severity among non-WAIVED hits, IDENTICAL mapped to HIGH; none -> LOW."""
    best = "LOW"
    rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    found = False
    for h in search["conflict_hits"]:
        if h["disposition"] == "WAIVED":
            continue
        sev = "HIGH" if h["severity"] == "IDENTICAL" else h["severity"]
        found = True
        if rank[sev] > rank[best]:
            best = sev
    return best if found else "LOW"


# ---------------------------------------------------------------------------
# Cross-resource helpers
# ---------------------------------------------------------------------------

def client_id_of_alert(alert):
    record = db.trademark_records.get(alert["trademark_record_id"])
    return record["client_id"] if record else None


def active_matter_of_alert(alert):
    """The alert's ACTIVE EnforcementMatter (used when the alert is ESCALATED)."""
    for m in db.enforcement_matters.values():
        if m["watch_alert_id"] == alert["id"] and m["status"] == "ACTIVE":
            return m
    return None


def client_id_for_resource(kind, ent):
    """Resolve the owning Client id of any resource (for ClientContact scope)."""
    if ent is None:
        return None
    if kind == "client":
        return ent["id"]
    if kind == "trademark_record":
        return ent["client_id"]
    if kind == "watch_alert":
        return client_id_of_alert(ent)
    if kind == "enforcement_matter":
        return ent["client_id"]
    if kind == "deadline":
        matter = db.enforcement_matters.get(ent["enforcement_matter_id"])
        return matter["client_id"] if matter else None
    if kind == "cease_desist_letter":
        matter = db.enforcement_matters.get(ent["enforcement_matter_id"])
        return matter["client_id"] if matter else None
    if kind == "takedown_filing":
        alert = db.watch_alerts.get(ent["watch_alert_id"])
        return client_id_of_alert(alert) if alert else None
    if kind == "coexistence_agreement":
        record = db.trademark_records.get(ent["trademark_record_id"])
        return record["client_id"] if record else None
    if kind == "evidence_item":
        record = db.trademark_records.get(ent["trademark_record_id"])
        return record["client_id"] if record else None
    if kind == "maintenance_filing":
        record = db.trademark_records.get(ent["trademark_record_id"])
        return record["client_id"] if record else None
    if kind == "clearance_search":
        return ent["client_id"]
    if kind == "customs_recordation":
        record = db.trademark_records.get(ent["trademark_record_id"])
        return record["client_id"] if record else None
    if kind == "counterfeit_referral":
        alert = db.watch_alerts.get(ent["watch_alert_id"])
        return client_id_of_alert(alert) if alert else None
    return None


# ---------------------------------------------------------------------------
# Serializers (declared fields + common fields only)
# ---------------------------------------------------------------------------

def ser_client(c):
    spent = client_budget_spent(c["id"])
    exposure = client_exposure_index(c["id"])
    return {
        "id": c["id"],
        "name": c["name"],
        "industry": c["industry"],
        "enforcement_budget_cents": c["enforcement_budget_cents"],
        "budget_spent_cents": spent,
        "budget_remaining_cents": c["enforcement_budget_cents"] - spent,
        "exposure_index": exposure,
        "watch_posture": "ELEVATED" if exposure >= ELEVATED_THRESHOLD else "STANDARD",
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_trademark_record(r):
    return {
        "id": r["id"],
        "client_id": r["client_id"],
        "mark_text": r["mark_text"],
        "mark_type": r["mark_type"],
        "jurisdiction": r["jurisdiction"],
        "nice_classes": list(r["nice_classes"]),
        "application_number": r["application_number"],
        "status": r["status"],
        "publication_date": r["publication_date"],
        "registration_date": r["registration_date"],
        "opposition_due_at": r["opposition_due_at"],
        "verified_evidence_count": verified_evidence_count(r["id"]),
        "maintenance_window_open": r["maintenance_window_open"],
        "maintenance_window_close": r["maintenance_window_close"],
        "maintenance_grace_close": r["maintenance_grace_close"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_watch_alert(a):
    return {
        "id": a["id"],
        "trademark_record_id": a["trademark_record_id"],
        "source": a["source"],
        "conflicting_mark_text": a["conflicting_mark_text"],
        "conflicting_owner": a["conflicting_owner"],
        "conflicting_classes": list(a["conflicting_classes"]),
        "similarity_mark": a["similarity_mark"],
        "similarity_goods": a["similarity_goods"],
        "similarity_channels": a["similarity_channels"],
        "provisional_score": a["provisional_score"],
        "provisional_tier": a["provisional_tier"],
        "final_score": a["final_score"],
        "final_tier": a["final_tier"],
        "assessment_round": a["assessment_round"],
        "escalation_level": a["escalation_level"],
        "confirmed_counterfeit_count": confirmed_counterfeit_count(a["id"]),
        "referral_auto_created": a["referral_auto_created"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_enforcement_matter(m):
    return {
        "id": m["id"],
        "client_id": m["client_id"],
        "trademark_record_id": m["trademark_record_id"],
        "watch_alert_id": m["watch_alert_id"],
        "matter_type": m["matter_type"],
        "status": m["status"],
        "posture": matter_posture(m),
        "resolution_outcome": m["resolution_outcome"],
        "accrued_fees_cents": matter_accrued_fees(m["id"]),
        "open_deadline_count": open_deadline_count(m["id"]),
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def ser_deadline(d):
    return {
        "id": d["id"],
        "enforcement_matter_id": d["enforcement_matter_id"],
        "deadline_type": d["deadline_type"],
        "statutory_basis": d["statutory_basis"],
        "basis_date": d["basis_date"],
        "offset_days": d["offset_days"],
        "computation_variant": d["computation_variant"],
        "computed_due_at": d["computed_due_at"],
        "extension_count": d["extension_count"],
        "max_extensions": d["max_extensions"],
        "docketed_by_user_id": d["docketed_by_user_id"],
        "verified_by_user_id": d["verified_by_user_id"],
        "satisfied_at": d["satisfied_at"],
        "satisfied_late": d["satisfied_late"],
        "requires_partner_review": d["requires_partner_review"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def ser_letter(l):
    return {
        "id": l["id"],
        "enforcement_matter_id": l["enforcement_matter_id"],
        "demand_type": l["demand_type"],
        "recipient_name": l["recipient_name"],
        "recipient_address": l["recipient_address"],
        "response_due_days": l["response_due_days"],
        "settlement_amount_cents": l["settlement_amount_cents"],
        "installment_count": l["installment_count"],
        "drafted_by_user_id": l["drafted_by_user_id"],
        "approved_by_user_id": l["approved_by_user_id"],
        "issued_at": l["issued_at"],
        "response_due_at": l["response_due_at"],
        "reissue_count": l["reissue_count"],
        "installment_schedule": l["installment_schedule"],
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def ser_takedown_filing(f):
    return {
        "id": f["id"],
        "watch_alert_id": f["watch_alert_id"],
        "platform": f["platform"],
        "listing_url": f["listing_url"],
        "basis": f["basis"],
        "fee_cents": f["fee_cents"],
        "appeal_count": f["appeal_count"],
        "status": f["status"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def ser_agreement(a):
    return {
        "id": a["id"],
        "trademark_record_id": a["trademark_record_id"],
        "enforcement_matter_id": a["enforcement_matter_id"],
        "counterparty_name": a["counterparty_name"],
        "territory_codes": list(a["territory_codes"]),
        "effective_start": a["effective_start"],
        "effective_end": a["effective_end"],
        "cure_period_days": a["cure_period_days"],
        "round_count": a["round_count"],
        "current_terms_text": a["current_terms_text"],
        "breach_claimed_at": a["breach_claimed_at"],
        "cure_deadline": a["cure_deadline"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_evidence_item(e):
    return {
        "id": e["id"],
        "trademark_record_id": e["trademark_record_id"],
        "nice_class": e["nice_class"],
        "specimen_type": e["specimen_type"],
        "specimen_date": e["specimen_date"],
        "collected_by_user_id": e["collected_by_user_id"],
        "verified_by_user_id": e["verified_by_user_id"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_maintenance_filing(f):
    return {
        "id": f["id"],
        "trademark_record_id": f["trademark_record_id"],
        "filing_type": f["filing_type"],
        "evidence_item_ids": list(f["evidence_item_ids"]),
        "fee_base_cents": f["fee_base_cents"],
        "fee_surcharge_cents": f["fee_surcharge_cents"],
        "late_fee_cents": f["late_fee_cents"],
        "fee_total_cents": f["fee_total_cents"],
        "is_late": f["is_late"],
        "status": f["status"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def ser_clearance_search(s):
    return {
        "id": s["id"],
        "client_id": s["client_id"],
        "proposed_mark": s["proposed_mark"],
        "proposed_classes": list(s["proposed_classes"]),
        "conflict_hits": [dict(h) for h in s["conflict_hits"]],
        "unresolved_hit_count": search_unresolved_hit_count(s),
        "risk_rating": search_risk_rating(s),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_customs_recordation(c):
    return {
        "id": c["id"],
        "trademark_record_id": c["trademark_record_id"],
        "customs_authority": c["customs_authority"],
        "recordation_number": c["recordation_number"],
        "term_start": c["term_start"],
        "term_end": c["term_end"],
        "supersedes_recordation_id": c["supersedes_recordation_id"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_counterfeit_referral(r):
    return {
        "id": r["id"],
        "watch_alert_id": r["watch_alert_id"],
        "enforcement_matter_id": r["enforcement_matter_id"],
        "referral_channel": r["referral_channel"],
        "seizure_lines": [dict(line) for line in r["seizure_lines"]],
        "estimated_damages_cents": r["estimated_damages_cents"],
        "auto_created": r["auto_created"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def moot_cascade(record):
    """Record -> CANCELLED moot cascade (PRD 3.2): ESCALATED alerts DISMISSED,
    ACTIVE recordations REVOKED, live agreements TERMINATED."""
    for a in db.watch_alerts.values():
        if a["trademark_record_id"] == record["id"] and a["status"] == "ESCALATED":
            a["status"] = "DISMISSED"
            touch(a)
    for c in db.customs_recordations.values():
        if c["trademark_record_id"] == record["id"] and c["status"] == "ACTIVE":
            c["status"] = "REVOKED"
            touch(c)
    for g in db.coexistence_agreements.values():
        if (g["trademark_record_id"] == record["id"]
                and g["status"] in LIVE_AGREEMENT_STATES):
            g["status"] = "TERMINATED"
            touch(g)


def jeopardy_cascade(deadline):
    """Deadline -> MISSED (PRD 3.5): matter posture JEOPARDY (derived), sibling
    non-terminal deadlines flagged requires_partner_review, alert URGENT."""
    matter = db.enforcement_matters.get(deadline["enforcement_matter_id"])
    if matter is not None:
        touch(matter)  # posture derivation changed for this matter
        alert = db.watch_alerts.get(matter["watch_alert_id"])
        if alert is not None and alert["escalation_level"] != "URGENT":
            alert["escalation_level"] = "URGENT"
            touch(alert)
    for d in db.deadlines.values():
        if (d["enforcement_matter_id"] == deadline["enforcement_matter_id"]
                and d["id"] != deadline["id"]
                and d["status"] in OPEN_DEADLINE_STATES
                and not d["requires_partner_review"]):
            d["requires_partner_review"] = True
            touch(d)


def auto_docket_response_deadline(matter, letter, now):
    """Auto-docket a RESPONSE_DUE deadline anchored at letter issuance (PRD 3.6)."""
    offset = letter["response_due_days"]
    due = business_day_count(now, offset)
    d = {
        "enforcement_matter_id": matter["id"],
        "deadline_type": "RESPONSE_DUE",
        "statutory_basis": None,
        "basis_date": fmt_business(now),
        "offset_days": offset,
        "computation_variant": "BUSINESS_DAY_COUNT",
        "computed_due_at": fmt_business(due),
        "extension_count": 0,
        "max_extensions": 3,
        "docketed_by_user_id": "system",
        "verified_by_user_id": None,
        "satisfied_at": None,
        "satisfied_late": False,
        "requires_partner_review": False,
        "status": "DOCKETED",
    }
    stamp_new(d)
    db.deadlines[d["id"]] = d
    return d


def reissue_letter_cascade(letter, now):
    """Breach/reopen reissue: COMPLIED -> ISSUED; the 25000-cent reissue fee
    accrues with the affordability check bypassed (fees are derived)."""
    letter["status"] = "ISSUED"
    letter["reissue_count"] += 1
    letter["issued_at"] = fmt_business(now)
    letter["response_due_at"] = fmt_business(business_day_count(now, letter["response_due_days"]))
    touch(letter)


def reopen_matter(matter, now):
    """RESOLVED -> ACTIVE (PRD 3.4): outcome cleared; every COMPLIED letter
    reissued to ISSUED; each reissued letter gets a fresh auto-docketed
    RESPONSE_DUE deadline with docketed_by_user_id 'system'."""
    matter["status"] = "ACTIVE"
    matter["resolution_outcome"] = None
    touch(matter)
    for letter in db.cease_desist_letters.values():
        if letter["enforcement_matter_id"] == matter["id"] and letter["status"] == "COMPLIED":
            reissue_letter_cascade(letter, now)
            auto_docket_response_deadline(matter, letter, now)


def referral_threshold_cascade(alert):
    """Takedown FILED/APPEALED -> REMOVED on a COUNTERFEIT basis: when the
    confirmed count reaches >= 5, auto-create a DRAFT LAW_ENFORCEMENT referral
    exactly once (PRD 3.7)."""
    if confirmed_counterfeit_count(alert["id"]) >= 5 and not alert["referral_auto_created"]:
        alert["referral_auto_created"] = True
        matter = active_matter_of_alert(alert) if alert["status"] == "ESCALATED" else None
        referral = {
            "watch_alert_id": alert["id"],
            "enforcement_matter_id": matter["id"] if matter else None,
            "referral_channel": "LAW_ENFORCEMENT",
            "seizure_lines": [],
            "estimated_damages_cents": 0,
            "auto_created": True,
            "status": "DRAFT",
        }
        stamp_new(referral)
        db.counterfeit_referrals[referral["id"]] = referral
        touch(alert)


# ---------------------------------------------------------------------------
# Time-based sweep (PRD 2.5) — runs on every clock set
# ---------------------------------------------------------------------------

def run_sweep(now):
    # Deadlines: PENDING/EXTENDED -> MISSED when the clock passes computed_due_at.
    for d in list(db.deadlines.values()):
        if d["status"] in ("PENDING", "EXTENDED") and now > parse_dt(d["computed_due_at"]):
            d["status"] = "MISSED"
            touch(d)
            jeopardy_cascade(d)

    # Records: REGISTERED -> MAINTENANCE_DUE at window open (inclusive);
    # MAINTENANCE_DUE -> CANCELLED strictly past grace close without a filed
    # maintenance filing (SUBMITTED / LATE_FILED / ACCEPTED).
    for r in list(db.trademark_records.values()):
        if (r["status"] == "REGISTERED" and r["maintenance_window_open"]
                and now >= parse_dt(r["maintenance_window_open"])):
            r["status"] = "MAINTENANCE_DUE"
            touch(r)
        if (r["status"] == "MAINTENANCE_DUE" and r["maintenance_grace_close"]
                and now > parse_dt(r["maintenance_grace_close"])):
            has_filed = any(
                f["trademark_record_id"] == r["id"]
                and f["status"] in ("SUBMITTED", "LATE_FILED", "ACCEPTED")
                for f in db.maintenance_filings.values()
            )
            if not has_filed:
                r["status"] = "CANCELLED"
                touch(r)
                moot_cascade(r)

    # Agreements: EXECUTED -> MONITORING at effective_start (inclusive);
    # MONITORING -> EXPIRED at effective_end (inclusive);
    # CURE_PERIOD -> TERMINATED strictly past cure_deadline.
    for a in list(db.coexistence_agreements.values()):
        if a["status"] == "EXECUTED" and now >= parse_dt(a["effective_start"]):
            a["status"] = "MONITORING"
            touch(a)
        if a["status"] == "MONITORING" and now >= parse_dt(a["effective_end"]):
            a["status"] = "EXPIRED"
            touch(a)
        elif (a["status"] == "CURE_PERIOD" and a["cure_deadline"]
                and now > parse_dt(a["cure_deadline"])):
            a["status"] = "TERMINATED"
            touch(a)

    # Recordations: ACTIVE -> EXPIRED strictly past term_end.
    for c in list(db.customs_recordations.values()):
        if c["status"] == "ACTIVE" and now > parse_dt(c["term_end"]):
            c["status"] = "EXPIRED"
            touch(c)


def deadline_variant(deadline_type):
    """computation_variant is derived from deadline_type, never caller-supplied."""
    if deadline_type in ("OPPOSITION_WINDOW", "RENEWAL"):
        return "CALENDAR_ROLL_FORWARD"
    return "BUSINESS_DAY_COUNT"


def compute_due_at(variant, basis, offset_days):
    if variant == "CALENDAR_ROLL_FORWARD":
        return calendar_roll_forward(basis, offset_days)
    return business_day_count(basis, offset_days)


def evidence_staleness_cutoff(record):
    """specimen_date must be >= maintenance_window_close - 36 months."""
    return add_months(parse_dt(record["maintenance_window_close"]), -36)
