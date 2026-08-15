"""Domain services: state machines, cascades, derived fields, calculations.

Everything here follows PRD §3 literally; rounding uses Decimal with
ROUND_HALF_UP per PRD §2.6 (per-line rounding before summation for escrow,
two-decimal half-up rounding for scores and trend averages).
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from db import (
    appointments, attendees, communities, deficiency_items, escrows, homes,
    signatures, surveys, visits,
)
from errors import (
    err_daily_capacity, err_no_releasable, err_open_appointment_exists,
    err_outside_window, err_rep_schedule_conflict, err_schedule_in_past,
    err_visit_overlap,
)

# --- enum value sets -------------------------------------------------------
OPEN_APPOINTMENT_STATUSES = {"REQUESTED", "CONFIRMED", "IN_PROGRESS"}
OPEN_ITEM_STATUSES = {"DECIDED", "IN_REPAIR", "READY_FOR_REINSPECTION", "VERIFIED"}
PROVISIONAL_ESCROW_STATUSES = OPEN_ITEM_STATUSES | {"SIGNED_OFF"}
FINAL_ESCROW_STATUSES = set(OPEN_ITEM_STATUSES)
TERMINAL_ITEM_STATUSES = {"SIGNED_OFF", "WITHDRAWN"}
NON_VOIDED_ESCROW_STATUSES = {"DRAFT", "ACTIVE", "PARTIALLY_RELEASED", "FULLY_RELEASED"}

MINUTES_PER_DAY = 1440
APPOINTMENT_START_EARLY_MINUTES = 30
RESCHEDULE_LIMIT = 3
DEFAULT_VISIT_DURATION_MINUTES = 60

CHECKLIST_CATALOG = [
    ("HVAC", "HVAC system demonstration", True),
    ("PLUMBING", "Plumbing system demonstration", True),
    ("ELECTRICAL", "Electrical system demonstration", True),
    ("APPLIANCES", "Appliances demonstration", False),
    ("EXTERIOR", "Exterior features demonstration", True),
    ("SAFETY", "Safety systems demonstration", True),
]

RES_BEFORE = "COMPLETE_BEFORE_CLOSING"
RES_AFTER = "COMPLETE_AFTER_CLOSING"


# ---------------------------------------------------------------------------
# Home derived counts and readiness (PRD §3.4)
# ---------------------------------------------------------------------------

def home_items(home_id):
    return [i for i in deficiency_items.values() if i["home_id"] == home_id]


def compute_open_counts(home_id):
    before = after = 0
    for i in home_items(home_id):
        if i["status"] in OPEN_ITEM_STATUSES:
            if i["resolution"] == RES_BEFORE:
                before += 1
            elif i["resolution"] == RES_AFTER:
                after += 1
    return before, after


def recompute_home(home):
    """Recompute open counts and re-evaluate readiness. The record's
    updated_at/version advance only when something actually changed
    (PRD §2.9: cascades that mutate a resource refresh it)."""
    changed = False
    before, after = compute_open_counts(home["id"])
    if home["open_before_closing_count"] != before:
        home["open_before_closing_count"] = before
        changed = True
    if home["open_after_closing_count"] != after:
        home["open_after_closing_count"] = after
        changed = True
    # Readiness re-evaluation (PRD §3.4):
    # ACKNOWLEDGED + before == 0  -> READY_TO_CLOSE
    # READY_TO_CLOSE + before > 0 -> ACKNOWLEDGED
    if home["status"] == "ACKNOWLEDGED" and before == 0:
        home["status"] = "READY_TO_CLOSE"
        changed = True
    elif home["status"] == "READY_TO_CLOSE" and before > 0:
        home["status"] = "ACKNOWLEDGED"
        changed = True
    if changed:
        db.touch(home)


# ---------------------------------------------------------------------------
# Escrow holdback (PRD §3.7)
# ---------------------------------------------------------------------------

def _contribution(item, community):
    """Per-line contribution: round_half_up(cost * multiplier) to whole cents."""
    product = Decimal(item["estimated_repair_cost_cents"]) * Decimal(
        str(community["holdback_cost_multiplier"])
    )
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def escrow_amount(home, community, statuses):
    """Per-line round FIRST, then sum, then clamp — the pinned order."""
    raw = sum(
        _contribution(i, community)
        for i in home_items(home["id"])
        if i["resolution"] == RES_AFTER and i["status"] in statuses
    )
    if raw == 0:
        return 0
    return min(max(raw, community["holdback_min_cents"]), community["holdback_max_cents"])


def non_voided_escrow(home_id):
    for e in sorted(escrows.values(), key=db.sort_key):
        if e["home_id"] == home_id and e["status"] in NON_VOIDED_ESCROW_STATUSES:
            return e
    return None


def any_voided_escrow(home_id):
    return any(
        e["home_id"] == home_id and e["status"] == "VOIDED" for e in escrows.values()
    )


def _create_escrow(home_id):
    esc = db.stamp({
        "id": db.new_id(),
        "home_id": home_id,
        "status": "DRAFT",
        "holdback_amount_cents": 0,
        "final_holdback_cents": None,
        "funded_amount_cents": 0,
        "released_amount_cents": 0,
        "remaining_amount_cents": 0,
    })
    escrows[esc["id"]] = esc
    return esc


def _apply_recompute(home, esc, bump_always):
    """Store the provisional amount and apply the DRAFT<->ACTIVE / ACTIVE->VOIDED
    flips. Returns the escrow."""
    community = communities[home["community_id"]]
    amount = escrow_amount(home, community, PROVISIONAL_ESCROW_STATUSES)
    changed = esc["holdback_amount_cents"] != amount
    esc["holdback_amount_cents"] = amount
    if esc["status"] == "DRAFT" and amount > 0:
        esc["status"] = "ACTIVE"
        changed = True
    elif esc["status"] == "ACTIVE" and amount == 0 and home["status"] != "CLOSED":
        esc["status"] = "VOIDED"
        changed = True
    if changed or bump_always:
        db.touch(esc)
    return esc


def escrow_provision_on_completion(home):
    """Appointment completion cascade LINK2+3: provision DRAFT(0) only when no
    non-VOIDED escrow exists, then recompute and activate when amount > 0."""
    if non_voided_escrow(home["id"]) is not None:
        return None
    esc = _create_escrow(home["id"])
    return _apply_recompute(home, esc, bump_always=False)


def escrow_on_decide(home):
    """Decide/reverse drives the recompute whenever a non-VOIDED holdback
    exists. When the prior holdback was voided pre-close (all after-closing
    decisions reversed), a later decision provisions a fresh DRAFT in its
    place (PRD §3.7 cycle)."""
    esc = non_voided_escrow(home["id"])
    if esc is not None:
        # Any decide-driven recompute advances the escrow version (OCC rule).
        return _apply_recompute(home, esc, bump_always=True)
    if any_voided_escrow(home["id"]):
        esc = _create_escrow(home["id"])
        return _apply_recompute(home, esc, bump_always=False)
    return None


# ---------------------------------------------------------------------------
# Scheduling calculations (PRD §3.2, §3.5)
# ---------------------------------------------------------------------------

def appointment_window_check(home, community, start_dt):
    """Temporal gates for orientation scheduling. The past check is evaluated
    before the window check (corner: schedule_in_past_rejected)."""
    if not start_dt > db.now():
        raise err_schedule_in_past()
    closing_dt = db.parse_dt(home["closing_date"])
    minutes_before = int((closing_dt - start_dt).total_seconds() // 60)
    if minutes_before < community["orientation_min_days_before_closing"] * MINUTES_PER_DAY:
        raise err_outside_window()
    if minutes_before > community["orientation_max_days_before_closing"] * MINUTES_PER_DAY:
        raise err_outside_window()


def orientation_overlap_check(rep_id, community, start_dt, duration_minutes, exclude_id=None):
    """Closed, buffer-extended pairwise intervals per rep; touching counts."""
    b = timedelta(minutes=community["appointment_buffer_minutes"])
    new_lo, new_hi = start_dt - b, start_dt + timedelta(minutes=duration_minutes) + b
    for appt in appointments.values():
        if appt["rep_id"] != rep_id or appt["id"] == exclude_id:
            continue
        if appt["status"] not in OPEN_APPOINTMENT_STATUSES:
            continue
        ex_start = db.parse_dt(appt["scheduled_start"])
        ex_lo = ex_start - b
        ex_hi = ex_start + timedelta(minutes=appt["duration_minutes"]) + b
        if new_lo <= ex_hi and ex_lo <= new_hi:
            raise err_rep_schedule_conflict()


def open_appointment_check(home_id):
    for appt in appointments.values():
        if appt["home_id"] == home_id and appt["status"] in OPEN_APPOINTMENT_STATUSES:
            raise err_open_appointment_exists()


def visit_overlap_check(rep_id, start_dt, duration_minutes):
    """Half-open pairwise intervals over the rep's SCHEDULED visits;
    adjacency (new_start == existing_end) is allowed."""
    new_lo = start_dt
    new_hi = start_dt + timedelta(minutes=duration_minutes)
    for v in visits.values():
        if v["rep_id"] != rep_id or v["status"] != "SCHEDULED":
            continue
        ex_lo = db.parse_dt(v["scheduled_start"])
        ex_hi = ex_lo + timedelta(minutes=v["duration_minutes"])
        if new_lo < ex_hi and ex_lo < new_hi:
            raise err_visit_overlap()


def visit_capacity_check(rep, start_dt, duration_minutes):
    """Daily aggregate over SCHEDULED+COMPLETED visits on the same UTC date;
    reaching the cap exactly is allowed."""
    day = start_dt.date()
    total = duration_minutes
    for v in visits.values():
        if v["rep_id"] != rep["id"] or v["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        if db.parse_dt(v["scheduled_start"]).date() == day:
            total += v["duration_minutes"]
    if total > rep["daily_visit_capacity_minutes"]:
        raise err_daily_capacity()


# ---------------------------------------------------------------------------
# Appointment completion gates and cascade (PRD §3.3)
# ---------------------------------------------------------------------------

def checklist_counts(appt):
    demo = pend = skip = 0
    for entry in appt["checklist_items"]:
        if entry["demonstration_status"] == "DEMONSTRATED":
            demo += 1
        elif entry["demonstration_status"] == "PENDING":
            pend += 1
        elif entry["demonstration_status"] == "SKIPPED":
            skip += 1
    appt["checklist_total_count"] = len(appt["checklist_items"])
    appt["checklist_demonstrated_count"] = demo
    appt["checklist_pending_count"] = pend
    appt["checklist_skipped_count"] = skip


def seed_checklist(appt):
    appt["checklist_items"] = [
        {
            "system_key": key,
            "label": label,
            "is_required": required,
            "demonstration_status": "PENDING",
            "demonstrated_at": None,
        }
        for key, label, required in CHECKLIST_CATALOG
    ]
    checklist_counts(appt)


def completion_cascade(appt, home):
    """COMPLETED side effects, all in the same request (PRD §3.3):
    completed_at stamped, survey ISSUED, signature PENDING (first time only),
    home -> ORIENTED, escrow provisioned/activated (LINK1..3)."""
    appt["status"] = "COMPLETED"
    appt["completed_at"] = db.fmt_dt(db.now())
    db.touch(appt)

    community = communities[home["community_id"]]
    completed_dt = db.parse_dt(appt["completed_at"])
    survey = db.stamp({
        "id": db.new_id(),
        "home_id": home["id"],
        "appointment_id": appt["id"],
        "status": "ISSUED",
        "overall_rating": None,
        "systems_demo_rating": None,
        "timeliness_rating": None,
        "would_recommend": None,
        "comments": None,
        "composite_score": None,
        "submitted_at": None,
        "window_closes_at": db.fmt_dt(
            completed_dt + timedelta(days=community["survey_window_days"])
        ),
    })
    surveys[survey["id"]] = survey

    if not any(s["home_id"] == home["id"] for s in signatures.values()):
        sig = db.stamp({
            "id": db.new_id(),
            "home_id": home["id"],
            "appointment_id": appt["id"],
            "status": "PENDING",
            "signer_buyer_id": None,
            "signed_at": None,
            "open_item_snapshot_count": None,
            "decline_reason": None,
        })
        signatures[sig["id"]] = sig

    if home["status"] == "ORIENTATION_SCHEDULED":
        home["status"] = "ORIENTED"
        db.touch(home)
    escrow_provision_on_completion(home)


# ---------------------------------------------------------------------------
# Deficiency identification shock wave (PRD §3.4)
# ---------------------------------------------------------------------------

def identification_cascade(home):
    """A new deficiency stales a SIGNED signature and reverts an
    ACKNOWLEDGED/READY_TO_CLOSE home to ORIENTED."""
    sig = next((s for s in signatures.values() if s["home_id"] == home["id"]), None)
    if sig is not None and sig["status"] == "SIGNED":
        sig["status"] = "STALE"
        db.touch(sig)
    if home["status"] in ("ACKNOWLEDGED", "READY_TO_CLOSE"):
        home["status"] = "ORIENTED"
        db.touch(home)


# ---------------------------------------------------------------------------
# Survey composite score (PRD §3.8) — Decimal, half-up, 2dp
# ---------------------------------------------------------------------------

def survey_composite(overall, systems, timeliness, would_recommend):
    base = (Decimal("0.5") * overall + Decimal("0.3") * systems
            + Decimal("0.2") * timeliness)
    if not would_recommend:
        base -= Decimal("0.5")
    if min(overall, systems, timeliness) == 1:
        composite = min(base, Decimal("2.0"))  # detractor cap
    else:
        composite = base
    composite = max(Decimal("1.00"), min(Decimal("5.00"), composite))
    return float(composite.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Quality trend aggregation (PRD §3.8) — half-open month window
# ---------------------------------------------------------------------------

def _round2(dec):
    return float(dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def quality_trend(community_id, year, month):
    period_start = db.parse_dt("%04d-%02d-01T00:00:00Z" % (year, month))
    if month == 12:
        period_end = db.parse_dt("%04d-01-01T00:00:00Z" % (year + 1))
    else:
        period_end = db.parse_dt("%04d-%02d-01T00:00:00Z" % (year, month + 1))

    community_homes = {h["id"]: h for h in homes.values()
                       if h["community_id"] == community_id}

    submitted = []
    for s in surveys.values():
        if s["status"] != "SUBMITTED" or s["home_id"] not in community_homes:
            continue
        st = db.parse_dt(s["submitted_at"])
        if period_start <= st < period_end:
            submitted.append(s)

    count = len(submitted)
    surveyed_home_ids = {s["home_id"] for s in submitted}

    if count:
        total = sum(Decimal(str(s["composite_score"])) for s in submitted)
        response_weighted = _round2(total / count)
    else:
        response_weighted = None

    if surveyed_home_ids:
        per_home = []
        for hid in sorted(surveyed_home_ids):
            hs = [s for s in submitted if s["home_id"] == hid]
            mean = sum(Decimal(str(s["composite_score"])) for s in hs) / len(hs)
            per_home.append(Decimal(str(_round2(mean))))
        home_weighted = _round2(sum(per_home) / len(per_home))
    else:
        home_weighted = None

    warrantable = 0
    for i in deficiency_items.values():
        if i["home_id"] not in community_homes or i["classification"] != "WARRANTABLE":
            continue
        created = db.parse_dt(i["created_at"])
        if period_start <= created < period_end:
            warrantable += 1

    completed_home_ids = set()
    for appt in appointments.values():
        if appt["status"] != "COMPLETED" or appt["home_id"] not in community_homes:
            continue
        completed = db.parse_dt(appt["completed_at"])
        if completed is not None and period_start <= completed < period_end:
            completed_home_ids.add(appt["home_id"])

    if completed_home_ids:
        avg_warrantable = _round2(Decimal(warrantable) / len(completed_home_ids))
    else:
        avg_warrantable = None

    return {
        "period_month": "%04d-%02d" % (year, month),
        "submitted_survey_count": count,
        "homes_surveyed_count": len(surveyed_home_ids),
        "response_weighted_avg_score": response_weighted,
        "home_weighted_avg_score": home_weighted,
        "avg_warrantable_items_per_home": avg_warrantable,
    }
