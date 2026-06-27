"""RentalAsset + RentalAgreement endpoints (PRD 3.7)."""
from flask import Blueprint, request

import calc
import clock
import db
import errors
import helpers
import serialize
import validate
from auth import authenticate, require_roles
from response import ok, created, ok_list

bp = Blueprint("rentals", __name__)

RENTAL_TERMINAL = {"RETURNED", "CANCELLED"}


# ---------------------------------------------------------------- Assets ---

@bp.route("/rental-assets", methods=["POST"])
def create_asset():
    caller = authenticate()
    require_roles(caller, {"RentalClerk", "InventoryManager"})
    data = validate.body()
    asset_tag = validate.require_str(data, "asset_tag")
    category = validate.require_str(data, "category")
    daily_rate = validate.require_int(data, "daily_rate_cents", minimum=1)
    deposit = validate.require_int(data, "deposit_cents", minimum=0)
    with db.lock:
        for a in db.rental_assets.values():
            if a["asset_tag"] == asset_tag:
                raise errors.duplicate("asset_tag already in use")
        rec = db.new_record({
            "asset_tag": asset_tag,
            "category": category,
            "daily_rate_cents": daily_rate,
            "deposit_cents": deposit,
            "status": "AVAILABLE",
        })
        db.rental_assets[rec["id"]] = rec
        return created(serialize.rental_asset(rec))


@bp.route("/rental-assets/<rid>", methods=["GET"])
def get_asset(rid):
    caller = authenticate()
    require_roles(caller, {"RentalClerk", "InventoryManager"})
    with db.lock:
        rec = helpers.get_or_404(db.rental_assets, rid)
        return ok(serialize.rental_asset(rec))


@bp.route("/rental-assets/<rid>/set-maintenance", methods=["POST"])
def set_maintenance(rid):
    caller = authenticate()
    require_roles(caller, {"RentalClerk", "InventoryManager"})
    data = validate.body()
    with db.lock:
        rec = helpers.get_or_404(db.rental_assets, rid)
        maintenance = validate.require_bool(data, "maintenance")
        if maintenance:
            rec["status"] = "MAINTENANCE"
        else:
            # false returns it to AVAILABLE when not currently rented
            if rec["status"] != "RENTED":
                rec["status"] = "AVAILABLE"
        db.touch(rec)
        return ok(serialize.rental_asset(rec))


# ------------------------------------------------------------ Agreements ---

def _non_terminal_agreements(asset_id, exclude_id=None):
    return [
        ag for ag in db.rental_agreements.values()
        if ag["rental_asset_id"] == asset_id
        and ag["status"] not in RENTAL_TERMINAL
        and ag["id"] != exclude_id
    ]


def _intervals_overlap(s1, e1, s2, e2):
    """Half-open [s, e) overlap: s1 < e2 and s2 < e1. Back-to-back allowed."""
    return s1 < e2 and s2 < e1


@bp.route("/rental-agreements", methods=["POST"])
def create_agreement():
    caller = authenticate()
    require_roles(caller, {"RentalClerk"})
    data = validate.body()
    asset_id = validate.require_str(data, "rental_asset_id")
    account_id = validate.opt_str(data, "contractor_account_id", default=None)
    start_at = validate.parse_datetime(data, "start_at", required=True)
    due_at = validate.parse_datetime(data, "due_at", required=True)
    if not (due_at > start_at):
        raise errors.invalid_request("due_at must be strictly after start_at")
    with db.lock:
        helpers.get_or_404(db.rental_assets, asset_id)
        if account_id is not None:
            helpers.get_or_404(db.contractor_accounts, account_id)
        # priority 15: overlap against non-terminal agreements
        for ag in _non_terminal_agreements(asset_id):
            if _intervals_overlap(start_at, due_at, ag["start_at"], ag["due_at"]):
                raise errors.ApiError(errors.ERR_RENTAL_OVERLAP, 409,
                                      "interval overlaps an existing agreement")
        rec = db.new_record({
            "rental_asset_id": asset_id,
            "contractor_account_id": account_id,
            "start_at": start_at,
            "due_at": due_at,
            "returned_at": None,
            "rental_charge_cents": 0,
            "status": "RESERVED",
        })
        db.rental_agreements[rec["id"]] = rec
        return created(serialize.rental_agreement(rec))


@bp.route("/rental-agreements/<rid>", methods=["GET"])
def get_agreement(rid):
    caller = authenticate()
    require_roles(caller, {"RentalClerk", "Contractor"})
    with db.lock:
        rec = helpers.get_or_404(db.rental_agreements, rid)
        if caller.is_contractor and rec["contractor_account_id"] != caller.user_id:
            raise errors.unauthorized()
        return ok(serialize.rental_agreement(rec))


@bp.route("/rental-agreements", methods=["GET"])
def list_agreements():
    caller = authenticate()
    require_roles(caller, {"RentalClerk", "Contractor"})
    limit, offset = validate.pagination()
    asset_id = request.args.get("rental_asset_id")
    account_id = request.args.get("contractor_account_id")
    with db.lock:
        items = list(db.rental_agreements.values())
        if caller.is_contractor:
            items = [a for a in items if a["contractor_account_id"] == caller.user_id]
        if asset_id is not None:
            items = [a for a in items if a["rental_asset_id"] == asset_id]
        if account_id is not None:
            items = [a for a in items if a["contractor_account_id"] == account_id]
        items = helpers.sorted_by_creation(items)
        page, total = helpers.paginate(items, limit, offset)
        return ok_list([serialize.rental_agreement(a) for a in page], limit, offset, total)


@bp.route("/rental-agreements/<rid>/check-out", methods=["POST"])
def check_out(rid):
    caller = authenticate()
    require_roles(caller, {"RentalClerk"})
    with db.lock:
        ag = helpers.get_or_404(db.rental_agreements, rid)
        if ag["status"] != "RESERVED":
            raise errors.invalid_state("check-out is only defined from RESERVED")
        asset = db.rental_assets.get(ag["rental_asset_id"])
        # ERR_ASSET_UNAVAILABLE before ERR_RENTAL_NOT_STARTED per scaffold order
        if asset is None or asset["status"] != "AVAILABLE":
            raise errors.ApiError(errors.ERR_ASSET_UNAVAILABLE, 409,
                                  "asset is not AVAILABLE")
        if clock.now() < ag["start_at"]:
            raise errors.ApiError(errors.ERR_RENTAL_NOT_STARTED, 409,
                                  "clock has not reached start_at")
        ag["status"] = "CHECKED_OUT"
        db.touch(ag)
        asset["status"] = "RENTED"
        db.touch(asset)
        return ok(serialize.rental_agreement(ag))


@bp.route("/rental-agreements/<rid>/return", methods=["POST"])
def return_agreement(rid):
    caller = authenticate()
    require_roles(caller, {"RentalClerk"})
    with db.lock:
        ag = helpers.get_or_404(db.rental_agreements, rid)
        if ag["status"] != "CHECKED_OUT":
            raise errors.invalid_state("return is only defined from CHECKED_OUT")
        returned_at = clock.now()
        ag["returned_at"] = returned_at
        asset = db.rental_assets.get(ag["rental_asset_id"])
        rate = asset["daily_rate_cents"] if asset else 0
        ag["rental_charge_cents"] = calc.rental_charge(rate, ag["start_at"], returned_at)
        ag["status"] = "RETURNED"
        db.touch(ag)
        if asset is not None:
            asset["status"] = "AVAILABLE"
            db.touch(asset)
        return ok(serialize.rental_agreement(ag))


@bp.route("/rental-agreements/<rid>/cancel", methods=["POST"])
def cancel_agreement(rid):
    caller = authenticate()
    require_roles(caller, {"RentalClerk"})
    with db.lock:
        ag = helpers.get_or_404(db.rental_agreements, rid)
        if ag["status"] != "RESERVED":
            raise errors.invalid_state("only a RESERVED agreement can be cancelled")
        ag["status"] = "CANCELLED"
        db.touch(ag)
        return ok(serialize.rental_agreement(ag))
