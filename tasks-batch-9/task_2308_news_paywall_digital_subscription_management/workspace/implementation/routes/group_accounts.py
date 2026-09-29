"""Institutional accounts and seat concurrency (PRD 3.9)."""
from flask import Blueprint, request

import config
import lookup
import middleware
import serializers
import validation as v
from clock import clock, parse_date
from db import by_seq, db, new_entity
from errors import fail
from middleware import auth
from response import listing, mark_created, object_response
from services import seats as seats_service
from services.derive import funding_subscription_live, group_seats

bp = Blueprint("group_accounts", __name__)


@bp.post("/group-accounts")
@auth(config.ROLE_OPS)
def create_group_account():
    data = v.body()
    name = v.get_string(data, "name", required=True, min_len=1, max_len=160)
    admin_email = v.get_string(data, "admin_email", required=True, min_len=1, max_len=200)
    allowed_email_domain = v.get_string(
        data, "allowed_email_domain", required=True, min_len=3, max_len=80
    )
    seat_capacity = v.get_int(data, "seat_capacity", required=True, minimum=1, maximum=10000)
    offer_plan_id = v.get_id(data, "offer_plan_id", required=True)

    if allowed_email_domain != allowed_email_domain.lower():
        fail("ERR_INVALID_REQUEST", "Field 'allowed_email_domain' must be a lowercase host.")

    plan = lookup.offer_plan(offer_plan_id)
    if plan["status"] != "ACTIVE":
        fail("ERR_PLAN_NOT_ACTIVE")
    if plan["bundle_type"] != "INSTITUTIONAL_SEAT" or plan["per_seat_price_cents"] < 1:
        fail("ERR_PLAN_NOT_INSTITUTIONAL")

    group = new_entity()
    group.update(
        {
            "name": name,
            "admin_email": admin_email,
            "allowed_email_domain": allowed_email_domain,
            "seat_capacity": seat_capacity,
            "offer_plan_id": offer_plan_id,
            "status": "ACTIVE",
            "seats_assigned_count": 0,
            "seats_available_count": seat_capacity,
        }
    )
    db.group_accounts[group["id"]] = group
    mark_created(group)
    return object_response(serializers.group_account(group), 201)


@bp.post("/group-accounts/<group_id>/seats")
@auth(config.ROLE_GROUP_ADMIN)
def invite_seat(group_id):
    middleware.guard_group_account_path(group_id)
    data = v.body()
    reader_id = v.get_id(data, "reader_id", required=True)
    starts_on = v.get_date(data, "starts_on", required=True)
    expected_version = v.get_int(data, "expected_group_account_version", required=True)
    ends_on = v.get_date(data, "ends_on")

    group = lookup.group_account(group_id)
    lookup.reader(reader_id)
    if expected_version != group["version"]:
        fail("ERR_STALE_GROUP_ACCOUNT_VERSION")
    if funding_subscription_live(group["id"]) is None:
        fail("ERR_GROUP_SUBSCRIPTION_NOT_ACTIVE")

    starts_iso = starts_on.isoformat()
    ends_iso = ends_on.isoformat() if ends_on is not None else None
    if seats_service.interval_invalid(starts_iso, ends_iso):
        fail("ERR_SEAT_INTERVAL_INVALID")
    if seats_service.reader_duplicate(group["id"], reader_id, starts_iso, ends_iso):
        fail("ERR_SEAT_READER_DUPLICATE")
    if seats_service.capacity_exceeded(group, starts_iso, ends_iso):
        fail("ERR_SEAT_CAPACITY_EXCEEDED")

    seat = seats_service.invite(group, reader_id, starts_iso, ends_iso)
    return object_response(serializers.seat(seat), 201)


@bp.post("/seats/<seat_id>/activate")
@auth(config.ROLE_READER)
def activate_seat(seat_id):
    middleware.guard_seat(seat_id)
    seat = lookup.seat(seat_id)
    if seat["status"] != "INVITED":
        fail("ERR_SEAT_NOT_INVITED")
    if clock.date() > parse_date(seat["invite_expires_on"]):
        fail("ERR_SEAT_INVITE_EXPIRED")

    group = db.group_accounts.get(seat["group_account_id"])
    reader = db.readers.get(seat["reader_id"])
    if group is None or reader is None or not seats_service.domain_matches(reader, group):
        fail("ERR_SEAT_DOMAIN_MISMATCH")
    if funding_subscription_live(group["id"]) is None:
        fail("ERR_GROUP_SUBSCRIPTION_NOT_ACTIVE")

    seats_service.claim(seat, group, reader)
    return object_response(serializers.seat(seat))


@bp.post("/seats/<seat_id>/reclaim")
@auth(config.ROLE_GROUP_ADMIN)
def reclaim_seat(seat_id):
    middleware.guard_seat(seat_id)
    seat = lookup.seat(seat_id)
    if seat["status"] not in config.SEAT_OCCUPYING_STATUSES:
        fail("ERR_SEAT_NOT_INVITED")
    group = db.group_accounts.get(seat["group_account_id"])
    seats_service.reclaim(seat, group)
    return object_response(serializers.seat(seat))


@bp.get("/group-accounts")
@auth(config.ROLE_OPS, config.ROLE_GROUP_ADMIN, config.ROLE_REVENUE)
def list_group_accounts():
    rows = by_seq(list(db.group_accounts.values()))
    if middleware.is_group_admin():
        rows = [r for r in rows if r["id"] == middleware.user_id()]
    for param in ("offer_plan_id", "status"):
        value = request.args.get(param)
        if value:
            rows = [r for r in rows if r[param] == value]
    return listing(rows, serializers.group_account)


@bp.get("/group-accounts/<group_id>")
@auth(config.ROLE_OPS, config.ROLE_GROUP_ADMIN)
def read_group_account(group_id):
    middleware.guard_group_account_path(group_id)
    return object_response(serializers.group_account(lookup.group_account(group_id)))


@bp.get("/seats")
@auth(config.ROLE_OPS, config.ROLE_GROUP_ADMIN, config.ROLE_READER)
def list_seats():
    group_account_id = request.args.get("group_account_id")
    reader_id = request.args.get("reader_id")
    if middleware.is_group_admin():
        middleware.guard_filter("group_account_id")
        group_account_id = middleware.user_id()
    if middleware.is_reader():
        middleware.guard_filter("reader_id")
        reader_id = middleware.user_id()

    rows = sorted(
        db.seats.values(), key=lambda s: (parse_date(s["starts_on"]), s["_seq"])
    )
    if group_account_id:
        rows = [r for r in rows if r["group_account_id"] == group_account_id]
    if reader_id:
        rows = [r for r in rows if r["reader_id"] == reader_id]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return listing(rows, serializers.seat)


@bp.get("/seats/<seat_id>")
@auth(config.ROLE_OPS, config.ROLE_GROUP_ADMIN, config.ROLE_READER)
def read_seat(seat_id):
    middleware.guard_seat(seat_id)
    return object_response(serializers.seat(lookup.seat(seat_id)))


def _group_seat_rows(group_id):
    return group_seats(group_id)
