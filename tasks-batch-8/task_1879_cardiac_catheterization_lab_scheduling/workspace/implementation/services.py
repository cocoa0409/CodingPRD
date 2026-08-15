"""Domain logic: calculations, selectors, cascades, and serializers."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import STORE, logical_now, next_seq, tick
from helpers import fmt_ms, fmt_s

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3 / PRD §3)
# ---------------------------------------------------------------------------
BASE_MINUTES = {
    "DIAGNOSTIC_CATHETERIZATION": 45,
    "PCI": 90,
    "STEMI_PCI": 75,
    "DEVICE_IMPLANT": 60,
    "EP_STUDY": 120,
}
TURNOVER_BUFFER = timedelta(minutes=20)
RECOVERY_MINUTES = timedelta(minutes=90)
RADIATION_ALERT_MGY = Decimal("5000.0")
SUBMISSION_WINDOW = timedelta(days=30)
CONTRAST_MULTIPLIER = Decimal("5.0")
CONTRAST_CAP_ML = Decimal("300.0")

REGISTRY_NAMES = {
    "DIAGNOSTIC_CATHETERIZATION": "NCDR_CATHPCI",
    "PCI": "NCDR_CATHPCI",
    "STEMI_PCI": "NCDR_CATHPCI",
    "DEVICE_IMPLANT": "NCDR_ICD",
    "EP_STUDY": "NCDR_EP",
}

NON_TERMINAL_CASE_STATUSES = ("POSTED", "SCHEDULED", "BUMPED", "IN_PROGRESS")
TERMINAL_CASE_STATUSES = ("COMPLETED", "CANCELLED")


def D(x):
    return x if isinstance(x, Decimal) else Decimal(x)


def round1(x):
    return D(x).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def round2(x):
    return D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------

def new_entity():
    ts = fmt_ms(tick())
    return {
        "id": None,  # caller assigns
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    """Every modification bumps version and refreshes updated_at (PRD 2.4/2.9)."""
    entity["version"] += 1
    entity["updated_at"] = fmt_ms(tick())


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def compute_contrast_limit_ml(weight_kg, serum_creatinine):
    raw = CONTRAST_MULTIPLIER * D(weight_kg) / D(serum_creatinine)
    return round1(min(raw, CONTRAST_CAP_ML))


def compute_case_end(procedure_type, priority, equipment_needs, scheduled_start):
    """estimated_case_window: base + setup; STEMI priority takes expedited branch."""
    base = BASE_MINUTES[procedure_type]
    if priority == "STEMI":
        setup = 0
    else:
        n = len(equipment_needs)
        setup = 0 if n == 0 else (15 if n <= 2 else 30)
    return scheduled_start + timedelta(minutes=base + setup)


def _buffered_overlap(c_start, c_end, n_start, n_end):
    """room_window_conflict: half-open with 20-minute turnover buffer."""
    return n_start < c_end + TURNOVER_BUFFER and c_start < n_end + TURNOVER_BUFFER


def room_window_conflict(room_id, new_start, new_end):
    for c in STORE["cases"].values():
        if c["lab_id"] == room_id and c["status"] in ("SCHEDULED", "IN_PROGRESS"):
            if _buffered_overlap(
                c["scheduled_start"], c["scheduled_end"], new_start, new_end
            ):
                return True
    return False


def staff_window_conflict(staff_id, new_start, new_end):
    """Strict half-open [start, end), no buffer; adjacency allowed."""
    for a in STORE["assignments"].values():
        if a["staff_id"] != staff_id or a["status"] != "ASSIGNED":
            continue
        case = STORE["cases"].get(a["case_id"])
        if case is None or case["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if new_start < a["window_end"] and a["window_start"] < new_end:
            return True
    return False


def lot_allocated_units(lot_id):
    return sum(
        u["quantity"]
        for u in STORE["usages"].values()
        if u["lot_id"] == lot_id and u["status"] == "RESERVED"
    )


def derive_lot_status(available_units, reorder_threshold):
    if available_units == 0:
        return "DEPLETED"
    if available_units < reorder_threshold:
        return "LOW_STOCK"
    return "ACTIVE"


def recompute_lot(lot, bump_version=True):
    alloc = lot_allocated_units(lot["id"])
    lot["allocated_units"] = alloc
    lot["available_units"] = lot["quantity_on_hand"] - alloc
    lot["status"] = derive_lot_status(lot["available_units"], lot["reorder_threshold"])
    if bump_version:
        touch(lot)


def recompute_case_doses(case, bump_version=True):
    """Recompute cumulative contrast/radiation over ACTIVE records.

    Radiation sums per-record rounded totals (rounding order pinned, PRD 3.6).
    radiation_alert latches and never auto-clears.
    """
    contrast = Decimal("0")
    radiation = Decimal("0")
    for r in STORE["dose_records"].values():
        if r["case_id"] != case["id"] or r["status"] != "ACTIVE":
            continue
        if r["record_type"] == "CONTRAST":
            contrast += D(r["contrast_ml"])
        else:
            radiation += D(r["record_total_mgy"])
    case["cumulative_contrast_ml"] = round1(contrast)
    case["cumulative_radiation_mgy"] = round2(radiation)
    if case["cumulative_radiation_mgy"] >= RADIATION_ALERT_MGY:
        case["radiation_alert"] = True
    if bump_version:
        touch(case)


def compute_completeness_pct(case):
    elective = case["priority"] == "ELECTIVE"
    total = 7 if elective else 6
    present = 0
    if case["patient_mrn"]:
        present += 1
    if case["performing_physician_id"]:
        present += 1
    if case["actual_start"] is not None:
        present += 1
    if case["actual_end"] is not None:
        present += 1
    has_active_radiation = any(
        r["case_id"] == case["id"]
        and r["record_type"] == "RADIATION"
        and r["status"] == "ACTIVE"
        for r in STORE["dose_records"].values()
    )
    if has_active_radiation:
        present += 1
    has_reserved_usage = any(
        u["case_id"] == case["id"] and u["status"] == "RESERVED"
        for u in STORE["usages"].values()
    )
    if not has_reserved_usage:
        present += 1
    if elective and case["auc_status"] == "DOCUMENTED":
        present += 1
    pct = (Decimal(present) * Decimal(100) / Decimal(total)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    return pct


# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------

def select_recovery_bed():
    """bed_selector: AVAILABLE beds, created_at ASC, ties by bed_label ASC."""
    candidates = [b for b in STORE["beds"].values() if b["status"] == "AVAILABLE"]
    if not candidates:
        return None
    candidates.sort(key=lambda b: (b["_seq"], b["bed_label"]))
    return candidates[0]


def select_stemi_room(equipment_needs, start, end):
    """bump_room_selector.

    Eligible: ACTIVE, equipment subset, no IN_PROGRESS case, no overlapping
    SCHEDULED STEMI/URGENT case. Ranked by fewest overlapping SCHEDULED
    ELECTIVE victims, ties by room created_at ASC. Returns (room, victims).
    """
    eligible = []
    for room in STORE["rooms"].values():
        if room["status"] != "ACTIVE":
            continue
        if not set(equipment_needs).issubset(set(room["equipment_profile"])):
            continue
        blocked = False
        victims = []
        for c in STORE["cases"].values():
            if c["lab_id"] != room["id"]:
                continue
            if c["status"] == "IN_PROGRESS":
                blocked = True
                break
            if c["status"] == "SCHEDULED":
                overlaps = _buffered_overlap(
                    c["scheduled_start"], c["scheduled_end"], start, end
                )
                if c["priority"] in ("STEMI", "URGENT") and overlaps:
                    blocked = True
                    break
                if c["priority"] == "ELECTIVE" and overlaps:
                    victims.append(c)
        if blocked:
            continue
        eligible.append((len(victims), room["_seq"], room, victims))
    if not eligible:
        return None
    eligible.sort(key=lambda t: (t[0], t[1]))
    _, _, room, victims = eligible[0]
    victims.sort(key=lambda c: c["_seq"])
    return room, victims


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def release_bed_for_case(case_id):
    for b in STORE["beds"].values():
        if b["held_case_id"] == case_id and b["status"] == "RESERVED":
            b["status"] = "AVAILABLE"
            b["held_case_id"] = None
            b["window_start"] = None
            b["window_end"] = None
            touch(b)


def release_assignments_for_case(case_id):
    for a in STORE["assignments"].values():
        if a["case_id"] == case_id and a["status"] == "ASSIGNED":
            a["status"] = "RELEASED"
            touch(a)


def release_usages_for_case(case_id):
    for u in STORE["usages"].values():
        if u["case_id"] == case_id and u["status"] == "RESERVED":
            u["status"] = "RELEASED"
            touch(u)
            recompute_lot(STORE["lots"][u["lot_id"]])


def bump_case(case):
    """SCHEDULED -> BUMPED with full release cascade (PRD 3.2)."""
    case["status"] = "BUMPED"
    case["bump_count"] += 1
    case["lab_id"] = None
    case["scheduled_start"] = None
    case["scheduled_end"] = None
    touch(case)
    release_bed_for_case(case["id"])
    release_assignments_for_case(case["id"])
    release_usages_for_case(case["id"])


def reserve_bed_for_case(bed, case):
    bed["status"] = "RESERVED"
    bed["held_case_id"] = case["id"]
    bed["window_start"] = case["scheduled_end"]
    bed["window_end"] = case["scheduled_end"] + RECOVERY_MINUTES
    touch(bed)


def occupy_bed_for_case(case):
    for b in STORE["beds"].values():
        if b["held_case_id"] == case["id"] and b["status"] == "RESERVED":
            b["status"] = "OCCUPIED"
            b["window_start"] = case["actual_end"]
            b["window_end"] = case["actual_end"] + RECOVERY_MINUTES
            touch(b)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _num(x):
    return float(x) if isinstance(x, Decimal) else x


def room_out(r):
    return {
        "id": r["id"],
        "room_name": r["room_name"],
        "equipment_profile": list(r["equipment_profile"]),
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def staff_out(s):
    return {
        "id": s["id"],
        "full_name": s["full_name"],
        "staff_role": s["staff_role"],
        "credentials": list(s["credentials"]),
        "is_active": s["is_active"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def case_out(c):
    return {
        "id": c["id"],
        "patient_mrn": c["patient_mrn"],
        "procedure_type": c["procedure_type"],
        "priority": c["priority"],
        "performing_physician_id": c["performing_physician_id"],
        "weight_kg": _num(c["weight_kg"]),
        "serum_creatinine": _num(c["serum_creatinine"]),
        "equipment_needs": list(c["equipment_needs"]),
        "lab_id": c["lab_id"],
        "scheduled_start": fmt_s(c["scheduled_start"]) if c["scheduled_start"] else None,
        "scheduled_end": fmt_s(c["scheduled_end"]) if c["scheduled_end"] else None,
        "actual_start": fmt_s(c["actual_start"]) if c["actual_start"] else None,
        "actual_end": fmt_s(c["actual_end"]) if c["actual_end"] else None,
        "contrast_limit_ml": _num(c["contrast_limit_ml"]),
        "cumulative_contrast_ml": _num(c["cumulative_contrast_ml"]),
        "cumulative_radiation_mgy": _num(c["cumulative_radiation_mgy"]),
        "radiation_alert": c["radiation_alert"],
        "bump_count": c["bump_count"],
        "auc_status": c["auc_status"],
        "auc_score": c["auc_score"],
        "auc_criterion_code": c["auc_criterion_code"],
        "ordering_physician_id": c["ordering_physician_id"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def assignment_out(a):
    return {
        "id": a["id"],
        "case_id": a["case_id"],
        "staff_id": a["staff_id"],
        "role_in_case": a["role_in_case"],
        "window_start": fmt_s(a["window_start"]),
        "window_end": fmt_s(a["window_end"]),
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def lot_out(lot):
    return {
        "id": lot["id"],
        "device_type": lot["device_type"],
        "manufacturer": lot["manufacturer"],
        "model_number": lot["model_number"],
        "lot_number": lot["lot_number"],
        "ownership": lot["ownership"],
        "quantity_on_hand": lot["quantity_on_hand"],
        "allocated_units": lot["allocated_units"],
        "available_units": lot["available_units"],
        "reorder_threshold": lot["reorder_threshold"],
        "expiration_date": fmt_s(lot["expiration_date"]),
        "status": lot["status"],
        "created_at": lot["created_at"],
        "updated_at": lot["updated_at"],
        "version": lot["version"],
    }


def usage_out(u):
    return {
        "id": u["id"],
        "case_id": u["case_id"],
        "lot_id": u["lot_id"],
        "quantity": u["quantity"],
        "status": u["status"],
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
    }


def dose_record_out(r):
    return {
        "id": r["id"],
        "case_id": r["case_id"],
        "record_type": r["record_type"],
        "contrast_ml": _num(r["contrast_ml"]) if r["contrast_ml"] is not None else None,
        "fluoroscopy_mgy": _num(r["fluoroscopy_mgy"]) if r["fluoroscopy_mgy"] is not None else None,
        "cine_mgy": _num(r["cine_mgy"]) if r["cine_mgy"] is not None else None,
        "record_total_mgy": _num(r["record_total_mgy"]),
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def bed_out(b):
    return {
        "id": b["id"],
        "bed_label": b["bed_label"],
        "status": b["status"],
        "held_case_id": b["held_case_id"],
        "window_start": fmt_s(b["window_start"]) if b["window_start"] else None,
        "window_end": fmt_s(b["window_end"]) if b["window_end"] else None,
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def submission_out(s):
    return {
        "id": s["id"],
        "case_id": s["case_id"],
        "registry_name": s["registry_name"],
        "completeness_pct": _num(s["completeness_pct"]),
        "submitted_at": fmt_s(s["submitted_at"]) if s["submitted_at"] else None,
        "decided_at": fmt_s(s["decided_at"]) if s["decided_at"] else None,
        "rejection_reason": s["rejection_reason"],
        "correction_note": s["correction_note"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }
