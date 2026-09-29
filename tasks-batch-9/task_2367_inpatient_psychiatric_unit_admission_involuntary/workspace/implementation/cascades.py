"""Cascade discipline (PRD §2.8): derived-counter recomputation and chained side effects.

Every link refreshes updated_at and increments version on the row it touches, and
every derived counter is recomputed from the underlying rows, never adjusted by a delta.
"""

from store import db, ordered, touch
import calc


# --------------------------------------------------------------------------- #
# derived counter recomputation
# --------------------------------------------------------------------------- #
def recompute_patient_hold_count(patient):
    patient["active_hold_count"] = len(
        [h for h in db.holds.values() if h["patient_id"] == patient["id"] and h["status"] == "ACTIVE"]
    )
    touch(patient)


def recompute_clinician_docket(clinician):
    clinician["booked_docket_minutes"] = calc.booked_docket_minutes(clinician["id"])
    touch(clinician)


def recompute_clinician_docket_by_id(clinician_id):
    clinician = db.clinicians.get(clinician_id)
    if clinician is not None:
        recompute_clinician_docket(clinician)


def recompute_petition_continuances(petition):
    petition["continuance_count"] = len(
        [
            h
            for h in db.hearings.values()
            if h["petition_id"] == petition["id"] and h["status"] == "CONTINUED"
        ]
    )


def recompute_admission_staffing(admission):
    admission["observation_staff_quarter_hours"] = calc.observation_staffing_quarter_hours(
        admission["id"]
    )
    touch(admission)


def recompute_unit(unit, allow_promotion=True):
    """Run the four-step availability computation; bump version; maybe promote."""
    if unit is None:
        return
    previous_posture = unit["posture"]
    calc.compute_unit_counters(unit)
    touch(unit)
    if allow_promotion and previous_posture == "CLOSED" and unit["posture"] != "CLOSED":
        run_queued_promotion(unit)


def recompute_unit_by_id(unit_id, allow_promotion=True):
    recompute_unit(db.units.get(unit_id), allow_promotion=allow_promotion)


# --------------------------------------------------------------------------- #
# queued admission promotion
# --------------------------------------------------------------------------- #
def run_queued_promotion(unit):
    """Exactly one promotion per posture transition out of CLOSED."""
    for admission in calc.promotion_queue(unit["id"]):
        patient = db.patients.get(admission["patient_id"]) or {}
        bed = calc.select_bed(unit, admission, patient)
        if bed is None:
            # The winner cannot be placed; no promotion happens.
            return
        occupy_bed(admission, bed)
        recompute_unit(unit, allow_promotion=False)
        return


def occupy_bed(admission, bed):
    admission["bed_id"] = bed["id"]
    admission["placed_at"] = db.now()
    admission["placement_status"] = "PLACED"
    touch(admission)
    bed["status"] = "OCCUPIED"
    touch(bed)


# --------------------------------------------------------------------------- #
# hold closure cascades
# --------------------------------------------------------------------------- #
def _patient_admissions_in_scope(patient_id):
    return ordered(
        [
            a
            for a in db.admissions.values()
            if a["patient_id"] == patient_id
            and a["placement_status"] in ("PENDING_PLACEMENT", "PLACED")
        ]
    )


def grant_pending_discharge_requests(admission, responding_clinician_id):
    """Discharge-request link of the hold-closure chain."""
    for request_row in ordered(
        [
            d
            for d in db.discharge_requests.values()
            if d["admission_id"] == admission["id"] and d["status"] == "PENDING"
        ]
    ):
        request_row["status"] = "GRANTED_DISCHARGE"
        request_row["decision"] = "GRANT"
        if responding_clinician_id is not None:
            request_row["responding_clinician_id"] = responding_clinician_id
        touch(request_row)
        advance_placement_on_grant(admission)


def advance_placement_on_grant(admission):
    if admission["placement_status"] == "PLACED":
        admission["placement_status"] = "DISCHARGE_READY"
        touch(admission)
    elif admission["placement_status"] == "PENDING_PLACEMENT":
        admission["placement_status"] = "CANCELLED"
        touch(admission)


def close_hold_cascade(hold, kind, responding_clinician_id=None):
    """Shared closure chain for rescission, statutory expiry and court denial.

    kind: 'RESCIND' | 'EXPIRY' | 'COURT_DENIED'
    """
    patient = db.patients.get(hold["patient_id"])
    if patient is None:
        return
    recompute_patient_hold_count(patient)
    if patient["active_hold_count"] != 0:
        return

    units_to_recount = []
    for admission in _patient_admissions_in_scope(patient["id"]):
        changed = False
        if admission["legal_status"] == "INVOLUNTARY":
            admission["legal_status"] = "VOLUNTARY"
            changed = True
        if (
            kind == "EXPIRY"
            and admission["placement_status"] == "PLACED"
            and not admission["rights_violation_flag"]
        ):
            admission["rights_violation_flag"] = True
            changed = True
            if admission["unit_id"] not in units_to_recount:
                units_to_recount.append(admission["unit_id"])
        if changed:
            touch(admission)
        if kind in ("RESCIND", "COURT_DENIED"):
            grant_pending_discharge_requests(admission, responding_clinician_id)

    for unit_id in units_to_recount:
        recompute_unit_by_id(unit_id)


# --------------------------------------------------------------------------- #
# rights violations
# --------------------------------------------------------------------------- #
def flag_rights_violation(admission):
    if not admission["rights_violation_flag"]:
        admission["rights_violation_flag"] = True
        touch(admission)
    recompute_unit_by_id(admission["unit_id"])


# --------------------------------------------------------------------------- #
# restraint episode finalization
# --------------------------------------------------------------------------- #
def finalize_episode(episode, released_at, actual_duration_minutes, new_status):
    episode["released_at"] = released_at
    episode["actual_duration_minutes"] = actual_duration_minutes
    required, satisfied, grid_pct, raw_pct = calc.monitoring_compliance(
        episode, actual_duration_minutes
    )
    episode["required_check_count"] = required
    episode["grid_satisfied_slot_count"] = satisfied
    episode["grid_compliance_pct"] = grid_pct
    episode["raw_compliance_pct"] = raw_pct
    episode["status"] = new_status
    touch(episode)
