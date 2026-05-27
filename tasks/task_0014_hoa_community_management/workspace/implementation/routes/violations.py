"""Violation endpoints (create, list, fetch, contest/uphold/dismiss/pay-fine)."""
from __future__ import annotations

import datetime

from flask import Blueprint, g, request

import db
import recompute
from errors import ERR_INVALID_STATE, ERR_UNAUTHORIZED, raise_err
from middleware import auth_required
from response import list_success, success
from .helpers import (
    fetch_or_404,
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    require_str,
)


bp = Blueprint("violations", __name__)

CATEGORIES = {"LANDSCAPING", "APPEARANCE", "NOISE", "PARKING"}

# tier 1: 10000, tier 2: 25000, tier 3: 50000, tier 4+: 100000
TIER_SCHEDULE = {1: 10000, 2: 25000, 3: 50000}
TIER_CAP_CENTS = 100000


def _public_status(v: dict) -> str:
    """Compliance-rollup status (ACTIVE) is the internal marker; the public
    lifecycle stays as UPHELD when the violation is in ACTIVE.

    Per PRD §3.5: 'upholding moves the violation to the UPHELD lifecycle
    state and additionally promotes its compliance-rollup status to ACTIVE'.
    We track these as the same stored `status` field, but for fetch/list
    responses we report whatever is stored. The scaffold's enum includes
    both UPHELD and ACTIVE; ACTIVE is the value we record after upholding
    because the compliance rollup looks for it.
    """
    return v["status"]


def _serialize(v: dict) -> dict:
    return {
        "id": v["id"],
        "property_id": v["property_id"],
        "category": v["category"],
        "tier": int(v["tier"]),
        "fine_cents": int(v["fine_cents"]),
        "status": _public_status(v),
        "opened_at": v["opened_at"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def _compute_tier_and_fine(property_id: str, category: str) -> tuple[int, int]:
    now = db.get_current_utc()
    window_start = now - datetime.timedelta(days=365)
    prior = 0
    for v in db.violations.values():
        if v["property_id"] != property_id:
            continue
        if v["category"] != category:
            continue
        opened = db.parse_iso(v["opened_at"])
        if opened < window_start:
            continue
        # Include OPEN, CONTESTED, UPHELD/ACTIVE, PAID; exclude DISMISSED
        if v["status"] in {"OPEN", "CONTESTED", "UPHELD", "ACTIVE", "PAID"}:
            prior += 1
    tier = prior + 1
    fine = TIER_SCHEDULE.get(tier, TIER_CAP_CENTS)
    return tier, fine


def _require_owner_of_property(prop: dict):
    """HomeOwner ownership precondition: X-User-ID == Property.owner_id."""
    if g.user_id != prop["owner_id"]:
        raise_err(ERR_UNAUTHORIZED,
                  "Caller does not own the target property")


@bp.route("/hoa/violations", methods=["POST"])
@auth_required({"BoardSecretary"})
def create_violation():
    body = get_json_body()
    property_id = require_str(body, "property_id")
    category = require_enum(body, "category", CATEGORIES)

    prop = fetch_or_404(db.properties, property_id, "Property")
    tier, fine = _compute_tier_and_fine(property_id, category)

    now_s = db.iso_now()
    record = {
        **db.make_common_fields(),
        "property_id": property_id,
        "category": category,
        "tier": tier,
        "fine_cents": fine,
        "status": "OPEN",
        "opened_at": now_s,
    }
    db.violations[record["id"]] = record
    # Recompute property's compliance posture
    recompute.recompute_property_compliance_posture(prop)
    return success(_serialize(record), status=201)


@bp.route("/hoa/violations/<vid>", methods=["GET"])
@auth_required({"PlatformAdmin", "BoardPresident", "BoardSecretary",
                "ACCMember", "HomeOwner"})
def fetch_violation(vid):
    v = fetch_or_404(db.violations, vid, "Violation")
    return success(_serialize(v))


@bp.route("/hoa/violations", methods=["GET"])
@auth_required({"PlatformAdmin", "BoardPresident", "BoardSecretary",
                "ACCMember", "HomeOwner"})
def list_violations():
    limit, offset = parse_pagination()
    property_id = request.args.get("property_id")
    category = request.args.get("category")
    status = request.args.get("status")
    rows = list(db.violations.values())
    if property_id is not None:
        rows = [r for r in rows if r["property_id"] == property_id]
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return list_success([_serialize(r) for r in page], total, limit, offset)


@bp.route("/hoa/violations/<vid>/contest", methods=["POST"])
@auth_required({"HomeOwner"})
def contest_violation(vid):
    v = fetch_or_404(db.violations, vid, "Violation")
    prop = fetch_or_404(db.properties, v["property_id"], "Property")
    if v["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE,
                  f"Violation must be OPEN to contest (currently {v['status']})")
    opened = db.parse_iso(v["opened_at"])
    now = db.get_current_utc()
    if now > opened + datetime.timedelta(days=30):
        raise_err(ERR_INVALID_STATE,
                  "Contest window has expired (30 days from opened_at)")
    _require_owner_of_property(prop)
    v["status"] = "CONTESTED"
    db.bump(v)
    return success(_serialize(v))


@bp.route("/hoa/violations/<vid>/uphold", methods=["POST"])
@auth_required({"BoardSecretary"})
def uphold_violation(vid):
    v = fetch_or_404(db.violations, vid, "Violation")
    if v["status"] != "CONTESTED":
        raise_err(ERR_INVALID_STATE,
                  f"Violation must be CONTESTED to uphold (currently {v['status']})")
    # Per scaffold: side effect sets status to ACTIVE for rollup
    # (UPHELD is a sub-state of ACTIVE). We store ACTIVE.
    v["status"] = "ACTIVE"
    db.bump(v)
    prop = db.properties.get(v["property_id"])
    if prop is not None:
        recompute.recompute_property_compliance_posture(prop)
    return success(_serialize(v))


@bp.route("/hoa/violations/<vid>/dismiss", methods=["POST"])
@auth_required({"BoardSecretary"})
def dismiss_violation(vid):
    v = fetch_or_404(db.violations, vid, "Violation")
    if v["status"] != "CONTESTED":
        raise_err(ERR_INVALID_STATE,
                  f"Violation must be CONTESTED to dismiss (currently {v['status']})")
    v["status"] = "DISMISSED"
    db.bump(v)
    prop = db.properties.get(v["property_id"])
    if prop is not None:
        recompute.recompute_property_compliance_posture(prop)
    return success(_serialize(v))


@bp.route("/hoa/violations/<vid>/pay-fine", methods=["POST"])
@auth_required({"HomeOwner"})
def pay_violation_fine(vid):
    v = fetch_or_404(db.violations, vid, "Violation")
    prop = fetch_or_404(db.properties, v["property_id"], "Property")
    # Allowed from OPEN or UPHELD/ACTIVE
    if v["status"] not in {"OPEN", "UPHELD", "ACTIVE"}:
        raise_err(ERR_INVALID_STATE,
                  f"Violation must be OPEN or UPHELD to pay-fine "
                  f"(currently {v['status']})")
    _require_owner_of_property(prop)
    v["status"] = "PAID"
    db.bump(v)
    recompute.recompute_property_compliance_posture(prop)
    return success(_serialize(v))
