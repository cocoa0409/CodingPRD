"""Business-logic services: record lifecycle, derived fields, reconciliation,
compliance posture, report snapshots, and staleness marking."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, next_seq
from util import CLOCK, new_id, parse_date

OVERDUE_NONCOMPLIANT_THRESHOLD = 3
WALKTHROUGH_WINDOW_DAYS = 365
UNANNOUNCED_ALLOWANCE_PCT_NUM = 1
UNANNOUNCED_ALLOWANCE_PCT_DEN = 4  # 25%


# ---------------------------------------------------------------------------
# Record lifecycle
# ---------------------------------------------------------------------------

def new_record(collection, fields):
    now = CLOCK.now_iso()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    rec.update(fields)
    db[collection][rec["id"]] = rec
    return rec


def bump(rec):
    rec["version"] += 1
    rec["updated_at"] = CLOCK.now_iso()


def apply_changes(rec, changes, force=False):
    """Apply a set of field changes; bump updated_at/version at most once."""
    changed = False
    for k, v in changes.items():
        if rec.get(k) != v:
            rec[k] = v
            changed = True
    if changed or force:
        bump(rec)
    return changed


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# SchoolSite derived fields (PRD 3.10, 3.11)
# ---------------------------------------------------------------------------

def site_drills_in_ay(site):
    a = parse_date(site["academic_year_start"])
    b = parse_date(site["academic_year_end"])
    return [
        d for d in db["drill_events"].values()
        if d["site_id"] == site["id"] and a <= parse_date(d["scheduled_date"]) <= b
    ]


def _overdue_action_count(site_id):
    today = CLOCK.today()
    n = 0
    for ca in db["corrective_actions"].values():
        if ca["status"] == "VERIFIED":
            continue
        if parse_date(ca["due_date"]) >= today:
            continue
        aar = db["after_action_reviews"].get(ca["aar_id"])
        if aar is None:
            continue
        drill = db["drill_events"].get(aar["drill_event_id"])
        if drill is None or drill["site_id"] != site_id:
            continue
        n += 1
    return n


def compute_posture(site):
    today = CLOCK.today()
    drills = site_drills_in_ay(site)
    overdue = _overdue_action_count(site["id"])

    non_compliant = False
    if today > parse_date(site["academic_year_end"]):
        reqs = [r for r in db["requirements"].values() if r["site_id"] == site["id"]]
        for req in reqs:
            completed = sum(
                1 for d in drills
                if d["drill_type"] == req["drill_type"] and d["status"] in ("COMPLETED", "CLOSED")
            )
            if completed < req["required_per_year"]:
                non_compliant = True
                break
    if overdue >= OVERDUE_NONCOMPLIANT_THRESHOLD:
        non_compliant = True
    if non_compliant:
        return "NON_COMPLIANT"

    if any(d["status"] == "MISSED" for d in drills) or overdue >= 1:
        return "AT_RISK"
    return "ON_TRACK"


def refresh_site(site_id):
    """Recompute the four drill counters and compliance_posture (single bump)."""
    site = db["sites"].get(site_id)
    if site is None:
        return
    drills = site_drills_in_ay(site)
    changes = {
        "drills_scheduled_count": sum(1 for d in drills if d["status"] in ("SCHEDULED", "IN_PROGRESS")),
        "drills_completed_count": sum(1 for d in drills if d["status"] in ("COMPLETED", "CLOSED")),
        "drills_missed_count": sum(1 for d in drills if d["status"] == "MISSED"),
        "drills_cancelled_count": sum(1 for d in drills if d["status"] == "CANCELLED"),
        "compliance_posture": compute_posture(site),
    }
    apply_changes(site, changes)


# ---------------------------------------------------------------------------
# Drill roster counters (PRD 3.12)
# ---------------------------------------------------------------------------

def roster_entries_of(drill_id):
    return [e for e in db["roster_entries"].values() if e["drill_event_id"] == drill_id]


def refresh_roster_counters(drill):
    entries = roster_entries_of(drill["id"])
    changes = {
        "roster_total": len(entries),
        "unaccounted_count": sum(1 for e in entries if e["status"] == "UNACCOUNTED"),
        "accounted_count": sum(1 for e in entries if e["status"] == "ACCOUNTED"),
        "released_count": sum(1 for e in entries if e["status"] == "RELEASED"),
    }
    apply_changes(drill, changes)


# ---------------------------------------------------------------------------
# AfterActionReview corrective-action counters
# ---------------------------------------------------------------------------

def corrective_actions_of(aar_id):
    return [c for c in db["corrective_actions"].values() if c["aar_id"] == aar_id]


def ca_counter_changes(aar_id):
    cas = corrective_actions_of(aar_id)
    return {
        "ca_total_count": len(cas),
        "ca_verified_count": sum(1 for c in cas if c["status"] == "VERIFIED"),
    }


# ---------------------------------------------------------------------------
# CorrectiveAction is_overdue flag
# ---------------------------------------------------------------------------

def ca_is_overdue(ca):
    return ca["status"] != "VERIFIED" and parse_date(ca["due_date"]) < CLOCK.today()


# ---------------------------------------------------------------------------
# ComplianceReport staleness (PRD 3.9)
# ---------------------------------------------------------------------------

def stale_reports_for_drill(site_id, scheduled_date):
    sd = parse_date(scheduled_date)
    for r in db["compliance_reports"].values():
        if r["site_id"] != site_id or r["status"] != "DRAFT":
            continue
        if parse_date(r["period_start"]) <= sd <= parse_date(r["period_end"]):
            apply_changes(r, {"status": "STALE"})


def stale_all_draft_reports(site_id):
    for r in db["compliance_reports"].values():
        if r["site_id"] == site_id and r["status"] == "DRAFT":
            apply_changes(r, {"status": "STALE"})


# ---------------------------------------------------------------------------
# Compliance snapshot (PRD 3.9; calculations statutory_attainment + score)
# ---------------------------------------------------------------------------

def compute_snapshot(site_id, period_start, period_end):
    ps = parse_date(period_start)
    pe = parse_date(period_end)
    reqs = sorted(
        (r for r in db["requirements"].values() if r["site_id"] == site_id),
        key=lambda r: (r["created_at"], r["_seq"]),
    )
    attainments = []
    ratios = []
    for req in reqs:
        counted = [
            d for d in db["drill_events"].values()
            if d["site_id"] == site_id
            and d["drill_type"] == req["drill_type"]
            and d["status"] in ("COMPLETED", "CLOSED")
            and ps <= parse_date(d["scheduled_date"]) <= pe
        ]
        counted.sort(key=lambda d: (d["scheduled_date"], d["created_at"], d["_seq"]))
        n = len(counted)
        spacing_ok = True
        for prev, cur in zip(counted, counted[1:]):
            gap = (parse_date(cur["scheduled_date"]) - parse_date(prev["scheduled_date"])).days
            if gap < req["min_spacing_days"]:
                spacing_ok = False
                break
        count_only = n >= req["required_per_year"]
        attainments.append({
            "drill_type": req["drill_type"],
            "required_count": req["required_per_year"],
            "completed_count": n,
            "spacing_compliant": spacing_ok,
            "attainment_count_only": count_only,
            "attainment_strict": count_only and spacing_ok,
        })
        ratio = Decimal(n) / Decimal(req["required_per_year"])
        if ratio > 1:
            ratio = Decimal(1)
        ratio = ratio.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        ratios.append(ratio)
    n_req = len(reqs)
    overall_count_only = all(a["attainment_count_only"] for a in attainments)
    overall_strict = all(a["attainment_strict"] for a in attainments)
    score = ((sum(ratios, Decimal(0)) / Decimal(n_req)) * 100).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP)
    return attainments, overall_count_only, overall_strict, float(score)


# ---------------------------------------------------------------------------
# Evacuation timing assessment (calculations.evacuation_time_assessment)
# ---------------------------------------------------------------------------

def compute_evac_assessment(drill):
    """Returns dict of computed timing fields for an IN_PROGRESS -> COMPLETED drill."""
    from util import fmt_dt, parse_dt
    actual_start = parse_dt(drill["actual_start_at"])
    all_clear = CLOCK.now()
    provisional = int((all_clear - actual_start).total_seconds())
    entries = roster_entries_of(drill["id"])
    if entries:
        marks = []
        for e in entries:
            ts = e["released_at"] if e["status"] == "RELEASED" else e["accounted_at"]
            if ts is not None:
                marks.append(parse_dt(ts))
        last_accountability = max(marks) if marks else all_clear
    else:
        # PRD 3.6: when the roster is empty, last_accountability_at = all_clear_at
        last_accountability = all_clear
    official = int((last_accountability - actual_start).total_seconds())

    req = next(
        (r for r in db["requirements"].values()
         if r["site_id"] == drill["site_id"] and r["drill_type"] == drill["drill_type"]),
        None,
    )
    target = req["target_evac_seconds"] if req else None
    if target is None:
        met_standard = None
        met_adjusted = None
    else:
        met_standard = official <= target
        if drill["announcement_mode"] == "UNANNOUNCED":
            # ceil(target * 0.25) with exact integer arithmetic
            allowance = (target * UNANNOUNCED_ALLOWANCE_PCT_NUM
                         + UNANNOUNCED_ALLOWANCE_PCT_DEN - 1) // UNANNOUNCED_ALLOWANCE_PCT_DEN
            met_adjusted = official <= (target + allowance)
        else:
            met_adjusted = met_standard
    return {
        "all_clear_at": fmt_dt(all_clear),
        "last_accountability_at": fmt_dt(last_accountability),
        "provisional_evac_seconds": provisional,
        "official_evac_seconds": official,
        "met_target_standard": met_standard,
        "met_target_adjusted": met_adjusted,
    }
