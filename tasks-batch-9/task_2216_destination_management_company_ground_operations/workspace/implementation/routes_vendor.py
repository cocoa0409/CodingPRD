"""Venue, supplier and supplier-contract endpoints."""

from flask import Blueprint

import calc
import cascades
import derive
import serializers
from auth import (ALL_DMC_ROLES, ALL_ROLES, ROLE_PROGRAM_DIRECTOR, ROLE_SUPPLIER,
                  ROLE_SUPPLIER_MANAGER, current_user_id, endpoint)
from common import (apply_filters, contract_or_404, program_or_404, respond_list,
                    supplier_or_404, venue_or_404)
from envelope import created, ok
from errors import fail
from store import clock_now, db, new_row, touch
from validation import (body, opt_bool, opt_enum, opt_int, opt_num, opt_str, ref_id,
                        req_enum, req_dt, req_int, req_str)

bp = Blueprint("vendor", __name__)

VENUE_STATUSES = ("ACTIVE", "SUSPENDED")
SUPPLIER_TYPES = ("VENUE_SERVICES", "TRANSPORT", "ACTIVITY", "STAFFING")
SUPPLIER_STATUSES = ("PROSPECT", "APPROVED", "SUSPENDED")
CONTRACT_STATUSES = ("DRAFT", "SENT", "COUNTERED", "ACTIVE", "CLOSED", "TERMINATED")
CANCELLATION_TIERS = ("STANDARD", "STRICT")


# --------------------------------------------------------------------------
# venues
# --------------------------------------------------------------------------

@bp.post("/dmc/venues")
@endpoint((ROLE_PROGRAM_DIRECTOR,))
def create_venue():
    data = body()
    row = new_row(
        name=req_str(data, "name", min_len=1),
        capacity_seated=req_int(data, "capacity_seated", minimum=0),
        capacity_reception=req_int(data, "capacity_reception", minimum=0),
        turnover_buffer_minutes=opt_int(data, "turnover_buffer_minutes", default=90,
                                        minimum=0),
        requires_special_venue_permit=opt_bool(data, "requires_special_venue_permit",
                                               default=False),
        status=opt_enum(data, "status", VENUE_STATUSES, default="ACTIVE"),
    )
    if row["turnover_buffer_minutes"] is None:
        row["turnover_buffer_minutes"] = 90
    db.venues[row["id"]] = row
    return created(serializers.venue(row))


@bp.get("/dmc/venues/<venue_id>")
@endpoint(ALL_DMC_ROLES)
def read_venue(venue_id):
    return ok(serializers.venue(venue_or_404(venue_id)))


@bp.get("/dmc/venues")
@endpoint(ALL_DMC_ROLES)
def list_venues():
    rows = apply_filters(list(db.venues.values()),
                         [("status", "status", VENUE_STATUSES)])
    return respond_list(rows, serializers.venue)


# --------------------------------------------------------------------------
# suppliers
# --------------------------------------------------------------------------

@bp.post("/dmc/suppliers")
@endpoint((ROLE_SUPPLIER_MANAGER,))
def create_supplier():
    data = body()
    row = new_row(
        legal_name=req_str(data, "legal_name", min_len=1),
        supplier_type=req_enum(data, "supplier_type", SUPPLIER_TYPES),
        insurance_expires_on=req_dt(data, "insurance_expires_on"),
        insurance_liability_limit_cents=req_int(data, "insurance_liability_limit_cents",
                                                minimum=0),
        coi_verified=opt_bool(data, "coi_verified", default=False),
        status=opt_enum(data, "status", SUPPLIER_STATUSES, default="PROSPECT"),
    )
    db.suppliers[row["id"]] = row
    return created(serializers.supplier(row))


@bp.patch("/dmc/suppliers/<supplier_id>")
@endpoint((ROLE_SUPPLIER_MANAGER,))
def patch_supplier(supplier_id):
    supplier = supplier_or_404(supplier_id)
    data = body()
    if "insurance_expires_on" in data:
        supplier["insurance_expires_on"] = req_dt(data, "insurance_expires_on")
    if "insurance_liability_limit_cents" in data:
        supplier["insurance_liability_limit_cents"] = req_int(
            data, "insurance_liability_limit_cents", minimum=0)
    if "coi_verified" in data:
        supplier["coi_verified"] = opt_bool(data, "coi_verified",
                                            default=supplier["coi_verified"])
    if "status" in data:
        supplier["status"] = req_enum(data, "status", SUPPLIER_STATUSES)
    touch(supplier)
    return ok(serializers.supplier(supplier))


@bp.get("/dmc/suppliers/<supplier_id>")
@endpoint(ALL_DMC_ROLES)
def read_supplier(supplier_id):
    return ok(serializers.supplier(supplier_or_404(supplier_id)))


@bp.get("/dmc/suppliers")
@endpoint(ALL_DMC_ROLES)
def list_suppliers():
    rows = apply_filters(list(db.suppliers.values()), [
        ("supplier_type", "supplier_type", SUPPLIER_TYPES),
        ("status", "status", SUPPLIER_STATUSES),
    ])
    return respond_list(rows, serializers.supplier)


# --------------------------------------------------------------------------
# supplier contracts
# --------------------------------------------------------------------------

def _insurance_ok(supplier, contract):
    if not supplier["coi_verified"]:
        return False
    if supplier["insurance_expires_on"] < clock_now():
        return False
    return (int(supplier["insurance_liability_limit_cents"])
            >= int(contract["required_liability_limit_cents"]))


@bp.post("/dmc/supplier-contracts")
@endpoint((ROLE_SUPPLIER_MANAGER,))
def create_contract():
    data = body()
    program_ref = ref_id(data, "program_id")
    if program_ref is not None:
        program_or_404(program_ref)
    supplier_ref = ref_id(data, "supplier_id")
    if supplier_ref is not None:
        supplier_or_404(supplier_ref)

    program_id = req_str(data, "program_id", min_len=1)
    supplier_id = req_str(data, "supplier_id", min_len=1)
    row = new_row(
        program_id=program_id,
        supplier_id=supplier_id,
        contract_value_cents=req_int(data, "contract_value_cents", minimum=1),
        required_liability_limit_cents=req_int(data, "required_liability_limit_cents",
                                              minimum=0),
        deposit_pct=opt_num(data, "deposit_pct", default=0.3, minimum=0, maximum=1),
        cancellation_tier=opt_enum(data, "cancellation_tier", CANCELLATION_TIERS,
                                   default="STANDARD"),
        status="DRAFT",
        round_count=0,
        deposit_due_cents=0,
        deposit_paid_cents=0,
        sent_by_user_id=None,
        countersigned_by_user_id=None,
    )
    db.contracts[row["id"]] = row
    return created(serializers.contract(row))


@bp.get("/dmc/supplier-contracts/<contract_id>")
@endpoint(ALL_ROLES)
def read_contract(contract_id):
    return ok(serializers.contract(contract_or_404(contract_id)))


@bp.get("/dmc/supplier-contracts")
@endpoint(ALL_ROLES)
def list_contracts():
    rows = apply_filters(list(db.contracts.values()), [
        ("program_id", "program_id", None),
        ("supplier_id", "supplier_id", None),
        ("status", "status", CONTRACT_STATUSES),
    ])
    return respond_list(rows, serializers.contract)


@bp.post("/dmc/supplier-contracts/<contract_id>/send")
@endpoint((ROLE_SUPPLIER_MANAGER,))
def send_contract(contract_id):
    contract = contract_or_404(contract_id)
    if contract["status"] not in ("DRAFT", "COUNTERED"):
        fail("ERR_INVALID_STATE_TRANSITION", "send requires status DRAFT or COUNTERED.")
    supplier = db.suppliers.get(contract["supplier_id"])
    if contract["status"] == "DRAFT":
        if supplier is None or not _insurance_ok(supplier, contract):
            fail("ERR_SUPPLIER_INSURANCE_INSUFFICIENT",
                 "The supplier's certificate of insurance does not satisfy this contract.")
        if supplier["status"] != "APPROVED":
            fail("ERR_SUPPLIER_NOT_APPROVED", "The supplier is not APPROVED.")
    if int(contract["round_count"]) >= calc.MAX_NEGOTIATION_ROUNDS:
        fail("ERR_NEGOTIATION_ROUNDS_EXHAUSTED",
             "The negotiation round ceiling has been reached.")

    contract["status"] = "SENT"
    contract["sent_by_user_id"] = current_user_id()
    contract["round_count"] = int(contract["round_count"]) + 1
    touch(contract)
    return ok(serializers.contract(contract))


@bp.post("/dmc/supplier-contracts/<contract_id>/counter")
@endpoint((ROLE_SUPPLIER,))
def counter_contract(contract_id):
    contract = contract_or_404(contract_id)
    if current_user_id() != contract["supplier_id"]:
        fail("ERR_NOT_RESOURCE_OWNER",
             "A supplier may only counter its own contract.")
    data = body()
    countered_value_cents = req_int(data, "countered_value_cents", minimum=1)
    if contract["status"] != "SENT":
        fail("ERR_INVALID_STATE_TRANSITION", "counter requires status SENT.")
    if int(contract["round_count"]) >= calc.MAX_NEGOTIATION_ROUNDS:
        fail("ERR_NEGOTIATION_ROUNDS_EXHAUSTED",
             "The negotiation round ceiling has been reached.")

    contract["status"] = "COUNTERED"
    contract["contract_value_cents"] = countered_value_cents
    touch(contract)
    return ok(serializers.contract(contract))


@bp.post("/dmc/supplier-contracts/<contract_id>/countersign")
@endpoint((ROLE_SUPPLIER_MANAGER,))
def countersign_contract(contract_id):
    contract = contract_or_404(contract_id)
    if contract["status"] not in ("SENT", "COUNTERED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "countersign requires status SENT or COUNTERED.")
    supplier = db.suppliers.get(contract["supplier_id"])
    if supplier is None or not _insurance_ok(supplier, contract):
        fail("ERR_SUPPLIER_INSURANCE_INSUFFICIENT",
             "The supplier's certificate of insurance does not satisfy this contract.")
    if current_user_id() == contract["sent_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The countersigner must differ from the sender.")

    contract["status"] = "ACTIVE"
    contract["countersigned_by_user_id"] = current_user_id()
    deposit_due = calc.cents(calc.dec(contract["contract_value_cents"])
                             * calc.dec(contract["deposit_pct"]))
    contract["deposit_due_cents"] = deposit_due
    contract["deposit_paid_cents"] = deposit_due
    touch(contract)
    return ok(serializers.contract(contract))


@bp.post("/dmc/supplier-contracts/<contract_id>/terminate")
@endpoint((ROLE_SUPPLIER_MANAGER,))
def terminate_contract(contract_id):
    contract = contract_or_404(contract_id)
    body()
    if contract["status"] not in ("DRAFT", "SENT", "COUNTERED", "ACTIVE"):
        fail("ERR_INVALID_STATE_TRANSITION", "The contract can no longer be terminated.")
    for payment in derive.payments_of_contract(contract_id):
        if payment["status"] in ("APPROVED", "PAID"):
            fail("ERR_SETTLEMENT_ALREADY_PAID",
                 "A settlement payment against this contract has already moved.")

    contract["status"] = "TERMINATED"
    contract["deposit_paid_cents"] = 0
    program = db.programs.get(contract["program_id"])
    for element in derive.elements_of_program(contract["program_id"]):
        if element["supplier_id"] == contract["supplier_id"]:
            cascades.cancel_element(element, program)
    touch(contract)
    return ok(serializers.contract(contract))
