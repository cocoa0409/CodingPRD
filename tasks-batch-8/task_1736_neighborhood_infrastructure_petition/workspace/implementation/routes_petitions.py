"""Petition and PetitionSignature endpoints (§3.2)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

import errors
import shape
from envelope import ok_object
from helpers import get_or_404, list_response, sort_created
from security import ALL_ROLES, OWNER_READ_ROLES, authenticate, require_role
from serializers import (parcel_frontage, petition_tallies, ser_petition,
                         ser_signature)
from store import STORE, new_id, now, touch

bp = Blueprint("petitions", __name__)

COUNT_THRESHOLD = Decimal("60.00")
FRONTAGE_THRESHOLD = Decimal("50.00")
PCT_Q = Decimal("0.01")


def _petition_or_404(pid):
    return get_or_404("petitions", pid, errors.PETITION_NOT_FOUND, "Petition not found")


def _signature_or_404(sid):
    return get_or_404("signatures", sid, errors.SIGNATURE_NOT_FOUND, "Signature not found")


@bp.route("/petitions", methods=["POST"])
def create_petition():
    body = shape.get_body()
    district_id = shape.req_str(body, "district_id")
    ctx = authenticate()
    require_role(ctx, ["CityClerk"])
    d = get_or_404("districts", district_id, errors.DISTRICT_NOT_FOUND,
                   "District not found")
    if d["status"] != "DRAFT":
        errors.raise_err(errors.DISTRICT_NOT_DRAFT,
                         "A petition may only be opened while the district is DRAFT")
    ts = now()
    pet = {
        "id": new_id(),
        "district_id": district_id,
        "status": "CIRCULATING",
        "opened_at": ts,
        "closed_at": None,
        "eligible_parcel_count_snapshot": None,
        "eligible_frontage_snapshot": None,
        "support_count_pct": None,
        "support_frontage_pct": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    STORE.put("petitions", pet)
    d["status"] = "PETITIONING"
    touch(d)
    return ok_object(ser_petition(pet), 201)


@bp.route("/petitions/<pid>", methods=["GET"])
def get_petition(pid):
    ctx = authenticate()
    require_role(ctx, ALL_ROLES)
    return ok_object(ser_petition(_petition_or_404(pid)))


@bp.route("/petitions/<pid>/close", methods=["POST"])
def close_petition(pid):
    shape.get_body()
    ctx = authenticate()
    require_role(ctx, ["CityClerk"])
    pet = _petition_or_404(pid)
    if pet["status"] != "CIRCULATING":
        errors.raise_err(errors.PETITION_NOT_CIRCULATING,
                         "Only a CIRCULATING petition can be closed")
    d = STORE.districts[pet["district_id"]]
    # freeze evidence
    eligible = [p for p in STORE.parcels.values()
                if p["district_id"] == d["id"] and p["status"] == "ACTIVE"
                and not p["exempt"]]
    eligible_count = len(eligible)
    eligible_frontage = sum((parcel_frontage(p) for p in eligible), Decimal("0"))
    verified_count, verified_frontage = petition_tallies(pet)
    if eligible_count == 0:
        count_pct = Decimal("0")
        frontage_pct = Decimal("0")
        passed = False
    else:
        count_pct = (Decimal(verified_count) / Decimal(eligible_count)
                     * Decimal("100")).quantize(PCT_Q, rounding=ROUND_HALF_UP)
        frontage_pct = ((verified_frontage / eligible_frontage) * Decimal("100")
                        ).quantize(PCT_Q, rounding=ROUND_HALF_UP) \
            if eligible_frontage > 0 else Decimal("0")
        passed = count_pct >= COUNT_THRESHOLD and frontage_pct >= FRONTAGE_THRESHOLD
    pet["closed_at"] = now()
    pet["eligible_parcel_count_snapshot"] = eligible_count
    pet["eligible_frontage_snapshot"] = eligible_frontage
    pet["support_count_pct"] = float(count_pct)
    pet["support_frontage_pct"] = float(frontage_pct)
    if passed:
        pet["status"] = "CLOSED_VERIFIED"
        d["status"] = "SCOPING"
    else:
        pet["status"] = "CLOSED_INSUFFICIENT"
        d["status"] = "DRAFT"
    touch(pet)
    touch(d)
    return ok_object(ser_petition(pet))


@bp.route("/petitions/<pid>/signatures", methods=["GET"])
def petition_signatures(pid):
    ctx = authenticate()
    require_role(ctx, OWNER_READ_ROLES)
    _petition_or_404(pid)
    records = [s for s in STORE.signatures.values() if s["petition_id"] == pid]
    return list_response(sort_created(records), ser_signature, paginated=False)


# --- signatures ---

@bp.route("/signatures", methods=["POST"])
def create_signature():
    body = shape.get_body()
    petition_id = shape.req_str(body, "petition_id")
    parcel_id = shape.req_str(body, "parcel_id")
    ctx = authenticate()
    require_role(ctx, ["PropertyOwner"])
    pet = _petition_or_404(petition_id)
    parcel = get_or_404("parcels", parcel_id, errors.PARCEL_NOT_FOUND,
                        "Parcel not found")
    if parcel["owner_id"] != ctx.user_id:
        errors.raise_err(errors.NOT_RESOURCE_OWNER,
                         "Only the parcel's owner of record may sign")
    if pet["status"] != "CIRCULATING":
        errors.raise_err(errors.PETITION_NOT_CIRCULATING,
                         "The petition is not circulating")
    if parcel["district_id"] != pet["district_id"]:
        errors.raise_err(errors.PARCEL_NOT_IN_DISTRICT,
                         "Parcel does not belong to the petition's district")
    if parcel["exempt"] or parcel["status"] != "ACTIVE":
        errors.raise_err(errors.INELIGIBLE_PARCEL,
                         "Exempt or removed parcels cannot sign petitions")
    if any(s["petition_id"] == petition_id and s["parcel_id"] == parcel_id
           and s["status"] in ("SUBMITTED", "VERIFIED")
           for s in STORE.signatures.values()):
        errors.raise_err(errors.DUPLICATE_SIGNATURE,
                         "Parcel already has a live signature on this petition")
    ts = now()
    s = {
        "id": new_id(),
        "petition_id": petition_id,
        "parcel_id": parcel_id,
        "owner_id": ctx.user_id,
        "signed_at": ts,
        "status": "SUBMITTED",
        "rejection_reason": None,
        "verified_by": None,
        "verified_at": None,
        "withdrawn_at": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    STORE.put("signatures", s)
    return ok_object(ser_signature(s), 201)


@bp.route("/signatures/<sid>", methods=["GET"])
def get_signature(sid):
    ctx = authenticate()
    require_role(ctx, OWNER_READ_ROLES)
    return ok_object(ser_signature(_signature_or_404(sid)))


@bp.route("/signatures/<sid>/verify", methods=["POST"])
def verify_signature(sid):
    shape.get_body()
    ctx = authenticate()
    require_role(ctx, ["CityClerk"])
    s = _signature_or_404(sid)
    if s["status"] != "SUBMITTED":
        errors.raise_err(errors.SIGNATURE_NOT_VERIFIABLE,
                         "Signature must be SUBMITTED to verify")
    pet = STORE.petitions[s["petition_id"]]
    if pet["status"] != "CIRCULATING":
        errors.raise_err(errors.PETITION_NOT_CIRCULATING,
                         "The petition is not circulating")
    parcel = STORE.parcels.get(s["parcel_id"])
    if parcel is None or parcel["status"] != "ACTIVE" or parcel["exempt"]:
        errors.raise_err(errors.INELIGIBLE_PARCEL,
                         "Parcel is no longer eligible")
    if s["owner_id"] != parcel["owner_id"]:
        errors.raise_err(errors.NOT_RESOURCE_OWNER,
                         "Signature owner no longer matches the parcel's owner of record")
    s["status"] = "VERIFIED"
    s["verified_by"] = ctx.user_id
    s["verified_at"] = now()
    touch(s)
    touch(pet)
    return ok_object(ser_signature(s))


@bp.route("/signatures/<sid>/reject", methods=["POST"])
def reject_signature(sid):
    body = shape.get_body()
    reason = shape.req_str(body, "reason")
    ctx = authenticate()
    require_role(ctx, ["CityClerk"])
    s = _signature_or_404(sid)
    if s["status"] != "SUBMITTED":
        errors.raise_err(errors.SIGNATURE_NOT_VERIFIABLE,
                         "Signature must be SUBMITTED to reject")
    pet = STORE.petitions[s["petition_id"]]
    if pet["status"] != "CIRCULATING":
        errors.raise_err(errors.PETITION_NOT_CIRCULATING,
                         "The petition is not circulating")
    s["status"] = "REJECTED"
    s["rejection_reason"] = reason
    touch(s)
    return ok_object(ser_signature(s))


@bp.route("/signatures/<sid>/withdraw", methods=["POST"])
def withdraw_signature(sid):
    shape.get_body()
    ctx = authenticate()
    require_role(ctx, ["PropertyOwner"])
    s = _signature_or_404(sid)
    if s["owner_id"] != ctx.user_id:
        errors.raise_err(errors.NOT_RESOURCE_OWNER,
                         "Only the signing owner may withdraw the signature")
    pet = STORE.petitions[s["petition_id"]]
    if pet["status"] != "CIRCULATING" or s["status"] not in ("SUBMITTED", "VERIFIED"):
        errors.raise_err(errors.SIGNATURE_NOT_WITHDRAWABLE,
                         "Signature can be withdrawn only while the petition circulates")
    s["status"] = "WITHDRAWN"
    s["withdrawn_at"] = now()
    touch(s)
    touch(pet)
    return ok_object(ser_signature(s))
