"""Dealers, technicians, vehicles and vehicle history events (PRD 3.2)."""
from flask import Blueprint

import cascades as cas
import enums
import helpers as h
import serializers as ser
from db import cfg, db, new_id
from errors import ApiError

bp = Blueprint("participants", __name__)

LIVE_CERT_STATUSES = ("ACTIVE", "UNDER_AUDIT")


def dealer_or_404(dealer_id):
    row = db.dealers.get(dealer_id)
    if row is None:
        raise ApiError("ERR_DEALER_NOT_FOUND", "No dealer with that id.")
    return row


def vehicle_or_404(vehicle_id):
    row = db.vehicles.get(vehicle_id)
    if row is None:
        raise ApiError("ERR_VEHICLE_NOT_FOUND", "No vehicle with that id.")
    return row


def new_dealer_row(name, franchise_code, region_code):
    return h.new_common(
        {
            "id": new_id(),
            "name": name,
            "franchise_code": franchise_code,
            "region_code": region_code,
            "privilege_status": "ACTIVE",
            "privilege_reason": None,
            "lifetime_submitted_count": 0,
            "lifetime_activated_count": 0,
            "window_activated_count": 0,
            "active_certification_count": 0,
            "approved_claim_count_lifetime": 0,
            "approved_claim_count_window": 0,
            "claim_ratio_variant": "LIFETIME_CUMULATIVE",
            "claim_ratio_effective": 0.0,
            "audit_sample_count": 0,
            "audit_fail_count": 0,
            "audit_fail_rate": 0.0,
            "risk_score": 0,
            "fee_billed_cents_total": 0,
            "fee_credited_cents_total": 0,
            "fee_balance_cents": 0,
        }
    )


# --------------------------------------------------------------------------- #
# dealers
# --------------------------------------------------------------------------- #
@bp.route("/dealers", methods=["POST"])
def create_dealer():
    h.authorize(("ProgramAdministrator",))
    body = h.body_dict()
    name = h.f_string(body, "name")
    franchise_code = h.f_string(body, "franchise_code")
    region_code = h.f_string(body, "region_code")
    for existing in db.dealers.values():
        if existing["franchise_code"] == franchise_code:
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE", "A dealer already uses that franchise_code."
            )
    row = new_dealer_row(name, franchise_code, region_code)
    db.dealers[row["id"]] = row
    return h.object_response(ser.dealer(row), 201)


@bp.route("/dealers/<dealer_id>", methods=["GET"])
def read_dealer(dealer_id):
    h.authorize(("ProgramAdministrator", "ProgramAuditor", "DealerPrincipal"))
    return h.object_response(ser.dealer(dealer_or_404(dealer_id)))


@bp.route("/dealers/<dealer_id>/privilege", methods=["PATCH"])
def move_privilege(dealer_id):
    h.authorize(("ProgramAdministrator",))
    body = h.body_dict()
    status = h.f_enum(body, "privilege_status", enums.PRIVILEGE_STATUSES)
    reason = h.f_enum(
        body, "privilege_reason", enums.PRIVILEGE_REASONS, required=False,
        default="ADMIN_ACTION",
    )
    dealer = dealer_or_404(dealer_id)
    if status == "SUSPENDED":
        cas.suspend_dealer(dealer, reason, ("DRAFT", "SYNDICATED"))
    else:
        dealer["privilege_status"] = status
        dealer["privilege_reason"] = reason
        h.touch(dealer)
    return h.object_response(ser.dealer(dealer))


# --------------------------------------------------------------------------- #
# technicians
# --------------------------------------------------------------------------- #
@bp.route("/dealers/<dealer_id>/technicians", methods=["POST"])
def create_technician(dealer_id):
    h.authorize(("ProgramAdministrator", "DealerPrincipal"))
    body = h.body_dict()
    name = h.f_string(body, "name")
    credential_id = h.f_string(body, "credential_id")
    credential_expires_at = h.f_instant(body, "credential_expires_at")
    credential_status = h.f_enum(
        body, "credential_status", enums.CREDENTIAL_STATUSES, required=False,
        default="ACTIVE",
    )
    dealer_or_404(dealer_id)
    for existing in db.technicians.values():
        if existing["dealer_id"] == dealer_id and existing["credential_id"] == credential_id:
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE",
                "That credential_id is already registered under this dealer.",
            )
    row = h.new_common(
        {
            "id": new_id(),
            "dealer_id": dealer_id,
            "name": name,
            "credential_id": credential_id,
            "credential_expires_at": credential_expires_at,
            "credential_status": credential_status,
        }
    )
    db.technicians[row["id"]] = row
    return h.object_response(ser.technician(row), 201)


@bp.route("/dealers/<dealer_id>/technicians", methods=["GET"])
def list_technicians(dealer_id):
    h.authorize(("ProgramAdministrator", "ProgramAuditor", "DealerPrincipal"))
    credential_status = h.q_enum("credential_status", enums.CREDENTIAL_STATUSES)
    limit, offset = h.pagination()
    dealer_or_404(dealer_id)
    rows = [t for t in db.technicians.values() if t["dealer_id"] == dealer_id]
    if credential_status:
        rows = [r for r in rows if r["credential_status"] == credential_status]
    return h.paged(rows, limit, offset, ser.technician)


# --------------------------------------------------------------------------- #
# vehicles
# --------------------------------------------------------------------------- #
@bp.route("/vehicles", methods=["POST"])
def create_vehicle():
    h.authorize(("ProgramAdministrator", "DealerPrincipal"))
    body = h.body_dict()
    vin = h.f_string(body, "vin")
    if len(vin) != 17:
        h.bad_request("Field 'vin' must be exactly 17 characters.")
    model_year = h.f_int(body, "model_year")
    in_service_date = h.f_date(body, "in_service_date")
    odometer_miles = h.f_int(body, "odometer_miles", minimum=0)
    # Only CLEAN may be supplied at registration; every other brand arrives
    # later through a TITLE_BRANDED history event.
    title_brand = h.f_enum(body, "title_brand", ("CLEAN",), required=False, default="CLEAN")
    prior_use = h.f_enum(body, "prior_use", enums.PRIOR_USES)
    owner_count = h.f_int(body, "owner_count", required=False, default=1, minimum=0)

    for existing in db.vehicles.values():
        if existing["vin"] == vin:
            raise ApiError("ERR_DUPLICATE_RESOURCE", "A vehicle already uses that VIN.")

    row = h.new_common(
        {
            "id": new_id(),
            "vin": vin,
            "model_year": model_year,
            "in_service_date": in_service_date,
            "odometer_miles": odometer_miles,
            "title_brand": title_brand,
            "prior_use": prior_use,
            "owner_count": owner_count,
            "cpo_state": "NOT_CERTIFIED",
            "inventory_state": "IN_INVENTORY",
            "decertified_at": None,
            "last_history_event_type": None,
            "last_history_event_at": None,
        }
    )
    db.vehicles[row["id"]] = row
    return h.object_response(ser.vehicle(row), 201)


@bp.route("/vehicles/<vehicle_id>", methods=["GET"])
def read_vehicle(vehicle_id):
    h.authorize(
        ("ProgramAdministrator", "ProgramAuditor", "DealerPrincipal", "CustomerAdvocate")
    )
    return h.object_response(ser.vehicle(vehicle_or_404(vehicle_id)))


_DISPOSITION_SOURCES = {
    "RETAIL_SOLD": ("IN_INVENTORY",),
    "WHOLESALED": ("IN_INVENTORY",),
    "RETURNED_TO_INVENTORY": ("RETAIL_SOLD", "WHOLESALED"),
}


@bp.route("/vehicles/<vehicle_id>/history-events", methods=["POST"])
def record_history_event(vehicle_id):
    h.authorize(("ProgramAdministrator", "DealerPrincipal"))
    body = h.body_dict()
    event_type = h.f_enum(body, "event_type", enums.HISTORY_EVENT_TYPES)
    odometer_miles = h.f_int(body, "odometer_miles", required=False, minimum=0)
    title_brand = h.f_enum(body, "title_brand", enums.TITLE_BRANDS, required=False)
    if event_type == "TITLE_BRANDED" and title_brand is None:
        h.bad_request("A TITLE_BRANDED event requires a title_brand.")

    vehicle = vehicle_or_404(vehicle_id)

    allowed_sources = _DISPOSITION_SOURCES.get(event_type)
    if allowed_sources is not None and vehicle["inventory_state"] not in allowed_sources:
        raise ApiError(
            "ERR_VEHICLE_HISTORY_EVENT_INVALID",
            "%s is not a declared transition out of %s."
            % (event_type, vehicle["inventory_state"]),
        )
    if odometer_miles is not None and odometer_miles < vehicle["odometer_miles"]:
        raise ApiError(
            "ERR_VEHICLE_HISTORY_EVENT_INVALID",
            "The odometer never runs backwards.",
        )

    if odometer_miles is not None:
        vehicle["odometer_miles"] = odometer_miles
    vehicle["last_history_event_type"] = event_type
    vehicle["last_history_event_at"] = db.clock
    h.touch(vehicle)

    if event_type == "TITLE_BRANDED":
        vehicle["title_brand"] = title_brand
        _decertify_live(vehicle, "TITLE_BRANDED")
    elif event_type == "RETAIL_SOLD":
        vehicle["inventory_state"] = "RETAIL_SOLD"
        _decertify_live(vehicle, "RETAIL_SOLD")
    elif event_type == "WHOLESALED":
        vehicle["inventory_state"] = "WHOLESALED"
        _decertify_live(vehicle, "WHOLESALED")
    elif event_type == "RETURNED_TO_INVENTORY":
        vehicle["inventory_state"] = "IN_INVENTORY"

    return h.object_response(ser.vehicle(vehicle))


def _decertify_live(vehicle, reason):
    for certification in list(db.certifications.values()):
        if (
            certification["vehicle_id"] == vehicle["id"]
            and certification["status"] in LIVE_CERT_STATUSES
        ):
            cas.decertify_certification(certification, reason)
