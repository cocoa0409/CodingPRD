import db
import util


def patient_prescriptions(patient_id):
    return [rx for rx in db.prescriptions.values() if rx["patient_id"] == patient_id]


def reconcile(patient_id):
    """Recompute the patient's ControlledSubstanceLedger accounts and the
    patient's current_daily_med_mg from the current prescription states.

    total_active_med_mg = sum(provisional) over ACTIVE + TAPERING
    suspended_med_mg     = sum(provisional) over SUSPENDED
    discontinued_med_mg  = sum(provisional) over DISCONTINUED
    Patient.current_daily_med_mg = round(active total, 2)

    Mutates the ledger row (updated_at/version bumped) and the patient row.
    """
    rxs = patient_prescriptions(patient_id)
    active = 0.0
    suspended = 0.0
    discontinued = 0.0
    for rx in rxs:
        prov = rx.get("provisional_daily_med_mg") or 0.0
        if rx["status"] in ("ACTIVE", "TAPERING"):
            active += prov
        elif rx["status"] == "SUSPENDED":
            suspended += prov
        elif rx["status"] == "DISCONTINUED":
            discontinued += prov

    active = util.round2(active)
    suspended = util.round2(suspended)
    discontinued = util.round2(discontinued)

    ledger_id = db.ledger_by_patient.get(patient_id)
    if ledger_id is not None:
        ledger = db.ledgers[ledger_id]
        ledger["total_active_med_mg"] = active
        ledger["suspended_med_mg"] = suspended
        ledger["discontinued_med_mg"] = discontinued
        db.touch(ledger)

    patient = db.patients.get(patient_id)
    if patient is not None:
        patient["current_daily_med_mg"] = active
        patient["open_uds_count"] = _open_uds_count(patient_id)
        db.touch(patient)


def _open_uds_count(patient_id):
    return sum(
        1 for u in db.urine_drug_screens.values()
        if u["patient_id"] == patient_id and u["status"] in ("SCHEDULED", "COLLECTED")
    )


def refresh_open_uds_count(patient_id):
    patient = db.patients.get(patient_id)
    if patient is not None:
        patient["open_uds_count"] = _open_uds_count(patient_id)
        db.touch(patient)


def compliance_cascade(patient):
    """FLAGGED cascade: set compliance_flag = FLAGGED, suspend every ACTIVE or
    TAPERING opioid prescription for the patient, then reconcile the ledger.

    Shared by inconsistent-UDS result and inconsistent pill-count audit.
    """
    patient["compliance_flag"] = "FLAGGED"
    db.touch(patient)
    _suspend_active_prescriptions(patient["id"])
    reconcile(patient["id"])


def _suspend_active_prescriptions(patient_id):
    for rx in db.prescriptions.values():
        if rx["patient_id"] == patient_id and rx["status"] in ("ACTIVE", "TAPERING"):
            rx["status"] = "SUSPENDED"
            db.touch(rx)
