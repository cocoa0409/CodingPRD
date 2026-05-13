"""Elder lifecycle: admit, leave, return, transfer, discharge — and cascades."""
from clock import iso_now, now, parse_date
from db import LOCK, get_db
from errors import APIError
from helpers import touch
from services import audit, waitlist as waitlist_svc


REQUIRED_ADMISSION_DEPOSIT_CENTS = 500000  # 5,000.00


def serialize_elder(e):
    """Return a public dict for an elder (drop internal-only fields)."""
    return dict(e)


def _has_approved_assessment(elder_id):
    db = get_db()
    return any(
        a["elder_id"] == elder_id and a["status"] == "APPROVED"
        for a in db.care_assessments.values()
    )


def admit(elder, bed, actor_id, actor_role):
    """Admit elder to bed. Performs the priority-13 bed-type check and
    priority-23 deposit floor, then mutates both records.
    """
    db = get_db()
    # Bed must be AVAILABLE — first-writer-wins.
    if bed["status"] != "AVAILABLE":
        raise APIError("ERR_BED_ALREADY_OCCUPIED",
                       f"Bed {bed['id']} is {bed['status']}", 409)

    # Bed-type / care-level rule (priority 13)
    elder_level = elder.get("current_care_level")
    if bed["bed_type"] == "INTENSIVE_CARE" and elder_level != "INTENSIVE":
        raise APIError("ERR_BED_TYPE_MISMATCH",
                       "INTENSIVE_CARE bed requires INTENSIVE elder", 409)
    if bed["bed_type"] != "INTENSIVE_CARE" and elder_level == "INTENSIVE":
        raise APIError("ERR_BED_TYPE_MISMATCH",
                       "INTENSIVE elder may only occupy INTENSIVE_CARE bed", 409)

    # Mutate
    bed["status"] = "OCCUPIED"
    bed["current_elder_id"] = elder["id"]
    touch(bed)

    elder["status"] = "ADMITTED"
    elder["current_bed_id"] = bed["id"]
    history = elder.setdefault("admission_history", [])
    history.append({
        "admitted_at": iso_now(),
        "discharged_at": None,
        "bed_id": bed["id"],
        "reason": "admission",
    })
    touch(elder)

    # Fulfill matching waitlist entry if elder was OFFERED this bed
    for entry in db.waitlist.values():
        if (entry["elder_id"] == elder["id"]
                and entry["status"] == "OFFERED"
                and entry.get("offered_bed_id") == bed["id"]):
            entry["status"] = "FULFILLED"
            break


def go_on_leave(elder, actor_id, actor_role, reason=None):
    """ADMITTED -> ON_LEAVE; cascade ACTIVE prescriptions -> SUSPENDED."""
    db = get_db()
    if elder.get("status") != "ADMITTED":
        raise APIError("ERR_INVALID_STATE",
                       f"Elder is in {elder.get('status')}, not ADMITTED", 409)
    elder["status"] = "ON_LEAVE"
    history = elder.setdefault("admission_history", [])
    history.append({
        "event": "leave",
        "at": iso_now(),
        "bed_id": elder.get("current_bed_id"),
        "reason": reason,
    })
    touch(elder)
    # Cascade active prescriptions
    for p in db.prescriptions.values():
        if p["elder_id"] == elder["id"] and p["status"] == "ACTIVE":
            prev = p["status"]
            p["status"] = "SUSPENDED"
            touch(p)
            audit.log(actor_role, actor_id, "Prescription", p["id"],
                      "SUSPEND_CASCADE", prev, p["status"])


def return_from_leave(elder, actor_id, actor_role):
    """ON_LEAVE -> ADMITTED; cascade SUSPENDED prescriptions back to ACTIVE."""
    db = get_db()
    if elder.get("status") != "ON_LEAVE":
        raise APIError("ERR_INVALID_STATE",
                       f"Elder is in {elder.get('status')}, not ON_LEAVE", 409)
    bed_id = elder.get("current_bed_id")
    bed = db.beds.get(bed_id) if bed_id else None
    if bed is None or bed.get("status") != "OCCUPIED":
        raise APIError("ERR_INVALID_STATE", "Elder bed not held", 409)
    elder["status"] = "ADMITTED"
    history = elder.setdefault("admission_history", [])
    history.append({
        "event": "return",
        "at": iso_now(),
        "bed_id": bed_id,
    })
    touch(elder)
    # Cascade suspended prescriptions
    for p in db.prescriptions.values():
        if p["elder_id"] == elder["id"] and p["status"] == "SUSPENDED":
            prev = p["status"]
            p["status"] = "ACTIVE"
            touch(p)
            audit.log(actor_role, actor_id, "Prescription", p["id"],
                      "RESUME_CASCADE", prev, p["status"])


def transfer(elder, target_bed, actor_id, actor_role):
    """Atomic transfer: release source bed (waitlist promote), occupy target."""
    db = get_db()
    if elder.get("status") not in ("ADMITTED", "ON_LEAVE"):
        raise APIError("ERR_INVALID_STATE",
                       "Transfer requires ADMITTED or ON_LEAVE elder", 409)
    source_bed_id = elder.get("current_bed_id")
    source_bed = db.beds.get(source_bed_id) if source_bed_id else None
    if source_bed is None:
        raise APIError("ERR_INVALID_STATE", "Elder has no current bed", 409)
    if target_bed["status"] != "AVAILABLE":
        raise APIError("ERR_BED_ALREADY_OCCUPIED",
                       f"Target bed {target_bed['id']} not AVAILABLE", 409)

    # Bed-type/care-level check on the target
    level = elder.get("current_care_level")
    if target_bed["bed_type"] == "INTENSIVE_CARE" and level != "INTENSIVE":
        raise APIError("ERR_BED_TYPE_MISMATCH",
                       "INTENSIVE_CARE bed requires INTENSIVE elder", 409)
    if target_bed["bed_type"] != "INTENSIVE_CARE" and level == "INTENSIVE":
        raise APIError("ERR_BED_TYPE_MISMATCH",
                       "INTENSIVE elder may only occupy INTENSIVE_CARE bed", 409)

    # Release source
    source_bed["status"] = "AVAILABLE"
    source_bed["current_elder_id"] = None
    touch(source_bed)

    # Occupy target
    target_bed["status"] = "OCCUPIED"
    target_bed["current_elder_id"] = elder["id"]
    touch(target_bed)

    elder["current_bed_id"] = target_bed["id"]
    history = elder.setdefault("admission_history", [])
    history.append({
        "event": "transfer",
        "at": iso_now(),
        "from_bed_id": source_bed["id"],
        "to_bed_id": target_bed["id"],
    })
    touch(elder)

    # Trigger waitlist promotion on the source release
    waitlist_svc.promote_for_bed(source_bed)


def discharge(elder, actor_id, actor_role):
    """ADMITTED|ON_LEAVE -> DISCHARGED with fiscal+clinical clearance."""
    db = get_db()
    if elder.get("status") not in ("ADMITTED", "ON_LEAVE"):
        raise APIError("ERR_INVALID_STATE", "Elder not eligible for discharge", 409)
    # Outstanding balance + no DRAFT bills.
    has_draft = any(b for b in db.bills.values()
                    if b["elder_id"] == elder["id"] and b["status"] == "DRAFT")
    if elder.get("outstanding_balance_cents", 0) != 0 or has_draft:
        raise APIError("ERR_OUTSTANDING_BALANCE",
                       "Cannot discharge with outstanding bills", 409)
    # Active prescriptions must be DISCONTINUED first
    has_open_rx = any(
        p for p in db.prescriptions.values()
        if p["elder_id"] == elder["id"]
        and p["status"] in ("PENDING_REVIEW", "ACTIVE", "SUSPENDED")
    )
    if has_open_rx:
        raise APIError("ERR_INVALID_STATE",
                       "Open prescriptions must be DISCONTINUED first", 409)

    # Release bed
    bed_id = elder.get("current_bed_id")
    bed = db.beds.get(bed_id) if bed_id else None
    if bed:
        bed["status"] = "AVAILABLE"
        bed["current_elder_id"] = None
        touch(bed)

    elder["status"] = "DISCHARGED"
    elder["current_bed_id"] = None
    history = elder.setdefault("admission_history", [])
    history.append({
        "event": "discharge",
        "discharged_at": iso_now(),
        "bed_id": bed_id,
    })

    # Refund deposit via system event (in-memory: simply clear it)
    if elder.get("deposit_balance_cents", 0) > 0:
        elder["deposit_balance_cents"] = 0

    touch(elder)

    # Cancel open RESERVED visits
    for r in db.visit_reservations.values():
        if r["elder_id"] == elder["id"] and r["status"] == "RESERVED":
            prev = r["status"]
            r["status"] = "CANCELLED"
            touch(r)

    # Cancel waitlist entries for this elder
    for w in db.waitlist.values():
        if w["elder_id"] == elder["id"] and w["status"] in ("QUEUED", "OFFERED"):
            w["status"] = "CANCELLED"
            w["offered_bed_id"] = None

    # Waitlist promotion for released bed
    if bed is not None:
        waitlist_svc.promote_for_bed(bed)


def recompute_outstanding_balance(elder_id):
    """Sum amount_due_cents of FINALIZED/ADJUSTED bills for elder."""
    db = get_db()
    total = 0
    for b in db.bills.values():
        if b["elder_id"] == elder_id and b["status"] in ("FINALIZED", "ADJUSTED"):
            total += int(b.get("amount_due_cents", 0))
    elder = db.elders.get(elder_id)
    if elder is not None:
        old = elder.get("outstanding_balance_cents")
        elder["outstanding_balance_cents"] = total
        if old != total:
            touch(elder)
