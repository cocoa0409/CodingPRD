"""Domain core: entity construction, derived-field computation, cascades and sweeps.

All derived fields (supplier qualification scores, freezer capacity bookkeeping,
excursion severity, par-level signals, valuation) are computed from live state,
so every mutation path that changes a unit/reservation/document/recall/adverse
status automatically reconciles the figures that depend on it.
"""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from db import db, next_seq
from util import CLOCK, fmt_dt, fmt_dt_full, dec, round2_half_up, new_id

# ---------------------------------------------------------------------------
# Enum vocabularies
# ---------------------------------------------------------------------------

TISSUE_TYPES = {"BONE", "SOFT_TISSUE", "CARDIOVASCULAR", "SKIN", "CORNEA"}
CRITICALITY_TIERS = {"STANDARD", "SENSITIVE", "CRITICAL"}
DOC_TYPES = {"AATB_ACCREDITATION", "FDA_REGISTRATION", "STATE_LICENSE", "ISO_CERTIFICATE"}
REQUIRED_DOC_TYPES = ("AATB_ACCREDITATION", "FDA_REGISTRATION")
REACTION_TYPES = {"INFECTION", "REJECTION", "OTHER"}
REACTION_SEVERITIES = {"MINOR", "MAJOR", "CRITICAL"}
EXCURSION_DISPOSITIONS = {"RELEASE", "DESTROY"}
ADVERSE_OUTCOMES = {"CONFIRMED", "UNCONFIRMED"}
VALUATION_METHODS = {"FIFO", "WEIGHTED_AVERAGE"}

STORED_STATUSES = ("QUARANTINED", "AVAILABLE", "RESERVED")
ON_HAND_STATUSES = ("QUARANTINED", "AVAILABLE", "RESERVED", "ISSUED")

SUSPENSION_THRESHOLD = 60
RESERVE_TRIGGER_UTILIZATION = Fraction(80, 1)
RESERVED_SLOTS = 2
RETENTION_DAYS = 3650

# ---------------------------------------------------------------------------
# Common-field plumbing
# ---------------------------------------------------------------------------


def stamp_new(entity: dict):
    """Attach id / created_at / updated_at / version (version starts at 1)."""
    now = CLOCK.now()
    entity["id"] = new_id()
    entity["created_at"] = fmt_dt_full(now)
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    entity["_created_dt"] = now
    entity["_seq"] = next_seq()
    return entity


def touch(entity: dict):
    """Every mutation (including cascaded ones) refreshes updated_at and bumps
    version by 1 (PRD §2.5)."""
    entity["updated_at"] = fmt_dt_full(CLOCK.now())
    entity["version"] += 1


# ---------------------------------------------------------------------------
# Supplier qualification scores (calculations.supplier_qualification_score)
# ---------------------------------------------------------------------------


def supplier_scores(supplier_id: str):
    confirmed = 0
    open_adverse = 0
    for a in db["adverse_reactions"].values():
        u = db["units"].get(a["tissue_unit_id"])
        if u is None or u["supplier_id"] != supplier_id:
            continue
        if a["status"] == "CLOSED_CONFIRMED":
            confirmed += 1
        elif a["status"] in ("REPORTED", "UNDER_INVESTIGATION", "REOPENED"):
            open_adverse += 1
    active_recalls = sum(
        1 for r in db["recalls"].values()
        if r["supplier_id"] == supplier_id and r["status"] == "ACTIVE"
    )
    expired_docs = sum(
        1 for d in db["documents"].values()
        if d["supplier_id"] == supplier_id and d["status"] == "EXPIRED"
    )
    score_final = max(0, 100 - 20 * confirmed - 5 * expired_docs)
    score_provisional = max(
        0, 100 - 20 * confirmed - 15 * active_recalls - 10 * open_adverse - 5 * expired_docs
    )
    return score_provisional, score_final


def maybe_auto_suspend(supplier: dict) -> bool:
    """Auto-suspension gate, evaluated on every score mutation: a QUALIFIED
    supplier whose provisional score falls below 60 moves to SUSPENDED."""
    if supplier["status"] != "QUALIFIED":
        return False
    prov, _ = supplier_scores(supplier["id"])
    if prov < SUSPENSION_THRESHOLD:
        supplier["status"] = "SUSPENDED"
        supplier["suspended_at"] = fmt_dt(CLOCK.now())
        touch(supplier)
        return True
    return False


def has_required_doc_coverage(supplier_id: str) -> bool:
    """At least one VERIFIED document of each required type with valid_to >= clock."""
    now = CLOCK.now()
    for doc_type in REQUIRED_DOC_TYPES:
        covered = any(
            d["supplier_id"] == supplier_id
            and d["doc_type"] == doc_type
            and d["status"] == "VERIFIED"
            and d["_valid_to"] >= now
            for d in db["documents"].values()
        )
        if not covered:
            return False
    return True


# ---------------------------------------------------------------------------
# Freezer capacity bookkeeping (calculations.storage_capacity_gating) — pinned
# evaluation order: occupied -> utilization -> reserve -> effective; never
# iterated to a fixed point.
# ---------------------------------------------------------------------------


def freezer_occupied_count(freezer_id: str) -> int:
    return sum(
        1 for u in db["units"].values()
        if u["freezer_id"] == freezer_id and u["status"] in STORED_STATUSES
    )


def capacity_fields(freezer: dict):
    """Returns (occupied_count, utilization_pct, quarantine_reserve_slots,
    effective_capacity) computed from CURRENT occupancy."""
    occ = freezer_occupied_count(freezer["id"])
    nominal = freezer["nominal_capacity"]
    util_frac = Fraction(occ * 100, nominal)
    reserve = RESERVED_SLOTS if util_frac >= RESERVE_TRIGGER_UTILIZATION else 0
    effective = nominal - reserve
    util_display = float(
        (Decimal(occ * 100) / Decimal(nominal)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )
    return occ, util_display, reserve, effective


def freezer_admits(freezer: dict, n: int) -> bool:
    """Admission rule: storing N additional units requires
    occupied_count + N <= effective_capacity (equality admitted)."""
    occ, _util, _reserve, effective = capacity_fields(freezer)
    return occ + n <= effective


# ---------------------------------------------------------------------------
# Recall scope matching
# ---------------------------------------------------------------------------


def recall_matches_unit(recall: dict, unit: dict) -> bool:
    return (
        unit["supplier_id"] == recall["supplier_id"]
        and unit["lot_number"] in recall["lot_numbers"]
        and recall["_window_start"] <= unit["_received_dt"] <= recall["_window_end"]
    )


def unit_under_active_recall(unit: dict) -> bool:
    return any(
        r["status"] == "ACTIVE" and recall_matches_unit(r, unit)
        for r in db["recalls"].values()
    )


# ---------------------------------------------------------------------------
# Excursion severity (calculations.excursion_severity_score)
# ---------------------------------------------------------------------------

_TIER_RANK = {"STANDARD": 0, "SENSITIVE": 1, "CRITICAL": 2}
_TIER_PTS = {"STANDARD": 0, "SENSITIVE": 5, "CRITICAL": 10}


def excursion_affected_units(excursion: dict):
    return [
        u for u in db["units"].values()
        if u["freezer_id"] == excursion["freezer_id"] and u["hold_reason"] == "EXCURSION"
    ]


def excursion_severity(excursion: dict):
    affected = excursion_affected_units(excursion)
    # deviation: ceil of exact decimal degrees, 8 pts per degree, capped at 40
    dev = dec(excursion["max_deviation_celsius"])
    dev_pts = min(40, int(math.ceil(dev)) * 8) if dev > 0 else 0
    # duration: whole hours only, 6 pts per hour, capped at 30
    end = excursion["_resolved_dt"] if excursion["_resolved_dt"] is not None else CLOCK.now()
    seconds = (end - excursion["_opened_dt"]).total_seconds()
    hours = int(seconds // 3600)
    dur_pts = min(30, hours * 6)
    # affected stock: 2 pts each, capped at 20
    unit_pts = min(20, len(affected) * 2)
    # criticality: highest tier among affected units; 0 units -> STANDARD
    max_tier = "STANDARD"
    for u in affected:
        if _TIER_RANK[u["criticality_tier"]] > _TIER_RANK[max_tier]:
            max_tier = u["criticality_tier"]
    score = dev_pts + dur_pts + unit_pts + _TIER_PTS[max_tier]
    if score < 25:
        cls = "LOW"
    elif score <= 59:
        cls = "MEDIUM"
    else:
        cls = "HIGH"
    return score, cls, len(affected)


# ---------------------------------------------------------------------------
# Par-level signals (calculations.par_level_deficit)
# ---------------------------------------------------------------------------


def policy_signals(policy: dict):
    on_hand = sum(
        1 for u in db["units"].values()
        if u["tissue_type"] == policy["tissue_type"] and u["status"] == "AVAILABLE"
    )
    deficit = max(0, policy["par_quantity"] - on_hand)
    return on_hand, deficit, on_hand < policy["par_quantity"]


# ---------------------------------------------------------------------------
# Inventory valuation (calculations.inventory_valuation)
# ---------------------------------------------------------------------------


def _accepted_population(tissue_type: str):
    return [
        u for u in db["units"].values()
        if u["tissue_type"] == tissue_type
        and db["shipments"][u["shipment_id"]]["status"] == "ACCEPTED"
    ]


def _weighted_average_total(population, on_hand):
    """Per-lot-line round-half-up to 2dp FIRST, then sum (pinned order)."""
    avg = Fraction(sum(u["unit_cost_cents"] for u in population), len(population))
    lots = sorted({u["lot_number"] for u in on_hand})
    total = Decimal(0)
    for lot in lots:
        cnt = sum(1 for u in on_hand if u["lot_number"] == lot)
        total += round2_half_up(avg * cnt)
    return total


def compute_valuation(tissue_type: str, method: str):
    population = _accepted_population(tissue_type)
    on_hand = [u for u in population if u["status"] in ON_HAND_STATUSES]
    if not population:
        return 0, (0.0 if method == "WEIGHTED_AVERAGE" else 0)
    if method == "FIFO":
        ordered = sorted(population, key=lambda u: (u["_received_dt"], u["_created_dt"], u["_seq"]))
        consumed_count = len(population) - len(on_hand)
        remaining = ordered[consumed_count:]
        return len(on_hand), sum(u["unit_cost_cents"] for u in remaining)
    total = _weighted_average_total(population, on_hand)
    return len(on_hand), float(total)


def projected_wa_total_with(tissue_type: str, extra_units) -> Decimal:
    """Projected WEIGHTED_AVERAGE valuation if extra_units (not yet accepted)
    joined the population — used by the shipment-accept fiscal cap."""
    population = _accepted_population(tissue_type) + list(extra_units)
    on_hand = [u for u in population if u["status"] in ON_HAND_STATUSES]
    if not population:
        return Decimal(0)
    return _weighted_average_total(population, on_hand)


# ---------------------------------------------------------------------------
# Disposition records
# ---------------------------------------------------------------------------


def create_disposition(unit: dict, disposition_type: str, reason: str, actor_id: str) -> dict:
    record = {
        "tissue_unit_id": unit["id"],
        "disposition_type": disposition_type,
        "reason": reason,
        "recorded_by_user_id": actor_id,
        "status": "DRAFT",
        "finalized_at": None,
        "finalized_by_user_id": None,
        "_finalized_dt": None,
    }
    stamp_new(record)
    db["dispositions"][record["id"]] = record
    return record


# ---------------------------------------------------------------------------
# Excursion open / resolve cascades
# ---------------------------------------------------------------------------


def open_excursion(freezer: dict, origin: str, reporter_id, initial_deviation) -> dict:
    """Open an excursion on a freezer and fire the quarantine cascade.

    Cascade: AVAILABLE -> QUARANTINED (EXCURSION); RESERVED -> QUARANTINED
    (EXCURSION) with its ACTIVE reservation RELEASED (EXCURSION); QUARANTINED
    units keep status and take hold_reason EXCURSION only when previously NONE.
    """
    now = CLOCK.now()
    excursion = {
        "freezer_id": freezer["id"],
        "origin": origin,
        "status": "OPEN",
        "opened_at": fmt_dt(now),
        "last_reading_at": fmt_dt(now),
        "max_deviation_celsius": initial_deviation,
        "reported_by_user_id": reporter_id,
        "resolved_by_user_id": None,
        "resolution_notes": None,
        "resolved_at": None,
        "_opened_dt": now,
        "_resolved_dt": None,
    }
    stamp_new(excursion)
    db["excursions"][excursion["id"]] = excursion

    freezer["status"] = "EXCURSION_ACTIVE"
    freezer["current_excursion_id"] = excursion["id"]
    touch(freezer)  # excursion open increments Freezer.version by 1

    held = sorted(
        (u for u in db["units"].values() if u["freezer_id"] == freezer["id"]),
        key=lambda u: u["_seq"],
    )
    for u in held:
        if u["status"] == "AVAILABLE":
            u["status"] = "QUARANTINED"
            u["hold_reason"] = "EXCURSION"
            touch(u)
        elif u["status"] == "RESERVED":
            u["status"] = "QUARANTINED"
            u["hold_reason"] = "EXCURSION"
            touch(u)
            res = active_reservation_for_unit(u["id"])
            if res is not None:
                res["status"] = "RELEASED"
                res["release_reason"] = "EXCURSION"
                touch(res)
        elif u["status"] == "QUARANTINED" and u["hold_reason"] == "NONE":
            u["hold_reason"] = "EXCURSION"
            touch(u)
    return excursion


def resolve_excursion_cascade(excursion: dict, disposition: str, resolver_id: str, notes: str):
    now = CLOCK.now()
    excursion["status"] = "RESOLVED_RELEASE" if disposition == "RELEASE" else "RESOLVED_DESTROY"
    excursion["resolved_by_user_id"] = resolver_id
    excursion["resolution_notes"] = notes
    excursion["_resolved_dt"] = now
    excursion["resolved_at"] = fmt_dt(now)
    touch(excursion)

    freezer = db["freezers"][excursion["freezer_id"]]
    held = sorted(
        (u for u in db["units"].values()
         if u["freezer_id"] == freezer["id"] and u["hold_reason"] == "EXCURSION"),
        key=lambda u: u["_seq"],
    )
    for u in held:
        if disposition == "RELEASE":
            u["status"] = "AVAILABLE"
            u["hold_reason"] = "NONE"
            touch(u)
        else:
            u["status"] = "DISCARDED"
            u["hold_reason"] = "NONE"
            u["recall_flag"] = False
            touch(u)
            create_disposition(u, "DESTROYED", notes, resolver_id)

    freezer["status"] = "OPERATIONAL"
    freezer["current_excursion_id"] = None
    touch(freezer)


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------


def active_reservation_for_unit(unit_id: str):
    for r in db["reservations"].values():
        if r["tissue_unit_id"] == unit_id and r["status"] == "ACTIVE":
            return r
    return None


# ---------------------------------------------------------------------------
# Clock sweeps (POST /_clock/set_current_utc) — pinned order: documents, then
# units, then reservations. All comparisons strict > at second precision.
# ---------------------------------------------------------------------------


def run_clock_sweeps(actor_id: str) -> dict:
    now = CLOCK.now()
    counts = {
        "documents_expired": 0,
        "units_expired": 0,
        "reservations_expired": 0,
        "suppliers_auto_suspended": 0,
    }

    # 1) Document expiry sweep (valid_to ASC, tie created_at ASC)
    docs = sorted(
        (d for d in db["documents"].values()
         if d["status"] == "VERIFIED" and d["_valid_to"] < now),
        key=lambda d: (d["_valid_to"], d["_created_dt"], d["_seq"]),
    )
    affected_supplier_ids = set()
    for d in docs:
        d["status"] = "EXPIRED"
        touch(d)
        counts["documents_expired"] += 1
        sid = d["supplier_id"]
        affected_supplier_ids.add(sid)
        supplier = db["suppliers"].get(sid)
        if supplier is None:
            continue
        if d["doc_type"] in REQUIRED_DOC_TYPES:
            covered = any(
                o is not d
                and o["supplier_id"] == sid
                and o["doc_type"] == d["doc_type"]
                and o["status"] == "VERIFIED"
                and o["_valid_to"] >= now
                for o in db["documents"].values()
            )
            if not covered and supplier["status"] == "QUALIFIED":
                supplier["status"] = "SUSPENDED"
                supplier["suspended_at"] = fmt_dt(now)
                touch(supplier)
                counts["suppliers_auto_suspended"] += 1
    # expired-document events feed the score model; evaluate the gate per supplier
    for sid in affected_supplier_ids:
        supplier = db["suppliers"].get(sid)
        if supplier is not None and maybe_auto_suspend(supplier):
            counts["suppliers_auto_suspended"] += 1

    # 2) Unit expiration sweep (received_at ASC, tie created_at ASC); ISSUED exempt
    units = sorted(
        (u for u in db["units"].values()
         if u["status"] in STORED_STATUSES and u["_expiration_dt"] < now),
        key=lambda u: (u["_received_dt"], u["_created_dt"], u["_seq"]),
    )
    for u in units:
        was_reserved = u["status"] == "RESERVED"
        u["status"] = "EXPIRED"
        u["hold_reason"] = "NONE"
        touch(u)
        counts["units_expired"] += 1
        if was_reserved:
            res = active_reservation_for_unit(u["id"])
            if res is not None:
                res["status"] = "EXPIRED"
                res["release_reason"] = "CLOCK_EXPIRED"
                touch(res)
                counts["reservations_expired"] += 1
        create_disposition(u, "EXPIRED", "Unit expiration_at passed the logical clock", actor_id)

    # 3) Reservation expiry sweep (clock > hold_until)
    reservations = sorted(
        (r for r in db["reservations"].values()
         if r["status"] == "ACTIVE" and r["_hold_until"] < now),
        key=lambda r: (r["_hold_until"], r["_created_dt"], r["_seq"]),
    )
    for r in reservations:
        r["status"] = "EXPIRED"
        r["release_reason"] = "CLOCK_EXPIRED"
        touch(r)
        counts["reservations_expired"] += 1
        u = db["units"].get(r["tissue_unit_id"])
        if u is not None and u["status"] == "RESERVED":
            u["status"] = "AVAILABLE"
            touch(u)

    return counts


# ---------------------------------------------------------------------------
# Serializers (derived fields computed on read)
# ---------------------------------------------------------------------------


def supplier_json(s: dict) -> dict:
    prov, fin = supplier_scores(s["id"])
    return {
        "id": s["id"],
        "legal_name": s["legal_name"],
        "license_number": s["license_number"],
        "status": s["status"],
        "qualification_score_provisional": prov,
        "qualification_score_final": fin,
        "suspended_at": s["suspended_at"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def document_json(d: dict) -> dict:
    return {
        "id": d["id"],
        "supplier_id": d["supplier_id"],
        "doc_type": d["doc_type"],
        "document_ref": d["document_ref"],
        "valid_from": d["valid_from"],
        "valid_to": d["valid_to"],
        "status": d["status"],
        "verified_by_user_id": d["verified_by_user_id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def shipment_json(sh: dict) -> dict:
    return {
        "id": sh["id"],
        "supplier_id": sh["supplier_id"],
        "freezer_id": sh["freezer_id"],
        "items": [
            {
                "tissue_type": it["tissue_type"],
                "lot_number": it["lot_number"],
                "serial_number": it["serial_number"],
                "unit_cost_cents": it["unit_cost_cents"],
                "expiration_at": it["expiration_at"],
                "criticality_tier": it["criticality_tier"],
            }
            for it in sh["items"]
        ],
        "status": sh["status"],
        "received_at": sh["received_at"],
        "total_declared_value_cents": sh["total_declared_value_cents"],
        "unit_count": sh["unit_count"],
        "accepted_at": sh["accepted_at"],
        "rejection_reason": sh["rejection_reason"],
        "created_at": sh["created_at"],
        "updated_at": sh["updated_at"],
        "version": sh["version"],
    }


def unit_json(u: dict) -> dict:
    return {
        "id": u["id"],
        "shipment_id": u["shipment_id"],
        "supplier_id": u["supplier_id"],
        "freezer_id": u["freezer_id"],
        "tissue_type": u["tissue_type"],
        "lot_number": u["lot_number"],
        "serial_number": u["serial_number"],
        "unit_cost_cents": u["unit_cost_cents"],
        "criticality_tier": u["criticality_tier"],
        "expiration_at": u["expiration_at"],
        "received_at": u["received_at"],
        "status": u["status"],
        "hold_reason": u["hold_reason"],
        "recall_flag": u["recall_flag"],
        "implanted_case_id": u["implanted_case_id"],
        "implanted_at": u["implanted_at"],
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
    }


def freezer_json(f: dict) -> dict:
    occ, util, reserve, effective = capacity_fields(f)
    return {
        "id": f["id"],
        "name": f["name"],
        "min_celsius": f["min_celsius"],
        "max_celsius": f["max_celsius"],
        "nominal_capacity": f["nominal_capacity"],
        "status": f["status"],
        "occupied_count": occ,
        "utilization_pct": util,
        "quarantine_reserve_slots": reserve,
        "effective_capacity": effective,
        "current_excursion_id": f["current_excursion_id"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def reading_json(r: dict) -> dict:
    # TemperatureReading is an immutable observation: id + created_at only,
    # no updated_at / version (PRD §2.5).
    return {
        "id": r["id"],
        "freezer_id": r["freezer_id"],
        "temp_celsius": r["temp_celsius"],
        "in_range": r["in_range"],
        "recorded_by_user_id": r["recorded_by_user_id"],
        "excursion_id": r["excursion_id"],
        "created_at": r["created_at"],
    }


def excursion_json(e: dict) -> dict:
    score, cls, affected = excursion_severity(e)
    return {
        "id": e["id"],
        "freezer_id": e["freezer_id"],
        "origin": e["origin"],
        "status": e["status"],
        "opened_at": e["opened_at"],
        "last_reading_at": e["last_reading_at"],
        "max_deviation_celsius": e["max_deviation_celsius"],
        "affected_unit_count": affected,
        "severity_score": score,
        "severity_class": cls,
        "reported_by_user_id": e["reported_by_user_id"],
        "resolved_by_user_id": e["resolved_by_user_id"],
        "resolution_notes": e["resolution_notes"],
        "resolved_at": e["resolved_at"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def case_json(c: dict) -> dict:
    return {
        "id": c["id"],
        "surgeon_id": c["surgeon_id"],
        "patient_ref": c["patient_ref"],
        "or_room_id": c["or_room_id"],
        "scheduled_start": c["scheduled_start"],
        "scheduled_end": c["scheduled_end"],
        "status": c["status"],
        "implanted_unit_count": c["implanted_unit_count"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def reservation_json(r: dict) -> dict:
    return {
        "id": r["id"],
        "implant_case_id": r["implant_case_id"],
        "tissue_unit_id": r["tissue_unit_id"],
        "status": r["status"],
        "hold_until": r["hold_until"],
        "release_reason": r["release_reason"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def recall_json(r: dict) -> dict:
    return {
        "id": r["id"],
        "supplier_id": r["supplier_id"],
        "lot_numbers": r["lot_numbers"],
        "received_window_start": r["received_window_start"],
        "received_window_end": r["received_window_end"],
        "reason": r["reason"],
        "status": r["status"],
        "closure_reason": r["closure_reason"],
        "affected_unit_count": r["affected_unit_count"],
        "activated_at": r["activated_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def adverse_json(a: dict) -> dict:
    return {
        "id": a["id"],
        "implant_case_id": a["implant_case_id"],
        "tissue_unit_id": a["tissue_unit_id"],
        "reporter_user_id": a["reporter_user_id"],
        "reaction_type": a["reaction_type"],
        "severity": a["severity"],
        "description": a["description"],
        "status": a["status"],
        "investigator_user_id": a["investigator_user_id"],
        "reopened_count": a["reopened_count"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def policy_json(p: dict) -> dict:
    on_hand, deficit, needs = policy_signals(p)
    return {
        "id": p["id"],
        "tissue_type": p["tissue_type"],
        "par_quantity": p["par_quantity"],
        "max_inventory_value_cents": p["max_inventory_value_cents"],
        "status": p["status"],
        "on_hand_available": on_hand,
        "deficit": deficit,
        "needs_reorder": needs,
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def disposition_json(d: dict) -> dict:
    return {
        "id": d["id"],
        "tissue_unit_id": d["tissue_unit_id"],
        "disposition_type": d["disposition_type"],
        "reason": d["reason"],
        "recorded_by_user_id": d["recorded_by_user_id"],
        "status": d["status"],
        "finalized_at": d["finalized_at"],
        "finalized_by_user_id": d["finalized_by_user_id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }
