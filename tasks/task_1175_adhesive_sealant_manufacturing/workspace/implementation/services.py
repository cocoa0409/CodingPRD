"""Domain services: calculations, cascades, derived fields, serializers,
existence lookups, and the logical-clock sweep."""
import uuid
from datetime import timedelta, date
from calendar import monthrange
from decimal import Decimal, ROUND_HALF_UP

from db import store
from errors import not_found
from helpers import now_iso, fmt_dt, fmt_date

# ---------------------------------------------------------------------------
# Constants (calculation rules)
# ---------------------------------------------------------------------------

OVERFILL_PCT = {
    "CARTRIDGE": Decimal("0.02"),
    "PAIL": Decimal("0.01"),
    "DRUM": Decimal("0.005"),
}
SPECIMEN_TOLERANCE_MPA = Decimal("2.0")
SOLVENT_THRESHOLD_PCT = Decimal("24.0")
PG_II_FLASH_BELOW_C = Decimal("23.0")
CLASS3_FLASH_BELOW_C = Decimal("60.5")
LQ_MAX_UNIT_ML = 5000
HAZMAT_RANK = {
    "NON_REGULATED": 0,
    "UN1133_CLASS3_PG_III": 1,
    "UN1133_CLASS3_PG_II": 2,
}
TIER1_GROSS_CENTS = 500000
TIER1_PCT = 5
TIER2_GROSS_CENTS = 1000000
TIER2_PCT = 10

QA_PENDING = ("AWAITING_TEST", "TESTING", "UNDER_REVIEW")
BATCH_INFLIGHT = ("MIXING", "MIXED", "PACKING")


# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------

def new_entity():
    store.seq += 1
    return {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": store.seq,
    }


def touch(e):
    """Refresh updated_at and bump version on any mutation (cascades included)."""
    e["updated_at"] = now_iso()
    e["version"] = e.get("version", 1) + 1


def sorted_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r.get("_seq", 0)))


# ---------------------------------------------------------------------------
# Existence lookups
# ---------------------------------------------------------------------------

def _get(table, rid, what):
    e = table.get(rid)
    if e is None:
        raise not_found(what)
    return e


def get_formulation(fid):
    return _get(store.formulations, fid, "Formulation")


def get_vessel(vid):
    return _get(store.vessels, vid, "MixingVessel")


def get_dry_room(did):
    return _get(store.dry_rooms, did, "DryRoom")


def get_batch(bid):
    return _get(store.batches, bid, "ProductionBatch")


def get_run(rid):
    return _get(store.runs, rid, "PackagingRun")


def get_event(eid):
    return _get(store.events, eid, "MoistureExposureEvent")


def get_lot(lid):
    return _get(store.lots, lid, "ProductionLot")


def get_test(tid):
    return _get(store.tests, tid, "CureTest")


def get_request(rid):
    return _get(store.requests, rid, "FormulationRequest")


def get_distributor(did):
    return _get(store.distributors, did, "Distributor")


def get_agreement(aid):
    return _get(store.agreements, aid, "ConsignmentAgreement")


def get_stock(sid):
    return _get(store.stock, sid, "ConsignmentStock")


def get_report(rid):
    return _get(store.reports, rid, "ConsumptionReport")


def get_shipment(sid):
    return _get(store.shipments, sid, "Shipment")


def runs_of_batch(batch_id):
    return [r for r in store.runs.values() if r["batch_id"] == batch_id]


def lot_of_batch(batch):
    return store.lots.get(batch["production_lot_id"])


# ---------------------------------------------------------------------------
# Calendar arithmetic: expiry dating (day clamped to last day of month)
# ---------------------------------------------------------------------------

def add_months(d, months):
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    last = monthrange(y, m)[1]
    return date(y, m, min(d.day, last))


# ---------------------------------------------------------------------------
# Clock sweep: MIXING batches whose mix window has passed -> EXPIRED
# ---------------------------------------------------------------------------

def sweep_clock():
    now = store.clock
    for batch in list(store.batches.values()):
        if batch["status"] == "MIXING" and batch["mix_end_at"] < now:
            fire_batch_expiry(batch)


# ---------------------------------------------------------------------------
# Batch expiry / void cascades
# ---------------------------------------------------------------------------

def _recompute_lot_hold(lot):
    """hold_status -> CLEAR when no HOLD runs of this lot's batch remain."""
    if lot["hold_status"] != "QUARANTINE_HOLD":
        return
    if not any(r["status"] == "HOLD" for r in runs_of_batch(lot["batch_id"])):
        lot["hold_status"] = "CLEAR"


def fire_batch_expiry(batch):
    """MIXING|MIXED|PACKING -> EXPIRED with run and lot cascades."""
    lot = lot_of_batch(batch)
    batch["status"] = "EXPIRED"
    lot_changed = False
    for run in runs_of_batch(batch["id"]):
        if run["status"] in ("OPEN", "HOLD"):
            if (run["status"] == "HOLD" and run["held_from"] == "SEALED"
                    and lot is not None and lot["qa_status"] != "RELEASED"):
                # held sealed units leave quarantine and are condemned
                lot["units_quarantined"] -= run["units_produced"] or 0
                lot["units_condemned"] += run["units_produced"] or 0
                batch["written_off_volume_ml"] += run["total_filled_ml"] or 0
                lot_changed = True
            run["status"] = "VOID"
            run["held_from"] = None
            touch(run)
    if lot is not None and lot["qa_status"] in QA_PENDING:
        # sealed units are unsalvageable: condemn them
        for run in runs_of_batch(batch["id"]):
            if run["status"] == "SEALED":
                lot["units_condemned"] += run["units_produced"] or 0
                batch["written_off_volume_ml"] += run["total_filled_ml"] or 0
        lot["qa_status"] = "REJECTED"
        lot_changed = True
    if lot is not None:
        before = lot["hold_status"]
        _recompute_lot_hold(lot)
        lot_changed = lot_changed or lot["hold_status"] != before
        if lot_changed:
            touch(lot)
    touch(batch)


def fire_batch_void(batch):
    """MIXING|MIXED -> VOID: OPEN|HOLD runs -> VOID; pending lot -> REJECTED."""
    lot = lot_of_batch(batch)
    for run in runs_of_batch(batch["id"]):
        if run["status"] in ("OPEN", "HOLD"):
            run["status"] = "VOID"
            run["held_from"] = None
            touch(run)
    if lot is not None and lot["qa_status"] in QA_PENDING:
        lot["qa_status"] = "REJECTED"
        touch(lot)
    batch["status"] = "VOID"
    touch(batch)


# ---------------------------------------------------------------------------
# Packaging fill allocation (pinned rounding order: per unit first)
# ---------------------------------------------------------------------------

def pack_fill(unit_volume_ml, pack_format, planned_units, remaining_ml):
    per_unit = int(
        (Decimal(unit_volume_ml) * (1 + OVERFILL_PCT[pack_format])).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    units = min(planned_units, remaining_ml // per_unit)
    return per_unit, units, units * per_unit


# ---------------------------------------------------------------------------
# Bond strength assessment (QUICK vs FULL)
# ---------------------------------------------------------------------------

def assess_test(method, specimens, spec_min):
    """Returns (evaluated_value_mpa, assessment_pass)."""
    spec = Decimal(str(spec_min))
    if method == "QUICK":
        value = Decimal(str(specimens[0]))
        return float(value), value >= spec
    # FULL: sort, drop one min and one max, mean of retained 3, round_half_up 2dp
    ordered = sorted(Decimal(str(s)) for s in specimens)
    retained = ordered[1:4]
    mean = (retained[0] + retained[1] + retained[2]) / Decimal(3)
    value = mean.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    passed = (value >= spec) and (retained[0] >= spec - SPECIMEN_TOLERANCE_MPA)
    return float(value), passed


# ---------------------------------------------------------------------------
# Lot availability / FIFO
# ---------------------------------------------------------------------------

def reserved_units(lot_id):
    total = 0
    for s in store.shipments.values():
        if s["status"] in ("DRAFT", "PLANNED", "CONFIRMED"):
            for ln in s["lines"]:
                if ln["lot_id"] == lot_id:
                    total += ln["units"]
    return total


def units_available(lot):
    return (lot["units_filled"] - lot["units_quarantined"] - lot["units_condemned"]
            - lot["units_shipped"] - reserved_units(lot["id"]))


def lot_sort_key(lot):
    return (lot["expiry_date"], lot["created_at"], lot.get("_seq", 0))


def older_eligible_lot_with_stock(lot, ship_date):
    """The oldest RELEASED/CLEAR/unexpired lot of the same formulation that is
    strictly older than `lot` and still has available units (FIFO blocker)."""
    blockers = []
    for other in store.lots.values():
        if other["id"] == lot["id"] or other["formulation_id"] != lot["formulation_id"]:
            continue
        if other["qa_status"] != "RELEASED" or other["hold_status"] != "CLEAR":
            continue
        if other["expiry_date"] is None or not (other["expiry_date"] > ship_date):
            continue
        if units_available(other) <= 0:
            continue
        if lot_sort_key(other) < lot_sort_key(lot):
            blockers.append(other)
    return min(blockers, key=lot_sort_key) if blockers else None


# ---------------------------------------------------------------------------
# Hazmat classification
# ---------------------------------------------------------------------------

def classify_line(lot):
    f = store.formulations[lot["formulation_id"]]
    solvent = Decimal(str(f["solvent_content_pct"]))
    flash = Decimal(str(f["flash_point_c"]))
    if solvent >= SOLVENT_THRESHOLD_PCT and flash < CLASS3_FLASH_BELOW_C:
        if flash < PG_II_FLASH_BELOW_C:
            return "UN1133_CLASS3_PG_II"
        return "UN1133_CLASS3_PG_III"
    return "NON_REGULATED"


def worst_hazmat_class(shipment):
    worst = "NON_REGULATED"
    for ln in shipment["lines"]:
        lot = store.lots.get(ln["lot_id"])
        if lot is None:
            continue
        cls = classify_line(lot)
        if HAZMAT_RANK[cls] > HAZMAT_RANK[worst]:
            worst = cls
    return worst


# ---------------------------------------------------------------------------
# Consignment: stock waterfall, settlement, credit check
# ---------------------------------------------------------------------------

def stock_rows_of_agreement(agreement_id):
    return [r for r in store.stock.values() if r["agreement_id"] == agreement_id]


def total_on_hand(agreement_id):
    return sum(r["qty_on_hand"] for r in stock_rows_of_agreement(agreement_id))


def credit_check(distributor, candidate):
    total = sum(
        a["max_consigned_value_cents"]
        for a in store.agreements.values()
        if a["distributor_id"] == distributor["id"] and a["status"] in ("ACTIVE", "SUSPENDED")
    )
    total += candidate["max_consigned_value_cents"]
    return total <= distributor["credit_limit_cents"]


# ---------------------------------------------------------------------------
# Serializers (exactly the spec fields; internal `_`-prefixed keys excluded)
# ---------------------------------------------------------------------------

def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_formulation(f):
    return {
        **_common(f),
        "code": f["code"],
        "name": f["name"],
        "chemistry_family": f["chemistry_family"],
        "moisture_sensitive": f["moisture_sensitive"],
        "solvent_content_pct": f["solvent_content_pct"],
        "flash_point_c": f["flash_point_c"],
        "pot_life_minutes": f["pot_life_minutes"],
        "shelf_life_months": f["shelf_life_months"],
        "spec_min_bond_strength_mpa": f["spec_min_bond_strength_mpa"],
        "min_remaining_shelf_life_days": f["min_remaining_shelf_life_days"],
        "status": f["status"],
    }


def ser_vessel(v):
    return {
        **_common(v),
        "vessel_code": v["vessel_code"],
        "capacity_liters": v["capacity_liters"],
    }


def ser_dry_room(d):
    return {
        **_common(d),
        "room_code": d["room_code"],
        "max_concurrent_runs": d["max_concurrent_runs"],
        "humidity_limit_pct": d["humidity_limit_pct"],
    }


def ser_batch(b):
    return {
        **_common(b),
        "formulation_id": b["formulation_id"],
        "vessel_id": b["vessel_id"],
        "mix_start_at": fmt_dt(b["mix_start_at"]),
        "mix_end_at": fmt_dt(b["mix_end_at"]),
        "batch_volume_ml": b["batch_volume_ml"],
        "mixed_at": fmt_dt(b["mixed_at"]),
        "pot_life_deadline": fmt_dt(b["pot_life_deadline"]),
        "remaining_bulk_volume_ml": b["remaining_bulk_volume_ml"],
        "written_off_volume_ml": b["written_off_volume_ml"],
        "production_lot_id": b["production_lot_id"],
        "status": b["status"],
    }


def ser_run(r):
    return {
        **_common(r),
        "batch_id": r["batch_id"],
        "dry_room_id": r["dry_room_id"],
        "pack_format": r["pack_format"],
        "unit_volume_ml": r["unit_volume_ml"],
        "planned_units": r["planned_units"],
        "planned_start_at": fmt_dt(r["planned_start_at"]),
        "planned_end_at": fmt_dt(r["planned_end_at"]),
        "per_unit_fill_ml": r["per_unit_fill_ml"],
        "units_produced": r["units_produced"],
        "total_filled_ml": r["total_filled_ml"],
        "held_from": r["held_from"],
        "status": r["status"],
    }


def ser_event(e):
    # Append-only log record: id + created_at only, no updated_at / version.
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "packaging_run_id": e["packaging_run_id"],
        "exposure_minutes": e["exposure_minutes"],
        "occurred_at": fmt_dt(e["occurred_at"]),
        "note": e["note"],
    }


def ser_lot(lot):
    return {
        **_common(lot),
        "batch_id": lot["batch_id"],
        "formulation_id": lot["formulation_id"],
        "lot_number": lot["lot_number"],
        "manufacture_date": fmt_date(lot["manufacture_date"]),
        "expiry_date": fmt_date(lot["expiry_date"]),
        "pack_format": lot["pack_format"],
        "unit_volume_ml": lot["unit_volume_ml"],
        "units_filled": lot["units_filled"],
        "units_quarantined": lot["units_quarantined"],
        "units_condemned": lot["units_condemned"],
        "units_shipped": lot["units_shipped"],
        "retest_count": lot["retest_count"],
        "released_by": lot["released_by"],
        "qa_status": lot["qa_status"],
        "hold_status": lot["hold_status"],
    }


def ser_test(t):
    return {
        **_common(t),
        "lot_id": t["lot_id"],
        "method": t["method"],
        "specimens": t["specimens"],
        "technician_id": t["technician_id"],
        "evaluated_value_mpa": t["evaluated_value_mpa"],
        "assessment_pass": t["assessment_pass"],
        "status": t["status"],
    }


def ser_request(r):
    return {
        **_common(r),
        "distributor_id": r["distributor_id"],
        "contact_name": r["contact_name"],
        "target_substrate": r["target_substrate"],
        "required_bond_strength_mpa": r["required_bond_strength_mpa"],
        "application_notes": r["application_notes"],
        "info_request_note": r["info_request_note"],
        "response_note": r["response_note"],
        "decision_outcome": r["decision_outcome"],
        "resulting_formulation_id": r["resulting_formulation_id"],
        "status": r["status"],
    }


def ser_distributor(d):
    return {
        **_common(d),
        "name": d["name"],
        "credit_limit_cents": d["credit_limit_cents"],
        "contact_email": d["contact_email"],
    }


def ser_agreement(a):
    return {
        **_common(a),
        "distributor_id": a["distributor_id"],
        "formulation_id": a["formulation_id"],
        "unit_price_cents": a["unit_price_cents"],
        "max_consigned_value_cents": a["max_consigned_value_cents"],
        "reorder_threshold_units": a["reorder_threshold_units"],
        "reorder_qty_units": a["reorder_qty_units"],
        "min_remaining_shelf_life_days": a["min_remaining_shelf_life_days"],
        "status": a["status"],
    }


def ser_stock(s):
    return {
        **_common(s),
        "agreement_id": s["agreement_id"],
        "lot_id": s["lot_id"],
        "qty_shipped": s["qty_shipped"],
        "qty_consumed": s["qty_consumed"],
        "qty_returned": s["qty_returned"],
        "qty_on_hand": s["qty_on_hand"],
        "row_key": s["row_key"],
    }


def ser_report(r):
    return {
        **_common(r),
        "agreement_id": r["agreement_id"],
        "period": r["period"],
        "consumed_units": r["consumed_units"],
        "provisional_settlement_cents": r["provisional_settlement_cents"],
        "rebate_tier": r["rebate_tier"],
        "rebate_cents": r["rebate_cents"],
        "final_net_settlement_cents": r["final_net_settlement_cents"],
        "dispute_reason": r["dispute_reason"],
        "status": r["status"],
    }


def ser_shipment(s):
    return {
        **_common(s),
        "shipment_kind": s["shipment_kind"],
        "distributor_id": s["distributor_id"],
        "agreement_id": s["agreement_id"],
        "transport_mode": s["transport_mode"],
        "ship_date": fmt_date(s["ship_date"]),
        "lines": [{"lot_id": ln["lot_id"], "units": ln["units"]} for ln in s["lines"]],
        "hazmat_class": s["hazmat_class"],
        "auto_replenishment": s["auto_replenishment"],
        "proposed_units": s["proposed_units"],
        "status": s["status"],
    }
