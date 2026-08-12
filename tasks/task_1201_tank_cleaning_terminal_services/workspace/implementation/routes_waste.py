"""WasteProfile review cycle and WasteShipment logistics (PRD §3.5)."""

from flask import Blueprint

from core import (
    db, ApiError, auth, require_role, body_json, need, req_num, req_str,
    req_enum, as_int, as_num, as_enum, get_or_404, create_entity, touch, ser,
    ok, paginate, sorted_all, apply_filters, forbid,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_WASTE_PROFILE_NOT_APPROVED,
    ERR_PROFILE_ALREADY_APPROVED, ERR_SHIPMENT_PROFILE_MISMATCH,
)
import calc
from services import recompute_shipped_solids, recompute_waste_cost

bp = Blueprint("waste", __name__)

HAZARD_CLASSES = {"NON_HAZARDOUS", "HAZARDOUS"}
MATERIALS = {"SLUDGE", "WASH_WATER", "SCALE"}


def _own_job(uid, job):
    if job["contractor_id"] != uid:
        forbid("acting ContractorSupervisor does not own this job")


# ---------------------------------------------------------- waste profiles ---


@bp.post("/waste-profiles")
def create_profile():
    uid, role = auth()
    require_role(role, {"ContractorSupervisor"})
    b = body_json()
    job_id = req_str(b, "job_id")
    waste_code = req_str(b, "waste_code")
    hazard_class = req_enum(b, "hazard_class", HAZARD_CLASSES)
    flash = req_num(b, "lab_flash_point_c")
    tph = req_num(b, "lab_tph_mg_l")
    job = get_or_404(db.cleaning_jobs, job_id, "cleaning job")
    _own_job(uid, job)
    p = create_entity({
        "job_id": job_id,
        "waste_code": waste_code,
        "hazard_class": hazard_class,
        "lab_flash_point_c": flash,
        "lab_tph_mg_l": tph,
        "status": "DRAFT",
    })
    db.waste_profiles[p["id"]] = p
    return ok(ser(p), 201)


@bp.get("/waste-profiles/<profileId>")
def get_profile(profileId):
    auth()
    return ok(ser(get_or_404(db.waste_profiles, profileId, "waste profile")), 200)


@bp.get("/waste-profiles")
def list_profiles():
    auth()
    items = apply_filters(sorted_all(db.waste_profiles), [
        ("job_id", "job_id"),
        ("status", "status"),
    ])
    page, pg = paginate(items)
    return ok([ser(e) for e in page], 200, pg)


@bp.post("/waste-profiles/<profileId>/submit")
def submit_profile(profileId):
    uid, role = auth()
    require_role(role, {"ContractorSupervisor"})
    p = get_or_404(db.waste_profiles, profileId, "waste profile")
    job = db.cleaning_jobs.get(p["job_id"])
    if job is not None:
        _own_job(uid, job)
    if p["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a DRAFT or REJECTED profile can be submitted")
    p["status"] = "SUBMITTED"
    touch(p)
    return ok(ser(p), 200)


@bp.post("/waste-profiles/<profileId>/approve")
def approve_profile(profileId):
    uid, role = auth()
    require_role(role, {"EHSOfficer"})
    p = get_or_404(db.waste_profiles, profileId, "waste profile")
    if p["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "profile is not SUBMITTED")
    if any(o["job_id"] == p["job_id"] and o["id"] != p["id"]
           and o["status"] == "APPROVED" for o in db.waste_profiles.values()):
        raise ApiError(ERR_PROFILE_ALREADY_APPROVED, 409,
                       "another profile for this job is already APPROVED")
    p["status"] = "APPROVED"
    touch(p)
    return ok(ser(p), 200)


@bp.post("/waste-profiles/<profileId>/reject")
def reject_profile(profileId):
    uid, role = auth()
    require_role(role, {"EHSOfficer"})
    p = get_or_404(db.waste_profiles, profileId, "waste profile")
    if p["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "profile is not SUBMITTED")
    p["status"] = "REJECTED"
    touch(p)
    return ok(ser(p), 200)


@bp.post("/waste-profiles/<profileId>/reclassify")
def reclassify_profile(profileId):
    uid, role = auth()
    require_role(role, {"EHSOfficer"})
    p = get_or_404(db.waste_profiles, profileId, "waste profile")
    b = body_json()
    new_class = req_enum(b, "hazard_class", HAZARD_CLASSES)
    if p["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "profile is not APPROVED")
    if new_class == p["hazard_class"]:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "hazard_class must differ from the current class")
    p["hazard_class"] = new_class
    p["status"] = "DRAFT"
    touch(p)
    # Atomic cascade (PRD §3.5): void non-reconciled shipments referencing this
    # profile (RECONCILED survive), recompute shipped solids, revert RTS gate.
    affected_jobs = set()
    for s in db.waste_shipments.values():
        if s["profile_id"] == p["id"] \
                and s["status"] in ("BOOKED", "IN_TRANSIT", "DELIVERED"):
            s["status"] = "VOIDED"
            touch(s)
            affected_jobs.add(s["job_id"])
    for job_id in affected_jobs:
        job = db.cleaning_jobs.get(job_id)
        if job is not None:
            recompute_shipped_solids(job)
    return ok(ser(p), 200)


# --------------------------------------------------------- waste shipments ---


@bp.post("/waste-shipments")
def create_shipment():
    uid, role = auth()
    require_role(role, {"ContractorSupervisor"})
    b = body_json()
    job_id = req_str(b, "job_id")
    profile_id = req_str(b, "profile_id")
    lines = need(b, "lines")
    if not isinstance(lines, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "lines must be a list")
    parsed_lines = []
    for ln in lines:
        if not isinstance(ln, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "each line must be an object")
        material = as_enum(need(ln, "material"), "material", MATERIALS)
        kg = as_int(need(ln, "kg"), "kg")
        rate = as_num(need(ln, "rate_cents_per_kg"), "rate_cents_per_kg")
        if kg < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "line kg must be >= 0")
        if rate < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "line rate_cents_per_kg must be >= 0")
        parsed_lines.append({"material": material, "kg": kg,
                             "rate_cents_per_kg": rate})
    job = get_or_404(db.cleaning_jobs, job_id, "cleaning job")
    profile = get_or_404(db.waste_profiles, profile_id, "waste profile")
    _own_job(uid, job)
    # PRD §3.5 order: profile APPROVED first, then same-job match.
    if profile["status"] != "APPROVED":
        raise ApiError(ERR_WASTE_PROFILE_NOT_APPROVED, 409,
                       "referenced waste profile is not APPROVED")
    if profile["job_id"] != job_id:
        raise ApiError(ERR_SHIPMENT_PROFILE_MISMATCH, 409,
                       "profile belongs to a different job")
    manifested = sum(ln["kg"] for ln in parsed_lines)
    # Pinned rounding order: round each line to whole cents FIRST, then sum.
    cost = sum(calc.line_cost_cents(ln["kg"], ln["rate_cents_per_kg"],
                                    profile["hazard_class"])
               for ln in parsed_lines)
    s = create_entity({
        "job_id": job_id,
        "profile_id": profile_id,
        "lines": parsed_lines,
        "manifested_kg": manifested,
        "disposal_cost_cents": cost,
        "status": "BOOKED",
    })
    db.waste_shipments[s["id"]] = s
    return ok(ser(s), 201)


@bp.get("/waste-shipments/<shipmentId>")
def get_shipment(shipmentId):
    auth()
    return ok(ser(get_or_404(db.waste_shipments, shipmentId, "waste shipment")), 200)


@bp.get("/waste-shipments")
def list_shipments():
    auth()
    items = apply_filters(sorted_all(db.waste_shipments), [
        ("job_id", "job_id"),
        ("profile_id", "profile_id"),
        ("status", "status"),
    ])
    page, pg = paginate(items)
    return ok([ser(e) for e in page], 200, pg)


def _shipment_and_owner(uid, shipmentId):
    s = get_or_404(db.waste_shipments, shipmentId, "waste shipment")
    job = db.cleaning_jobs.get(s["job_id"])
    if job is not None:
        _own_job(uid, job)
    return s, job


@bp.post("/waste-shipments/<shipmentId>/dispatch")
def dispatch_shipment(shipmentId):
    uid, role = auth()
    require_role(role, {"ContractorSupervisor"})
    s, job = _shipment_and_owner(uid, shipmentId)
    if s["status"] != "BOOKED":
        raise ApiError(ERR_INVALID_STATE, 409, "shipment is not BOOKED")
    s["status"] = "IN_TRANSIT"
    touch(s)
    return ok(ser(s), 200)


@bp.post("/waste-shipments/<shipmentId>/deliver")
def deliver_shipment(shipmentId):
    uid, role = auth()
    require_role(role, {"ContractorSupervisor"})
    s, job = _shipment_and_owner(uid, shipmentId)
    if s["status"] != "IN_TRANSIT":
        raise ApiError(ERR_INVALID_STATE, 409, "shipment is not IN_TRANSIT")
    s["status"] = "DELIVERED"
    touch(s)
    if job is not None:
        recompute_shipped_solids(job)
    return ok(ser(s), 200)


@bp.post("/waste-shipments/<shipmentId>/reconcile")
def reconcile_shipment(shipmentId):
    uid, role = auth()
    require_role(role, {"EHSOfficer"})
    s = get_or_404(db.waste_shipments, shipmentId, "waste shipment")
    if s["status"] != "DELIVERED":
        raise ApiError(ERR_INVALID_STATE, 409, "shipment is not DELIVERED")
    s["status"] = "RECONCILED"
    touch(s)
    job = db.cleaning_jobs.get(s["job_id"])
    if job is not None:
        recompute_waste_cost(job)
    return ok(ser(s), 200)


@bp.post("/waste-shipments/<shipmentId>/void")
def void_shipment(shipmentId):
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    s = get_or_404(db.waste_shipments, shipmentId, "waste shipment")
    if s["status"] not in ("BOOKED", "IN_TRANSIT", "DELIVERED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a non-reconciled shipment can be voided")
    s["status"] = "VOIDED"
    touch(s)
    job = db.cleaning_jobs.get(s["job_id"])
    if job is not None:
        recompute_shipped_solids(job)
    return ok(ser(s), 200)
