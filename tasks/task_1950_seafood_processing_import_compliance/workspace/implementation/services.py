"""Business logic: calculations, cascades, serializers (SCAFFOLD §1.3, §1.2)."""
from decimal import Decimal

from db import store, new_entity, new_append_only, touch
from utils import q2, q3, iso_z, iso_z3, add_months

# ---------------------------------------------------------------- constants
HISTAMINE_SUSCEPTIBLE_SPECIES = {
    "TUNA", "MAHI_MAHI", "MACKEREL", "SARDINE", "ANCHOVY", "BLUEFISH",
}
BASE_YIELD = {
    "FILLET": Decimal("0.42"),
    "LOIN": Decimal("0.55"),
    "PORTION": Decimal("0.48"),
}
GRADE_FACTOR = {
    "A": Decimal("1.00"),
    "B": Decimal("0.95"),
    "C": Decimal("0.88"),
}
YIELD_VARIANCE_TOLERANCE = Decimal("5.0")
PRIOR_NOTICE_LEAD_HOURS = {"VESSEL": 8, "AIR": 4, "ROAD": 2}
CRITICAL_LIMIT_PPM = Decimal("50.0")
SUBSAMPLE_CEILING_PPM = Decimal("100.0")
ABUSE_THRESHOLD_C = Decimal("4.4")
ABUSE_LIMIT_MIN = 240
FREEZE_STANDARD_THRESHOLD_C = Decimal("-20.0")
FREEZE_STANDARD_REQUIRED_MINUTES = 10080
FREEZE_BLAST_THRESHOLD_C = Decimal("-35.0")
FREEZE_BLAST_REQUIRED_MINUTES = 900
COMBO_BLAST_MIN_MINUTES = 240
COMBO_HOLD_THRESHOLD_C = Decimal("-20.0")
COMBO_HOLD_REQUIRED_MINUTES = 1440
TIER_INTERVAL_MONTHS = {"LOW": 36, "MODERATE": 12, "HIGH": 3}
W_EVAL = Decimal("0.40")
W_OPEN = Decimal("0.30")
W_HISTORY = Decimal("0.30")

OPEN_CA_STATUSES = ("OPEN", "INVESTIGATING")


# ---------------------------------------------------------------- lookups
def supplier_cas(supplier_id):
    return [c for c in store.corrective_actions.values()
            if c.get("supplier_id") == supplier_id]


def open_ca_count(supplier_id):
    return sum(1 for c in supplier_cas(supplier_id) if c["status"] in OPEN_CA_STATUSES)


def total_species_mismatches(supplier_id):
    return sum(1 for c in supplier_cas(supplier_id)
               if c["source_type"] == "SPECIES_MISMATCH")


def total_haccp_deviations(supplier_id):
    return sum(1 for c in supplier_cas(supplier_id)
               if c["source_type"] in ("HISTAMINE_DEVIATION", "TEMPERATURE_ABUSE"))


def latest_evaluation(supplier_id):
    evals = [e for e in store.evaluations.values() if e["supplier_id"] == supplier_id]
    if not evals:
        return None
    # latest by period_end DESC; ties broken by created_at ASC (earliest wins)
    return sorted(
        evals,
        key=lambda e: (-e["period_end"].timestamp(), e["_created_dt"], e["_seq"]),
    )[0]


def supplier_risk(supplier):
    """supplier_risk_score calculation. (score, tier); (None, None) pre-evaluation."""
    ev = latest_evaluation(supplier["id"])
    if ev is None:
        return None, None
    eval_component = Decimal("100") - ev["overall_score"]
    open_penalty = min(Decimal(open_ca_count(supplier["id"])) * 10, Decimal("100"))
    history_penalty = min(
        Decimal(total_species_mismatches(supplier["id"])) * 25
        + Decimal(total_haccp_deviations(supplier["id"])) * 15,
        Decimal("100"),
    )
    score = q2(W_EVAL * eval_component + W_OPEN * open_penalty + W_HISTORY * history_penalty)
    if score < Decimal("30"):
        tier = "LOW"
    elif score < Decimal("70"):
        tier = "MODERATE"
    else:
        tier = "HIGH"
    return score, tier


# ---------------------------------------------------------------- allocation
def run_entry_cost_allocation(entry):
    """entry_cost_allocation waterfall over the entry's ACCEPTED lots."""
    lots = [l for l in store.lots.values() if l["import_entry_id"] == entry["id"]]
    eligible = [l for l in lots if l["status"] == "ACCEPTED"]
    for l in lots:
        l["allocated_cost_cents"] = 0
    total_cents = entry.get("allocatable_total_cents")
    if total_cents is None or not eligible:
        return
    # milligrams (kg * 1000) are exact integers because kg carry 3 decimals
    mg = {l["id"]: int(l["quantity_accepted_kg"] * 1000) for l in eligible}
    sum_mg = sum(mg.values())
    if sum_mg <= 0:
        return
    floors = {lid: (total_cents * m) // sum_mg for lid, m in mg.items()}
    remainder = total_cents - sum(floors.values())
    # share DESC == mg DESC (common denominator); tie: quantity DESC (same),
    # then created_at ASC (insertion order as final deterministic tiebreak).
    by_id = {l["id"]: l for l in eligible}
    order = sorted(
        eligible,
        key=lambda l: (-mg[l["id"]], l["_created_dt"], l["_seq"]),
    )
    for l in order[:remainder]:
        floors[l["id"]] += 1
    for lid, cents in floors.items():
        by_id[lid]["allocated_cost_cents"] = cents


# ---------------------------------------------------------------- batch yield
def batch_inputs(batch_id):
    return sort_inputs([r for r in store.batch_inputs.values()
                        if r["processing_batch_id"] == batch_id])


def sort_inputs(rows):
    return sorted(rows, key=lambda e: (e["_created_dt"], e["_seq"]))


def input_provisional_yield(batch, lot, quantity_kg):
    return q3(quantity_kg * BASE_YIELD[batch["product_form"]] * GRADE_FACTOR[lot["grade"]])


def recompute_batch_totals(batch):
    rows = batch_inputs(batch["id"])
    input_total = sum((r["quantity_kg"] for r in rows), Decimal("0"))
    provisional = sum((r["provisional_yield_kg"] for r in rows), Decimal("0"))
    batch["input_total_kg"] = q3(input_total)
    batch["provisional_output_kg"] = q3(provisional)
    if batch["input_total_kg"] > 0:
        batch["yield_pct_provisional"] = q2(
            Decimal("100") * batch["provisional_output_kg"] / batch["input_total_kg"])
    else:
        batch["yield_pct_provisional"] = None


# ---------------------------------------------------------------- corrective actions
def auto_create_corrective_action(source_type, opened_by, lot=None, batch=None,
                                  monitoring_record_id=None):
    supplier_id = None
    if lot is not None:
        entry = store.entries.get(lot["import_entry_id"])
        if entry is not None:
            supplier_id = entry["supplier_id"]
    ca = new_entity(
        source_type=source_type,
        supplier_id=supplier_id,
        receipt_lot_id=lot["id"] if lot is not None else None,
        processing_batch_id=batch["id"] if batch is not None else None,
        monitoring_record_id=monitoring_record_id,
        opened_by=opened_by,
        status="OPEN",
        resolution_note=None,
        closed_by=None,
        recall_id=None,
    )
    store.corrective_actions[ca["id"]] = ca
    if supplier_id is not None:
        supplier = store.suppliers.get(supplier_id)
        if supplier is not None:
            # counters/risk derive from CAs; bump the supplier version per cascade
            touch(supplier)
    return ca


def quarantine_lot(lot):
    """Transition UNDER_INSPECTION|ACCEPTED -> QUARANTINED (no-op otherwise).
    Returns True when a transition happened."""
    if lot["status"] not in ("UNDER_INSPECTION", "ACCEPTED"):
        return False
    was_accepted = lot["status"] == "ACCEPTED"
    lot["status"] = "QUARANTINED"
    touch(lot)
    if was_accepted:
        entry = store.entries.get(lot["import_entry_id"])
        if entry is not None:
            run_entry_cost_allocation(entry)
    return True


# ---------------------------------------------------------------- temperature
def lot_temperature_logs(lot_id):
    logs = [t for t in store.temp_logs.values() if t.get("receipt_lot_id") == lot_id]
    return sorted(logs, key=lambda t: (t["interval_start"], t["_created_dt"], t["_seq"]))


def interval_minutes(log):
    return int((log["interval_end"] - log["interval_start"]).total_seconds() // 60)


def compute_freeze_compliant(lot, logs):
    proto = lot["freeze_protocol"]
    if proto == "NONE":
        return False
    if proto == "STANDARD":
        total = sum(interval_minutes(l) for l in logs
                    if l["core_temp_c"] <= FREEZE_STANDARD_THRESHOLD_C)
        return total >= FREEZE_STANDARD_REQUIRED_MINUTES
    if proto == "BLAST":
        total = sum(interval_minutes(l) for l in logs
                    if l["core_temp_c"] <= FREEZE_BLAST_THRESHOLD_C)
        return total >= FREEZE_BLAST_REQUIRED_MINUTES
    if proto == "COMBO":
        phase1 = sum(interval_minutes(l) for l in logs
                     if l["core_temp_c"] <= FREEZE_BLAST_THRESHOLD_C)
        first_blast = next(
            (l for l in logs if l["core_temp_c"] <= FREEZE_BLAST_THRESHOLD_C), None)
        if first_blast is None:
            return False
        threshold_start = first_blast["interval_end"]
        phase2 = sum(
            interval_minutes(l) for l in logs
            if l["interval_start"] >= threshold_start
            and l["core_temp_c"] <= COMBO_HOLD_THRESHOLD_C)
        return phase1 >= COMBO_BLAST_MIN_MINUTES and phase2 >= COMBO_HOLD_REQUIRED_MINUTES
    return False


def recompute_temperature_effects(lot, actor_id):
    """Recompute abuse accumulation and freeze compliance after a new log.

    Abuse crossing auto-creates a TEMPERATURE_ABUSE CA and quarantines the lot
    when it is UNDER_INSPECTION or ACCEPTED."""
    logs = lot_temperature_logs(lot["id"])
    if lot["species_declared"] in HISTAMINE_SUSCEPTIBLE_SPECIES:
        total = sum(interval_minutes(l) for l in logs
                    if l["avg_temp_c"] > ABUSE_THRESHOLD_C)
        lot["cumulative_abuse_minutes"] = total
        if total >= ABUSE_LIMIT_MIN and lot["status"] in ("UNDER_INSPECTION", "ACCEPTED"):
            auto_create_corrective_action(
                "TEMPERATURE_ABUSE", opened_by=actor_id, lot=lot)
            quarantine_lot(lot)
    if lot["freeze_protocol"] != "NONE":
        lot["freeze_compliant"] = compute_freeze_compliant(lot, logs)


# ---------------------------------------------------------------- serializers
def serialize_supplier(s):
    score, tier = supplier_risk(s)
    return {
        "id": s["id"],
        "legal_name": s["legal_name"],
        "country_code": s["country_code"],
        "facility_registration_number": s["facility_registration_number"],
        "handles_histamine_susceptible_species": s["handles_histamine_susceptible_species"],
        "fsvp_status": s["fsvp_status"],
        "risk_score": float(score) if score is not None else None,
        "risk_tier": tier,
        "open_corrective_action_count": open_ca_count(s["id"]),
        "total_species_mismatches": total_species_mismatches(s["id"]),
        "total_haccp_deviations": total_haccp_deviations(s["id"]),
        "last_evaluation_period_end": iso_z(s.get("last_evaluation_period_end")),
        "next_evaluation_due": iso_z(s.get("next_evaluation_due")),
        "created_at": iso_z3(s["_created_dt"]),
        "updated_at": iso_z3(s.get("_updated_dt", s["_created_dt"])),
        "version": s["version"],
    }


def serialize_evaluation(e):
    return {
        "id": e["id"],
        "supplier_id": e["supplier_id"],
        "period_start": iso_z(e["period_start"]),
        "period_end": iso_z(e["period_end"]),
        "hazard_analysis_score": float(e["hazard_analysis_score"]),
        "record_review_score": float(e["record_review_score"]),
        "performance_score": float(e["performance_score"]),
        "overall_score": float(e["overall_score"]),
        "outcome": e["outcome"],
        "evaluated_by": e["evaluated_by"],
        "created_at": iso_z3(e["_created_dt"]),
        "updated_at": iso_z3(e.get("_updated_dt", e["_created_dt"])),
        "version": e["version"],
    }


def serialize_entry(e):
    return {
        "id": e["id"],
        "supplier_id": e["supplier_id"],
        "entry_number": e["entry_number"],
        "species_declared": e["species_declared"],
        "transport_mode": e["transport_mode"],
        "scheduled_arrival": iso_z(e["scheduled_arrival"]),
        "port_code": e["port_code"],
        "goods_value_cents": e["goods_value_cents"],
        "freight_cost_cents": e["freight_cost_cents"],
        "duty_rate_pct": float(e["duty_rate_pct"]),
        "total_weight_kg": float(e["total_weight_kg"]),
        "prior_notice_filed_at": iso_z3(e["prior_notice_filed_at"]) if e.get("prior_notice_filed_at") else None,
        "prior_notice_confirmation": e.get("prior_notice_confirmation"),
        "entry_filed_at": iso_z3(e["entry_filed_at"]) if e.get("entry_filed_at") else None,
        "duty_cents": e.get("duty_cents"),
        "allocatable_total_cents": e.get("allocatable_total_cents"),
        "status": e["status"],
        "created_at": iso_z3(e["_created_dt"]),
        "updated_at": iso_z3(e.get("_updated_dt", e["_created_dt"])),
        "version": e["version"],
    }


def serialize_lot(l):
    return {
        "id": l["id"],
        "import_entry_id": l["import_entry_id"],
        "vessel_name": l["vessel_name"],
        "harvest_date": iso_z(l["harvest_date"]),
        "catch_area_code": l["catch_area_code"],
        "harvest_country_code": l["harvest_country_code"],
        "production_method": l["production_method"],
        "species_declared": l["species_declared"],
        "species_verified": l.get("species_verified"),
        "grade": l["grade"],
        "quantity_received_kg": float(l["quantity_received_kg"]),
        "ice_deduction_pct": float(l["ice_deduction_pct"]),
        "quantity_accepted_kg": float(l["quantity_accepted_kg"]),
        "consumed_kg": float(l["consumed_kg"]),
        "remaining_kg": float(l["quantity_accepted_kg"] - l["consumed_kg"]),
        "receiving_temp_c": float(l["receiving_temp_c"]),
        "freeze_protocol": l["freeze_protocol"],
        "freeze_compliant": l["freeze_compliant"],
        "cumulative_abuse_minutes": l["cumulative_abuse_minutes"],
        "mislabel_flag": l["mislabel_flag"],
        "allocated_cost_cents": l["allocated_cost_cents"],
        "status": l["status"],
        "created_at": iso_z3(l["_created_dt"]),
        "updated_at": iso_z3(l.get("_updated_dt", l["_created_dt"])),
        "version": l["version"],
    }


def serialize_verification(v):
    return {
        "id": v["id"],
        "receipt_lot_id": v["receipt_lot_id"],
        "test_method": v["test_method"],
        "sample_size": v["sample_size"],
        "verified_species": v["verified_species"],
        "is_match": v["is_match"],
        "resolution": v.get("resolution"),
        "status": v["status"],
        "created_at": iso_z3(v["_created_dt"]),
        "updated_at": iso_z3(v.get("_updated_dt", v["_created_dt"])),
        "version": v["version"],
    }


def serialize_batch(b):
    return {
        "id": b["id"],
        "target_species": b["target_species"],
        "product_form": b["product_form"],
        "status": b["status"],
        "input_total_kg": float(b["input_total_kg"]),
        "provisional_output_kg": float(b["provisional_output_kg"]) if b.get("provisional_output_kg") is not None else None,
        "actual_output_kg": float(b["actual_output_kg"]) if b.get("actual_output_kg") is not None else None,
        "trim_waste_kg": float(b["trim_waste_kg"]) if b.get("trim_waste_kg") is not None else None,
        "other_waste_kg": float(b["other_waste_kg"]) if b.get("other_waste_kg") is not None else None,
        "yield_pct_provisional": float(b["yield_pct_provisional"]) if b.get("yield_pct_provisional") is not None else None,
        "yield_pct_final": float(b["yield_pct_final"]) if b.get("yield_pct_final") is not None else None,
        "yield_variance_pct": float(b["yield_variance_pct"]) if b.get("yield_variance_pct") is not None else None,
        "created_at": iso_z3(b["_created_dt"]),
        "updated_at": iso_z3(b.get("_updated_dt", b["_created_dt"])),
        "version": b["version"],
    }


def serialize_batch_input(r):
    return {
        "id": r["id"],
        "processing_batch_id": r["processing_batch_id"],
        "receipt_lot_id": r["receipt_lot_id"],
        "quantity_kg": float(r["quantity_kg"]),
        "provisional_yield_kg": float(r["provisional_yield_kg"]),
        "created_at": iso_z3(r["_created_dt"]),
        "updated_at": iso_z3(r.get("_updated_dt", r["_created_dt"])),
        "version": r["version"],
    }


def serialize_temp_log(t):
    return {
        "id": t["id"],
        "receipt_lot_id": t.get("receipt_lot_id"),
        "processing_batch_id": t.get("processing_batch_id"),
        "interval_start": iso_z(t["interval_start"]),
        "interval_end": iso_z(t["interval_end"]),
        "core_temp_c": float(t["core_temp_c"]),
        "avg_temp_c": float(t["avg_temp_c"]),
        "source": t["source"],
        "created_at": iso_z3(t["_created_dt"]),
    }


def serialize_haccp_record(r):
    return {
        "id": r["id"],
        "hazard_type": r["hazard_type"],
        "receipt_lot_id": r.get("receipt_lot_id"),
        "processing_batch_id": r.get("processing_batch_id"),
        "phase": r["phase"],
        "measured_value": float(r["measured_value"]) if r.get("measured_value") is not None else None,
        "subsample_values": [float(x) for x in r["subsample_values"]] if r.get("subsample_values") is not None else None,
        "measured_at": iso_z(r["measured_at"]),
        "verdict": r["verdict"],
        "corrective_action_id": r.get("corrective_action_id"),
        "created_at": iso_z3(r["_created_dt"]),
    }


def serialize_corrective_action(c):
    return {
        "id": c["id"],
        "source_type": c["source_type"],
        "supplier_id": c.get("supplier_id"),
        "receipt_lot_id": c.get("receipt_lot_id"),
        "processing_batch_id": c.get("processing_batch_id"),
        "monitoring_record_id": c.get("monitoring_record_id"),
        "opened_by": c["opened_by"],
        "status": c["status"],
        "resolution_note": c.get("resolution_note"),
        "closed_by": c.get("closed_by"),
        "recall_id": c.get("recall_id"),
        "created_at": iso_z3(c["_created_dt"]),
        "updated_at": iso_z3(c.get("_updated_dt", c["_created_dt"])),
        "version": c["version"],
    }


def serialize_label(l):
    return {
        "id": l["id"],
        "market_name": l["market_name"],
        "scientific_name": l["scientific_name"],
        "species": l["species"],
        "production_method": l["production_method"],
        "country_of_origin": l["country_of_origin"],
        "keep_frozen_statement": l["keep_frozen_statement"],
        "allergen_statement": l["allergen_statement"],
        "supersedes_label_id": l.get("supersedes_label_id"),
        "status": l["status"],
        "approved_at": iso_z3(l["approved_at"]) if l.get("approved_at") else None,
        "created_at": iso_z3(l["_created_dt"]),
        "updated_at": iso_z3(l.get("_updated_dt", l["_created_dt"])),
        "version": l["version"],
    }


def serialize_finished_lot(l):
    return {
        "id": l["id"],
        "processing_batch_id": l["processing_batch_id"],
        "net_weight_kg": float(l["net_weight_kg"]),
        "product_label_id": l.get("product_label_id"),
        "label_version_pinned": l.get("label_version_pinned"),
        "label_stale": l["label_stale"],
        "allergen_statement": l.get("allergen_statement"),
        "country_of_origin": l.get("country_of_origin"),
        "status": l["status"],
        "released_at": iso_z3(l["released_at"]) if l.get("released_at") else None,
        "created_at": iso_z3(l["_created_dt"]),
        "updated_at": iso_z3(l.get("_updated_dt", l["_created_dt"])),
        "version": l["version"],
    }


def serialize_recall(r):
    return {
        "id": r["id"],
        "corrective_action_id": r["corrective_action_id"],
        "reason": r["reason"],
        "scope_lot_ids": list(r["scope_lot_ids"]),
        "status": r["status"],
        "notified_at": iso_z3(r["notified_at"]) if r.get("notified_at") else None,
        "created_at": iso_z3(r["_created_dt"]),
        "updated_at": iso_z3(r.get("_updated_dt", r["_created_dt"])),
        "version": r["version"],
    }
