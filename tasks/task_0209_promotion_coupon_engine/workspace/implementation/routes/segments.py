"""Segment + SegmentMembership endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_roles
from response import success, success_list
from services.common import (
    new_record,
    paginate,
    require_json_object,
    require_str,
    serialize,
    sort_by_created,
    touch,
)

bp = Blueprint("segments", __name__)


def recompute_member_count(segment):
    count = sum(
        1
        for m in db.segment_memberships.values()
        if m["segment_id"] == segment["id"] and m["status"] == "ACTIVE"
    )
    if segment["member_count"] != count:
        segment["member_count"] = count
        touch(segment)


@bp.post("/segments")
@require_roles("MerchantAdmin")
def create_segment():
    with db.lock:
        body = require_json_object(request.get_json(silent=True))
        code = require_str(body, "code")
        name = require_str(body, "name")
        for s in db.segments.values():
            if s["code"].lower() == code.lower():
                raise err("ERR_DUPLICATE", "Segment code already exists")
        rec = new_record({"code": code, "name": name, "member_count": 0})
        db.segments[rec["id"]] = rec
        return success(serialize(rec), 201)


@bp.get("/segments/<segment_id>")
@require_roles("MerchantAdmin", "Shopper")
def get_segment(segment_id):
    with db.lock:
        s = db.segments.get(segment_id)
        if not s:
            raise err("ERR_NOT_FOUND", "Segment not found")
        return success(serialize(s), 200)


@bp.post("/segments/<segment_id>/members")
@require_roles("MerchantAdmin")
def add_member(segment_id):
    with db.lock:
        segment = db.segments.get(segment_id)
        if not segment:
            raise err("ERR_NOT_FOUND", "Segment not found")
        body = require_json_object(request.get_json(silent=True))
        customer_id = require_str(body, "customer_id")
        # FK existence (priority 4).
        if customer_id not in db.customers:
            raise err("ERR_FK_NOT_FOUND", "customer_id does not reference a customer")
        # Duplicate ACTIVE membership for (customer_id, segment_id) (priority 6).
        for m in db.segment_memberships.values():
            if (
                m["customer_id"] == customer_id
                and m["segment_id"] == segment_id
                and m["status"] == "ACTIVE"
            ):
                raise err("ERR_DUPLICATE", "Customer already an active member")
        rec = new_record(
            {
                "customer_id": customer_id,
                "segment_id": segment_id,
                "status": "ACTIVE",
            }
        )
        db.segment_memberships[rec["id"]] = rec
        recompute_member_count(segment)
        return success(serialize(rec), 201)


@bp.get("/segments/<segment_id>/members")
@require_roles("MerchantAdmin")
def list_segment_members(segment_id):
    with db.lock:
        segment = db.segments.get(segment_id)
        if not segment:
            raise err("ERR_NOT_FOUND", "Segment not found")
        limit, offset = paginate(request.args)
        status = request.args.get("status")
        items = [
            m
            for m in db.segment_memberships.values()
            if m["segment_id"] == segment_id
        ]
        if status is not None:
            items = [m for m in items if m["status"] == status]
        items = sort_by_created(items)
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([serialize(m) for m in page], limit, offset, total)


@bp.delete("/segments/<segment_id>/members/<membership_id>")
@require_roles("MerchantAdmin")
def revoke_member(segment_id, membership_id):
    with db.lock:
        segment = db.segments.get(segment_id)
        if not segment:
            raise err("ERR_NOT_FOUND", "Segment not found")
        m = db.segment_memberships.get(membership_id)
        if not m or m["segment_id"] != segment_id:
            raise err("ERR_NOT_FOUND", "Membership not found")
        if m["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Membership is not ACTIVE")
        m["status"] = "REVOKED"
        touch(m)
        recompute_member_count(segment)
        return success(serialize(m), 200)


@bp.get("/segment-memberships/<membership_id>")
@require_roles("MerchantAdmin", "Shopper")
def get_membership(membership_id):
    with db.lock:
        m = db.segment_memberships.get(membership_id)
        if not m:
            raise err("ERR_NOT_FOUND", "Membership not found")
        return success(serialize(m), 200)


@bp.get("/segment-memberships")
@require_roles("MerchantAdmin")
def list_memberships():
    with db.lock:
        limit, offset = paginate(request.args)
        customer_id = request.args.get("customer_id")
        segment_id = request.args.get("segment_id")
        status = request.args.get("status")
        items = list(db.segment_memberships.values())
        if customer_id is not None:
            items = [m for m in items if m["customer_id"] == customer_id]
        if segment_id is not None:
            items = [m for m in items if m["segment_id"] == segment_id]
        if status is not None:
            items = [m for m in items if m["status"] == status]
        items = sort_by_created(items)
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([serialize(m) for m in page], limit, offset, total)
