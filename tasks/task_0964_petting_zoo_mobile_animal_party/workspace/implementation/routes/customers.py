"""Customers, venues, and insurance certificates (PRD §3.1)."""
from flask import Blueprint

from db import store
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_FORBIDDEN,
    ERR_CUSTOMER_NOT_FOUND, ERR_VENUE_NOT_FOUND, ERR_CERTIFICATE_NOT_FOUND,
    ERR_INVALID_STATE,
)
from middleware import require, check_customer_ownership
from response import ok
from serializers import ser_customer, ser_venue, ser_insurance_certificate
from util import (
    body_json, new_common, paginate, v_bool, v_dt, v_enum, v_int, v_str,
)

bp = Blueprint("customers", __name__)

CUSTOMER_TYPES = {"PRIVATE", "SCHOOL", "LIBRARY"}
VENUE_TYPES = {"INDOOR", "OUTDOOR", "MIXED"}
SURFACE_TYPES = {"GRASS", "PAVEMENT", "INDOOR_FLOOR"}
TRAVEL_ZONES = {"ZONE_A", "ZONE_B", "ZONE_C"}


def get_customer_or_404(customer_id):
    customer = store.customers.get(customer_id)
    if customer is None:
        raise_err(ERR_CUSTOMER_NOT_FOUND, "Customer not found")
    return customer


@bp.post("/petting-zoo/customers")
def create_customer():
    require({"Anonymous"})
    body = body_json()
    email = v_str(body, "email")
    full_name = v_str(body, "full_name")
    customer_type = v_enum(body, "customer_type", CUSTOMER_TYPES)
    if any(c["email"] == email for c in store.customers.values()):
        raise_err(ERR_INVALID_REQUEST, "Email is already registered")
    customer = new_common()
    customer.update({"email": email, "full_name": full_name, "customer_type": customer_type})
    store.customers[customer["id"]] = customer
    return ok(ser_customer(customer), status=201)


@bp.get("/petting-zoo/customers/<customer_id>")
def get_customer(customer_id):
    role, uid = require({"Customer", "Coordinator", "ComplianceOfficer", "Operator"})
    if role == "Customer" and customer_id != uid:
        raise_err(ERR_FORBIDDEN, "Customer may only access its own resources")
    return ok(ser_customer(get_customer_or_404(customer_id)))


@bp.get("/petting-zoo/customers/<customer_id>/venues")
def list_customer_venues(customer_id):
    role, uid = require({"Customer", "Coordinator"})
    if role == "Customer" and customer_id != uid:
        raise_err(ERR_FORBIDDEN, "Customer may only access its own resources")
    get_customer_or_404(customer_id)
    venues = [v for v in store.venues.values() if v["customer_id"] == customer_id]
    data, meta = paginate(venues, ser_venue)
    return ok(data, pagination=meta)


@bp.post("/petting-zoo/customers/<customer_id>/insurance-certificates")
def create_insurance_certificate(customer_id):
    role, uid = require({"Customer"})
    body = body_json()
    provider = v_str(body, "provider")
    policy_number = v_str(body, "policy_number")
    coverage_amount_cents = v_int(body, "coverage_amount_cents")
    expires_at = v_dt(body, "expires_at")
    if customer_id != uid:
        raise_err(ERR_FORBIDDEN, "Customer may only manage its own certificates")
    get_customer_or_404(customer_id)
    cert = new_common()
    cert.update({
        "customer_id": customer_id,
        "provider": provider,
        "policy_number": policy_number,
        "coverage_amount_cents": coverage_amount_cents,
        "expires_at": expires_at,
        "status": "SUBMITTED",
    })
    store.insurance_certificates[cert["id"]] = cert
    return ok(ser_insurance_certificate(cert), status=201)


@bp.get("/petting-zoo/customers/<customer_id>/insurance-certificates")
def list_insurance_certificates(customer_id):
    role, uid = require({"Customer", "ComplianceOfficer", "Operator"})
    if role == "Customer" and customer_id != uid:
        raise_err(ERR_FORBIDDEN, "Customer may only access its own certificates")
    get_customer_or_404(customer_id)
    certs = [c for c in store.insurance_certificates.values() if c["customer_id"] == customer_id]
    data, meta = paginate(certs, ser_insurance_certificate)
    return ok(data, pagination=meta)


@bp.post("/petting-zoo/insurance-certificates/<cert_id>/verify")
def verify_insurance_certificate(cert_id):
    require({"ComplianceOfficer"})
    body = body_json()
    decision = v_enum(body, "decision", {"VERIFIED", "REJECTED"})
    cert = store.insurance_certificates.get(cert_id)
    if cert is None:
        raise_err(ERR_CERTIFICATE_NOT_FOUND, "Insurance certificate not found")
    if cert["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Certificate is not in SUBMITTED state")
    from util import bump
    cert["status"] = decision
    bump(cert)
    return ok(ser_insurance_certificate(cert))


# ---------------------------------------------------------------------------
# Venues
# ---------------------------------------------------------------------------

@bp.post("/petting-zoo/venues")
def create_venue():
    role, uid = require({"Customer"})
    body = body_json()
    venue = new_common()
    venue.update({
        "customer_id": uid,  # owning customer from X-User-ID, never the body
        "name": v_str(body, "name"),
        "address": v_str(body, "address"),
        "venue_type": v_enum(body, "venue_type", VENUE_TYPES),
        "water_access": v_bool(body, "water_access"),
        "surface_type": v_enum(body, "surface_type", SURFACE_TYPES),
        "travel_zone": v_enum(body, "travel_zone", TRAVEL_ZONES),
        "distance_miles": v_int(body, "distance_miles"),
        "max_guest_capacity": v_int(body, "max_guest_capacity"),
        "requires_animal_permit": v_bool(body, "requires_animal_permit"),
        "requires_handwash_stations": v_bool(body, "requires_handwash_stations"),
    })
    store.venues[venue["id"]] = venue
    return ok(ser_venue(venue), status=201)


@bp.get("/petting-zoo/venues/<venue_id>")
def get_venue(venue_id):
    role, uid = require({"Customer", "Coordinator", "Operator"})
    venue = store.venues.get(venue_id)
    if venue is None:
        raise_err(ERR_VENUE_NOT_FOUND, "Venue not found")
    check_customer_ownership(role, uid, venue["customer_id"])
    return ok(ser_venue(venue))
