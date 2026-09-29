"""Damage claims: intake, the bounded review cycle, adjudication and the ledger."""

from flask import Blueprint

import calc
import enums
import serializers as ser
import services as svc
import validation as v
from envelope import list_response, object_response
from errors import fail
from store import creation_order, db, new_record, touch
from web import paged, route

bp = Blueprint("claims", __name__)


def _booking_of(claim):
    return db.bookings[claim["booking_id"]]


def _require_claim_status(claim, allowed):
    if claim["status"] not in allowed:
        fail("ERR_CLAIM_STATE_INVALID",
             "DamageClaim.status %s does not permit this transition." % claim["status"])


def _require_disputed(booking):
    if booking["settlement_status"] != "DISPUTED":
        fail("ERR_BOOKING_SETTLEMENT_CLOSED",
             "The booking's settlement dimension is not DISPUTED.")


# ------------------------------------------------------------ claim intake -----
@route(bp, "/damage-claims", ["POST"], ("Owner",))
def create_claim(user_id, role):
    body = v.body()
    booking_id = v.get_str(body, "booking_id")
    cause_code = v.get_enum(body, "cause_code", enums.CAUSE_CODE)
    damage_zone = v.get_enum(body, "damage_zone", enums.ZONE)
    claimed_amount_cents = v.get_int(body, "claimed_amount_cents", 1)
    description = v.get_str(body, "description", min_len=1, max_len=500)
    booking = svc.lookup("bookings", booking_id)
    svc.require_booking_access(role, user_id, booking)
    if booking["settlement_status"] not in ("RECONCILING", "DISPUTED"):
        fail("ERR_BOOKING_SETTLEMENT_CLOSED",
             "The booking's settlement dimension accepts no claim activity.")
    pre_count, post_count, verdict = calc.photo_comparison(booking_id, damage_zone)
    if pre_count == 0 or post_count == 0:
        fail("ERR_PHOTO_BASELINE_MISSING",
             "The claimed zone needs both a PRE_TRIP and a POST_TRIP photo.")
    claim = new_record(booking_id=booking_id, cause_code=cause_code,
                       damage_zone=damage_zone,
                       claimed_amount_cents=claimed_amount_cents,
                       description=description, status="SUBMITTED",
                       comparison_verdict=verdict, pre_photo_count=pre_count,
                       post_photo_count=post_count, info_rounds_used=0,
                       gross_amount_cents=0, renter_charge_cents=0,
                       plan_paid_cents=0, owner_payout_cents=0,
                       override_amount_cents=None, override_reason=None,
                       info_request_note=None, response_note=None,
                       withdraw_reason=None)
    db.damage_claims[claim["id"]] = claim
    if booking["settlement_status"] == "RECONCILING":
        booking["settlement_status"] = "DISPUTED"
    touch(booking)
    return object_response(ser.dump("damage_claim", claim), 201)


@route(bp, "/damage-claims/<claim_id>", ["GET"],
       ("Owner", "Renter", "PlatformAdmin", "ClaimsAdjuster"))
def get_claim(user_id, role, claim_id):
    claim = svc.lookup("damage_claims", claim_id)
    return object_response(ser.dump("damage_claim", claim))


@route(bp, "/damage-claims", ["GET"],
       ("Owner", "Renter", "PlatformAdmin", "ClaimsAdjuster"))
def list_claims(user_id, role):
    limit, offset = v.pagination()
    booking_id = v.query_str("booking_id")
    status = v.query_enum("status", enums.CLAIM_STATUS)
    rows = creation_order(list(db.damage_claims.values()))
    if booking_id is not None:
        rows = [r for r in rows if r["booking_id"] == booking_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(ser.dump_all("damage_claim", paged(rows, limit, offset)),
                         limit, offset, len(rows))


# ----------------------------------------------------------- review cycle ------
@route(bp, "/damage-claims/<claim_id>/start-review", ["POST"], ("ClaimsAdjuster",))
def start_review(user_id, role, claim_id):
    v.body()
    claim = svc.lookup("damage_claims", claim_id)
    _require_claim_status(claim, ("SUBMITTED",))
    _require_disputed(_booking_of(claim))
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return object_response(ser.dump("damage_claim", claim))


@route(bp, "/damage-claims/<claim_id>/request-info", ["POST"], ("ClaimsAdjuster",))
def request_info(user_id, role, claim_id):
    body = v.body()
    info_request_note = v.get_str(body, "info_request_note", min_len=1)
    claim = svc.lookup("damage_claims", claim_id)
    _require_claim_status(claim, ("UNDER_REVIEW",))
    _require_disputed(_booking_of(claim))
    if claim["info_rounds_used"] >= calc.MAX_INFO_ROUNDS:
        fail("ERR_INFO_ROUND_LIMIT_REACHED",
             "This claim has exhausted its information rounds.")
    claim["status"] = "INFO_REQUESTED"
    claim["info_request_note"] = info_request_note
    touch(claim)
    return object_response(ser.dump("damage_claim", claim))


@route(bp, "/damage-claims/<claim_id>/respond", ["POST"], ("Owner", "Renter"))
def respond_to_info(user_id, role, claim_id):
    body = v.body()
    response_note = v.get_str(body, "response_note", min_len=1)
    claim = svc.lookup("damage_claims", claim_id)
    booking = _booking_of(claim)
    svc.require_booking_access(role, user_id, booking)
    _require_claim_status(claim, ("INFO_REQUESTED",))
    _require_disputed(booking)
    claim["info_rounds_used"] += 1
    claim["response_note"] = response_note
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    booking["info_round_count"] += 1
    touch(booking)
    return object_response(ser.dump("damage_claim", claim))


@route(bp, "/damage-claims/<claim_id>/adjudicate", ["POST"], ("ClaimsAdjuster",))
def adjudicate_claim(user_id, role, claim_id):
    body = v.body()
    override_amount_cents = v.get_int(body, "override_amount_cents", 0, required=False)
    override_reason = v.get_str(body, "override_reason", min_len=1, required=False)
    claim = svc.lookup("damage_claims", claim_id)
    booking = _booking_of(claim)
    _require_claim_status(claim, ("UNDER_REVIEW",))
    _require_disputed(booking)
    if override_amount_cents is not None and not override_reason:
        fail("ERR_ADJUDICATION_OVERRIDE_REASON_REQUIRED",
             "override_reason is required whenever override_amount_cents is supplied.")

    plan = db.protection_plans[booking["protection_plan_id"]]
    gross, renter_charge, plan_paid, owner_payout, status = calc.adjudicate_amounts(
        claim, plan, override_amount_cents)
    claim["gross_amount_cents"] = gross
    claim["renter_charge_cents"] = renter_charge
    claim["plan_paid_cents"] = plan_paid
    claim["owner_payout_cents"] = owner_payout
    claim["override_amount_cents"] = override_amount_cents
    claim["override_reason"] = override_reason
    claim["status"] = status
    touch(claim)

    if status in ("APPROVED", "PARTIAL"):
        svc.add_ledger(booking["id"], "RENTER", "DAMAGE_RENTER_CHARGE",
                       -renter_charge, "Damage charge, renter deductible share")
        svc.add_ledger(booking["id"], "PLATFORM", "DAMAGE_PLAN_PAYMENT",
                       -plan_paid, "Damage payment, protection plan share")
        svc.add_ledger(booking["id"], "OWNER", "DAMAGE_OWNER_CREDIT",
                       owner_payout, "Damage credit to owner")
        svc.recompute_owner_payout(svc.owner_of_listing(svc.listing_of(booking)))

    svc.close_claim_window(booking)
    touch(booking)
    return object_response(ser.dump("damage_claim", claim))


@route(bp, "/damage-claims/<claim_id>/withdraw", ["POST"], ("Owner",))
def withdraw_claim(user_id, role, claim_id):
    body = v.body()
    withdraw_reason = v.get_str(body, "withdraw_reason", min_len=1)
    claim = svc.lookup("damage_claims", claim_id)
    booking = _booking_of(claim)
    svc.require_booking_access(role, user_id, booking)
    _require_claim_status(claim, ("SUBMITTED", "INFO_REQUESTED"))
    claim["status"] = "WITHDRAWN"
    claim["withdraw_reason"] = withdraw_reason
    touch(claim)
    svc.close_claim_window(booking)
    touch(booking)
    return object_response(ser.dump("damage_claim", claim))


# --------------------------------------------------------------- ledger --------
@route(bp, "/ledger-entries/<entry_id>", ["GET"],
       ("Owner", "PlatformAdmin", "ClaimsAdjuster"))
def get_entry(user_id, role, entry_id):
    entry = svc.lookup("ledger_entries", entry_id)
    return object_response(ser.dump("ledger_entry", entry))


@route(bp, "/ledger-entries", ["GET"],
       ("Owner", "Renter", "PlatformAdmin", "ClaimsAdjuster"))
def list_entries(user_id, role):
    limit, offset = v.pagination()
    booking_id = v.query_str("booking_id")
    party = v.query_enum("party", enums.PARTY)
    entry_type = v.query_enum("entry_type", enums.ENTRY_TYPE)
    rows = creation_order(list(db.ledger_entries.values()))
    if booking_id is not None:
        rows = [r for r in rows if r["booking_id"] == booking_id]
    if party is not None:
        rows = [r for r in rows if r["party"] == party]
    if entry_type is not None:
        rows = [r for r in rows if r["entry_type"] == entry_type]
    return list_response(ser.dump_all("ledger_entry", paged(rows, limit, offset)),
                         limit, offset, len(rows))
