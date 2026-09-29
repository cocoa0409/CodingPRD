"""Admissions, bedside care and milk handling (PRD 3.7, 3.8)."""
from decimal import Decimal

from flask import Blueprint

import cascade
import clock
import ctx
import derive
import lookup
import response
import serialize
from db import base_record, db, ordered, touch
from errors import ApiError

bp = Blueprint("care", __name__)

D0 = Decimal("0")

ADMISSION_READ_ROLES = ["NetworkAdmin", "UnitDirector", "IntakeNeonatologist",
                        "BedsideNurse", "FollowUpCoordinator"]
BATCH_READ_ROLES = ["NetworkAdmin", "UnitDirector", "IntakeNeonatologist", "BedsideNurse"]
TERMINAL_BATCH_STATUSES = ("ADMINISTERED", "DISCARDED")


# --------------------------------------------------------------------------
# Admission
# --------------------------------------------------------------------------
@bp.post("/admissions")
def create_admission():
    caller = ctx.authenticate(["IntakeNeonatologist"])
    data = ctx.body()
    referral_id = ctx.req_string(data, "referral_id")
    referral = lookup.referral(referral_id)
    ctx.require_scope(caller, referral["receiving_unit_id"])
    if referral["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", 409)
    unit = lookup.unit(referral["receiving_unit_id"])

    reservation = cascade.live_hold(referral["id"])
    transport_run_id = None
    if reservation is not None:
        for run in ordered(cascade.runs_for_reservation(reservation["id"])):
            if run["status"] == "ARRIVED":
                transport_run_id = run["id"]

    source_admission = None
    if referral["referral_kind"] == "BACK_TRANSFER":
        source_admission = db.admissions.get(referral.get("source_admission_id"))

    admission = base_record()
    admission.update({
        "unit_id": unit["id"],
        "referral_id": referral["id"],
        "transport_run_id": transport_run_id,
        "back_transfer_source_admission_id": (source_admission["id"]
                                              if source_admission else None),
        "gestational_age_weeks": referral["gestational_age_weeks"],
        "birth_weight_grams": referral["birth_weight_grams"],
        "current_weight_grams": referral["birth_weight_grams"],
        "support_modality": referral["support_modality"],
        "care_status": "ADMITTED",
        "infection_status": "SURVEILLANCE_CLEAR",
        "infection_confirmed_at": None,
        "patient_days": 0,
        "central_line_days": 0,
        "ventilator_days": 0,
        "developmental_round_count": 0,
        "kangaroo_care_sessions": 0,
        "family_presence_minutes": 0,
        "cluster_care_compliant_count": 0,
        "light_cycling_compliant_count": 0,
        "developmental_bundle_score": derive.q2(D0),
        "milk_administered_ml": derive.q1(D0),
        "high_risk_graduate": False,
        "back_transfer_attestation_note": None,
        "discharged_at": None,
        "discharge_disposition": None,
    })
    db.admissions[admission["id"]] = admission

    referral["status"] = "COMPLETED"
    touch(referral)
    if reservation is not None:
        cascade.release_hold(reservation, "ADMITTED", status="OCCUPIED")
    touch(unit)

    if source_admission is not None and source_admission["care_status"] in (
            "BACK_TRANSFER_READY", "BACK_TRANSFER_REQUIRED"):
        source_admission["care_status"] = "TRANSFERRED"
        source_admission["discharged_at"] = clock.now()
        source_admission["discharge_disposition"] = "BACK_TRANSFERRED"
        touch(source_admission)
        source_unit = db.units.get(source_admission["unit_id"])
        if source_unit is not None:
            cascade.promote_queue(source_unit)
            touch(source_unit)

    return response.created(serialize.admission(admission))


@bp.get("/admissions")
def list_admissions():
    ctx.authenticate(ADMISSION_READ_ROLES)
    limit, offset = ctx.pagination()
    active = ctx.filters("unit_id", "referral_id", "transport_run_id",
                         "back_transfer_source_admission_id", "care_status",
                         "infection_status", "current_care_level")
    rows = ordered(db.admissions.values())
    for field in ("unit_id", "referral_id", "transport_run_id",
                  "back_transfer_source_admission_id", "care_status", "infection_status"):
        if field in active:
            rows = [r for r in rows if r[field] == active[field]]
    if "current_care_level" in active:
        rows = [r for r in rows
                if derive.current_care_level(r) == active["current_care_level"]]
    return response.listing(
        [serialize.admission(r) for r in ctx.page(rows, limit, offset)],
        limit, offset, len(rows))


@bp.get("/admissions/<admission_id>")
def read_admission(admission_id):
    ctx.authenticate(ADMISSION_READ_ROLES)
    return response.ok(serialize.admission(lookup.admission(admission_id)))


@bp.post("/admissions/<admission_id>/care-updates")
def care_update(admission_id):
    ctx.authenticate(["BedsideNurse"])
    admission = lookup.admission(admission_id)
    data = ctx.body()
    weight = ctx.req_int(data, "current_weight_grams", minimum=1)
    support = ctx.req_enum(data, "support_modality", derive.SUPPORT_MODALITIES)
    central_line = ctx.opt_bool(data, "central_line_present", False)
    ventilated = ctx.opt_bool(data, "ventilated", False)
    if admission["care_status"] in ("TRANSFERRED", "DISCHARGED", "DECEASED"):
        raise ApiError("ERR_INVALID_STATE", 409)
    admission["current_weight_grams"] = weight
    admission["support_modality"] = support
    admission["patient_days"] += 1
    if central_line:
        admission["central_line_days"] += 1
    if ventilated:
        admission["ventilator_days"] += 1
    if admission["care_status"] == "ADMITTED" and support in ("ROOM_AIR", "CPAP"):
        admission["care_status"] = "STABILIZED"
    touch(admission)
    return response.ok(serialize.admission(admission))


@bp.post("/admissions/<admission_id>/developmental-rounds")
def developmental_round(admission_id):
    ctx.authenticate(["BedsideNurse"])
    admission = lookup.admission(admission_id)
    data = ctx.body()
    kangaroo_minutes = ctx.req_int(data, "kangaroo_care_minutes", minimum=0)
    family_minutes = ctx.req_int(data, "family_presence_minutes", minimum=0)
    cluster = ctx.req_bool(data, "cluster_care_compliant")
    light = ctx.req_bool(data, "light_cycling_compliant")
    if admission["care_status"] in ("TRANSFERRED", "DISCHARGED", "DECEASED"):
        raise ApiError("ERR_INVALID_STATE", 409)
    admission["developmental_round_count"] += 1
    if kangaroo_minutes >= 60:
        admission["kangaroo_care_sessions"] += 1
    admission["family_presence_minutes"] += family_minutes
    if cluster:
        admission["cluster_care_compliant_count"] += 1
    if light:
        admission["light_cycling_compliant_count"] += 1
    derive.recompute_developmental(admission)
    touch(admission)
    return response.ok(serialize.admission(admission))


@bp.post("/admissions/<admission_id>/infection-events")
def infection_event(admission_id):
    caller = ctx.authenticate(["BedsideNurse", "UnitDirector"])
    admission = lookup.admission(admission_id)
    ctx.require_scope(caller, admission["unit_id"])
    data = ctx.body()
    event = ctx.req_enum(data, "event", derive.INFECTION_EVENTS)
    status = admission["infection_status"]

    if event == "SUSPECT":
        if status not in ("SURVEILLANCE_CLEAR", "RESOLVED"):
            raise ApiError("ERR_INVALID_STATE", 409)
        admission["infection_status"] = "SUSPECTED"
        for batch in ordered(derive.admission_batches(admission["id"])):
            if batch["status"] in ("RECEIVED", "VERIFIED", "PARTIALLY_ADMINISTERED"):
                batch["pre_quarantine_status"] = batch["status"]
                batch["status"] = "QUARANTINED"
                touch(batch)
    elif event == "CONFIRM_CLABSI":
        if status != "SUSPECTED":
            raise ApiError("ERR_INVALID_STATE", 409)
        if admission["central_line_days"] < 1:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "A CLABSI cannot be confirmed without a central-line day.")
        admission["infection_status"] = "CONFIRMED_CLABSI"
        admission["infection_confirmed_at"] = clock.now()
    else:
        if status not in ("SUSPECTED", "CONFIRMED_CLABSI"):
            raise ApiError("ERR_INVALID_STATE", 409)
        admission["infection_status"] = "RESOLVED"
        for batch in ordered(derive.admission_batches(admission["id"])):
            if batch["status"] == "QUARANTINED":
                batch["status"] = batch.get("pre_quarantine_status") or "RECEIVED"
                batch["pre_quarantine_status"] = None
                derive.recompute_batch(batch)
                touch(batch)
    touch(admission)
    return response.ok(serialize.admission(admission))


@bp.post("/admissions/<admission_id>/back-transfer-ready")
def back_transfer_ready(admission_id):
    caller = ctx.authenticate(["IntakeNeonatologist"])
    admission = lookup.admission(admission_id)
    ctx.require_scope(caller, admission["unit_id"])
    data = ctx.body()
    note = ctx.req_string(data, "back_transfer_attestation_note")
    if admission["care_status"] != "STABILIZED":
        raise ApiError("ERR_INVALID_STATE", 409)
    if admission["developmental_bundle_score"] < Decimal("60"):
        raise ApiError("ERR_DEVELOPMENTAL_BUNDLE_INCOMPLETE", 422)
    if admission["support_modality"] not in ("ROOM_AIR", "CPAP"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Respiratory support is not risk-appropriate for back transfer.")
    if admission["infection_status"] == "CONFIRMED_CLABSI":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "An active central-line infection blocks back transfer.")
    admission["care_status"] = "BACK_TRANSFER_READY"
    admission["back_transfer_attestation_note"] = note
    touch(admission)
    return response.ok(serialize.admission(admission))


@bp.post("/admissions/<admission_id>/back-transfer-referrals")
def back_transfer_referral(admission_id):
    caller = ctx.authenticate(["IntakeNeonatologist"])
    admission = lookup.admission(admission_id)
    ctx.require_scope(caller, admission["unit_id"])
    data = ctx.body()
    expected = ctx.req_int(data, "expected_admission_version")
    receiving_unit_id = ctx.req_string(data, "receiving_unit_id")
    case_reference = ctx.req_string(data, "case_reference")
    lookup.unit(receiving_unit_id)
    if expected != admission["version"]:
        raise ApiError("ERR_ADMISSION_VERSION_CONFLICT", 412)
    if admission["care_status"] not in ("BACK_TRANSFER_READY", "BACK_TRANSFER_REQUIRED"):
        raise ApiError("ERR_DEPENDENT_STATE_INVALID", 409,
                       "The admission is not ready for back transfer.")

    referral = base_record()
    referral.update({
        "referring_unit_id": admission["unit_id"],
        "receiving_unit_id": receiving_unit_id,
        "source_admission_id": admission["id"],
        "superseded_by_referral_id": None,
        "referral_kind": "BACK_TRANSFER",
        "case_reference": case_reference,
        "gestational_age_weeks": admission["gestational_age_weeks"],
        "birth_weight_grams": admission["birth_weight_grams"],
        "weight_basis_grams": admission["current_weight_grams"],
        "support_modality": admission["support_modality"],
        "diagnoses": [],
        "planned_surgery": False,
        "status": "PENDING",
        "info_request_rounds": 0,
        "requested_items": None,
        "decision_reason": None,
    })
    db.referrals[referral["id"]] = referral

    for earlier in ordered(db.referrals.values()):
        if earlier["id"] == referral["id"]:
            continue
        if earlier.get("source_admission_id") != admission["id"]:
            continue
        if earlier["status"] not in ("PENDING", "DEFERRED"):
            continue
        earlier["status"] = "SUPERSEDED"
        earlier["superseded_by_referral_id"] = referral["id"]
        touch(earlier)
        hold = cascade.live_hold(earlier["id"])
        if hold is not None:
            cascade.release_hold(hold, "REVOKED")

    touch(admission)
    return response.created(serialize.referral(referral))


@bp.post("/admissions/<admission_id>/discharge")
def discharge(admission_id):
    caller = ctx.authenticate(["IntakeNeonatologist"])
    admission = lookup.admission(admission_id)
    ctx.require_scope(caller, admission["unit_id"])
    data = ctx.body()
    disposition = ctx.req_enum(data, "disposition", derive.DISPOSITIONS)
    unit = db.units.get(admission["unit_id"])

    if disposition == "HOME":
        if admission["care_status"] not in ("STABILIZED", "BACK_TRANSFER_READY"):
            raise ApiError("ERR_INVALID_STATE", 409)
        for batch in derive.admission_batches(admission["id"]):
            settled = (batch["status"] in TERMINAL_BATCH_STATUSES
                       or (batch["status"] == "RECEIVED" and batch["remaining_ml"] == 0))
            if not settled:
                raise ApiError("ERR_DEPENDENT_STATE_INVALID", 409,
                               "Milk remains unaccounted for on this admission.")
        admission["care_status"] = "DISCHARGED"
        admission["discharged_at"] = clock.now()
        admission["discharge_disposition"] = "HOME"
        admission["high_risk_graduate"] = (
            derive.eligibility_basis(admission) != "NOT_ELIGIBLE")
    else:
        if admission["care_status"] not in ("ADMITTED", "STABILIZED",
                                           "BACK_TRANSFER_READY",
                                           "BACK_TRANSFER_REQUIRED"):
            raise ApiError("ERR_INVALID_STATE", 409)
        admission["care_status"] = "DECEASED"
        admission["discharged_at"] = clock.now()
        admission["discharge_disposition"] = "DECEASED"
        for batch in ordered(derive.admission_batches(admission["id"])):
            if batch["status"] in TERMINAL_BATCH_STATUSES:
                continue
            batch["discarded_ml"] = derive.q1(batch["discarded_ml"]
                                              + batch["remaining_ml"])
            derive.recompute_batch(batch)
            batch["status"] = "DISCARDED"
            touch(batch)
        for enrollment in ordered(db.enrollments.values()):
            if enrollment["admission_id"] != admission["id"]:
                continue
            if enrollment["status"] not in ("ENROLLED", "SCHEDULED"):
                continue
            enrollment["status"] = "LOST_TO_FOLLOWUP"
            touch(enrollment)

    touch(admission)
    if unit is not None:
        cascade.promote_queue(unit)
        touch(unit)
    return response.ok(serialize.admission(admission))


# --------------------------------------------------------------------------
# MilkBatch
# --------------------------------------------------------------------------
@bp.post("/milk-batches")
def create_batch():
    caller = ctx.authenticate(["BedsideNurse"])
    data = ctx.body()
    admission_id = ctx.req_string(data, "admission_id")
    donor_type = ctx.req_enum(data, "donor_type", derive.DONOR_TYPES)
    volume_ml = ctx.req_number(data, "volume_ml", exclusive_min=0)
    expressed_at = ctx.req_dt(data, "expressed_at")
    label_code = ctx.req_string(data, "label_code")
    lookup.admission(admission_id)

    volume_ml = derive.q1(volume_ml)
    batch = base_record()
    batch.update({
        "admission_id": admission_id,
        "donor_type": donor_type,
        "volume_ml": volume_ml,
        "expressed_at": expressed_at,
        "expires_at": clock.plus_hours(expressed_at,
                                       derive.MILK_EXPIRY_HOURS[donor_type]),
        "label_code": label_code,
        "received_by_user_id": caller.user_id,
        "verified_by_user_id": None,
        "administered_ml": derive.q1(D0),
        "discarded_ml": derive.q1(D0),
        "remaining_ml": volume_ml,
        "status": "RECEIVED",
        "pre_quarantine_status": None,
    })
    db.milk_batches[batch["id"]] = batch
    return response.created(serialize.batch(batch))


@bp.get("/milk-batches")
def list_batches():
    ctx.authenticate(BATCH_READ_ROLES)
    limit, offset = ctx.pagination()
    active = ctx.filters("admission_id", "status", "donor_type")
    rows = ordered(db.milk_batches.values())
    for field in ("admission_id", "status", "donor_type"):
        if field in active:
            rows = [r for r in rows if r[field] == active[field]]
    return response.listing([serialize.batch(r) for r in ctx.page(rows, limit, offset)],
                            limit, offset, len(rows))


@bp.get("/milk-batches/<batch_id>")
def read_batch(batch_id):
    ctx.authenticate(BATCH_READ_ROLES)
    return response.ok(serialize.batch(lookup.batch(batch_id)))


@bp.post("/milk-batches/<batch_id>/verify")
def verify_batch(batch_id):
    caller = ctx.authenticate(["BedsideNurse"])
    batch = lookup.batch(batch_id)
    data = ctx.body()
    label_code = ctx.req_string(data, "label_code")
    if batch["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", 409)
    if label_code != batch["label_code"]:
        raise ApiError("ERR_MILK_LABEL_MISMATCH", 422)
    if caller.user_id == batch["received_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409)
    batch["verified_by_user_id"] = caller.user_id
    batch["status"] = "VERIFIED"
    touch(batch)
    return response.ok(serialize.batch(batch))


@bp.post("/milk-batches/<batch_id>/administrations")
def administer(batch_id):
    ctx.authenticate(["BedsideNurse"])
    batch = lookup.batch(batch_id)
    data = ctx.body()
    volume_ml = derive.q1(ctx.req_number(data, "volume_ml", exclusive_min=0))
    admission = db.admissions.get(batch["admission_id"])
    if admission is not None and admission["care_status"] in ("DISCHARGED", "DECEASED"):
        raise ApiError("ERR_DEPENDENT_STATE_INVALID", 409,
                       "The admission is closed.")
    if batch["status"] not in ("VERIFIED", "PARTIALLY_ADMINISTERED"):
        raise ApiError("ERR_MILK_NOT_ADMINISTRABLE", 422)
    if batch["expires_at"] <= clock.now():
        raise ApiError("ERR_MILK_EXPIRED", 422)
    if volume_ml > batch["remaining_ml"]:
        raise ApiError("ERR_MILK_VOLUME_EXCEEDED", 422)
    batch["administered_ml"] = derive.q1(batch["administered_ml"] + volume_ml)
    derive.recompute_batch(batch)
    touch(batch)
    if admission is not None:
        derive.recompute_milk_rollup(admission)
        touch(admission)
    return response.ok(serialize.batch(batch))


@bp.post("/milk-batches/<batch_id>/administrations/reverse")
def reverse_administration(batch_id):
    ctx.authenticate(["BedsideNurse"])
    batch = lookup.batch(batch_id)
    data = ctx.body()
    volume_ml = derive.q1(ctx.req_number(data, "volume_ml", exclusive_min=0))
    if volume_ml > batch["administered_ml"]:
        raise ApiError("ERR_MILK_VOLUME_EXCEEDED", 422)
    batch["administered_ml"] = derive.q1(batch["administered_ml"] - volume_ml)
    derive.recompute_batch(batch)
    if batch["administered_ml"] == 0 and batch["status"] not in (
            "DISCARDED", "QUARANTINED", "RECEIVED"):
        batch["status"] = "VERIFIED"
    touch(batch)
    admission = db.admissions.get(batch["admission_id"])
    if admission is not None:
        derive.recompute_milk_rollup(admission)
        touch(admission)
    return response.ok(serialize.batch(batch))


@bp.post("/milk-batches/<batch_id>/discard")
def discard_batch(batch_id):
    ctx.authenticate(["BedsideNurse"])
    batch = lookup.batch(batch_id)
    data = ctx.body()
    reason = ctx.req_enum(data, "reason", derive.DISCARD_REASONS)
    if batch["status"] == "DISCARDED":
        raise ApiError("ERR_INVALID_STATE", 409)
    batch["discarded_ml"] = derive.q1(batch["discarded_ml"] + batch["remaining_ml"])
    derive.recompute_batch(batch)
    batch["status"] = "DISCARDED"
    batch["pre_quarantine_status"] = None
    del reason
    touch(batch)
    return response.ok(serialize.batch(batch))
