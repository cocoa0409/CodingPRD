"""Referrals, bed reservations and transport runs (PRD 3.3, 3.4, 3.6)."""
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

bp = Blueprint("referrals", __name__)


# --------------------------------------------------------------------------
# Referral
# --------------------------------------------------------------------------
@bp.post("/referrals")
def create_referral():
    caller = ctx.authenticate(["ReferringClinician"])
    data = ctx.body()
    if isinstance(data.get("referring_unit_id"), str):
        ctx.require_scope(caller, data["referring_unit_id"])
    referring_unit_id = ctx.req_string(data, "referring_unit_id")
    receiving_unit_id = ctx.req_string(data, "receiving_unit_id")
    referral_kind = ctx.req_enum(data, "referral_kind", derive.REFERRAL_KINDS)
    case_reference = ctx.req_string(data, "case_reference")
    gestational_age = ctx.req_number(data, "gestational_age_weeks",
                                    minimum="20.0", maximum="44.0")
    birth_weight = ctx.req_int(data, "birth_weight_grams", minimum=300)
    support_modality = ctx.req_enum(data, "support_modality", derive.SUPPORT_MODALITIES)
    diagnoses = ctx.opt_str_array(data, "diagnoses", [], derive.DIAGNOSES)
    planned_surgery = ctx.opt_bool(data, "planned_surgery", False)
    lookup.unit(referring_unit_id)
    lookup.unit(receiving_unit_id)

    referral = base_record()
    referral.update({
        "referring_unit_id": referring_unit_id,
        "receiving_unit_id": receiving_unit_id,
        "source_admission_id": None,
        "superseded_by_referral_id": None,
        "referral_kind": referral_kind,
        "case_reference": case_reference,
        "gestational_age_weeks": gestational_age,
        "birth_weight_grams": birth_weight,
        "weight_basis_grams": None,
        "support_modality": support_modality,
        "diagnoses": diagnoses,
        "planned_surgery": planned_surgery,
        "status": "PENDING",
        "info_request_rounds": 0,
        "requested_items": None,
        "decision_reason": None,
    })
    db.referrals[referral["id"]] = referral
    return response.created(serialize.referral(referral))


@bp.get("/referrals")
def list_referrals():
    ctx.authenticate(["NetworkAdmin", "UnitDirector", "IntakeNeonatologist",
                      "ReferringClinician", "TransportCoordinator"])
    limit, offset = ctx.pagination()
    active = ctx.filters("referring_unit_id", "receiving_unit_id", "source_admission_id",
                         "superseded_by_referral_id", "status", "referral_kind",
                         "required_level")
    rows = ordered(db.referrals.values())
    for field in ("referring_unit_id", "receiving_unit_id", "source_admission_id",
                  "superseded_by_referral_id", "status", "referral_kind"):
        if field in active:
            rows = [r for r in rows if r[field] == active[field]]
    if "required_level" in active:
        rows = [r for r in rows if derive.required_level(r) == active["required_level"]]
    return response.listing([serialize.referral(r) for r in ctx.page(rows, limit, offset)],
                            limit, offset, len(rows))


@bp.get("/referrals/<referral_id>")
def read_referral(referral_id):
    ctx.authenticate(["NetworkAdmin", "UnitDirector", "IntakeNeonatologist",
                      "ReferringClinician", "TransportCoordinator"])
    return response.ok(serialize.referral(lookup.referral(referral_id)))


@bp.post("/referrals/<referral_id>/request-info")
def request_info(referral_id):
    caller = ctx.authenticate(["IntakeNeonatologist"])
    referral = lookup.referral(referral_id)
    ctx.require_scope(caller, referral["receiving_unit_id"])
    data = ctx.body()
    requested_items = ctx.req_string(data, "requested_items")
    if referral["status"] not in ("PENDING", "DEFERRED"):
        raise ApiError("ERR_INVALID_STATE", 409)
    if referral["info_request_rounds"] >= 2:
        referral["status"] = "DIVERTED"
        referral["decision_reason"] = "INFO_ROUNDS_EXHAUSTED"
    else:
        referral["status"] = "INFO_REQUESTED"
        referral["requested_items"] = requested_items
    touch(referral)
    return response.ok(serialize.referral(referral))


@bp.post("/referrals/<referral_id>/provide-info")
def provide_info(referral_id):
    caller = ctx.authenticate(["ReferringClinician"])
    referral = lookup.referral(referral_id)
    ctx.require_scope(caller, referral["referring_unit_id"])
    data = ctx.body()
    support_modality = ctx.opt_enum(data, "support_modality", derive.SUPPORT_MODALITIES)
    birth_weight = ctx.opt_int(data, "birth_weight_grams", minimum=300)
    gestational_age = ctx.opt_number(data, "gestational_age_weeks",
                                    minimum="20.0", maximum="44.0")
    diagnoses = ctx.opt_str_array(data, "diagnoses", None, derive.DIAGNOSES)
    planned_surgery = ctx.opt_bool(data, "planned_surgery")
    if referral["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409)
    if support_modality is not None:
        referral["support_modality"] = support_modality
    if birth_weight is not None:
        referral["birth_weight_grams"] = birth_weight
    if gestational_age is not None:
        referral["gestational_age_weeks"] = gestational_age
    if diagnoses is not None:
        referral["diagnoses"] = diagnoses
    if planned_surgery is not None:
        referral["planned_surgery"] = planned_surgery
    referral["status"] = "PENDING"
    referral["info_request_rounds"] += 1
    referral["requested_items"] = None
    touch(referral)
    return response.ok(serialize.referral(referral))


@bp.post("/referrals/<referral_id>/accept")
def accept_referral(referral_id):
    caller = ctx.authenticate(["IntakeNeonatologist"])
    referral = lookup.referral(referral_id)
    ctx.require_scope(caller, referral["receiving_unit_id"])
    data = ctx.body()
    expected = ctx.req_int(data, "expected_unit_version")
    unit = lookup.unit(referral["receiving_unit_id"])
    if expected != unit["version"]:
        raise ApiError("ERR_UNIT_VERSION_CONFLICT", 412)
    if referral["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409)

    unit_level = derive.rank(derive.effective_level(unit))
    if derive.rank(derive.required_level(referral)) > unit_level:
        raise ApiError("ERR_LEVEL_CAPABILITY_INSUFFICIENT", 422)
    if unit["designation_status"] == "SUSPENDED":
        raise ApiError("ERR_UNIT_SUSPENDED", 422)

    available = derive.available_bed_count(unit)
    if available == 1 and referral["referral_kind"] != "MATERNAL_ANTENATAL":
        incoming = derive.triage_priority(referral)
        for other in db.referrals.values():
            if other["id"] == referral["id"]:
                continue
            if other["receiving_unit_id"] != unit["id"]:
                continue
            if other["status"] not in ("PENDING", "DEFERRED"):
                continue
            if other["referral_kind"] != "MATERNAL_ANTENATAL":
                continue
            if derive.rank(derive.required_level(other)) > unit_level:
                continue
            if derive.triage_priority(other) > incoming:
                raise ApiError("ERR_MATERNAL_TRANSFER_PREFERENCE", 409)
    if available < 1:
        raise ApiError("ERR_NO_BED_AVAILABLE", 409)

    referral["status"] = "ACCEPTED"
    referral["decision_reason"] = None
    touch(referral)
    cascade.create_hold(unit, referral)
    touch(unit)
    return response.ok(serialize.referral(referral))


@bp.post("/referrals/<referral_id>/decline")
def decline_referral(referral_id):
    caller = ctx.authenticate(["IntakeNeonatologist"])
    referral = lookup.referral(referral_id)
    ctx.require_scope(caller, referral["receiving_unit_id"])
    data = ctx.body()
    reason = ctx.req_enum(data, "decision_reason", derive.DECLINE_REASONS)
    if referral["status"] not in ("PENDING", "INFO_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE", 409)
    referral["status"] = "DECLINED"
    referral["decision_reason"] = reason
    touch(referral)
    return response.ok(serialize.referral(referral))


@bp.post("/referrals/<referral_id>/defer")
def defer_referral(referral_id):
    caller = ctx.authenticate(["IntakeNeonatologist"])
    referral = lookup.referral(referral_id)
    ctx.require_scope(caller, referral["receiving_unit_id"])
    ctx.body()
    unit = lookup.unit(referral["receiving_unit_id"])
    if referral["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409)
    if derive.available_bed_count(unit) >= 1:
        raise ApiError("ERR_DEPENDENT_STATE_INVALID", 409,
                       "A bed is still available; the referral cannot be deferred.")
    referral["status"] = "DEFERRED"
    referral["decision_reason"] = "NO_BED"
    touch(referral)
    return response.ok(serialize.referral(referral))


@bp.post("/referrals/<referral_id>/withdraw")
def withdraw_referral(referral_id):
    caller = ctx.authenticate(["ReferringClinician"])
    referral = lookup.referral(referral_id)
    ctx.require_scope(caller, referral["referring_unit_id"])
    ctx.body()
    if referral["status"] not in ("PENDING", "INFO_REQUESTED", "DEFERRED", "ACCEPTED"):
        raise ApiError("ERR_INVALID_STATE", 409)
    referral["status"] = "WITHDRAWN"
    referral["decision_reason"] = "FAMILY_CHOICE"
    touch(referral)
    hold = cascade.live_hold(referral["id"])
    if hold is not None:
        cascade.release_hold(hold, "REFERRAL_WITHDRAWN")
        unit = db.units.get(hold["unit_id"])
        if unit is not None:
            touch(unit)
    return response.ok(serialize.referral(referral))


@bp.post("/referrals/<referral_id>/revoke-acceptance")
def revoke_acceptance(referral_id):
    caller = ctx.authenticate(["IntakeNeonatologist"])
    referral = lookup.referral(referral_id)
    ctx.require_scope(caller, referral["receiving_unit_id"])
    data = ctx.body()
    expected = ctx.req_int(data, "expected_unit_version")
    unit = lookup.unit(referral["receiving_unit_id"])
    if expected != unit["version"]:
        raise ApiError("ERR_UNIT_VERSION_CONFLICT", 412)
    if referral["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", 409)
    hold = cascade.live_hold(referral["id"])
    if hold is not None:
        for run in cascade.runs_for_reservation(hold["id"]):
            if run["status"] in derive.IN_FLIGHT_RUN_STATUSES:
                raise ApiError("ERR_DEPENDENT_STATE_INVALID", 409,
                               "A transport run is already under way.")
    referral["status"] = "REVOKED"
    touch(referral)
    if hold is not None:
        cascade.release_hold(hold, "REVOKED")
        for run in cascade.runs_for_reservation(hold["id"]):
            if run["status"] == "ACTIVATED":
                cascade.abort_run(run, "CAPABILITY_LOST")
    touch(unit)
    return response.ok(serialize.referral(referral))


# --------------------------------------------------------------------------
# BedReservation (read-only)
# --------------------------------------------------------------------------
@bp.get("/bed-reservations")
def list_reservations():
    ctx.authenticate(["NetworkAdmin", "UnitDirector", "IntakeNeonatologist",
                      "TransportCoordinator"])
    limit, offset = ctx.pagination()
    active = ctx.filters("unit_id", "referral_id", "status", "bed_class")
    rows = ordered(db.reservations.values())
    for field in ("unit_id", "referral_id", "status", "bed_class"):
        if field in active:
            rows = [r for r in rows if r[field] == active[field]]
    return response.listing(
        [serialize.reservation(r) for r in ctx.page(rows, limit, offset)],
        limit, offset, len(rows))


@bp.get("/bed-reservations/<reservation_id>")
def read_reservation(reservation_id):
    ctx.authenticate(["NetworkAdmin", "UnitDirector", "IntakeNeonatologist",
                      "TransportCoordinator"])
    return response.ok(serialize.reservation(lookup.reservation(reservation_id)))


# --------------------------------------------------------------------------
# TransportRun
# --------------------------------------------------------------------------
def _referral_behind(run):
    reservation = db.reservations.get(run["reservation_id"])
    if reservation is None:
        return None
    return db.referrals.get(reservation["referral_id"])


@bp.post("/transport-runs")
def create_run():
    ctx.authenticate(["TransportCoordinator"])
    data = ctx.body()
    reservation_id = ctx.req_string(data, "reservation_id")
    isolette_asset_id = ctx.req_string(data, "isolette_asset_id")
    mode = ctx.req_enum(data, "mode", derive.TRANSPORT_MODES)
    crew = ctx.req_str_array(data, "crew_composition")
    depart_at = ctx.req_dt(data, "depart_at")
    planned_return_at = ctx.req_dt(data, "planned_return_at")
    weather = ctx.opt_bool(data, "weather_minimums_met", True)
    if not planned_return_at > depart_at:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "planned_return_at must be strictly after depart_at.")
    reservation = lookup.reservation(reservation_id)
    asset = lookup.asset(isolette_asset_id)

    if (asset["equipment_code"] != "TRANSPORT_ISOLETTE"
            or derive.asset_status(asset) != "IN_SERVICE"):
        raise ApiError("ERR_ISOLETTE_NOT_SERVICEABLE", 422)
    if asset["unit_id"] != reservation["unit_id"]:
        raise ApiError("ERR_ISOLETTE_UNIT_MISMATCH", 409)

    decontamination_minutes = derive.DECONTAMINATION_MINUTES[mode]
    start = depart_at
    end = clock.plus_minutes(planned_return_at, decontamination_minutes)
    for other in db.runs.values():
        if other["isolette_asset_id"] != isolette_asset_id:
            continue
        if other["status"] == "ABORTED":
            continue
        other_start, other_end = derive.occupation_interval(other)
        if start < other_end and other_start < end:
            raise ApiError("ERR_ISOLETTE_UNAVAILABLE", 409)

    run = base_record()
    run.update({
        "reservation_id": reservation_id,
        "receiving_unit_id": reservation["unit_id"],
        "isolette_asset_id": isolette_asset_id,
        "mode": mode,
        "crew_composition": crew,
        "depart_at": depart_at,
        "planned_return_at": planned_return_at,
        "weather_minimums_met": weather,
        "status": "ACTIVATED",
        "decontamination_minutes": decontamination_minutes,
        "temp_c": None,
        "glucose_mg_dl": None,
        "mean_bp_mmhg": None,
        "spo2_pct": None,
        "stabilization_score": None,
        "stabilization_bundle_complete": False,
        "arrived_at": None,
        "abort_reason": None,
    })
    db.runs[run["id"]] = run
    return response.created(serialize.run(run))


@bp.get("/transport-runs")
def list_runs():
    ctx.authenticate(["NetworkAdmin", "UnitDirector", "IntakeNeonatologist",
                      "TransportCoordinator", "BedsideNurse"])
    limit, offset = ctx.pagination()
    active = ctx.filters("reservation_id", "receiving_unit_id", "isolette_asset_id",
                         "status", "mode")
    rows = ordered(db.runs.values())
    for field in ("reservation_id", "receiving_unit_id", "isolette_asset_id",
                  "status", "mode"):
        if field in active:
            rows = [r for r in rows if r[field] == active[field]]
    return response.listing([serialize.run(r) for r in ctx.page(rows, limit, offset)],
                            limit, offset, len(rows))


@bp.get("/transport-runs/<run_id>")
def read_run(run_id):
    ctx.authenticate(["NetworkAdmin", "UnitDirector", "IntakeNeonatologist",
                      "TransportCoordinator", "BedsideNurse"])
    return response.ok(serialize.run(lookup.run(run_id)))


@bp.post("/transport-runs/<run_id>/dispatch")
def dispatch_run(run_id):
    ctx.authenticate(["TransportCoordinator"])
    run = lookup.run(run_id)
    ctx.body()
    if run["status"] != "ACTIVATED":
        raise ApiError("ERR_INVALID_STATE", 409)
    if "TRANSPORT_RN" not in run["crew_composition"]:
        raise ApiError("ERR_CREW_COMPOSITION_INVALID", 422)
    asset = db.assets.get(run["isolette_asset_id"])
    if asset is None or derive.asset_status(asset) != "IN_SERVICE":
        raise ApiError("ERR_ISOLETTE_NOT_SERVICEABLE", 422)
    if run["mode"] == "GROUND":
        run["status"] = "GROUND_ROLLING"
    else:
        if not run["weather_minimums_met"]:
            raise ApiError("ERR_WEATHER_MINIMUMS_NOT_MET", 422)
        run["status"] = "AIR_LAUNCHED"
    asset["decontamination_ready_at"] = clock.plus_minutes(
        run["planned_return_at"], run["decontamination_minutes"])
    touch(asset)
    touch(run)
    return response.ok(serialize.run(run))


@bp.post("/transport-runs/<run_id>/on-scene")
def on_scene(run_id):
    ctx.authenticate(["TransportCoordinator"])
    run = lookup.run(run_id)
    ctx.body()
    if run["status"] not in ("GROUND_ROLLING", "AIR_LAUNCHED"):
        raise ApiError("ERR_INVALID_STATE", 409)
    run["status"] = "ON_SCENE"
    touch(run)
    return response.ok(serialize.run(run))


@bp.post("/transport-runs/<run_id>/stabilize")
def stabilize(run_id):
    ctx.authenticate(["TransportCoordinator", "BedsideNurse"])
    run = lookup.run(run_id)
    data = ctx.body()
    temp_c = ctx.req_number(data, "temp_c")
    glucose = ctx.req_number(data, "glucose_mg_dl")
    mean_bp = ctx.req_number(data, "mean_bp_mmhg")
    spo2 = ctx.req_number(data, "spo2_pct")
    if run["status"] not in ("ON_SCENE", "STABILIZING"):
        raise ApiError("ERR_INVALID_STATE", 409)
    run["temp_c"] = temp_c
    run["glucose_mg_dl"] = glucose
    run["mean_bp_mmhg"] = mean_bp
    run["spo2_pct"] = spo2
    score, complete = derive.stabilization(run, _referral_behind(run))
    run["stabilization_score"] = score
    run["stabilization_bundle_complete"] = complete
    run["status"] = "STABILIZING"
    touch(run)
    return response.ok(serialize.run(run))


@bp.post("/transport-runs/<run_id>/depart")
def depart(run_id):
    ctx.authenticate(["TransportCoordinator"])
    run = lookup.run(run_id)
    ctx.body()
    if run["status"] != "STABILIZING":
        raise ApiError("ERR_INVALID_STATE", 409)
    referral = _referral_behind(run)
    if referral is None or referral["status"] != "ACCEPTED":
        raise ApiError("ERR_DEPENDENT_STATE_INVALID", 409,
                       "The referral behind the reservation is no longer ACCEPTED.")
    if not run["stabilization_bundle_complete"]:
        raise ApiError("ERR_STABILIZATION_INCOMPLETE", 422)
    run["status"] = "EN_ROUTE"
    touch(run)
    return response.ok(serialize.run(run))


@bp.post("/transport-runs/<run_id>/arrive")
def arrive(run_id):
    ctx.authenticate(["TransportCoordinator"])
    run = lookup.run(run_id)
    data = ctx.body()
    arrived_at = ctx.req_dt(data, "arrived_at")
    if run["status"] != "EN_ROUTE":
        raise ApiError("ERR_INVALID_STATE", 409)
    run["status"] = "ARRIVED"
    run["arrived_at"] = arrived_at
    asset = db.assets.get(run["isolette_asset_id"])
    if asset is not None:
        asset["decontamination_ready_at"] = clock.plus_minutes(
            arrived_at, run["decontamination_minutes"])
        touch(asset)
    touch(run)
    return response.ok(serialize.run(run))


@bp.post("/transport-runs/<run_id>/abort")
def abort(run_id):
    ctx.authenticate(["TransportCoordinator"])
    run = lookup.run(run_id)
    data = ctx.body()
    abort_reason = ctx.req_enum(data, "abort_reason", derive.ABORT_REASONS)
    if run["status"] not in derive.NON_TERMINAL_RUN_STATUSES:
        raise ApiError("ERR_INVALID_STATE", 409)
    reservation = db.reservations.get(run["reservation_id"])
    if reservation is not None and reservation["status"] == "HELD":
        cascade.release_hold(reservation, "TRANSPORT_ABORTED")
    if reservation is not None:
        referral = db.referrals.get(reservation["referral_id"])
        if referral is not None and referral["status"] == "ACCEPTED":
            referral["status"] = "PENDING"
            referral["decision_reason"] = "TRANSPORT_ABORTED"
            touch(referral)
    cascade.abort_run(run, abort_reason)
    return response.ok(serialize.run(run))
