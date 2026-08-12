from datetime import timedelta

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import auth, body, require_ownership
from response import success, paged
from services import get_or_404, create_compound_order
from util import (new_resource, touch, req, as_str, as_int, as_bool,
                  as_date_str, parse_date)

bp = Blueprint("rx", __name__)

RX_READ = ("Owner", "Veterinarian", "Pharmacist", "PharmacyTech", "PharmacyAdmin")


def _filter(items, names):
    out = []
    for it in items:
        ok = True
        for n in names:
            v = request.args.get(n)
            if v is not None and str(it.get(n)) != v:
                ok = False
                break
        if ok:
            out.append(it)
    return out


@bp.route("/prescriptions", methods=["POST"])
def create_rx():
    auth("PharmacyTech")
    d = body()
    # body FK existence, in declared field order
    pet_id = d.get("pet_id")
    owner_id = d.get("owner_id")
    vet_id = d.get("veterinarian_id")
    formula_id = d.get("formula_id")
    if pet_id is not None:
        get_or_404(db.pets, pet_id, "pet")
    if owner_id is not None:
        get_or_404(db.owners, owner_id, "owner")
    if vet_id is not None:
        get_or_404(db.veterinarians, vet_id, "veterinarian")
    if formula_id is not None:
        get_or_404(db.formulas, formula_id, "formula")
    pet_id = as_str(req(d, "pet_id"), "pet_id")
    owner_id = as_str(req(d, "owner_id"), "owner_id")
    vet_id = as_str(req(d, "veterinarian_id"), "veterinarian_id")
    formula_id = as_str(req(d, "formula_id"), "formula_id")
    pet = db.pets[pet_id]
    vet = db.veterinarians[vet_id]
    formula = db.formulas[formula_id]
    if pet["owner_id"] != owner_id:
        raise ApiError("ERR_INVALID_REQUEST",
                       "owner_id must equal the pet's owner", 400)
    quantity = as_int(req(d, "quantity"), "quantity")
    if quantity <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "quantity must be > 0", 400)
    days_supply = as_int(req(d, "days_supply"), "days_supply")
    if days_supply <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "days_supply must be > 0", 400)
    refills_authorized = as_int(req(d, "refills_authorized"), "refills_authorized")
    if refills_authorized < 0:
        raise ApiError("ERR_INVALID_REQUEST", "refills_authorized must be >= 0", 400)
    directions = as_str(req(d, "directions"), "directions")
    written_date = as_date_str(req(d, "written_date"), "written_date")
    drug = db.drug_catalog_items[formula["drug_catalog_item_id"]]
    schedule = drug["schedule"]
    is_controlled = schedule != "NON_CONTROLLED"
    # safety gates in pinned order: DEA first, then C_II refill prohibition
    if is_controlled and not vet.get("dea_registration_number"):
        raise ApiError("ERR_CONTROLLED_DEA_REQUIRED",
                       "controlled formula requires a veterinarian with DEA registration",
                       422)
    if schedule == "C_II" and refills_authorized != 0:
        raise ApiError("ERR_CONTROLLED_REFILL_FORBIDDEN",
                       "C_II prescriptions must carry zero refills", 422)
    days = 365 if not is_controlled else 180
    expiration = (parse_date(written_date) + timedelta(days=days)).isoformat()
    rx = new_resource({
        "pet_id": pet_id, "owner_id": owner_id, "veterinarian_id": vet_id,
        "formula_id": formula_id, "quantity": quantity, "days_supply": days_supply,
        "refills_authorized": refills_authorized,
        "refills_remaining": refills_authorized,
        "directions": directions, "written_date": written_date,
        "expiration_date": expiration, "is_controlled": is_controlled,
        "schedule_snapshot": schedule, "status": "RECEIVED",
        "clarification_count": 0,
    })
    db.prescriptions[rx["id"]] = rx
    return success(rx, 201)


@bp.route("/prescriptions", methods=["GET"])
def list_rx():
    auth(*RX_READ)
    return paged(_filter(list(db.prescriptions.values()),
                         ["pet_id", "owner_id", "veterinarian_id", "formula_id",
                          "status"]))


@bp.route("/prescriptions/<rid>", methods=["GET"])
def get_rx(rid):
    auth(*RX_READ)
    return success(get_or_404(db.prescriptions, rid, "prescription"))


@bp.route("/prescriptions/<rid>/submit-verification", methods=["POST"])
def submit_verification(rid):
    auth("PharmacyTech")
    rx = get_or_404(db.prescriptions, rid, "prescription")
    if rx["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE",
                       "prescription is not in RECEIVED", 409)
    vet = db.veterinarians[rx["veterinarian_id"]]
    if vet["status"] != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE",
                       "prescribing veterinarian is not VERIFIED", 409)
    rx["status"] = "VET_VERIFICATION_PENDING"
    touch(rx)
    return success(rx)


def _vet_owned_rx(rid):
    _, user_id = auth("Veterinarian")
    rx = get_or_404(db.prescriptions, rid, "prescription")
    require_ownership(user_id, rx["veterinarian_id"])
    return rx


@bp.route("/prescriptions/<rid>/vet-confirm", methods=["POST"])
def vet_confirm(rid):
    rx = _vet_owned_rx(rid)
    if rx["status"] != "VET_VERIFICATION_PENDING":
        raise ApiError("ERR_INVALID_STATE",
                       "prescription is not pending vet verification", 409)
    vet = db.veterinarians[rx["veterinarian_id"]]
    if vet["status"] != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE",
                       "prescribing veterinarian is not VERIFIED", 409)
    rx["status"] = "VERIFIED"
    touch(rx)
    return success(rx)


@bp.route("/prescriptions/<rid>/vet-reject", methods=["POST"])
def vet_reject(rid):
    rx = _vet_owned_rx(rid)
    body()  # reason (free text)
    if rx["status"] != "VET_VERIFICATION_PENDING":
        raise ApiError("ERR_INVALID_STATE",
                       "prescription is not pending vet verification", 409)
    rx["status"] = "REJECTED"
    touch(rx)
    return success(rx)


@bp.route("/prescriptions/<rid>/request-clarification", methods=["POST"])
def request_clarification(rid):
    rx = _vet_owned_rx(rid)
    body()  # note (free text)
    if rx["status"] != "VET_VERIFICATION_PENDING":
        raise ApiError("ERR_INVALID_STATE",
                       "prescription is not pending vet verification", 409)
    rx["status"] = "CLARIFICATION_REQUESTED"
    rx["clarification_count"] += 1
    touch(rx)
    return success(rx)


@bp.route("/prescriptions/<rid>/resubmit", methods=["POST"])
def resubmit(rid):
    auth("PharmacyTech")
    rx = get_or_404(db.prescriptions, rid, "prescription")
    if rx["status"] != "CLARIFICATION_REQUESTED":
        raise ApiError("ERR_INVALID_STATE",
                       "prescription is not in CLARIFICATION_REQUESTED", 409)
    rx["status"] = "VET_VERIFICATION_PENDING"
    touch(rx)
    return success(rx)


@bp.route("/prescriptions/<rid>/compound-orders", methods=["POST"])
def create_order(rid):
    auth("Pharmacist", "PharmacyTech")
    rx = get_or_404(db.prescriptions, rid, "prescription")
    d = body()
    flavoring_id = d.get("flavoring_id")
    flavoring = None
    if flavoring_id is not None:
        flavoring = get_or_404(db.flavorings, flavoring_id, "flavoring")
    is_refill = as_bool(req(d, "is_refill"), "is_refill")
    expected = as_int(req(d, "expected_prescription_version"),
                      "expected_prescription_version")
    if expected != rx["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_prescription_version does not match the "
                       "prescription's current version", 412)
    order = create_compound_order(rx, flavoring, is_refill)
    return success(order, 201)


@bp.route("/prescriptions/<rid>/compound-orders", methods=["GET"])
def list_rx_orders(rid):
    auth("Owner", "Pharmacist", "PharmacyTech", "PharmacyAdmin")
    get_or_404(db.prescriptions, rid, "prescription")
    return paged([o for o in db.compound_orders.values()
                  if o["prescription_id"] == rid])
