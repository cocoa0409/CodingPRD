"""Share endpoints: creation, activation, exit initiation (PRD 3.2, 3.9)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
from clock import CLOCK
from errors import ApiError
from middleware import ALL_ROLES, require_roles
from response import ok, ok_list
from services.core import (
    FULL_SHARE_HOURS,
    exit_view,
    new_common,
    schedule_view,
    share_view,
    touch,
)
from util import as_int, as_num, as_str, body, paginate_sorted, required

bp = Blueprint("shares", __name__)

ALLOWED_DENOMINATORS = {4, 8, 16, 32}
ALLOWED_METHODS = {"STRAIGHT_LINE", "DOUBLE_DECLINING"}
ALLOWED_RECOVERY = {5, 7}


def _get_share(sid):
    s = db.shares.get(sid)
    if not s:
        raise ApiError("ERR_NOT_FOUND", 404, "Share not found")
    return s


def _create_schedule(share_id, method, years, basis_cents):
    rec = {
        "id": db.new_id(),
        "created_at": CLOCK.now_iso(),
        "share_id": share_id,
        "schedule_method": method,
        "recovery_years": years,
        "basis_cents": basis_cents,
        "accumulated_depreciation_cents": 0,
        "current_year_allowance_cents": 0,
    }
    db.depreciation_schedules[rec["id"]] = rec
    return rec


@bp.route("/shares", methods=["POST"])
def create_share():
    require_roles("ProgramAdmin")
    data = body()
    owner_id = as_str(required(data, "owner_id"), "owner_id")
    owner = db.owners.get(owner_id)
    if not owner:
        raise ApiError("ERR_NOT_FOUND", 404, "Owner not found")
    class_id = as_str(required(data, "class_id"), "class_id")
    cls = db.aircraft_classes.get(class_id)
    if not cls:
        raise ApiError("ERR_NOT_FOUND", 404, "Aircraft class not found")
    num = as_int(required(data, "fraction_numerator"), "fraction_numerator")
    den = as_int(required(data, "fraction_denominator"), "fraction_denominator")
    price = as_int(required(data, "purchase_price_cents"), "purchase_price_cents")

    # Fraction validity (pipeline stage 13)
    if den not in ALLOWED_DENOMINATORS or num < 1 or num > den:
        raise ApiError("ERR_INVALID_FRACTION", 422,
                       "Fraction denominator must be in {4,8,16,32} and "
                       "1 <= numerator <= denominator")
    if price <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "purchase_price_cents must be > 0")

    # Program posture: new share creation rejected in WINDING_DOWN/CLOSED.
    program = db.programs.get(cls["program_id"])
    if program and program["program_posture"] in ("WINDING_DOWN", "CLOSED"):
        raise ApiError("ERR_PROGRAM_POSTURE_BLOCKS", 409,
                       "Program posture blocks new share creation")

    method = data.get("schedule_method")
    years = data.get("recovery_years")
    if method is not None:
        as_str(method, "schedule_method")
        if method not in ALLOWED_METHODS:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "schedule_method must be STRAIGHT_LINE or "
                           "DOUBLE_DECLINING")
    if years is not None:
        as_int(years, "recovery_years")
        if years not in ALLOWED_RECOVERY:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "recovery_years must be in {5, 7}")

    rec = new_common()
    rec.update({
        "owner_id": owner_id,
        "class_id": class_id,
        "fraction_numerator": num,
        "fraction_denominator": den,
        "annual_entitlement_hours": None,
        "hours_remaining_cy": None,
        "contract_year_index": 0,
        "share_status": "PENDING_ACTIVATION",
        "purchase_price_cents": price,
    })
    db.shares[rec["id"]] = rec

    if method is not None and years is not None:
        _create_schedule(rec["id"], method, years, price)

    return ok(share_view(rec), status=201)


@bp.route("/shares/<sid>", methods=["GET"])
def get_share(sid):
    require_roles(*ALL_ROLES)
    return ok(share_view(_get_share(sid)))


@bp.route("/shares", methods=["GET"])
def list_shares():
    require_roles(*ALL_ROLES)
    owner_id = request.args.get("owner_id")
    class_id = request.args.get("class_id")
    status = request.args.get("share_status")
    items = list(db.shares.values())
    if owner_id is not None:
        items = [s for s in items if s["owner_id"] == owner_id]
    if class_id is not None:
        items = [s for s in items if s["class_id"] == class_id]
    if status is not None:
        items = [s for s in items if s["share_status"] == status]
    page, total, limit, offset = paginate_sorted(items)
    return ok_list([share_view(s) for s in page], total, limit, offset)


@bp.route("/shares/<sid>/activate", methods=["POST"])
def activate_share(sid):
    require_roles("ProgramAdmin")
    s = _get_share(sid)
    if s["share_status"] != "PENDING_ACTIVATION":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Share must be PENDING_ACTIVATION to activate")
    cls = db.aircraft_classes[s["class_id"]]
    program = db.programs[cls["program_id"]]
    if program["program_posture"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_POSTURE_BLOCKS", 409,
                       "Program must be ACTIVE to activate a share")
    owner = db.owners[s["owner_id"]]
    if owner["owner_standing"] not in ("GOOD", "DELINQUENT"):
        raise ApiError("ERR_OWNER_STANDING_BLOCKS", 422,
                       "Owner standing blocks share activation")

    entitlement = (
        Decimal(s["fraction_numerator"]) / Decimal(s["fraction_denominator"])
        * Decimal(FULL_SHARE_HOURS)
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    s["annual_entitlement_hours"] = float(entitlement)
    s["hours_remaining_cy"] = float(entitlement)
    s["share_status"] = "ACTIVE"
    touch(s)

    # Create depreciation schedule if not provided at create.
    if not any(d["share_id"] == s["id"] for d in db.depreciation_schedules.values()):
        _create_schedule(s["id"], "STRAIGHT_LINE", 5, s["purchase_price_cents"])

    return ok(share_view(s))


@bp.route("/shares/<sid>/exit", methods=["POST"])
def exit_share(sid):
    user_id, role = require_roles("Owner")
    s = _get_share(sid)
    if s["owner_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "Only the share's owner may open an exit")
    if s["share_status"] not in ("ACTIVE", "LISTED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Share must be ACTIVE or LISTED to exit")
    # Referential: covering listing must be withdrawn/expired first; no live
    # exit request for this share.
    if s["share_status"] == "LISTED":
        live = any(
            t["share_id"] == s["id"]
            and t["listing_status"] in ("LISTED", "UNDER_OFFER")
            for t in db.transfer_listings.values()
        )
        if live:
            raise ApiError("ERR_REFERENTIAL_CONFLICT", 409,
                           "Covering transfer listing must be withdrawn or "
                           "expired first")
    if any(
        x["share_id"] == s["id"]
        and x["exit_status"] in ("SUBMITTED", "VALUED", "APPROVED")
        for x in db.exit_requests.values()
    ):
        raise ApiError("ERR_REFERENTIAL_CONFLICT", 409,
                       "An exit request is already open for this share")

    # Cascade: REQUESTED bookings -> EXPIRED; CONFIRMED -> CANCELLED with
    # compensating re-credit.
    for b in db.bookings.values():
        if b["share_id"] != s["id"]:
            continue
        if b["booking_status"] == "REQUESTED":
            b["booking_status"] = "EXPIRED"
            touch(b)
        elif b["booking_status"] == "CONFIRMED":
            b["booking_status"] = "CANCELLED"
            b["billing_status"] = "UNBILLED"
            touch(b)
            s["hours_remaining_cy"] = round(
                s["hours_remaining_cy"] + b["estimated_block_hours"], 2
            )

    s["share_status"] = "IN_EXIT"
    touch(s)

    rec = new_common()
    rec.update({
        "share_id": s["id"],
        "exit_status": "SUBMITTED",
        "buyout_amount_cents": None,
        "early_exit_penalty_cents": None,
        "settlement_cents": None,
    })
    db.exit_requests[rec["id"]] = rec
    return ok(exit_view(rec), status=201)
