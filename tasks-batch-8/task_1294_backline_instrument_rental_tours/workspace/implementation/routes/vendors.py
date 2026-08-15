"""PartnerVendor and CrossRentalRequest endpoints (PRD §3.8)."""

from flask import Blueprint, request
import errors
from db import store
from middleware import get_auth, require_roles
from response import success_object, success_list
from services import domain, calculations as calc
from util import (body, req_str, req_int, req_str_list, new_resource, touch,
                  pagination_params, paginate, sort_by_created, day_count)

bp = Blueprint("vendors", __name__)

VENDOR_READ_ROLES = {"OpsManager", "TourManager", "LogisticsCoordinator"}
CRR_READ_ROLES = {"OpsManager", "TourManager", "LogisticsCoordinator", "PartnerVendorRep"}


# ---------------------------------------------------------------------------
# Partner vendors
# ---------------------------------------------------------------------------

@bp.route("/backline/partner-vendors", methods=["POST"])
def create_vendor():
    auth = get_auth()
    require_roles(auth, {"OpsManager"})
    data = body()
    commission = req_int(data, "commission_bps", minimum=0)
    if commission > 3000:
        raise errors.invalid_request("commission_bps must be between 0 and 3000")
    vendor = new_resource()
    vendor.update({
        "name": req_str(data, "name"),
        "city_codes": req_str_list(data, "city_codes"),
        "commission_bps": commission,
        "status": "PENDING",
    })
    store.partner_vendors[vendor["id"]] = vendor
    return success_object(domain.serialize(vendor), status=201)


@bp.route("/backline/partner-vendors/<vendor_id>", methods=["GET"])
def fetch_vendor(vendor_id):
    auth = get_auth()
    require_roles(auth, VENDOR_READ_ROLES)
    vendor = domain.get_vendor(vendor_id)
    return success_object(domain.serialize(vendor), status=200)


@bp.route("/backline/partner-vendors", methods=["GET"])
def list_vendors():
    auth = get_auth()
    require_roles(auth, VENDOR_READ_ROLES)
    limit, offset = pagination_params()
    status = request.args.get("status")
    items = list(store.partner_vendors.values())
    if status is not None:
        items = [v for v in items if v.get("status") == status]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success_list([domain.serialize(v) for v in page], meta, status=200)


@bp.route("/backline/partner-vendors/<vendor_id>/approve", methods=["POST"])
def approve_vendor(vendor_id):
    auth = get_auth()
    require_roles(auth, {"OpsManager"})
    vendor = domain.get_vendor(vendor_id)
    # PENDING -> APPROVED; SUSPENDED -> APPROVED reinstatement cycle permitted
    if vendor["status"] not in {"PENDING", "SUSPENDED"}:
        raise errors.invalid_state("Vendor must be PENDING or SUSPENDED to approve")
    vendor["status"] = "APPROVED"
    touch(vendor)
    return success_object(domain.serialize(vendor), status=200)


@bp.route("/backline/partner-vendors/<vendor_id>/suspend", methods=["POST"])
def suspend_vendor(vendor_id):
    auth = get_auth()
    require_roles(auth, {"OpsManager"})
    vendor = domain.get_vendor(vendor_id)
    if vendor["status"] != "APPROVED":
        raise errors.invalid_state("Vendor must be APPROVED to suspend")
    # Cascade: open cross-rental requests of this vendor are cancelled
    for cr in store.cross_rental_requests.values():
        if cr.get("partner_vendor_id") == vendor["id"] and \
                cr.get("status") in {"REQUESTED", "ACCEPTED"}:
            cr["status"] = "CANCELLED"
            touch(cr)
    vendor["status"] = "SUSPENDED"
    touch(vendor)
    return success_object(domain.serialize(vendor), status=200)


# ---------------------------------------------------------------------------
# Cross-rental requests
# ---------------------------------------------------------------------------

@bp.route("/backline/cross-rental-requests", methods=["POST"])
def create_cross_rental():
    auth = get_auth()
    require_roles(auth, {"LogisticsCoordinator"})
    data = body()
    reservation_line_id = req_str(data, "reservation_line_id")
    partner_vendor_id = req_str(data, "partner_vendor_id")
    gear_model_id = req_str(data, "gear_model_id")
    vendor_rate = req_int(data, "vendor_rate_cents_per_day", minimum=0)
    # Existence, left to right
    reservation = domain.get_reservation(reservation_line_id)
    vendor = domain.get_vendor(partner_vendor_id)
    domain.get_gear_model(gear_model_id)
    # Gate 13: vendor must be APPROVED and cover the stop's city
    rider_line = store.rider_lines.get(reservation.get("rider_line_id"))
    stop = store.tour_stops.get(rider_line["tour_stop_id"]) if rider_line else None
    stop_city = stop["city_code"] if stop else reservation.get("dest_city_code")
    if vendor.get("status") != "APPROVED" or \
            stop_city not in (vendor.get("city_codes") or []):
        raise errors.vendor_not_eligible("Vendor not eligible for this cross-rental")
    cr = new_resource()
    cr.update({
        "reservation_line_id": reservation_line_id,
        "partner_vendor_id": partner_vendor_id,
        "gear_model_id": gear_model_id,
        "status": "REQUESTED",
        "vendor_rate_cents_per_day": vendor_rate,
        "commission_cents": None,
    })
    store.cross_rental_requests[cr["id"]] = cr
    return success_object(domain.serialize(cr), status=201)


@bp.route("/backline/cross-rental-requests/<req_id>", methods=["GET"])
def fetch_cross_rental(req_id):
    auth = get_auth()
    require_roles(auth, CRR_READ_ROLES)
    cr = domain.get_cross_rental(req_id)
    return success_object(domain.serialize(cr), status=200)


@bp.route("/backline/cross-rental-requests", methods=["GET"])
def list_cross_rentals():
    auth = get_auth()
    require_roles(auth, CRR_READ_ROLES)
    limit, offset = pagination_params()
    reservation_line_id = request.args.get("reservation_line_id")
    partner_vendor_id = request.args.get("partner_vendor_id")
    gear_model_id = request.args.get("gear_model_id")
    status = request.args.get("status")
    items = list(store.cross_rental_requests.values())
    if reservation_line_id is not None:
        items = [c for c in items if c.get("reservation_line_id") == reservation_line_id]
    if partner_vendor_id is not None:
        items = [c for c in items if c.get("partner_vendor_id") == partner_vendor_id]
    if gear_model_id is not None:
        items = [c for c in items if c.get("gear_model_id") == gear_model_id]
    if status is not None:
        items = [c for c in items if c.get("status") == status]
    # Vendor reps are confined to their own company's requests (§2.1)
    if auth["role"] == "PartnerVendorRep":
        items = [c for c in items if c.get("partner_vendor_id") == auth["user_id"]]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success_list([domain.serialize(c) for c in page], meta, status=200)


def _vendor_rep_gate(auth, cr):
    """Ownership: acting rep's X-User-ID must equal the request's vendor id,
    and the vendor must still be APPROVED (gate 13)."""
    if auth["user_id"] != cr.get("partner_vendor_id"):
        raise errors.vendor_not_eligible("Rep belongs to a different vendor")
    vendor = store.partner_vendors.get(cr.get("partner_vendor_id"))
    if vendor is None or vendor.get("status") != "APPROVED":
        raise errors.vendor_not_eligible("Vendor is not APPROVED")
    return vendor


@bp.route("/backline/cross-rental-requests/<req_id>/accept", methods=["POST"])
def accept_cross_rental(req_id):
    auth = get_auth()
    require_roles(auth, {"PartnerVendorRep"})
    cr = domain.get_cross_rental(req_id)
    if cr["status"] != "REQUESTED":
        raise errors.invalid_state("Cross-rental request must be REQUESTED to accept")
    _vendor_rep_gate(auth, cr)
    cr["status"] = "ACCEPTED"
    touch(cr)
    return success_object(domain.serialize(cr), status=200)


@bp.route("/backline/cross-rental-requests/<req_id>/reject", methods=["POST"])
def reject_cross_rental(req_id):
    auth = get_auth()
    require_roles(auth, {"PartnerVendorRep"})
    cr = domain.get_cross_rental(req_id)
    if cr["status"] != "REQUESTED":
        raise errors.invalid_state("Cross-rental request must be REQUESTED to reject")
    if auth["user_id"] != cr.get("partner_vendor_id"):
        raise errors.vendor_not_eligible("Rep belongs to a different vendor")
    cr["status"] = "REJECTED"
    touch(cr)
    return success_object(domain.serialize(cr), status=200)


@bp.route("/backline/cross-rental-requests/<req_id>/mark-fulfilled", methods=["POST"])
def fulfill_cross_rental(req_id):
    auth = get_auth()
    require_roles(auth, {"PartnerVendorRep"})
    cr = domain.get_cross_rental(req_id)
    if cr["status"] != "ACCEPTED":
        raise errors.invalid_state("Cross-rental request must be ACCEPTED to fulfill")
    _vendor_rep_gate(auth, cr)
    reservation = domain.get_reservation(cr["reservation_line_id"])
    rider_line = store.rider_lines.get(reservation.get("rider_line_id"))
    tour = domain.get_tour(reservation["tour_id"])
    artist = store.artists.get(tour["artist_id"])
    model = store.gear_models.get(cr["gear_model_id"])
    # The reservation is driven DRAFT -> SOURCED without consuming an in-house
    # unit; the deposit hold is still computed and blocked against the artist
    # because cross-rental never waives the deposit (§3.8).
    deposit = calc.deposit_hold_rule(model["replacement_value_cents"],
                                     artist.get("deposit_waived", False))
    if artist.get("deposit_credit_cents", 0) < deposit:
        raise errors.deposit_insufficient("Artist deposit balance cannot cover the hold")
    days = day_count(reservation["_start_dt"], reservation["_end_dt"])
    quoted = calc.rental_fee_quote(cr["vendor_rate_cents_per_day"], days,
                                   reservation["origin_city_code"],
                                   reservation["dest_city_code"],
                                   artist.get("risk_score", 0))
    # Fulfillment drives the linked reservation DRAFT -> SOURCED without
    # consuming an in-house unit (§3.8). A reservation already past DRAFT is
    # left untouched by the transition itself.
    if reservation.get("status") == "DRAFT":
        reservation["is_cross_rental"] = True
        reservation["_vendor_rate_cents_per_day"] = cr["vendor_rate_cents_per_day"]
        reservation["quoted_fee_cents"] = quoted
        reservation["deposit_held_cents"] = deposit
        reservation["status"] = "SOURCED"
        touch(reservation)
        artist["deposit_credit_cents"] = artist.get("deposit_credit_cents", 0) - deposit
        touch(artist)
    if rider_line is not None and rider_line.get("status") == "REQUESTED":
        rider_line["status"] = "SOURCED"
        rider_line["fulfilled_by_reservation_id"] = reservation["id"]
        touch(rider_line)
        stop = store.tour_stops.get(rider_line.get("tour_stop_id"))
        if stop is not None:
            stop["rider_revision"] = stop.get("rider_revision", 0) + 1
            touch(stop)
    cr["status"] = "FULFILLED"
    touch(cr)
    return success_object(domain.serialize(cr), status=200)


@bp.route("/backline/cross-rental-requests/<req_id>/settle", methods=["POST"])
def settle_cross_rental(req_id):
    auth = get_auth()
    require_roles(auth, {"OpsManager"})
    cr = domain.get_cross_rental(req_id)
    if cr["status"] != "FULFILLED":
        raise errors.invalid_state("Cross-rental request must be FULFILLED to settle")
    reservation = domain.get_reservation(cr["reservation_line_id"])
    if reservation.get("status") != "SETTLED":
        raise errors.invalid_state("Linked reservation must be SETTLED before cross-rental settle")
    vendor = store.partner_vendors.get(cr["partner_vendor_id"])
    days = day_count(reservation["_start_dt"], reservation["_end_dt"])
    cr["commission_cents"] = calc.cross_rental_settlement(
        cr["vendor_rate_cents_per_day"], days, vendor.get("commission_bps", 0))
    cr["status"] = "SETTLED"
    touch(cr)
    return success_object(domain.serialize(cr), status=200)


@bp.route("/backline/cross-rental-requests/<req_id>/cancel", methods=["POST"])
def cancel_cross_rental(req_id):
    auth = get_auth()
    require_roles(auth, {"LogisticsCoordinator"})
    cr = domain.get_cross_rental(req_id)
    if cr["status"] not in {"REQUESTED", "ACCEPTED"}:
        raise errors.invalid_state("Only REQUESTED or ACCEPTED cross-rentals may be cancelled")
    cr["status"] = "CANCELLED"
    touch(cr)
    return success_object(domain.serialize(cr), status=200)
