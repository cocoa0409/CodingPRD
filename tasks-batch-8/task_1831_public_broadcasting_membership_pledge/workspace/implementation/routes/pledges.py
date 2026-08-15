"""Pledges: capture, payments, decline, write-off, premium reservation/ship/waive."""

from datetime import timedelta

from flask import Blueprint, request

import db
import response
import validators as v
from errors import (
    ApiError,
    ERR_CHALLENGE_NOT_OPEN,
    ERR_CROSS_REFERENCE,
    ERR_DRIVE_NOT_OPEN,
    ERR_INSUFFICIENT_INVENTORY,
    ERR_INVALID_STATE,
    ERR_LEVEL_OR_PREMIUM_INELIGIBLE,
    ERR_NOT_FOUND,
    ERR_PAYMENT_AMOUNT,
    ERR_PREMIUM_NOT_SELECTED,
    ERR_STALE_PLEDGE_VERSION,
    ERR_WRITEOFF_WINDOW,
)
from middleware import require_roles
from services import core

bp = Blueprint("pledges", __name__)

ALL_ROLES = ("StationAdmin", "MembershipCoordinator", "PhoneVolunteer")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_pledge_or_404(pid):
    p = db.pledges.get(pid)
    if p is None:
        v.not_found(f"Pledge '{pid}' not found")
    return p


def _release_reservation(reservation):
    """Reservation HELD -> RELEASED with lot counter compensation."""
    lot = db.lots.get(reservation["lot_id"])
    reservation["status"] = "RELEASED"
    db.touch(reservation)
    if lot is not None:
        lot["reserved_qty"] -= reservation["quantity"]
        lot["available_qty"] += reservation["quantity"]
        db.touch(lot)


def _compensating_reversal(pledge, reason):
    """Shared decline/write-off compensating reversal cascade (PRD §3.9)."""
    drive = db.drives.get(pledge["drive_id"])
    if drive is not None:
        drive["pledged_cents"] -= pledge["amount_cents"]
        drive["collected_cents"] -= pledge["net_collected_cents"]
        db.touch(drive)
    if pledge.get("matching_challenge_id"):
        challenge = db.challenges.get(pledge["matching_challenge_id"])
        if challenge is not None:
            # Progress decrements; status latched (MET/EXPIRED never revert)
            core.challenge_progress_sub(challenge, pledge["amount_cents"])
    if pledge["fulfillment_status"] == "RESERVED":
        reservation = core.active_reservation_for_pledge(pledge["id"])
        if reservation is not None and reservation["status"] == "HELD":
            _release_reservation(reservation)
    donor = db.donors.get(pledge["donor_id"])
    if donor is not None:
        core.donor_lifetime_sub(donor, pledge["net_collected_cents"])
    pledge["decline_reason"] = reason
    # net_collected recomputes to 0 path: keep as-is; status is terminal so
    # drive/donor rollups exclude the pledge entirely after reversal above.


# ---------------------------------------------------------------------------
# Pledge capture
# ---------------------------------------------------------------------------

@bp.route("/station/pledges", methods=["POST"])
def capture_pledge():
    body = v.get_json_body()
    require_roles("PhoneVolunteer")

    donor_id = v.req_str(body, "donor_id")
    membership_id = v.req_str(body, "membership_id")
    drive_id = v.req_str(body, "drive_id")
    on_air_break_id = v.opt_str(body, "on_air_break_id")
    matching_challenge_id = v.opt_str(body, "matching_challenge_id")
    channel = v.req_enum(body, "channel", {"PHONE", "WEB"})
    kind = v.req_enum(body, "kind", {"ONE_TIME", "SUSTAINER"})
    amount_cents = v.req_int(body, "amount_cents", min_val=1)
    premium_id = v.opt_str(body, "premium_id")
    premium_waived = v.opt_bool(body, "premium_waived", default=False)

    # Existence (priority 3)
    donor = db.donors.get(donor_id)
    if donor is None:
        v.not_found(f"Donor '{donor_id}' not found")
    membership = db.memberships.get(membership_id)
    if membership is None:
        v.not_found(f"Membership '{membership_id}' not found")
    drive = db.drives.get(drive_id)
    if drive is None:
        v.not_found(f"PledgeDrive '{drive_id}' not found")
    brk = None
    if on_air_break_id is not None:
        brk = db.breaks.get(on_air_break_id)
        if brk is None:
            v.not_found(f"OnAirBreak '{on_air_break_id}' not found")
    challenge = None
    if matching_challenge_id is not None:
        challenge = db.challenges.get(matching_challenge_id)
        if challenge is None:
            v.not_found(f"MatchingChallenge '{matching_challenge_id}' not found")
    premium = None
    if premium_id is not None:
        premium = db.premiums.get(premium_id)
        if premium is None:
            v.not_found(f"Premium '{premium_id}' not found")

    # State (priority 4): drive must be ON_AIR — domain-specific error
    if drive["status"] != "ON_AIR":
        raise ApiError(ERR_DRIVE_NOT_OPEN[0],
                       f"Pledge capture requires drive ON_AIR (current: {drive['status']})",
                       ERR_DRIVE_NOT_OPEN[1])

    # Cross-reference belonging (priority 8)
    if membership["donor_id"] != donor_id:
        raise ApiError(ERR_CROSS_REFERENCE[0],
                       "membership_id does not belong to donor_id",
                       ERR_CROSS_REFERENCE[1])
    if brk is not None and brk["drive_id"] != drive_id:
        raise ApiError(ERR_CROSS_REFERENCE[0],
                       "on_air_break_id does not belong to drive_id",
                       ERR_CROSS_REFERENCE[1])
    if challenge is not None and challenge["drive_id"] != drive_id:
        raise ApiError(ERR_CROSS_REFERENCE[0],
                       "matching_challenge_id does not belong to drive_id",
                       ERR_CROSS_REFERENCE[1])

    # Challenge OPEN check (priority 8.5)
    if challenge is not None and challenge["status"] != "OPEN":
        raise ApiError(ERR_CHALLENGE_NOT_OPEN[0],
                       f"Matching challenge is {challenge['status']}, not OPEN",
                       ERR_CHALLENGE_NOT_OPEN[1])

    # Level & premium eligibility (priority 9) — membership_level_for_amount
    level = core.get_level_by_code(membership["level_code"])
    if level is None:
        raise ApiError(ERR_LEVEL_OR_PREMIUM_INELIGIBLE[0],
                       f"MembershipLevel '{membership['level_code']}' not found",
                       ERR_LEVEL_OR_PREMIUM_INELIGIBLE[1])
    annualized = amount_cents * 12 if kind == "SUSTAINER" else amount_cents
    if kind == "SUSTAINER":
        level_ok = amount_cents >= level["min_monthly_sustainer_cents"]
    else:
        level_ok = annualized >= level["min_annual_cents"]
    if not level_ok:
        raise ApiError(ERR_LEVEL_OR_PREMIUM_INELIGIBLE[0],
                       "Pledge amount does not qualify for membership level",
                       ERR_LEVEL_OR_PREMIUM_INELIGIBLE[1])
    if premium is not None:
        if not premium["active"]:
            raise ApiError(ERR_LEVEL_OR_PREMIUM_INELIGIBLE[0],
                           "Premium is not active",
                           ERR_LEVEL_OR_PREMIUM_INELIGIBLE[1])
        if not level["premium_eligible"]:
            raise ApiError(ERR_LEVEL_OR_PREMIUM_INELIGIBLE[0],
                           "Membership level is not premium-eligible",
                           ERR_LEVEL_OR_PREMIUM_INELIGIBLE[1])
        premium_level = core.get_level_by_code(premium["membership_level_code"])
        if premium_level is None:
            raise ApiError(ERR_LEVEL_OR_PREMIUM_INELIGIBLE[0],
                           "Premium's membership_level_code is invalid",
                           ERR_LEVEL_OR_PREMIUM_INELIGIBLE[1])
        if core.level_rank(level) < core.level_rank(premium_level):
            raise ApiError(ERR_LEVEL_OR_PREMIUM_INELIGIBLE[0],
                           "Pledge level below premium tier",
                           ERR_LEVEL_OR_PREMIUM_INELIGIBLE[1])

    # Capture-time fulfillment status + automatic reservation if stock available
    fulfillment_status = "NO_PREMIUM"
    if premium is not None:
        if premium_waived:
            fulfillment_status = "WAIVED"
        else:
            # Try automatic reservation against FIFO-eligible lots
            candidate = None
            lots = [l for l in db.lots.values()
                    if l["premium_id"] == premium_id and l["available_qty"] >= 1]
            lots.sort(key=lambda l: (l["received_at"], l["created_at"]))
            if lots:
                candidate = lots[0]
            if candidate is not None:
                fulfillment_status = "RESERVED"
            else:
                fulfillment_status = "AWAITING_RESERVATION"
    else:
        fulfillment_status = "WAIVED" if premium_waived else "NO_PREMIUM"

    ent = db.new_entity()
    ent.update({
        "donor_id": donor_id,
        "membership_id": membership_id,
        "drive_id": drive_id,
        "on_air_break_id": on_air_break_id,
        "matching_challenge_id": matching_challenge_id,
        "channel": channel,
        "kind": kind,
        "amount_cents": amount_cents,
        "payment_status": "PLEDGED",
        "fulfillment_status": fulfillment_status,
        "premium_id": premium_id,
        "premium_waived": premium_waived,
        "net_collected_cents": 0,
        "collected_cents": 0,
        "decline_reason": None,
    })
    db.pledges[ent["id"]] = ent

    # Auto-create reservation (HELD) when premium selected, not waived, stock available
    if fulfillment_status == "RESERVED" and premium is not None:
        lots = [l for l in db.lots.values()
                if l["premium_id"] == premium_id and l["available_qty"] >= 1]
        lots.sort(key=lambda l: (l["received_at"], l["created_at"]))
        lot = lots[0]
        res = db.new_entity()
        res.update({
            "pledge_id": ent["id"],
            "premium_id": premium_id,
            "lot_id": lot["id"],
            "quantity": 1,
            "status": "HELD",
        })
        db.reservations[res["id"]] = res
        lot["reserved_qty"] += 1
        lot["available_qty"] -= 1
        db.touch(lot)

    # Drive rollup
    core.drive_pledged_add(drive, amount_cents)

    # Challenge progress + threshold (>= comparator, latched)
    if challenge is not None:
        core.challenge_progress_add(challenge, amount_cents)

    # Sustainer conversion
    if kind == "SUSTAINER":
        if not membership["sustainer"]:
            membership["sustainer"] = True
            db.touch(membership)

    return response.success_object(ent, status=201)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

@bp.route("/station/pledges/<pid>", methods=["GET"])
def get_pledge(pid):
    require_roles(*ALL_ROLES)
    ent = _get_pledge_or_404(pid)
    return response.success_object(ent)


@bp.route("/station/pledges", methods=["GET"])
def list_pledges():
    require_roles(*ALL_ROLES)
    limit, offset = v.parse_pagination(request.args)
    items = list(db.pledges.values())
    for field in ("donor_id", "drive_id", "membership_id", "matching_challenge_id",
                  "on_air_break_id", "premium_id", "payment_status", "fulfillment_status"):
        q = request.args.get(field)
        if q is not None:
            items = [p for p in items if p.get(field) == q]
    items = v.sort_created(items)
    page, total = v.paginate(items, limit, offset)
    return response.success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

@bp.route("/station/pledges/<pid>/payments", methods=["POST"])
def post_payment(pid):
    body = v.get_json_body()
    require_roles("PhoneVolunteer")
    pledge = _get_pledge_or_404(pid)

    amount_cents = v.req_int(body, "amount_cents")
    expected = body.get("expected_pledge_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        v.invalid("Field 'expected_pledge_version' is required and must be an integer")

    # State: payment on terminal pledge
    if pledge["payment_status"] not in ("PLEDGED", "PARTIAL"):
        raise ApiError(ERR_INVALID_STATE[0],
                       f"Pledge payment_status is {pledge['payment_status']} (terminal)",
                       ERR_INVALID_STATE[1])

    # SUSTAINER requires membership ACTIVE or GRACE
    membership = db.memberships.get(pledge["membership_id"])
    if pledge["kind"] == "SUSTAINER" and membership is not None:
        if membership["status"] not in ("ACTIVE", "GRACE"):
            raise ApiError(ERR_INVALID_STATE[0],
                           "SUSTAINER payment requires membership ACTIVE or GRACE",
                           ERR_INVALID_STATE[1])

    # OCC
    if expected != pledge["version"]:
        raise ApiError(ERR_STALE_PLEDGE_VERSION[0],
                       "expected_pledge_version does not match Pledge.version",
                       ERR_STALE_PLEDGE_VERSION[1])

    # Amount bounds (priority 10)
    if amount_cents < 1:
        raise ApiError(ERR_PAYMENT_AMOUNT[0],
                       "Payment amount must be >= 1",
                       ERR_PAYMENT_AMOUNT[1])
    if pledge["kind"] == "ONE_TIME":
        remaining = pledge["amount_cents"] - pledge["collected_cents"]
        if amount_cents > remaining:
            raise ApiError(ERR_PAYMENT_AMOUNT[0],
                           "Payment exceeds remaining balance on a ONE_TIME pledge",
                           ERR_PAYMENT_AMOUNT[1])
    else:  # SUSTAINER: payment does not exceed amount_cents (per-installment)
        if amount_cents > pledge["amount_cents"]:
            raise ApiError(ERR_PAYMENT_AMOUNT[0],
                           "Payment exceeds per-month installment amount",
                           ERR_PAYMENT_AMOUNT[1])

    # Apply payment
    old_net = pledge["net_collected_cents"]
    pledge["collected_cents"] += amount_cents

    # New status
    if pledge["kind"] == "ONE_TIME":
        pledge["payment_status"] = "PAID" if pledge["collected_cents"] >= pledge["amount_cents"] else "PARTIAL"
    else:
        # SUSTAINER: first installment pays it; further installments keep PAID
        pledge["payment_status"] = "PAID"

    pledge["net_collected_cents"] = core.compute_net_collected(pledge)
    db.touch(pledge)
    net_delta = pledge["net_collected_cents"] - old_net

    # Drive collected delta
    drive = db.drives.get(pledge["drive_id"])
    if drive is not None:
        drive["collected_cents"] += net_delta
        db.touch(drive)

    # Donor lifetime delta
    donor = db.donors.get(pledge["donor_id"])
    if donor is not None:
        donor["lifetime_given_cents"] += net_delta
        db.touch(donor)

    # Membership period extension + LAPSED/REINSTATED_PENDING -> ACTIVE cascade
    if membership is not None:
        core.extend_membership_on_payment(membership, pledge["kind"], donor)

    return response.success_object(pledge, status=201)


# ---------------------------------------------------------------------------
# Decline / write-off
# ---------------------------------------------------------------------------

@bp.route("/station/pledges/<pid>/decline", methods=["POST"])
def decline_pledge(pid):
    body = v.get_json_body()
    require_roles("PhoneVolunteer")
    pledge = _get_pledge_or_404(pid)
    reason = v.req_str(body, "reason")

    if pledge["payment_status"] not in ("PLEDGED", "PARTIAL"):
        raise ApiError(ERR_INVALID_STATE[0],
                       f"Pledge payment_status is {pledge['payment_status']} (terminal)",
                       ERR_INVALID_STATE[1])

    _compensating_reversal(pledge, reason)
    pledge["payment_status"] = "DECLINED"
    db.touch(pledge)
    return response.success_object(pledge)


@bp.route("/station/pledges/<pid>/write-off", methods=["POST"])
def write_off_pledge(pid):
    body = v.get_json_body()
    require_roles("MembershipCoordinator")
    pledge = _get_pledge_or_404(pid)
    reason = v.req_str(body, "reason")

    if pledge["payment_status"] not in ("PLEDGED", "PARTIAL"):
        raise ApiError(ERR_INVALID_STATE[0],
                       f"Pledge payment_status is {pledge['payment_status']} (terminal)",
                       ERR_INVALID_STATE[1])

    # 60-day follow-up window (priority 7)
    created = db.parse_dt(pledge["created_at"])
    if db.now() < created + timedelta(days=60):
        raise ApiError(ERR_WRITEOFF_WINDOW[0],
                       "Write-off attempted before the 60-day follow-up window elapsed",
                       ERR_WRITEOFF_WINDOW[1])

    _compensating_reversal(pledge, reason)
    pledge["payment_status"] = "WRITTEN_OFF"
    db.touch(pledge)
    return response.success_object(pledge)


# ---------------------------------------------------------------------------
# Premium reservations (create/list under pledge)
# ---------------------------------------------------------------------------

@bp.route("/station/pledges/<pid>/premium-reservations", methods=["POST"])
def create_reservation(pid):
    body = v.get_json_body()
    require_roles("MembershipCoordinator")
    pledge = _get_pledge_or_404(pid)

    quantity = v.req_int(body, "quantity", min_val=1)
    lot_id = v.opt_str(body, "lot_id")

    # ERR_PREMIUM_NOT_SELECTED: no premium selected at all
    if pledge.get("premium_id") is None:
        raise ApiError(ERR_PREMIUM_NOT_SELECTED[0],
                       "Pledge has no premium selected",
                       ERR_PREMIUM_NOT_SELECTED[1])

    # State: must be AWAITING_RESERVATION
    if pledge["fulfillment_status"] == "WAIVED":
        raise ApiError(ERR_PREMIUM_NOT_SELECTED[0],
                       "Pledge premium was waived",
                       ERR_PREMIUM_NOT_SELECTED[1])
    if pledge["fulfillment_status"] != "AWAITING_RESERVATION":
        raise ApiError(ERR_INVALID_STATE[0],
                       f"Pledge fulfillment_status is {pledge['fulfillment_status']}",
                       ERR_INVALID_STATE[1])

    premium = db.premiums.get(pledge["premium_id"])
    if premium is None or not premium["active"]:
        raise ApiError(ERR_LEVEL_OR_PREMIUM_INELIGIBLE[0],
                       "Premium is not active",
                       ERR_LEVEL_OR_PREMIUM_INELIGIBLE[1])

    # Select lot: explicit or FIFO
    if lot_id is not None:
        lot = db.lots.get(lot_id)
        if lot is None:
            v.not_found(f"PremiumInventoryLot '{lot_id}' not found")
        if lot["premium_id"] != pledge["premium_id"]:
            raise ApiError(ERR_INSUFFICIENT_INVENTORY[0],
                           "Lot does not stock the pledge's premium",
                           ERR_INSUFFICIENT_INVENTORY[1])
        if lot["available_qty"] < quantity:
            raise ApiError(ERR_INSUFFICIENT_INVENTORY[0],
                           "Lot available_qty < quantity",
                           ERR_INSUFFICIENT_INVENTORY[1])
    else:
        candidates = [l for l in db.lots.values()
                      if l["premium_id"] == pledge["premium_id"] and l["available_qty"] >= quantity]
        candidates.sort(key=lambda l: (l["received_at"], l["created_at"]))
        if not candidates:
            raise ApiError(ERR_INSUFFICIENT_INVENTORY[0],
                           "No lot has available_qty >= quantity",
                           ERR_INSUFFICIENT_INVENTORY[1])
        lot = candidates[0]

    res = db.new_entity()
    res.update({
        "pledge_id": pid,
        "premium_id": pledge["premium_id"],
        "lot_id": lot["id"],
        "quantity": quantity,
        "status": "HELD",
    })
    db.reservations[res["id"]] = res
    lot["reserved_qty"] += quantity
    lot["available_qty"] -= quantity
    db.touch(lot)

    pledge["fulfillment_status"] = "RESERVED"
    db.touch(pledge)
    core.resync_pledge_net(pledge)

    return response.success_object(res, status=201)


@bp.route("/station/pledges/<pid>/premium-reservations", methods=["GET"])
def list_pledge_reservations(pid):
    require_roles("StationAdmin", "MembershipCoordinator")
    if pid not in db.pledges:
        v.not_found(f"Pledge '{pid}' not found")
    limit, offset = v.parse_pagination(request.args)
    items = [r for r in db.reservations.values() if r["pledge_id"] == pid]
    items = v.sort_created(items)
    page, total = v.paginate(items, limit, offset)
    return response.success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Ship / waive premium
# ---------------------------------------------------------------------------

@bp.route("/station/pledges/<pid>/ship-premium", methods=["POST"])
def ship_premium(pid):
    v.get_json_body(required=False)
    require_roles("MembershipCoordinator")
    pledge = _get_pledge_or_404(pid)

    if pledge.get("premium_id") is None or pledge["fulfillment_status"] in ("NO_PREMIUM", "WAIVED"):
        raise ApiError(ERR_PREMIUM_NOT_SELECTED[0],
                       "Pledge has no premium selected",
                       ERR_PREMIUM_NOT_SELECTED[1])
    if pledge["fulfillment_status"] != "RESERVED":
        raise ApiError(ERR_INVALID_STATE[0],
                       f"Pledge fulfillment_status is {pledge['fulfillment_status']}, must be RESERVED",
                       ERR_INVALID_STATE[1])
    if pledge["payment_status"] != "PAID":
        raise ApiError(ERR_INVALID_STATE[0],
                       "Premiums ship only after full payment (payment_status PAID)",
                       ERR_INVALID_STATE[1])

    reservation = core.active_reservation_for_pledge(pid)
    if reservation is not None and reservation["status"] == "HELD":
        lot = db.lots.get(reservation["lot_id"])
        reservation["status"] = "COMMITTED"
        db.touch(reservation)
        if lot is not None:
            lot["reserved_qty"] -= reservation["quantity"]
            lot["committed_qty"] += reservation["quantity"]
            db.touch(lot)
    pledge["fulfillment_status"] = "SHIPPED"
    db.touch(pledge)
    return response.success_object(pledge)


@bp.route("/station/pledges/<pid>/waive-premium", methods=["POST"])
def waive_premium(pid):
    v.get_json_body(required=False)
    require_roles("MembershipCoordinator")
    pledge = _get_pledge_or_404(pid)

    if pledge.get("premium_id") is None or pledge["fulfillment_status"] in ("NO_PREMIUM", "WAIVED"):
        raise ApiError(ERR_PREMIUM_NOT_SELECTED[0],
                       "Pledge has no premium selected",
                       ERR_PREMIUM_NOT_SELECTED[1])
    if pledge["fulfillment_status"] not in ("AWAITING_RESERVATION", "RESERVED"):
        raise ApiError(ERR_INVALID_STATE[0],
                       f"Pledge fulfillment_status is {pledge['fulfillment_status']}",
                       ERR_INVALID_STATE[1])

    if pledge["fulfillment_status"] == "RESERVED":
        reservation = core.active_reservation_for_pledge(pid)
        if reservation is not None and reservation["status"] == "HELD":
            _release_reservation(reservation)

    pledge["premium_waived"] = True
    pledge["fulfillment_status"] = "WAIVED"
    db.touch(pledge)
    core.resync_pledge_net(pledge)
    return response.success_object(pledge)
