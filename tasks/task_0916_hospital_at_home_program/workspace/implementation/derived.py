"""Every ``source: computed`` field, evaluated live from the store.

Keeping the roll-ups derived rather than cached is what makes the three
conservation invariants of PRD 2.8 hold by construction.
"""

from datetime import timedelta

import calc
import clock
from store import DB, ordered

QUALIFYING_IN_PERSON_VISIT_TYPES = ("RN_IN_PERSON", "PARAMEDIC_IN_PERSON")
PHYSICIAN_VISIT_TYPES = ("PHYSICIAN_IN_PERSON", "PHYSICIAN_TELEHEALTH")
ATTESTED_STATES = ("ATTESTED", "AMENDED")
TERMINAL_ESCALATION_STATES = ("RESOLVED", "BED_RETURN_CONVERTED")
TERMINAL_DELIVERY_STATES = ("DELIVERED", "FAILED", "CANCELLED")


# --- helpers --------------------------------------------------------------

def episode_visits(episode_id):
    return [v for v in DB.visits.values() if v["episode_id"] == episode_id]


def episode_records(episode_id):
    rows = [r for r in DB.compliance_days.values() if r["episode_id"] == episode_id]
    return sorted(rows, key=lambda r: (r["service_date"], r["_seq"]))


def find_record(episode_id, service_date):
    for record in DB.compliance_days.values():
        if record["episode_id"] == episode_id and record["service_date"] == service_date:
            return record
    return None


def episode_meal_plans(episode_id):
    return ordered([p for p in DB.meal_plans.values() if p["episode_id"] == episode_id])


def episode_escalations(episode_id):
    return ordered([e for e in DB.escalations.values() if e["episode_id"] == episode_id])


def episode_delivery_orders(episode_id):
    return ordered([o for o in DB.delivery_orders.values() if o["episode_id"] == episode_id])


def episode_reservations(episode_id):
    return ordered([r for r in DB.reservations.values() if r["episode_id"] == episode_id])


def unit_reservations(unit_id):
    return ordered([r for r in DB.reservations.values() if r["unit_id"] == unit_id])


def kit_components(kit_id):
    return ordered([c for c in DB.components.values() if c["kit_id"] == kit_id])


def episode_deployed_kit(episode_id):
    for kit in ordered(DB.kits.values()):
        if kit["assigned_episode_id"] == episode_id and kit["status"] == "DEPLOYED":
            return kit
    return None


# --- DailyComplianceRecord computed fields --------------------------------

def qualified_in_person_visit_count(episode_id, service_date):
    total = 0
    for visit in episode_visits(episode_id):
        if visit["service_date"] != service_date:
            continue
        if visit["visit_type"] not in QUALIFYING_IN_PERSON_VISIT_TYPES:
            continue
        if visit["scheduling_status"] != "COMPLETED":
            continue
        if visit["attestation_status"] not in ATTESTED_STATES:
            continue
        total += 1
    return total


def physician_eval_present(episode_id, service_date):
    for visit in episode_visits(episode_id):
        if visit["service_date"] != service_date:
            continue
        if visit["visit_type"] not in PHYSICIAN_VISIT_TYPES:
            continue
        if visit["scheduling_status"] != "COMPLETED":
            continue
        if visit["attestation_status"] not in ATTESTED_STATES:
            continue
        return True
    return False


def monitoring_lapse_minutes(episode_id, service_date):
    """Clip every intersecting gap to the UTC day window, merge, floor to minutes."""
    window_start = clock.date_str_to_dt(service_date)
    window_end = window_start + timedelta(days=1)
    candidates = []
    for lapse in DB.lapses.values():
        if lapse["episode_id"] != episode_id:
            continue
        start = lapse["_gap_start_dt"]
        end = lapse["_gap_end_dt"]
        if start >= window_end or end <= window_start:
            continue
        clipped_start = start if start > window_start else window_start
        clipped_end = end if end < window_end else window_end
        candidates.append((clipped_start, clipped_end, lapse["_created_dt"], lapse["_seq"]))
    candidates.sort(key=lambda item: (item[0], item[2], item[3]))
    return calc.merge_lapse_minutes([(item[0], item[1]) for item in candidates])


def score_record(record):
    """Run the daily verdict for a record under its episode's program track."""
    episode = DB.episodes[record["episode_id"]]
    return calc.score_day(
        episode["program_track"],
        qualified_in_person_visit_count(record["episode_id"], record["service_date"]),
        physician_eval_present(record["episode_id"], record["service_date"]),
        monitoring_lapse_minutes(record["episode_id"], record["service_date"]),
        record["kit_deployed_all_day"],
    )


# --- Episode day ledger ---------------------------------------------------

def episode_day_ledger(episode_id):
    records = episode_records(episode_id)
    service = len(records)
    billable = len([r for r in records if r["status"] == "COMPLIANT"])
    carved = len([r for r in records if r["status"] == "CARVED_OUT"])
    pending = len([r for r in records if r["status"] == "PENDING"])
    return service, billable, carved, pending


def episode_billable_day_count(episode_id):
    return episode_day_ledger(episode_id)[1]


def episode_reimbursement_amount(episode):
    return calc.episode_reimbursement(
        episode["program_track"], episode_billable_day_count(episode["id"])
    )


def episode_travel_total(episode_id):
    amounts = []
    for visit in episode_visits(episode_id):
        if visit["scheduling_status"] != "COMPLETED":
            continue
        if visit["attestation_status"] not in ATTESTED_STATES:
            continue
        amounts.append(visit["travel_payment_usd"])
    return calc.travel_total(amounts)


def episode_open_escalation_count(episode_id):
    return len([
        e for e in DB.escalations.values()
        if e["episode_id"] == episode_id and e["status"] not in TERMINAL_ESCALATION_STATES
    ])


# --- MealPlan accrual -----------------------------------------------------

def meal_plan_credited_day_count(plan):
    eligible = 0
    for record in episode_records(plan["episode_id"]):
        if record["status"] not in ("PENDING", "COMPLIANT"):
            continue
        if record["service_date"] < plan["activated_on_date"]:
            continue
        eligible += 1
    return max(0, eligible - plan["suspension_day_count"])


def meal_plan_credit_total(plan):
    if plan["status"] == "CANCELLED":
        return calc.ZERO
    episode = DB.episodes[plan["episode_id"]]
    return calc.meal_credit(episode["program_track"], meal_plan_credited_day_count(plan))


def episode_meal_credit_total(episode_id):
    total = calc.ZERO
    for plan in episode_meal_plans(episode_id):
        if plan["status"] not in ("ACTIVE", "SUSPENDED", "COMPLETED"):
            continue
        total = total + meal_plan_credit_total(plan)
    return calc.money(total)


# --- DeviceKit census -----------------------------------------------------

def kit_component_count(kit_id):
    return len([c for c in DB.components.values() if c["kit_id"] == kit_id])


def kit_unreconciled_component_count(kit_id):
    return len([
        c for c in DB.components.values()
        if c["kit_id"] == kit_id and c["reconciliation_status"] == "PENDING_RECONCILIATION"
    ])


def kit_census():
    kits = list(DB.kits.values())
    return {
        "total_kits": len(kits),
        "available_count": len([k for k in kits if k["status"] == "AVAILABLE"]),
        "deployed_count": len([k for k in kits if k["status"] == "DEPLOYED"]),
        "in_refurb_count": len([k for k in kits if k["status"] == "IN_REFURB"]),
        "retired_count": len([k for k in kits if k["status"] == "RETIRED"]),
    }


# --- InpatientUnit bed census ---------------------------------------------

def unit_bed_census(unit):
    reservations = unit_reservations(unit["id"])
    held = len([r for r in reservations if r["status"] == "HELD"])
    occupied = len([r for r in reservations if r["status"] == "OCCUPIED"])
    return held, occupied, unit["total_beds"] - held - occupied


# --- version-bump fingerprints -------------------------------------------

def episode_fingerprint(episode):
    service, billable, carved, pending = episode_day_ledger(episode["id"])
    return (
        service,
        billable,
        carved,
        pending,
        str(episode_reimbursement_amount(episode)),
        str(episode_meal_credit_total(episode["id"])),
        str(episode_travel_total(episode["id"])),
        episode_open_escalation_count(episode["id"]),
    )


def unit_fingerprint(unit):
    return unit_bed_census(unit)
