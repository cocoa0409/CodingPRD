"""Reservation lifecycle, assignments, add-ons, incidents (PRD §3.5, §3.6, §3.8, §3.9)."""
from flask import Blueprint, request, g

import errors
import response
from db import db, new_id, now_iso
from middleware import require_roles
from services import serialize, calc
from services.common import (stamp_create, touch, get_body, require_fields,
                             require_enum, parse_date, days_between)
from services.query import paginate_params, sort_by_created, apply_page
from services.package import recompute_credits_remaining
from services import assignment as asvc
from routes.facilities import get_facility_or_404
from routes.pets import get_pet_or_404
from routes.runs import get_run_or_404
from routes.packages import get_package_or_404

bp = Blueprint("reservations", __name__)

SERVICE_TYPES = {"DAYCARE", "OVERNIGHT"}
CARE_KINDS = {"FEEDING", "MEDICATION"}
ADDON_KINDS = {"BATH", "PLAYTIME"}


# --------------------------------------------------------------------------
# lookups + ownership
# --------------------------------------------------------------------------
def get_reservation_or_404(rid):
    r = db.reservations.get(rid)
    if r is None:
        raise errors.err_not_found()
    return r


def _reservation_owner_guard(res):
    if g.role == "Owner" and g.user_id != res["owner_id"]:
        raise errors.err_not_resource_owner()


# --------------------------------------------------------------------------
# Create Reservation
# --------------------------------------------------------------------------
@bp.route("/facilities/<fid>/reservations", methods=["POST"])
@require_roles("FacilityManager", "FacilityStaff", "Owner")
def create_reservation(fid):
    facility = get_facility_or_404(fid)
    body = get_body()
    require_fields(body, ["pet_id", "service_type", "start_date", "end_date"])

    service_type = body["service_type"]
    require_enum(service_type, SERVICE_TYPES, "service_type")
    start_date = body["start_date"]
    end_date = body["end_date"]
    sd = parse_date(start_date)
    ed = parse_date(end_date)

    # Date ordering (ERR_INVALID_REQUEST).
    if service_type == "OVERNIGHT":
        if not (ed > sd):
            raise errors.err_invalid_request("OVERNIGHT end_date must be after start_date.")
        nights = (ed - sd).days
    else:  # DAYCARE
        if ed != sd:
            raise errors.err_invalid_request("DAYCARE end_date must equal start_date.")
        nights = 0

    pet_id = body["pet_id"]
    package_id = body.get("package_id")

    # Owner-role: the reservation is created for a pet they own. Validate the
    # pet's owner against the caller after existence (handled below).
    pet = db.pets.get(pet_id)
    if pet is None:
        # body FK not found -> cross-facility reference family for create
        raise errors.err_cross_facility()
    if pet["facility_id"] != fid:
        raise errors.err_cross_facility()
    if g.role == "Owner" and g.user_id != pet["owner_id"]:
        raise errors.err_not_resource_owner()

    if package_id is not None:
        pkg = db.packages.get(package_id)
        if pkg is None or pkg["facility_id"] != fid:
            raise errors.err_cross_facility()

    # care_plan
    care_plan = body.get("care_plan", [])
    care_plan = _build_care_plan(care_plan)
    # belongings
    belongings = body.get("belongings", [])
    belongings = _build_belongings(belongings)

    res = {
        "facility_id": fid,
        "pet_id": pet_id,
        "owner_id": pet["owner_id"],
        "package_id": package_id,
        "service_type": service_type,
        "start_date": start_date,
        "end_date": end_date,
        "nights": nights,
        "care_plan": care_plan,
        "belongings": belongings,
        "incidents": [],
        "deposit_cents": 0,
        "deposit_paid_cents": 0,
        "total_cents": 0,
        "refund_cents": 0,
        "redeemed_credit": False,
        "status": "REQUESTED",
    }
    # deposit estimate variant
    res["deposit_cents"] = calc.deposit_amount(
        service_type, pet["size_class"], nights, facility["deposit_policy"])
    stamp_create(res)
    db.reservations[res["id"]] = res
    return response.success(serialize.reservation(res), status=201)


def _build_care_plan(raw):
    if not isinstance(raw, list):
        raise errors.err_invalid_request("care_plan must be a list.")
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise errors.err_invalid_request("care_plan entries must be objects.")
        require_fields(entry, ["kind", "schedule_time", "detail"])
        kind = entry["kind"]
        require_enum(kind, CARE_KINDS, "care_plan.kind")
        requires_signoff = bool(entry.get("requires_signoff", False))
        if kind == "MEDICATION":
            requires_signoff = True
        out.append({
            "kind": kind,
            "schedule_time": entry["schedule_time"],
            "detail": entry["detail"],
            "requires_signoff": requires_signoff,
        })
    return out


def _build_belongings(raw):
    if not isinstance(raw, list):
        raise errors.err_invalid_request("belongings must be a list.")
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise errors.err_invalid_request("belongings entries must be objects.")
        require_fields(entry, ["description", "quantity"])
        quantity = entry["quantity"]
        if isinstance(quantity, bool) or not isinstance(quantity, (int, float)):
            raise errors.err_invalid_request("quantity must be a number.")
        if quantity <= 0:
            raise errors.err_invalid_request("quantity must be > 0.")
        out.append({
            "description": entry["description"],
            "quantity": quantity,
            "returned": False,
        })
    return out


# --------------------------------------------------------------------------
# Get / List Reservation
# --------------------------------------------------------------------------
@bp.route("/reservations/<rid>", methods=["GET"])
@require_roles("FacilityManager", "FacilityStaff", "Owner")
def get_reservation(rid):
    res = get_reservation_or_404(rid)
    _reservation_owner_guard(res)
    return response.success(serialize.reservation(res), status=200)


@bp.route("/reservations", methods=["GET"])
@require_roles("FacilityManager", "FacilityStaff", "Owner")
def list_reservations():
    limit, offset = paginate_params()
    pet_id = request.args.get("pet_id")
    owner_id = request.args.get("owner_id")
    package_id = request.args.get("package_id")
    status_filter = request.args.get("status")

    items = list(db.reservations.values())
    if g.role == "Owner":
        items = [r for r in items if r["owner_id"] == g.user_id]
    if pet_id is not None:
        items = [r for r in items if r["pet_id"] == pet_id]
    if owner_id is not None:
        items = [r for r in items if r["owner_id"] == owner_id]
    if package_id is not None:
        items = [r for r in items if r.get("package_id") == package_id]
    if status_filter is not None:
        items = [r for r in items if r["status"] == status_filter]
    items = sort_by_created(items)
    page, total = apply_page(items, limit, offset)
    return response.list_success([serialize.reservation(r) for r in page],
                                 limit, offset, total)


# --------------------------------------------------------------------------
# Pay deposit
# --------------------------------------------------------------------------
@bp.route("/reservations/<rid>/pay_deposit", methods=["POST"])
@require_roles("FacilityManager", "FacilityStaff", "Owner")
def pay_deposit(rid):
    res = get_reservation_or_404(rid)
    _reservation_owner_guard(res)
    body = get_body()
    require_fields(body, ["cash_cents"])
    cash_cents = body["cash_cents"]
    if isinstance(cash_cents, bool) or not isinstance(cash_cents, int) or cash_cents < 0:
        raise errors.err_invalid_request("cash_cents must be a non-negative integer.")

    if res["status"] != "REQUESTED":
        raise errors.err_invalid_state()

    owner = db.owners.get(res["owner_id"])
    remaining = res["deposit_cents"] - res["deposit_paid_cents"]
    if remaining < 0:
        remaining = 0
    # Draw on wallet credit first.
    credit_used = min(owner["wallet_credit_cents"], remaining)
    owner["wallet_credit_cents"] -= credit_used
    if credit_used:
        touch(owner)
    res["deposit_paid_cents"] += credit_used + cash_cents
    touch(res)
    return response.success(serialize.reservation(res), status=200)


# --------------------------------------------------------------------------
# Confirm
# --------------------------------------------------------------------------
@bp.route("/reservations/<rid>/confirm", methods=["POST"])
@require_roles("FacilityManager", "FacilityStaff")
def confirm_reservation(rid):
    res = get_reservation_or_404(rid)
    facility = db.facilities.get(res["facility_id"])
    pet = db.pets.get(res["pet_id"])

    # Precondition order (PRD §3.6).
    if res["status"] != "REQUESTED":
        raise errors.err_invalid_state()
    if pet["vaccination_status"] != "VALID":
        raise errors.err_vaccination_required()
    if pet["temperament_clearance"] == "FLAGGED":
        raise errors.err_temperament_not_cleared()
    held = [a for a in db.run_assignments.values()
            if a["reservation_id"] == rid and a["status"] == "HELD"]
    if not held:
        raise errors.err_no_run_assigned()

    # Latch deposit (final variant) BEFORE the deposit-paid check.
    latched = calc.deposit_amount(res["service_type"], pet["size_class"],
                                  res["nights"], facility["deposit_policy"])
    res["deposit_cents"] = latched

    if facility["deposit_policy"] != "NONE":
        if res["deposit_paid_cents"] < latched:
            raise errors.err_deposit_unpaid()

    pkg = None
    if res.get("package_id") is not None:
        pkg = db.packages.get(res["package_id"])
        if pkg is None or pkg["status"] != "ACTIVE" \
                or pkg["credits_remaining"] < 1 or res["service_type"] != "DAYCARE":
            raise errors.err_package_not_redeemable()

    # All preconditions pass — cascade.
    res["status"] = "CONFIRMED"
    for a in held:
        a["status"] = "OCCUPIED"
        touch(a)

    if pkg is not None:
        redemption = {
            "package_id": pkg["id"],
            "reservation_id": rid,
            "credits_used": 1,
            "redeemed_on": facility["current_date"],
            "reversed": False,
        }
        redemption["id"] = new_id()
        redemption["created_at"] = now_iso()
        db.package_redemptions[redemption["id"]] = redemption
        res["redeemed_credit"] = True
        recompute_credits_remaining(pkg)
        touch(pkg)

    touch(res)
    return response.success(serialize.reservation(res), status=200)


# --------------------------------------------------------------------------
# Check-in
# --------------------------------------------------------------------------
@bp.route("/reservations/<rid>/check_in", methods=["POST"])
@require_roles("FacilityManager", "FacilityStaff")
def check_in(rid):
    res = get_reservation_or_404(rid)
    facility = db.facilities.get(res["facility_id"])
    pet = db.pets.get(res["pet_id"])

    if res["status"] != "CONFIRMED":
        raise errors.err_invalid_state()
    if days_between(facility["current_date"], res["start_date"]) < 0:
        raise errors.err_checkin_too_early()
    if pet["vaccination_status"] != "VALID":
        raise errors.err_vaccination_required()

    res["status"] = "CHECKED_IN"
    touch(res)
    return response.success(serialize.reservation(res), status=200)


# --------------------------------------------------------------------------
# Check-out (and close on a second call)
# --------------------------------------------------------------------------
@bp.route("/reservations/<rid>/check_out", methods=["POST"])
@require_roles("FacilityManager", "FacilityStaff")
def check_out(rid):
    res = get_reservation_or_404(rid)
    body = get_body()

    if res["status"] == "CHECKED_IN":
        _do_check_out(res)
        return response.success(serialize.reservation(res), status=200)
    elif res["status"] == "CHECKED_OUT":
        _do_close(res, body)
        return response.success(serialize.reservation(res), status=200)
    else:
        raise errors.err_invalid_state()


def _addon_in_window(res, addon):
    """scheduled_date within the reservation window. OVERNIGHT window is
    [start_date, end_date); DAYCARE window is [start_date, start_date] (single
    date), matching the add-on creation window check."""
    sd = parse_date(res["start_date"])
    d = parse_date(addon["scheduled_date"])
    if res["service_type"] == "OVERNIGHT":
        ed = parse_date(res["end_date"])
        return sd <= d < ed
    else:
        return d == sd


def _do_check_out(res):
    pet = db.pets.get(res["pet_id"])
    # Auto-deliver in-window BOOKED add-ons.
    delivered_prices = []
    for a in db.addons.values():
        if a["reservation_id"] != res["id"]:
            continue
        if a["status"] == "BOOKED" and _addon_in_window(res, a):
            a["status"] = "DELIVERED"
            touch(a)
        if a["status"] == "DELIVERED":
            delivered_prices.append(a["price_cents"])

    # Latch total.
    res["total_cents"] = calc.reservation_total(
        res["service_type"], pet["size_class"], res["nights"],
        delivered_prices, res["redeemed_credit"])

    # Release OCCUPIED assignments.
    for a in db.run_assignments.values():
        if a["reservation_id"] == res["id"] and a["status"] == "OCCUPIED":
            a["status"] = "RELEASED"
            touch(a)

    res["status"] = "CHECKED_OUT"
    touch(res)


def _do_close(res, body):
    return_all = bool(body.get("return_all_belongings", False))
    if return_all:
        for b in res["belongings"]:
            b["returned"] = True
    if not all(b["returned"] for b in res["belongings"]):
        raise errors.err_belongings_outstanding()
    res["status"] = "CLOSED"
    touch(res)


# --------------------------------------------------------------------------
# Cancel
# --------------------------------------------------------------------------
@bp.route("/reservations/<rid>/cancel", methods=["POST"])
@require_roles("FacilityManager", "FacilityStaff", "Owner")
def cancel(rid):
    res = get_reservation_or_404(rid)
    _reservation_owner_guard(res)

    if res["status"] not in ("REQUESTED", "CONFIRMED"):
        raise errors.err_invalid_state()

    facility = db.facilities.get(res["facility_id"])
    from_state = res["status"]

    refund = calc.cancellation_refund("CANCEL", res["deposit_paid_cents"],
                                      res["start_date"], facility["current_date"])
    res["refund_cents"] = refund
    owner = db.owners.get(res["owner_id"])
    if refund:
        owner["wallet_credit_cents"] += refund
        touch(owner)

    # Release assignments: HELD (from REQUESTED) or OCCUPIED (from CONFIRMED).
    for a in db.run_assignments.values():
        if a["reservation_id"] != rid:
            continue
        if a["status"] in ("HELD", "OCCUPIED"):
            a["status"] = "RELEASED"
            touch(a)

    # Cancel any BOOKED add-ons.
    for a in db.addons.values():
        if a["reservation_id"] == rid and a["status"] == "BOOKED":
            a["status"] = "CANCELLED"
            touch(a)

    # Reverse package redemption if a credit was consumed.
    if res["redeemed_credit"]:
        _reverse_redemption(res)

    res["status"] = "CANCELLED"
    touch(res)
    return response.success(serialize.reservation(res), status=200)


# --------------------------------------------------------------------------
# Mark no-show
# --------------------------------------------------------------------------
@bp.route("/reservations/<rid>/mark_no_show", methods=["POST"])
@require_roles("FacilityManager")
def mark_no_show(rid):
    res = get_reservation_or_404(rid)
    facility = db.facilities.get(res["facility_id"])

    if res["status"] != "CONFIRMED":
        raise errors.err_invalid_state()
    if days_between(facility["current_date"], res["start_date"]) <= 0:
        raise errors.err_no_show_too_early()

    res["refund_cents"] = 0
    for a in db.run_assignments.values():
        if a["reservation_id"] == rid and a["status"] == "OCCUPIED":
            a["status"] = "RELEASED"
            touch(a)
    for a in db.addons.values():
        if a["reservation_id"] == rid and a["status"] == "BOOKED":
            a["status"] = "CANCELLED"
            touch(a)
    if res["redeemed_credit"]:
        _reverse_redemption(res)

    res["status"] = "NO_SHOW"
    touch(res)
    return response.success(serialize.reservation(res), status=200)


def _reverse_redemption(res):
    for rec in db.package_redemptions.values():
        if rec["reservation_id"] == res["id"] and not rec["reversed"]:
            rec["reversed"] = True
            pkg = db.packages.get(rec["package_id"])
            if pkg is not None:
                recompute_credits_remaining(pkg)
                touch(pkg)


# --------------------------------------------------------------------------
# Incidents
# --------------------------------------------------------------------------
@bp.route("/reservations/<rid>/incidents", methods=["POST"])
@require_roles("FacilityManager", "FacilityStaff")
def add_incident(rid):
    res = get_reservation_or_404(rid)
    facility = db.facilities.get(res["facility_id"])
    body = get_body()
    require_fields(body, ["severity", "note"])

    incident = {
        "severity": body["severity"],
        "note": body["note"],
        "logged_on": facility["current_date"],
        "pet_id": res["pet_id"],
    }
    res["incidents"].append(incident)
    touch(res)
    return response.success(serialize.reservation(res), status=201)


# --------------------------------------------------------------------------
# Assignments (OCC-guarded create + list)
# --------------------------------------------------------------------------
@bp.route("/reservations/<rid>/assignments", methods=["POST"])
@require_roles("FacilityManager", "FacilityStaff")
def create_assignment(rid):
    res = get_reservation_or_404(rid)
    facility = db.facilities.get(res["facility_id"])
    body = get_body()
    require_fields(body, ["run_id", "expected_reservation_version"])
    run_id = body["run_id"]
    expected_version = body["expected_reservation_version"]
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise errors.err_invalid_request("expected_reservation_version must be an integer.")

    # Cross-facility reference: run must belong to the reservation's facility.
    run = db.runs.get(run_id)
    if run is None or run["facility_id"] != res["facility_id"]:
        raise errors.err_cross_facility()

    pet = db.pets.get(res["pet_id"])

    # State: assignments are created only while building the reservation.
    if res["status"] != "REQUESTED":
        raise errors.err_invalid_state()

    # Eligibility (ERR_RUN_NOT_ELIGIBLE).
    asvc.check_eligibility(run, pet, res)

    # Derived window.
    win_start, win_end = asvc.assignment_window(res)

    # Pet self-exclusion (ERR_PET_DOUBLE_BOOKED).
    asvc.check_pet_double_booked(pet["id"], win_start, win_end)

    # Suite overlap / daycare capacity / grouping.
    if run["kind"] == "OVERNIGHT_SUITE":
        asvc.check_suite_overlap(run_id, win_start, win_end)
    else:  # DAYCARE_PEN
        asvc.check_daycare_capacity(run, win_start, win_end, facility)
        asvc.check_group_compatibility(run, pet, win_start, win_end)

    # OCC check is the fiscal-tier guard (ERR_STALE_VERSION).
    if expected_version != res["version"]:
        raise errors.err_stale_version()

    a = {
        "reservation_id": rid,
        "run_id": run_id,
        "window_start_date": win_start,
        "window_end_date": win_end,
        "status": "HELD",
    }
    stamp_create(a)
    db.run_assignments[a["id"]] = a

    # Creating an assignment advances the parent reservation's version.
    touch(res)
    return response.success(serialize.assignment(a), status=201)


@bp.route("/reservations/<rid>/assignments", methods=["GET"])
@require_roles("FacilityManager", "FacilityStaff")
def list_assignments(rid):
    get_reservation_or_404(rid)
    limit, offset = paginate_params()
    status_filter = request.args.get("status")
    items = [a for a in db.run_assignments.values() if a["reservation_id"] == rid]
    if status_filter is not None:
        items = [a for a in items if a["status"] == status_filter]
    items = sort_by_created(items)
    page, total = apply_page(items, limit, offset)
    return response.list_success([serialize.assignment(a) for a in page],
                                 limit, offset, total)


# --------------------------------------------------------------------------
# Add-ons
# --------------------------------------------------------------------------
@bp.route("/reservations/<rid>/addons", methods=["POST"])
@require_roles("FacilityManager", "FacilityStaff", "Owner")
def create_addon(rid):
    res = get_reservation_or_404(rid)
    _reservation_owner_guard(res)
    pet = db.pets.get(res["pet_id"])
    body = get_body()
    require_fields(body, ["kind", "scheduled_date"])
    kind = body["kind"]
    require_enum(kind, ADDON_KINDS, "kind")
    scheduled_date = body["scheduled_date"]
    parse_date(scheduled_date)

    # Must fall inside the reservation window (ERR_ADDON_OUT_OF_WINDOW).
    if not _addon_in_window(res, {"scheduled_date": scheduled_date}):
        raise errors.err_addon_out_of_window()

    price = calc.addon_price(kind, pet["size_class"])
    a = {
        "reservation_id": rid,
        "kind": kind,
        "scheduled_date": scheduled_date,
        "price_cents": price,
        "status": "BOOKED",
    }
    stamp_create(a)
    db.addons[a["id"]] = a
    return response.success(serialize.addon(a), status=201)
