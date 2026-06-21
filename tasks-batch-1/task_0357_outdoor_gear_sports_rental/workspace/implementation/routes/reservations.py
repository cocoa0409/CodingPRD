"""Reservation endpoints: the core workflow.

create / get / list / quote / addons / confirm / checkout / checkin /
settle / cancel.
"""
from flask import Blueprint, request

import db
import errors
import store
import serializers as S
import middleware as M
from response import ok, created, ok_list
import calculations as C

bp = Blueprint("reservations", __name__)

CATEGORIES = {"KAYAK", "SKI", "SUP", "SNOWBOARD"}
CONDITION_RATINGS = {"GOOD", "WORN", "DAMAGED", "LOST"}


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _owns(role, user_id, reservation):
    """Renter must own; ShopAdmin/RentalAgent are not subject to ownership."""
    if role == "Renter" and reservation["customer_id"] != user_id:
        raise errors.unauthorized("renter does not own this reservation")


def _gear_type_for_unit(unit):
    return db.gear_types.get(unit["gear_type_id"])


def _rate_card_for_reservation(reservation):
    return db.rate_cards.get(reservation["rate_card_id"])


def _recompute_quote(reservation):
    unit = db.gear_units.get(reservation["gear_unit_id"])
    rate_card = _rate_card_for_reservation(reservation)
    gear_type = _gear_type_for_unit(unit)
    total, basis = C.quote_rental_cost(reservation, rate_card, gear_type)
    reservation["quoted_total_cents"] = total
    reservation["quoted_rate_basis"] = basis


# ----------------------------------------------------------------------------
# Create (quote)
# ----------------------------------------------------------------------------

@bp.post("/rental/reservations")
def create_reservation():
    body = M.get_json_body()
    # 0. payload well-formedness
    customer_id = M.require_str(body, "customer_id")
    gear_unit_id = M.require_str(body, "gear_unit_id")
    M.require_fields(body, ["pickup_at", "due_at", "expected_gear_unit_version"])
    pickup_at = M.parse_dt(body["pickup_at"], "pickup_at")
    due_at = M.parse_dt(body["due_at"], "due_at")
    if pickup_at >= due_at:
        raise errors.validation("pickup_at must be strictly earlier than due_at")
    damage_waiver_opted = M.optional_bool(body, "damage_waiver_opted", False)
    expected_version = M.require_int(body, "expected_gear_unit_version")

    # 1-2. auth + role + ownership
    user_id, role = M.get_auth()
    M.require_role(role, {"Renter", "RentalAgent"})
    if role == "Renter" and customer_id != user_id:
        raise errors.unauthorized("renter may only create own reservations")

    # 3. existence, left to right: customer then gear unit
    customer = db.customers.get(customer_id)
    if not customer:
        raise errors.not_found("customer not found")
    unit = db.gear_units.get(gear_unit_id)
    if not unit:
        raise errors.not_found("gear unit not found")

    gear_type = db.gear_types.get(unit["gear_type_id"])
    rate_card = db.rate_cards.get(unit["rate_card_id"])

    # 5. referential business: unit AVAILABLE, type + rate card active
    if unit["availability"] != "AVAILABLE":
        raise errors.unit_not_available("gear unit is not AVAILABLE")
    if gear_type is None or not gear_type["active"]:
        raise errors.unit_not_available("gear type is inactive")
    if rate_card is None or not rate_card["active"]:
        raise errors.unit_not_available("rate card is inactive")

    # 6. window overlap (incl. turnaround buffer)
    if C.window_overlap(gear_unit_id, pickup_at, due_at):
        raise errors.window_conflict("requested window overlaps an existing window on the unit")

    # 10. OCC: expected_gear_unit_version must match the unit's current version
    if expected_version != unit["version"]:
        raise errors.stale_version("gear unit version mismatch")

    # create reservation
    reservation = store.create_reservation(
        customer_id=customer_id,
        gear_unit_id=gear_unit_id,
        rate_card_id=unit["rate_card_id"],
        pickup_at=pickup_at,
        due_at=due_at,
        damage_waiver_opted=damage_waiver_opted,
        quoted_rate_basis=None,
        quoted_total_cents=0,
    )
    _recompute_quote(reservation)

    # cascade: unit AVAILABLE -> RESERVED, active_reservation_id set, version+1
    unit["availability"] = "RESERVED"
    unit["active_reservation_id"] = reservation["id"]
    store.touch(unit)

    return created(S.reservation(reservation))


# ----------------------------------------------------------------------------
# Read
# ----------------------------------------------------------------------------

@bp.get("/rental/reservations/<id>")
def get_reservation(id):
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin", "RentalAgent", "Renter"})
    rec = db.reservations.get(id)
    if not rec:
        raise errors.not_found("reservation not found")
    return ok(S.reservation(rec))


@bp.get("/rental/reservations")
def list_reservations():
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin", "RentalAgent", "Renter"})
    limit, offset = M.parse_pagination()
    items = list(db.reservations.values())
    customer_id = request.args.get("customer_id")
    gear_unit_id = request.args.get("gear_unit_id")
    lifecycle_status = request.args.get("lifecycle_status")
    if customer_id is not None:
        items = [r for r in items if r["customer_id"] == customer_id]
    if gear_unit_id is not None:
        items = [r for r in items if r["gear_unit_id"] == gear_unit_id]
    if lifecycle_status is not None:
        items = [r for r in items if r["lifecycle_status"] == lifecycle_status]
    page, total = store.paginate(items, limit, offset)
    return ok_list([S.reservation(r) for r in page], limit, offset, total)


@bp.get("/rental/reservations/<id>/quote")
def quote_reservation(id):
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin", "RentalAgent", "Renter"})
    rec = db.reservations.get(id)
    if not rec:
        raise errors.not_found("reservation not found")
    _recompute_quote(rec)
    return ok(S.reservation(rec))


# ----------------------------------------------------------------------------
# Attach add-on (QUOTED only)
# ----------------------------------------------------------------------------

@bp.post("/rental/reservations/<id>/addons")
def attach_addon(id):
    body = M.get_json_body()
    addon_id = M.require_str(body, "addon_id")
    slot_start_at = None
    slot_end_at = None
    if body.get("slot_start_at") is not None:
        slot_start_at = M.parse_dt(body["slot_start_at"], "slot_start_at")
    if body.get("slot_end_at") is not None:
        slot_end_at = M.parse_dt(body["slot_end_at"], "slot_end_at")

    user_id, role = M.get_auth()
    M.require_role(role, {"Renter", "RentalAgent"})

    # existence: reservation then add-on
    reservation = db.reservations.get(id)
    if not reservation:
        raise errors.not_found("reservation not found")
    _owns(role, user_id, reservation)
    addon = db.addons.get(addon_id)
    if not addon:
        raise errors.not_found("add-on not found")

    # state: QUOTED only
    if reservation["lifecycle_status"] != "QUOTED":
        raise errors.invalid_state("add-ons can only be attached while QUOTED")

    # referential: add-on category must match the unit's gear type category
    unit = db.gear_units.get(reservation["gear_unit_id"])
    gear_type = db.gear_types.get(unit["gear_type_id"]) if unit else None
    if gear_type is None or addon["category"] != gear_type["category"]:
        raise errors.unit_not_available("add-on category mismatch")

    # slot capacity for LESSON (closed interval)
    if addon["kind"] == "LESSON":
        if slot_start_at is not None and slot_end_at is not None:
            occupancy = 0
            for ra in db.reservation_addons.values():
                if ra["addon_id"] != addon_id:
                    continue
                other_res = db.reservations.get(ra["reservation_id"])
                if other_res is None or other_res["lifecycle_status"] == "CANCELLED":
                    continue
                if ra["slot_start_at"] is None or ra["slot_end_at"] is None:
                    continue
                if C.intervals_intersect_closed(slot_start_at, slot_end_at,
                                                 ra["slot_start_at"], ra["slot_end_at"]):
                    occupancy += 1
            if occupancy + 1 > addon["capacity_per_slot"]:
                raise errors.slot_full("lesson slot at capacity")

    line = store.create_reservation_addon(
        reservation_id=id,
        addon_id=addon_id,
        slot_start_at=slot_start_at,
        slot_end_at=slot_end_at,
        price_cents=addon["price_cents"],
    )

    # recompute reservation quoted_total_cents (cascade -> reservation mutated)
    _recompute_quote(reservation)
    store.touch(reservation)

    return created(S.reservation_addon(line))


# ----------------------------------------------------------------------------
# Confirm (QUOTED -> CONFIRMED, holds deposit)
# ----------------------------------------------------------------------------

@bp.post("/rental/reservations/<id>/confirm")
def confirm(id):
    user_id, role = M.get_auth()
    M.require_role(role, {"Renter", "RentalAgent"})
    reservation = db.reservations.get(id)
    if not reservation:
        raise errors.not_found("reservation not found")
    _owns(role, user_id, reservation)

    # state: QUOTED -> CONFIRMED
    if reservation["lifecycle_status"] != "QUOTED":
        raise errors.invalid_state("reservation is not QUOTED")

    unit = db.gear_units.get(reservation["gear_unit_id"])
    gear_type = db.gear_types.get(unit["gear_type_id"]) if unit else None
    customer = db.customers.get(reservation["customer_id"])
    rate_card = _rate_card_for_reservation(reservation)

    # priority 8: beginner-lesson safety rule (before suspension per §2.9 order)
    has_lesson = any(
        db.addons.get(ra["addon_id"]) is not None and db.addons[ra["addon_id"]]["kind"] == "LESSON"
        for ra in db.reservation_addons.values()
        if ra["reservation_id"] == id
    )
    if (gear_type is not None and gear_type["requires_lesson_for_beginner"]
            and customer is not None and customer["skill_level"] == "BEGINNER"
            and not has_lesson):
        raise errors.lesson_required("beginner must attach a LESSON add-on before confirm")

    # priority 9: customer must not be SUSPENDED
    C.recompute_customer_standing(customer)
    if customer["standing"] == "SUSPENDED":
        raise errors.customer_suspended("customer standing is SUSPENDED")

    # side effects
    reservation["lifecycle_status"] = "CONFIRMED"
    reservation["deposit_cents"] = rate_card["deposit_cents"]
    reservation["payment_status"] = "DEPOSIT_HELD"
    store.touch(reservation)

    store.create_ledger_entry(
        reservation_id=id,
        customer_id=reservation["customer_id"],
        entry_type="DEPOSIT_HOLD",
        amount_cents=rate_card["deposit_cents"],
    )

    return ok(S.reservation(reservation))


# ----------------------------------------------------------------------------
# Checkout (CONFIRMED -> PICKED_UP)
# ----------------------------------------------------------------------------

@bp.post("/rental/reservations/<id>/checkout")
def checkout(id):
    body = M.get_json_body()
    condition_rating = M.require_enum(body, "condition_rating", CONDITION_RATINGS)
    notes = body.get("notes") if isinstance(body.get("notes"), str) else ""
    _, role = M.get_auth()
    M.require_role(role, {"RentalAgent"})
    reservation = db.reservations.get(id)
    if not reservation:
        raise errors.not_found("reservation not found")

    # state: CONFIRMED -> PICKED_UP
    if reservation["lifecycle_status"] != "CONFIRMED":
        raise errors.invalid_state("reservation is not CONFIRMED")

    unit = db.gear_units.get(reservation["gear_unit_id"])

    # creates CHECKOUT ConditionReport
    store.create_condition_report(
        reservation_id=id,
        gear_unit_id=reservation["gear_unit_id"],
        phase="CHECKOUT",
        condition_rating=condition_rating,
        notes=notes,
    )

    reservation["lifecycle_status"] = "PICKED_UP"
    reservation["picked_up_at"] = db.now_dt()
    store.touch(reservation)

    # unit: RESERVED -> CHECKED_OUT; condition set from rating
    unit["availability"] = "CHECKED_OUT"
    unit["condition"] = condition_rating
    store.touch(unit)

    return ok(S.reservation(reservation))


# ----------------------------------------------------------------------------
# Check-in (PICKED_UP -> RETURNED)
# ----------------------------------------------------------------------------

@bp.post("/rental/reservations/<id>/checkin")
def checkin(id):
    body = M.get_json_body()
    condition_rating = M.require_enum(body, "condition_rating", CONDITION_RATINGS)
    notes = body.get("notes") if isinstance(body.get("notes"), str) else ""
    _, role = M.get_auth()
    M.require_role(role, {"RentalAgent"})
    reservation = db.reservations.get(id)
    if not reservation:
        raise errors.not_found("reservation not found")

    # state: PICKED_UP -> RETURNED
    if reservation["lifecycle_status"] != "PICKED_UP":
        raise errors.invalid_state("reservation is not PICKED_UP")

    unit = db.gear_units.get(reservation["gear_unit_id"])
    gear_type = db.gear_types.get(unit["gear_type_id"]) if unit else None
    rate_card = _rate_card_for_reservation(reservation)
    customer = db.customers.get(reservation["customer_id"])

    # creates CHECKIN ConditionReport
    checkin_report = store.create_condition_report(
        reservation_id=id,
        gear_unit_id=reservation["gear_unit_id"],
        phase="CHECKIN",
        condition_rating=condition_rating,
        notes=notes,
    )

    reservation["lifecycle_status"] = "RETURNED"
    reservation["returned_at"] = db.now_dt()

    # checkout rating
    checkout_rating = None
    for cr in db.condition_reports.values():
        if cr["reservation_id"] == id and cr["phase"] == "CHECKOUT":
            checkout_rating = cr["condition_rating"]

    # late fee (computed before final settlement reads it)
    late = C.late_fee(reservation, rate_card)
    reservation["late_fee_cents"] = late

    # damage assessment
    outcome, charge, waiver_applied = C.damage_charge(
        checkout_rating, condition_rating, reservation["damage_waiver_opted"],
        rate_card["loss_fee_cents"],
    )
    assessment = store.create_damage_assessment(
        reservation_id=id,
        checkin_report_id=checkin_report["id"],
        outcome=outcome,
        charge_cents=charge,
        waiver_applied=waiver_applied,
        status="ASSESSED",
    )

    # final settlement total uses the assessment's damage charge
    final_total, _rental, _basis = C.final_settlement(
        reservation, rate_card, gear_type, late, charge
    )
    reservation["final_total_cents"] = final_total
    store.touch(reservation)

    # unit: CHECKED_OUT -> INSPECTING; condition set from CHECKIN rating;
    # if LOST -> RETIRED with active_reservation_id cleared.
    unit["condition"] = condition_rating
    if condition_rating == "LOST":
        unit["availability"] = "RETIRED"
        unit["active_reservation_id"] = None
    else:
        unit["availability"] = "INSPECTING"
    store.touch(unit)

    # recompute customer standing (provisional variant) — cascade
    C.recompute_customer_standing(customer)
    store.touch(customer)

    return ok(S.reservation(reservation))


# ----------------------------------------------------------------------------
# Settle (RETURNED -> CLOSED)
# ----------------------------------------------------------------------------

@bp.post("/rental/reservations/<id>/settle")
def settle(id):
    _, role = M.get_auth()
    M.require_role(role, {"RentalAgent"})
    reservation = db.reservations.get(id)
    if not reservation:
        raise errors.not_found("reservation not found")

    # state: RETURNED -> CLOSED
    if reservation["lifecycle_status"] != "RETURNED":
        raise errors.invalid_state("reservation is not RETURNED")

    unit = db.gear_units.get(reservation["gear_unit_id"])
    rate_card = _rate_card_for_reservation(reservation)
    customer = db.customers.get(reservation["customer_id"])

    # locate the assessment for this reservation
    assessment = None
    for da in db.damage_assessments.values():
        if da["reservation_id"] == id:
            assessment = da
    # priority 11: cannot settle while DISPUTED
    if assessment is not None and assessment["status"] == "DISPUTED":
        raise errors.assessment_disputed("assessment is DISPUTED")

    # recompute the rental portion on actual usage (independent of damage/late)
    gear_type = db.gear_types.get(unit["gear_type_id"]) if unit else None
    rental_cents, waiver_cents, _basis = C.tiered_rental(
        rate_card,
        gear_type["category"],
        reservation["picked_up_at"],
        reservation["returned_at"],
        reservation["picked_up_at"],
        reservation["damage_waiver_opted"],
    )
    addons_total = C.addons_total(id)
    rental_portion = rental_cents + waiver_cents + addons_total

    # lifecycle + payment + assessment status
    reservation["lifecycle_status"] = "CLOSED"
    reservation["payment_status"] = "SETTLED"
    store.touch(reservation)

    if assessment is not None:
        assessment["status"] = "SETTLED"
        store.touch(assessment)

    # post RENTAL_CHARGE
    store.create_ledger_entry(id, reservation["customer_id"], "RENTAL_CHARGE", rental_portion)
    # LATE_FEE
    if reservation["late_fee_cents"] and reservation["late_fee_cents"] > 0:
        store.create_ledger_entry(id, reservation["customer_id"], "LATE_FEE", reservation["late_fee_cents"])
    # DAMAGE_FEE / LOSS_FEE
    loss_fee_posted = False
    if assessment is not None:
        if assessment["outcome"] == "DAMAGE" and assessment["charge_cents"] > 0:
            store.create_ledger_entry(id, reservation["customer_id"], "DAMAGE_FEE", assessment["charge_cents"])
        elif assessment["outcome"] == "LOSS":
            store.create_ledger_entry(id, reservation["customer_id"], "LOSS_FEE", assessment["charge_cents"])
            loss_fee_posted = True

    # release deposit unless absorbed by an open LOSS_FEE
    if reservation["deposit_cents"] > 0 and not loss_fee_posted:
        store.create_ledger_entry(
            id, reservation["customer_id"], "DEPOSIT_REFUND", -reservation["deposit_cents"]
        )

    # unit leaves inspection: INSPECTING -> AVAILABLE (GOOD/WORN) or
    # MAINTENANCE (DAMAGED). A RETIRED unit (LOST) stays retired.
    if unit is not None and unit["availability"] == "INSPECTING":
        if unit["condition"] == "DAMAGED":
            unit["availability"] = "MAINTENANCE"
        else:
            unit["availability"] = "AVAILABLE"
        unit["active_reservation_id"] = None
        store.touch(unit)

    # recompute customer standing (final variant) — cascade
    C.recompute_customer_standing(customer)
    store.touch(customer)

    return ok(S.reservation(reservation))


# ----------------------------------------------------------------------------
# Cancel (QUOTED|CONFIRMED -> CANCELLED)
# ----------------------------------------------------------------------------

@bp.post("/rental/reservations/<id>/cancel")
def cancel(id):
    user_id, role = M.get_auth()
    M.require_role(role, {"Renter", "RentalAgent"})
    reservation = db.reservations.get(id)
    if not reservation:
        raise errors.not_found("reservation not found")
    _owns(role, user_id, reservation)

    # state: only QUOTED or CONFIRMED can cancel
    if reservation["lifecycle_status"] not in ("QUOTED", "CONFIRMED"):
        raise errors.invalid_state("reservation cannot be cancelled in its current state")

    unit = db.gear_units.get(reservation["gear_unit_id"])
    customer = db.customers.get(reservation["customer_id"])

    reservation["lifecycle_status"] = "CANCELLED"

    # release unit RESERVED -> AVAILABLE; clear back-pointer
    if unit is not None and unit["availability"] == "RESERVED":
        unit["availability"] = "AVAILABLE"
        unit["active_reservation_id"] = None
        store.touch(unit)

    # refund deposit if held
    if reservation["payment_status"] == "DEPOSIT_HELD":
        store.create_ledger_entry(
            id, reservation["customer_id"], "DEPOSIT_REFUND", -reservation["deposit_cents"]
        )
        reservation["payment_status"] = "REFUNDED"

    store.touch(reservation)

    # re-run standing derivation (two-pass also re-run on cancel)
    if customer is not None:
        C.recompute_customer_standing(customer)
        store.touch(customer)

    return ok(S.reservation(reservation))
