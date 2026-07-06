"""Cross-aggregate recomputes + serialization (PRD §2.6-§2.8, §3.6).

Computed fields (quota counts, points_balance, lifetime counters, health) are
derived FRESHLY from current state on every read/transition — never stored as
drifting tallies (PRD §2.7, §2.8). This module owns those derivations and the
public serialization shape of each entity.
"""
import math

import clock
import db
from services import calc

# Screening-axis sets that reserve / commit a quota seat (PRD §2.7).
RESERVING_STATES = {"SCREENING", "SCREENED_IN"}
COMMITTING_STATES = {"QUALIFIED"}


# ---------------------------------------------------------------------------
# Quota cell fill counts (calc 4 / PRD §2.7)
# ---------------------------------------------------------------------------
def cell_counts(cell):
    """reserved_n, committed_n, available_n, fill_status from current state.

    Evaluation order pinned: reserved_n and committed_n computed first from the
    CURRENT screening_status of every participation, THEN available_n derived.
    """
    reserved_n = 0
    committed_n = 0
    for p in db.participations.values():
        if p["quota_cell_id"] != cell["id"]:
            continue
        ss = p["screening_status"]
        if ss in RESERVING_STATES:
            reserved_n += 1
        elif ss in COMMITTING_STATES:
            committed_n += 1
    target_n = cell["target_n"]
    available_n = max(0, target_n - reserved_n - committed_n)
    fill_status = "FILLED" if committed_n >= target_n else "OPEN"
    return reserved_n, committed_n, available_n, fill_status


def cell_available(cell):
    return cell_counts(cell)[2]


def cell_available_for_claim(cell, claiming_participation_id):
    """available_n for a seat-claim check (screen-in / rescreen), excluding the
    acting participation's own contribution to reserved_n.

    PRD ambiguity resolved: the screen-in check is "available_n of at least 1"
    (PRD §3.2), while the scaffold notes "cell reserved_n already counts this
    participation" (scaffold line 280). A SCREENING->SCREENED_IN transition keeps
    the SAME seat (both are reserving states), so it must not require a fresh seat
    — otherwise a target_n=1 cell could never be filled. We therefore compute the
    seat-claim availability as target_n - reserved_n - committed_n with the acting
    participation excluded from the counts. For rescreen the acting participation
    is SCREENED_OUT (holds no seat), so excluding it is a no-op and the check
    correctly demands a genuinely free seat. This makes screen-in and rescreen
    uniform: the participation needs a seat that is free once its own current
    contribution is set aside.
    """
    reserved_n = 0
    committed_n = 0
    for p in db.participations.values():
        if p["quota_cell_id"] != cell["id"]:
            continue
        if p["id"] == claiming_participation_id:
            continue
        ss = p["screening_status"]
        if ss in RESERVING_STATES:
            reserved_n += 1
        elif ss in COMMITTING_STATES:
            committed_n += 1
    return max(0, cell["target_n"] - reserved_n - committed_n)


# ---------------------------------------------------------------------------
# Study computed quota totals (PRD §2.7)
# ---------------------------------------------------------------------------
def study_totals(study):
    target_total_n = 0
    committed_total_n = 0
    for cell in db.quota_cells.values():
        if cell["study_id"] != study["id"]:
            continue
        _, committed_n, _, _ = cell_counts(cell)
        target_total_n += cell["target_n"]
        committed_total_n += committed_n
    return target_total_n, committed_total_n


# ---------------------------------------------------------------------------
# Panelist points balance (calc 5 / PRD §2.8)
# ---------------------------------------------------------------------------
def points_balance(panelist):
    credited = 0
    for a in db.incentive_accruals.values():
        if a["panelist_id"] == panelist["id"] and a["status"] == "CREDITED":
            credited += a["points"]
    consumed = 0
    for pr in db.payout_requests.values():
        if pr["panelist_id"] == panelist["id"] and pr["status"] in ("APPROVED", "PAID"):
            consumed += pr["points_requested"]
    return credited - consumed


# ---------------------------------------------------------------------------
# Panelist lifetime counters + last_activity (PRD §3.2-§3.6)
# ---------------------------------------------------------------------------
def panelist_participations(panelist_id):
    return [p for p in db.participations.values()
            if p["panelist_id"] == panelist_id]


def lifetime_invited_n(panelist_id):
    return len(panelist_participations(panelist_id))


def lifetime_completed_n(panelist_id):
    return sum(1 for p in panelist_participations(panelist_id)
               if p["completion_status"] == "COMPLETED")


# ---------------------------------------------------------------------------
# Health score (calc 3 / PRD §3.6), rolling + lifetime variants
# ---------------------------------------------------------------------------
def _days_since(last_activity_iso):
    if not last_activity_iso:
        return None
    last = clock.parse_iso8601(last_activity_iso)
    delta = clock.now() - last
    days = delta.total_seconds() / 86400.0
    if days < 0:
        days = 0
    return math.floor(days)


def health_scores(panelist):
    """Return (rolling, lifetime) health scores per calc 3 variants."""
    parts = panelist_participations(panelist["id"])
    # most recent by created_at DESC, stable on insertion seq
    parts_sorted = sorted(parts, key=lambda p: (p["created_at"], p["_seq"]),
                          reverse=True)
    days = _days_since(panelist.get("last_activity_at"))

    # rolling variant: most recent RECENT_WINDOW only
    window = parts_sorted[:calc.RECENT_WINDOW]
    completed_recent = sum(1 for p in window if p["completion_status"] == "COMPLETED")
    invited_recent = len(window)
    rolling = calc.health_score(completed_recent, invited_recent, days)

    # lifetime variant: ALL participations
    completed_all = sum(1 for p in parts_sorted if p["completion_status"] == "COMPLETED")
    invited_all = len(parts_sorted)
    lifetime = calc.health_score(completed_all, invited_all, days)
    return rolling, lifetime


def recompute_panelist_health(panelist):
    """Recompute rolling health_score, persist it, and drive ACTIVE<->AT_RISK.

    On each health recompute (PRD §3.6): if health_score < CHURN_THRESHOLD an
    ACTIVE panelist becomes AT_RISK; if it rises back to >= CHURN_THRESHOLD an
    AT_RISK panelist returns to ACTIVE. SUSPENDED / CHURNED are untouched here.
    """
    rolling, _ = health_scores(panelist)
    changed = False
    if panelist.get("health_score") != rolling:
        panelist["health_score"] = rolling
        changed = True

    status = panelist["status"]
    new_status = status
    if status == "ACTIVE" and rolling < calc.CHURN_THRESHOLD:
        new_status = "AT_RISK"
    elif status == "AT_RISK" and rolling >= calc.CHURN_THRESHOLD:
        new_status = "ACTIVE"
    if new_status != status:
        panelist["status"] = new_status
        changed = True

    if changed:
        db.touch(panelist)
    return rolling


# ---------------------------------------------------------------------------
# Serialization — public shapes (system + computed fields materialized)
# ---------------------------------------------------------------------------
def _common(rec, has_version=True):
    out = {
        "id": rec["id"],
        "created_at": rec["created_at"],
    }
    if has_version:
        out["updated_at"] = rec["updated_at"]
        out["version"] = rec["version"]
    return out


def serialize_study(study):
    target_total_n, committed_total_n = study_totals(study)
    out = _common(study)
    out.update({
        "title": study["title"],
        "irb_protocol_number": study["irb_protocol_number"],
        "estimated_minutes": study["estimated_minutes"],
        "base_incentive_points": study["base_incentive_points"],
        "screener_min_age": study["screener_min_age"],
        "required_consent_version": study["required_consent_version"],
        "target_total_n": target_total_n,
        "committed_total_n": committed_total_n,
        "status": study["status"],
    })
    return out


def serialize_quota_cell(cell):
    reserved_n, committed_n, available_n, fill_status = cell_counts(cell)
    out = _common(cell)
    out.update({
        "study_id": cell["study_id"],
        "segment_key": cell["segment_key"],
        "target_n": cell["target_n"],
        "reserved_n": reserved_n,
        "committed_n": committed_n,
        "available_n": available_n,
        "fill_status": fill_status,
    })
    return out


def serialize_panelist(panelist):
    out = _common(panelist)
    out.update({
        "email": panelist["email"],
        "full_name": panelist["full_name"],
        "age": panelist["age"],
        "segment_key": panelist["segment_key"],
        "points_balance": points_balance(panelist),
        "lifetime_invited_n": lifetime_invited_n(panelist["id"]),
        "lifetime_completed_n": lifetime_completed_n(panelist["id"]),
        "last_activity_at": panelist.get("last_activity_at"),
        "health_score": panelist["health_score"],
        "status": panelist["status"],
    })
    return out


def serialize_consent(consent):
    out = _common(consent, has_version=False)
    out.update({
        "panelist_id": consent["panelist_id"],
        "study_id": consent["study_id"],
        "consent_version": consent["consent_version"],
        "decision": consent["decision"],
        "recorded_at": consent["recorded_at"],
    })
    return out


def serialize_participation(p):
    out = _common(p)
    out.update({
        "study_id": p["study_id"],
        "panelist_id": p["panelist_id"],
        "quota_cell_id": p["quota_cell_id"],
        "screening_status": p["screening_status"],
        "completion_status": p["completion_status"],
        "completion_seconds": p.get("completion_seconds"),
        "straightline_run": p.get("straightline_run"),
        "quality_score": p.get("quality_score"),
        "quality_status": p["quality_status"],
        "provisional_points": p.get("provisional_points"),
        "rescreen_count": p["rescreen_count"],
    })
    return out


def serialize_attention_check(ac):
    out = _common(ac, has_version=False)
    out.update({
        "participation_id": ac["participation_id"],
        "check_kind": ac["check_kind"],
        "passed": ac["passed"],
        "recorded_at": ac["recorded_at"],
    })
    return out


def serialize_accrual(a):
    out = _common(a)
    out.update({
        "panelist_id": a["panelist_id"],
        "participation_id": a["participation_id"],
        "accrual_kind": a["accrual_kind"],
        "points": a["points"],
        "status": a["status"],
    })
    return out


def serialize_payout_request(pr):
    out = _common(pr)
    out.update({
        "panelist_id": pr["panelist_id"],
        "payout_method": pr["payout_method"],
        "points_requested": pr["points_requested"],
        "cash_cents": pr["cash_cents"],
        "expected_panelist_version": pr["expected_panelist_version"],
        "status": pr["status"],
    })
    return out


def serialize_facility(f):
    out = _common(f)
    out.update({
        "name": f["name"],
        "capacity": f["capacity"],
        "turnaround_minutes": f["turnaround_minutes"],
        "status": f["status"],
    })
    return out


def focus_group_booked_n(fg_id):
    return sum(1 for b in db.focus_group_bookings.values()
               if b["focus_group_id"] == fg_id and b["status"] == "CONFIRMED")


def serialize_focus_group(fg):
    out = _common(fg)
    out.update({
        "study_id": fg["study_id"],
        "facility_id": fg["facility_id"],
        "starts_at": fg["starts_at"],
        "ends_at": fg["ends_at"],
        "seats": fg["seats"],
        "booked_n": focus_group_booked_n(fg["id"]),
        "status": fg["status"],
    })
    return out


def serialize_booking(b):
    out = _common(b)
    out.update({
        "focus_group_id": b["focus_group_id"],
        "panelist_id": b["panelist_id"],
        "expected_focus_group_version": b["expected_focus_group_version"],
        "status": b["status"],
    })
    return out


def serialize_data_delivery(d):
    out = _common(d)
    out.update({
        "study_id": d["study_id"],
        "included_completes_n": d["included_completes_n"],
        "report_format": d["report_format"],
        "status": d["status"],
    })
    return out
