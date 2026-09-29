"""Registration endpoints: the sale, the waitlist and the cancellation cascade."""

from flask import Blueprint

import calc
import derive
import enums
import serial
import store
import validate
from auth import (CHARITY_TREASURER, COURSE_OPERATIONS, PARTICIPANT,
                  SPONSORSHIP_MANAGER, TOURNAMENT_DIRECTOR, auth)
from envelope import created, ok, paginate
from errors import fail
from lookup import outing as get_outing
from lookup import registration as get_registration
from lookup import tier as get_tier
from store import touch

bp = Blueprint("registrations", __name__)

READ_ROLES = (TOURNAMENT_DIRECTOR, SPONSORSHIP_MANAGER, CHARITY_TREASURER,
              PARTICIPANT)
LIST_ROLES = (TOURNAMENT_DIRECTOR, SPONSORSHIP_MANAGER, CHARITY_TREASURER)

CREATE_FIELDS = ("outing_id", "package_tier_id", "buyer_name", "player_count",
                 "buyer_email")


@bp.post("/outing-ops/registrations")
def create_registration():
    user_id, _role = auth((TOURNAMENT_DIRECTOR, SPONSORSHIP_MANAGER, PARTICIPANT))
    body = validate.body()
    validate.only_fields(body, CREATE_FIELDS)
    outing_id = validate.req_ref(body, "outing_id")
    tier_id = validate.req_ref(body, "package_tier_id")
    buyer_name = validate.req_str(body, "buyer_name")
    player_count = validate.req_int(body, "player_count", minimum=0, maximum=4)
    buyer_email = validate.opt_str(body, "buyer_email")
    outing = get_outing(outing_id)
    tier = get_tier(tier_id)
    if tier["outing_id"] != outing_id:
        fail("ERR_CROSS_OUTING_REFERENCE",
             "The package tier belongs to another outing.")
    if player_count > tier["player_slots"]:
        fail("ERR_INVALID_REQUEST",
             "player_count exceeds the tier's player_slots.")
    if outing["play_status"] != "OPEN":
        fail("ERR_REGISTRATION_CLOSED", "The outing's field is not open.")
    row = store.new_row("Registration", {
        "outing_id": outing_id,
        "package_tier_id": tier_id,
        "buyer_name": buyer_name,
        "buyer_email": buyer_email,
        "player_count": player_count,
        "status": "PENDING_PAYMENT",
        "amount_paid_cents": 0,
        "amount_refunded_cents": 0,
        "late_cancel_fee_cents": 0,
        "fulfillment_credit_cents": 0,
        "entitled_asset_balance": 0,
        "confirmed_at": None,
        "amendment_count": 0,
        "recorded_by_user_id": user_id,
        "receipt_issued": False,
    })
    return created(serial.dump(row))


@bp.get("/outing-ops/registrations/<row_id>")
def read_registration(row_id):
    auth(READ_ROLES)
    return ok(serial.dump(get_registration(row_id)))


@bp.get("/outing-ops/registrations")
def list_registrations():
    auth(LIST_ROLES)
    limit, offset = validate.page_params()
    outing_id = validate.q_str("outing_id")
    tier_id = validate.q_str("package_tier_id")
    status = validate.q_enum("status", enums.REGISTRATION_STATUS)
    rows = store.sorted_rows(store.registrations.values())
    if outing_id is not None:
        rows = [r for r in rows if r["outing_id"] == outing_id]
    if tier_id is not None:
        rows = [r for r in rows if r["package_tier_id"] == tier_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset, serial.dump)


@bp.post("/outing-ops/registrations/<row_id>/payment")
def record_payment(row_id):
    auth((TOURNAMENT_DIRECTOR, SPONSORSHIP_MANAGER, CHARITY_TREASURER))
    body = validate.body()
    validate.only_fields(body, ("amount_cents",))
    amount = validate.req_money(body, "amount_cents")
    reg = get_registration(row_id)
    if reg["status"] != "PENDING_PAYMENT":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A payment is only accepted on a PENDING_PAYMENT registration.")
    outing = store.outings.get(reg["outing_id"])
    if outing is None or outing["play_status"] != "OPEN":
        fail("ERR_REGISTRATION_CLOSED", "The outing's field is not open.")
    tier = derive.tier_of(reg)
    if tier is not None and tier["sold_count"] >= tier["inventory_cap"]:
        fail("ERR_TIER_INVENTORY_EXHAUSTED",
             "The package tier's inventory cap is reached.")
    price = tier["price_cents"] if tier is not None else 0
    if amount != price:
        fail("ERR_PAYMENT_AMOUNT_MISMATCH",
             "The payment must equal the tier price of %d cents." % price)
    capacity = outing["field_capacity_teams"] * calc.PLAYER_SLOTS_PER_TEAM
    reg["amount_paid_cents"] = reg["amount_paid_cents"] + amount
    if outing["confirmed_player_slots"] + reg["player_count"] <= capacity:
        reg["status"] = "CONFIRMED"
        reg["confirmed_at"] = store.now_iso()
        touch(reg)
        derive.snapshot_registration_players(reg)
        derive.rederive_entitled_balance(reg)
        derive.rederive_tier_sold_count(tier)
    else:
        reg["status"] = "WAITLISTED"
        touch(reg)
    derive.run_rollup(outing)
    return ok(serial.dump(reg))


AMENDABLE_STATES = ("CONFIRMED", "AMENDED", "CHECKED_IN")


@bp.post("/outing-ops/registrations/<row_id>/amend-tier")
def amend_tier(row_id):
    auth((SPONSORSHIP_MANAGER, TOURNAMENT_DIRECTOR))
    body = validate.body()
    validate.only_fields(body, ("package_tier_id", "expected_registration_version",
                                "amount_cents", "player_count"))
    tier_id = validate.req_ref(body, "package_tier_id")
    expected = validate.req_int(body, "expected_registration_version")
    amount = validate.opt_signed_int(body, "amount_cents", default=0)
    if amount is None:
        amount = 0
    supplied_count = validate.opt_int(body, "player_count", minimum=0, maximum=4)
    reg = get_registration(row_id)
    new_tier = get_tier(tier_id)
    if new_tier["outing_id"] != reg["outing_id"]:
        fail("ERR_CROSS_OUTING_REFERENCE",
             "The package tier belongs to another outing.")
    effective_count = reg["player_count"] if supplied_count is None else supplied_count
    if effective_count > new_tier["player_slots"]:
        fail("ERR_INVALID_REQUEST",
             "player_count exceeds the new tier's player_slots.")
    if reg["status"] not in AMENDABLE_STATES:
        fail("ERR_INVALID_STATE_TRANSITION",
             "A %s registration cannot be amended." % reg["status"])
    outing = store.outings.get(reg["outing_id"])
    if outing is None or outing["play_status"] not in ("OPEN", "FIELD_LOCKED"):
        fail("ERR_REGISTRATION_CLOSED", "The outing's field is no longer open.")
    if expected != reg["version"]:
        fail("ERR_STALE_REGISTRATION_VERSION",
             "The registration has moved to version %d." % reg["version"])
    old_tier = derive.tier_of(reg)
    if (new_tier["id"] != reg["package_tier_id"]
            and new_tier["sold_count"] + 1 > new_tier["inventory_cap"]):
        fail("ERR_TIER_INVENTORY_EXHAUSTED",
             "The new package tier's inventory cap is reached.")
    old_price = old_tier["price_cents"] if old_tier is not None else 0
    delta = new_tier["price_cents"] - old_price
    if amount != delta:
        fail("ERR_PAYMENT_AMOUNT_MISMATCH",
             "The amendment must charge the signed delta of %d cents." % delta)

    reg["package_tier_id"] = new_tier["id"]
    reg["player_count"] = effective_count
    reg["amendment_count"] = reg["amendment_count"] + 1
    if delta > 0:
        reg["amount_paid_cents"] = reg["amount_paid_cents"] + delta
    elif delta < 0:
        reg["amount_refunded_cents"] = reg["amount_refunded_cents"] - delta
    if reg["status"] == "CONFIRMED":
        reg["status"] = "AMENDED"
    touch(reg)
    if old_tier is not None:
        derive.rederive_tier_sold_count(old_tier)
    derive.rederive_tier_sold_count(new_tier)
    _release_excess_entitlements(reg, new_tier)
    derive.rederive_entitled_balance(reg)
    derive.rederive_outing_counters(outing)
    derive.run_rollup(outing)
    return ok(serial.dump(reg))


def _release_excess_entitlements(reg, tier):
    """Release the entitlement allocations the new tier no longer covers."""
    live = [a for a in derive.allocs_of_registration(reg["id"])
            if a["source"] == "PACKAGE_ENTITLEMENT" and a["status"] != "RELEASED"]
    live.sort(key=lambda a: (a["created_at"], a["_seq"]))
    allowed = tier["entitled_asset_count"]
    for alloc in live[allowed:]:
        derive.release_allocation(alloc)


@bp.post("/outing-ops/registrations/<row_id>/lifecycle")
def registration_lifecycle(row_id):
    user_id, _role = auth((TOURNAMENT_DIRECTOR, SPONSORSHIP_MANAGER,
                           COURSE_OPERATIONS))
    body = validate.body()
    validate.only_fields(body, ("action", "refund_cents"))
    action = validate.req_enum(body, "action", enums.REGISTRATION_ACTIONS)
    refund_cents = validate.opt_money(body, "refund_cents", None)
    reg = get_registration(row_id)
    outing = store.outings.get(reg["outing_id"])
    if action == "CHECK_IN":
        _check_in(reg, outing)
    elif action == "RECONFIRM":
        _reconfirm(reg)
    else:
        _cancel(reg, outing, refund_cents, user_id)
    touch(reg)
    return ok(serial.dump(reg))


def _check_in(reg, outing):
    if reg["status"] not in ("CONFIRMED", "AMENDED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "CHECK_IN is not an edge out of %s." % reg["status"])
    if outing is None or outing["play_status"] not in ("FIELD_LOCKED", "IN_PLAY"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "The outing's field has not been locked for play.")
    reg["status"] = "CHECKED_IN"
    for player in derive.players_of_registration(reg["id"]):
        player["checked_in"] = True
        touch(player)
    derive.rederive_outing_counters(outing)


def _reconfirm(reg):
    if reg["status"] != "AMENDED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "RECONFIRM is not an edge out of %s." % reg["status"])
    tier = derive.tier_of(reg)
    price = tier["price_cents"] if tier is not None else 0
    if reg["amount_paid_cents"] - reg["amount_refunded_cents"] != price:
        fail("ERR_PAYMENT_AMOUNT_MISMATCH",
             "The net paid must equal the held tier price of %d cents." % price)
    reg["status"] = "CONFIRMED"


def _cancel(reg, outing, refund_cents, user_id):
    status = reg["status"]
    if status == "PENDING_PAYMENT":
        if reg["amount_paid_cents"] != 0:
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A paid registration cannot be cancelled from PENDING_PAYMENT.")
        reg["status"] = "CANCELLED"
        return
    if status not in ("CONFIRMED", "AMENDED", "CHECKED_IN", "WAITLISTED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "CANCEL is not an edge out of %s." % status)
    if outing is None or outing["finance_status"] != "COLLECTING":
        fail("ERR_INVALID_STATE_TRANSITION",
             "The outing's finances have left COLLECTING.")
    if status == "WAITLISTED":
        _cancel_waitlisted(reg, outing, refund_cents)
        return
    _cancel_revenue(reg, outing, refund_cents, user_id)


def _cancel_waitlisted(reg, outing, refund_cents):
    paid = reg["amount_paid_cents"]
    refund = paid if refund_cents is None else refund_cents
    if reg["amount_refunded_cents"] + refund > paid:
        fail("ERR_REFUND_EXCEEDS_PAYMENT",
             "The refund exceeds what was paid.")
    reg["status"] = "CANCELLED"
    reg["amount_refunded_cents"] = reg["amount_refunded_cents"] + refund
    if refund > 0:
        reg["status"] = "REFUNDED"
    derive.rederive_outing_counters(outing)


def _cancel_revenue(reg, outing, refund_cents, user_id):
    contract = derive.contract_of(outing["id"])
    notice_days = contract["cancellation_notice_days"] if contract else 0
    paid = reg["amount_paid_cents"]

    # step 1 - the late cancellation test
    late = False
    if outing["scheduled_date"] is not None:
        deadline = store.parse_ts(outing["scheduled_date"]) - store.days(notice_days)
        late = store.now_dt() >= deadline
    fee = calc.pct_of(calc.LATE_CANCEL_FEE_PCT, paid) if late else 0
    default_refund = paid - fee
    refund = default_refund if refund_cents is None else refund_cents

    # step 2 - the refund, its ceiling and the auto advance
    if reg["amount_refunded_cents"] + refund > paid - fee:
        fail("ERR_REFUND_EXCEEDS_PAYMENT",
             "The refund exceeds the payment net of the late cancellation fee.")
    freed_slots = reg["player_count"]
    reg["late_cancel_fee_cents"] = fee
    reg["status"] = "CANCELLED"
    reg["amount_refunded_cents"] = reg["amount_refunded_cents"] + refund
    if refund > 0:
        reg["status"] = "REFUNDED"
    touch(reg)

    # steps 3, 4 and 5 - the allocations, their assets and the outing counter
    for alloc in derive.allocs_of_registration(reg["id"]):
        if alloc["status"] != "RELEASED":
            derive.release_allocation(alloc)

    # step 6 - the players and the teams they leave behind
    orphaned = []
    for player in derive.players_of_registration(reg["id"]):
        team_id = player["team_id"]
        player["team_id"] = None
        player["checked_in"] = False
        touch(player)
        if team_id is not None and team_id not in orphaned:
            orphaned.append(team_id)
    for team_id in orphaned:
        team = store.teams.get(team_id)
        if team is not None:
            derive.rederive_team_player_count(team)

    derive.rederive_tier_sold_count(derive.tier_of(reg))
    derive.rederive_outing_counters(outing)

    # step 7 - the waitlist offer
    derive.promote_from_waitlist(outing, freed_slots)

    # step 8 - the automatic receipt reversal
    original = derive.live_forward_receipt(outing["id"], registration_id=reg["id"])
    if original is not None:
        derive.append_reversal(original, user_id)

    # step 9 - the finance rollup
    derive.run_rollup(outing)
