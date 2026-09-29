"""Derived-field recomputation and the multi-hop cascades (PRD 2.6, 3.x)."""
import calc
import db
from db import touch
from util import add_days


# --- lookups ---------------------------------------------------------------
def model_of(unit):
    if not unit.get("model_spec_id"):
        return None
    return db.db.model_specs.get(unit["model_spec_id"])


def shipment_of(unit):
    return db.db.intake_shipments.get(unit["intake_shipment_id"])


def account_of(shipment):
    if shipment is None:
        return None
    return db.db.customer_accounts.get(shipment["customer_account_id"])


def account_of_unit(unit):
    return account_of(shipment_of(unit))


# --- CustomerAccount -------------------------------------------------------
def refresh_waiver_status(account):
    account["liability_waiver_status"] = calc.waiver_status(account)


def bump_open_shipments(account, delta):
    """PRD 3.1: the recall clock is armed when the last open shipment closes."""
    if account is None:
        return
    account["open_shipment_count"] = (account["open_shipment_count"] or 0) + delta
    if account["open_shipment_count"] == 0:
        account["loaner_recall_due_at"] = add_days(db.now(),
                                                   calc.LOANER_RECALL_GRACE_DAYS)
    elif account["open_shipment_count"] > 0:
        account["loaner_recall_due_at"] = None
    touch(account)


# --- IntakeShipment --------------------------------------------------------
def refresh_units_registered(shipment):
    shipment["units_registered"] = sum(
        1 for u in db.db.equipment_units.values()
        if u["intake_shipment_id"] == shipment["id"])


def start_processing(shipment):
    """ACCEPTED -> IN_PROCESS on the first unit that leaves RECEIVED."""
    if shipment is not None and shipment["status"] == "ACCEPTED":
        shipment["status"] = "IN_PROCESS"
        touch(shipment)


def maybe_ready_for_return(shipment):
    """IN_PROCESS -> READY_FOR_RETURN once nothing is left in process."""
    if shipment is None:
        return
    if shipment["status"] != "IN_PROCESS":
        return
    if shipment["units_in_process"] != 0:
        return
    shipment["status"] = "READY_FOR_RETURN"
    touch(shipment)
    bump_open_shipments(account_of(shipment), -1)


def revert_to_in_process(shipment):
    """READY_FOR_RETURN -> IN_PROCESS when a void reopens work."""
    if shipment is None:
        return
    if shipment["status"] != "READY_FOR_RETURN":
        return
    if shipment["settlement_locked"]:
        return
    shipment["status"] = "IN_PROCESS"
    shipment["settlement_locked"] = False
    shipment["final_total_cents"] = None
    touch(shipment)
    bump_open_shipments(account_of(shipment), 1)


# --- EquipmentUnit derived fields -----------------------------------------
def refresh_unit_age(unit):
    model = model_of(unit)
    if model is None or unit.get("manufacture_date") is None or not unit.get("age_basis"):
        unit["service_age_years"] = None
        unit["life_expired"] = False
        unit["warranty_coverage"] = "PENDING"
        return
    years = calc.unit_service_age(unit["manufacture_date"], unit["age_basis"],
                                 db.now())
    unit["service_age_years"] = years
    unit["life_expired"] = years >= model["max_service_life_years"]
    unit["warranty_coverage"] = calc.warranty_coverage(years,
                                                       model["warranty_years"])


def refresh_inspection_summary(unit):
    unit["inspection_verdict_summary"] = calc.inspection_verdict_summary(
        unit, model_of(unit))


def refresh_condemn_required(unit):
    unit["condemn_required"] = calc.condemn_required(unit, model_of(unit))


def refresh_unit_derived(unit):
    refresh_unit_age(unit)
    refresh_inspection_summary(unit)
    refresh_condemn_required(unit)


# --- the four-hop condemnation cascade (PRD 3.6) ---------------------------
def condemn_cascade(unit, condemn_reason):
    """recon CONDEMNED -> custody PENDING_DISPOSAL -> DestructionRecord ->
    shipment counters -> shipment/account rollup."""
    unit["recon_status"] = "CONDEMNED"
    unit["condemn_reason"] = condemn_reason
    # hop 1 — custody axis
    if unit["custody_status"] == "AT_PLANT":
        unit["custody_status"] = "PENDING_DISPOSAL"
    touch(unit)
    # hop 2 — destruction record
    record = db.base_record()
    record.update({
        "equipment_unit_id": unit["id"],
        "condemn_reason_snapshot": condemn_reason,
        "method": None,
        "witness_name": None,
        "witnessed_by_user_id": None,
        "witnessed_at": None,
        "verification_ref": None,
        "verified_by_user_id": None,
        "verified_at": None,
        "status": "PENDING",
    })
    db.db.destruction_records[record["id"]] = record
    # hop 3 — shipment counters
    shipment = shipment_of(unit)
    if shipment is not None:
        shipment["units_in_process"] = (shipment["units_in_process"] or 0) - 1
        shipment["units_condemned"] = (shipment["units_condemned"] or 0) + 1
        touch(shipment)
        # hop 4 — shipment/account rollup
        maybe_ready_for_return(shipment)
    return record


# --- certification / void ledger moves ------------------------------------
def certify_unit_counters(unit):
    shipment = shipment_of(unit)
    if shipment is None:
        return
    shipment["units_in_process"] = (shipment["units_in_process"] or 0) - 1
    shipment["units_certified"] = (shipment["units_certified"] or 0) + 1
    touch(shipment)
    maybe_ready_for_return(shipment)


def void_unit_counters(unit):
    shipment = shipment_of(unit)
    if shipment is None:
        return
    shipment["units_certified"] = (shipment["units_certified"] or 0) - 1
    shipment["units_in_process"] = (shipment["units_in_process"] or 0) + 1
    touch(shipment)
    revert_to_in_process(shipment)


def release_unit_counters(unit):
    shipment = shipment_of(unit)
    if shipment is None:
        return
    shipment["units_certified"] = (shipment["units_certified"] or 0) - 1
    shipment["units_released"] = (shipment["units_released"] or 0) + 1
    touch(shipment)


# --- part stock ledger -----------------------------------------------------
def reserve_part(part, quantity):
    part["on_hand_qty"] -= quantity
    part["reserved_qty"] += quantity
    touch(part)


def consume_part(part, quantity):
    part["reserved_qty"] -= quantity
    part["consumed_qty"] += quantity
    touch(part)


def release_part(part, quantity):
    part["reserved_qty"] -= quantity
    part["on_hand_qty"] += quantity
    touch(part)


def refresh_order_totals(order):
    reserved = 0
    installed = 0
    for line in order["part_lines"]:
        if line["status"] == "RESERVED":
            reserved += line["line_total_cents"]
        elif line["status"] == "INSTALLED":
            installed += line["line_total_cents"]
    order["reserved_parts_cents"] = reserved
    order["installed_parts_cents"] = installed


# --- loaner status ---------------------------------------------------------
def refresh_loaner_status(loaner):
    if loaner is None:
        return
    new_status = calc.derived_loaner_status(loaner["id"])
    if loaner["status"] != new_status:
        loaner["status"] = new_status
        touch(loaner)
