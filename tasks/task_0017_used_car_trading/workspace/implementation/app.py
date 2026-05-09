"""Used-Car Trading API — Flask app entrypoint.

Implements the full REST surface from PRD §4 and SCAFFOLD §1.5.
"""

import os
import re

from flask import Flask, g, request

import audit
import calculations as calc
from clock import CLOCK, iso, now, parse_iso
from db import DB_INSTANCE, new_uuid
from errors import APIError, err
from helpers import (
    bump,
    check_version,
    get_body,
    paginate,
    parse_pagination,
    sort_for_list,
    stamp_new_record,
)
from middleware import auth_required, require_role
from response import error as resp_error
from response import ok, ok_list, replay
import services as svc


app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


# =============================================================================
# Global hooks: auth + error handling
# =============================================================================

@app.before_request
def _before():
    try:
        auth_required()
    except APIError as e:
        return resp_error(e.error_id, e.http_status, e.message)


@app.errorhandler(APIError)
def _handle_api_error(e: APIError):
    return resp_error(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def _handle_404(e):
    return resp_error("ERR_NOT_FOUND", 404, "Route not found")


@app.errorhandler(405)
def _handle_405(e):
    return resp_error("ERR_NOT_FOUND", 404, "Method not allowed")


@app.errorhandler(Exception)
def _handle_exception(e):
    # Generic fallback — never expose stack traces.
    if isinstance(e, APIError):
        return resp_error(e.error_id, e.http_status, e.message)
    return resp_error("ERR_INVALID_STATE", 500, str(e))


# =============================================================================
# Helpers (entity views)
# =============================================================================

def _seller_view(s):
    return s


def _buyer_view(b):
    # PRD §3.7 — running deposit_balance equals deposit_held at all times; recompute lazily
    svc.recompute_deposit(b["id"])
    return b


def _vehicle_view(v):
    return v


def _assessment_view(a):
    return a


def _listing_view(l):
    return l


def _bid_view(b):
    return b


def _reservation_view(r):
    return r


def _po_view(o):
    return o


def _loan_view(ln):
    return ln


def _transfer_view(t):
    return t


def _warranty_view(w):
    return w


def _claim_view(c):
    return c


def _dispute_view(d):
    return d


def _event_view(ev):
    return ev


def _audit_view(al):
    return al


def _require_uuid_lookup(table, key, name):
    obj = table.get(key)
    if not obj:
        raise err("ERR_NOT_FOUND", f"{name} not found")
    return obj


# =============================================================================
# Routes — Sellers / Buyers
# =============================================================================

@app.route("/sellers", methods=["POST"])
def create_seller():
    require_role("PlatformAdmin", "Seller")
    body = get_body()
    legal_name = body.get("legal_name")
    id_doc = body.get("id_document_number")
    phone = body.get("phone")
    if not legal_name or not id_doc or not phone:
        raise err("ERR_INVALID_STATE", "Missing required field")
    # Uniqueness on id_document_number
    for s in DB_INSTANCE.sellers.values():
        if s["id_document_number"] == id_doc:
            raise err("ERR_INVALID_STATE", "id_document_number already exists")
    sid = new_uuid()
    seller = {
        "id": sid,
        "legal_name": legal_name,
        "id_document_number": id_doc,
        "phone": phone,
        "kyc_status": "PENDING",
        "total_listings": 0,
    }
    stamp_new_record(seller)
    DB_INSTANCE.sellers[sid] = seller
    audit.log("Seller", sid, "STATE_TRANSITION", from_value=None, to_value="PENDING")
    return ok(_seller_view(seller), status=201)


@app.route("/buyers", methods=["POST"])
def create_buyer():
    require_role("PlatformAdmin", "Buyer")
    body = get_body()
    legal_name = body.get("legal_name")
    id_doc = body.get("id_document_number")
    phone = body.get("phone")
    if not legal_name or not id_doc or not phone:
        raise err("ERR_INVALID_STATE", "Missing required field")
    for b in DB_INSTANCE.buyers.values():
        if b["id_document_number"] == id_doc:
            raise err("ERR_INVALID_STATE", "id_document_number already exists")
    bid = new_uuid()
    buyer = {
        "id": bid,
        "legal_name": legal_name,
        "id_document_number": id_doc,
        "phone": phone,
        "deposit_balance_cents": 0,
        "deposit_held_cents": 0,
    }
    stamp_new_record(buyer)
    DB_INSTANCE.buyers[bid] = buyer
    return ok(_buyer_view(buyer), status=201)


@app.route("/buyers/<buyer_id>", methods=["GET"])
def get_buyer(buyer_id):
    require_role("PlatformAdmin", "Buyer")
    buyer = _require_uuid_lookup(DB_INSTANCE.buyers, buyer_id, "Buyer")
    if g.role == "Buyer" and g.user_id != buyer_id:
        raise err("ERR_NOT_OWNER", "Cannot read another buyer")
    return ok(_buyer_view(buyer))


# =============================================================================
# Routes — Vehicles & Assessments
# =============================================================================

VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


def _validate_vin(vin: str):
    if not isinstance(vin, str) or not VIN_RE.match(vin):
        raise err("ERR_VIN_INVALID", "VIN must be 17 alphanumeric chars excluding I/O/Q")


@app.route("/vehicles", methods=["POST"])
def create_vehicle():
    require_role("Seller")
    body = get_body()
    vin = body.get("vin", "")
    make = body.get("make")
    model = body.get("model")
    model_year = body.get("model_year")
    declared_mileage_km = body.get("declared_mileage_km")
    color = body.get("color")

    # VIN format check (priority 10)
    _validate_vin(vin)

    # model_year and mileage sanity
    cur_year = now().year
    try:
        my = int(model_year)
        if my < 1980 or my > cur_year:
            raise err("ERR_INVALID_STATE", "model_year out of range")
    except (TypeError, ValueError):
        raise err("ERR_INVALID_STATE", "model_year invalid")
    try:
        dm = int(declared_mileage_km)
        if dm < 0:
            raise err("ERR_INVALID_STATE", "declared_mileage_km must be >= 0")
    except (TypeError, ValueError):
        raise err("ERR_INVALID_STATE", "declared_mileage_km invalid")
    if not make or not model or not color:
        raise err("ERR_INVALID_STATE", "Missing required field")

    # VIN unique
    for v in DB_INSTANCE.vehicles.values():
        if v["vin"] == vin:
            raise err("ERR_INVALID_STATE", "VIN already exists")

    vid = new_uuid()
    vehicle = {
        "id": vid,
        "vin": vin,
        "make": make,
        "model": model,
        "model_year": my,
        "declared_mileage_km": dm,
        "verified_mileage_km": None,
        "color": color,
        "vehicle_status": "REGISTERED",
        "ownership_seller_id": g.user_id,
        "assessment_score": None,
        "valuation_cents": None,
    }
    stamp_new_record(vehicle)
    DB_INSTANCE.vehicles[vid] = vehicle
    audit.log("Vehicle", vid, "STATE_TRANSITION", from_value=None, to_value="REGISTERED")
    return ok(_vehicle_view(vehicle), status=201)


@app.route("/vehicles/<vehicle_id>", methods=["GET"])
def get_vehicle(vehicle_id):
    require_role("PlatformAdmin", "Seller", "Buyer", "Inspector")
    v = _require_uuid_lookup(DB_INSTANCE.vehicles, vehicle_id, "Vehicle")
    return ok(_vehicle_view(v))


@app.route("/vehicles", methods=["GET"])
def list_vehicles():
    require_role("PlatformAdmin", "Seller", "Buyer")
    limit, offset = parse_pagination(request.args)
    status_filter = request.args.get("status")
    seller_filter = request.args.get("seller_id")

    items = list(DB_INSTANCE.vehicles.values())
    if status_filter:
        items = [v for v in items if v["vehicle_status"] == status_filter]
    if seller_filter:
        items = [v for v in items if v["ownership_seller_id"] == seller_filter]
    items = sort_for_list(items)
    page, total = paginate(items, limit, offset)
    return ok_list([_vehicle_view(v) for v in page], limit, offset, total)


# ---- AssessmentReport ----

@app.route("/vehicles/<vehicle_id>/assessments", methods=["POST"])
def create_assessment(vehicle_id):
    require_role("Inspector")
    vehicle = _require_uuid_lookup(DB_INSTANCE.vehicles, vehicle_id, "Vehicle")
    body = get_body()
    vin_history = body.get("vin_history_records") or []
    inspector_user_id = body.get("inspector_user_id")
    if not isinstance(vin_history, list):
        raise err("ERR_INVALID_STATE", "vin_history_records must be a list")
    if not inspector_user_id:
        raise err("ERR_INVALID_STATE", "inspector_user_id is required")

    accident_count = 0
    major_accident_count = 0
    maintenance_count = 0
    for h in vin_history:
        if not isinstance(h, dict):
            continue
        et = h.get("event_type")
        sev = h.get("severity")
        if et == "ACCIDENT":
            accident_count += 1
            if sev == "MAJOR":
                major_accident_count += 1
        if et == "MAINTENANCE":
            maintenance_count += 1

    aid = new_uuid()
    report = {
        "id": aid,
        "vehicle_id": vehicle_id,
        "vin_history_records": vin_history,
        "accident_count": accident_count,
        "major_accident_count": major_accident_count,
        "maintenance_count": maintenance_count,
        "inspector_user_id": inspector_user_id,
        "onsite_findings": None,
        "declared_mileage_km": None,
        "mileage_discrepancy_flag": False,
        "provisional_valuation_cents": None,
        "final_valuation_cents": None,
        "status": "DRAFT",
    }
    stamp_new_record(report)
    DB_INSTANCE.assessments[aid] = report
    audit.log("AssessmentReport", aid, "STATE_TRANSITION",
              from_value=None, to_value="DRAFT")
    return ok(_assessment_view(report), status=201)


@app.route("/assessments/<assessment_id>/request-onsite", methods=["POST"])
def request_onsite(assessment_id):
    require_role("Inspector")
    rep = _require_uuid_lookup(DB_INSTANCE.assessments, assessment_id, "AssessmentReport")
    body = get_body()
    check_version(rep["version"], body)
    if rep["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "AssessmentReport must be DRAFT")
    if not rep["vin_history_records"]:
        raise err("ERR_INVALID_STATE", "vin_history_records must be non-empty")

    # Compute provisional valuation
    vehicle = DB_INSTANCE.vehicles.get(rep["vehicle_id"])
    declared_mileage = vehicle["declared_mileage_km"] if vehicle else 0
    rep["provisional_valuation_cents"] = calc.provisional_price_valuation(
        declared_mileage,
        rep["accident_count"],
        rep["maintenance_count"],
    )
    old = rep["status"]
    rep["status"] = "ONSITE_PENDING"
    bump(rep)
    audit.log("AssessmentReport", rep["id"], "STATE_TRANSITION",
              from_value=old, to_value="ONSITE_PENDING")
    return ok(_assessment_view(rep))


@app.route("/assessments/<assessment_id>/finalize", methods=["POST"])
def finalize_assessment(assessment_id):
    require_role("Inspector")
    rep = _require_uuid_lookup(DB_INSTANCE.assessments, assessment_id, "AssessmentReport")
    body = get_body()
    check_version(rep["version"], body)
    if rep["status"] != "ONSITE_PENDING":
        raise err("ERR_INVALID_STATE", "AssessmentReport must be ONSITE_PENDING")
    onsite = body.get("onsite_findings")
    if not isinstance(onsite, dict):
        raise err("ERR_INVALID_STATE", "onsite_findings missing")
    for k in ("exterior_grade", "interior_grade", "mechanical_grade", "mileage_km_observed"):
        if k not in onsite or onsite[k] is None:
            raise err("ERR_INVALID_STATE", f"onsite_findings.{k} required")
    for grade_field in ("exterior_grade", "interior_grade", "mechanical_grade"):
        if onsite[grade_field] not in calc.GRADE_VALUES:
            raise err("ERR_INVALID_STATE", f"{grade_field} must be one of A/B/C/D")
    if not rep.get("inspector_user_id"):
        raise err("ERR_INVALID_STATE", "inspector_user_id is required")

    vehicle = DB_INSTANCE.vehicles.get(rep["vehicle_id"])
    if not vehicle:
        raise err("ERR_NOT_FOUND", "Vehicle not found")

    declared_snapshot = vehicle["declared_mileage_km"]
    rep["onsite_findings"] = onsite
    rep["declared_mileage_km"] = declared_snapshot
    observed = int(onsite["mileage_km_observed"])
    rep["mileage_discrepancy_flag"] = calc.mileage_discrepancy(observed, declared_snapshot)

    rep["final_valuation_cents"] = calc.final_price_valuation(
        verified_mileage_km=observed,
        exterior_grade=onsite["exterior_grade"],
        interior_grade=onsite["interior_grade"],
        mechanical_grade=onsite["mechanical_grade"],
        accident_count=rep["accident_count"],
        major_accident_count=rep["major_accident_count"],
        maintenance_count=rep["maintenance_count"],
        mileage_discrepancy_flag=rep["mileage_discrepancy_flag"],
    )
    score = calc.assessment_score(
        verified_mileage_km=observed,
        exterior_grade=onsite["exterior_grade"],
        interior_grade=onsite["interior_grade"],
        mechanical_grade=onsite["mechanical_grade"],
        accident_count=rep["accident_count"],
        major_accident_count=rep["major_accident_count"],
        mileage_discrepancy_flag=rep["mileage_discrepancy_flag"],
    )

    # Update vehicle.verified_mileage_km, assessment_score, valuation_cents
    vehicle["verified_mileage_km"] = observed
    vehicle["assessment_score"] = score
    vehicle["valuation_cents"] = rep["final_valuation_cents"]
    bump(vehicle)

    # Vehicle REGISTERED → ASSESSED on first finalize; subsequent stays in ASSESSED.
    if vehicle["vehicle_status"] == "REGISTERED":
        svc.transition_vehicle(vehicle, "ASSESSED")

    # Move prior FINALIZED reports to SUPERSEDED
    for other in DB_INSTANCE.assessments.values():
        if other["id"] == rep["id"]:
            continue
        if other["vehicle_id"] != rep["vehicle_id"]:
            continue
        if other["status"] == "FINALIZED":
            old_status = other["status"]
            other["status"] = "SUPERSEDED"
            bump(other)
            audit.log("AssessmentReport", other["id"], "STATE_TRANSITION",
                      from_value=old_status, to_value="SUPERSEDED")

    old = rep["status"]
    rep["status"] = "FINALIZED"
    bump(rep)
    audit.log("AssessmentReport", rep["id"], "STATE_TRANSITION",
              from_value=old, to_value="FINALIZED")
    return ok(_assessment_view(rep))


@app.route("/assessments/<assessment_id>", methods=["GET"])
def get_assessment(assessment_id):
    require_role("PlatformAdmin", "Seller", "Buyer", "Inspector")
    rep = _require_uuid_lookup(DB_INSTANCE.assessments, assessment_id, "AssessmentReport")
    return ok(_assessment_view(rep))


# =============================================================================
# Routes — Listings
# =============================================================================

@app.route("/listings", methods=["POST"])
def create_listing():
    require_role("Seller")
    body = get_body()
    vehicle_id = body.get("vehicle_id")
    assessment_report_id = body.get("assessment_report_id")
    sale_mode = body.get("sale_mode")
    ask_price_cents = body.get("ask_price_cents")
    reserve_price_cents = body.get("reserve_price_cents")
    photo_urls = body.get("photo_urls") or []
    documents_authentic_flag = bool(body.get("documents_authentic_flag", False))

    # Existence (priority 5)
    vehicle = _require_uuid_lookup(DB_INSTANCE.vehicles, vehicle_id, "Vehicle")
    rep = _require_uuid_lookup(DB_INSTANCE.assessments, assessment_report_id, "AssessmentReport")

    # Ownership: only the seller of the vehicle may create a listing
    if vehicle.get("ownership_seller_id") != g.user_id:
        raise err("ERR_NOT_OWNER", "Only the vehicle owner can list it")

    # Assessment must be FINALIZED at creation time
    if rep["status"] != "FINALIZED":
        raise err("ERR_ASSESSMENT_NOT_FINALIZED", "Pinned assessment must be FINALIZED")
    if rep["vehicle_id"] != vehicle_id:
        raise err("ERR_ASSESSMENT_NOT_FINALIZED", "Assessment vehicle mismatch")

    if sale_mode not in ("AUCTION", "FIXED_PRICE"):
        raise err("ERR_INVALID_STATE", "sale_mode must be AUCTION or FIXED_PRICE")
    try:
        ask_price = int(ask_price_cents)
        if ask_price < 0:
            raise err("ERR_INVALID_STATE", "ask_price_cents must be >= 0")
    except (TypeError, ValueError):
        raise err("ERR_INVALID_STATE", "ask_price_cents invalid")
    if sale_mode == "FIXED_PRICE" and reserve_price_cents is not None:
        raise err("ERR_INVALID_STATE", "reserve_price_cents must be null for FIXED_PRICE")
    if sale_mode == "AUCTION" and reserve_price_cents is not None:
        try:
            int(reserve_price_cents)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_STATE", "reserve_price_cents invalid")
    if not isinstance(photo_urls, list):
        raise err("ERR_INVALID_STATE", "photo_urls must be a list")

    lid = new_uuid()
    listing = {
        "id": lid,
        "vehicle_id": vehicle_id,
        "seller_id": g.user_id,
        "assessment_report_id": assessment_report_id,
        "assessment_report_version": None,
        "sale_mode": sale_mode,
        "ask_price_cents": ask_price,
        "reserve_price_cents": int(reserve_price_cents) if reserve_price_cents is not None else None,
        "photo_urls": list(photo_urls),
        "documents_authentic_flag": documents_authentic_flag,
        "doc_check_status": "NOT_RUN",
        "status": "DRAFT",
        "active_bid_id": None,
        "reservation_buyer_id": None,
    }
    stamp_new_record(listing)
    DB_INSTANCE.listings[lid] = listing

    # Increment seller's total_listings counter
    seller = DB_INSTANCE.sellers.get(g.user_id)
    if seller:
        seller["total_listings"] = seller.get("total_listings", 0) + 1
        bump(seller)

    audit.log("Listing", lid, "STATE_TRANSITION", from_value=None, to_value="DRAFT")
    return ok(_listing_view(listing), status=201)


@app.route("/listings/<listing_id>/submit", methods=["POST"])
def submit_listing(listing_id):
    require_role("Seller")
    listing = _require_uuid_lookup(DB_INSTANCE.listings, listing_id, "Listing")
    body = get_body()
    if listing["seller_id"] != g.user_id:
        raise err("ERR_NOT_OWNER", "Only the seller may submit this listing")
    check_version(listing["version"], body)
    if listing["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Listing must be DRAFT")

    rep = DB_INSTANCE.assessments.get(listing["assessment_report_id"])
    if not rep:
        raise err("ERR_NOT_FOUND", "AssessmentReport not found")
    # docs sufficiency
    if len(listing.get("photo_urls") or []) < 6 or not listing.get("documents_authentic_flag"):
        raise err("ERR_LISTING_DOCS_INSUFFICIENT", "Need >= 6 photos and attestation")
    if rep["status"] != "FINALIZED":
        raise err("ERR_ASSESSMENT_NOT_FINALIZED", "Pinned report must be FINALIZED")

    listing["assessment_report_version"] = rep["version"]
    old = listing["status"]
    listing["status"] = "UNDER_REVIEW"
    bump(listing)
    audit.log("Listing", listing["id"], "STATE_TRANSITION",
              from_value=old, to_value="UNDER_REVIEW")
    return ok(_listing_view(listing))


@app.route("/listings/<listing_id>/approve", methods=["POST"])
def approve_listing(listing_id):
    require_role("PlatformAdmin")
    listing = _require_uuid_lookup(DB_INSTANCE.listings, listing_id, "Listing")
    body = get_body()
    check_version(listing["version"], body)
    if listing["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Listing must be UNDER_REVIEW")
    rep = DB_INSTANCE.assessments.get(listing["assessment_report_id"])
    if not rep:
        raise err("ERR_NOT_FOUND", "AssessmentReport not found")
    if listing.get("assessment_report_version") != rep["version"]:
        raise err("ERR_ASSESSMENT_VERSION_STALE",
                  "Pinned assessment_report_version is stale")

    listing["doc_check_status"] = "PASS"
    old = listing["status"]
    listing["status"] = "ACTIVE"
    bump(listing)
    audit.log("Listing", listing["id"], "STATE_TRANSITION",
              from_value=old, to_value="ACTIVE")

    # Vehicle ASSESSED → LISTED
    vehicle = DB_INSTANCE.vehicles.get(listing["vehicle_id"])
    if vehicle and vehicle["vehicle_status"] == "ASSESSED":
        svc.transition_vehicle(vehicle, "LISTED")
    return ok(_listing_view(listing))


@app.route("/listings/<listing_id>/reject", methods=["POST"])
def reject_listing(listing_id):
    require_role("PlatformAdmin")
    listing = _require_uuid_lookup(DB_INSTANCE.listings, listing_id, "Listing")
    body = get_body()
    check_version(listing["version"], body)
    if listing["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Listing must be UNDER_REVIEW")
    listing["doc_check_status"] = "FAIL"
    old = listing["status"]
    listing["status"] = "REJECTED"
    bump(listing)
    audit.log("Listing", listing["id"], "STATE_TRANSITION",
              from_value=old, to_value="REJECTED")
    return ok(_listing_view(listing))


@app.route("/listings/<listing_id>/return-for-revision", methods=["POST"])
def return_for_revision(listing_id):
    require_role("PlatformAdmin")
    listing = _require_uuid_lookup(DB_INSTANCE.listings, listing_id, "Listing")
    body = get_body()
    check_version(listing["version"], body)
    if listing["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Listing must be UNDER_REVIEW")
    old = listing["status"]
    listing["status"] = "DRAFT"
    bump(listing)
    audit.log("Listing", listing["id"], "STATE_TRANSITION",
              from_value=old, to_value="DRAFT")
    return ok(_listing_view(listing))


@app.route("/listings/<listing_id>/delist", methods=["POST"])
def delist_listing(listing_id):
    require_role("Seller")
    listing = _require_uuid_lookup(DB_INSTANCE.listings, listing_id, "Listing")
    body = get_body()
    if listing["seller_id"] != g.user_id:
        raise err("ERR_NOT_OWNER", "Only the seller may delist")
    check_version(listing["version"], body)
    if listing["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Listing must be ACTIVE")
    # No LIVE bid and no HOLDING reservation
    for b in DB_INSTANCE.bids.values():
        if b["listing_id"] == listing["id"] and b["status"] == "LIVE":
            raise err("ERR_INVALID_STATE", "Active bid in progress")
    for r in DB_INSTANCE.reservations.values():
        if r["listing_id"] == listing["id"] and r["status"] == "HOLDING":
            raise err("ERR_INVALID_STATE", "Active reservation in progress")

    # Cancel queued reservations + release deposits
    buyers_to_recompute = set()
    for r in DB_INSTANCE.reservations.values():
        if r["listing_id"] == listing["id"] and r["status"] == "QUEUED":
            svc.transition_reservation(r, "CANCELLED")
            buyers_to_recompute.add(r["buyer_id"])
    old = listing["status"]
    listing["status"] = "DELISTED"
    bump(listing)
    audit.log("Listing", listing["id"], "STATE_TRANSITION",
              from_value=old, to_value="DELISTED")

    # Vehicle LISTED → ASSESSED if no other active listings
    vehicle = DB_INSTANCE.vehicles.get(listing["vehicle_id"])
    if vehicle and vehicle["vehicle_status"] == "LISTED":
        if not svc.vehicle_has_other_active_listings(vehicle["id"], exclude_listing_id=listing["id"]):
            svc.transition_vehicle(vehicle, "ASSESSED")

    for b in buyers_to_recompute:
        svc.recompute_deposit(b)
    return ok(_listing_view(listing))


@app.route("/listings", methods=["GET"])
def list_listings():
    require_role("PlatformAdmin", "Seller", "Buyer")
    limit, offset = parse_pagination(request.args)
    items = list(DB_INSTANCE.listings.values())
    status_filter = request.args.get("status")
    sale_mode_filter = request.args.get("sale_mode")
    vehicle_filter = request.args.get("vehicle_id")
    seller_filter = request.args.get("seller_id")
    if status_filter:
        items = [x for x in items if x["status"] == status_filter]
    if sale_mode_filter:
        items = [x for x in items if x["sale_mode"] == sale_mode_filter]
    if vehicle_filter:
        items = [x for x in items if x["vehicle_id"] == vehicle_filter]
    if seller_filter:
        items = [x for x in items if x["seller_id"] == seller_filter]
    items = sort_for_list(items)
    page, total = paginate(items, limit, offset)
    return ok_list([_listing_view(x) for x in page], limit, offset, total)


@app.route("/listings/<listing_id>", methods=["GET"])
def get_listing(listing_id):
    require_role("PlatformAdmin", "Seller", "Buyer")
    listing = _require_uuid_lookup(DB_INSTANCE.listings, listing_id, "Listing")
    return ok(_listing_view(listing))


# =============================================================================
# Routes — Bids (AUCTION)
# =============================================================================

@app.route("/listings/<listing_id>/bids", methods=["POST"])
def place_bid(listing_id):
    require_role("Buyer")
    listing = _require_uuid_lookup(DB_INSTANCE.listings, listing_id, "Listing")
    if listing["sale_mode"] != "AUCTION":
        raise err("ERR_INVALID_STATE", "Listing is not an AUCTION")
    if listing["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Listing must be ACTIVE")
    body = get_body()
    try:
        amount = int(body.get("amount_cents"))
    except (TypeError, ValueError):
        raise err("ERR_INVALID_STATE", "amount_cents required")

    # Determine current_max
    current_max = None
    if listing.get("active_bid_id"):
        curr = DB_INSTANCE.bids.get(listing["active_bid_id"])
        if curr and curr["status"] == "LIVE":
            current_max = int(curr["amount_cents"])
    if current_max is None:
        current_max = int(listing["ask_price_cents"])
    increment = calc.bid_increment_for(current_max)
    required_min = current_max + increment
    if amount < required_min:
        raise err("ERR_BID_TOO_LOW",
                  f"Bid {amount} below required minimum {required_min}")

    deposit = calc.ceil_int(amount * 0.10)
    # Deposit limit (priority 16) — release of prior LIVE bid for this buyer should be netted.
    # But the prior LIVE for this buyer on this same listing is the active bid only if buyer was leading.
    # PRD says deposit is acquired on placement; the previous LIVE bid (whoever owns it) is released.
    # We'll approximate the limit using current held + new deposit minus this buyer's own LIVE bid for this listing (if any).
    buyer = DB_INSTANCE.buyers.get(g.user_id)
    if not buyer:
        raise err("ERR_NOT_FOUND", "Buyer not found")
    held = buyer.get("deposit_held_cents", 0)
    # If this buyer currently owns the active LIVE bid, that deposit would be released by their new placement.
    additional = deposit
    if listing.get("active_bid_id"):
        prev = DB_INSTANCE.bids.get(listing["active_bid_id"])
        if prev and prev["status"] == "LIVE" and prev["buyer_id"] == g.user_id:
            additional = deposit - int(prev["deposit_cents"])
    if held + additional > calc.BUYER_DEPOSIT_LIMIT_CENTS:
        raise err("ERR_DEPOSIT_LIMIT_EXCEEDED",
                  "Buyer deposit limit exceeded")

    # Demote prior LIVE bid (whoever's), release deposit
    prev_id = listing.get("active_bid_id")
    affected_buyers = set()
    if prev_id:
        prev = DB_INSTANCE.bids.get(prev_id)
        if prev and prev["status"] == "LIVE":
            svc.transition_bid(prev, "OUTBID")
            affected_buyers.add(prev["buyer_id"])

    bid_id = new_uuid()
    bid = {
        "id": bid_id,
        "listing_id": listing_id,
        "buyer_id": g.user_id,
        "amount_cents": amount,
        "deposit_cents": deposit,
        "status": "LIVE",
        "placed_at": iso(now()),
        "created_at": iso(now()),
    }
    DB_INSTANCE.bids[bid_id] = bid
    listing["active_bid_id"] = bid_id
    bump(listing)
    audit.log("Bid", bid_id, "STATE_TRANSITION", from_value=None, to_value="LIVE")

    affected_buyers.add(g.user_id)
    for buy in affected_buyers:
        svc.recompute_deposit(buy)

    return ok(_bid_view(bid), status=201)


@app.route("/listings/<listing_id>/close-auction", methods=["POST"])
def close_auction(listing_id):
    require_role("PlatformAdmin")
    listing = _require_uuid_lookup(DB_INSTANCE.listings, listing_id, "Listing")
    if listing["sale_mode"] != "AUCTION":
        raise err("ERR_INVALID_STATE", "Listing is not an AUCTION")
    if listing["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Listing must be ACTIVE")

    live_bids = [b for b in DB_INSTANCE.bids.values()
                 if b["listing_id"] == listing["id"] and b["status"] == "LIVE"]
    affected_buyers = set()
    if not live_bids:
        # No live bids — listing stays ACTIVE; nothing to do.
        return ok(_listing_view(listing))

    # Highest bid
    highest = max(live_bids, key=lambda b: int(b["amount_cents"]))
    reserve = listing.get("reserve_price_cents")
    meets_reserve = (reserve is None) or (int(highest["amount_cents"]) >= int(reserve))

    if not meets_reserve:
        # Move all LIVE → LOST and release deposits; listing stays ACTIVE
        for b in live_bids:
            svc.transition_bid(b, "LOST")
            affected_buyers.add(b["buyer_id"])
        listing["active_bid_id"] = None
        bump(listing)
        for buy in affected_buyers:
            svc.recompute_deposit(buy)
        return ok(_listing_view(listing))

    # Highest meets reserve — winner WON; others LOST
    for b in live_bids:
        if b["id"] == highest["id"]:
            svc.transition_bid(b, "WON")
        else:
            svc.transition_bid(b, "LOST")
        affected_buyers.add(b["buyer_id"])
    listing["active_bid_id"] = highest["id"]
    svc.transition_listing(listing, "RESERVED")

    # Create PurchaseOrder PENDING_PAYMENT
    order_id = new_uuid()
    order = {
        "id": order_id,
        "listing_id": listing["id"],
        "vehicle_id": listing["vehicle_id"],
        "seller_id": listing["seller_id"],
        "buyer_id": highest["buyer_id"],
        "agreed_price_cents": int(highest["amount_cents"]),
        "payment_method": "FULL_PAYMENT",
        "loan_id": None,
        "down_payment_cents": int(highest["amount_cents"]),
        "status": "PENDING_PAYMENT",
        "paid_at": None,
    }
    stamp_new_record(order)
    DB_INSTANCE.purchase_orders[order_id] = order
    audit.log("PurchaseOrder", order_id, "STATE_TRANSITION",
              from_value=None, to_value="PENDING_PAYMENT")

    for buy in affected_buyers:
        svc.recompute_deposit(buy)

    return ok(_listing_view(listing))


@app.route("/bids/<bid_id>/cancel", methods=["POST"])
def cancel_bid(bid_id):
    require_role("Buyer")
    bid = _require_uuid_lookup(DB_INSTANCE.bids, bid_id, "Bid")
    body = get_body()
    if bid["buyer_id"] != g.user_id:
        raise err("ERR_NOT_OWNER", "Cannot cancel another buyer's bid")
    if bid["status"] != "LIVE":
        raise err("ERR_INVALID_STATE", "Bid must be LIVE")
    listing = DB_INSTANCE.listings.get(bid["listing_id"])
    if not listing or listing["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Listing must be ACTIVE")

    svc.transition_bid(bid, "CANCELLED")
    if listing.get("active_bid_id") == bid_id:
        listing["active_bid_id"] = None
        bump(listing)
    svc.recompute_deposit(g.user_id)
    return ok(_bid_view(bid))


@app.route("/listings/<listing_id>/bids", methods=["GET"])
def list_bids(listing_id):
    require_role("PlatformAdmin", "Seller", "Buyer")
    _require_uuid_lookup(DB_INSTANCE.listings, listing_id, "Listing")
    limit, offset = parse_pagination(request.args)
    status_filter = request.args.get("status")
    items = [b for b in DB_INSTANCE.bids.values() if b["listing_id"] == listing_id]
    if status_filter:
        items = [b for b in items if b["status"] == status_filter]
    items = sort_for_list(items)
    page, total = paginate(items, limit, offset)
    return ok_list([_bid_view(b) for b in page], limit, offset, total)


# =============================================================================
# Routes — Reservations (FIXED_PRICE)
# =============================================================================

@app.route("/listings/<listing_id>/reservations", methods=["POST"])
def create_reservation(listing_id):
    require_role("Buyer")
    listing = _require_uuid_lookup(DB_INSTANCE.listings, listing_id, "Listing")
    if listing["sale_mode"] != "FIXED_PRICE":
        raise err("ERR_LISTING_NOT_RESERVABLE", "Listing is not FIXED_PRICE")
    if listing["status"] not in ("ACTIVE", "RESERVED"):
        raise err("ERR_LISTING_NOT_RESERVABLE", "Listing not reservable in current state")

    deposit = calc.ceil_int(int(listing["ask_price_cents"]) * 0.05)

    # Determine queue position based on existing non-terminal reservations
    non_terminal = [r for r in DB_INSTANCE.reservations.values()
                    if r["listing_id"] == listing["id"]
                    and r["status"] in ("QUEUED", "HOLDING")]
    queue_position = len(non_terminal) + 1

    # Deposit limit check only for HOLDING (position 1) — the only state that holds money.
    if queue_position == 1:
        svc.check_deposit_limit_for_increase(g.user_id, deposit)

    rid = new_uuid()
    reservation = {
        "id": rid,
        "listing_id": listing["id"],
        "buyer_id": g.user_id,
        "queue_position": queue_position,
        "deposit_cents": deposit,
        "status": "QUEUED",
        "hold_expires_at": None,
        "created_at": iso(now()),
    }
    DB_INSTANCE.reservations[rid] = reservation
    audit.log("Reservation", rid, "STATE_TRANSITION", from_value=None, to_value="QUEUED")

    if queue_position == 1:
        # Promote to HOLDING immediately
        from datetime import timedelta
        svc.transition_reservation(reservation, "HOLDING")
        reservation["hold_expires_at"] = iso(now() + timedelta(hours=24))
        # Listing ACTIVE → RESERVED
        if listing["status"] == "ACTIVE":
            svc.transition_listing(listing, "RESERVED")
        listing["reservation_buyer_id"] = g.user_id
        bump(listing)
        svc.recompute_deposit(g.user_id)

    return ok(_reservation_view(reservation), status=201)


@app.route("/reservations/<reservation_id>/cancel", methods=["POST"])
def cancel_reservation(reservation_id):
    require_role("Buyer")
    reservation = _require_uuid_lookup(DB_INSTANCE.reservations, reservation_id, "Reservation")
    body = get_body()
    if reservation["buyer_id"] != g.user_id:
        raise err("ERR_NOT_OWNER", "Cannot cancel another buyer's reservation")
    if reservation["status"] not in ("QUEUED", "HOLDING"):
        raise err("ERR_INVALID_STATE", "Reservation cannot be cancelled in current state")

    listing = DB_INSTANCE.listings.get(reservation["listing_id"])
    was_holding = reservation["status"] == "HOLDING"
    svc.transition_reservation(reservation, "CANCELLED")

    if was_holding:
        svc.recompute_deposit(g.user_id)
        # Promote next or restore listing to ACTIVE
        if listing:
            listing["reservation_buyer_id"] = None
            bump(listing)
            promoted = svc.promote_next_reservation(listing)
            if promoted is None and listing["status"] == "RESERVED":
                svc.transition_listing(listing, "ACTIVE")
    else:
        # Was QUEUED — no deposit movement; rerank not required since we use FIFO ordering.
        pass

    return ok(_reservation_view(reservation))


@app.route("/listings/<listing_id>/reservations", methods=["GET"])
def list_reservations(listing_id):
    require_role("PlatformAdmin", "Seller", "Buyer")
    _require_uuid_lookup(DB_INSTANCE.listings, listing_id, "Listing")
    limit, offset = parse_pagination(request.args)
    status_filter = request.args.get("status")
    items = [r for r in DB_INSTANCE.reservations.values() if r["listing_id"] == listing_id]
    if status_filter:
        items = [r for r in items if r["status"] == status_filter]
    items = sort_for_list(items)
    page, total = paginate(items, limit, offset)
    return ok_list([_reservation_view(r) for r in page], limit, offset, total)


# =============================================================================
# Routes — Purchase Orders
# =============================================================================

@app.route("/purchase-orders", methods=["POST"])
def create_purchase_order():
    require_role("Buyer")
    body = get_body()
    listing_id = body.get("listing_id")
    payment_method = body.get("payment_method", "FULL_PAYMENT")
    if payment_method not in ("FULL_PAYMENT", "LOAN"):
        raise err("ERR_INVALID_STATE", "payment_method must be FULL_PAYMENT or LOAN")
    listing = _require_uuid_lookup(DB_INSTANCE.listings, listing_id, "Listing")

    # Find buyer's eligibility: WON bid (auction) or HOLDING reservation
    agreed_price = None
    if listing["sale_mode"] == "AUCTION":
        won_bid = None
        for b in DB_INSTANCE.bids.values():
            if b["listing_id"] == listing["id"] and b["status"] == "WON" and b["buyer_id"] == g.user_id:
                won_bid = b
                break
        if not won_bid:
            raise err("ERR_INVALID_STATE", "No winning bid for this buyer on this listing")
        agreed_price = int(won_bid["amount_cents"])
    else:  # FIXED_PRICE
        holding_res = None
        for r in DB_INSTANCE.reservations.values():
            if r["listing_id"] == listing["id"] and r["status"] == "HOLDING" and r["buyer_id"] == g.user_id:
                holding_res = r
                break
        if not holding_res:
            raise err("ERR_INVALID_STATE", "No holding reservation for this buyer")
        agreed_price = int(listing["ask_price_cents"])

    # Idempotency check: only one active order per listing+buyer
    for o in DB_INSTANCE.purchase_orders.values():
        if (o["listing_id"] == listing["id"]
                and o["buyer_id"] == g.user_id
                and o["status"] in ("PENDING_PAYMENT", "PAID", "AWAITING_TRANSFER", "COMPLETED")):
            raise err("ERR_INVALID_STATE", "An active purchase order already exists")

    # Create a Warranty in PENDING_ACTIVATION (package_code may come from body)
    package_code = body.get("package_code", "BASIC")
    if package_code not in calc.WARRANTY_PACKAGES:
        package_code = "BASIC"

    oid = new_uuid()
    order = {
        "id": oid,
        "listing_id": listing["id"],
        "vehicle_id": listing["vehicle_id"],
        "seller_id": listing["seller_id"],
        "buyer_id": g.user_id,
        "agreed_price_cents": agreed_price,
        "payment_method": payment_method,
        "loan_id": None,
        "down_payment_cents": agreed_price if payment_method == "FULL_PAYMENT" else 0,
        "status": "PENDING_PAYMENT",
        "paid_at": None,
    }
    stamp_new_record(order)
    DB_INSTANCE.purchase_orders[oid] = order
    audit.log("PurchaseOrder", oid, "STATE_TRANSITION", from_value=None, to_value="PENDING_PAYMENT")

    # Auto-create a Warranty per the package code (PRD §3.8: every PO gives rise to a Warranty).
    wid = new_uuid()
    warranty = {
        "id": wid,
        "purchase_order_id": oid,
        "package_code": package_code,
        "coverage_scope": list(calc.WARRANTY_PACKAGES[package_code]["scope"]),
        "effective_at": None,
        "expires_at": None,
        "status": "PENDING_ACTIVATION",
        "claims_count": 0,
        "total_claim_payout_cents": 0,
    }
    stamp_new_record(warranty)
    DB_INSTANCE.warranties[wid] = warranty
    audit.log("Warranty", wid, "STATE_TRANSITION",
              from_value=None, to_value="PENDING_ACTIVATION")

    return ok(_po_view(order), status=201)


@app.route("/purchase-orders/<order_id>", methods=["GET"])
def get_purchase_order(order_id):
    require_role("PlatformAdmin", "Seller", "Buyer")
    o = _require_uuid_lookup(DB_INSTANCE.purchase_orders, order_id, "PurchaseOrder")
    return ok(_po_view(o))


@app.route("/purchase-orders/<order_id>/cancel", methods=["POST"])
def cancel_purchase_order(order_id):
    require_role("Buyer")
    order = _require_uuid_lookup(DB_INSTANCE.purchase_orders, order_id, "PurchaseOrder")
    body = get_body()
    if order["buyer_id"] != g.user_id:
        raise err("ERR_NOT_OWNER", "Cannot cancel another buyer's order")
    check_version(order["version"], body)
    if order["status"] != "PENDING_PAYMENT":
        raise err("ERR_INVALID_STATE", "Order must be PENDING_PAYMENT")

    old = order["status"]
    order["status"] = "CANCELLED"
    bump(order)
    audit.log("PurchaseOrder", order["id"], "STATE_TRANSITION",
              from_value=old, to_value="CANCELLED")

    svc.perform_pending_cancel_cascade(order)
    return ok(_po_view(order))


# =============================================================================
# Routes — Loans
# =============================================================================

@app.route("/purchase-orders/<order_id>/loans", methods=["POST"])
def create_loan(order_id):
    require_role("Buyer")
    order = _require_uuid_lookup(DB_INSTANCE.purchase_orders, order_id, "PurchaseOrder")
    if order["buyer_id"] != g.user_id:
        raise err("ERR_NOT_OWNER", "Cannot create loan for another buyer's order")
    if order["status"] != "PENDING_PAYMENT":
        raise err("ERR_INVALID_STATE", "Order must be PENDING_PAYMENT")
    if order["payment_method"] != "LOAN":
        raise err("ERR_INVALID_STATE", "Order is not financed (payment_method != LOAN)")
    body = get_body()
    lender_code = body.get("lender_code")
    if lender_code not in calc.LENDER_RULES:
        raise err("ERR_LOAN_PARAMS_INVALID", "Unsupported lender_code")
    try:
        requested_principal = int(body.get("requested_principal_cents"))
        down_payment_ratio_bp = int(body.get("down_payment_ratio_bp"))
        # term_months: PRD §3.6 lists six exact integer values; reject any
        # non-integer (e.g. 24.5) before coercion so a fractional input cannot
        # quietly truncate to a valid value.
        raw_term = body.get("term_months")
        if isinstance(raw_term, bool) or not isinstance(raw_term, int):
            raise ValueError("term_months must be an integer")
        term_months = int(raw_term)
    except (TypeError, ValueError):
        raise err("ERR_LOAN_PARAMS_INVALID", "Loan params malformed")

    # Down-payment ratio (priority 14)
    lender_min_down = calc.LENDER_RULES[lender_code]["min_down_bp"]
    if down_payment_ratio_bp < lender_min_down:
        raise err("ERR_DOWN_PAYMENT_INSUFFICIENT",
                  f"Down-payment ratio below lender minimum {lender_min_down}")

    # Term + principal validity (priority 15)
    if term_months not in (12, 24, 36, 48, 60, 72):
        raise err("ERR_LOAN_PARAMS_INVALID", "term_months must be in {12,24,36,48,60,72}")
    if requested_principal <= 0:
        raise err("ERR_LOAN_PARAMS_INVALID", "requested_principal_cents must be > 0")
    agreed_price = int(order["agreed_price_cents"])
    min_down = calc.ceil_int(agreed_price * lender_min_down / 10000.0)
    max_principal_for_validation = agreed_price - min_down
    if requested_principal > max_principal_for_validation:
        raise err("ERR_LOAN_PARAMS_INVALID",
                  "Requested principal exceeds price minus lender minimum down-payment")

    # Only one loan per PO
    if order.get("loan_id") and order["loan_id"] in DB_INSTANCE.loans:
        existing = DB_INSTANCE.loans[order["loan_id"]]
        if existing["status"] not in ("CANCELLED", "REJECTED"):
            raise err("ERR_INVALID_STATE", "Loan already exists for this order")

    lid = new_uuid()
    loan = {
        "id": lid,
        "purchase_order_id": order_id,
        "buyer_id": g.user_id,
        "lender_code": lender_code,
        "requested_principal_cents": requested_principal,
        "approved_principal_cents": None,
        "down_payment_ratio_bp": down_payment_ratio_bp,
        "term_months": term_months,
        "monthly_payment_cents": None,
        "total_interest_cents": None,
        "credit_score": None,
        "status": "APPLIED",
        "disbursed_at": None,
    }
    stamp_new_record(loan)
    DB_INSTANCE.loans[lid] = loan
    order["loan_id"] = lid
    bump(order)
    audit.log("Loan", lid, "STATE_TRANSITION", from_value=None, to_value="APPLIED")
    return ok(_loan_view(loan), status=201)


@app.route("/loans/<loan_id>/run-credit-check", methods=["POST"])
def run_credit_check(loan_id):
    require_role("PlatformAdmin")
    loan = _require_uuid_lookup(DB_INSTANCE.loans, loan_id, "Loan")
    body = get_body()
    check_version(loan["version"], body)
    if loan["status"] != "APPLIED":
        raise err("ERR_INVALID_STATE", "Loan must be APPLIED")
    # Re-verify down-payment ratio at this step too (priority 14)
    lender_min_down = calc.LENDER_RULES[loan["lender_code"]]["min_down_bp"]
    if loan["down_payment_ratio_bp"] < lender_min_down:
        raise err("ERR_DOWN_PAYMENT_INSUFFICIENT", "Down-payment ratio below lender minimum")
    old = loan["status"]
    loan["status"] = "CREDIT_CHECKING"
    bump(loan)
    audit.log("Loan", loan["id"], "STATE_TRANSITION",
              from_value=old, to_value="CREDIT_CHECKING")
    return ok(_loan_view(loan))


@app.route("/loans/<loan_id>/cancel", methods=["POST"])
def cancel_loan(loan_id):
    require_role("Buyer")
    loan = _require_uuid_lookup(DB_INSTANCE.loans, loan_id, "Loan")
    body = get_body()
    if loan["buyer_id"] != g.user_id:
        raise err("ERR_NOT_OWNER", "Cannot cancel another buyer's loan")
    check_version(loan["version"], body)
    if loan["status"] not in ("APPLIED", "APPROVED"):
        raise err("ERR_INVALID_STATE", "Loan must be APPLIED or APPROVED")
    old = loan["status"]
    loan["status"] = "CANCELLED"
    bump(loan)
    audit.log("Loan", loan["id"], "STATE_TRANSITION",
              from_value=old, to_value="CANCELLED")
    return ok(_loan_view(loan))


@app.route("/loans/<loan_id>", methods=["GET"])
def get_loan(loan_id):
    require_role("PlatformAdmin", "Buyer")
    loan = _require_uuid_lookup(DB_INSTANCE.loans, loan_id, "Loan")
    if g.role == "Buyer" and loan["buyer_id"] != g.user_id:
        raise err("ERR_NOT_OWNER", "Cannot read another buyer's loan")
    return ok(_loan_view(loan))


# =============================================================================
# Routes — Transfers
# =============================================================================

@app.route("/transfers/<transfer_id>", methods=["GET"])
def get_transfer(transfer_id):
    require_role("PlatformAdmin", "Seller", "Buyer")
    t = _require_uuid_lookup(DB_INSTANCE.transfers, transfer_id, "TransferCase")
    return ok(_transfer_view(t))


@app.route("/transfers/<transfer_id>/documents", methods=["PATCH"])
def upload_document(transfer_id):
    require_role("Buyer", "Seller")
    t = _require_uuid_lookup(DB_INSTANCE.transfers, transfer_id, "TransferCase")
    order = DB_INSTANCE.purchase_orders.get(t["purchase_order_id"])
    if not order:
        raise err("ERR_NOT_FOUND", "PurchaseOrder not found")
    if g.role == "Buyer" and order["buyer_id"] != g.user_id:
        raise err("ERR_NOT_OWNER", "Cannot modify another buyer's transfer")
    if g.role == "Seller" and order["seller_id"] != g.user_id:
        raise err("ERR_NOT_OWNER", "Cannot modify another seller's transfer")
    body = get_body()
    check_version(t["version"], body)
    if t["status"] != "DOCS_PENDING":
        raise err("ERR_INVALID_STATE", "TransferCase must be DOCS_PENDING")
    doc_type = body.get("doc_type")
    doc_url = body.get("doc_url")
    if not doc_type or not doc_url:
        raise err("ERR_TRANSFER_DOCS_INCOMPLETE", "doc_type and doc_url required")
    found = False
    for item in t["required_documents"]:
        if item["doc_type"] == doc_type:
            item["submitted"] = True
            item["doc_url"] = doc_url
            found = True
            break
    if not found:
        raise err("ERR_TRANSFER_DOCS_INCOMPLETE", f"Unknown doc_type {doc_type}")
    bump(t)
    return ok(_transfer_view(t))


@app.route("/transfers/<transfer_id>/book-appointment", methods=["POST"])
def book_appointment(transfer_id):
    require_role("Buyer")
    t = _require_uuid_lookup(DB_INSTANCE.transfers, transfer_id, "TransferCase")
    order = DB_INSTANCE.purchase_orders.get(t["purchase_order_id"])
    if not order:
        raise err("ERR_NOT_FOUND", "PurchaseOrder not found")
    if order["buyer_id"] != g.user_id:
        raise err("ERR_NOT_OWNER", "Cannot book another buyer's transfer")
    body = get_body()
    check_version(t["version"], body)
    if t["status"] != "DOCS_PENDING":
        raise err("ERR_INVALID_STATE", "TransferCase must be DOCS_PENDING")

    appointment_at_str = body.get("appointment_at")
    dmv_office_code = body.get("dmv_office_code")
    license_plate_action = body.get("license_plate_action") or "REASSIGN"
    new_plate_number = body.get("new_plate_number")
    if license_plate_action not in ("KEEP_OLD", "REASSIGN", "NEW_NUMBER"):
        raise err("ERR_TRANSFER_DOCS_INCOMPLETE", "license_plate_action invalid")
    if not dmv_office_code:
        raise err("ERR_TRANSFER_DOCS_INCOMPLETE", "dmv_office_code required")

    # Required documents check
    for item in t["required_documents"]:
        if not item["submitted"]:
            raise err("ERR_TRANSFER_DOCS_INCOMPLETE",
                      f"Document {item['doc_type']} not submitted")

    # Plate rules
    if license_plate_action == "NEW_NUMBER":
        if not new_plate_number or not isinstance(new_plate_number, str) or not new_plate_number.strip():
            raise err("ERR_TRANSFER_DOCS_INCOMPLETE", "new_plate_number required")
    else:
        if new_plate_number is not None:
            raise err("ERR_TRANSFER_DOCS_INCOMPLETE", "new_plate_number must be null")

    # Appointment window
    if not appointment_at_str:
        raise err("ERR_APPOINTMENT_OUT_OF_WINDOW", "appointment_at required")
    try:
        appt_dt = parse_iso(appointment_at_str)
    except Exception:
        raise err("ERR_APPOINTMENT_OUT_OF_WINDOW", "appointment_at malformed")
    cur = now()
    if appt_dt <= cur:
        raise err("ERR_APPOINTMENT_OUT_OF_WINDOW", "appointment_at must be in the future")
    delta_seconds = (appt_dt - cur).total_seconds()
    if delta_seconds > 60 * 24 * 3600:
        raise err("ERR_APPOINTMENT_OUT_OF_WINDOW",
                  "appointment_at must be within 60 days")

    t["appointment_at"] = iso(appt_dt)
    t["dmv_office_code"] = dmv_office_code
    t["license_plate_action"] = license_plate_action
    t["new_plate_number"] = new_plate_number if license_plate_action == "NEW_NUMBER" else None
    old = t["status"]
    t["status"] = "APPOINTMENT_BOOKED"
    bump(t)
    audit.log("TransferCase", t["id"], "STATE_TRANSITION",
              from_value=old, to_value="APPOINTMENT_BOOKED")
    return ok(_transfer_view(t))


@app.route("/transfers/<transfer_id>/rollback", methods=["POST"])
def rollback_transfer(transfer_id):
    require_role("PlatformAdmin")
    t = _require_uuid_lookup(DB_INSTANCE.transfers, transfer_id, "TransferCase")
    body = get_body()
    check_version(t["version"], body)
    if t["status"] != "FAILED":
        raise err("ERR_INVALID_STATE", "Only FAILED transfers can be rolled back")
    old = t["status"]
    t["status"] = "ROLLED_BACK"
    t["rolled_back_at"] = iso(now())
    bump(t)
    audit.log("TransferCase", t["id"], "STATE_TRANSITION",
              from_value=old, to_value="ROLLED_BACK")

    # PurchaseOrder AWAITING_TRANSFER → REFUNDED
    order = DB_INSTANCE.purchase_orders.get(t["purchase_order_id"])
    if order and order["status"] == "AWAITING_TRANSFER":
        old_o = order["status"]
        order["status"] = "REFUNDED"
        bump(order)
        audit.log("PurchaseOrder", order["id"], "STATE_TRANSITION",
                  from_value=old_o, to_value="REFUNDED")
        svc.perform_refund_cascade(order)
    return ok(_transfer_view(t))


# =============================================================================
# Routes — Warranties / Claims
# =============================================================================

@app.route("/warranties/<warranty_id>", methods=["GET"])
def get_warranty(warranty_id):
    require_role("PlatformAdmin", "Buyer", "Seller")
    w = _require_uuid_lookup(DB_INSTANCE.warranties, warranty_id, "Warranty")
    return ok(_warranty_view(w))


@app.route("/warranties/<warranty_id>/claims", methods=["POST"])
def file_warranty_claim(warranty_id):
    require_role("Buyer")
    w = _require_uuid_lookup(DB_INSTANCE.warranties, warranty_id, "Warranty")
    order = DB_INSTANCE.purchase_orders.get(w["purchase_order_id"])
    if not order:
        raise err("ERR_NOT_FOUND", "PurchaseOrder not found")
    if order["buyer_id"] != g.user_id:
        raise err("ERR_NOT_OWNER", "Cannot file claim on another buyer's warranty")
    body = get_body()
    component = body.get("component")
    try:
        claimed_amount = int(body.get("claimed_amount_cents"))
    except (TypeError, ValueError):
        raise err("ERR_INVALID_STATE", "claimed_amount_cents required")
    if claimed_amount <= 0:
        raise err("ERR_INVALID_STATE", "claimed_amount_cents must be > 0")

    # Warranty active + not expired (priority 18)
    if w["status"] != "ACTIVE":
        raise err("ERR_WARRANTY_NOT_ACTIVE", "Warranty not active")
    if w.get("expires_at"):
        if now() >= parse_iso(w["expires_at"]):
            raise err("ERR_WARRANTY_NOT_ACTIVE", "Warranty expired")

    # Component coverage (priority 19)
    if component not in (w.get("coverage_scope") or []):
        raise err("ERR_COMPONENT_NOT_COVERED", f"Component {component} not covered")

    cid = new_uuid()
    claim = {
        "id": cid,
        "warranty_id": warranty_id,
        "component": component,
        "claimed_amount_cents": claimed_amount,
        "approved_amount_cents": None,
        "status": "PENDING",
    }
    stamp_new_record(claim)
    DB_INSTANCE.warranty_claims[cid] = claim
    audit.log("WarrantyClaim", cid, "STATE_TRANSITION", from_value=None, to_value="PENDING")
    return ok(_claim_view(claim), status=201)


@app.route("/warranty-claims/<claim_id>/approve", methods=["POST"])
def approve_claim(claim_id):
    require_role("PlatformAdmin")
    claim = _require_uuid_lookup(DB_INSTANCE.warranty_claims, claim_id, "WarrantyClaim")
    body = get_body()
    check_version(claim["version"], body)
    if claim["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Claim must be PENDING")
    w = DB_INSTANCE.warranties.get(claim["warranty_id"])
    if not w:
        raise err("ERR_NOT_FOUND", "Warranty not found")
    if w["status"] != "ACTIVE":
        raise err("ERR_WARRANTY_NOT_ACTIVE", "Warranty not active at approval")
    if w.get("expires_at") and now() >= parse_iso(w["expires_at"]):
        raise err("ERR_WARRANTY_NOT_ACTIVE", "Warranty expired")

    approved = calc.warranty_claim_payout(
        package_code=w["package_code"],
        claimed_amount_cents=int(claim["claimed_amount_cents"]),
        running_total_payout_cents=int(w.get("total_claim_payout_cents", 0)),
    )
    claim["approved_amount_cents"] = approved
    old = claim["status"]
    claim["status"] = "APPROVED"
    bump(claim)
    audit.log("WarrantyClaim", claim["id"], "STATE_TRANSITION",
              from_value=old, to_value="APPROVED")
    return ok(_claim_view(claim))


@app.route("/warranty-claims/<claim_id>/reject", methods=["POST"])
def reject_claim(claim_id):
    require_role("PlatformAdmin")
    claim = _require_uuid_lookup(DB_INSTANCE.warranty_claims, claim_id, "WarrantyClaim")
    body = get_body()
    check_version(claim["version"], body)
    if claim["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Claim must be PENDING")
    old = claim["status"]
    claim["status"] = "REJECTED"
    bump(claim)
    audit.log("WarrantyClaim", claim["id"], "STATE_TRANSITION",
              from_value=old, to_value="REJECTED")
    return ok(_claim_view(claim))


# =============================================================================
# Routes — Disputes
# =============================================================================

@app.route("/purchase-orders/<order_id>/disputes", methods=["POST"])
def file_dispute(order_id):
    require_role("Buyer", "Seller")
    order = _require_uuid_lookup(DB_INSTANCE.purchase_orders, order_id, "PurchaseOrder")
    if g.role == "Buyer" and order["buyer_id"] != g.user_id:
        raise err("ERR_NOT_OWNER", "Cannot file dispute on another buyer's order")
    if g.role == "Seller" and order["seller_id"] != g.user_id:
        raise err("ERR_NOT_OWNER", "Cannot file dispute on another seller's order")
    if order["status"] not in ("COMPLETED", "AWAITING_TRANSFER"):
        raise err("ERR_DISPUTE_NOT_ELIGIBLE",
                  "PurchaseOrder must be COMPLETED or AWAITING_TRANSFER")
    body = get_body()
    complainant_role = body.get("complainant_role")
    if complainant_role not in ("BUYER", "SELLER"):
        raise err("ERR_INVALID_STATE", "complainant_role must be BUYER or SELLER")
    complaint_text = body.get("complaint_text") or ""
    evidence_items = body.get("evidence_items") or []
    if not isinstance(evidence_items, list):
        raise err("ERR_INVALID_STATE", "evidence_items must be a list")

    did = new_uuid()
    dispute = {
        "id": did,
        "purchase_order_id": order_id,
        "complainant_role": complainant_role,
        "complaint_text": complaint_text,
        "evidence_items": evidence_items,
        "stage": "SUBMITTED",
        "round_count": 0,
        "third_party_report_url": None,
        "resolution": None,
        "refund_amount_cents": None,
    }
    stamp_new_record(dispute)
    DB_INSTANCE.disputes[did] = dispute
    audit.log("DisputeCase", did, "STATE_TRANSITION", from_value=None, to_value="SUBMITTED")
    return ok(_dispute_view(dispute), status=201)


@app.route("/disputes/<dispute_id>/start-review", methods=["POST"])
def start_review(dispute_id):
    require_role("PlatformAdmin")
    d = _require_uuid_lookup(DB_INSTANCE.disputes, dispute_id, "DisputeCase")
    body = get_body()
    check_version(d["version"], body)
    if d["stage"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Dispute must be SUBMITTED")
    # round_count cap before incrementing — moving to EVIDENCE_REVIEW increments it
    if d["round_count"] >= 3:
        raise err("ERR_DISPUTE_ROUNDS_EXHAUSTED", "Max mediation rounds reached")
    d["round_count"] += 1
    old = d["stage"]
    d["stage"] = "EVIDENCE_REVIEW"
    bump(d)
    audit.log("DisputeCase", d["id"], "STATE_TRANSITION",
              from_value=old, to_value="EVIDENCE_REVIEW")
    return ok(_dispute_view(d))


@app.route("/disputes/<dispute_id>/request-more-evidence", methods=["POST"])
def request_more_evidence(dispute_id):
    require_role("PlatformAdmin")
    d = _require_uuid_lookup(DB_INSTANCE.disputes, dispute_id, "DisputeCase")
    body = get_body()
    check_version(d["version"], body)
    if d["stage"] != "EVIDENCE_REVIEW":
        raise err("ERR_INVALID_STATE", "Dispute must be EVIDENCE_REVIEW")
    # The next start-review would re-bump; cap at 3.
    if d["round_count"] >= 3:
        raise err("ERR_DISPUTE_ROUNDS_EXHAUSTED", "Max mediation rounds reached")
    old = d["stage"]
    d["stage"] = "SUBMITTED"
    bump(d)
    audit.log("DisputeCase", d["id"], "STATE_TRANSITION",
              from_value=old, to_value="SUBMITTED")
    return ok(_dispute_view(d))


@app.route("/disputes/<dispute_id>/request-third-party", methods=["POST"])
def request_third_party(dispute_id):
    require_role("PlatformAdmin")
    d = _require_uuid_lookup(DB_INSTANCE.disputes, dispute_id, "DisputeCase")
    body = get_body()
    check_version(d["version"], body)
    if d["stage"] != "EVIDENCE_REVIEW":
        raise err("ERR_INVALID_STATE", "Dispute must be EVIDENCE_REVIEW")
    old = d["stage"]
    d["stage"] = "THIRD_PARTY_INSPECTION"
    bump(d)
    audit.log("DisputeCase", d["id"], "STATE_TRANSITION",
              from_value=old, to_value="THIRD_PARTY_INSPECTION")
    return ok(_dispute_view(d))


@app.route("/disputes/<dispute_id>/submit-third-party-report", methods=["POST"])
def submit_third_party_report(dispute_id):
    require_role("PlatformAdmin")
    d = _require_uuid_lookup(DB_INSTANCE.disputes, dispute_id, "DisputeCase")
    body = get_body()
    check_version(d["version"], body)
    if d["stage"] != "THIRD_PARTY_INSPECTION":
        raise err("ERR_INVALID_STATE", "Dispute must be THIRD_PARTY_INSPECTION")
    url = body.get("third_party_report_url")
    if not url or not isinstance(url, str) or not url.strip():
        raise err("ERR_INVALID_STATE", "third_party_report_url required")
    d["third_party_report_url"] = url
    old = d["stage"]
    d["stage"] = "RESOLUTION_PROPOSED"
    bump(d)
    audit.log("DisputeCase", d["id"], "STATE_TRANSITION",
              from_value=old, to_value="RESOLUTION_PROPOSED")
    return ok(_dispute_view(d))


@app.route("/disputes/<dispute_id>/propose-resolution", methods=["POST"])
def propose_resolution(dispute_id):
    require_role("PlatformAdmin")
    d = _require_uuid_lookup(DB_INSTANCE.disputes, dispute_id, "DisputeCase")
    body = get_body()
    check_version(d["version"], body)
    if d["stage"] != "EVIDENCE_REVIEW":
        raise err("ERR_INVALID_STATE", "Dispute must be EVIDENCE_REVIEW")
    resolution = body.get("resolution")
    if resolution not in ("REFUND_FULL", "REFUND_PARTIAL", "COMPENSATE_SELLER", "NO_ACTION"):
        raise err("ERR_INVALID_STATE", "Invalid resolution")
    d["resolution"] = resolution
    old = d["stage"]
    d["stage"] = "RESOLUTION_PROPOSED"
    bump(d)
    audit.log("DisputeCase", d["id"], "STATE_TRANSITION",
              from_value=old, to_value="RESOLUTION_PROPOSED")
    return ok(_dispute_view(d))


def _latest_assessment_for_vehicle(vehicle_id):
    relevant = [a for a in DB_INSTANCE.assessments.values()
                if a["vehicle_id"] == vehicle_id and a["status"] in ("FINALIZED", "SUPERSEDED")]
    if not relevant:
        return None
    return max(relevant, key=lambda a: (a.get("updated_at", ""), a["id"]))


@app.route("/disputes/<dispute_id>/execute", methods=["POST"])
def execute_dispute(dispute_id):
    require_role("PlatformAdmin")
    d = _require_uuid_lookup(DB_INSTANCE.disputes, dispute_id, "DisputeCase")
    body = get_body()
    check_version(d["version"], body)
    if d["stage"] != "RESOLUTION_PROPOSED":
        raise err("ERR_INVALID_STATE", "Dispute must be RESOLUTION_PROPOSED")
    # PRD §3.9: "A dispute that the admin starts but does not yet have an
    # executable resolution must have its resolution set before the execute
    # step." For the third-party path, the dispute reaches RESOLUTION_PROPOSED
    # via submit-third-party-report with no resolution yet recorded; the
    # admin sets it in the execute body.
    body_resolution = body.get("resolution")
    if body_resolution is not None:
        if body_resolution not in ("REFUND_FULL", "REFUND_PARTIAL", "COMPENSATE_SELLER", "NO_ACTION"):
            raise err("ERR_INVALID_STATE", "Invalid resolution")
        d["resolution"] = body_resolution
    if not d.get("resolution"):
        raise err("ERR_INVALID_STATE", "Resolution must be set before execute")
    order = DB_INSTANCE.purchase_orders.get(d["purchase_order_id"])
    if not order:
        raise err("ERR_NOT_FOUND", "PurchaseOrder not found")

    # mileage_discrepancy_at_sale comes from the latest assessment
    asr = _latest_assessment_for_vehicle(order["vehicle_id"])
    discrepancy_flag = bool(asr.get("mileage_discrepancy_flag")) if asr else False
    had_3p = bool(d.get("third_party_report_url"))

    refund = calc.dispute_compensation(
        resolution=d["resolution"],
        agreed_price_cents=int(order["agreed_price_cents"]),
        had_third_party_report=had_3p,
        mileage_discrepancy_at_sale=discrepancy_flag,
    )
    d["refund_amount_cents"] = refund
    old = d["stage"]
    d["stage"] = "CLOSED"
    bump(d)
    audit.log("DisputeCase", d["id"], "STATE_TRANSITION",
              from_value=old, to_value="CLOSED")

    # Cascade depending on resolution
    if d["resolution"] == "REFUND_FULL":
        # PurchaseOrder → REFUNDED + full cascade
        if order["status"] in ("AWAITING_TRANSFER", "COMPLETED"):
            old_o = order["status"]
            order["status"] = "REFUNDED"
            bump(order)
            audit.log("PurchaseOrder", order["id"], "STATE_TRANSITION",
                      from_value=old_o, to_value="REFUNDED")
            svc.perform_refund_cascade(order)
            # Make sure the warranty is voided even if perform_refund_cascade only voids ACTIVE
            w = svc.find_warranty_for_order(order["id"])
            if w and w["status"] == "ACTIVE":
                # already handled by perform_refund_cascade
                pass

    return ok(_dispute_view(d))


# =============================================================================
# Routes — External events / clock / audit
# =============================================================================

@app.route("/_events/emit", methods=["POST"])
def emit_event():
    require_role("PlatformAdmin")
    body = get_body()
    source = body.get("source")
    event_type = body.get("event_type")
    idempotency_key = body.get("idempotency_key")
    payload = body.get("payload") or {}
    if source not in ("DMV", "BANK", "INSURANCE", "PAYMENT"):
        raise err("ERR_INVALID_STATE", "Invalid source")
    if not event_type or not idempotency_key:
        raise err("ERR_INVALID_STATE", "event_type and idempotency_key required")

    # Idempotency replay
    if idempotency_key in DB_INSTANCE.events_by_key:
        original = DB_INSTANCE.events_by_key[idempotency_key]
        return replay(_event_view(original))

    eid = new_uuid()
    event = {
        "id": eid,
        "source": source,
        "event_type": event_type,
        "idempotency_key": idempotency_key,
        "payload": payload,
        "processed": False,
        "created_at": iso(now()),
    }
    DB_INSTANCE.events[eid] = event
    DB_INSTANCE.events_by_key[idempotency_key] = event

    # Route to handler
    try:
        _process_event(event)
    finally:
        event["processed"] = True

    audit.log("ExternalEvent", eid, "EXTERNAL_SYNC",
              from_value=None, to_value=event_type)
    return ok(_event_view(event), status=201)


def _process_event(event):
    et = event["event_type"]
    payload = event["payload"] or {}
    if et == "payment_received":
        order_id = payload.get("purchase_order_id")
        if not order_id:
            return
        order = DB_INSTANCE.purchase_orders.get(order_id)
        if not order or order["status"] != "PENDING_PAYMENT":
            return
        if order["payment_method"] == "LOAN":
            ln = svc.find_loan_for_order(order["id"])
            if not ln or ln["status"] != "DISBURSED":
                return
        old = order["status"]
        order["status"] = "PAID"
        order["paid_at"] = iso(now())
        bump(order)
        audit.log("PurchaseOrder", order["id"], "STATE_TRANSITION",
                  from_value=old, to_value="PAID",
                  actor_role="system", actor_id="system")
        svc.perform_paid_cascade(order, paid_at_iso=order["paid_at"])
    elif et == "transfer_succeeded":
        transfer_id = payload.get("transfer_case_id") or payload.get("transfer_id")
        t = DB_INSTANCE.transfers.get(transfer_id) if transfer_id else None
        if not t or t["status"] != "IN_PROGRESS":
            return
        old = t["status"]
        t["status"] = "SUCCEEDED"
        bump(t)
        audit.log("TransferCase", t["id"], "STATE_TRANSITION",
                  from_value=old, to_value="SUCCEEDED",
                  actor_role="system", actor_id="system")
        svc.perform_transfer_succeeded_cascade(t)
    elif et == "transfer_failed":
        transfer_id = payload.get("transfer_case_id") or payload.get("transfer_id")
        t = DB_INSTANCE.transfers.get(transfer_id) if transfer_id else None
        if not t or t["status"] != "IN_PROGRESS":
            return
        old = t["status"]
        t["status"] = "FAILED"
        t["failure_reason"] = payload.get("reason")
        bump(t)
        audit.log("TransferCase", t["id"], "STATE_TRANSITION",
                  from_value=old, to_value="FAILED",
                  actor_role="system", actor_id="system")
    elif et == "credit_check_returned":
        loan_id = payload.get("loan_id")
        ln = DB_INSTANCE.loans.get(loan_id) if loan_id else None
        if not ln or ln["status"] != "CREDIT_CHECKING":
            return
        score = payload.get("credit_score")
        try:
            score = int(score)
        except (TypeError, ValueError):
            return
        ln["credit_score"] = score
        order = DB_INSTANCE.purchase_orders.get(ln["purchase_order_id"])
        if not order:
            return
        lender_min_credit = calc.LENDER_RULES[ln["lender_code"]]["min_credit"]
        lender_min_down = calc.LENDER_RULES[ln["lender_code"]]["min_down_bp"]
        approved_ok = (score >= lender_min_credit
                       and ln["down_payment_ratio_bp"] >= lender_min_down)
        result = None
        if approved_ok:
            result = calc.loan_amortization(
                agreed_price_cents=int(order["agreed_price_cents"]),
                requested_principal_cents=int(ln["requested_principal_cents"]),
                down_payment_ratio_bp=int(ln["down_payment_ratio_bp"]),
                term_months=int(ln["term_months"]),
                lender_code=ln["lender_code"],
                credit_score=score,
            )
        if approved_ok and result is not None:
            approved_principal, monthly_payment, total_interest = result
            ln["approved_principal_cents"] = approved_principal
            ln["monthly_payment_cents"] = monthly_payment
            ln["total_interest_cents"] = total_interest
            old = ln["status"]
            ln["status"] = "APPROVED"
            bump(ln)
            audit.log("Loan", ln["id"], "STATE_TRANSITION",
                      from_value=old, to_value="APPROVED",
                      actor_role="system", actor_id="system")
            # Update PO down_payment_cents
            order["down_payment_cents"] = int(order["agreed_price_cents"]) - approved_principal
            bump(order)
        else:
            ln["approved_principal_cents"] = 0
            old = ln["status"]
            ln["status"] = "REJECTED"
            bump(ln)
            audit.log("Loan", ln["id"], "STATE_TRANSITION",
                      from_value=old, to_value="REJECTED",
                      actor_role="system", actor_id="system")
    elif et == "disbursement_completed":
        loan_id = payload.get("loan_id")
        ln = DB_INSTANCE.loans.get(loan_id) if loan_id else None
        if not ln or ln["status"] != "APPROVED":
            return
        old = ln["status"]
        ln["status"] = "DISBURSED"
        ln["disbursed_at"] = iso(now())
        bump(ln)
        audit.log("Loan", ln["id"], "STATE_TRANSITION",
                  from_value=old, to_value="DISBURSED",
                  actor_role="system", actor_id="system")
    elif et == "warranty_claim_paid":
        claim_id = payload.get("warranty_claim_id")
        c = DB_INSTANCE.warranty_claims.get(claim_id) if claim_id else None
        if not c or c["status"] != "APPROVED":
            return
        old = c["status"]
        c["status"] = "PAID"
        bump(c)
        audit.log("WarrantyClaim", c["id"], "STATE_TRANSITION",
                  from_value=old, to_value="PAID",
                  actor_role="system", actor_id="system")
        # Update warranty totals
        w = DB_INSTANCE.warranties.get(c["warranty_id"])
        if w:
            paid_claims = [x for x in DB_INSTANCE.warranty_claims.values()
                           if x["warranty_id"] == w["id"] and x["status"] == "PAID"]
            w["claims_count"] = len(paid_claims)
            w["total_claim_payout_cents"] = sum(int(x.get("approved_amount_cents") or 0)
                                                for x in paid_claims)
            bump(w)


@app.route("/_clock/advance", methods=["POST"])
def advance_clock():
    require_role("PlatformAdmin")
    body = get_body()
    to = body.get("to_iso_8601")
    if not to:
        raise err("ERR_INVALID_STATE", "to_iso_8601 required")
    try:
        target_dt = parse_iso(to)
    except Exception:
        raise err("ERR_INVALID_STATE", "to_iso_8601 malformed")
    CLOCK.set(target_dt)

    # Sweep: HOLDING reservations past hold_expires_at → EXPIRED + promote next
    cur = now()
    affected_buyers = set()
    listings_touched = set()
    for r in list(DB_INSTANCE.reservations.values()):
        if r["status"] == "HOLDING" and r.get("hold_expires_at"):
            try:
                exp = parse_iso(r["hold_expires_at"])
            except Exception:
                continue
            if cur >= exp:
                svc.transition_reservation(r, "EXPIRED")
                affected_buyers.add(r["buyer_id"])
                listings_touched.add(r["listing_id"])
                listing = DB_INSTANCE.listings.get(r["listing_id"])
                if listing:
                    listing["reservation_buyer_id"] = None
                    bump(listing)

    for lid in listings_touched:
        listing = DB_INSTANCE.listings.get(lid)
        if not listing:
            continue
        promoted = svc.promote_next_reservation(listing)
        if promoted is None and listing["status"] == "RESERVED":
            svc.transition_listing(listing, "ACTIVE")

    for b in affected_buyers:
        svc.recompute_deposit(b)

    # APPOINTMENT_BOOKED past appointment_at → IN_PROGRESS
    for t in DB_INSTANCE.transfers.values():
        if t["status"] == "APPOINTMENT_BOOKED" and t.get("appointment_at"):
            try:
                appt = parse_iso(t["appointment_at"])
            except Exception:
                continue
            if cur >= appt:
                old = t["status"]
                t["status"] = "IN_PROGRESS"
                bump(t)
                audit.log("TransferCase", t["id"], "STATE_TRANSITION",
                          from_value=old, to_value="IN_PROGRESS",
                          actor_role="system", actor_id="system")

    # ACTIVE Warranty past expires_at → EXPIRED
    for w in DB_INSTANCE.warranties.values():
        if w["status"] == "ACTIVE" and w.get("expires_at"):
            try:
                exp = parse_iso(w["expires_at"])
            except Exception:
                continue
            if cur >= exp:
                old = w["status"]
                w["status"] = "EXPIRED"
                bump(w)
                audit.log("Warranty", w["id"], "STATE_TRANSITION",
                          from_value=old, to_value="EXPIRED",
                          actor_role="system", actor_id="system")

    return ok({"now": iso(cur)})


@app.route("/audit-logs", methods=["GET"])
def list_audit_logs():
    require_role("PlatformAdmin")
    limit, offset = parse_pagination(request.args)
    target_entity = request.args.get("target_entity")
    target_id = request.args.get("target_id")
    event_type = request.args.get("event_type")
    items = list(DB_INSTANCE.audit_logs)
    if target_entity:
        items = [a for a in items if a["target_entity"] == target_entity]
    if target_id:
        items = [a for a in items if a["target_id"] == target_id]
    if event_type:
        items = [a for a in items if a["event_type"] == event_type]
    items = sort_for_list(items)
    page, total = paginate(items, limit, offset)
    return ok_list([_audit_view(a) for a in page], limit, offset, total)


# =============================================================================
# Health endpoint (no auth — convenience for container probes)
# =============================================================================

@app.route("/_health", methods=["GET"])
def _health():
    # Health check exempt from auth via EXEMPT_PATHS
    return ok({"status": "ok"})


# Mark the health route as exempt
from middleware import EXEMPT_PATHS
EXEMPT_PATHS.add("/_health")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
