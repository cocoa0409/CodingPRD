"""Configuration layer: staff, patients, drug products, hoods, coverage."""

from flask import Blueprint, request

import db
import validate as V
from auth import authenticate, ALL_ROLES
from calc import compute_patient_panel
from errors import err_not_found
from response import ok, ok_list, serialize, paginate

bp = Blueprint("config", __name__)

ADMIN = ["PharmacyAdmin"]

STAFF_ROLES = {"PRESCRIBER", "PHARMACIST", "TECHNICIAN", "NURSE"}
SCHEDULES = {"NON_CONTROLLED", "C_II", "C_III", "C_IV", "C_V"}
DRUG_STATUS = {"ACTIVE", "DISCONTINUED"}
RENAL_POLICIES = {"IBW", "ABW_WHEN_OBESE"}
ISO_CLASSES = {"ISO_5", "ISO_7", "ISO_8"}


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------

@bp.post("/pharmacy/staff")
def create_staff():
    authenticate(ADMIN)
    d = V.body()
    full_name = V.req_str(d, "full_name")
    staff_role = V.req_enum(d, "staff_role", STAFF_ROLES)
    hd_cert = V.opt_bool(d, "hd_compounding_certified", False)
    hd_expires = V.opt_datetime(d, "hd_cert_expires_at")
    if not hd_cert:
        hd_expires = None
    s = db.base_fields()
    s.update({
        "full_name": full_name,
        "staff_role": staff_role,
        "hd_compounding_certified": hd_cert,
        "hd_cert_expires_at": hd_expires,
        "active": True,
    })
    db.staff[s["id"]] = s
    return ok(serialize(s), 201)


@bp.get("/pharmacy/staff/<sid>")
def get_staff(sid):
    authenticate(ALL_ROLES)
    s = db.staff.get(sid)
    if s is None:
        raise err_not_found("Staff member not found")
    return ok(serialize(s))


@bp.get("/pharmacy/staff")
def list_staff():
    authenticate(ALL_ROLES)
    items = list(db.staff.values())
    role_filter = request.args.get("staff_role")
    if role_filter is not None:
        items = [s for s in items if s["staff_role"] == role_filter]
    page, meta = paginate(items, request.args)
    return ok_list(page, meta)


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------

@bp.post("/pharmacy/patients")
def create_patient():
    authenticate(ADMIN)
    d = V.body()
    p = db.base_fields()
    p.update({
        "full_name": V.req_str(d, "full_name"),
        "date_of_birth": V.req_datetime(d, "date_of_birth"),
        "sex": V.req_enum(d, "sex", {"M", "F"}),
        "height_cm": V.req_number(d, "height_cm"),
        "weight_kg": V.req_number(d, "weight_kg"),
        "scr_mg_dl": V.req_number(d, "scr_mg_dl"),
        "allergy_drug_product_ids": V.opt_str_list(d, "allergy_drug_product_ids", []),
    })
    p.update(compute_patient_panel(p, db.now()))
    db.patients[p["id"]] = p
    return ok(serialize(p), 201)


@bp.get("/pharmacy/patients/<pid>")
def get_patient(pid):
    authenticate(ALL_ROLES)
    p = db.patients.get(pid)
    if p is None:
        raise err_not_found("Patient not found")
    return ok(serialize(p))


@bp.patch("/pharmacy/patients/<pid>")
def update_patient(pid):
    authenticate(ADMIN)
    d = V.body()
    weight = V.opt_number(d, "weight_kg")
    scr = V.opt_number(d, "scr_mg_dl")
    allergies = V.opt_str_list(d, "allergy_drug_product_ids")
    p = db.patients.get(pid)
    if p is None:
        raise err_not_found("Patient not found")
    if weight is not None:
        p["weight_kg"] = weight
    if scr is not None:
        p["scr_mg_dl"] = scr
    if allergies is not None:
        p["allergy_drug_product_ids"] = allergies
    p.update(compute_patient_panel(p, db.now()))
    db.touch(p)
    return ok(serialize(p))


# ---------------------------------------------------------------------------
# Drug products
# ---------------------------------------------------------------------------

@bp.post("/pharmacy/drug-products")
def create_drug():
    authenticate(ADMIN)
    d = V.body()
    drug = db.base_fields()
    drug.update({
        "name": V.req_str(d, "name"),
        "schedule": V.req_enum(d, "schedule", SCHEDULES),
        "is_hazardous": V.opt_bool(d, "is_hazardous", False),
        "concentration_mg_per_ml": V.req_number(d, "concentration_mg_per_ml"),
        "vial_size_ml": V.req_number(d, "vial_size_ml"),
        "has_stability_data": V.opt_bool(d, "has_stability_data", False),
        "stability_hours_room": V.opt_int(d, "stability_hours_room"),
        "stability_hours_refrigerated": V.opt_int(d, "stability_hours_refrigerated"),
        "stability_hours_frozen": V.opt_int(d, "stability_hours_frozen"),
        "renal_dosing_policy": V.opt_enum(d, "renal_dosing_policy", RENAL_POLICIES, "IBW"),
        "in_shortage": V.opt_bool(d, "in_shortage", False),
        "status": V.opt_enum(d, "status", DRUG_STATUS, "ACTIVE"),
    })
    db.drugs[drug["id"]] = drug
    return ok(serialize(drug), 201)


@bp.get("/pharmacy/drug-products/<did>")
def get_drug(did):
    authenticate(ALL_ROLES)
    drug = db.drugs.get(did)
    if drug is None:
        raise err_not_found("Drug product not found")
    return ok(serialize(drug))


@bp.get("/pharmacy/drug-products")
def list_drugs():
    authenticate(ALL_ROLES)
    items = list(db.drugs.values())
    status = request.args.get("status")
    if status is not None:
        items = [x for x in items if x["status"] == status]
    haz = request.args.get("is_hazardous")
    if haz is not None:
        want = haz.lower() in ("true", "1")
        items = [x for x in items if x["is_hazardous"] == want]
    sched = request.args.get("schedule")
    if sched is not None:
        items = [x for x in items if x["schedule"] == sched]
    short = request.args.get("in_shortage")
    if short is not None:
        want = short.lower() in ("true", "1")
        items = [x for x in items if x["in_shortage"] == want]
    page, meta = paginate(items, request.args)
    return ok_list(page, meta)


@bp.patch("/pharmacy/drug-products/<did>")
def update_drug(did):
    authenticate(ADMIN)
    d = V.body()
    in_shortage = V.opt_bool(d, "in_shortage")
    status = V.opt_enum(d, "status", DRUG_STATUS)
    drug = db.drugs.get(did)
    if drug is None:
        raise err_not_found("Drug product not found")
    if in_shortage is not None:
        drug["in_shortage"] = in_shortage
    if status is not None:
        drug["status"] = status
    db.touch(drug)
    return ok(serialize(drug))


@bp.get("/pharmacy/drug-products/<did>/substitution-protocols")
def list_drug_protocols(did):
    authenticate(ALL_ROLES)
    drug = db.drugs.get(did)
    if drug is None:
        raise err_not_found("Drug product not found")
    items = [p for p in db.protocols.values() if p["shortage_drug_product_id"] == did]
    page, meta = paginate(items, request.args)
    return ok_list(page, meta)


# ---------------------------------------------------------------------------
# Hoods
# ---------------------------------------------------------------------------

@bp.post("/pharmacy/hoods")
def create_hood():
    authenticate(ADMIN)
    d = V.body()
    hood = db.base_fields()
    hood.update({
        "name": V.req_str(d, "name"),
        "iso_class": V.req_enum(d, "iso_class", ISO_CLASSES),
        "is_hd_rated": V.opt_bool(d, "is_hd_rated", False),
    })
    db.hoods[hood["id"]] = hood
    return ok(serialize(hood), 201)


@bp.get("/pharmacy/hoods/<hid>")
def get_hood(hid):
    authenticate(ALL_ROLES)
    hood = db.hoods.get(hid)
    if hood is None:
        raise err_not_found("Hood not found")
    return ok(serialize(hood))


@bp.get("/pharmacy/hoods")
def list_hoods():
    authenticate(ALL_ROLES)
    page, meta = paginate(list(db.hoods.values()), request.args)
    return ok_list(page, meta)


# ---------------------------------------------------------------------------
# Coverage shifts
# ---------------------------------------------------------------------------

@bp.post("/pharmacy/coverage-shifts")
def create_shift():
    from errors import err_invalid_quantity, err_coverage_cap
    authenticate(ADMIN)
    d = V.body()
    staff_id = V.req_str(d, "staff_id")
    zone = V.req_str(d, "zone")
    start_at = V.req_datetime(d, "start_at")
    end_at = V.req_datetime(d, "end_at")
    if staff_id not in db.staff:
        raise err_not_found("Staff member not found")
    if not (end_at > start_at):
        raise err_invalid_quantity("end_at must be strictly after start_at")
    # At most two shifts per zone may overlap at any instant (half-open).
    existing = [s for s in db.shifts.values() if s["zone"] == zone]
    candidates = [start_at] + [
        s["start_at"] for s in existing if start_at < s["start_at"] < end_at
    ]
    for t in candidates:
        covering = sum(1 for s in existing if s["start_at"] <= t < s["end_at"])
        if covering + 1 > 2:
            raise err_coverage_cap()
    shift = db.base_fields()
    shift.update({
        "staff_id": staff_id,
        "zone": zone,
        "start_at": start_at,
        "end_at": end_at,
    })
    db.shifts[shift["id"]] = shift
    return ok(serialize(shift), 201)


@bp.get("/pharmacy/coverage-shifts/<sid>")
def get_shift(sid):
    authenticate(ALL_ROLES)
    shift = db.shifts.get(sid)
    if shift is None:
        raise err_not_found("Coverage shift not found")
    return ok(serialize(shift))


@bp.get("/pharmacy/coverage-shifts")
def list_shifts():
    authenticate(ALL_ROLES)
    items = list(db.shifts.values())
    staff_id = request.args.get("staff_id")
    if staff_id is not None:
        items = [s for s in items if s["staff_id"] == staff_id]
    zone = request.args.get("zone")
    if zone is not None:
        items = [s for s in items if s["zone"] == zone]
    page, meta = paginate(items, request.args)
    return ok_list(page, meta)
