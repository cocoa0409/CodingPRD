"""Travellers and their ledger entry points (PRD sections 3.5, 3.6, 3.7)."""

from flask import Blueprint, request

import core
import response
from db import db, lock
from errors import err
from middleware import (ROLE_AIR_DESK_AGENT, ROLE_FINANCE_CONTROLLER, ROLE_GROUP_LEADER,
                        ROLE_PROGRAM_MANAGER, ROLE_PROTECTION_ADMINISTRATOR, ROLE_RISK_OFFICER,
                        authorize)
from validate import (apply_filters, body_of, opt_bool, opt_enum, opt_id, pagination, req_date,
                      req_enum, req_id, req_int, req_str, opt_datetime, req_bool)

bp = Blueprint("pilgrims", __name__)

READ_ROLES = (ROLE_PROGRAM_MANAGER, ROLE_RISK_OFFICER, ROLE_AIR_DESK_AGENT,
              ROLE_FINANCE_CONTROLLER, ROLE_PROTECTION_ADMINISTRATOR, ROLE_GROUP_LEADER)


def _load(pilgrim_id):
    row = db.pilgrims.get(pilgrim_id)
    if row is None:
        err("ERR_PILGRIM_NOT_FOUND", "Pilgrim %s does not exist." % pilgrim_id)
    return row


# ---------------------------------------------------------------------------
# Enrolment and reads
# ---------------------------------------------------------------------------


@bp.route("/pilgrims", methods=["POST"])
def create_pilgrim():
    caller = authorize((ROLE_PROGRAM_MANAGER, ROLE_GROUP_LEADER))
    if caller.is_group_leader:
        peek = request.get_json(silent=True)
        supplied = peek.get("recruited_by_agreement_id") if isinstance(peek, dict) else None
        if supplied != caller.user_id:
            err("ERR_UNAUTHORIZED",
                "A group leader may only enrol travelers against their own agreement.")
    body = body_of()
    with lock:
        departure_id = req_id(body, "departure_id")
        full_name = req_str(body, "full_name", 1, 120)
        date_of_birth = req_date(body, "date_of_birth")
        room_type_requested = req_enum(body, "room_type_requested", core.ROOM_TYPES)
        recruited_by_agreement_id = opt_id(body, "recruited_by_agreement_id")
        mobility_code = opt_enum(body, "mobility_code", core.MOBILITY_CODES, "NONE")
        is_free_seat_grant = opt_bool(body, "is_free_seat_grant", False)
        risk_acknowledged = opt_bool(body, "risk_acknowledged", False)

        departure = db.departures.get(departure_id)
        if departure is None:
            err("ERR_DEPARTURE_NOT_FOUND", "Departure %s does not exist." % departure_id)
        agreement = None
        if recruited_by_agreement_id is not None:
            agreement = db.agreements.get(recruited_by_agreement_id)
            if agreement is None:
                err("ERR_AGREEMENT_NOT_FOUND",
                    "Group leader agreement %s does not exist." % recruited_by_agreement_id)

        if date_of_birth >= core.as_date(departure["departure_date"]):
            err("ERR_INVALID_REQUEST",
                "date_of_birth must be strictly before the departure date.")

        core.refresh_posture(departure)
        if departure["status"] not in ("PLANNING", "OPEN_FOR_SALE"):
            err("ERR_DEPARTURE_INVALID_STATE",
                "Enrolment requires the departure to be PLANNING or OPEN_FOR_SALE.")
        live_count = len([p for p in db.pilgrims.values()
                          if p["departure_id"] == departure_id
                          and p["booking_status"] != "CANCELLED"])
        if live_count >= departure["max_pax"]:
            err("ERR_DEPARTURE_INVALID_STATE",
                "The departure already holds max_pax non-cancelled travelers.")

        if mobility_code in core.GROUND_FLOOR_MOBILITY_CODES and \
                not departure["mobility_accessible_coach"]:
            err("ERR_MOBILITY_UNSUPPORTED",
                "This departure's coach cannot carry a %s traveler." % mobility_code)
        if departure["risk_posture"] == "SUSPENDED":
            err("ERR_DEPARTURE_SUSPENDED_NO_NEW_BOOKINGS",
                "A suspended departure takes no new bookings.")
        if departure["risk_posture"] == "RESTRICTED" and not risk_acknowledged:
            err("ERR_RISK_ACKNOWLEDGEMENT_REQUIRED",
                "The elevated-risk acknowledgement is required on a RESTRICTED departure.")

        if agreement is not None:
            if agreement["departure_id"] != departure_id or \
                    agreement["status"] not in ("PENDING_COUNTERSIGN", "ACTIVE"):
                err("ERR_AGREEMENT_DEPARTURE_MISMATCH",
                    "The recruiting agreement does not belong to this departure or is not live.")
        if is_free_seat_grant:
            if agreement is None or \
                    not agreement["earned_free_seats"] > core.free_seats_granted(agreement):
                err("ERR_NO_EARNED_FREE_SEAT",
                    "No unconsumed earned free seat is available on this agreement.")

        row = core.base_row()
        row.update({
            "departure_id": departure_id,
            "recruited_by_agreement_id": recruited_by_agreement_id,
            "roommate_pilgrim_id": None,
            "full_name": full_name,
            "date_of_birth": core.date_str(date_of_birth),
            "age_at_departure": core.complete_years(
                date_of_birth, core.as_date(departure["departure_date"])),
            "room_type_requested": room_type_requested,
            "room_type_assigned": None,
            "room_label": None,
            "ground_floor": False,
            "dietary_codes": ["NONE"],
            "mobility_code": mobility_code,
            "risk_acknowledged": risk_acknowledged,
            "is_free_seat_grant": is_free_seat_grant,
            "is_paying": not is_free_seat_grant,
            "booking_status": "INQUIRY",
            "payment_status": "UNPAID",
            "protection_status": "NONE",
            "price_locked_cents": None,
            "single_supplement_applied_cents": 0,
            "deviation_type": "NONE",
            "deviation_fee_cents": 0,
            "invoice_total_cents": 0,
            "protection_premium_cents": 0,
            "cash_applied_cents": 0,
            "credit_balance_cents": 0,
            "ticketed_name": None,
            "refund_cents": 0,
            "penalty_retained_cents": 0,
        })
        row["_deposit_date"] = None
        db.pilgrims[row["id"]] = row

        departure_before = core.snap(departure)
        core.recompute_provisional_tier(departure)
        core.touch_if_changed(departure, departure_before)
        core.refresh_recruiting_agreement(row, "snapshot")

        return response.ok(core.serialize(row), 201)


@bp.route("/pilgrims/<pilgrim_id>", methods=["GET"])
def get_pilgrim(pilgrim_id):
    caller = authorize(READ_ROLES)
    with lock:
        row = _load(pilgrim_id)
        if caller.is_group_leader and row["recruited_by_agreement_id"] != caller.user_id:
            err("ERR_UNAUTHORIZED", "A group leader may only read their own recruits.")
        return response.ok(core.serialize(row))


@bp.route("/pilgrims", methods=["GET"])
def list_pilgrims():
    caller = authorize(READ_ROLES)
    with lock:
        limit, offset = pagination()
        rows = core.order_rows(list(db.pilgrims.values()))
        if caller.is_group_leader:
            rows = [r for r in rows if r["recruited_by_agreement_id"] == caller.user_id]
        rows = apply_filters(rows, {
            "departure_id": "departure_id",
            "recruited_by_agreement_id": "recruited_by_agreement_id",
            "roommate_pilgrim_id": "roommate_pilgrim_id",
            "booking_status": "booking_status",
        })
        page, total = core.paginate(rows, limit, offset)
        return response.ok_list([core.serialize(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Booking lifecycle
# ---------------------------------------------------------------------------


@bp.route("/pilgrims/<pilgrim_id>/confirm", methods=["POST"])
def confirm_pilgrim(pilgrim_id):
    authorize((ROLE_PROGRAM_MANAGER,))
    with lock:
        pilgrim = _load(pilgrim_id)
        departure = core.departure_of(pilgrim)
        core.refresh_posture(departure)

        if departure["status"] != "OPEN_FOR_SALE":
            err("ERR_DEPARTURE_INVALID_STATE",
                "Confirmation requires the departure to be OPEN_FOR_SALE.")
        allowed_from = ("DEPOSITED",) if pilgrim["is_paying"] else ("INQUIRY", "DEPOSITED")
        if pilgrim["booking_status"] not in allowed_from:
            err("ERR_PILGRIM_NOT_ACTIVE",
                "A traveler in %s cannot be confirmed." % pilgrim["booking_status"])
        if pilgrim["room_type_assigned"] is None:
            err("ERR_PILGRIM_NOT_ACTIVE", "An unroomed traveler cannot be manifested.")

        if departure["risk_posture"] == "RESTRICTED" and not pilgrim["risk_acknowledged"]:
            err("ERR_RISK_ACKNOWLEDGEMENT_REQUIRED",
                "The elevated-risk acknowledgement is required on a RESTRICTED departure.")
        if departure["risk_posture"] == "SUSPENDED":
            err("ERR_DEPARTURE_POSTURE_BLOCKS_CONFIRM",
                "A suspended departure cannot confirm travelers.")
        if pilgrim["age_at_departure"] >= core.SENIOR_PROTECTION_AGE:
            purchased = [tp for tp in core.protections_of_pilgrim(pilgrim_id)
                         if tp["status"] == "PURCHASED"]
            if not purchased:
                err("ERR_SENIOR_PROTECTION_REQUIRED",
                    "A traveler aged %d requires purchased travel protection."
                    % core.SENIOR_PROTECTION_AGE)
        if departure["pending_modification_required"]:
            err("ERR_PENDING_MODIFICATION_UNRATIFIED",
                "An itinerary modification is awaiting ratification.")

        pilgrim["booking_status"] = "CONFIRMED"
        pilgrim["price_locked_cents"] = departure["provisional_per_pax_price_cents"]
        core.recompute_invoice(pilgrim)
        core.touch(pilgrim)

        departure_before = core.snap(departure)
        core.recompute_provisional_tier(departure)
        core.touch_if_changed(departure, departure_before)
        core.refresh_recruiting_agreement(pilgrim, "snapshot")
        return response.ok(core.serialize(pilgrim))


@bp.route("/pilgrims/<pilgrim_id>/cancel", methods=["POST"])
def cancel_pilgrim_route(pilgrim_id):
    authorize((ROLE_PROGRAM_MANAGER, ROLE_FINANCE_CONTROLLER))
    body = body_of()
    with lock:
        pilgrim = _load(pilgrim_id)
        req_str(body, "cancellation_reason", 1, None)
        if pilgrim["booking_status"] == "CANCELLED":
            err("ERR_PILGRIM_NOT_ACTIVE", "The traveler is already cancelled.")
        core.refresh_posture(core.departure_of(pilgrim))
        core.cancel_pilgrim(pilgrim)
        return response.ok(core.serialize(pilgrim))


@bp.route("/pilgrims/<pilgrim_id>/rooming", methods=["POST"])
def rooming(pilgrim_id):
    authorize((ROLE_PROGRAM_MANAGER,))
    body = body_of()
    with lock:
        pilgrim = _load(pilgrim_id)
        room_type_assigned = req_enum(body, "room_type_assigned", core.ROOM_TYPES)
        room_label = req_str(body, "room_label", 1, 40)
        ground_floor = req_bool(body, "ground_floor")
        roommate_pilgrim_id = opt_id(body, "roommate_pilgrim_id")
        dietary_codes = _validate_dietary_codes(body, pilgrim["dietary_codes"])

        roommate = None
        if roommate_pilgrim_id is not None:
            roommate = db.pilgrims.get(roommate_pilgrim_id)
            if roommate is None:
                err("ERR_PILGRIM_NOT_FOUND", "Pilgrim %s does not exist." % roommate_pilgrim_id)

        if pilgrim["booking_status"] not in ("INQUIRY", "DEPOSITED", "CONFIRMED"):
            err("ERR_PILGRIM_NOT_ACTIVE", "A cancelled traveler cannot be roomed.")

        departure = core.departure_of(pilgrim)
        if pilgrim["mobility_code"] in core.GROUND_FLOOR_MOBILITY_CODES and not ground_floor:
            err("ERR_MOBILITY_ACCOMMODATION_UNMET",
                "A %s traveler requires a ground-floor room." % pilgrim["mobility_code"])

        if any(code in core.DIETARY_LEAD_TIME_CODES for code in dietary_codes):
            days = core.whole_days(core.as_date(departure["departure_date"]), core.clock_date())
            if days < core.DIETARY_LEAD_TIME_MIN_DAYS:
                err("ERR_DIETARY_LEAD_TIME_UNMET",
                    "KOSHER or HALAL catering requires at least %d days lead time."
                    % core.DIETARY_LEAD_TIME_MIN_DAYS)

        occupants = len([p for p in db.pilgrims.values()
                         if p["departure_id"] == departure["id"]
                         and p["id"] != pilgrim["id"]
                         and p["booking_status"] != "CANCELLED"
                         and p["room_label"] == room_label])
        if occupants + 1 > core.ROOM_CAPACITY[room_type_assigned]:
            err("ERR_ROOM_CAPACITY_EXCEEDED",
                "Room %s cannot hold more than %d travelers."
                % (room_label, core.ROOM_CAPACITY[room_type_assigned]))

        if roommate is not None:
            if roommate["id"] == pilgrim["id"] \
                    or roommate["departure_id"] != pilgrim["departure_id"] \
                    or roommate["booking_status"] == "CANCELLED" \
                    or roommate["room_type_requested"] != pilgrim["room_type_requested"]:
                err("ERR_ROOMMATE_INVALID", "The named rooming partner is not eligible.")

        pilgrim["room_type_assigned"] = room_type_assigned
        pilgrim["room_label"] = room_label
        pilgrim["ground_floor"] = ground_floor
        pilgrim["dietary_codes"] = dietary_codes
        if roommate is not None:
            pilgrim["roommate_pilgrim_id"] = roommate["id"]
            roommate_before = core.snap(roommate)
            roommate["roommate_pilgrim_id"] = pilgrim["id"]
            core.touch_if_changed(roommate, roommate_before)
        if room_type_assigned == "SINGLE":
            pilgrim["single_supplement_applied_cents"] = \
                departure["provisional_single_supplement_cents"]
        else:
            pilgrim["single_supplement_applied_cents"] = 0
        core.recompute_invoice(pilgrim)
        core.touch(pilgrim)
        return response.ok(core.serialize(pilgrim))


def _validate_dietary_codes(body, current):
    if "dietary_codes" not in body or body["dietary_codes"] is None:
        return list(current)
    value = body["dietary_codes"]
    if not isinstance(value, list) or not 1 <= len(value) <= 4:
        err("ERR_INVALID_REQUEST", "dietary_codes must be an array of 1 to 4 items.")
    seen = []
    for code in value:
        if not isinstance(code, str) or code not in core.DIETARY_CODES:
            err("ERR_INVALID_REQUEST", "dietary_codes contains an unknown code.")
        if code in seen:
            err("ERR_INVALID_REQUEST", "dietary_codes may not contain duplicates.")
        seen.append(code)
    if "NONE" in seen and len(seen) > 1:
        err("ERR_INVALID_REQUEST", "dietary_codes NONE may not be combined with other codes.")
    return seen


# ---------------------------------------------------------------------------
# Air desk actions
# ---------------------------------------------------------------------------


@bp.route("/pilgrims/<pilgrim_id>/ticket-name", methods=["POST"])
def ticket_name(pilgrim_id):
    authorize((ROLE_AIR_DESK_AGENT,))
    body = body_of()
    with lock:
        pilgrim = _load(pilgrim_id)
        ticketed_name = req_str(body, "ticketed_name", 1, 120)
        if pilgrim["booking_status"] not in ("INQUIRY", "DEPOSITED", "CONFIRMED"):
            err("ERR_PILGRIM_NOT_ACTIVE", "A cancelled traveler cannot be ticketed.")

        block = core.confirmed_air_block(pilgrim["departure_id"])
        if block is None:
            err("ERR_AIR_BLOCK_NOT_CONFIRMED",
                "The departure has no CONFIRMED air block.")
        if core.clock_now() > core.as_dt(block["name_change_deadline_utc"]):
            err("ERR_NAME_CHANGE_DEADLINE_PASSED",
                "The air block's name change deadline has passed.")
        holds_seat = (pilgrim["ticketed_name"] is not None
                      and pilgrim["booking_status"] in ("DEPOSITED", "CONFIRMED"))
        if core.seats_assigned_for(pilgrim["departure_id"]) >= block["seats_held"] \
                and not holds_seat:
            err("ERR_AIR_BLOCK_SEATS_EXHAUSTED", "No seat remains in the confirmed block.")

        pilgrim["ticketed_name"] = ticketed_name
        core.touch(pilgrim)
        return response.ok(core.serialize(pilgrim))


@bp.route("/pilgrims/<pilgrim_id>/air-deviation", methods=["POST"])
def air_deviation(pilgrim_id):
    authorize((ROLE_AIR_DESK_AGENT,))
    body = body_of()
    with lock:
        pilgrim = _load(pilgrim_id)
        deviation_type = req_enum(body, "deviation_type",
                                  ("ORIGIN_CHANGE", "DATE_DEVIATION", "CLASS_UPGRADE"))
        if pilgrim["booking_status"] not in ("INQUIRY", "DEPOSITED", "CONFIRMED"):
            err("ERR_PILGRIM_NOT_ACTIVE", "A cancelled traveler cannot request a deviation.")

        block = core.confirmed_air_block(pilgrim["departure_id"])
        if block is None:
            err("ERR_AIR_BLOCK_NOT_CONFIRMED", "The departure has no CONFIRMED air block.")

        departure = core.departure_of(pilgrim)
        pilgrim["deviation_type"] = deviation_type
        pilgrim["deviation_fee_cents"] = core.deviation_fee(departure, block, deviation_type)
        core.recompute_invoice(pilgrim)
        core.touch(pilgrim)
        core.requote_quoted_protections(pilgrim)
        return response.ok(core.serialize(pilgrim))


# ---------------------------------------------------------------------------
# Plans and receipts
# ---------------------------------------------------------------------------


@bp.route("/pilgrims/<pilgrim_id>/payment-plans", methods=["POST"])
def create_payment_plan(pilgrim_id):
    authorize((ROLE_FINANCE_CONTROLLER,))
    body = body_of()
    with lock:
        pilgrim = _load(pilgrim_id)
        plan_type = req_enum(body, "plan_type", core.PLAN_TYPES)
        first_due_date = req_date(body, "first_due_date")
        expected_pilgrim_version = req_int(body, "expected_pilgrim_version")

        departure = core.departure_of(pilgrim)
        if first_due_date < core.clock_date():
            err("ERR_INVALID_REQUEST",
                "first_due_date must be on or after the current logical date.")
        if first_due_date > core.as_date(departure["final_payment_due_date"]):
            err("ERR_INVALID_REQUEST",
                "first_due_date must be on or before the departure's final_payment_due_date.")

        if pilgrim["booking_status"] not in ("DEPOSITED", "CONFIRMED"):
            err("ERR_PILGRIM_NOT_ACTIVE",
                "A payment plan requires a DEPOSITED or CONFIRMED traveler.")
        if pilgrim["invoice_total_cents"] <= 0:
            err("ERR_PILGRIM_NOT_ACTIVE",
                "A payment plan requires a positive invoice total.")

        if expected_pilgrim_version != pilgrim["version"]:
            err("ERR_STALE_PILGRIM_VERSION",
                "expected_pilgrim_version %d does not match the stored version %d."
                % (expected_pilgrim_version, pilgrim["version"]))

        total = pilgrim["invoice_total_cents"]
        row = core.base_row()
        row.update({
            "pilgrim_id": pilgrim_id,
            "plan_type": plan_type,
            "first_due_date": core.date_str(first_due_date),
            "installment_count": core.INSTALLMENT_COUNT[plan_type],
            "total_scheduled_cents": total,
            "installments": core.build_installments(plan_type, first_due_date, total),
            "past_due_count": 0,
            "status": "ACTIVE",
            "superseded_by_plan_id": None,
        })

        for prior in core.plans_of_pilgrim(pilgrim_id):
            if prior["status"] != "ACTIVE":
                continue
            prior["status"] = "SUPERSEDED"
            prior["superseded_by_plan_id"] = row["id"]
            returned = sum(i["amount_paid_cents"] for i in prior["installments"])
            pilgrim["credit_balance_cents"] = pilgrim["credit_balance_cents"] + returned
            for installment in prior["installments"]:
                if installment["status"] in ("SCHEDULED", "PARTIALLY_PAID", "PAST_DUE"):
                    installment["status"] = "WAIVED"
            core.refresh_past_due_count(prior)
            core.touch(prior)

        db.payment_plans[row["id"]] = row

        credit = pilgrim["credit_balance_cents"]
        pilgrim["credit_balance_cents"] = 0
        core.allocate_cash(pilgrim, credit)
        # The plan is brand new in this request: the credit drain is part of its
        # creation, so it stays at version 1.
        row["version"] = 1
        row["updated_at"] = row["created_at"]
        core.touch(pilgrim)
        return response.ok(core.serialize(row), 201)


@bp.route("/pilgrims/<pilgrim_id>/payments", methods=["POST"])
def create_payment(pilgrim_id):
    authorize((ROLE_FINANCE_CONTROLLER,))
    body = body_of()
    with lock:
        pilgrim = _load(pilgrim_id)
        amount_cents = req_int(body, "amount_cents", 1)
        method = req_enum(body, "method", core.PAYMENT_METHODS)
        received_at = opt_datetime(body, "received_at", None)
        if received_at is not None and received_at > core.clock_now():
            err("ERR_INVALID_REQUEST", "received_at may not be later than the logical clock.")
        if received_at is None:
            received_at = core.clock_now()

        if pilgrim["booking_status"] == "CANCELLED":
            err("ERR_PILGRIM_NOT_ACTIVE", "A cancelled traveler cannot receive payments.")

        ceiling = pilgrim["invoice_total_cents"] + pilgrim["protection_premium_cents"]
        if pilgrim["cash_applied_cents"] + amount_cents > ceiling:
            err("ERR_OVERPAYMENT_NOT_ALLOWED",
                "The receipt would carry applied cash beyond the invoice and premium.")

        departure = core.departure_of(pilgrim)
        pilgrim["cash_applied_cents"] = pilgrim["cash_applied_cents"] + amount_cents
        allocation, _plan_ids = core.allocate_cash(pilgrim, amount_cents)

        row = core.base_row(with_version=False)
        row.update({
            "pilgrim_id": pilgrim_id,
            "amount_cents": amount_cents,
            "method": method,
            "received_at": response.iso_ms(received_at),
            "status": "APPLIED",
            "allocation": allocation,
            "reversed_at": None,
        })
        row["_alloc_plan_ids"] = _plan_ids
        db.payments[row["id"]] = row

        crosses_deposit = (pilgrim["is_paying"]
                           and pilgrim["booking_status"] == "INQUIRY"
                           and pilgrim["cash_applied_cents"] >= departure["provisional_deposit_cents"])
        if crosses_deposit:
            pilgrim["booking_status"] = "DEPOSITED"
            if pilgrim["payment_status"] == "UNPAID":
                pilgrim["payment_status"] = "DEPOSIT_PAID"
            pilgrim["_deposit_date"] = core.clock_date()
            for protection in core.protections_of_pilgrim(pilgrim_id):
                protection_before = core.snap(protection)
                protection["deposit_reference_date"] = core.date_str(core.clock_date())
                core.touch_if_changed(protection, protection_before)
            departure_before = core.snap(departure)
            core.recompute_provisional_tier(departure)
            core.touch_if_changed(departure, departure_before)
            core.refresh_recruiting_agreement(pilgrim, "snapshot")

        core.touch(pilgrim)
        return response.ok(core.serialize(row), 201)
