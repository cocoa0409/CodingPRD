"""Member and ComplianceAttestation endpoints."""
from flask import Blueprint, request

import db as _db
from db import db, new_entity, touch
from errors import (ApiError, duplicate, invalid_request, invalid_state,
                    not_found)
from helpers import (body, get_or_404, paginate, pagination_params, public,
                     req_date, req_enum, req_int, req_str)
from middleware import require, require_member_ownership
from response import success
from services import refresh_tier

bp = Blueprint("members", __name__)

ATT_VIEW = ["PlatformAdmin", "ShopStaff", "ComplianceOfficer", "Member"]


@bp.post("/members")
def create_member():
    require(["Anonymous", "PlatformAdmin", "ShopStaff"])
    data = body()
    email = req_str(data, "email")
    if "@" not in email:
        raise invalid_request("Field 'email' must be a valid email address")
    full_name = req_str(data, "full_name")
    dob = req_date(data, "date_of_birth")
    home_state = req_str(data, "home_state_code")
    lowered = email.lower()
    for m in db["members"].values():
        if m["email"].lower() == lowered:
            raise duplicate("email already exists")
    ent = new_entity({
        "email": email,
        "full_name": full_name,
        "date_of_birth": dob,
        "home_state_code": home_state,
        "age_attestation_status": "UNVERIFIED",
        "loyalty_tier": "BRONZE",
        "loyalty_points_balance": 0,
        "loyalty_points_lifetime": 0,
        "wallet_credit_cents": 0,
    })
    db["members"][ent["id"]] = ent
    return success(public(ent), status=201)


@bp.get("/members")
def list_members():
    require(["PlatformAdmin", "ShopStaff", "ComplianceOfficer"])
    limit, offset = pagination_params()
    att = request.args.get("age_attestation_status")
    tier = request.args.get("loyalty_tier")
    items = list(db["members"].values())
    if att is not None:
        items = [m for m in items if m["age_attestation_status"] == att]
    if tier is not None:
        items = [m for m in items if m["loyalty_tier"] == tier]
    page, pg = paginate(items, limit, offset)
    return success([public(m) for m in page], response_type="array",
                   pagination=pg)


@bp.get("/members/<mid>")
def get_member(mid):
    role, uid = require(ATT_VIEW)
    ent = get_or_404(db["members"], mid)
    require_member_ownership(role, uid, mid)
    return success(public(ent))


def _member_child_list(mid, store, field, roles):
    role, uid = require(roles)
    get_or_404(db["members"], mid)
    require_member_ownership(role, uid, mid)
    limit, offset = pagination_params()
    items = [e for e in db[store].values() if e.get(field) == mid]
    page, pg = paginate(items, limit, offset)
    return success([public(e) for e in page], response_type="array",
                   pagination=pg)


@bp.get("/members/<mid>/orders")
def member_orders(mid):
    return _member_child_list(mid, "orders", "member_id",
                              ["PlatformAdmin", "ShopStaff", "Member"])


@bp.get("/members/<mid>/club-subscriptions")
def member_subscriptions(mid):
    return _member_child_list(mid, "club_subscriptions", "member_id",
                              ["PlatformAdmin", "ShopStaff", "Member"])


@bp.get("/members/<mid>/special-orders")
def member_special_orders(mid):
    return _member_child_list(mid, "special_orders", "member_id",
                              ["PlatformAdmin", "ShopStaff", "Member"])


@bp.get("/members/<mid>/attestations")
def member_attestations(mid):
    return _member_child_list(mid, "attestations", "member_id", ATT_VIEW)


@bp.get("/members/<mid>/tasting-events")
def member_tasting_events(mid):
    return _member_child_list(mid, "tasting_events", "host_member_id",
                              ["PlatformAdmin", "ShopStaff", "Member"])


@bp.get("/members/<mid>/tasting-seats")
def member_tasting_seats(mid):
    return _member_child_list(mid, "tasting_seats", "member_id",
                              ["PlatformAdmin", "ShopStaff", "Member"])


@bp.post("/members/<mid>/wallet/adjustments")
def wallet_adjust(mid):
    require(["PlatformAdmin", "ShopStaff"])
    ent = get_or_404(db["members"], mid)
    data = body()
    delta = req_int(data, "delta_cents")
    req_str(data, "reason")
    ent["wallet_credit_cents"] = max(0, ent["wallet_credit_cents"] + delta)
    touch(ent)
    return success(public(ent), status=201)


# ---------------------------------------------------------------------------
# Attestations
# ---------------------------------------------------------------------------

@bp.post("/members/<mid>/attestations")
def submit_attestation(mid):
    require(["ShopStaff", "ComplianceOfficer"])
    member = get_or_404(db["members"], mid)
    data = body()
    attested_by = req_str(data, "attested_by_user_id")
    outcome = req_enum(data, "outcome", {"APPROVED", "REJECTED"})
    attested_on = req_date(data, "attested_on")
    document_reference = req_str(data, "document_reference")
    if member["age_attestation_status"] not in ("UNVERIFIED", "REJECTED"):
        raise invalid_state(
            "Member must be UNVERIFIED or REJECTED to submit attestation")
    if attested_by == mid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 422,
                       "attested_by_user_id must differ from member_id")
    ent = new_entity({
        "member_id": mid,
        "attested_by_user_id": attested_by,
        "outcome": outcome,
        "attested_on": attested_on,
        "document_reference": document_reference,
    })
    db["attestations"][ent["id"]] = ent
    member["age_attestation_status"] = "PENDING_REVIEW"
    touch(member)
    return success(public(ent), status=201)


def _resolve_attestation(mid, att_id):
    member = get_or_404(db["members"], mid)
    att = db["attestations"].get(att_id)
    if att is None or att["member_id"] != mid:
        raise not_found("Attestation not found for member")
    return member, att


@bp.post("/members/<mid>/attestations/<att_id>/approve")
def approve_attestation(mid, att_id):
    role, uid = require(["ComplianceOfficer"])
    member, att = _resolve_attestation(mid, att_id)
    if member["age_attestation_status"] != "PENDING_REVIEW":
        raise invalid_state("Member is not PENDING_REVIEW")
    if att["outcome"] != "APPROVED":
        raise invalid_state("Attestation outcome is not APPROVED")
    if uid == att["attested_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 422,
                       "Approving officer must differ from original attester")
    member["age_attestation_status"] = "ATTESTED"
    refresh_tier(member)
    touch(member)
    return success(public(member))


@bp.post("/members/<mid>/attestations/<att_id>/reject")
def reject_attestation(mid, att_id):
    require(["ComplianceOfficer"])
    member, att = _resolve_attestation(mid, att_id)
    if member["age_attestation_status"] != "PENDING_REVIEW":
        raise invalid_state("Member is not PENDING_REVIEW")
    member["age_attestation_status"] = "REJECTED"
    touch(member)
    return success(public(member))


@bp.post("/members/<mid>/attestations/revoke")
def revoke_attestation(mid):
    require(["ComplianceOfficer"])
    member = get_or_404(db["members"], mid)
    if member["age_attestation_status"] != "ATTESTED":
        raise invalid_state("Member is not ATTESTED")
    member["age_attestation_status"] = "REVOKED"
    touch(member)
    # Cascade: cancel DRAFT/PICKING orders containing ADULT_ONLY_REQUIRED SKUs
    from services import (order_lines, restore_allocation, recompute_on_hand)
    for order in db["orders"].values():
        if order["member_id"] != mid:
            continue
        if order["fulfillment_status"] not in ("DRAFT", "PICKING"):
            continue
        has_adult = False
        for line in order_lines(order["id"]):
            sku = db["skus"].get(line["sku_id"])
            if sku is not None and sku["age_neutral_class"] == "ADULT_ONLY_REQUIRED":
                has_adult = True
                break
        if not has_adult:
            continue
        affected = set()
        if order["fulfillment_status"] == "PICKING":
            for line in order_lines(order["id"]):
                restore_allocation(line.get("lot_allocation"))
                line["lot_allocation"] = []
                touch(line)
                affected.add(line["sku_id"])
            order["payment_status"] = "VOIDED"
            member["loyalty_points_balance"] += order.get(
                "loyalty_points_redeemed") or 0
            touch(member)
        order["fulfillment_status"] = "CANCELLED"
        touch(order)
        for sku_id in affected:
            recompute_on_hand(sku_id)
    return success(public(member))
