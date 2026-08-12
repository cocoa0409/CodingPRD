"""Read-time derivation (PRD 2.11) plus the graph-walk lookup helpers.

Nothing in this module writes.  Every figure listed in PRD 2.11 as "recomputed
on read" is computed here from live rows, never served from a write-time cache.
"""

from core import clock, db
from core.constants import (
    BILLABLE_WORKFLOW_STATUSES,
    COUNTED_STOP_STATUSES,
    ROUTINE_READ_WEIGHT,
    STAT_READ_WEIGHT,
)
from services.timecalc import wall_minutes_between


# --------------------------------------------------------------------------
# graph walks
# --------------------------------------------------------------------------

def referral_of_appointment(appt):
    if appt is None:
        return None
    return db.get("referrals", appt.get("referral_id"))


def appointment_of_study(study):
    if study is None:
        return None
    return db.get("appointments", study.get("appointment_id"))


def referral_of_study(study):
    return referral_of_appointment(appointment_of_study(study))


def clinic_id_of_study(study):
    ref = referral_of_study(study)
    return ref.get("clinic_id") if ref else None


def clinic_of_study(study):
    cid = clinic_id_of_study(study)
    return db.get("clinics", cid) if cid else None


def stop_of_appointment(appt):
    if appt is None:
        return None
    return db.get("route_stops", appt.get("route_stop_id"))


def stop_of_study(study):
    return stop_of_appointment(appointment_of_study(study))


def route_of_stop(stop):
    if stop is None:
        return None
    return db.get("routes", stop.get("route_id"))


def route_of_study(study):
    return route_of_stop(stop_of_study(study))


def studies_of_appointment(appt):
    return db.sort_rows(db.where("studies", appointment_id=appt["id"]))


def appointments_of_stop(stop):
    return db.sort_rows(db.where("appointments", route_stop_id=stop["id"]))


def studies_at_stop(stop):
    """Every study whose appointment is bound to this stop, created_at ASC."""
    if stop is None:
        return []
    appt_ids = {a["id"] for a in db.where("appointments", route_stop_id=stop["id"])}
    rows = [s for s in db.all_rows("studies") if s.get("appointment_id") in appt_ids]
    return db.sort_rows(rows)


def stops_of_route(route):
    return db.sort_rows(db.where("route_stops", route_id=route["id"]))


# --------------------------------------------------------------------------
# ClinicContract
# --------------------------------------------------------------------------

def contract_status(contract):
    """EXPIRED / SUSPENDED / ACTIVE, computed against the logical clock."""
    now = clock.now()
    vf = contract.get("valid_from")
    vu = contract.get("valid_until")
    if vf is None or vu is None:
        return "EXPIRED"
    if now >= vu or now < vf:
        return "EXPIRED"
    if contract.get("suspended"):
        return "SUSPENDED"
    return "ACTIVE"


def contract_consumed(contract):
    entries = db.where("block_ledger_entries", contract_id=contract["id"])
    return -1 * sum(e["delta_studies"] for e in entries)


def contract_remaining(contract):
    return contract.get("block_purchased_studies", 0) - contract_consumed(contract)


def active_contracts_for_clinic(clinic_id):
    return [
        c
        for c in db.sort_rows(db.where("contracts", clinic_id=clinic_id))
        if contract_status(c) == "ACTIVE"
    ]


# --------------------------------------------------------------------------
# Equipment
# --------------------------------------------------------------------------

def calibration_status(equipment):
    """QUARANTINED > UNCALIBRATED > EXPIRED > VALID, in that fixed test order."""
    if equipment.get("quarantined_at") is not None:
        return "QUARANTINED"
    if equipment.get("calibration_valid_from") is None:
        return "UNCALIBRATED"
    now = clock.now()
    if now < equipment["calibration_valid_from"]:
        return "EXPIRED"
    if now >= equipment["calibration_valid_until"]:
        return "EXPIRED"
    return "VALID"


# --------------------------------------------------------------------------
# Route / RouteStop
# --------------------------------------------------------------------------

def counted_stops(route):
    return [
        s
        for s in stops_of_route(route)
        if s["status"] in COUNTED_STOP_STATUSES
    ]


def stop_actual_service_minutes(stop):
    if stop.get("departed_at") is None or stop.get("arrived_at") is None:
        return 0
    return wall_minutes_between(stop["arrived_at"], stop["departed_at"])


def route_stop_count(route):
    return len(counted_stops(route))


def route_planned_occupied_minutes(route):
    return sum(
        s["drive_minutes_from_prev"] + s["service_minutes"] for s in counted_stops(route)
    )


def route_actual_occupied_minutes(route):
    return sum(
        s["drive_minutes_from_prev"] + stop_actual_service_minutes(s)
        for s in stops_of_route(route)
        if s["status"] == "SERVICED"
    )


def route_slack_minutes(route):
    span = route["shift_end_minute"] - route["shift_start_minute"]
    return span - route_planned_occupied_minutes(route)


def stop_sequence(stop):
    """1-based position by planned_arrival_minute ASC, created_at ASC.

    BUMPED and CANCELLED stops keep whatever sequence they last held and are
    skipped by the renumbering (PRD 3.3), so their stored `_sequence` is served.
    """
    if stop["status"] not in COUNTED_STOP_STATUSES:
        return stop.get("_sequence")
    route = route_of_stop(stop)
    if route is None:
        return stop.get("_sequence")
    ordered = sorted(
        counted_stops(route),
        key=lambda s: (s["planned_arrival_minute"], s["created_at"], s["_seq"]),
    )
    for idx, s in enumerate(ordered, start=1):
        if s["id"] == stop["id"]:
            return idx
    return stop.get("_sequence")


def resequence_route(route):
    """Persist the derived sequence so BUMPED/CANCELLED stops can keep theirs."""
    if route is None:
        return
    ordered = sorted(
        counted_stops(route),
        key=lambda s: (s["planned_arrival_minute"], s["created_at"], s["_seq"]),
    )
    for idx, s in enumerate(ordered, start=1):
        s["_sequence"] = idx


# --------------------------------------------------------------------------
# Appointment disposition counters
# --------------------------------------------------------------------------

def appointment_counts(appt):
    studies = studies_of_appointment(appt)
    pending = acquired = cancelled = not_performed = 0
    for s in studies:
        ws = s["workflow_status"]
        if ws in ("ORDERED", "REPEAT_PENDING"):
            pending += 1
        elif ws in BILLABLE_WORKFLOW_STATUSES:
            acquired += 1
        elif ws == "CANCELLED":
            cancelled += 1
        elif ws == "NOT_PERFORMED":
            not_performed += 1
    return {
        "ordered_studies_count": len(studies),
        "pending_studies_count": pending,
        "acquired_studies_count": acquired,
        "cancelled_studies_count": cancelled,
        "not_performed_studies_count": not_performed,
    }


# --------------------------------------------------------------------------
# Specialist load figures
# --------------------------------------------------------------------------

def specialist_open_read_count(specialist):
    return len(
        [
            a
            for a in db.where("read_assignments", specialist_id=specialist["id"])
            if a["status"] in ("OFFERED", "ACCEPTED")
        ]
    )


def specialist_workload_score(specialist):
    if specialist.get("stat_eligible"):
        counted_statuses = ("OFFERED", "ACCEPTED")
    else:
        counted_statuses = ("ACCEPTED",)
    score = 0
    for a in db.where("read_assignments", specialist_id=specialist["id"]):
        if a["status"] not in counted_statuses:
            continue
        study = db.get("studies", a["study_id"])
        if study is None:
            continue
        score += STAT_READ_WEIGHT if study["priority"] == "STAT" else ROUTINE_READ_WEIGHT
    return score


# --------------------------------------------------------------------------
# Invoice
# --------------------------------------------------------------------------

def invoice_active_lines(invoice):
    return [
        l
        for l in db.where("charge_lines", invoice_id=invoice["id"])
        if l["status"] == "ACTIVE"
    ]


def invoice_total_cents(invoice):
    if invoice["status"] == "FINALIZED":
        return invoice.get("finalized_total_cents") or 0
    return sum(l["amount_cents"] for l in invoice_active_lines(invoice))


def invoice_posted_study_count(invoice):
    return len({l["study_id"] for l in invoice_active_lines(invoice)})


# --------------------------------------------------------------------------
# Billable set at a stop (PRD 3.9 step 3)
# --------------------------------------------------------------------------

def billable_set_at_stop(stop):
    """created_at ASC list of the studies sharing this stop's trip fee."""
    if stop is None:
        return []
    out = [
        s
        for s in studies_at_stop(stop)
        if s["workflow_status"] in BILLABLE_WORKFLOW_STATUSES
        and s["billing_status"] != "NON_BILLABLE"
    ]
    return out
