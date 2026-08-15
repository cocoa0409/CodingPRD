"""Houses, biosecurity audits, downtime/quarantine release, house flocks."""
from flask import Blueprint, request

import db
import utils
from errors import ApiError
from helpers import check_unique, get_or_404, need_date, need_enum, need_int, need_str
from middleware import body, grower_owns_or_403, list_response, require_roles
from response import ok
from services import domain

bp = Blueprint("houses", __name__)

ADMIN = "IntegratorAdmin"
GROWER = "Grower"
ANALYST = "SettlementAnalyst"
TECH = "ServiceTech"
HAUL = "LivehaulScheduler"


@bp.route("/api/houses", methods=["POST"])
@require_roles(ADMIN)
def create_house():
    b = body()
    # Priority 4: body FK existence.
    grower_id = b.get("grower_id")
    if not isinstance(grower_id, str) or not grower_id:
        raise ApiError("ERR_QUANTITY_INVALID", "Field 'grower_id' is required.", 422)
    if grower_id not in db.growers:
        raise ApiError(
            "ERR_REFERENCE_NOT_FOUND",
            "grower_id %s does not resolve." % grower_id,
            404,
        )
    # Priority 11: quantity sanity.
    house_no = need_str(b, "house_no")
    capacity = need_int(b, "capacity_birds")
    if capacity <= 0:
        raise ApiError(
            "ERR_QUANTITY_INVALID", "capacity_birds must be positive.", 422
        )
    # Priority 12: uniqueness within the grower.
    check_unique(
        db.houses.values(),
        "house_no",
        house_no,
        "house_no for this grower",
        scope_field="grower_id",
        scope_value=grower_id,
    )
    rec = utils.make_record(
        {
            "grower_id": grower_id,
            "house_no": house_no,
            "capacity_birds": capacity,
            "house_status": "ACTIVE",
            "downtime_until": None,
        }
    )
    db.houses[rec["id"]] = rec
    grower = db.growers[grower_id]
    if domain.recompute_house_count(grower):
        domain.bump(grower)
    return ok(utils.pub(rec), 201)


@bp.route("/api/houses/<hid>", methods=["GET"])
@require_roles(ADMIN, GROWER, TECH, HAUL)
def get_house(hid):
    rec = get_or_404(db.houses, hid, "House")
    grower_owns_or_403(rec["grower_id"])
    return ok(utils.pub(rec))


@bp.route("/api/houses/<hid>/release-downtime", methods=["POST"])
@require_roles(TECH)
def release_downtime(hid):
    rec = get_or_404(db.houses, hid, "House")
    if rec["house_status"] != "DOWNTIME":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a DOWNTIME house can be released from downtime (current: %s)."
            % rec["house_status"],
            409,
        )
    if rec["downtime_until"] is not None and not utils.logical_after(rec["downtime_until"]):
        raise ApiError(
            "ERR_INVALID_STATE",
            "House remains in downtime until %s." % rec["downtime_until"],
            409,
        )
    if domain.fail_quarantine_covers_now(hid):
        raise ApiError(
            "ERR_INVALID_STATE",
            "A FAIL audit quarantine window still covers the current date.",
            409,
        )
    rec["house_status"] = "ACTIVE"
    rec["downtime_until"] = None
    domain.bump(rec)
    grower = db.growers.get(rec["grower_id"])
    if grower is not None and domain.recompute_house_count(grower):
        domain.bump(grower)
    return ok(utils.pub(rec))


@bp.route("/api/houses/<hid>/release-quarantine", methods=["POST"])
@require_roles(TECH)
def release_quarantine(hid):
    rec = get_or_404(db.houses, hid, "House")
    if rec["house_status"] != "QUARANTINED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a QUARANTINED house can be released from quarantine (current: %s)."
            % rec["house_status"],
            409,
        )
    if not domain.pass_since_fail_exists(hid):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Release requires a PASS audit dated on or after the quarantine-triggering FAIL audit.",
            409,
        )
    rec["house_status"] = "ACTIVE"
    rec["downtime_until"] = None
    domain.bump(rec)
    grower = db.growers.get(rec["grower_id"])
    if grower is not None and domain.recompute_house_count(grower):
        domain.bump(grower)
    return ok(utils.pub(rec))


@bp.route("/api/houses/<hid>/audits", methods=["POST"])
@require_roles(TECH)
def create_audit(hid):
    house = get_or_404(db.houses, hid, "House")
    b = body()
    audit_date = need_date(b, "audit_date")
    result = need_enum(b, "result", domain.AUDIT_RESULTS)
    quarantine_days = b.get("quarantine_days", 0)
    if not utils.is_int(quarantine_days) or quarantine_days < 0:
        raise ApiError(
            "ERR_QUANTITY_INVALID", "quarantine_days must be an integer >= 0.", 422
        )
    if result == "FAIL" and quarantine_days < 7:
        raise ApiError(
            "ERR_QUANTITY_INVALID",
            "quarantine_days must be at least 7 when result is FAIL.",
            422,
        )
    rec = utils.make_record(
        {
            "house_id": hid,
            "audit_date": audit_date,
            "result": result,
            "quarantine_days": quarantine_days,
        }
    )
    db.audits[rec["id"]] = rec
    if result == "FAIL":
        domain.apply_audit_fail(house, rec)
    return ok(utils.pub(rec), 201)


@bp.route("/api/houses/<hid>/audits", methods=["GET"])
@require_roles(ADMIN, TECH, GROWER)
def list_audits(hid):
    house = get_or_404(db.houses, hid, "House")
    grower_owns_or_403(house["grower_id"])
    rows = [a for a in db.audits.values() if a["house_id"] == hid]
    return list_response(rows)


@bp.route("/api/houses/<hid>/flocks", methods=["GET"])
@require_roles(ADMIN, GROWER, TECH, HAUL, ANALYST)
def list_house_flocks(hid):
    house = get_or_404(db.houses, hid, "House")
    grower_owns_or_403(house["grower_id"])
    rows = [f for f in db.flocks.values() if f["house_id"] == hid]
    return list_response(rows, {"status": request.args.get("status")})
