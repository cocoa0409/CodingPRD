"""Entity helpers: creation of common fields, lazy expiry, derived-field
reconciliation, and serialization. Pure data manipulation over db dicts.
"""
import db
import calculations as calc
import timeutil


# ---------------------------------------------------------------------------
# Common system fields
# ---------------------------------------------------------------------------
def init_common(record):
    """Attach id, created_at, updated_at, version=1 (first-class records)."""
    rid = db.new_id()
    ts = db.now_iso()
    record["id"] = rid
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version on a mutation."""
    record["updated_at"] = db.now_iso()
    record["version"] = record.get("version", 1) + 1


def touch_no_version(record):
    """Refresh updated_at only (used where version bump is not specified by PRD)."""
    record["updated_at"] = db.now_iso()


# ---------------------------------------------------------------------------
# Facility clock
# ---------------------------------------------------------------------------
def facility_clock(facility):
    return timeutil.parse_iso(facility["current_utc"])


# ---------------------------------------------------------------------------
# Lazy expiry
# ---------------------------------------------------------------------------
def refresh_prescription_expiry(presc):
    """Lazily move ACTIVE -> EXPIRED when current_utc > written_utc + 180 days."""
    if presc["status"] != "ACTIVE":
        return
    facility = db.facilities.get(presc["facility_id"])
    if facility is None:
        return
    current = facility_clock(facility)
    written = timeutil.parse_iso(presc["written_utc"])
    deadline = timeutil.add_days(written, calc.PRESCRIPTION_VALIDITY_DAYS)
    if current > deadline:
        presc["status"] = "EXPIRED"
        touch(presc)


def refresh_lot_expiry(lot):
    """Lazily move AVAILABLE -> EXPIRED when expiration_utc <= current_utc."""
    if lot["status"] != "AVAILABLE":
        return
    facility = db.facilities.get(lot["facility_id"])
    if facility is None:
        return
    current = facility_clock(facility)
    expiry = timeutil.parse_iso(lot["expiration_utc"])
    if expiry <= current:
        lot["status"] = "EXPIRED"
        touch(lot)


# ---------------------------------------------------------------------------
# Derived-field reconciliation
# ---------------------------------------------------------------------------
def recompute_remaining_grams(lot):
    """remaining_grams = initial_grams - sum(grams_used over usages whose batch
    status is neither DRAFT nor REJECTED)."""
    used = 0.0
    for usage in db.batch_ingredient_usages.values():
        if usage["ingredient_lot_id"] != lot["id"]:
            continue
        batch = db.compounding_batches.get(usage["compounding_batch_id"])
        if batch is None:
            continue
        if batch["status"] in ("DRAFT", "REJECTED"):
            continue
        used += usage["grams_used"]
    lot["remaining_grams"] = calc.remaining_grams(lot["initial_grams"], used)
    return lot["remaining_grams"]


def recompute_ledger(ledger):
    """Recompute window_start_utc, consumed_units, remaining_units against the clock."""
    mfr = db.master_formulation_records.get(ledger["master_formulation_record_id"])
    if mfr is None:
        return ledger
    facility = db.facilities.get(mfr["facility_id"])
    current = facility_clock(facility)
    window_days = mfr["anticipatory_window_days"]
    window_start = timeutil.add_days(current, -window_days)

    consumed = 0
    for batch in db.compounding_batches.values():
        if batch["master_formulation_record_id"] != mfr["id"]:
            continue
        if batch["purpose"] != "OFFICE_USE":
            continue
        if batch["status"] != "RELEASED":
            continue
        released = batch.get("released_at_utc")
        if released is None:
            continue
        released_dt = timeutil.parse_iso(released)
        if released_dt >= window_start:
            consumed += batch.get("actual_yield_units") or 0

    remaining = max(0, mfr["anticipatory_max_units"] - consumed)
    ledger["window_start_utc"] = timeutil.format_iso(window_start)
    ledger["consumed_units"] = consumed
    ledger["remaining_units"] = remaining
    return ledger


def ledger_for_mfr(mfr_id):
    for ledger in db.anticipatory_ledgers.values():
        if ledger["master_formulation_record_id"] == mfr_id:
            return ledger
    return None


# ---------------------------------------------------------------------------
# Serialization — emit fields in declared order, parse-safe copies
# ---------------------------------------------------------------------------
def serialize_facility(f):
    return {
        "id": f["id"],
        "name": f["name"],
        "registration_type": f["registration_type"],
        "state_code": f["state_code"],
        "current_utc": f["current_utc"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def serialize_mfr(m):
    return {
        "id": m["id"],
        "facility_id": m["facility_id"],
        "name": m["name"],
        "dosage_form": m["dosage_form"],
        "is_sterile": m["is_sterile"],
        "default_bud_days_nonsterile": m["default_bud_days_nonsterile"],
        "theoretical_yield_units": m["theoretical_yield_units"],
        "anticipatory_window_days": m["anticipatory_window_days"],
        "anticipatory_max_units": m["anticipatory_max_units"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def serialize_lot(l):
    return {
        "id": l["id"],
        "facility_id": l["facility_id"],
        "parent_lot_id": l.get("parent_lot_id"),
        "component_name": l["component_name"],
        "lot_number": l["lot_number"],
        "labeled_potency_pct": l["labeled_potency_pct"],
        "endotoxin_eu_per_mg": l["endotoxin_eu_per_mg"],
        "initial_grams": l["initial_grams"],
        "remaining_grams": l["remaining_grams"],
        "expiration_utc": l["expiration_utc"],
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def serialize_env_log(e):
    return {
        "id": e["id"],
        "facility_id": e["facility_id"],
        "usp_chapter": e["usp_chapter"],
        "reading_type": e["reading_type"],
        "measured_value": e["measured_value"],
        "action_limit": e["action_limit"],
        "in_spec": e["in_spec"],
        "reading_utc": e["reading_utc"],
        "created_at": e["created_at"],
    }


def serialize_prescription(p):
    return {
        "id": p["id"],
        "facility_id": p["facility_id"],
        "master_formulation_record_id": p["master_formulation_record_id"],
        "patient_name": p["patient_name"],
        "prescriber_npi": p["prescriber_npi"],
        "units_prescribed": p["units_prescribed"],
        "units_dispensed": p["units_dispensed"],
        "written_utc": p["written_utc"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_batch(b):
    return {
        "id": b["id"],
        "facility_id": b["facility_id"],
        "master_formulation_record_id": b["master_formulation_record_id"],
        "purpose": b["purpose"],
        "prescription_id": b.get("prescription_id"),
        "compiled_by_user_id": b.get("compiled_by_user_id"),
        "released_by_user_id": b.get("released_by_user_id"),
        "theoretical_yield_units": b["theoretical_yield_units"],
        "actual_yield_units": b.get("actual_yield_units"),
        "yield_variance_pct": b.get("yield_variance_pct"),
        "released_at_utc": b.get("released_at_utc"),
        "assigned_bud_utc": b.get("assigned_bud_utc"),
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_usage(u):
    return {
        "id": u["id"],
        "compounding_batch_id": u["compounding_batch_id"],
        "ingredient_lot_id": u["ingredient_lot_id"],
        "grams_used": u["grams_used"],
        "potency_adjusted_grams": u["potency_adjusted_grams"],
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
    }


def serialize_qc(q):
    return {
        "id": q["id"],
        "compounding_batch_id": q["compounding_batch_id"],
        "test_type": q["test_type"],
        "measured_value": q.get("measured_value"),
        "lower_limit": q.get("lower_limit"),
        "upper_limit": q.get("upper_limit"),
        "result": q["result"],
        "created_at": q["created_at"],
        "updated_at": q["updated_at"],
        "version": q["version"],
    }


def serialize_finished(fp):
    return {
        "id": fp["id"],
        "compounding_batch_id": fp["compounding_batch_id"],
        "facility_id": fp["facility_id"],
        "unit_serial": fp["unit_serial"],
        "label_text": fp["label_text"],
        "beyond_use_utc": fp["beyond_use_utc"],
        "qc_status": fp["qc_status"],
        "dispense_status": fp["dispense_status"],
        "created_at": fp["created_at"],
        "updated_at": fp["updated_at"],
        "version": fp["version"],
    }


def serialize_dispense(d):
    return {
        "id": d["id"],
        "facility_id": d["facility_id"],
        "finished_preparation_id": d["finished_preparation_id"],
        "prescription_id": d.get("prescription_id"),
        "office_account_name": d.get("office_account_name"),
        "dispensed_utc": d["dispensed_utc"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def serialize_ledger(le):
    return {
        "id": le["id"],
        "master_formulation_record_id": le["master_formulation_record_id"],
        "window_start_utc": le.get("window_start_utc"),
        "consumed_units": le.get("consumed_units"),
        "remaining_units": le.get("remaining_units"),
        "created_at": le["created_at"],
        "updated_at": le["updated_at"],
        "version": le["version"],
    }


def serialize_recall(r):
    return {
        "id": r["id"],
        "facility_id": r["facility_id"],
        "compounding_batch_id": r["compounding_batch_id"],
        "reason": r["reason"],
        "classification": r["classification"],
        "units_in_scope": r["units_in_scope"],
        "units_reconciled": r["units_reconciled"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
