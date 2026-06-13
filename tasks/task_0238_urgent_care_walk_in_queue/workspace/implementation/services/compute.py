"""Derived/computed value calculations (SCAFFOLD §1.3)."""
import math
from decimal import Decimal, ROUND_HALF_UP

from db import db, touch


def recompute_clinic(clinic):
    """A posture/depth/rooms recompute counts as a clinic mutation
    (PRD §2.4, §2.9): bump updated_at + version."""
    touch(clinic)

ACTIVE_STATES = {"WAITING", "TRIAGED", "IN_REGISTRATION", "READY_FOR_PROVIDER"}
AHEAD_STATES = {"TRIAGED", "IN_REGISTRATION", "READY_FOR_PROVIDER"}
UNTRIAGED_ESI_SENTINEL = 5
DEFAULT_ESI_MINUTES = {"1": 40, "2": 30, "3": 20, "4": 12, "5": 8}


# --------------------------------------------------------------------------
# Posture & depth (clinic_posture)
# --------------------------------------------------------------------------
def active_queue_entries(clinic_id):
    return [
        q for q in db.queue_entries.values()
        if q["clinic_id"] == clinic_id and q["status"] in ACTIVE_STATES
    ]


def active_queue_depth(clinic_id):
    return len(active_queue_entries(clinic_id))


def compute_posture(clinic):
    depth = active_queue_depth(clinic["id"])
    if depth >= clinic["diversion_threshold"]:
        return "DIVERSION"
    if depth >= clinic["surge_threshold"]:
        return "SURGE"
    return "OPEN"


def rooms_occupied(clinic_id):
    return sum(
        1 for r in db.exam_rooms.values()
        if r["clinic_id"] == clinic_id and r["status"] == "OCCUPIED"
    )


# --------------------------------------------------------------------------
# Queue ordering (priority_rank)
# --------------------------------------------------------------------------
def _sort_key(q):
    if q["status"] == "WAITING" and q.get("esi_level") is None:
        esi = UNTRIAGED_ESI_SENTINEL
        second = q["created_at"]
    else:
        esi = q.get("esi_level") if q.get("esi_level") is not None else UNTRIAGED_ESI_SENTINEL
        second = q.get("triaged_at") or q["created_at"]
    return (esi, second, q["created_at"])


def ranked_active_entries(clinic_id):
    """Active entries sorted by priority (rank-1 first)."""
    entries = active_queue_entries(clinic_id)
    return sorted(entries, key=_sort_key)


def priority_rank(entry):
    """1-based rank of this entry among its clinic's active set, or None."""
    if entry["status"] not in ACTIVE_STATES:
        return None
    ordered = ranked_active_entries(entry["clinic_id"])
    for idx, q in enumerate(ordered):
        if q["id"] == entry["id"]:
            return idx + 1
    return None


# --------------------------------------------------------------------------
# Wait estimate (wait_estimate)
# --------------------------------------------------------------------------
def _effective_servers(clinic_id):
    return sum(
        1 for p in db.providers.values()
        if p["clinic_id"] == clinic_id and p["on_shift"]
    )


def _esi_minutes(clinic, esi_level):
    m = clinic.get("avg_provider_minutes_per_esi") or DEFAULT_ESI_MINUTES
    key = str(esi_level)
    if key in m:
        return m[key]
    return DEFAULT_ESI_MINUTES.get(key, 0)


def estimated_wait_minutes(entry):
    """Wait estimate for `entry`. RESERVED holds use the optimistic variant;
    active (triaged) entries use the conservative variant."""
    clinic = db.clinics.get(entry["clinic_id"])
    if clinic is None:
        return None

    status = entry["status"]
    if status not in ACTIVE_STATES and status != "RESERVED":
        return None

    servers = _effective_servers(entry["clinic_id"])
    if servers == 0:
        return None

    ordered = ranked_active_entries(entry["clinic_id"])

    if status == "RESERVED":
        # Optimistic: a RESERVED hold sits behind every active entry. The
        # ahead-set is every active entry in an AHEAD state; divisor is
        # servers + 1 (fast-track server assumption).
        ahead = [q for q in ordered if q["status"] in AHEAD_STATES]
        divisor = servers + 1
    else:
        my_rank = None
        for idx, q in enumerate(ordered):
            if q["id"] == entry["id"]:
                my_rank = idx + 1
                break
        if my_rank is None:
            return None
        ahead = [
            q for i, q in enumerate(ordered)
            if (i + 1) < my_rank and q["status"] in AHEAD_STATES
        ]
        divisor = servers

    work_ahead = sum(_esi_minutes(clinic, q["esi_level"]) for q in ahead)
    return math.ceil(work_ahead / divisor)


# --------------------------------------------------------------------------
# Billing (charge_total)
# --------------------------------------------------------------------------
def visit_charges_subtotal(visit_id):
    """Sum of non-voided VISIT-source charges on the visit."""
    total = 0
    for c in db.charges.values():
        if c["visit_id"] == visit_id and not c["voided"] and c["source_type"] == "VISIT":
            total += c["amount_cents"]
    return total


def _patient_coverage(patient_id):
    if patient_id is None:
        return None
    for cov in db.coverages.values():
        if cov["patient_id"] == patient_id:
            return cov
    return None


def round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_responsibility(visit):
    """Return (subtotal_cents, patient_responsibility_cents) per charge_total."""
    subtotal = visit_charges_subtotal(visit["id"])
    clinic_id = _clinic_for_visit(visit)
    clinic = db.clinics.get(clinic_id)
    discount = clinic["self_pay_discount_pct"] if clinic else 0
    coverage = _patient_coverage(visit.get("patient_id"))

    if coverage and coverage["coverage_type"] == "INSURANCE" and coverage["eligibility_status"] == "ELIGIBLE":
        responsibility = coverage.get("copay_cents") or 0
    else:
        # self-pay (or insurance fallback): discount then round once.
        discounted = Decimal(subtotal) * (Decimal(1) - Decimal(str(discount)))
        responsibility = round_half_up_cents(discounted)
    return subtotal, responsibility


def _clinic_for_visit(visit):
    qe = db.queue_entries.get(visit.get("queue_entry_id"))
    if qe:
        return qe["clinic_id"]
    return None
