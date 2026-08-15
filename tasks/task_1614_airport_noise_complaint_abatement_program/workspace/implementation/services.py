"""Business logic: calculations, counters, cascades, and lazy sweeps."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, new_id
from util import now, round1, quarter_bounds, quarter_key_of

# ---------------------------------------------------------------------------
# generic helpers
# ---------------------------------------------------------------------------

OPEN_COMPLAINT_STATES = {
    "RECEIVED", "UNDER_REVIEW", "AWAITING_COMPLAINANT", "CORRELATED", "REOPENED",
}
CLOSED_COMPLAINT_STATES = {"CLOSED_SUBSTANTIATED", "CLOSED_UNSUBSTANTIATED"}
TERMINAL_COMPLAINT_STATES = CLOSED_COMPLAINT_STATES | {"WITHDRAWN"}

CLASSIFIED_FOR_CORRELATION = {"CLASSIFIED_AIRCRAFT", "CLASSIFIED_MIXED", "VERIFIED"}

NOTIFICATION_OPEN_STATES = {"SENT", "ACKNOWLEDGED", "RESPONSE_RECEIVED", "ESCALATED"}
NOTIFICATION_CLOSED_STATES = {"CLOSED", "AUTO_CLOSED"}

ACTIVE_APPLICATION_STATES = {
    "NEW", "SUBMITTED", "SCREENING", "ELIGIBLE_TIER1", "ELIGIBLE_TIER2", "APPEALED",
}

ACTIVE_OUTREACH_STATES = {"OPEN", "CONTACT_ATTEMPTED", "ENGAGED"}


def touch(entity):
    """Any modification refreshes updated_at and increments version by 1."""
    entity["updated_at"] = now()
    entity["version"] = entity.get("version", 0) + 1


# ---------------------------------------------------------------------------
# complainant counters / standing machine
# ---------------------------------------------------------------------------

def complaints_90d_count(complainant):
    t = now()
    window_start = t - timedelta(days=90)
    baseline = complainant.get("repeat_baseline_at")
    if baseline is not None and baseline > window_start:
        window_start = baseline
    n = 0
    for c in db.complaints.values():
        if c["complainant_id"] != complainant["id"]:
            continue
        if c["status"] == "WITHDRAWN":
            continue
        if window_start <= c["created_at"] <= t:
            n += 1
    return n


def _complainant_counts(complainant):
    cid = complainant["id"]
    filed = opened = closed = withdrawn = substantiated = 0
    for c in db.complaints.values():
        if c["complainant_id"] != cid:
            continue
        filed += 1
        if c["status"] in OPEN_COMPLAINT_STATES:
            opened += 1
        elif c["status"] in CLOSED_COMPLAINT_STATES:
            closed += 1
            if c["status"] == "CLOSED_SUBSTANTIATED":
                substantiated += 1
        elif c["status"] == "WITHDRAWN":
            withdrawn += 1
    return filed, opened, closed, withdrawn, substantiated


def _standing_for(count):
    if count >= 25:
        return "RESTRICTED"
    if count >= 10:
        return "REPEAT"
    return "GOOD_STANDING"


def _maybe_auto_outreach_case(complainant, trigger_reason):
    """Auto-create an OPEN outreach case iff no active case exists."""
    for case in db.outreach_cases.values():
        if (case["complainant_id"] == complainant["id"]
                and case["status"] in ACTIVE_OUTREACH_STATES):
            return None
    t = now()
    case = {
        "id": new_id(),
        "complainant_id": complainant["id"],
        "trigger_reason": trigger_reason,
        "status": "OPEN",
        "contact_attempts": 0,
        "opened_at": t,
        "resolved_at": None,
        "resolution_summary": None,
        "created_at": t,
        "updated_at": t,
        "version": 1,
    }
    db.outreach_cases[case["id"]] = case
    return case


def refresh_complainant(complainant):
    """Recompute counters + standing after a complaint lifecycle event or an
    outreach resolution. The recompute itself is a modification: version +1."""
    filed, opened, closed, withdrawn, substantiated = _complainant_counts(complainant)
    complainant["filed_total"] = filed
    complainant["open_count"] = opened
    complainant["closed_count"] = closed
    complainant["withdrawn_count"] = withdrawn
    complainant["substantiated_count"] = substantiated
    complainant["complaints_90d"] = complaints_90d_count(complainant)

    old = complainant["standing"]
    new = _standing_for(complainant["complaints_90d"])
    if new != old:
        complainant["standing"] = new
        complainant["low_priority_flag"] = (new == "RESTRICTED")
        # upward crossings auto-create outreach cases
        if old == "GOOD_STANDING" and new == "REPEAT":
            _maybe_auto_outreach_case(complainant, "REPEAT_THRESHOLD")
        elif new == "RESTRICTED" and old in ("GOOD_STANDING", "REPEAT"):
            _maybe_auto_outreach_case(complainant, "RESTRICTED_THRESHOLD")
    else:
        complainant["low_priority_flag"] = (new == "RESTRICTED")
    touch(complainant)


# ---------------------------------------------------------------------------
# correlation confidence (§3.4)
# ---------------------------------------------------------------------------

def _correlation_score(complaint, flight, event):
    """Return (score, variant) or (None, None) when no variant is eligible."""
    complainant = db.complainants.get(complaint["complainant_id"])
    zone_match = flight is not None and complainant is not None \
        and flight["zone_code"] == complainant["zone_code"]
    bonus_ok = event is not None and event["status"] in (
        "CLASSIFIED_AIRCRAFT", "VERIFIED")

    if flight is None:
        # event-only correlation
        score = 70.0 if (event is not None and event["status"] == "VERIFIED") else 55.0
        return round1(score), "RELAXED"

    dt = abs((complaint["occurred_at"] - flight["actual_at"]).total_seconds())
    d_dt = Decimal(str(dt))
    if dt <= 300:
        score = (Decimal(100) - Decimal(40) * d_dt / Decimal(300)
                 - (Decimal(0) if zone_match else Decimal(10))
                 + (Decimal(15) if bonus_ok else Decimal(0)))
        variant = "STRICT"
    elif dt <= 1200:
        score = (Decimal(85) - Decimal(55) * d_dt / Decimal(1200)
                 - (Decimal(0) if zone_match else Decimal(15))
                 + (Decimal(10) if bonus_ok else Decimal(0)))
        variant = "RELAXED"
    else:
        return None, None
    if score < 0:
        score = Decimal(0)
    if score > 100:
        score = Decimal(100)
    q = score.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(q), variant


def recompute_correlation(complaint):
    """Cascade B recompute: refresh confidence/eligibility from current
    flight/event evidence; bump the complaint version iff values changed."""
    flight = db.flights.get(complaint.get("correlated_flight_id") or "")
    event = db.events.get(complaint.get("correlated_event_id") or "")
    if flight is None and event is None:
        return
    score, variant = _correlation_score(complaint, flight, event)
    if score is None:
        return
    eligible = score >= 60.0
    if (complaint["correlation_confidence"] != score
            or complaint["substantiation_eligible"] != eligible
            or complaint["correlation_variant_used"] != variant):
        complaint["correlation_confidence"] = score
        complaint["substantiation_eligible"] = eligible
        complaint["correlation_variant_used"] = variant
        touch(complaint)


# ---------------------------------------------------------------------------
# curfew matching (§3.2)
# ---------------------------------------------------------------------------

def _season_covers(season, month):
    if season == "YEAR_ROUND":
        return True
    if season == "SUMMER":
        return 4 <= month <= 9
    # WINTER: months 10,11,12,1,2,3
    return month >= 10 or month <= 3


def _applies_to_covers(applies_to, operation_type):
    if applies_to == "BOTH":
        return True
    return applies_to == operation_type


def _matching_rules(flight):
    actual = flight["actual_at"]
    minute = actual.hour * 60 + actual.minute
    a_date = actual.date()
    out = []
    for r in db.curfew_rules.values():
        if r["status"] != "ACTIVE":
            continue
        if r["runway_code"] != flight["runway_code"]:
            continue
        if not _season_covers(r["season"], actual.month):
            continue
        if not _applies_to_covers(r["applies_to"], flight["operation_type"]):
            continue
        if not (r["effective_from"] <= a_date <= r["effective_to"]):
            continue
        if r["window_start_minute"] <= minute <= r["window_end_minute"]:
            out.append(r)
    return out


def compute_curfew_flags(flight):
    """Computed once when a flight becomes OPERATED; immutable afterwards."""
    operator = db.operators.get(flight["operator_id"])
    rules = _matching_rules(flight)
    movement = len(rules) > 0
    violation = False
    if movement and flight["exemption_code"] == "NONE":
        actual = flight["actual_at"]
        minute = actual.hour * 60 + actual.minute
        for r in rules:
            grace = min(r["grace_minutes"],
                        operator["curfew_grace_minutes"] if operator else 15)
            lo = r["window_start_minute"] + grace
            hi = r["window_end_minute"] - grace
            if lo <= minute <= hi:
                violation = True
                break
    return movement, violation


_CLASS_MULT = {"STAGE_3": Decimal("1.5"), "STAGE_4": Decimal("1.0"),
               "STAGE_5": Decimal("0.5")}


def compliance_score(operator, year, q):
    """Curfew compliance for one operator/quarter. The standing multiplier reads
    the operator's CURRENT stored standing (no feedback into this computation).
    Returns (movements, violations, score, implied_standing)."""
    start, end = quarter_bounds(year, q)
    movements = 0
    violations = 0
    points = Decimal(0)
    standing_mult = Decimal("1.25") if operator["compliance_standing"] == "PROBATION" \
        else Decimal("1.0")
    for f in db.flights.values():
        if f["operator_id"] != operator["id"] or f["status"] != "OPERATED":
            continue
        if f.get("actual_at") is None or not (start <= f["actual_at"] < end):
            continue
        if not f["curfew_movement"]:
            continue
        movements += 1
        if f["curfew_violation"]:
            violations += 1
            points += Decimal(100) * _CLASS_MULT[f["engine_class"]] * standing_mult
    score = Decimal(1000) - points
    if score < 0:
        score = Decimal(0)
    score = float(score.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    if score >= 900:
        band = "GOOD"
    elif score >= 700:
        band = "WATCH"
    else:
        band = "PROBATION"
    return movements, violations, score, band


# ---------------------------------------------------------------------------
# monitor uptime (§3.3)
# ---------------------------------------------------------------------------

def monitor_uptime(monitor_id):
    t = now()
    window_start = t - timedelta(days=30)
    overlap_seconds = Decimal(0)
    for o in db.outages.values():
        if o["monitor_id"] != monitor_id:
            continue
        lo = max(o["start_at"], window_start)
        hi = min(o["end_at"], t)
        if hi > lo:
            overlap_seconds += Decimal(str((hi - lo).total_seconds()))
    window_seconds = Decimal(43200 * 60)
    pct = (window_seconds - overlap_seconds) / window_seconds * Decimal(100)
    return float(pct.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def classification_confidence(event, flight_linked):
    """40 + 2*(lmax-65) + (20 if duration>=30) + (20 if flight linked), cap 100."""
    val = (Decimal(40)
           + (Decimal(str(event["lmax_db"])) - Decimal("65.0")) * 2
           + (Decimal(20) if event["duration_seconds"] >= 30 else Decimal(0))
           + (Decimal(20) if flight_linked else Decimal(0)))
    if val > 100:
        val = Decimal(100)
    return float(val.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# parcels / studies (§3.7)
# ---------------------------------------------------------------------------

def recompute_parcel(parcel, stamp_reassessed=False):
    """Dual-variant exposure recompute. Returns True if anything changed."""
    study = db.studies.get(parcel["study_id"])
    if study is not None and study["status"] == "ADOPTED":
        effective = round1(parcel["dnl_db_measured"])
    else:
        effective = round1(parcel["dnl_db_modeled"] - 1.5)
    band = int(math.floor(Decimal(str(effective)) / 5) * 5)
    lu = parcel["land_use"]
    if lu in ("RESIDENTIAL", "SCHOOL", "HOSPITAL"):
        if effective >= 65.0:
            compat = "INCOMPATIBLE_RESIDENTIAL"
        elif effective >= 60.0:
            compat = "COMPATIBLE_WITH_MEASURES"
        else:
            compat = "COMPATIBLE"
    elif lu in ("COMMERCIAL", "INDUSTRIAL"):
        compat = "INCOMPATIBLE_NONRES" if effective >= 75.0 else "COMPATIBLE"
    else:  # OPEN_SPACE
        compat = "COMPATIBLE"
    eligible = compat == "INCOMPATIBLE_RESIDENTIAL"
    changed = (parcel["dnl_db_effective"] != effective
               or parcel["dnl_band"] != band
               or parcel["compatibility_status"] != compat
               or parcel["insulation_eligible"] != eligible)
    parcel["dnl_db_effective"] = effective
    parcel["dnl_band"] = band
    parcel["compatibility_status"] = compat
    parcel["insulation_eligible"] = eligible
    if stamp_reassessed:
        parcel["reassessed_at"] = now()
        changed = True
    return changed


def priority_score(application):
    parcel = db.parcels.get(application["parcel_id"])
    score = 0
    if parcel is not None:
        band = parcel["dnl_band"]
        if band >= 75:
            score += 80
        elif band >= 70:
            score += 60
        elif band >= 65:
            score += 40
        lu = parcel["land_use"]
        if lu in ("SCHOOL", "HOSPITAL"):
            score += 20
        elif lu == "RESIDENTIAL":
            score += 10
    cid = application.get("complainant_id")
    if cid:
        complainant = db.complainants.get(cid)
        if complainant is not None and complainant["substantiated_count"] >= 5:
            score += 10
    if application["rooms_count"] >= 8:
        score += 5
    return score


# ---------------------------------------------------------------------------
# grants (§3.8)
# ---------------------------------------------------------------------------

TIER1_CAP = 8_000_000
TIER2_CAP = 4_000_000
ADMIN_CAP = 250_000


def obligation_split(cost_cents, tier):
    """Pinned rounding: each component rounded half-up to whole cents, then summed."""
    cost = Decimal(cost_cents)
    if tier == "ELIGIBLE_TIER1":
        structure = min(int(cost), TIER1_CAP)
    else:
        covered = int((cost * Decimal("0.80")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        structure = min(covered, TIER2_CAP)
    contingency = int((Decimal(structure) * Decimal("0.10")).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))
    admin = min(int((Decimal(structure) * Decimal("0.05")).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)), ADMIN_CAP)
    return structure, contingency, admin, structure + contingency + admin


def active_fund():
    for f in db.funds.values():
        if f["status"] == "ACTIVE":
            return f
    return None


def fund_available(fund):
    return fund["total_allocation_cents"] - fund["reserved_cents"] - fund["disbursed_cents"]


def projected_pipeline():
    """Sum of provisional obligations over UNFUNDED applications at either tier."""
    total = 0
    for a in db.applications.values():
        if a["funding_status"] != "UNFUNDED":
            continue
        if a["eligibility_status"] not in ("ELIGIBLE_TIER1", "ELIGIBLE_TIER2"):
            continue
        total += obligation_split(a["est_cost_cents"], a["eligibility_status"])[3]
    return total


def issue_offer(application, fund):
    """Shared by direct issue-offer and the waterfall. Returns offered amount."""
    _, _, _, obligation = obligation_split(
        application["est_cost_cents"], application["eligibility_status"])
    offered = min(obligation, fund_available(fund))
    fund["reserved_cents"] += offered
    touch(fund)
    t = now()
    application["funding_status"] = "OFFER_ISSUED"
    application["offered_amount_cents"] = offered
    application["fund_id"] = fund["id"]
    application["offer_issued_at"] = t
    application["offer_expires_at"] = t + timedelta(days=45)
    touch(application)
    return offered


def release_reservation(application):
    """Return an application's reservation to its fund's available bucket."""
    fund = db.funds.get(application.get("fund_id") or "")
    offered = application.get("offered_amount_cents") or 0
    if fund is not None and offered:
        fund["reserved_cents"] -= offered
        touch(fund)
    application["offered_amount_cents"] = None
    application["fund_id"] = None


def sweep_offer_expiry(application):
    """Lazy offer-expiry sweep, evaluated on READ of the application only."""
    if application["funding_status"] != "OFFER_ISSUED":
        return
    exp = application.get("offer_expires_at")
    if exp is None or now() < exp:
        return
    release_reservation(application)
    application["funding_status"] = "UNFUNDED"
    application["last_offer_expired_at"] = now()
    touch(application)


# ---------------------------------------------------------------------------
# notifications (§3.5)
# ---------------------------------------------------------------------------

def notification_overdue(n):
    return (n["status"] in ("SENT", "ACKNOWLEDGED")
            and n.get("due_at") is not None
            and now() > n["due_at"])


def escalate_notification(n, reason):
    """SENT|ACKNOWLEDGED -> ESCALATED with cascade C."""
    n["status"] = "ESCALATED"
    n["severity"] = "ESCALATION"
    n["escalation_reason"] = reason
    touch(n)
    operator = db.operators.get(n["operator_id"])
    if operator is not None:
        old = operator["compliance_standing"]
        new = {"GOOD": "WATCH", "WATCH": "PROBATION", "PROBATION": "PROBATION"}[old]
        changed = False
        if new != old:
            operator["compliance_standing"] = new
            changed = True
        if new == "PROBATION" and operator["curfew_grace_minutes"] != 0:
            operator["curfew_grace_minutes"] = 0
            changed = True
        if changed:
            touch(operator)


def sweep_notifications_globally():
    """Clock-advance sweep: every overdue SENT|ACKNOWLEDGED notification."""
    for n in list(db.notifications.values()):
        if notification_overdue(n):
            escalate_notification(n, "Response deadline exceeded (auto-escalated)")


def sweep_notification_on_read(n):
    if notification_overdue(n):
        escalate_notification(n, "Response deadline exceeded (auto-escalated)")


def on_time_responses_90d(operator_id):
    t = now()
    window_start = t - timedelta(days=90)
    count = 0
    for n in db.notifications.values():
        if n["operator_id"] != operator_id:
            continue
        if n["status"] != "CLOSED" or n["severity"] == "ESCALATION":
            continue
        closed_at = n.get("closed_at")
        due_at = n.get("due_at")
        if closed_at is None or due_at is None:
            continue
        if closed_at <= due_at and window_start <= closed_at <= t:
            count += 1
    return count


# ---------------------------------------------------------------------------
# quarterly rollup (§3.9) and annoyance index (§3.6)
# ---------------------------------------------------------------------------

def quarterly_rollup(year, q):
    start, end = quarter_bounds(year, q)
    received = 0
    substantiated = 0
    complainants = set()
    for c in db.complaints.values():
        if start <= c["created_at"] < end:
            received += 1
            complainants.add(c["complainant_id"])
        if (c["status"] == "CLOSED_SUBSTANTIATED" and c.get("closed_at") is not None
                and start <= c["closed_at"] < end):
            substantiated += 1
    events_aircraft = events_community = events_mixed = 0
    for e in db.events.values():
        if not (start <= e["started_at"] < end):
            continue
        if e["status"] in ("CLASSIFIED_AIRCRAFT", "VERIFIED"):
            events_aircraft += 1
        elif e["status"] == "CLASSIFIED_COMMUNITY":
            events_community += 1
        elif e["status"] == "CLASSIFIED_MIXED":
            events_mixed += 1
    movements = violations = 0
    operators_in_period = {}
    for f in db.flights.values():
        if f["status"] != "OPERATED" or f.get("actual_at") is None:
            continue
        if not (start <= f["actual_at"] < end):
            continue
        operators_in_period[f["operator_id"]] = True
        if f["curfew_movement"]:
            movements += 1
        if f["curfew_violation"]:
            violations += 1
    scores = []
    for op_id in operators_in_period:
        op = db.operators.get(op_id)
        if op is None:
            continue
        scores.append(Decimal(str(compliance_score(op, year, q)[2])))
    if scores:
        avg = sum(scores) / Decimal(len(scores))
        avg = float(avg.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    else:
        avg = 0.0
    return {
        "complaints_received_count": received,
        "complaints_substantiated_count": substantiated,
        "distinct_complainants_count": len(complainants),
        "events_aircraft_count": events_aircraft,
        "events_community_count": events_community,
        "events_mixed_count": events_mixed,
        "curfew_movements_count": movements,
        "curfew_violations_count": violations,
        "avg_operator_compliance_score": avg,
    }


def annoyance_index(zone_code):
    t = now()
    start30 = t - timedelta(days=30)
    start90 = t - timedelta(days=90)
    distinct = set()
    substantiated = 0
    for c in db.complaints.values():
        complainant = db.complainants.get(c["complainant_id"])
        if complainant is None or complainant["zone_code"] != zone_code:
            continue
        if start30 <= c["created_at"] <= t:
            distinct.add(c["complainant_id"])
        if (c["status"] == "CLOSED_SUBSTANTIATED" and c.get("closed_at") is not None
                and start90 <= c["closed_at"] <= t):
            substantiated += 1
    violations = 0
    for f in db.flights.values():
        if (f["status"] == "OPERATED" and f["curfew_violation"]
                and f["zone_code"] == zone_code and f.get("actual_at") is not None
                and start90 <= f["actual_at"] <= t):
            violations += 1
    base = (Decimal("2.5") * len(distinct)
            + Decimal(4) * Decimal(substantiated).sqrt()
            + Decimal("1.5") * violations)
    base = float(base.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    if base < 20:
        tier, bonus = "LOW", 0
    elif base < 40:
        tier, bonus = "MODERATE", 6
    else:
        tier, bonus = "HIGH", 15
    return {
        "zone_code": zone_code,
        "base_index": base,
        "tier": tier,
        "final_index": float(Decimal(str(base)) + Decimal(bonus)),
    }


def dnl_for_date(monitor_id, day):
    """Day-evening-night level for one UTC calendar date."""
    total_power = 0.0
    day_count = night_count = 0
    for e in db.events.values():
        if e["monitor_id"] != monitor_id:
            continue
        if e["status"] not in ("CLASSIFIED_AIRCRAFT", "CLASSIFIED_MIXED", "VERIFIED"):
            continue
        st = e["started_at"]
        if st.date() != day:
            continue
        if st.hour >= 22 or st.hour < 7:
            adjusted = e["sel_db"] + 10
            night_count += 1
        else:
            adjusted = e["sel_db"]
            day_count += 1
        total_power += 10 ** (adjusted / 10.0)
    if day_count + night_count == 0:
        dnl = 0.0
    else:
        dnl = round1(10.0 * math.log10(total_power / 86400.0))
    return {
        "date": day.isoformat(),
        "dnl_db": dnl,
        "day_event_count": day_count,
        "night_event_count": night_count,
    }
