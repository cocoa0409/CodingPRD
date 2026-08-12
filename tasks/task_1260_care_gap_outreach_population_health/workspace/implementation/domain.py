"""Business logic: registry clock, calculations, cascades, serializers."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
from util import fmt_dt

# ---------------------------------------------------------------------------
# Constants (pinned by the PRD / scaffold)
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

RISK_TIER_WEIGHT = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
MEASURE_DOMAIN_WEIGHT = {"SCREENING": 1, "MED_ADHERENCE": 2}
NO_SHOW_STRIKE_BONUS = 8
REOPEN_BONUS = 12

WORKLOAD_TARGET = 250
PER_GAP_BASE_CENTS = 4500
QUALITY_BONUS_CENTS = 50000
QUALITY_THRESHOLD_BPS = 7000

OPEN_STATUSES = {"OPEN", "OUTREACH_IN_PROGRESS", "AWAITING_APPOINTMENT", "PENDING_EVIDENCE"}
EXPIRABLE_STATUSES = OPEN_STATUSES | {"REOPENED"}


# ---------------------------------------------------------------------------
# Entity bookkeeping
# ---------------------------------------------------------------------------

def stamp_new(entity, now):
    entity["id"] = db.new_id()
    entity["_seq"] = db.next_seq()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    return entity


def bump(entity, now):
    """Every mutation increments version and refreshes updated_at."""
    entity["updated_at"] = now
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Registry resolution helpers
# ---------------------------------------------------------------------------

def registry_of_gap(gap):
    panel = db.panels.get(gap["panel_id"])
    return db.registries.get(panel["registry_id"]) if panel else None


def registry_of_member(member):
    return db.registries.get(member["registry_id"])


def registry_of_appointment(appt):
    gap = db.care_gaps.get(appt["care_gap_id"])
    return registry_of_gap(gap) if gap else None


def registry_of_transport(t):
    appt = db.appointments.get(t["appointment_id"])
    return registry_of_appointment(appt) if appt else None


def registry_of_evidence(ev):
    gap = db.care_gaps.get(ev["care_gap_id"])
    return registry_of_gap(gap) if gap else None


def registry_of_exclusion(ex):
    member = db.members.get(ex["member_id"])
    return registry_of_member(member) if member else None


def registry_of_campaign(c):
    return db.registries.get(c["registry_id"])


def registry_of_workload(w):
    return db.registries.get(w["registry_id"])


def registry_of_payout(p):
    w = db.workloads.get(p["workload_id"])
    return registry_of_workload(w) if w else None


def registry_of_report(r):
    return db.registries.get(r["registry_id"])


def clock_of(registry):
    return registry["current_business_date"]


def current_period_key(now):
    return f"{now.year:04d}-{now.month:02d}"


# ---------------------------------------------------------------------------
# calculations.priority_score
# ---------------------------------------------------------------------------

def days_overdue(gap, now):
    delta = now - gap["due_date"]
    days = int(delta.total_seconds() // 86400)
    return max(0, days)


def priority_band_for(score):
    if score >= 80:
        return "P1_URGENT"
    if score >= 60:
        return "P2_HIGH"
    if score >= 30:
        return "P3_ROUTINE"
    return "P4_LOW"


def recompute_gap_priority(gap):
    """EXCLUDED and EXPIRED rows keep their last computed score."""
    if gap["status"] in ("EXCLUDED", "EXPIRED"):
        return
    reg = registry_of_gap(gap)
    now = clock_of(reg)
    member = db.members[gap["member_id"]]
    measure = db.measures[gap["measure_id"]]

    base = min(days_overdue(gap, now), 90)
    tier_term = (
        RISK_TIER_WEIGHT[member["risk_tier"]]
        * MEASURE_DOMAIN_WEIGHT[measure["measure_domain"]]
        * 5
    )
    attempt_decay = max(0, 20 - 4 * gap["attempt_count"])
    strikes = sum(
        1
        for a in db.appointments.values()
        if a["care_gap_id"] == gap["id"] and a["status"] == "NO_SHOW"
    )
    strike_bonus = strikes * NO_SHOW_STRIKE_BONUS
    reopen_bonus = REOPEN_BONUS if gap.get("_was_reopened") else 0
    raw = base + tier_term + attempt_decay + strike_bonus + reopen_bonus
    score = max(0, min(100, raw))  # all terms integral; floor after clamp is a no-op
    gap["priority_score"] = int(score)
    gap["priority_band"] = priority_band_for(gap["priority_score"])


# ---------------------------------------------------------------------------
# calculations.attempt_cadence
# ---------------------------------------------------------------------------

def compute_next_eligible_attempt_at(gap, campaign, now):
    cooldown = timedelta(hours=campaign["min_attempt_interval_hours"])
    candidate = now + cooldown
    qs = campaign["quiet_hours_start_min"]
    qe = campaign["quiet_hours_end_min"]
    mins = candidate.hour * 60 + candidate.minute
    if mins >= qs:
        nxt_day = (candidate + timedelta(days=1)).date()
        candidate = datetime(
            nxt_day.year, nxt_day.month, nxt_day.day, tzinfo=timezone.utc
        ) + timedelta(minutes=qe)
    elif mins < qe:
        d = candidate.date()
        candidate = datetime(
            d.year, d.month, d.day, tzinfo=timezone.utc
        ) + timedelta(minutes=qe)
    result = max(candidate, campaign["starts_at"])
    return result.replace(microsecond=0)


# ---------------------------------------------------------------------------
# Cohort matching / panel materialization
# ---------------------------------------------------------------------------

def age_years(dob, at):
    return at.year - dob.year - ((at.month, at.day) < (dob.month, dob.day))


def member_matches_cohort(member, cohort, now):
    a = age_years(member["date_of_birth"], now)
    if a < cohort["min_age"] or a > cohort["max_age"]:
        return False
    if cohort["risk_tier_filter"] != "ANY" and member["risk_tier"] != cohort["risk_tier_filter"]:
        return False
    if cohort["requires_active_enrollment"] and member["enrollment_status"] != "ENROLLED":
        return False
    return True


def create_gap(panel, member, measure, now):
    gap = {
        "panel_id": panel["id"],
        "member_id": member["id"],
        "measure_id": measure["id"],
        "last_qualifying_event_at": None,
        # No qualifying event -> due_date falls back to the member's enrollment date.
        "due_date": member["created_at"],
        "attempt_count": 0,
        "next_eligible_attempt_at": None,
        "status": "OPEN",
        "closure_source": None,
        "_was_reopened": False,
        "_last_closed_at": None,
    }
    stamp_new(gap, now)
    recompute_gap_priority(gap)
    db.care_gaps[gap["id"]] = gap
    member["open_gap_count"] += 1
    bump(member, now)
    return gap


def materialize_panel_gaps(panel, now):
    """Create gaps for cohort-matching members lacking one under this panel;
    existing gaps are left untouched. member_count is the cardinality of
    members currently satisfying the cohort criteria."""
    cohort = db.cohorts[panel["cohort_id"]]
    measure = db.measures[panel["measure_id"]]
    count = 0
    for member in db.members.values():
        if member["registry_id"] != panel["registry_id"]:
            continue
        if not member_matches_cohort(member, cohort, now):
            continue
        count += 1
        has_gap = any(
            g["panel_id"] == panel["id"] and g["member_id"] == member["id"]
            for g in db.care_gaps.values()
        )
        if not has_gap:
            create_gap(panel, member, measure, now)
    panel["member_count"] = count


# ---------------------------------------------------------------------------
# Exclusion coverage
# ---------------------------------------------------------------------------

def exclusion_covers_measure(exclusion, measure_id):
    return exclusion["measure_id"] is None or exclusion["measure_id"] == measure_id


def exclusion_in_force_at(exclusion, now):
    """An APPROVED exclusion suppresses while now in [effective_from, effective_until)."""
    if exclusion["status"] != "APPROVED":
        return False
    if now < exclusion["effective_from"]:
        return False
    if exclusion["effective_until"] is not None and now >= exclusion["effective_until"]:
        return False
    return True


def member_excluded_for_measure(member_id, measure_id, now):
    return any(
        e["member_id"] == member_id
        and exclusion_covers_measure(e, measure_id)
        and exclusion_in_force_at(e, now)
        for e in db.exclusions.values()
    )


# ---------------------------------------------------------------------------
# calculations.gap_closure_rate / measure_performance_numerator_denominator
# ---------------------------------------------------------------------------

def period_window(period_key):
    year, month = (int(p) for p in period_key.split("-"))
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def _exclusion_counts_for_denominator(exclusion, measure_id, pstart, pend, variant, freeze_at):
    if not exclusion_covers_measure(exclusion, measure_id):
        return False
    ef = exclusion["effective_from"]
    eu = exclusion["effective_until"]
    if not (ef < pend and (eu is None or eu > pstart)):
        return False
    if variant == "PROVISIONAL":
        # Live exclusion list.
        return exclusion["status"] == "APPROVED"
    # FINAL: freeze the set of exclusions approved as of period_end + lag.
    approved_at = exclusion.get("_approved_at")
    if approved_at is None or approved_at > freeze_at:
        return False
    if exclusion["status"] == "APPROVED":
        return True
    if exclusion["status"] == "REVOKED" and exclusion.get("_revoked_at") is not None:
        return exclusion["_revoked_at"] > freeze_at
    return False


def compute_report_counts(report, variant):
    measure = db.measures[report["measure_id"]]
    registry = db.registries[report["registry_id"]]
    now = clock_of(registry)
    pstart, pend = period_window(report["period_key"])
    freeze_at = pend + timedelta(days=measure["reporting_lag_days"])

    cohorts = [
        db.cohorts[p["cohort_id"]]
        for p in db.panels.values()
        if p["registry_id"] == registry["id"] and p["measure_id"] == measure["id"]
    ]

    denominator_members = []
    if cohorts:
        for member in db.members.values():
            if member["registry_id"] != registry["id"]:
                continue
            if member["enrollment_status"] != "ENROLLED":
                continue
            if not any(member_matches_cohort(member, c, now) for c in cohorts):
                continue
            excluded = any(
                e["member_id"] == member["id"]
                and _exclusion_counts_for_denominator(
                    e, measure["id"], pstart, pend, variant, freeze_at
                )
                for e in db.exclusions.values()
            )
            if excluded:
                continue
            denominator_members.append(member)

    denominator = len(denominator_members)
    denominator_ids = {m["id"] for m in denominator_members}

    numerator_members = set()
    for gap in db.care_gaps.values():
        if gap["measure_id"] != measure["id"]:
            continue
        if gap["member_id"] not in denominator_ids:
            continue
        closed_at = gap.get("_last_closed_at")
        if closed_at is None or not (pstart <= closed_at < pend):
            continue
        if variant == "PROVISIONAL":
            # Includes CLAIMS_FEED closures not yet reconciliation-checked
            # (reopened rows have left CLOSED and no longer count).
            if gap["status"] != "CLOSED":
                continue
        else:
            # FINAL: claims-feed closures later reopened are excluded.
            if gap["status"] in ("REOPENED", "OPEN"):
                continue
        numerator_members.add(gap["member_id"])

    numerator = len(numerator_members)
    if denominator == 0:
        rate = None
    else:
        rate = int(
            (Decimal(numerator * 10000) / Decimal(denominator)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    return denominator, numerator, rate


def recompute_report(report, variant=None):
    variant = variant or report["variant"]
    d, n, rate = compute_report_counts(report, variant)
    report["denominator_count"] = d
    report["numerator_count"] = n
    report["closure_rate_bps"] = rate


def recompute_provisional_reports(registry_id, measure_ids=None):
    for r in db.reports.values():
        if r["registry_id"] != registry_id or r["variant"] != "PROVISIONAL":
            continue
        if measure_ids is not None and r["measure_id"] not in measure_ids:
            continue
        recompute_report(r, "PROVISIONAL")
        reg = registry_of_report(r)
        bump(r, clock_of(reg))


# ---------------------------------------------------------------------------
# calculations.workload_utilization
# ---------------------------------------------------------------------------

def _utilization_decimal(assigned_member_count):
    return (Decimal(assigned_member_count) / Decimal(WORKLOAD_TARGET)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def refresh_workload_assignment(workload, now):
    total = sum(
        p["member_count"]
        for p in db.panels.values()
        if p["registry_id"] == workload["registry_id"]
        and p["panel_manager_id"] == workload["panel_manager_id"]
        and p["status"] == "ACTIVE"
    )
    workload["assigned_member_count"] = total
    workload["utilization_ratio"] = float(_utilization_decimal(total))
    bump(workload, now)


def refresh_workloads_for_manager(registry_id, panel_manager_id, now):
    for w in db.workloads.values():
        if w["registry_id"] == registry_id and w["panel_manager_id"] == panel_manager_id:
            refresh_workload_assignment(w, now)


# ---------------------------------------------------------------------------
# calculations.panel_manager_incentive_payout
# ---------------------------------------------------------------------------

def compute_payout_amounts(workload):
    util = _utilization_decimal(workload["assigned_member_count"])
    if util < Decimal("0.80"):
        mult = 10000
    elif util < Decimal("1.00"):
        mult = 12000
    else:
        mult = 15000
    # Pinned rounding order: round the per-gap line first, then multiply.
    per_gap_line = int(
        (Decimal(PER_GAP_BASE_CENTS) * Decimal(mult) / Decimal(10000)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    base = per_gap_line * workload["closed_gap_count_period"]
    bonus = 0
    for r in db.reports.values():
        if (
            r["registry_id"] == workload["registry_id"]
            and r["period_key"] == workload["period_key"]
            and r["variant"] == "PROVISIONAL"
            and r["closure_rate_bps"] is not None
            and r["closure_rate_bps"] >= QUALITY_THRESHOLD_BPS
        ):
            bonus = QUALITY_BONUS_CENTS
            break
    return {
        "base_amount_cents": base,
        "tier_multiplier_bps": mult,
        "quality_bonus_cents": bonus,
        "total_payout_cents": base + bonus,
    }


def recompute_projected_payouts(registry_id, panel_manager_id, period_key, now):
    for w in db.workloads.values():
        if (
            w["registry_id"] == registry_id
            and w["panel_manager_id"] == panel_manager_id
            and w["period_key"] == period_key
        ):
            for p in db.payouts.values():
                if p["workload_id"] == w["id"] and p["status"] == "PROJECTED":
                    p.update(compute_payout_amounts(w))
                    bump(p, now)


# ---------------------------------------------------------------------------
# Care-gap closure / reopen cascades
# ---------------------------------------------------------------------------

def gap_closed_cascade(gap, now):
    """Gap has just transitioned to CLOSED."""
    member = db.members[gap["member_id"]]
    member["open_gap_count"] = max(0, member["open_gap_count"] - 1)
    bump(member, now)
    panel = db.panels[gap["panel_id"]]
    registry_id = panel["registry_id"]
    pm_id = panel["panel_manager_id"]
    period_key = current_period_key(now)
    for w in db.workloads.values():
        if (
            w["registry_id"] == registry_id
            and w["panel_manager_id"] == pm_id
            and w["period_key"] == period_key
        ):
            w["closed_gap_count_period"] += 1
            bump(w, now)
    recompute_projected_payouts(registry_id, pm_id, period_key, now)
    recompute_provisional_reports(registry_id, {gap["measure_id"]})


def gap_reopened_cascade(gap, now):
    """Gap has just transitioned CLOSED -> REOPENED."""
    member = db.members[gap["member_id"]]
    member["open_gap_count"] += 1
    bump(member, now)
    panel = db.panels[gap["panel_id"]]
    registry_id = panel["registry_id"]
    pm_id = panel["panel_manager_id"]
    period_key = current_period_key(now)
    for w in db.workloads.values():
        if (
            w["registry_id"] == registry_id
            and w["panel_manager_id"] == pm_id
            and w["period_key"] == period_key
        ):
            w["closed_gap_count_period"] -= 1
            bump(w, now)
    recompute_projected_payouts(registry_id, pm_id, period_key, now)
    recompute_provisional_reports(registry_id, {gap["measure_id"]})


def cancel_active_appointments_for_gap(gap, now):
    for a in db.appointments.values():
        if a["care_gap_id"] == gap["id"] and a["status"] in ("SCHEDULED", "CONFIRMED"):
            a["status"] = "CANCELLED"
            bump(a, now)
            cancel_open_transports(a["id"], now)


def cancel_open_transports(appointment_id, now):
    for t in db.transports.values():
        if t["appointment_id"] == appointment_id and t["status"] in ("REQUESTED", "ARRANGED"):
            t["status"] = "CANCELLED"
            bump(t, now)


# ---------------------------------------------------------------------------
# Registry logical clock sweeps
# ---------------------------------------------------------------------------

def run_clock_sweeps(registry):
    now = clock_of(registry)
    rid = registry["id"]

    # Campaign auto-launch at starts_at (requires the linked panel ACTIVE).
    for c in db.campaigns.values():
        if c["registry_id"] != rid or c["status"] != "SCHEDULED":
            continue
        if now >= c["starts_at"]:
            panel = db.panels.get(c["panel_id"])
            if panel is not None and panel["status"] == "ACTIVE":
                c["status"] = "ACTIVE"
                bump(c, now)

    # Campaign auto-complete once the clock crosses ends_at.
    for c in db.campaigns.values():
        if c["registry_id"] != rid:
            continue
        if c["status"] in ("ACTIVE", "PAUSED") and now >= c["ends_at"]:
            c["status"] = "COMPLETED"
            bump(c, now)

    # Gap expiry once the reconciliation window has lapsed.
    for g in db.care_gaps.values():
        panel = db.panels.get(g["panel_id"])
        if panel is None or panel["registry_id"] != rid:
            continue
        if g["status"] not in EXPIRABLE_STATUSES:
            continue
        measure = db.measures[g["measure_id"]]
        if now >= g["due_date"] + timedelta(days=measure["reporting_lag_days"]):
            g["status"] = "EXPIRED"
            bump(g, now)
            member = db.members[g["member_id"]]
            member["open_gap_count"] = max(0, member["open_gap_count"] - 1)
            bump(member, now)

    # Reopened gaps re-triage back into the open pool once eligible.
    for g in db.care_gaps.values():
        panel = db.panels.get(g["panel_id"])
        if panel is None or panel["registry_id"] != rid:
            continue
        if g["status"] != "REOPENED":
            continue
        nea = g["next_eligible_attempt_at"]
        if nea is None or now >= nea:
            g["status"] = "OPEN"
            recompute_gap_priority(g)
            bump(g, now)


# ---------------------------------------------------------------------------
# Serializers (internal "_"-prefixed fields never leak)
# ---------------------------------------------------------------------------

def ser_registry(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "description": r.get("description"),
        "program_year": r["program_year"],
        "current_business_date": fmt_dt(r["current_business_date"]),
        "status": r["status"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def ser_measure(m):
    return {
        "id": m["id"],
        "registry_id": m["registry_id"],
        "measure_code": m["measure_code"],
        "measure_domain": m["measure_domain"],
        "lookback_days": m["lookback_days"],
        "exclusion_window_days": m["exclusion_window_days"],
        "reporting_lag_days": m["reporting_lag_days"],
        "status": m["status"],
        "created_at": fmt_dt(m["created_at"]),
        "updated_at": fmt_dt(m["updated_at"]),
        "version": m["version"],
    }


def ser_cohort(c):
    return {
        "id": c["id"],
        "registry_id": c["registry_id"],
        "cohort_code": c["cohort_code"],
        "min_age": c["min_age"],
        "max_age": c["max_age"],
        "risk_tier_filter": c["risk_tier_filter"],
        "requires_active_enrollment": c["requires_active_enrollment"],
        "status": c["status"],
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def ser_member(m):
    return {
        "id": m["id"],
        "registry_id": m["registry_id"],
        "mrn": m["mrn"],
        "date_of_birth": fmt_dt(m["date_of_birth"]),
        "risk_tier": m["risk_tier"],
        "phone_ok": m["phone_ok"],
        "mail_ok": m["mail_ok"],
        "enrollment_status": m["enrollment_status"],
        "open_gap_count": m["open_gap_count"],
        "created_at": fmt_dt(m["created_at"]),
        "updated_at": fmt_dt(m["updated_at"]),
        "version": m["version"],
    }


def ser_panel(p):
    return {
        "id": p["id"],
        "registry_id": p["registry_id"],
        "cohort_id": p["cohort_id"],
        "measure_id": p["measure_id"],
        "panel_manager_id": p["panel_manager_id"],
        "member_count": p["member_count"],
        "status": p["status"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def ser_gap(g):
    reg = registry_of_gap(g)
    now = clock_of(reg)
    return {
        "id": g["id"],
        "panel_id": g["panel_id"],
        "member_id": g["member_id"],
        "measure_id": g["measure_id"],
        "last_qualifying_event_at": fmt_dt(g["last_qualifying_event_at"]),
        "due_date": fmt_dt(g["due_date"]),
        "days_overdue": days_overdue(g, now),
        "priority_score": g["priority_score"],
        "priority_band": g["priority_band"],
        "attempt_count": g["attempt_count"],
        "next_eligible_attempt_at": fmt_dt(g["next_eligible_attempt_at"]),
        "status": g["status"],
        "closure_source": g["closure_source"],
        "created_at": fmt_dt(g["created_at"]),
        "updated_at": fmt_dt(g["updated_at"]),
        "version": g["version"],
    }


def ser_campaign(c):
    return {
        "id": c["id"],
        "registry_id": c["registry_id"],
        "panel_id": c["panel_id"],
        "measure_id": c["measure_id"],
        "name": c["name"],
        "channel": c["channel"],
        "quiet_hours_start_min": c["quiet_hours_start_min"],
        "quiet_hours_end_min": c["quiet_hours_end_min"],
        "min_attempt_interval_hours": c["min_attempt_interval_hours"],
        "max_attempts_per_member": c["max_attempts_per_member"],
        "starts_at": fmt_dt(c["starts_at"]),
        "ends_at": fmt_dt(c["ends_at"]),
        "status": c["status"],
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def ser_attempt(a):
    # Append-only ledger entry: no updated_at, no version.
    return {
        "id": a["id"],
        "care_gap_id": a["care_gap_id"],
        "campaign_id": a["campaign_id"],
        "member_id": a["member_id"],
        "channel": a["channel"],
        "attempted_at": fmt_dt(a["attempted_at"]),
        "outcome": a["outcome"],
        "notes": a.get("notes"),
        "reversal_reason": a.get("reversal_reason"),
        "created_at": fmt_dt(a["created_at"]),
    }


def ser_appointment(a):
    return {
        "id": a["id"],
        "care_gap_id": a["care_gap_id"],
        "member_id": a["member_id"],
        "provider_id": a["provider_id"],
        "slot_start_at": fmt_dt(a["slot_start_at"]),
        "slot_end_at": fmt_dt(a["slot_end_at"]),
        "provider_capacity_per_slot": a["provider_capacity_per_slot"],
        "status": a["status"],
        "created_at": fmt_dt(a["created_at"]),
        "updated_at": fmt_dt(a["updated_at"]),
        "version": a["version"],
    }


def ser_transport(t):
    return {
        "id": t["id"],
        "appointment_id": t["appointment_id"],
        "member_id": t["member_id"],
        "vendor": t["vendor"],
        "pickup_at": fmt_dt(t["pickup_at"]),
        "cost_cents": t["cost_cents"],
        "status": t["status"],
        "created_at": fmt_dt(t["created_at"]),
        "updated_at": fmt_dt(t["updated_at"]),
        "version": t["version"],
    }


def ser_evidence(e):
    return {
        "id": e["id"],
        "care_gap_id": e["care_gap_id"],
        "member_id": e["member_id"],
        "evidence_type": e["evidence_type"],
        "service_date": fmt_dt(e["service_date"]),
        "document_uri": e["document_uri"],
        "submitted_by_role": e["submitted_by_role"],
        "status": e["status"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_exclusion(x):
    return {
        "id": x["id"],
        "member_id": x["member_id"],
        "measure_id": x["measure_id"],
        "exclusion_kind": x["exclusion_kind"],
        "justification": x["justification"],
        "effective_from": fmt_dt(x["effective_from"]),
        "effective_until": fmt_dt(x["effective_until"]),
        "status": x["status"],
        "created_at": fmt_dt(x["created_at"]),
        "updated_at": fmt_dt(x["updated_at"]),
        "version": x["version"],
    }


def ser_workload(w):
    return {
        "id": w["id"],
        "registry_id": w["registry_id"],
        "panel_manager_id": w["panel_manager_id"],
        "assigned_member_count": w["assigned_member_count"],
        "closed_gap_count_period": w["closed_gap_count_period"],
        "utilization_ratio": w["utilization_ratio"],
        "period_key": w["period_key"],
        "created_at": fmt_dt(w["created_at"]),
        "updated_at": fmt_dt(w["updated_at"]),
        "version": w["version"],
    }


def ser_payout(p):
    return {
        "id": p["id"],
        "workload_id": p["workload_id"],
        "panel_manager_id": p["panel_manager_id"],
        "period_key": p["period_key"],
        "base_amount_cents": p["base_amount_cents"],
        "tier_multiplier_bps": p["tier_multiplier_bps"],
        "quality_bonus_cents": p["quality_bonus_cents"],
        "total_payout_cents": p["total_payout_cents"],
        "status": p["status"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def ser_report(r):
    return {
        "id": r["id"],
        "measure_id": r["measure_id"],
        "registry_id": r["registry_id"],
        "period_key": r["period_key"],
        "denominator_count": r["denominator_count"],
        "numerator_count": r["numerator_count"],
        "closure_rate_bps": r["closure_rate_bps"],
        "variant": r["variant"],
        "reconciled_at": fmt_dt(r.get("reconciled_at")),
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }
