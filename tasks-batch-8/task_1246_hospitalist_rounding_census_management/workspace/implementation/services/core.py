"""Shared helpers: entity creation, serialization, computed field refresh."""

import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
from db import store


# ---------------------------------------------------------------------------
# Constants from the scaffold
# ---------------------------------------------------------------------------

CONTINUITY_BONUS = Decimal("0.25")
NIGHT_PENALTY = Decimal("0.10")
CONTINUITY_WINDOW_DAYS = 30

LEVELING_THRESHOLD = Decimal("0.15")
PROJECTION_HORIZON_HOURS = 24

ESTIMATED_WRVU = {
    "ADMISSION_HCP": Decimal("2.5"),
    "SUBSEQUENT_VISIT": Decimal("1.2"),
    "DISCHARGE_DAY": Decimal("1.8"),
    "CONSULT_NOTE": Decimal("1.5"),
}
ADJUST_FACTOR = Decimal("1.06")

DISCHARGE_CUTOFF_TIME = "11:00:00Z"

EXPECTED_LOS_DAYS = {
    "INPATIENT": {"HIGH": 6, "MEDIUM": 4, "LOW": 2},
    "OBSERVATION": {"HIGH": 2, "MEDIUM": 2, "LOW": 1},
}
LOS_ALERT_MULTIPLIER = Decimal("1.5")

OBS_CONVERT_THRESHOLD_HOURS = Decimal("48.0")

SLA_MINUTES = {"STAT": 15, "URGENT": 30, "ROUTINE": 120}
REOPEN_WINDOW_HOURS = 24

MAX_CROSS_COVER_LOAD = Decimal("40")
NIGHT_CROSS_COVER_MULTIPLIER = Decimal("2.0")
CONSULT_LOAD_WEIGHT = Decimal("1")
HANDOFF_LOAD_WEIGHT = Decimal("2")


# ---------------------------------------------------------------------------
# Rounding helpers
# ---------------------------------------------------------------------------

def round2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round4(value):
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def to_number(d):
    """Convert Decimal to a JSON-friendly number (int when whole, else float)."""
    if d is None:
        return None
    if not isinstance(d, Decimal):
        return d
    f = float(d)
    return f


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def touch(entity):
    entity["updated_at"] = clock.now()
    entity["version"] += 1


def make_entity(fields):
    now = clock.now()
    entity = {"id": new_id(), "created_at": now, "updated_at": now, "version": 1}
    entity.update(fields)
    return entity


# ---------------------------------------------------------------------------
# Hospitalist computed fields
# ---------------------------------------------------------------------------

def refresh_hospitalist_census(h):
    """Recompute current_census, pending_offers, distribution_eligible for hospitalist h."""
    hid = h["id"]
    current = sum(
        1 for a in store["assignments"].values()
        if a["hospitalist_id"] == hid and a["status"] == "ACTIVE"
    )
    pending = sum(
        1 for a in store["admissions"].values()
        if a["status"] == "OFFERED" and a["offered_to_hospitalist_id"] == hid
    )
    h["current_census"] = current
    h["pending_offers"] = pending
    h["distribution_eligible"] = (
        h["employment_status"] == "ACTIVE" and current < h["max_census_cap"]
    )


# ---------------------------------------------------------------------------
# Shift helpers
# ---------------------------------------------------------------------------

def active_covering_shift(hospitalist_id, at=None):
    """Return the hospitalist's ACTIVE shift whose half-open interval covers `at` (or now)."""
    if at is None:
        at = clock.now()
    for s in store["shifts"].values():
        if (
            s["hospitalist_id"] == hospitalist_id
            and s["state"] == "ACTIVE"
            and s["start_at"] <= at < s["end_at"]
        ):
            return s
    return None


def intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap test. Pure adjacency does not overlap."""
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------------------
# Continuity predicate
# ---------------------------------------------------------------------------

def continuity_flag(patient_id, hospitalist_id, at=None):
    """True when a CLOSED assignment pairing (patient, hospitalist) closed within
    CONTINUITY_WINDOW_DAYS of `at` (default now)."""
    if at is None:
        at = clock.now()
    window_start = at - timedelta(days=CONTINUITY_WINDOW_DAYS)
    for a in store["assignments"].values():
        if (
            a["patient_id"] == patient_id
            and a["hospitalist_id"] == hospitalist_id
            and a["status"] == "CLOSED"
            and a.get("closed_at") is not None
            and a["closed_at"] >= window_start
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Distribution selector
# ---------------------------------------------------------------------------

def run_selector(admission):
    """Run the admission distribution selector for a QUEUED admission.

    If a winner exists: transitions admission QUEUED -> OFFERED, stamps fields,
    bumps pending_offers and version. Otherwise leaves admission QUEUED.
    """
    now = clock.now()
    candidates = []
    for h in store["hospitalists"].values():
        if h["employment_status"] != "ACTIVE":
            continue
        if not h["distribution_eligible"]:
            continue
        if h["current_census"] >= h["max_census_cap"]:
            continue
        shift = active_covering_shift(h["id"], now)
        if shift is None:
            continue
        if h["id"] in admission["declined_hospitalist_ids"]:
            continue
        # one outstanding offer per hospitalist
        has_offer = any(
            a["status"] == "OFFERED" and a["offered_to_hospitalist_id"] == h["id"]
            for a in store["admissions"].values()
        )
        if has_offer:
            continue

        cont = 1 if continuity_flag(admission["patient_id"], h["id"], now) else 0
        night_loaded = 1 if (shift["shift_type"] == "NIGHT" and h["pending_offers"] > 0) else 0

        spare = Decimal(h["max_census_cap"] - h["current_census"]) / Decimal(h["max_census_cap"])
        base = spare + CONTINUITY_BONUS * cont
        if base > Decimal("1.0"):
            base = Decimal("1.0")
        score = base - NIGHT_PENALTY * night_loaded
        score = round4(score)
        candidates.append((h, shift, score))

    if not candidates:
        return  # documented fallback: stay QUEUED

    # ranking: score DESC; current_census ASC; covering shift start_at ASC; covering shift created_at ASC
    candidates.sort(key=lambda c: (-c[2], c[0]["current_census"], c[1]["start_at"], c[1]["created_at"]))
    winner, _shift, score = candidates[0]

    admission["status"] = "OFFERED"
    admission["offered_to_hospitalist_id"] = winner["id"]
    admission["offered_at"] = now
    admission["distribution_score"] = score
    touch(admission)
    refresh_hospitalist_census(winner)
    touch(winner)


# ---------------------------------------------------------------------------
# Handoff completeness
# ---------------------------------------------------------------------------

def compute_handoff_counts(handoff):
    """Compute required/covered/open counts and completeness score for a handoff."""
    shift = store["shifts"].get(handoff["shift_id"])
    if shift is None:
        required_set = set()
    else:
        required_set = {
            a["patient_id"]
            for a in store["assignments"].values()
            if a["hospitalist_id"] == shift["hospitalist_id"] and a["status"] == "ACTIVE"
        }
    patient_ids = set(handoff.get("patient_ids") or [])
    covered = required_set & patient_ids
    required_count = len(required_set)
    covered_count = len(covered)
    open_count = required_count - covered_count
    if required_count == 0:
        score = Decimal("1.0")
    else:
        score = round4(Decimal(covered_count) / Decimal(required_count))
    handoff["required_patient_count"] = required_count
    handoff["covered_patient_count"] = covered_count
    handoff["open_item_count"] = open_count
    handoff["completeness_score"] = score


# ---------------------------------------------------------------------------
# Report totals
# ---------------------------------------------------------------------------

def compute_report_totals(report):
    """Recompute encounter_count, total_wrvu_provisional, total_wrvu_final, wrvu_variance
    over the currently-RECORDED encounters of the report's hospitalist in period."""
    hid = report["hospitalist_id"]
    ps = report["period_start"]
    pe = report["period_end"]
    linked = [
        e for e in store["encounters"].values()
        if e["hospitalist_id"] == hid
        and e["status"] == "RECORDED"
        and ps <= e["occurred_on"] <= pe
    ]
    report["encounter_count"] = len(linked)
    prov = Decimal("0")
    for e in linked:
        prov += Decimal(str(e["estimated_wrvu"]))
    report["total_wrvu_provisional"] = round2(prov)
    if report.get("total_wrvu_final") is not None or report["status"] == "FINALIZED":
        raw = Decimal("0")
        for e in linked:
            raw += Decimal(str(e["wrvu_value"]))
        final = round2(raw)
        report["total_wrvu_final"] = final
        report["wrvu_variance"] = round2(final - report["total_wrvu_provisional"])
    return linked


def link_report_encounters(report):
    """Link all currently RECORDED in-period encounters of the hospitalist to this report."""
    hid = report["hospitalist_id"]
    ps = report["period_start"]
    pe = report["period_end"]
    for e in store["encounters"].values():
        if (
            e["hospitalist_id"] == hid
            and e["status"] == "RECORDED"
            and ps <= e["occurred_on"] <= pe
        ):
            if e.get("productivity_report_id") != report["id"]:
                e["productivity_report_id"] = report["id"]
                touch(e)
