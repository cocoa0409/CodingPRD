"""Clock, sweep, units, standards, credentials, equipment and designation
reviews (PRD 3.1, 3.2)."""
from flask import Blueprint

import cascade
import clock
import ctx
import derive
import lookup
import response
import serialize
from ctx import ALL_ROLES
from db import base_record, db, ordered, touch
from errors import ApiError

bp = Blueprint("network", __name__)


# --------------------------------------------------------------------------
# Operational / test-driving
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    ctx.authenticate(["NetworkAdmin"])
    data = ctx.body()
    instant = ctx.req_dt(data, "current_utc")
    clock.set_now(instant)
    return response.ok({"current_utc": clock.fmt(instant)})


@bp.post("/ops/run-capacity-sweep")
def capacity_sweep():
    ctx.authenticate(["NetworkAdmin"])
    data = ctx.body()
    unit_id = ctx.opt_string(data, "unit_id")
    if unit_id is not None:
        lookup.unit(unit_id)
    return response.ok(cascade.run_capacity_sweep(unit_id))


# --------------------------------------------------------------------------
# NicuUnit
# --------------------------------------------------------------------------
@bp.post("/nicu-units")
def create_unit():
    ctx.authenticate(["NetworkAdmin"])
    data = ctx.body()
    name = ctx.req_string(data, "name")
    hospital_type = ctx.req_enum(data, "hospital_type", derive.HOSPITAL_TYPES)
    staffed_bed_target = ctx.req_int(data, "staffed_bed_target", minimum=1)
    designated_level = ctx.opt_enum(data, "designated_level", derive.LEVELS, "LEVEL_I")
    transport_capable = ctx.opt_bool(data, "transport_capable", False)
    annual_admission_volume = ctx.opt_int(data, "annual_admission_volume", 0, minimum=0)
    followup_capacity = ctx.opt_int(data, "followup_clinic_daily_capacity", 0, minimum=0)

    unit = base_record()
    unit.update({
        "name": name,
        "hospital_type": hospital_type,
        "designated_level": designated_level,
        "designation_status": "PROVISIONAL",
        "staffed_bed_target": staffed_bed_target,
        "transport_capable": transport_capable,
        "annual_admission_volume": annual_admission_volume,
        "followup_clinic_daily_capacity": followup_capacity,
        "quality_flag": "WITHIN_BENCHMARK",
    })
    db.units[unit["id"]] = unit
    return response.created(serialize.unit(unit))


@bp.get("/nicu-units")
def list_units():
    ctx.authenticate(ALL_ROLES)
    limit, offset = ctx.pagination()
    active = ctx.filters("hospital_type", "designation_status", "census_posture")
    rows = ordered(db.units.values())
    if "hospital_type" in active:
        rows = [u for u in rows if u["hospital_type"] == active["hospital_type"]]
    if "designation_status" in active:
        rows = [u for u in rows if u["designation_status"] == active["designation_status"]]
    if "census_posture" in active:
        rows = [u for u in rows if derive.census_posture(u) == active["census_posture"]]
    return response.listing([serialize.unit(u) for u in ctx.page(rows, limit, offset)],
                            limit, offset, len(rows))


@bp.get("/nicu-units/<unit_id>")
def read_unit(unit_id):
    ctx.authenticate(ALL_ROLES)
    unit = lookup.unit(unit_id)
    return response.ok(serialize.unit(unit))


@bp.patch("/nicu-units/<unit_id>")
def patch_unit(unit_id):
    caller = ctx.authenticate(["NetworkAdmin", "UnitDirector"])
    unit = lookup.unit(unit_id)
    ctx.require_scope(caller, unit_id)
    data = ctx.body()
    expected = ctx.req_int(data, "expected_unit_version")
    staffed_bed_target = ctx.opt_int(data, "staffed_bed_target", minimum=1)
    followup_capacity = ctx.opt_int(data, "followup_clinic_daily_capacity", minimum=0)
    annual_volume = ctx.opt_int(data, "annual_admission_volume", minimum=0)
    transport_capable = ctx.opt_bool(data, "transport_capable")
    if expected != unit["version"]:
        raise ApiError("ERR_UNIT_VERSION_CONFLICT", 412)
    if staffed_bed_target is not None:
        unit["staffed_bed_target"] = staffed_bed_target
    if followup_capacity is not None:
        unit["followup_clinic_daily_capacity"] = followup_capacity
    if annual_volume is not None:
        unit["annual_admission_volume"] = annual_volume
    if transport_capable is not None:
        unit["transport_capable"] = transport_capable
    touch(unit)
    return response.ok(serialize.unit(unit))


@bp.get("/nicu-units/<unit_id>/capacity-projection")
def capacity_projection(unit_id):
    ctx.authenticate(["NetworkAdmin", "UnitDirector", "IntakeNeonatologist",
                      "TransportCoordinator"])
    unit = lookup.unit(unit_id)
    committed = derive.available_bed_count(unit)
    ready = derive.back_transfer_ready_count(unit)
    expiring = derive.expiring_hold_count(unit)
    return response.ok({
        "unit_id": unit["id"],
        "committed_available": committed,
        "forecast_available": committed + ready + expiring,
        "back_transfer_ready_count": ready,
        "expiring_hold_count": expiring,
        "census_posture": derive.census_posture(unit),
        "required_nurse_count": derive.required_nurse_count(unit),
        "deferral_queue_depth": derive.deferral_queue_depth(unit),
    })


@bp.get("/nicu-units/<unit_id>/deferral-queue")
def deferral_queue(unit_id):
    ctx.authenticate(["NetworkAdmin", "UnitDirector", "IntakeNeonatologist"])
    unit = lookup.unit(unit_id)
    limit, offset = ctx.pagination()
    rows = [r for r in db.referrals.values()
            if r["receiving_unit_id"] == unit["id"] and r["status"] == "DEFERRED"]
    rows.sort(key=lambda r: (
        -derive.triage_priority(r),
        0 if derive.maternal_transfer_preferred(r) else 1,
        r["created_at"],
        r["_seq"],
    ))
    return response.listing([serialize.referral(r) for r in ctx.page(rows, limit, offset)],
                            limit, offset, len(rows))


# --------------------------------------------------------------------------
# DesignationStandard
# --------------------------------------------------------------------------
@bp.post("/designation-standards")
def create_standard():
    ctx.authenticate(["NetworkAdmin"])
    data = ctx.body()
    level = ctx.req_enum(data, "level", derive.LEVELS)
    credential_codes = ctx.req_str_array(data, "required_credential_codes",
                                         derive.CREDENTIAL_CODES)
    equipment_codes = ctx.req_str_array(data, "required_equipment_codes",
                                        derive.EQUIPMENT_CODES)
    denominator = ctx.req_number(data, "nurse_patient_ratio_denominator", exclusive_min=0)
    min_volume = ctx.req_int(data, "min_annual_volume", minimum=1)
    transport_required = ctx.req_bool(data, "transport_capability_required")
    min_score = ctx.req_number(data, "min_compliance_score")
    floor_score = ctx.req_number(data, "conditional_floor_score")
    if derive.standard_for_level(level) is not None:
        raise ApiError("ERR_DUPLICATE_STANDARD", 409)

    standard = base_record(with_version=False)
    standard.update({
        "level": level,
        "required_credential_codes": credential_codes,
        "required_equipment_codes": equipment_codes,
        "nurse_patient_ratio_denominator": denominator,
        "min_annual_volume": min_volume,
        "transport_capability_required": transport_required,
        "min_compliance_score": min_score,
        "conditional_floor_score": floor_score,
    })
    db.standards[standard["id"]] = standard
    return response.created(serialize.standard(standard))


@bp.get("/designation-standards")
def list_standards():
    ctx.authenticate(ALL_ROLES)
    limit, offset = ctx.pagination()
    active = ctx.filters("level")
    rows = ordered(db.standards.values())
    if "level" in active:
        rows = [s for s in rows if s["level"] == active["level"]]
    return response.listing([serialize.standard(s) for s in ctx.page(rows, limit, offset)],
                            limit, offset, len(rows))


@bp.get("/designation-standards/<standard_id>")
def read_standard(standard_id):
    ctx.authenticate(ALL_ROLES)
    return response.ok(serialize.standard(lookup.standard(standard_id)))


# --------------------------------------------------------------------------
# StaffCredential
# --------------------------------------------------------------------------
@bp.post("/staff-credentials")
def create_credential():
    caller = ctx.authenticate(["NetworkAdmin", "UnitDirector"])
    data = ctx.body()
    unit_id = ctx.req_string(data, "unit_id")
    credential_code = ctx.req_enum(data, "credential_code", derive.CREDENTIAL_CODES)
    holder_reference = ctx.req_string(data, "holder_reference")
    fte = ctx.req_number(data, "fte", exclusive_min=0)
    expires_on = ctx.req_dt(data, "expires_on")
    lookup.unit(unit_id)
    ctx.require_scope(caller, unit_id)

    credential = base_record()
    credential.update({
        "unit_id": unit_id,
        "credential_code": credential_code,
        "holder_reference": holder_reference,
        "fte": fte,
        "expires_on": expires_on,
        "revoked_at": None,
    })
    db.credentials[credential["id"]] = credential
    return response.created(serialize.credential(credential))


@bp.get("/staff-credentials")
def list_credentials():
    ctx.authenticate(["NetworkAdmin", "UnitDirector", "IntakeNeonatologist"])
    limit, offset = ctx.pagination()
    active = ctx.filters("unit_id", "credential_code", "status")
    rows = ordered(db.credentials.values())
    if "unit_id" in active:
        rows = [c for c in rows if c["unit_id"] == active["unit_id"]]
    if "credential_code" in active:
        rows = [c for c in rows if c["credential_code"] == active["credential_code"]]
    if "status" in active:
        rows = [c for c in rows if derive.credential_status(c) == active["status"]]
    return response.listing([serialize.credential(c) for c in ctx.page(rows, limit, offset)],
                            limit, offset, len(rows))


@bp.get("/staff-credentials/<credential_id>")
def read_credential(credential_id):
    ctx.authenticate(["NetworkAdmin", "UnitDirector", "IntakeNeonatologist"])
    return response.ok(serialize.credential(lookup.credential(credential_id)))


@bp.post("/staff-credentials/<credential_id>/revoke")
def revoke_credential(credential_id):
    caller = ctx.authenticate(["NetworkAdmin", "UnitDirector"])
    credential = lookup.credential(credential_id)
    ctx.require_scope(caller, credential["unit_id"])
    unit = db.units.get(credential["unit_id"])
    before = derive.effective_level(unit) if unit else None
    credential["revoked_at"] = clock.now()
    touch(credential)
    if unit is not None:
        after = derive.effective_level(unit)
        if derive.rank(after) < derive.rank(before):
            cascade.capability_cascade(unit)
            touch(unit)
    return response.ok(serialize.credential(credential))


# --------------------------------------------------------------------------
# EquipmentAsset
# --------------------------------------------------------------------------
@bp.post("/equipment-assets")
def create_asset():
    caller = ctx.authenticate(["NetworkAdmin", "UnitDirector"])
    data = ctx.body()
    unit_id = ctx.req_string(data, "unit_id")
    equipment_code = ctx.req_enum(data, "equipment_code", derive.EQUIPMENT_CODES)
    asset_tag = ctx.req_string(data, "asset_tag")
    last_service_at = ctx.req_dt(data, "last_service_at")
    interval = ctx.req_int(data, "service_interval_days", minimum=1)
    lookup.unit(unit_id)
    ctx.require_scope(caller, unit_id)

    asset = base_record()
    asset.update({
        "unit_id": unit_id,
        "equipment_code": equipment_code,
        "asset_tag": asset_tag,
        "last_service_at": last_service_at,
        "service_interval_days": interval,
        "out_of_service_at": None,
        "out_of_service_reason": None,
        "decontamination_ready_at": None,
    })
    db.assets[asset["id"]] = asset
    return response.created(serialize.asset(asset))


@bp.get("/equipment-assets")
def list_assets():
    ctx.authenticate(["NetworkAdmin", "UnitDirector", "IntakeNeonatologist",
                      "TransportCoordinator"])
    limit, offset = ctx.pagination()
    active = ctx.filters("unit_id", "equipment_code", "status")
    rows = ordered(db.assets.values())
    if "unit_id" in active:
        rows = [a for a in rows if a["unit_id"] == active["unit_id"]]
    if "equipment_code" in active:
        rows = [a for a in rows if a["equipment_code"] == active["equipment_code"]]
    if "status" in active:
        rows = [a for a in rows if derive.asset_status(a) == active["status"]]
    return response.listing([serialize.asset(a) for a in ctx.page(rows, limit, offset)],
                            limit, offset, len(rows))


@bp.get("/equipment-assets/<asset_id>")
def read_asset(asset_id):
    ctx.authenticate(["NetworkAdmin", "UnitDirector", "IntakeNeonatologist",
                      "TransportCoordinator"])
    return response.ok(serialize.asset(lookup.asset(asset_id)))


@bp.post("/equipment-assets/<asset_id>/service")
def service_asset(asset_id):
    caller = ctx.authenticate(["NetworkAdmin", "UnitDirector"])
    asset = lookup.asset(asset_id)
    ctx.require_scope(caller, asset["unit_id"])
    data = ctx.body()
    serviced_at = ctx.req_dt(data, "serviced_at")
    asset["last_service_at"] = serviced_at
    asset["out_of_service_at"] = None
    asset["out_of_service_reason"] = None
    touch(asset)
    return response.ok(serialize.asset(asset))


@bp.post("/equipment-assets/<asset_id>/out-of-service")
def out_of_service_asset(asset_id):
    caller = ctx.authenticate(["NetworkAdmin", "UnitDirector"])
    asset = lookup.asset(asset_id)
    ctx.require_scope(caller, asset["unit_id"])
    data = ctx.body()
    reason = ctx.req_enum(data, "reason", derive.OUT_OF_SERVICE_REASONS)
    asset["out_of_service_at"] = clock.now()
    asset["out_of_service_reason"] = reason
    touch(asset)

    unit = db.units.get(asset["unit_id"])
    if unit is not None:
        standard = derive.standard_for_level(unit["designated_level"])
        if (standard is not None
                and asset["equipment_code"] in standard["required_equipment_codes"]
                and unit["designation_status"] in ("PROVISIONAL", "DESIGNATED")):
            unit["designation_status"] = "CONDITIONAL"
        cascade.capability_cascade(unit)
        touch(unit)
    return response.ok(serialize.asset(asset))


# --------------------------------------------------------------------------
# DesignationReview
# --------------------------------------------------------------------------
OPEN_REVIEW_STATUSES = ("DRAFT", "SUBMITTED", "RETURNED", "VERIFIED")


@bp.post("/designation-reviews")
def create_review():
    caller = ctx.authenticate(["UnitDirector"])
    data = ctx.body()
    unit_id = ctx.req_string(data, "unit_id")
    requested_level = ctx.req_enum(data, "requested_level", derive.LEVELS)
    assigned = ctx.req_int(data, "assigned_nurse_count", minimum=0)
    lookup.unit(unit_id)
    ctx.require_scope(caller, unit_id)
    for existing in db.reviews.values():
        if existing["unit_id"] == unit_id and existing["status"] in OPEN_REVIEW_STATUSES:
            raise ApiError("ERR_REVIEW_ALREADY_OPEN", 409)

    review = base_record()
    review.update({
        "unit_id": unit_id,
        "requested_level": requested_level,
        "assigned_nurse_count": assigned,
        "status": "DRAFT",
        "submission_round": 0,
        "assessment_at": None,
        "submitted_by_user_id": None,
        "verified_by_user_id": None,
        "certified_by_user_id": None,
        "required_nurse_count": 0,
        "staffing_subscore": derive.q2(0),
        "equipment_subscore": derive.q2(0),
        "volume_subscore": derive.q2(0),
        "compliance_score": derive.q2(0),
        "outcome_level": None,
        "return_reason": None,
        "denial_basis": None,
    })
    db.reviews[review["id"]] = review
    return response.created(serialize.review(review))


@bp.get("/designation-reviews")
def list_reviews():
    ctx.authenticate(["NetworkAdmin", "UnitDirector"])
    limit, offset = ctx.pagination()
    active = ctx.filters("unit_id", "status", "requested_level")
    rows = ordered(db.reviews.values())
    if "unit_id" in active:
        rows = [r for r in rows if r["unit_id"] == active["unit_id"]]
    if "status" in active:
        rows = [r for r in rows if r["status"] == active["status"]]
    if "requested_level" in active:
        rows = [r for r in rows if r["requested_level"] == active["requested_level"]]
    return response.listing([serialize.review(r) for r in ctx.page(rows, limit, offset)],
                            limit, offset, len(rows))


@bp.get("/designation-reviews/<review_id>")
def read_review(review_id):
    ctx.authenticate(["NetworkAdmin", "UnitDirector"])
    return response.ok(serialize.review(lookup.review(review_id)))


@bp.post("/designation-reviews/<review_id>/submit")
def submit_review(review_id):
    caller = ctx.authenticate(["UnitDirector"])
    review = lookup.review(review_id)
    ctx.require_scope(caller, review["unit_id"])
    data = ctx.body()
    assigned = ctx.opt_int(data, "assigned_nurse_count", minimum=0)
    if review["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError("ERR_INVALID_STATE", 409)
    unit = db.units.get(review["unit_id"])

    if review["status"] == "RETURNED" and review["submission_round"] >= 2:
        review["submission_round"] = 3
        review["status"] = "DENIED"
        review["denial_basis"] = "ROUNDS_EXHAUSTED"
        review["outcome_level"] = None
        touch(review)
        if unit is not None:
            unit["designation_status"] = "SUSPENDED"
            cascade.divert_open_referrals(unit)
            touch(unit)
        return response.ok(serialize.review(review))

    if unit is not None and unit["designation_status"] == "SUSPENDED":
        raise ApiError("ERR_DEPENDENT_STATE_INVALID", 409,
                       "A suspended unit may not submit a designation review.")
    if assigned is not None:
        review["assigned_nurse_count"] = assigned
    scores = derive.compliance_breakdown(unit, review["requested_level"],
                                         review["assigned_nurse_count"])
    review.update(scores)
    review["submission_round"] += 1
    review["status"] = "SUBMITTED"
    review["assessment_at"] = clock.now()
    review["submitted_by_user_id"] = caller.user_id
    touch(review)
    return response.ok(serialize.review(review))


@bp.post("/designation-reviews/<review_id>/return")
def return_review(review_id):
    caller = ctx.authenticate(["NetworkAdmin"])
    review = lookup.review(review_id)
    data = ctx.body()
    return_reason = ctx.req_string(data, "return_reason")
    if review["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409)
    if caller.user_id == review["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409)
    review["status"] = "RETURNED"
    review["return_reason"] = return_reason
    touch(review)
    return response.ok(serialize.review(review))


@bp.post("/designation-reviews/<review_id>/verify")
def verify_review(review_id):
    caller = ctx.authenticate(["NetworkAdmin"])
    review = lookup.review(review_id)
    ctx.body()
    if review["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409)
    _, floor_score = derive.standard_thresholds(review["requested_level"])
    if review["compliance_score"] < floor_score:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "The frozen compliance score is below the conditional floor.")
    if caller.user_id == review["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409)
    review["status"] = "VERIFIED"
    review["verified_by_user_id"] = caller.user_id
    touch(review)
    return response.ok(serialize.review(review))


@bp.post("/designation-reviews/<review_id>/certify")
def certify_review(review_id):
    caller = ctx.authenticate(["NetworkAdmin"])
    review = lookup.review(review_id)
    ctx.body()
    min_score, floor_score = derive.standard_thresholds(review["requested_level"])

    if review["status"] == "SUBMITTED":
        if not review["compliance_score"] < floor_score:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "A submitted review at or above the conditional floor must be "
                           "verified before it can be certified.")
        if caller.user_id == review["submitted_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409)
        review["status"] = "DENIED"
        review["denial_basis"] = "SCORE_BELOW_FLOOR"
        review["outcome_level"] = None
        touch(review)
        return response.ok(serialize.review(review))

    if review["status"] != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE", 409)
    if caller.user_id == review["verified_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409)

    if review["compliance_score"] >= min_score:
        outcome = review["requested_level"]
    else:
        outcome = derive.one_below(review["requested_level"])
    review["status"] = "CERTIFIED"
    review["certified_by_user_id"] = caller.user_id
    review["outcome_level"] = outcome
    touch(review)

    unit = db.units.get(review["unit_id"])
    if unit is not None:
        unit["designated_level"] = outcome
        unit["designation_status"] = ("DESIGNATED" if outcome == review["requested_level"]
                                     else "CONDITIONAL")
        cap = derive.rank(derive.effective_level(unit))
        for referral in list(db.referrals.values()):
            if referral["receiving_unit_id"] != unit["id"]:
                continue
            if referral["status"] != "ACCEPTED":
                continue
            if derive.rank(derive.required_level(referral)) <= cap:
                continue
            referral["status"] = "DIVERTED"
            referral["decision_reason"] = "CAPABILITY_LOST"
            touch(referral)
            hold = cascade.live_hold(referral["id"])
            if hold is not None:
                cascade.release_hold(hold, "CAPABILITY_LOST")
        touch(unit)
    return response.ok(serialize.review(review))
