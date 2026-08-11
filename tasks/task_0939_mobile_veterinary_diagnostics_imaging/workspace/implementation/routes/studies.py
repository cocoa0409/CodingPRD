"""Studies: ordering, acquisition, upload, image QC, escalation, cancellation,
the turnaround hold/resume pair, repeats and the pricing view (PRD 3.5, 3.8, 3.9)."""

from flask import Blueprint, g

from core import clock, db, envelope, gates
from core.auth import READ_ROLES, authenticate, authorize, require_owner
from core.constants import (
    EQUIPMENT_USAGE_CAP_BETWEEN_QC,
    HOLD_REASON_ENUM,
    MODALITY_ENUM,
    QC_RESULT_ENUM,
    REPEAT_CAP_PER_STUDY,
    REPEAT_CAUSE_ENUM,
)
from core.errors import ApiError
from core.validate import (
    body,
    enum_value,
    opt_str,
    req_id,
    req_int,
    req_str,
)
from routes.common import apply_filters, fk, listing, need, one
from services import cascades, derive, notify, pricing, tat

bp = Blueprint("studies", __name__)


def _study_state_gate(study, allowed):
    """Rung 19: terminal first, then any other wrong from-state."""
    if study["workflow_status"] in ("CANCELLED", "NOT_PERFORMED"):
        raise ApiError("ERR_STUDY_TERMINAL")
    if study["workflow_status"] not in allowed:
        raise ApiError("ERR_STUDY_INVALID_STATE")


def _own_study(study):
    require_owner(g.user_id == derive.clinic_id_of_study(study))


# ==========================================================================
# create / read
# ==========================================================================

@bp.post("/studies")
def create_study():
    authenticate()
    authorize("ClinicUser")
    data = body()
    appt = fk(data, "appointment_id", "appointments", "ERR_APPOINTMENT_NOT_FOUND")
    if appt is not None:
        referral = derive.referral_of_appointment(appt)
        require_owner(referral is not None and g.user_id == referral["clinic_id"])
    req_id(data, "appointment_id")
    modality = req_str(data, "modality")
    body_region = req_str(data, "body_region")
    enum_value(modality, MODALITY_ENUM, "modality")
    referral = derive.referral_of_appointment(appt)
    clinic = db.get("clinics", referral["clinic_id"]) if referral else None
    gates.g2_clinic_not_on_hold(clinic)

    rec = _new_study(
        appointment_id=appt["id"],
        modality=modality,
        body_region=body_region,
        study_kind=referral["study_kind"],
        species=referral["species"],
        priority=referral["priority"],
    )
    return one("studies", rec, 201)


def _new_study(appointment_id, modality, body_region, study_kind, species, priority,
               repeat_of_study_id=None, repeat_cause=None, billing_status="UNBILLED"):
    rec = db.new_record()
    rec.update(
        {
            "appointment_id": appointment_id,
            "equipment_id": None,
            "technician_id": None,
            "repeat_of_study_id": repeat_of_study_id,
            "study_kind": study_kind,
            "species": species,
            "modality": modality,
            "body_region": body_region,
            "priority": priority,
            "priority_source": "NATIVE",
            "workflow_status": "ORDERED",
            "qc_status": "PENDING_QC",
            "tat_status": "ACCRUING",
            "billing_status": billing_status,
            "image_count": 0,
            "acquired_at": None,
            "escalated_at": None,
            "pause_started_at": None,
            "hold_reason": None,
            "repeat_cause": repeat_cause,
            "repeat_count": 0,
            "read_attempt_count": 0,
            "cancellation_fee_cents": 0,
            "cancel_reason": None,
            "_billed_price_basis": None,
            "_billed_base_price_cents": 0,
            "_pause_windows": [],
            "_tat_frozen_elapsed": None,
            "_tat_frozen_paused": None,
            "_tat_breach_notified": False,
        }
    )
    return db.insert("studies", rec)


@bp.get("/studies/<study_id>")
def get_study(study_id):
    authenticate()
    authorize(*READ_ROLES)
    return one("studies", need("studies", study_id, "ERR_STUDY_NOT_FOUND"))


@bp.get("/studies")
def list_studies():
    authenticate()
    authorize(*READ_ROLES)
    rows = db.all_rows("studies")
    for row in rows:
        tat.evaluate(row)
    rows = apply_filters(
        rows,
        {
            "appointment_id": "appointment_id",
            "equipment_id": "equipment_id",
            "technician_id": "technician_id",
            "repeat_of_study_id": "repeat_of_study_id",
            "workflow_status": "workflow_status",
            "qc_status": "qc_status",
            "tat_status": "tat_status",
            "billing_status": "billing_status",
            "priority": "priority",
        },
    )
    return listing("studies", rows)


# ==========================================================================
# acquisition and upload
# ==========================================================================

@bp.post("/studies/<study_id>/acquire")
def acquire_study(study_id):
    authenticate()
    authorize("FieldTech")
    study = need("studies", study_id, "ERR_STUDY_NOT_FOUND")
    data = body()
    # rung 3 — a technician may only acquire as himself.  Pure identity compare.
    raw_tech = data.get("technician_id")
    if isinstance(raw_tech, str) and raw_tech:
        require_owner(raw_tech == g.user_id)
    # rung 4 — body FKs in the endpoint's input order
    equipment = fk(data, "equipment_id", "equipment", "ERR_EQUIPMENT_NOT_FOUND")
    technician = fk(data, "technician_id", "technicians", "ERR_RECORD_NOT_FOUND")
    # rung 5
    req_id(data, "equipment_id")
    req_id(data, "technician_id")
    image_count = req_int(data, "image_count", minimum=0)
    # rung 11 (G4)
    gates.g4_equipment_calibrated(equipment)
    # rung 13
    if study["study_kind"] == "TELERAD":
        raise ApiError("ERR_NOT_APPLICABLE_TO_TELERAD")
    # rung 19
    _study_state_gate(study, ("ORDERED",))
    # rung 23
    if technician["status"] != "ACTIVE":
        raise ApiError("ERR_TECHNICIAN_INACTIVE")
    if study["modality"] not in technician["certified_modalities"]:
        raise ApiError("ERR_TECHNICIAN_NOT_CERTIFIED")
    stop = derive.stop_of_study(study)
    route = derive.route_of_stop(stop)
    # rung 24
    if route is None or technician["id"] != route["technician_id"]:
        raise ApiError("ERR_TECHNICIAN_NOT_ON_ROUTE")
    # rung 25
    if stop is None or stop["status"] != "ARRIVED":
        raise ApiError("ERR_STOP_NOT_ARRIVED")
    # rung 26
    if equipment["assigned_unit_id"] != route["mobile_unit_id"]:
        raise ApiError("ERR_EQUIPMENT_NOT_ON_UNIT")
    # rung 27
    if equipment["modality"] != study["modality"]:
        raise ApiError("ERR_EQUIPMENT_MODALITY_MISMATCH")
    # rung 28
    if equipment["usage_count_since_qc"] >= EQUIPMENT_USAGE_CAP_BETWEEN_QC:
        raise ApiError("ERR_EQUIPMENT_QC_DUE")

    study["workflow_status"] = "ACQUIRED"
    study["acquired_at"] = clock.now()
    study["equipment_id"] = equipment["id"]
    study["technician_id"] = technician["id"]
    study["image_count"] = image_count
    db.touch(study)
    equipment["usage_count_since_qc"] += 1
    db.touch(equipment)
    # The newcomer joins the split, so its siblings' shares FALL.
    pricing.reprice_stop_siblings(stop)
    tat.evaluate(study)
    return one("studies", study)


@bp.post("/studies/<study_id>/upload")
def upload_study(study_id):
    authenticate()
    authorize("ClinicUser")
    study = need("studies", study_id, "ERR_STUDY_NOT_FOUND")
    _own_study(study)
    data = body()
    image_count = req_int(data, "image_count", minimum=0)
    # rung 13
    if study["study_kind"] == "MOBILE":
        raise ApiError("ERR_STUDY_KIND_MISMATCH")
    # rung 19
    _study_state_gate(study, ("ORDERED",))
    study["workflow_status"] = "ACQUIRED"
    study["acquired_at"] = clock.now()
    study["image_count"] = image_count
    db.touch(study)
    tat.evaluate(study)
    return one("studies", study)


# ==========================================================================
# image quality control
# ==========================================================================

@bp.post("/studies/<study_id>/qc")
def qc_study(study_id):
    authenticate()
    authorize("FieldTech")
    study = need("studies", study_id, "ERR_STUDY_NOT_FOUND")
    # No ownership clause at all on this verb (PRD 2.8 rung 3, last bullet).
    data = body()
    result = req_str(data, "qc_result")
    enum_value(result, QC_RESULT_ENUM, "qc_result")
    # rung 19 — workflow from-state, then the quality axis's own from-state.
    # Adjudication of an additional ambiguity: "qc_status must still be
    # PENDING_QC" nominates no code.  It is a from-state of the study on a study
    # action endpoint, so rung 19's "any other wrong from-state" limb
    # (ERR_STUDY_INVALID_STATE) is the only licensed code; inventing one would
    # emit an identifier §5 never attaches to this endpoint.
    _study_state_gate(study, ("ACQUIRED",))
    if study["qc_status"] != "PENDING_QC":
        raise ApiError("ERR_STUDY_INVALID_STATE")

    study["qc_status"] = result
    if result == "ACCEPTED":
        db.touch(study)
    else:
        study["workflow_status"] = "REPEAT_PENDING"
        db.touch(study)
        notify.append(
            derive.clinic_id_of_study(study),
            study["id"],
            "STUDY_REPEAT_REQUIRED",
            "Study %s requires a repeat (%s)." % (study["id"], result),
        )
        cascades.repeat_pending_trip_share_cascade(study)
    tat.evaluate(study)
    return one("studies", study)


# ==========================================================================
# STAT escalation
# ==========================================================================

@bp.post("/studies/<study_id>/escalate-stat")
def escalate_stat(study_id):
    authenticate()
    authorize("ClinicUser")
    study = need("studies", study_id, "ERR_STUDY_NOT_FOUND")
    _own_study(study)
    clinic = derive.clinic_of_study(study)
    gates.g2_clinic_not_on_hold(clinic)
    # rung 19 — permitted from ANY non-terminal workflow state.
    _study_state_gate(
        study,
        (
            "ORDERED",
            "ACQUIRED",
            "ASSIGNED",
            "READ_IN_PROGRESS",
            "PRELIM_REPORTED",
            "FINALIZED",
            "REPEAT_PENDING",
        ),
    )
    # rung 20
    if study["priority"] == "STAT":
        raise ApiError("ERR_ALREADY_STAT")

    study["priority"] = "STAT"
    study["priority_source"] = "UPGRADED"
    study["escalated_at"] = clock.now()
    db.touch(study)
    notify.append(
        derive.clinic_id_of_study(study),
        study["id"],
        "STAT_UPGRADED",
        "Study %s escalated to STAT." % study["id"],
    )
    # The re-anchor + re-target can breach the clock with no time passing at all.
    tat.evaluate(study)
    return one("studies", study)


# ==========================================================================
# cancellation / not-performed
# ==========================================================================

@bp.post("/studies/<study_id>/cancel")
def cancel_study(study_id):
    authenticate()
    authorize("ClinicUser")
    study = need("studies", study_id, "ERR_STUDY_NOT_FOUND")
    _own_study(study)
    data = body()
    cancel_reason = req_str(data, "cancel_reason")
    # rung 19
    _study_state_gate(study, ("ORDERED",))
    stop = derive.stop_of_study(study)
    if stop is not None and stop["status"] == "SERVICED":
        # No dedicated code exists for "the stop must not be SERVICED"; rung 19
        # is the study rung that applies to every /studies action endpoint.
        raise ApiError(
            "ERR_STUDY_INVALID_STATE",
            "The study's route stop has already been serviced.",
        )

    fee = pricing.cancellation_fee_cents(study, "CLINIC")
    study["workflow_status"] = "CANCELLED"
    study["cancel_reason"] = cancel_reason
    study["cancellation_fee_cents"] = fee
    study["billing_status"] = "NON_BILLABLE" if fee == 0 else "UNBILLED"
    db.touch(study)
    # Adjudication of friction 1: cancelling an ORDERED study RE-DERIVES the
    # stop's billable set from scratch — which is provably a no-op on the
    # siblings' shares, because the billable set begins at ACQUIRED and an
    # ORDERED study was never a member of it.  Chosen in reachability terms: the
    # two readings ("cancellation raises surviving siblings' shares" vs "no
    # sibling share moves") differ only in whether the re-derivation runs, and
    # running it satisfies BOTH — it strands neither the endpoint summary's
    # re-allocation step nor the transition note's invariance claim.  The same
    # adjudication is applied to not-performed and to clinic-side appointment
    # cancellation (see routes/intake.py and services/cascades.py).
    if stop is not None:
        pricing.reprice_stop_siblings(stop)
    tat.evaluate(study)
    return one("studies", study)


@bp.post("/studies/<study_id>/not-performed")
def not_performed_study(study_id):
    authenticate()
    authorize("FieldTech")
    study = need("studies", study_id, "ERR_STUDY_NOT_FOUND")
    data = body()
    cancel_reason = req_str(data, "cancel_reason")
    _study_state_gate(study, ("ORDERED",))
    study["workflow_status"] = "NOT_PERFORMED"
    study["cancel_reason"] = cancel_reason
    study["cancellation_fee_cents"] = 0
    study["billing_status"] = "NON_BILLABLE"
    db.touch(study)
    # Adjudication of friction 1 (not-performed limb): same re-derivation, same
    # no-op, same reachability argument as POST /studies/{study_id}/cancel.
    stop = derive.stop_of_study(study)
    if stop is not None:
        pricing.reprice_stop_siblings(stop)
    tat.evaluate(study)
    return one("studies", study)


# ==========================================================================
# turnaround hold / resume
# ==========================================================================

@bp.post("/studies/<study_id>/hold")
def hold_study(study_id):
    authenticate()
    authorize("Specialist")
    study = need("studies", study_id, "ERR_STUDY_NOT_FOUND")
    # Adjudication of friction 3: BOTH rules are enforced as written — rung 3's
    # narrow ownership clause (the actor must hold an ACCEPTED read assignment on
    # this study) AND the transition's wider workflow precondition
    # {ACQUIRED, ASSIGNED, READ_IN_PROGRESS, PRELIM_REPORTED}.  Chosen in
    # reachability terms: enforcing both keeps ERR_NOT_RESOURCE_OWNER reachable
    # on this endpoint and keeps the hold itself reachable (an ACCEPTED
    # assignment exists exactly in READ_IN_PROGRESS and PRELIM_REPORTED, both of
    # which the workflow precondition admits).  Dropping the ownership clause to
    # "widen" the workflow range would instead make a declared rung-3 bullet
    # unreachable, which the governing principle rules out.
    accepted = [
        a
        for a in db.where("read_assignments", study_id=study["id"])
        if a["status"] == "ACCEPTED" and a["specialist_id"] == g.user_id
    ]
    require_owner(bool(accepted))
    data = body()
    hold_reason = req_str(data, "hold_reason")
    enum_value(hold_reason, HOLD_REASON_ENUM, "hold_reason")
    # rung 19
    _study_state_gate(
        study, ("ACQUIRED", "ASSIGNED", "READ_IN_PROGRESS", "PRELIM_REPORTED")
    )
    # rung 20
    if study["tat_status"] != "ACCRUING":
        raise ApiError("ERR_TAT_CLOCK_STATE_INVALID")

    study["tat_status"] = "PAUSED"
    study["pause_started_at"] = clock.now()
    study["hold_reason"] = hold_reason
    db.touch(study)
    return one("studies", study)


@bp.post("/studies/<study_id>/resume")
def resume_study(study_id):
    authenticate()
    authorize("ClinicUser")
    study = need("studies", study_id, "ERR_STUDY_NOT_FOUND")
    _own_study(study)
    data = body()
    # Adjudication of friction 5: `clinical_history` on resume is ACCEPTED (and
    # type-checked) but DISCARDED — no record is written from it.  Chosen in
    # reachability terms: no declared behaviour anywhere in the document reads a
    # value recorded here, so discarding strands nothing; recording it onto the
    # parent Referral would instead mutate a record this endpoint's declared
    # side-effect list never names and bump that referral's `version`, a write no
    # declared behaviour asks for.
    opt_str(data, "clinical_history")
    # rung 20
    if study["tat_status"] != "PAUSED":
        raise ApiError("ERR_TAT_CLOCK_STATE_INVALID")

    study.setdefault("_pause_windows", []).append(
        (study["pause_started_at"], clock.now())
    )
    study["pause_started_at"] = None
    study["hold_reason"] = None
    study["tat_status"] = "ACCRUING"
    db.touch(study)
    tat.evaluate(study)
    return one("studies", study)


# ==========================================================================
# repeats
# ==========================================================================

@bp.post("/studies/<study_id>/repeat")
def repeat_study(study_id):
    authenticate()
    authorize("ClinicUser")
    source = need("studies", study_id, "ERR_STUDY_NOT_FOUND")
    _own_study(source)
    data = body()
    cause = req_str(data, "repeat_cause")
    enum_value(cause, REPEAT_CAUSE_ENUM, "repeat_cause")
    clinic = derive.clinic_of_study(source)
    gates.g2_clinic_not_on_hold(clinic)
    # rung 19 — CANCELLED / NOT_PERFORMED sources are terminal.
    if source["workflow_status"] in ("CANCELLED", "NOT_PERFORMED"):
        raise ApiError("ERR_STUDY_TERMINAL")
    # rung 46
    if source["repeat_count"] >= REPEAT_CAP_PER_STUDY:
        raise ApiError("ERR_REPEAT_CAP_EXCEEDED")
    if cause == "EQUIPMENT_QUARANTINE":
        equipment = db.get("equipment", source.get("equipment_id"))
        if equipment is None or derive.calibration_status(equipment) != "QUARANTINED":
            raise ApiError("ERR_REPEAT_CAUSE_NOT_SUPPORTED")
    elif cause == "QC_FAILURE":
        if source["qc_status"] not in ("REPEAT_REQUIRED", "NON_DIAGNOSTIC"):
            raise ApiError("ERR_REPEAT_CAUSE_NOT_SUPPORTED")
    else:  # CLINICIAN_EXTRA_VIEWS
        if source["workflow_status"] != "FINALIZED" or source["qc_status"] != "ACCEPTED":
            raise ApiError("ERR_REPEAT_CAUSE_NOT_SUPPORTED")

    billing = (
        "NON_BILLABLE"
        if cause in ("QC_FAILURE", "EQUIPMENT_QUARANTINE")
        else "UNBILLED"
    )
    replacement = _new_study(
        appointment_id=source["appointment_id"],
        modality=source["modality"],
        body_region=source["body_region"],
        study_kind=source["study_kind"],
        species=source["species"],
        priority=source["priority"],
        repeat_of_study_id=source["id"],
        repeat_cause=cause,
        billing_status=billing,
    )
    source["repeat_count"] += 1
    db.touch(source)
    if source["workflow_status"] == "REPEAT_PENDING":
        source["workflow_status"] = "NOT_PERFORMED"
        db.touch(source)
    stop = derive.stop_of_study(source)
    if stop is not None:
        pricing.reprice_stop_siblings(stop)
    return one("studies", replacement, 201)


# ==========================================================================
# pricing view
# ==========================================================================

@bp.get("/studies/<study_id>/pricing")
def study_pricing(study_id):
    authenticate()
    authorize("PlatformAdmin", "BillingAdmin", "ClinicUser")
    study = need("studies", study_id, "ERR_STUDY_NOT_FOUND")
    return envelope.object_response(pricing.decomposition(study))
