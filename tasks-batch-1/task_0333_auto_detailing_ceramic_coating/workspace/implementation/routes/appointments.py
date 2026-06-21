"""Appointment endpoints: booking, work/payment state machines, photos, add-on
lines (PRD §3.2-§3.4, §3.6, §3.7)."""
from flask import Blueprint, request

import auth
import clock
import db
import domain
from domain import (
    touch, compute_provisional, compute_final, compute_occupancy,
    recompute_outstanding, recompute_chronological, recompute_projected,
    recompute_credits_remaining, deposit_amount, package_by_tier,
    addon_by_code, NON_TERMINAL_WORK,
)
from errors import err
from recordutil import base_versioned, sorted_by_creation
from response import object_response, array_response
from serialize import serialize, serialize_list
from timeutil import parse_iso, add_minutes
from validation import (
    get_body, require_str, require_enum, require_int, optional_bool,
    parse_pagination, paginate, VEHICLE_SIZES, TIERS, ADDON_CODES, LOCATION_MODES,
)

bp = Blueprint("appointments", __name__)


def _uid():
    return request.headers.get("X-User-ID")


# =====================================================================
# Booking (PRD §3.2, §3.3) — validation priority order per §2.9
# =====================================================================
@bp.route("/detailing/appointments", methods=["POST"])
def book():
    _, role = auth.get_identity()
    auth.require_role(role, {"Customer", "Scheduler", "ShopManager"})
    body = get_body()

    # FK existence (priority 5) is checked after ownership (priority 3). We need
    # customer_id parsed first to resolve ownership. Body well-formedness for the
    # FK field itself: require a string customer_id.
    customer_id = require_str(body, "customer_id")
    cust = db.customers.get(customer_id)
    if cust is not None:
        # ownership precedes FK-not-found per §2.9 (auth before existence). But
        # if the customer does not exist we cannot own it; PRD checks ownership
        # (priority 3) before FK existence (priority 5), so only enforce when
        # the customer resolves.
        auth.require_owner(role, _uid(), customer_id)

    # priority 5: FK existence for customer_id.
    if cust is None:
        raise err("ERR_FK_NOT_FOUND", "customer_id not found")

    # priority 6: body well-formedness.
    tier = require_enum(body, "tier", TIERS)
    vehicle_size = require_enum(body, "vehicle_size", VEHICLE_SIZES)
    location_mode = require_enum(body, "location_mode", LOCATION_MODES)
    start_raw = body.get("scheduled_start_utc")
    scheduled_start = parse_iso(start_raw)
    if scheduled_start is None:
        raise err("ERR_INVALID_REQUEST", "scheduled_start_utc must be an ISO 8601 datetime")
    use_credit = optional_bool(body, "use_membership_credit", default=False)
    service_bay_id = body.get("service_bay_id")
    mobile_unit_id = body.get("mobile_unit_id")

    # Catalog reference data must exist to price/schedule. Missing tier/size rows
    # are a well-formedness failure (cannot compute) -> ERR_INVALID_REQUEST.
    if package_by_tier(tier) is None:
        raise err("ERR_INVALID_REQUEST", "no package catalog row for tier")
    if domain.rate_by_size(vehicle_size) is None:
        raise err("ERR_INVALID_REQUEST", "no vehicle-size rate for vehicle_size")

    # priority 5 (continued): FK existence for the resource FK actually supplied.
    if service_bay_id is not None and service_bay_id not in db.service_bays:
        raise err("ERR_FK_NOT_FOUND", "service_bay_id not found")
    if mobile_unit_id is not None and mobile_unit_id not in db.mobile_units:
        raise err("ERR_FK_NOT_FOUND", "mobile_unit_id not found")

    # priority 7: location/resource coherence.
    if location_mode == "SHOP":
        if not service_bay_id or mobile_unit_id is not None:
            raise err("ERR_RESOURCE_MODE_MISMATCH",
                      "SHOP requires service_bay_id and null mobile_unit_id")
    else:  # MOBILE
        if not mobile_unit_id or service_bay_id is not None:
            raise err("ERR_RESOURCE_MODE_MISMATCH",
                      "MOBILE requires mobile_unit_id and null service_bay_id")

    if location_mode == "SHOP":
        bay = db.service_bays[service_bay_id]
        # priority 8: ceramic-bay capability.
        if tier == "CERAMIC" and not bay["supports_ceramic"]:
            raise err("ERR_BAY_NO_CERAMIC", "bay does not support ceramic")
        # priority 9: stale bay version (before overlap arithmetic).
        expected_bay_version = require_int(body, "expected_service_bay_version")
        if expected_bay_version != bay["version"]:
            raise err("ERR_STALE_BAY_VERSION", "service bay version mismatch")
        # priority 10: resource availability.
        if bay["status"] != "AVAILABLE":
            raise err("ERR_RESOURCE_UNAVAILABLE", "service bay is in MAINTENANCE")
    else:
        unit = db.mobile_units[mobile_unit_id]
        # priority 10: resource availability.
        if unit["status"] != "AVAILABLE":
            raise err("ERR_RESOURCE_UNAVAILABLE", "mobile unit is in MAINTENANCE")

    # Membership snapshot + credit eligibility (priority 16 check for credit).
    is_member = domain.customer_is_member_now(customer_id)
    mem = None
    if use_credit:
        mem_id = cust.get("membership_id")
        mem = db.memberships.get(mem_id) if mem_id else None
        if not (mem and mem["status"] == "ACTIVE" and mem["credits_remaining"] > 0):
            raise err("ERR_NO_CREDIT_AVAILABLE",
                      "membership not ACTIVE or no credits remaining")

    # Build the appointment skeleton so occupancy/pricing helpers can read it.
    rec = base_versioned()
    rec.update({
        "customer_id": customer_id,
        "tier": tier,
        "vehicle_size": vehicle_size,
        "location_mode": location_mode,
        "service_bay_id": service_bay_id if location_mode == "SHOP" else None,
        "mobile_unit_id": mobile_unit_id if location_mode == "MOBILE" else None,
        "scheduled_start_utc": scheduled_start,
        "occupancy_end_utc": None,
        "vehicle_release_utc": None,
        "use_membership_credit": use_credit,
        "work_status": "BOOKED",
        "payment_status": "UNPAID",
        "is_member_at_booking": is_member,
        "credit_applied_cents": 0,
        "provisional_total_cents": 0,
        "final_total_cents": 0,
        "amount_charged_cents": 0,
        "amount_refunded_cents": 0,
        "outstanding_balance_cents": 0,
        "spawned_from_rework_claim_id": None,
    })

    # Occupancy window (no add-on lines yet at booking).
    occ_end, vehicle_release = compute_occupancy(rec)
    rec["occupancy_end_utc"] = occ_end
    rec["vehicle_release_utc"] = vehicle_release

    # priority 11/12: overlap checks (against existing rec is excluded since not stored yet).
    if location_mode == "SHOP":
        _check_bay_overlap(rec)
    else:
        _check_mobile_overlap(rec)

    # Pricing (provisional). final seeded equal to provisional.
    provisional = compute_provisional(rec)
    rec["provisional_total_cents"] = provisional
    rec["final_total_cents"] = provisional

    # Credit application: offsets package only.
    if use_credit and mem is not None:
        _, _, pkg_net = domain.package_pricing(tier, vehicle_size, is_member)
        rec["credit_applied_cents"] = min(mem["wash_credit_value_cents"], pkg_net)
        mem["credits_consumed_total"] += 1
        recompute_credits_remaining(mem)
        touch(mem)

    recompute_outstanding(rec)

    db.appointments[rec["id"]] = rec

    # SHOP booking bumps the bay version (concurrency surface for OCC).
    if location_mode == "SHOP":
        touch(db.service_bays[service_bay_id])

    # forward-looking projected spend recompute.
    recompute_projected(customer_id)

    return object_response(serialize(rec), status=201)


def _intervals(resource_field, resource_id):
    """Existing non-terminal appointments on the same resource."""
    for a in db.appointments.values():
        if a.get(resource_field) == resource_id and a["work_status"] in NON_TERMINAL_WORK:
            yield a


def _check_bay_overlap(candidate):
    cs = candidate["scheduled_start_utc"]
    ce = candidate["occupancy_end_utc"]
    for ex in _intervals("service_bay_id", candidate["service_bay_id"]):
        if ex["id"] == candidate["id"]:
            continue
        if cs < ex["occupancy_end_utc"] and ex["scheduled_start_utc"] < ce:
            raise err("ERR_BAY_TIME_CONFLICT", "overlaps an existing appointment on this bay")


def _check_mobile_overlap(candidate):
    unit = db.mobile_units[candidate["mobile_unit_id"]]
    buffer = unit["travel_buffer_minutes"]
    cs = candidate["scheduled_start_utc"]
    ce = candidate["occupancy_end_utc"]
    for ex in _intervals("mobile_unit_id", candidate["mobile_unit_id"]):
        if ex["id"] == candidate["id"]:
            continue
        if (cs < add_minutes(ex["occupancy_end_utc"], buffer)
                and ex["scheduled_start_utc"] < add_minutes(ce, buffer)):
            raise err("ERR_MOBILE_BUFFER_CONFLICT", "violates travel buffer on this unit")


# =====================================================================
# Reads / lists
# =====================================================================
@bp.route("/detailing/appointments/<aid>", methods=["GET"])
def get_appointment(aid):
    _, role = auth.get_identity()
    auth.require_role(role, {"Customer", "Scheduler", "ShopManager", "Detailer"})
    rec = db.appointments.get(aid)
    if not rec:
        raise err("ERR_NOT_FOUND", "appointment not found")
    auth.require_owner(role, _uid(), rec["customer_id"])
    return object_response(serialize(rec))


@bp.route("/detailing/appointments", methods=["GET"])
def list_appointments():
    _, role = auth.get_identity()
    auth.require_role(role, {"Customer", "Scheduler", "ShopManager", "Detailer"})
    limit, offset = parse_pagination()
    rows = list(db.appointments.values())
    for f in ("customer_id", "service_bay_id", "mobile_unit_id",
              "spawned_from_rework_claim_id"):
        val = request.args.get(f)
        if val is not None:
            rows = [a for a in rows if a.get(f) == val]
    # A Customer listing appointments only sees its own.
    if role == "Customer":
        rows = [a for a in rows if a["customer_id"] == _uid()]
    rows = sorted_by_creation(rows)
    return array_response(serialize_list(paginate(rows, limit, offset)),
                          limit, offset, len(rows))


# =====================================================================
# Add-on lines (PRD §3.4)
# =====================================================================
@bp.route("/detailing/appointments/<aid>/addons", methods=["POST"])
def add_addon_line(aid):
    _, role = auth.get_identity()
    auth.require_role(role, {"Customer", "Scheduler", "ShopManager"})
    appt = db.appointments.get(aid)
    if not appt:
        raise err("ERR_NOT_FOUND", "appointment not found")
    auth.require_owner(role, _uid(), appt["customer_id"])
    body = get_body()
    code = require_enum(body, "addon_code", ADDON_CODES)
    catalog = addon_by_code(code)
    if catalog is None:
        raise err("ERR_FK_NOT_FOUND", "addon_code not in catalog")
    if appt["work_status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "add-on lines may only be added to a BOOKED appointment")
    # unique per (appointment_id, addon_code).
    for line in db.appointment_addons.values():
        if line["appointment_id"] == aid and line["addon_code"] == code:
            raise err("ERR_INVALID_REQUEST", "addon_code already present on this appointment")
    line = base_versioned()
    line.update({
        "appointment_id": aid,
        "addon_code": code,
        "price_cents_snapshot": catalog["price_cents"],
        "extra_minutes_snapshot": catalog["extra_minutes"],
        "line_status": "REQUESTED",
    })
    db.appointment_addons[line["id"]] = line

    # recompute occupancy window + provisional total; bump appointment version.
    occ_end, vehicle_release = compute_occupancy(appt)
    appt["occupancy_end_utc"] = occ_end
    appt["vehicle_release_utc"] = vehicle_release
    appt["provisional_total_cents"] = compute_provisional(appt)
    # final stays seeded equal to provisional until completion (§3.2).
    appt["final_total_cents"] = appt["provisional_total_cents"]
    recompute_outstanding(appt)
    touch(appt)
    recompute_projected(appt["customer_id"])

    return object_response(serialize(line), status=201)


@bp.route("/detailing/appointments/<aid>/addons", methods=["GET"])
def list_addon_lines(aid):
    _, role = auth.get_identity()
    auth.require_role(role, {"Customer", "Scheduler", "ShopManager", "Detailer"})
    appt = db.appointments.get(aid)
    if not appt:
        raise err("ERR_NOT_FOUND", "appointment not found")
    auth.require_owner(role, _uid(), appt["customer_id"])
    limit, offset = parse_pagination()
    rows = sorted_by_creation([l for l in db.appointment_addons.values()
                               if l["appointment_id"] == aid])
    return array_response(serialize_list(paginate(rows, limit, offset)),
                          limit, offset, len(rows))


@bp.route("/detailing/appointments/<aid>/addons/<code>/set-line-status", methods=["POST"])
def set_line_status(aid, code):
    _, role = auth.get_identity()
    auth.require_role(role, {"Detailer"})
    appt = db.appointments.get(aid)
    if not appt:
        raise err("ERR_NOT_FOUND", "appointment not found")
    line = None
    for l in db.appointment_addons.values():
        if l["appointment_id"] == aid and l["addon_code"] == code:
            line = l
            break
    if line is None:
        raise err("ERR_NOT_FOUND", "add-on line not found")
    body = get_body()
    status = require_enum(body, "line_status", {"PERFORMED", "SKIPPED"})
    line["line_status"] = status
    touch(line)
    touch(appt)
    return object_response(serialize(line))


# =====================================================================
# Photos (PRD §3.4)
# =====================================================================
@bp.route("/detailing/appointments/<aid>/photos", methods=["POST"])
def add_photo(aid):
    _, role = auth.get_identity()
    auth.require_role(role, {"Detailer"})
    appt = db.appointments.get(aid)
    if not appt:
        raise err("ERR_NOT_FOUND", "appointment not found")
    body = get_body()
    phase = require_enum(body, "phase", {"BEFORE", "AFTER"})
    image_url = require_str(body, "image_url")
    rec = base_versioned()
    rec.update({"appointment_id": aid, "phase": phase, "image_url": image_url})
    db.job_photos[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/detailing/appointments/<aid>/photos", methods=["GET"])
def list_photos(aid):
    _, role = auth.get_identity()
    auth.require_role(role, {"Customer", "Scheduler", "ShopManager", "Detailer"})
    appt = db.appointments.get(aid)
    if not appt:
        raise err("ERR_NOT_FOUND", "appointment not found")
    auth.require_owner(role, _uid(), appt["customer_id"])
    limit, offset = parse_pagination()
    rows = sorted_by_creation([p for p in db.job_photos.values()
                               if p["appointment_id"] == aid])
    return array_response(serialize_list(paginate(rows, limit, offset)),
                          limit, offset, len(rows))


def _has_photo(aid, phase):
    return any(p["appointment_id"] == aid and p["phase"] == phase
               for p in db.job_photos.values())
