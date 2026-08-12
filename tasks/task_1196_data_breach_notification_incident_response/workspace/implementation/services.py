"""Business logic: calculations, recomputes, cascading side effects."""
import math
from datetime import timedelta, date
from decimal import Decimal, ROUND_HALF_UP

import clock
from db import store

# --- constants ---
ELEMENT_WEIGHTS = {
    "SSN": 20,
    "DRIVER_LICENSE": 15,
    "PASSPORT": 15,
    "FINANCIAL_ACCOUNT": 18,
    "HEALTH_RECORD": 18,
    "BIOMETRIC": 20,
    "CREDENTIALS": 15,
    "DOB": 8,
    "NAME": 2,
    "EMAIL": 3,
    "PHONE": 3,
    "ADDRESS": 4,
}
CHANNEL_MULT = {
    "LAW_ENFORCEMENT": Decimal("1.2"),
    "THIRD_PARTY_REPORT": Decimal("1.1"),
}
US_FEDERAL_HOLIDAYS_2026 = {
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 5, 25),
    date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7), date(2026, 10, 12),
    date(2026, 11, 11), date(2026, 11, 26), date(2026, 12, 25),
}

PII_CATEGORIES = set(ELEMENT_WEIGHTS.keys())


def bump_incident(incident):
    """Increment version and refresh updated_at."""
    incident["version"] += 1
    incident["updated_at"] = clock.iso(clock.now())


def bump_row(row):
    row["version"] += 1
    row["updated_at"] = clock.iso(clock.now())


# --- risk scoring ---
def _latest_risk_scope(incident_id):
    """Latest (by updated_at) ForensicScope with status in {BASELINED, AMENDED, FINAL}."""
    candidates = [
        s for s in store.forensic_scopes.values()
        if s["incident_id"] == incident_id and s["status"] in ("BASELINED", "AMENDED", "FINAL")
    ]
    if not candidates:
        return None
    # updated_at strings in ISO are lexicographically comparable
    candidates.sort(key=lambda s: (s["updated_at"], s["created_at"], s["id"]))
    return candidates[-1]


def _non_excluded_subjects(incident_id):
    return [
        s for s in store.affected_subjects.values()
        if s["incident_id"] == incident_id and s["status"] != "EXCLUDED"
    ]


def recompute_risk_scores(incident):
    scope = _latest_risk_scope(incident["id"])
    subjects = _non_excluded_subjects(incident["id"])
    total_affected = len(subjects)
    if scope is None:
        incident["risk_score_conservative"] = 0
        incident["risk_score_likelihood_adjusted"] = 0
        _update_severity(incident)
        return
    element_sum = sum(ELEMENT_WEIGHTS.get(e, 0) for e in scope["data_elements_at_risk"])
    mult = CHANNEL_MULT.get(incident["source_channel"], Decimal("1.0"))
    volume_bonus = min(20, total_affected // 500)
    base = Decimal(element_sum) * mult + Decimal(volume_bonus)
    conservative = min(100, int(base.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
    pct = Decimal(scope["exfiltration_likelihood_pct"])
    adjusted = min(100, int((base * pct / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
    incident["risk_score_conservative"] = conservative
    incident["risk_score_likelihood_adjusted"] = adjusted
    _update_severity(incident)


def _update_severity(incident):
    s = incident["risk_score_conservative"]
    if incident["risk_score_conservative"] == 0 and _latest_risk_scope(incident["id"]) is None:
        incident["severity"] = "UNCLASSIFIED"
        return
    if s < 25:
        incident["severity"] = "LOW"
    elif s < 50:
        incident["severity"] = "MODERATE"
    elif s < 75:
        incident["severity"] = "HIGH"
    else:
        incident["severity"] = "CRITICAL"


# --- derived counters ---
def recompute_incident_counters(incident):
    iid = incident["id"]
    subs = [s for s in store.affected_subjects.values() if s["incident_id"] == iid]
    # Affected = all non-EXCLUDED subjects (IDENTIFIED, VERIFIED, NOTICE_QUEUED, NOTIFIED).
    # This matches the risk-calc input_set and makes the DISPATCHING->COMPLETED
    # condition (total_affected == total_notified when pending == 0) reachable.
    incident["total_affected_subjects"] = sum(1 for s in subs if s["status"] != "EXCLUDED")
    incident["total_notified_subjects"] = sum(1 for s in subs if s["status"] == "NOTIFIED")
    incident["total_pending_subjects"] = sum(
        1 for s in subs if s["status"] in ("IDENTIFIED", "VERIFIED", "NOTICE_QUEUED")
    )
    incident["credit_monitoring_offered"] = sum(
        1 for s in subs if s["credit_monitoring_status"] != "NOT_OFFERED"
    )
    incident["credit_monitoring_enrolled"] = sum(
        1 for s in subs if s["credit_monitoring_status"] == "ENROLLED"
    )
    incident["credit_monitoring_declined"] = sum(
        1 for s in subs if s["credit_monitoring_status"] == "DECLINED"
    )
    recompute_jurisdiction_counters(incident)


def recompute_jurisdiction_counters(incident):
    iid = incident["id"]
    subs = [s for s in store.affected_subjects.values() if s["incident_id"] == iid]
    countable = [s for s in subs if s["status"] in ("IDENTIFIED", "VERIFIED", "NOTICE_QUEUED", "NOTIFIED")]
    for je in store.jurisdiction_evaluations.values():
        if je["incident_id"] != iid:
            continue
        n = sum(1 for s in countable if s["residence_state_code"] == je["state_code"])
        je["subjects_in_jurisdiction"] = n
        je["notification_required"] = n >= je["record_count_threshold"]
        je["updated_at"] = clock.iso(clock.now())
    _update_notification_status_from_matrix(incident)


def _update_notification_status_from_matrix(incident):
    if incident["notification_status"] != "EVALUATING":
        return
    jes = [j for j in store.jurisdiction_evaluations.values() if j["incident_id"] == incident["id"]]
    if any(j["notification_required"] for j in jes):
        incident["notification_status"] = "REQUIRED"
    elif jes and all(not j["notification_required"] for j in jes):
        incident["notification_status"] = "NOT_REQUIRED"


# --- notification deadline ---
def compute_deadline(determination_at, deadline_days, deadline_kind):
    """Returns aware UTC datetime pinned at 23:59:59.999 of the final day."""
    det_date = determination_at.date()
    if deadline_kind == "CALENDAR_DAYS":
        final = det_date + timedelta(days=deadline_days)
    else:  # BUSINESS_DAYS
        counted = 0
        cur = det_date
        while counted < deadline_days:
            cur = cur + timedelta(days=1)
            if cur.weekday() < 5 and cur not in US_FEDERAL_HOLIDAYS_2026:
                counted += 1
        final = cur
    from datetime import datetime, timezone, time
    eod = datetime.combine(final, time(23, 59, 59, 999000, tzinfo=timezone.utc))
    return eod


# --- call center seats ---
def compute_seats(pending_subjects, severity, languages_supported):
    P = pending_subjects
    if P < 100:
        seats = 2
    elif P < 1000:
        seats = 2 + math.ceil((P - 100) / 50)
    elif P < 10000:
        seats = 20 + math.ceil((P - 1000) / 250)
    else:
        seats = 56 + math.ceil((P - 10000) / 1000)
    if severity == "CRITICAL":
        seats = int((Decimal(seats) * Decimal("1.5")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if languages_supported and len(languages_supported) > 1:
        seats += 2
    return seats


def recompute_active_plan_seats(incident):
    """Recompute seats_required on the currently ACTIVE CallCenterStaffingPlan."""
    plans = [
        p for p in store.call_center_plans.values()
        if p["incident_id"] == incident["id"] and p["status"] == "ACTIVE"
    ]
    for p in plans:
        p["seats_required"] = compute_seats(
            incident["total_pending_subjects"], incident["severity"], p["languages_supported"]
        )
        bump_row(p)


# --- credit monitoring cost ---
def credit_monitoring_cost(incident_id):
    """Returns (total_cents, offer_count)."""
    offers = [o for o in store.credit_monitoring_offers.values() if o["incident_id"] == incident_id]
    total = 0
    for o in offers:
        base = o["term_months"] * o["unit_cost_cents"]
        status = o["status"]
        if status == "REDEEMED":
            cost = base
        elif status in ("DECLINED", "EXPIRED"):
            cost = 0
        elif status == "CANCELLED":
            issued_at = clock.parse_iso(o["created_at"])
            cancelled_at = clock.parse_iso(o.get("cancelled_at") or o["updated_at"])
            days = max(0, (cancelled_at.date() - issued_at.date()).days)
            denom = o["term_months"] * 30
            factor = Decimal(days) / Decimal(denom) if denom else Decimal(0)
            cost = int((Decimal(base) * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        else:  # ISSUED
            cost = int((Decimal(base) * Decimal("0.10")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        total += cost
    return total, len(offers)


# --- custody overlap ---
def intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap. None end means infinity."""
    a_end_val = a_end if a_end is not None else clock.datetime_max()
    b_end_val = b_end if b_end is not None else clock.datetime_max()
    return a_start < b_end_val and b_start < a_end_val


def custody_has_overlap(evidence_item_id, start_at, end_at, exclude_id=None):
    for log in store.custody_logs.values():
        if log["evidence_item_id"] != evidence_item_id:
            continue
        if exclude_id and log["id"] == exclude_id:
            continue
        l_start = clock.parse_iso(log["start_at"])
        l_end = clock.parse_iso(log["end_at"]) if log.get("end_at") else None
        if intervals_overlap(start_at, end_at, l_start, l_end):
            return True
    return False
