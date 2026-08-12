from flask import Blueprint

import db
from errors import ApiError
from middleware import auth, body
from response import success, paged
from services import get_or_404, cancel_schedules_for_prescription
from util import (new_resource, touch, req, opt, as_str, as_num, as_enum, as_list)

bp = Blueprint("core", __name__)

SPECIES = {"DOG", "CAT", "BIRD", "REPTILE", "OTHER"}


# ---- Owners ----

@bp.route("/owners", methods=["POST"])
def create_owner():
    auth("PharmacyAdmin")
    d = body()
    full_name = as_str(req(d, "full_name"), "full_name")
    email = as_str(req(d, "email"), "email")
    phone = as_str(req(d, "phone"), "phone")
    ship_to = as_str(req(d, "ship_to_address"), "ship_to_address")
    for o in db.owners.values():
        if o["email"] == email:
            raise ApiError("ERR_INVALID_REQUEST", "email already registered", 400)
    o = new_resource({
        "full_name": full_name, "email": email, "phone": phone,
        "ship_to_address": ship_to, "status": "ACTIVE",
    })
    db.owners[o["id"]] = o
    return success(o, 201)


@bp.route("/owners/<rid>", methods=["GET"])
def get_owner(rid):
    auth("Owner", "Pharmacist", "PharmacyTech", "ComplianceOfficer", "PharmacyAdmin")
    return success(get_or_404(db.owners, rid, "owner"))


@bp.route("/owners/<rid>", methods=["PATCH"])
def patch_owner(rid):
    auth("Owner", "PharmacyAdmin")
    o = get_or_404(db.owners, rid, "owner")
    d = body()
    for f in ("full_name", "phone", "ship_to_address"):
        if f in d and d[f] is not None:
            o[f] = as_str(d[f], f)
    touch(o)
    return success(o)


@bp.route("/owners/<rid>/pets", methods=["GET"])
def list_owner_pets(rid):
    auth("Owner", "Pharmacist", "PharmacyTech", "PharmacyAdmin")
    get_or_404(db.owners, rid, "owner")
    return paged([p for p in db.pets.values() if p["owner_id"] == rid])


@bp.route("/owners/<rid>/pets", methods=["POST"])
def create_pet(rid):
    auth("Owner", "PharmacyAdmin")
    get_or_404(db.owners, rid, "owner")
    d = body()
    name = as_str(req(d, "name"), "name")
    species = as_enum(req(d, "species"), "species", SPECIES)
    weight = as_num(req(d, "weight_kg"), "weight_kg")
    if weight <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "weight_kg must be > 0", 400)
    allergies = as_list(opt(d, "allergies", []), "allergies")
    p = new_resource({
        "owner_id": rid, "name": name, "species": species,
        "weight_kg": weight, "allergies": allergies, "status": "ALIVE",
    })
    db.pets[p["id"]] = p
    return success(p, 201)


@bp.route("/pets/<rid>", methods=["GET"])
def get_pet(rid):
    auth("Owner", "Veterinarian", "Pharmacist", "PharmacyTech", "PharmacyAdmin")
    return success(get_or_404(db.pets, rid, "pet"))


@bp.route("/pets/<rid>", methods=["PATCH"])
def patch_pet(rid):
    auth("Owner", "Pharmacist")
    p = get_or_404(db.pets, rid, "pet")
    d = body()
    if "weight_kg" in d and d["weight_kg"] is not None:
        w = as_num(d["weight_kg"], "weight_kg")
        if w <= 0:
            raise ApiError("ERR_INVALID_REQUEST", "weight_kg must be > 0", 400)
        p["weight_kg"] = w
    if "allergies" in d and d["allergies"] is not None:
        p["allergies"] = as_list(d["allergies"], "allergies")
    if "status" in d and d["status"] is not None:
        st = as_enum(d["status"], "status", {"ALIVE", "DECEASED"})
        if st == "DECEASED" and p["status"] == "ALIVE":
            p["status"] = "DECEASED"
            # cascade: cancel all ACTIVE/PAUSED auto-ship schedules on this pet's scripts
            for rx in db.prescriptions.values():
                if rx["pet_id"] == p["id"]:
                    cancel_schedules_for_prescription(rx["id"])
        elif st != p["status"]:
            raise ApiError("ERR_INVALID_STATE",
                           "pet status transition not permitted", 409)
    touch(p)
    return success(p)


# ---- Veterinarians ----

@bp.route("/veterinarians", methods=["POST"])
def create_vet():
    auth("PharmacyAdmin")
    d = body()
    full_name = as_str(req(d, "full_name"), "full_name")
    license_number = as_str(req(d, "license_number"), "license_number")
    dea = d.get("dea_registration_number")
    if dea is not None:
        dea = as_str(dea, "dea_registration_number")
    practice_state = as_str(req(d, "practice_state"), "practice_state")
    for v in db.veterinarians.values():
        if v["license_number"] == license_number:
            raise ApiError("ERR_INVALID_REQUEST", "license_number already registered", 400)
    v = new_resource({
        "full_name": full_name, "license_number": license_number,
        "dea_registration_number": dea, "practice_state": practice_state,
        "status": "PENDING",
    })
    db.veterinarians[v["id"]] = v
    return success(v, 201)


@bp.route("/veterinarians/<rid>", methods=["GET"])
def get_vet(rid):
    auth("Veterinarian", "Pharmacist", "PharmacyTech", "ComplianceOfficer",
         "PharmacyAdmin")
    return success(get_or_404(db.veterinarians, rid, "veterinarian"))


def _reject_pending_prescriptions(vet_id):
    for rx in db.prescriptions.values():
        if rx["veterinarian_id"] == vet_id and rx["status"] in (
                "RECEIVED", "VET_VERIFICATION_PENDING", "CLARIFICATION_REQUESTED"):
            rx["status"] = "REJECTED"
            touch(rx)


def _vet_transition(rid, from_states, to_state, cascade=False):
    auth("ComplianceOfficer")
    v = get_or_404(db.veterinarians, rid, "veterinarian")
    if v["status"] not in from_states:
        raise ApiError("ERR_INVALID_STATE",
                       "veterinarian is not in a permitted source state", 409)
    v["status"] = to_state
    if cascade:
        _reject_pending_prescriptions(v["id"])
    touch(v)
    return success(v)


@bp.route("/veterinarians/<rid>/verify", methods=["POST"])
def verify_vet(rid):
    return _vet_transition(rid, ("PENDING",), "VERIFIED")


@bp.route("/veterinarians/<rid>/suspend", methods=["POST"])
def suspend_vet(rid):
    return _vet_transition(rid, ("VERIFIED",), "SUSPENDED", cascade=True)


@bp.route("/veterinarians/<rid>/reinstate", methods=["POST"])
def reinstate_vet(rid):
    return _vet_transition(rid, ("SUSPENDED",), "VERIFIED")


@bp.route("/veterinarians/<rid>/revoke", methods=["POST"])
def revoke_vet(rid):
    return _vet_transition(rid, ("VERIFIED", "SUSPENDED"), "REVOKED", cascade=True)
