"""Agreement open/return/close side effects (PRD §3.5, §3.6, §3.8)."""
from db import DB

from . import calculations as calc
from .common import new_record, touch, clock_date_str
from .ledger import post_entry, recompute_balance


def open_agreement(reservation, unit, catalog_item, rate_card):
    """Open a RentalAgreement in ON_RENT and move the unit ON_RENT (PRD §3.5).

    Shared by dispatch and pickup. Sets unit ON_RENT, fuel to capacity, bumps the
    unit version, opens the agreement, and advances the reservation to ON_RENT.
    """
    clock_date = clock_date_str()

    # Unit goes ON_RENT, dispatched full (PRD §3.5).
    unit["availability_state"] = "ON_RENT"
    unit["fuel_level_liters"] = catalog_item["fuel_capacity_liters"]
    touch(unit)

    agreement = new_record({
        "reservation_id": reservation["id"],
        "equipment_unit_id": unit["id"],
        "contractor_account_id": reservation["contractor_account_id"],
        "agreement_state": "ON_RENT",
        "actual_start_date": clock_date,
        "scheduled_end_date": reservation["rental_end_date"],
        "actual_return_date": None,
        "deposit_held_cents": rate_card["deposit_cents"],
        "final_rental_cents": None,
        "late_fee_cents": None,
        "final_total_cents": None,
    })
    DB.rental_agreements[agreement["id"]] = agreement

    # Reservation tracks the live rental: -> ON_RENT (PRD §3.5).
    reservation["reservation_state"] = "ON_RENT"
    touch(reservation)
    return agreement


def mark_return(agreement, rate_card):
    """ON_RENT -> RETURNED_PENDING_INSPECTION (PRD §3.6).

    Stamps actual_return_date and computes final_rental_cents + late_fee_cents.
    """
    clock_date = clock_date_str()
    agreement["agreement_state"] = "RETURNED_PENDING_INSPECTION"
    agreement["actual_return_date"] = clock_date
    agreement["final_rental_cents"] = calc.final_rental_cents(
        agreement["actual_start_date"], clock_date,
        agreement["scheduled_end_date"], rate_card)
    agreement["late_fee_cents"] = calc.late_fee_cents(
        clock_date, agreement["scheduled_end_date"], rate_card)
    touch(agreement)


def close_agreement(agreement, reservation, inspection, unit, catalog_item, rate_card):
    """Close the agreement at inspection: compute final_total, post ledger lines,
    settle the account, fulfill the reservation, and reconcile the unit
    (PRD §3.6, §3.8).

    Returns (damage_charge_or_None,).
    """
    waiver_opted = reservation.get("damage_waiver_opted", False)
    gross = inspection["damage_assessed_cents"]
    net_damage = calc.net_damage_cents(gross, waiver_opted)

    # Fuel refill (PRD §3.8): dispatch level == capacity.
    fuel_refill = calc.fuel_refill_cents(
        inspection["return_fuel_level_liters"],
        catalog_item["fuel_capacity_liters"], rate_card)
    inspection["fuel_refill_cents"] = fuel_refill
    inspection["net_damage_cents"] = net_damage

    # Final interval billed days for the waiver amount (PRD §3.8).
    final_days = calc.final_interval_days(
        agreement["actual_start_date"], agreement["actual_return_date"],
        agreement["scheduled_end_date"])
    waiver_cents = (rate_card["damage_waiver_daily_cents"] * final_days
                    if waiver_opted else 0)
    cleaning_cents = (rate_card["cleaning_fee_cents"]
                      if inspection["cleanliness"] == "DIRTY" else 0)

    final_rental = agreement["final_rental_cents"]
    late_fee = agreement["late_fee_cents"]
    deposit_refund = agreement["deposit_held_cents"]

    agreement["final_total_cents"] = calc.final_total_cents(
        final_rental, waiver_cents, late_fee, fuel_refill,
        cleaning_cents, net_damage, deposit_refund)

    # Agreement state branches on NET damage (PRD §3.6).
    damage_charge = None
    if net_damage > 0:
        agreement["agreement_state"] = "CLOSED_WITH_DAMAGE"
        damage_charge = new_record({
            "rental_agreement_id": agreement["id"],
            "return_inspection_id": inspection["id"],
            "gross_cents": gross,
            "waiver_applied": waiver_opted,
            "net_cents": net_damage,
        }, full_common=False)
        DB.damage_charges[damage_charge["id"]] = damage_charge
    else:
        agreement["agreement_state"] = "CLOSED"

    # Post settlement ledger lines (PRD §3.6). Order: RENTAL_CHARGE, LATE_FEE?,
    # FUEL_CHARGE?, CLEANING_CHARGE?, DAMAGE_CHARGE?, DEPOSIT_REFUND.
    account_id = agreement["contractor_account_id"]
    aid = agreement["id"]
    post_entry(account_id, "RENTAL_CHARGE", final_rental, rental_agreement_id=aid)
    if late_fee > 0:
        post_entry(account_id, "LATE_FEE", late_fee, rental_agreement_id=aid)
    if fuel_refill > 0:
        post_entry(account_id, "FUEL_CHARGE", fuel_refill, rental_agreement_id=aid)
    if cleaning_cents > 0:
        post_entry(account_id, "CLEANING_CHARGE", cleaning_cents, rental_agreement_id=aid)
    if net_damage > 0:
        post_entry(account_id, "DAMAGE_CHARGE", net_damage, rental_agreement_id=aid)
    post_entry(account_id, "DEPOSIT_REFUND", -deposit_refund, rental_agreement_id=aid)
    recompute_balance(account_id)

    touch(agreement)

    # Reservation -> FULFILLED (PRD §3.6).
    reservation["reservation_state"] = "FULFILLED"
    touch(reservation)

    # Reconcile the unit and service threshold (PRD §3.6). "This agreement's
    # billed days" is the billed days of the actual (final) rental interval.
    this_billed = final_days
    pre_lifetime = unit["lifetime_rental_days"]
    unit["lifetime_rental_days"] = pre_lifetime + this_billed

    # Service threshold compares pre-accrual lifetime + billed against the
    # threshold (SCAFFOLD §1.2 / PRD §3.6).
    reaches_service = (pre_lifetime + this_billed) >= unit["service_due_at_days"]

    if gross == 0 and not reaches_service:
        # Healthy return below threshold: back to the pool (PRD §3.6).
        unit["availability_state"] = "AVAILABLE"
        touch(unit)
    else:
        # Damage assessed (>0) OR service threshold reached -> OUT_OF_SERVICE.
        unit["availability_state"] = "OUT_OF_SERVICE"
        touch(unit)
        reason = "DAMAGE_REPAIR" if gross > 0 else "SCHEDULED_SERVICE"
        ticket = new_record({
            "equipment_unit_id": unit["id"],
            "reason": reason,
            "ticket_state": "OPEN",
            "opened_by_agreement_id": agreement["id"],
        })
        DB.maintenance_tickets[ticket["id"]] = ticket

    return damage_charge
