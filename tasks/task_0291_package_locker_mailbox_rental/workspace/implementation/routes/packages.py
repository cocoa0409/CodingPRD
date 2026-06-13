"""Package endpoints."""
import random

from flask import Blueprint, request, g

from db import db, new_id, now_iso
from errors import err
from response import success, list_response
from middleware import require_roles
from common import (get_json, require_fields, require_str, require_enum, require_int,
                    fk_or_404, get_or_404, touch, parse_pagination, paginate,
                    require_customer_owns)
import constants as C
import calculations as calc
import clock
import serializers as S
from services import billing
from services import packages as pkg_svc

bp = Blueprint("packages", __name__)


def _agreement_customer(agreement):
    return agreement["customer_id"]


def _mint_pickup_code():
    return f"{random.randint(0, 999999):06d}"


@bp.post("/packages")
def receive_package():
    require_roles("FacilityOperator")
    body = get_json()
    require_fields(body, ["facility_id", "rental_agreement_id", "carrier",
                          "size_tier", "longest_dim_cm", "weight_g"])
    facility_id = require_str(body, "facility_id")
    rental_agreement_id = require_str(body, "rental_agreement_id")
    carrier = require_enum(body, "carrier", C.CARRIERS)
    size_tier = require_enum(body, "size_tier", C.LOCKER_SIZE_TIERS)
    longest_dim_cm = require_int(body, "longest_dim_cm", minimum=1)
    weight_g = require_int(body, "weight_g", minimum=1)
    facility = fk_or_404(db.facilities, facility_id)
    agreement = fk_or_404(db.rental_agreements, rental_agreement_id)
    # Receipt against a non-ACTIVE agreement -> ERR_AUTH_NOT_VERIFIED.
    if agreement["status"] != "ACTIVE":
        raise err("ERR_AUTH_NOT_VERIFIED", "Rental agreement must be ACTIVE to receive package")
    # Find a free AVAILABLE locker of the requested size_tier in this facility.
    locker = None
    candidates = [l for l in db.locker_units.values()
                  if l["facility_id"] == facility_id and l["size_tier"] == size_tier
                  and l["status"] == "AVAILABLE"]
    candidates.sort(key=lambda l: (l["created_at"], l.get("_seq", 0)))
    if candidates:
        locker = candidates[0]
    if locker is None:
        raise err("ERR_NO_LOCKER_AVAILABLE", "No available locker of requested size")
    pid = new_id()
    oversize = calc.oversize_fee_cents(locker["size_tier"], longest_dim_cm, weight_g)
    package = {
        "id": pid,
        "facility_id": facility_id,
        "rental_agreement_id": rental_agreement_id,
        "locker_unit_id": locker["id"],
        "carrier": carrier,
        "size_tier": size_tier,
        "longest_dim_cm": longest_dim_cm,
        "weight_g": weight_g,
        "pickup_code": _mint_pickup_code(),
        "notified_at": None,
        "resolved_at": None,
        "oversize_fee_cents": oversize,
        "overstay_fee_cents": 0,
        "status": "RECEIVED",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.packages[pid] = package
    # Occupy the locker.
    locker["status"] = "OCCUPIED"
    locker["current_package_id"] = pid
    touch(locker)
    touch(facility)  # available_locker_count shifted
    return success(S.package_out(package), status=201)


@bp.get("/packages/<pid>")
def get_package(pid):
    require_roles("FacilityOperator", "ComplianceOfficer", "Customer")
    package = get_or_404(db.packages, pid)
    agreement = db.rental_agreements.get(package["rental_agreement_id"])
    if agreement is not None:
        require_customer_owns(agreement["customer_id"])
    return success(S.package_out(package))


@bp.get("/packages")
def list_packages():
    require_roles("FacilityOperator", "ComplianceOfficer", "Customer")
    limit, offset = parse_pagination()
    items = list(db.packages.values())
    if g.role == "Customer":
        owned_agreements = {a["id"] for a in db.rental_agreements.values()
                            if a["customer_id"] == g.user_id}
        items = [x for x in items if x["rental_agreement_id"] in owned_agreements]
    for key in ("facility_id", "rental_agreement_id", "locker_unit_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [x for x in items if x.get(key) == val]
    page, total = paginate(items, limit, offset)
    return list_response([S.package_out(x) for x in page], limit, offset, total)


@bp.post("/packages/<pid>/notify")
def notify(pid):
    require_roles("FacilityOperator")
    package = get_or_404(db.packages, pid)
    if package["status"] != "RECEIVED":
        raise err("ERR_INVALID_STATE", "Package must be RECEIVED to notify")
    facility = db.facilities[package["facility_id"]]
    package["status"] = "NOTIFIED"
    package["notified_at"] = facility["current_utc"]
    pkg_svc.recompute_provisional_overstay(package, facility)
    touch(package)
    return success(S.package_out(package))


@bp.post("/packages/<pid>/pickup")
def pickup(pid):
    require_roles("FacilityOperator")
    package = get_or_404(db.packages, pid)
    body = get_json()
    require_fields(body, ["pickup_code", "expected_package_version"])
    supplied_code = body.get("pickup_code")
    expected = body.get("expected_package_version")
    if not isinstance(supplied_code, str) or supplied_code == "":
        raise err("ERR_INVALID_REQUEST", "pickup_code must be a non-empty string")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_package_version must be an integer")
    if package["status"] != "NOTIFIED":
        raise err("ERR_INVALID_STATE", "Package must be NOTIFIED to pick up")
    if expected != package["version"]:
        raise err("ERR_STALE_VERSION", "Package version is stale")
    if supplied_code != package["pickup_code"]:
        raise err("ERR_PICKUP_CODE_MISMATCH", "Pickup code does not match")
    agreement = db.rental_agreements.get(package["rental_agreement_id"])
    if agreement is None or agreement["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Owning agreement must be ACTIVE or SUSPENDED")
    facility = db.facilities[package["facility_id"]]
    resolved = clock.parse_iso(facility["current_utc"])
    pkg_svc.finalize_overstay(package, facility, resolved)
    package["resolved_at"] = facility["current_utc"]
    package["status"] = "PICKED_UP"
    invoice = pkg_svc.invoice_for_agreement(agreement["id"])
    if invoice is not None:
        pkg_svc.post_resolution_charges(package, agreement, invoice)
        billing.capture_autopay(agreement, invoice)
    pkg_svc.release_locker(package)
    touch(package)  # second version bump
    touch(facility)
    return success(S.package_out(package))


@bp.post("/packages/<pid>/forward")
def forward(pid):
    require_roles("Customer", "FacilityOperator")
    package = get_or_404(db.packages, pid)
    agreement = db.rental_agreements.get(package["rental_agreement_id"])
    if agreement is not None:
        require_customer_owns(agreement["customer_id"])
    body = get_json()
    require_fields(body, ["destination_address"])
    require_str(body, "destination_address")
    if package["status"] != "NOTIFIED":
        raise err("ERR_INVALID_STATE", "Package must be NOTIFIED to forward")
    if agreement is None or agreement["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "Owning agreement must be ACTIVE")
    facility = db.facilities[package["facility_id"]]
    resolved = clock.parse_iso(facility["current_utc"])
    pkg_svc.finalize_overstay(package, facility, resolved)
    package["resolved_at"] = facility["current_utc"]
    package["status"] = "FORWARDED"
    invoice = pkg_svc.invoice_for_agreement(agreement["id"])
    if invoice is not None:
        pkg_svc.post_resolution_charges(package, agreement, invoice)
        billing.post_ledger_entry(invoice, "CHARGE", "FORWARDING",
                                  C.PACKAGE_FORWARD_FEE_CENTS, package["id"])
        billing.capture_autopay(agreement, invoice)
    pkg_svc.release_locker(package)
    touch(facility)
    touch(package)
    return success(S.package_out(package))


@bp.post("/packages/<pid>/return-to-sender")
def return_to_sender(pid):
    require_roles("FacilityOperator")
    package = get_or_404(db.packages, pid)
    if package["status"] not in ("RECEIVED", "NOTIFIED"):
        raise err("ERR_INVALID_STATE", "Package must be RECEIVED or NOTIFIED to return")
    facility = db.facilities[package["facility_id"]]
    package["resolved_at"] = facility["current_utc"]
    package["status"] = "RETURNED"
    pkg_svc.release_locker(package)
    touch(facility)
    touch(package)
    return success(S.package_out(package))
