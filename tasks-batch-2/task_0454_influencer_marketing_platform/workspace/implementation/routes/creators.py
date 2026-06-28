from flask import Blueprint, request

from db import db, base_fields, bump, now_iso
from middleware import get_auth, require_role
from validators import (get_body, req_str, req_enum, opt_enum, opt_bool, req_int,
                        req_number)
from errors import err
from response import success
from pagination import paginate
import serializers as S
import services as svc
import derive
import calculations as calc

bp = Blueprint("creators", __name__)

PLATFORMS = {"INSTAGRAM", "TIKTOK", "YOUTUBE"}
PAYOUT_METHODS = {"ACH", "PAYPAL"}


@bp.route("/creators", methods=["POST"])
def create_creator():
    _, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    handle = req_str(body, "handle", allow_empty=False)
    primary_platform = req_enum(body, "primary_platform", PLATFORMS)
    payout_method = opt_enum(body, "payout_method", PAYOUT_METHODS, default="ACH")
    tax_id_on_file = opt_bool(body, "tax_id_on_file", default=False)

    # uniqueness (priority 6) after body shape (priority 5)
    for c in db.creators.values():
        if c["handle"] == handle:
            raise err("ERR_DUPLICATE_VALUE", "Creator handle already exists")

    rec = base_fields()
    rec.update({
        "handle": handle,
        "primary_platform": primary_platform,
        "payout_method": payout_method,
        "tax_id_on_file": tax_id_on_file,
        "discovery_status": "NEW",
        "brand_safety_status": "CLEAR",
        "ytd_paid_cents": 0,
    })
    db.creators[rec["id"]] = rec
    return success(S.creator_view(rec), status=201)


@bp.route("/creators/<creator_id>", methods=["GET"])
def get_creator(creator_id):
    _, role = get_auth()
    require_role(role, {"PlatformAdmin", "Brand", "ComplianceOfficer", "Creator"})
    c = svc.get_creator(creator_id)
    derive.recompute_discovery_status(c)
    derive.recompute_brand_safety_status(c)
    derive.recompute_creator_ytd(c)
    return success(S.creator_view(c), status=200)


@bp.route("/creators/<creator_id>", methods=["PATCH"])
def patch_creator(creator_id):
    user_id, role = get_auth()
    require_role(role, {"PlatformAdmin", "Creator"})
    # ownership (PRD 2.1): a Creator may only patch itself; PlatformAdmin any.
    if role == "Creator" and user_id != creator_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Creator may only update itself")
    c = svc.get_creator(creator_id)
    body = get_body()
    expected = req_int(body, "expected_creator_version")

    # OCC guard (PRD 2.9). The error catalog has no dedicated code for the creator
    # PATCH version mismatch (the contested-write OCC codes are offer/contract),
    # so a stale expected_creator_version surfaces as ERR_INVALID_REQUEST (422).
    if expected != c["version"]:
        raise err("ERR_INVALID_REQUEST", "expected_creator_version does not match")

    if "tax_id_on_file" in body and body["tax_id_on_file"] is not None:
        v = body["tax_id_on_file"]
        if not isinstance(v, bool):
            raise err("ERR_INVALID_REQUEST", "tax_id_on_file must be a boolean")
        c["tax_id_on_file"] = v
    if "payout_method" in body and body["payout_method"] is not None:
        v = body["payout_method"]
        if v not in PAYOUT_METHODS:
            raise err("ERR_INVALID_REQUEST", "payout_method must be one of %s" % sorted(PAYOUT_METHODS))
        c["payout_method"] = v

    bump(c)
    derive.recompute_discovery_status(c)
    derive.recompute_brand_safety_status(c)
    derive.recompute_creator_ytd(c)
    return success(S.creator_view(c), status=200)


@bp.route("/creators", methods=["GET"])
def list_creators():
    _, role = get_auth()
    require_role(role, {"PlatformAdmin", "Brand", "ComplianceOfficer"})

    discovery_status = request.args.get("discovery_status")
    primary_platform = request.args.get("primary_platform")
    min_follower = request.args.get("min_follower_count")

    rows = list(db.creators.values())
    # keep computed fields fresh
    for c in rows:
        derive.recompute_discovery_status(c)
        derive.recompute_brand_safety_status(c)
        derive.recompute_creator_ytd(c)

    out = []
    min_fc = None
    if min_follower is not None:
        try:
            min_fc = int(min_follower)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "min_follower_count must be an integer")

    for c in rows:
        if discovery_status is not None and c["discovery_status"] != discovery_status:
            continue
        if primary_platform is not None and c["primary_platform"] != primary_platform:
            continue
        if min_fc is not None:
            latest = derive.latest_follower_count(c["id"])
            if latest is None or latest < min_fc:
                continue
        out.append(c)

    page, meta = paginate(out)
    return success([S.creator_view(c) for c in page], status=200, pagination=meta)


@bp.route("/creators/<creator_id>/audience-snapshots", methods=["POST"])
def create_snapshot(creator_id):
    _, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    c = svc.get_creator(creator_id)
    body = get_body()
    follower_count = req_int(body, "follower_count", minimum=0)
    avg_engagement_rate = req_number(body, "avg_engagement_rate", minimum=0, maximum=1)
    estimated_reach = req_int(body, "estimated_reach", minimum=0)
    fake_follower_pct = req_number(body, "fake_follower_pct", minimum=0, maximum=1)

    score = calc.fraud_score(avg_engagement_rate, fake_follower_pct)

    rec = base_fields(versioned=False)
    rec.update({
        "creator_id": creator_id,
        "follower_count": follower_count,
        "avg_engagement_rate": avg_engagement_rate,
        "estimated_reach": estimated_reach,
        "fake_follower_pct": fake_follower_pct,
        "fraud_score": score,
        "captured_at": now_iso(),
    })
    db.audience_snapshots[rec["id"]] = rec
    derive.recompute_discovery_status(c)
    return success(S.audience_snapshot_view(rec), status=201)


@bp.route("/creators/<creator_id>/audience-snapshots", methods=["GET"])
def list_snapshots(creator_id):
    _, role = get_auth()
    require_role(role, {"PlatformAdmin", "Brand", "ComplianceOfficer"})
    svc.get_creator(creator_id)
    rows = [s for s in db.audience_snapshots.values() if s["creator_id"] == creator_id]
    page, meta = paginate(rows)
    return success([S.audience_snapshot_view(s) for s in page], status=200, pagination=meta)


@bp.route("/creators/<creator_id>/tax-forms", methods=["GET"])
def list_creator_tax_forms(creator_id):
    _, role = get_auth()
    require_role(role, {"PlatformAdmin", "Creator", "ComplianceOfficer"})
    svc.get_creator(creator_id)
    status = request.args.get("status")
    tax_year = request.args.get("tax_year")
    ty = None
    if tax_year is not None:
        try:
            ty = int(tax_year)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "tax_year must be an integer")
    rows = [t for t in db.tax_forms.values() if t["creator_id"] == creator_id]
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    if ty is not None:
        rows = [t for t in rows if t["tax_year"] == ty]
    page, meta = paginate(rows)
    return success([S.tax_form_view(t) for t in page], status=200, pagination=meta)
