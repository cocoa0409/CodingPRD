"""Membership transfer submission and decision (PRD 3.8)."""

from datetime import timedelta

from flask import Blueprint, request

import auth
import calc
import clock
import engine
import guards
import response
import serializers
import store
import validators as v
from auth import CLUB_ADMIN, MEMBER
from errors import fail

bp = Blueprint("transfers", __name__)

TRANSFER_TYPES = ("GIFT", "RESALE", "ESTATE")


@bp.post("/transfer-requests")
def submit_transfer():
    actor = auth.authorize(MEMBER)
    data = v.body()
    raw_membership = v.raw_id(data, "membership_id")
    auth.require_member_owner(actor, guards.find("memberships", raw_membership))
    guards.maybe("memberships", raw_membership)
    guards.maybe("members", v.raw_id(data, "to_member_id"))
    membership_id = v.req_id(data, "membership_id")
    to_member_id = v.req_id(data, "to_member_id")
    transfer_type = v.req_enum(data, "transfer_type", TRANSFER_TYPES)
    expected_version = v.req_int(data, "expected_membership_version", minimum=0)
    sale_price = v.opt_int(data, "sale_price_cents", default=0, minimum=0)
    if transfer_type != "RESALE" and sale_price:
        fail("ERR_INVALID_REQUEST",
             "sale_price_cents is only accepted on a RESALE transfer")

    membership = guards.fetch("memberships", membership_id)
    guards.fetch("members", to_member_id)
    tier = engine.tier_of(membership)
    if tier is None:
        fail("ERR_TIER_NOT_FOUND", "the membership's tier no longer exists")

    if expected_version != membership.get("version"):
        fail("ERR_STALE_MEMBERSHIP_VERSION",
             "expected_membership_version does not match the membership version")
    if membership["membership_status"] != "ACTIVE":
        fail("ERR_MEMBERSHIP_NOT_ACTIVE", "membership is not ACTIVE")
    if transfer_type == "RESALE":
        if not tier["resale_allowed"]:
            fail("ERR_RESALE_NOT_PERMITTED", "the tier does not permit resale")
        purchased = clock.parse_instant(membership["purchased_at"]).date()
        if (clock.today() - purchased).days < calc.RESALE_HOLD_DAYS:
            fail("ERR_RESALE_HOLD_ACTIVE", "the resale hold has not yet elapsed")
    if membership["transfer_count"] >= calc.MAX_TRANSFERS_PER_CHAIN:
        fail("ERR_TRANSFER_LIMIT_REACHED", "the transfer chain limit is reached")
    for res in engine.reservations_of_membership(membership_id):
        if res["status"] in engine.OPEN_RESERVATION_STATUSES:
            fail("ERR_TRANSFER_BLOCKED_OPEN_RESERVATIONS",
                 "the membership still holds an open reservation")
    if membership["dues_status"] != "CURRENT":
        fail("ERR_DUES_NOT_CURRENT", "a transfer requires dues_status CURRENT")

    row = store.base_row()
    row.update({
        "membership_id": membership_id,
        "from_member_id": membership["member_id"],
        "to_member_id": to_member_id,
        "transfer_type": transfer_type,
        "sale_price_cents": sale_price,
        "status": "SUBMITTED",
        "transfer_fee_cents": calc.transfer_fee_total(tier["transfer_fee_cents"],
                                                     transfer_type, sale_price),
        "successor_membership_id": None,
        "decided_by_user_id": None,
        "decided_at": None,
        "rejection_reason": None,
        "_submitted_by_user_id": actor.user_id,
    })
    store.insert("transfer_requests", row)

    membership["membership_status"] = "TRANSFER_PENDING"
    store.touch(membership)
    return response.created(serializers.transfer_request(row))


@bp.get("/transfer-requests/<request_id>")
def read_transfer(request_id):
    auth.authorize(MEMBER, CLUB_ADMIN)
    row = guards.fetch("transfer_requests", request_id)
    return response.ok(serializers.transfer_request(row))


@bp.get("/transfer-requests")
def list_transfers():
    auth.authorize(CLUB_ADMIN)
    rows = store.ordered(store.all_rows("transfer_requests"))
    for field in ("membership_id", "from_member_id", "to_member_id",
                  "successor_membership_id", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r.get(field) == value]
    return response.paginate(rows, serializers.transfer_request)


def _mint_successor(source, transfer):
    stamp = clock.now_iso()
    successor = store.base_row()
    successor.update({
        "member_id": transfer["to_member_id"],
        "tier_id": source["tier_id"],
        "transferred_from_membership_id": source["id"],
        "membership_status": "ACTIVE",
        "dues_status": "CURRENT",
        "suspension_reason": None,
        "purchased_at": stamp,
        "tenure_origin_at": source["tenure_origin_at"],
        "upfront_paid_cents": 0,
        "entitlement_year_start": clock.fmt_date(clock.today()),
        "nights_used_class_a": 0,
        "nights_used_class_b": 0,
        "nights_used_class_c": 0,
        "annual_nights_used": 0,
        "dues_balance_cents": 0,
        "dues_paid_through": source.get("dues_paid_through"),
        "transfer_count": source["transfer_count"] + 1,
        "resale_eligible_at": clock.fmt_instant(
            clock.now() + timedelta(days=calc.RESALE_HOLD_DAYS)),
        "tenure_years": 0,
    })
    store.insert("memberships", successor)
    engine.recompute_tenure(successor)
    engine.issue_invoice(successor, clock.today().year)
    return successor


@bp.post("/transfer-requests/<request_id>/decision")
def decide_transfer(request_id):
    actor = auth.authorize(CLUB_ADMIN)
    transfer = guards.fetch("transfer_requests", request_id)
    data = v.body()
    decision = v.req_enum(data, "decision", ("APPROVE", "REJECT"))
    rejection_reason = v.opt_str(data, "rejection_reason")
    if transfer["status"] != "SUBMITTED":
        fail("ERR_INVALID_TRANSFER_STATE", "the transfer request is already decided")
    if actor.user_id == transfer.get("_submitted_by_user_id"):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the approver may not be the submitter of the request")

    membership = guards.fetch("memberships", transfer["membership_id"])
    if decision == "APPROVE":
        if (membership["membership_status"] != "TRANSFER_PENDING"
                or membership["dues_status"] != "CURRENT"):
            fail("ERR_DUES_NOT_CURRENT",
                 "approval requires a TRANSFER_PENDING membership with CURRENT dues")

    transfer["decided_by_user_id"] = actor.user_id
    transfer["decided_at"] = clock.now_iso()
    if decision == "REJECT":
        transfer["status"] = "REJECTED"
        transfer["rejection_reason"] = rejection_reason
        store.touch(transfer)
        membership["membership_status"] = "ACTIVE"
        store.touch(membership)
        return response.ok(serializers.transfer_request(transfer))

    transfer["status"] = "APPROVED"
    successor = _mint_successor(membership, transfer)
    transfer["successor_membership_id"] = successor["id"]
    store.touch(transfer)

    membership["membership_status"] = "TERMINATED"
    for res in store.ordered(engine.reservations_of_membership(membership["id"])):
        if res["status"] == "WAITLISTED":
            res["status"] = "EXPIRED"
            store.touch(res)
    store.touch(membership)
    return response.ok(serializers.transfer_request(transfer))
