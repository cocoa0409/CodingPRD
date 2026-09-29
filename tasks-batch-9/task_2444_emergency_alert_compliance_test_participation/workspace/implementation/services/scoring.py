"""Station scoring (calculation 6) and the two deterministic cascades
(PRD 2.10, 2.11, 3.8)."""

from datetime import timedelta
from decimal import Decimal

import clock
import store
from store import db, touch
from services import calculations as calc

NON_CLOSED_OUTAGE_STATES = ("OPEN", "REPAIR_IN_PROGRESS", "RESTORED", "VERIFICATION_FAILED")


# ---------------------------------------------------------------------------
# Scoring inputs (PRD 3.8 "the five inputs")
# ---------------------------------------------------------------------------

def accessible_source_count(station):
    plan = db.state_plans.get(station["state_plan_id"])
    required = set(plan["required_source_types"]) if plan else set()
    kinds = set()
    for a in store.assignments_of_station(station["id"]):
        if a["status"] == "ACTIVE" and a["source_type"] in required:
            kinds.add(a["source_type"])
    return len(kinds)


def silent_assignment_count(station):
    return sum(
        1 for a in store.assignments_of_station(station["id"]) if a["status"] == "SILENT"
    )


def penalty_points_total(station):
    total = Decimal("0.00")
    for f in store.filings_of_station(station["id"]):
        if f["status"] in ("SUBMITTED", "ACCEPTED"):
            total += f["penalty_points"]
    return calc.r2(total)


def outage_breach_count(station):
    count = 0
    for o in store.outages_of_station(station["id"]):
        if o["obligation_breached"] and o["status"] in NON_CLOSED_OUTAGE_STATES:
            count += 1
    return count


def unfiled_test_count(station):
    return sum(
        1 for t in store.test_events_of_station(station["id"])
        if t["status"] == "FAILED_UNFILED"
    )


def certified_eligible(station):
    now = clock.now()
    lo = now - timedelta(days=calc.CERTIFICATION_WINDOW_DAYS)
    for f in store.filings_of_station(station["id"]):
        if f["status"] != "ACCEPTED":
            continue
        filed_at = f["filed_at"]
        if filed_at is not None and lo <= filed_at <= now:
            return True
    return False


def missing_source_count(station):
    plan = db.state_plans.get(station["state_plan_id"])
    required = plan["required_source_count"] if plan else 0
    return max(0, required - station["accessible_source_count"])


def posture_for(score):
    if score >= calc.COMPLIANT_MIN_SCORE:
        return "COMPLIANT"
    if score >= calc.WATCH_MIN_SCORE:
        return "WATCH"
    return "SUSPENDED_FILINGS"


def score_breakdown(station):
    """Compute the variant and score from the station's current derived fields."""
    plan = db.state_plans.get(station["state_plan_id"])
    required = plan["required_source_count"] if plan else 0
    missing = max(0, required - station["accessible_source_count"])

    d1 = Decimal(missing) * calc.MISSING_SOURCE_DEDUCTION
    d2 = Decimal(station["silent_assignment_count"]) * calc.SILENT_ASSIGNMENT_DEDUCTION
    d3 = calc.REVALIDATION_DEDUCTION if station["plan_revalidation_required"] else Decimal("0")
    d4 = Decimal(outage_breach_count(station)) * calc.OUTAGE_BREACH_DEDUCTION
    d5 = Decimal(unfiled_test_count(station)) * calc.UNFILED_TEST_DEDUCTION
    d6 = Decimal(station["penalty_points_total"])

    if certified_eligible(station):
        variant = "CERTIFIED"
        raw = calc.BASE_SCORE - d1 - d2 - d3 - d4 - d5 - d6
    else:
        variant = "PROVISIONAL"
        raw = calc.BASE_SCORE - d1 - d2 - d3 - d4

    score = calc.r2(max(Decimal("0.00"), raw))
    return variant, score


# ---------------------------------------------------------------------------
# The station recompute event (PRD 2.10 / 3.8)
# ---------------------------------------------------------------------------

def recompute_station(station, log_review=False):
    now = clock.now()

    if log_review:
        # --- phase 1: silence sweep ---------------------------------------
        horizon = now - timedelta(days=calc.SILENCE_MAX_DAYS)
        for a in store.assignments_of_station(station["id"]):
            if a["status"] != "ACTIVE":
                continue
            evidence = a["last_receipt_at"] if a["last_receipt_at"] is not None else a["created_at"]
            if evidence < horizon:
                a["status"] = "SILENT"
                a["silence_flagged_at"] = now
                touch(a)

        # --- phase 2: unfiled sweep ---------------------------------------
        for t in store.test_events_of_station(station["id"]):
            if t["status"] in ("READY", "LOGGED") and t["filing_deadline_at"] < now:
                t["status"] = "FAILED_UNFILED"
                touch(t)

    # --- phase 3: derived-field refresh -----------------------------------
    station["accessible_source_count"] = accessible_source_count(station)
    station["silent_assignment_count"] = silent_assignment_count(station)
    station["penalty_points_total"] = penalty_points_total(station)

    # --- phase 4: variant, score, posture ---------------------------------
    variant, score = score_breakdown(station)
    previous_posture = station["compliance_posture"]
    station["compliance_score"] = score
    station["compliance_variant_applied"] = variant
    station["compliance_posture"] = posture_for(score)
    if log_review:
        station["last_log_review_at"] = now
    touch(station)

    # Entry into SUSPENDED_FILINGS reverts READY test events (outage cascade hop 4)
    if station["compliance_posture"] == "SUSPENDED_FILINGS" and previous_posture != "SUSPENDED_FILINGS":
        for t in store.test_events_of_station(station["id"]):
            if t["status"] == "READY":
                t["status"] = "READINESS_PENDING"
                t["readiness_score"] = None
                t["readiness_evaluated_at"] = None
                touch(t)

    return station


# ---------------------------------------------------------------------------
# The outage cascade (PRD 2.11) — four hops
# ---------------------------------------------------------------------------

def outage_cascade(device):
    # hop 1: the referenced device transitions to FAILED from REGISTERED or READY
    if device["status"] in ("REGISTERED", "READY"):
        device["status"] = "FAILED"
        touch(device)
        # hop 2: that device's ACTIVE/SILENT assignments -> SUSPENDED
        for a in store.assignments_of_device(device["id"]):
            if a["status"] in ("ACTIVE", "SILENT"):
                a["status"] = "SUSPENDED"
                touch(a)

    # hop 3 (+ hop 4 inside): station recompute
    station = db.stations.get(device["station_id"])
    if station is not None:
        recompute_station(station)


# ---------------------------------------------------------------------------
# The plan-supersede cascade (PRD 2.11) — three hops
# ---------------------------------------------------------------------------

def plan_supersede_cascade(activated_plan):
    now = clock.now()
    for other in store.ordered(list(db.state_plans.values())):
        if other["id"] == activated_plan["id"]:
            continue
        if other["state_code"] != activated_plan["state_code"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        # hop 1
        other["status"] = "SUPERSEDED"
        other["superseded_at"] = now
        touch(other)
        # hop 2
        for st in store.stations_of_plan(other["id"]):
            flipped = not st["plan_revalidation_required"]
            st["plan_revalidation_required"] = True
            recompute_station(st)
            # hop 3 — only when the flag flipped false -> true
            if flipped:
                for ins in store.inspections_of_station(st["id"]):
                    if ins["status"] == "RESPONDED":
                        ins["status"] = "RESPONSE_DRAFTED"
                        ins["completeness_score"] = None
                        ins["responded_at"] = None
                        touch(ins)
