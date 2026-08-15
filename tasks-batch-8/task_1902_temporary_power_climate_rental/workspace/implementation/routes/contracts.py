"""Rental contracts and rental lines: lifecycle, OCC, cascades (PRD 3.3-3.5, 3.9)."""
from flask import Blueprint, request

from auth import (
    auth,
    body,
    check_customer_owns,
    customer_scope_filter,
    get_or_404,
    require_roles,
)
from calc import (
    CONTRACT_TERMINAL,
    LINE_TERMINAL,
    accrual_cents,
    emissions_screening,
    finalize_line,
    invoice_total,
    jurisdiction_cap,
    load_sizing,
    release_contract_reservations,
    required_amps,
    technician_conflict,
    windows_overlap,
)
from db import DB, contract_out, line_out, touch
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_CREDIT_HOLD,
    ERR_EMISSIONS_TIER_NONCOMPLIANT,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_STATE,
    ERR_KIT_UNDERSIZED,
    ERR_LOAD_PROFILE_EMPTY,
    ERR_NOT_FOUND,
    ERR_NOT_OWNER,
    ERR_OPEN_INCIDENTS,
    ERR_PERMIT_REQUIRED,
    ERR_REFERENCE_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_UNDERSIZED_FLEET,
    ERR_UNIT_RESERVED_CONFLICT,
    ERR_VALIDATION,
    raise_err,
)
from response import success_object
from routes.common import paginate
from util import D, as_decimal, as_int, new_id, now, parse_ts

bp = Blueprint("contracts", __name__)

LOAD_TYPES = {"CONTINUOUS", "INTERMITTENT", "STANDBY"}
SIZING_METHODS = {"NAMEPLATE_SUM", "DIVERSIFIED_DEMAND"}
LINE_TYPES = {"EQUIPMENT", "ACCESSORY_KIT"}
OCC_FIELD = "expected_rental_contract_version"


def _owning_customer(contract):
    return DB.customers[contract["customer_id"]]


def _check_contract_actionable(contract, allowed_from):
    """Tier 4 state gate: terminal lockdown, then valid from-state."""
    if contract["status"] in CONTRACT_TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "Contract %s is terminal (%s)." % (contract["id"], contract["status"]))
    if contract["status"] not in allowed_from:
        raise_err(
            ERR_INVALID_STATE,
            "Contract in %s cannot perform this transition." % contract["status"],
        )


def _check_credit(contract):
    """Tier 9 fiscal gate, evaluated last (PRD 2.8)."""
    if _owning_customer(contract)["credit_status"] == "HOLD":
        raise_err(ERR_CREDIT_HOLD, "Customer is on credit hold.")


# ---------------------------------------------------------------------------
# Contract creation and reads
# ---------------------------------------------------------------------------

@bp.post("/power-rental/rental-contracts")
def create_contract():
    uid, role = auth()
    require_roles(role, ["SalesEngineer", "Customer"])
    b = body()
    customer_id = b.get("customer_id")
    site_id = b.get("site_id")
    # Tier 2 ownership: Customer may create only for its own customer_id.
    if role == "Customer" and customer_id is not None and customer_id != uid:
        raise_err(ERR_NOT_OWNER, "Customers may only create contracts for themselves.")
    # Tier 3: body FK existence.
    if customer_id is not None and customer_id not in DB.customers:
        raise_err(ERR_REFERENCE_NOT_FOUND, "customer_id references a non-existent customer.")
    if site_id is not None and site_id not in DB.sites:
        raise_err(ERR_REFERENCE_NOT_FOUND, "site_id references a non-existent site.")
    # Tier 7: payload well-formedness.
    if customer_id is None:
        raise_err(ERR_VALIDATION, "customer_id is required.")
    if site_id is None:
        raise_err(ERR_VALIDATION, "site_id is required.")
    load_profile = b.get("load_profile")
    if not isinstance(load_profile, list):
        raise_err(ERR_VALIDATION, "load_profile must be an array.")
    for entry in load_profile:
        if not isinstance(entry, dict):
            raise_err(ERR_VALIDATION, "load_profile entries must be objects.")
        if entry.get("load_type") not in LOAD_TYPES:
            raise_err(ERR_VALIDATION, "load_type must be CONTINUOUS, INTERMITTENT, or STANDBY.")
        kw = as_decimal(entry.get("nameplate_kw"))
        if kw is None or kw <= 0:
            raise_err(ERR_VALIDATION, "nameplate_kw must be a positive number.")
    start = parse_ts(b.get("start_date"))
    end = parse_ts(b.get("expected_offhire_date"))
    if start is None:
        raise_err(ERR_VALIDATION, "start_date must be an ISO 8601 timestamp.")
    if end is None:
        raise_err(ERR_VALIDATION, "expected_offhire_date must be an ISO 8601 timestamp.")
    if not start < end:
        raise_err(ERR_INVALID_DATE_RANGE, "start_date must be strictly before expected_offhire_date.")
    ts = now()
    rec = {
        "id": new_id(),
        "customer_id": customer_id,
        "site_id": site_id,
        "load_profile": [
            {"load_type": e["load_type"], "nameplate_kw": e["nameplate_kw"]}
            for e in load_profile
        ],
        "sizing_method": None,
        "sized_kw": None,
        "status": "DRAFT",
        "start_date": start,
        "expected_offhire_date": end,
        "quoted_at": None,
        "quoted_total_cents": None,
        "on_rent_at": None,
        "actual_offhire_at": None,
        "invoice_total_cents": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": DB.next_seq(),
    }
    DB.contracts[rec["id"]] = rec
    return success_object(contract_out(rec), status=201)


@bp.get("/power-rental/rental-contracts/<cid>")
def get_contract(cid):
    uid, role = auth()
    require_roles(role, ["SalesEngineer", "Customer", "DepotManager", "FleetDispatcher", "ClaimsAssessor", "FieldTechnician"])
    rec = DB.contracts.get(cid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "No contract exists with id %s." % cid)
    if role == "Customer":
        check_customer_owns(rec["customer_id"], uid)
    return success_object(contract_out(rec))


@bp.get("/power-rental/rental-contracts")
def list_contracts():
    uid, role = auth()
    require_roles(role, ["SalesEngineer", "Customer", "DepotManager"])
    records = list(DB.contracts.values())
    scoped = customer_scope_filter(role, uid)
    if scoped is not None:
        records = [r for r in records if r["customer_id"] == scoped]
    elif request.args.get("customer_id") is not None:
        records = [r for r in records if r["customer_id"] == request.args.get("customer_id")]
    if request.args.get("site_id") is not None:
        records = [r for r in records if r["site_id"] == request.args.get("site_id")]
    if request.args.get("status") is not None:
        records = [r for r in records if r["status"] == request.args.get("status")]
    return paginate(records, contract_out)


# ---------------------------------------------------------------------------
# Sizing, quoting, confirmation, cancellation
# ---------------------------------------------------------------------------

@bp.post("/power-rental/rental-contracts/<cid>/size-load")
def size_load(cid):
    uid, role = auth()
    require_roles(role, ["SalesEngineer"])
    contract = get_or_404(DB.contracts, cid, "contract")
    _check_contract_actionable(contract, {"DRAFT"})
    b = body()
    method = b.get("sizing_method")
    if method not in SIZING_METHODS:
        raise_err(ERR_VALIDATION, "sizing_method must be NAMEPLATE_SUM or DIVERSIFIED_DEMAND.")
    if not contract["load_profile"]:
        raise_err(ERR_LOAD_PROFILE_EMPTY, "load_profile is empty; nothing to size.")
    contract["sized_kw"] = load_sizing(contract["load_profile"], method)
    contract["sizing_method"] = method
    touch(contract, now())
    return success_object(contract_out(contract))


@bp.post("/power-rental/rental-contracts/<cid>/quote")
def quote_contract(cid):
    uid, role = auth()
    require_roles(role, ["SalesEngineer"])
    contract = get_or_404(DB.contracts, cid, "contract")
    _check_contract_actionable(contract, {"DRAFT"})
    lines = [l for l in DB.lines.values() if l["contract_id"] == cid]
    equipment_capacity = 0
    for line in lines:
        if line["line_type"] != "EQUIPMENT":
            continue
        unit = DB.units.get(line["equipment_unit_id"])
        if unit is not None:
            equipment_capacity += unit["capacity_kw"]
    if contract["sized_kw"] is None or not lines or equipment_capacity < contract["sized_kw"]:
        raise_err(ERR_UNDERSIZED_FLEET, "Quote requires sized_kw, at least one line, and fleet capacity >= sized_kw.")
    _check_credit(contract)
    ts = now()
    total = 0
    for line in lines:
        if line["status"] != "PENDING":
            continue
        total += accrual_cents(line, contract["start_date"], contract["expected_offhire_date"])
    contract["quoted_total_cents"] = total
    contract["quoted_at"] = ts
    contract["status"] = "QUOTED"
    touch(contract, ts)
    return success_object(contract_out(contract))


@bp.post("/power-rental/rental-contracts/<cid>/revise")
def revise_contract(cid):
    uid, role = auth()
    require_roles(role, ["SalesEngineer"])
    contract = get_or_404(DB.contracts, cid, "contract")
    _check_contract_actionable(contract, {"QUOTED"})
    contract["quoted_at"] = None
    contract["quoted_total_cents"] = None
    contract["status"] = "DRAFT"
    touch(contract, now())
    return success_object(contract_out(contract))


@bp.post("/power-rental/rental-contracts/<cid>/confirm")
def confirm_contract(cid):
    uid, role = auth()
    require_roles(role, ["SalesEngineer", "Customer"])
    contract = get_or_404(DB.contracts, cid, "contract")
    if role == "Customer":
        check_customer_owns(contract["customer_id"], uid)
    _check_contract_actionable(contract, {"QUOTED"})
    b = body()
    # Tier 4 OCC — only evaluable when the field is supplied.
    if OCC_FIELD in b and b[OCC_FIELD] is not None:
        if b[OCC_FIELD] != contract["version"]:
            raise_err(ERR_STALE_VERSION, "expected_rental_contract_version does not match the current version.")
    elif OCC_FIELD not in b:
        # Non-optional per PRD 2.7; surfaces at the constraint tier.
        raise_err(ERR_VALIDATION, "expected_rental_contract_version is required.")
    _check_credit(contract)
    contract["status"] = "CONFIRMED"
    touch(contract, now())
    return success_object(contract_out(contract))


@bp.post("/power-rental/rental-contracts/<cid>/cancel")
def cancel_contract(cid):
    uid, role = auth()
    require_roles(role, ["SalesEngineer", "Customer"])
    contract = get_or_404(DB.contracts, cid, "contract")
    if role == "Customer":
        check_customer_owns(contract["customer_id"], uid)
    _check_contract_actionable(contract, {"DRAFT", "QUOTED", "CONFIRMED"})
    ts = now()
    contract["status"] = "CANCELLED"
    touch(contract, ts)
    release_contract_reservations(contract, ts)
    return success_object(contract_out(contract))


# ---------------------------------------------------------------------------
# Mobilization and rent
# ---------------------------------------------------------------------------

@bp.post("/power-rental/rental-contracts/<cid>/mobilize")
def mobilize_contract(cid):
    uid, role = auth()
    require_roles(role, ["DepotManager"])
    contract = get_or_404(DB.contracts, cid, "contract")
    _check_contract_actionable(contract, {"CONFIRMED"})
    site = DB.sites[contract["site_id"]]
    screening = emissions_screening(site)
    has_approved_emissions_permit = any(
        p["contract_id"] == cid and p["permit_type"] == "EMISSIONS" and p["status"] == "APPROVED"
        for p in DB.permits.values()
    )
    if screening["permit_required"] and not has_approved_emissions_permit:
        raise_err(ERR_PERMIT_REQUIRED, "Emissions screening requires an APPROVED EMISSIONS permit before mobilization.")
    contract["status"] = "MOBILIZING"
    touch(contract, now())
    return success_object(contract_out(contract))


@bp.post("/power-rental/rental-contracts/<cid>/start-rental")
def start_rental(cid):
    uid, role = auth()
    require_roles(role, ["DepotManager"])
    contract = get_or_404(DB.contracts, cid, "contract")
    _check_contract_actionable(contract, {"MOBILIZING"})
    ts = now()
    for line in DB.lines.values():
        if line["contract_id"] != cid or line["status"] != "PENDING":
            continue
        line["status"] = "ON_RENT"
        touch(line, ts)
        if line["line_type"] == "EQUIPMENT":
            unit = DB.units.get(line["equipment_unit_id"])
            if unit is not None and unit["status"] == "RESERVED":
                unit["status"] = "DEPLOYED"
                unit["current_site_id"] = contract["site_id"]
                touch(unit, ts)
    contract["status"] = "ON_RENT"
    contract["on_rent_at"] = ts
    touch(contract, ts)
    return success_object(contract_out(contract))


# ---------------------------------------------------------------------------
# Off-hire, close, invoicing
# ---------------------------------------------------------------------------

@bp.post("/power-rental/rental-contracts/<cid>/off-hire")
def off_hire_contract(cid):
    uid, role = auth()
    require_roles(role, ["SalesEngineer", "Customer"])
    contract = get_or_404(DB.contracts, cid, "contract")
    if role == "Customer":
        check_customer_owns(contract["customer_id"], uid)
    _check_contract_actionable(contract, {"ON_RENT"})
    ts = now()
    contract["actual_offhire_at"] = ts
    for line in DB.lines.values():
        if line["contract_id"] == cid and line["status"] == "ON_RENT":
            finalize_line(line, ts)
    contract["status"] = "OFF_HIRE"
    touch(contract, ts)
    return success_object(contract_out(contract))


@bp.post("/power-rental/rental-contracts/<cid>/close")
def close_contract(cid):
    uid, role = auth()
    require_roles(role, ["SalesEngineer"])
    contract = get_or_404(DB.contracts, cid, "contract")
    _check_contract_actionable(contract, {"OFF_HIRE"})
    lines = [l for l in DB.lines.values() if l["contract_id"] == cid]
    if any(l["status"] not in ("OFF_HIRED", "RETURNED") for l in lines):
        raise_err(ERR_INVALID_STATE, "All lines must be OFF_HIRED or RETURNED before close.")
    if any(i["contract_id"] == cid and i["status"] == "REPORTED" for i in DB.incidents.values()):
        raise_err(ERR_OPEN_INCIDENTS, "An incident is still REPORTED on this contract.")
    ts = now()
    total, charged = invoice_total(contract)
    contract["invoice_total_cents"] = total
    for inc in charged:
        inc["status"] = "CHARGED"
        touch(inc, ts)
    contract["status"] = "CLOSED"
    touch(contract, ts)
    return success_object(contract_out(contract))


# ---------------------------------------------------------------------------
# Rental lines
# ---------------------------------------------------------------------------

@bp.post("/power-rental/rental-contracts/<cid>/lines")
def add_line(cid):
    uid, role = auth()
    require_roles(role, ["SalesEngineer"])
    contract = get_or_404(DB.contracts, cid, "contract")
    b = body()
    line_type = b.get("line_type")
    equipment_unit_id = b.get("equipment_unit_id")
    accessory_kit_id = b.get("accessory_kit_id")
    # Tier 3: body FK existence for provided references.
    if equipment_unit_id is not None and equipment_unit_id not in DB.units:
        raise_err(ERR_REFERENCE_NOT_FOUND, "equipment_unit_id references a non-existent unit.")
    if accessory_kit_id is not None and accessory_kit_id not in DB.kits:
        raise_err(ERR_REFERENCE_NOT_FOUND, "accessory_kit_id references a non-existent kit.")
    # Tier 4: state, then OCC.
    _check_contract_actionable(contract, {"DRAFT"})
    if OCC_FIELD in b and b[OCC_FIELD] is not None:
        if b[OCC_FIELD] != contract["version"]:
            raise_err(ERR_STALE_VERSION, "expected_rental_contract_version does not match the current version.")
    unit = DB.units.get(equipment_unit_id) if equipment_unit_id is not None else None
    kit = DB.kits.get(accessory_kit_id) if accessory_kit_id is not None else None
    site = DB.sites[contract["site_id"]]
    # Tier 5: emissions-tier compliance.
    if line_type == "EQUIPMENT" and unit is not None:
        if jurisdiction_cap(site["jurisdiction_code"]) <= 5.0 and unit["emissions_tier"] == "TIER_2":
            raise_err(ERR_EMISSIONS_TIER_NONCOMPLIANT, "TIER_2 units are banned in jurisdictions with cap <= 5.0.")
    # Tier 6: reservation window overlap (half-open).
    if line_type == "EQUIPMENT" and unit is not None:
        for other in DB.lines.values():
            if other["line_type"] != "EQUIPMENT" or other["equipment_unit_id"] != equipment_unit_id:
                continue
            if other["status"] not in ("PENDING", "ON_RENT"):
                continue
            other_contract = DB.contracts.get(other["contract_id"])
            if other_contract is None:
                continue
            if windows_overlap(
                contract["start_date"], contract["expected_offhire_date"],
                other_contract["start_date"], other_contract["expected_offhire_date"],
            ):
                raise_err(ERR_UNIT_RESERVED_CONFLICT, "Unit has an overlapping PENDING/ON_RENT reservation.")
    # Tier 7: payload well-formedness.
    if line_type not in LINE_TYPES:
        raise_err(ERR_VALIDATION, "line_type must be EQUIPMENT or ACCESSORY_KIT.")
    quantity = b.get("quantity", 1)
    if as_int(quantity) is None or as_int(quantity) < 1:
        raise_err(ERR_VALIDATION, "quantity must be an integer >= 1.")
    quantity = as_int(quantity)
    if line_type == "EQUIPMENT":
        if equipment_unit_id is None or accessory_kit_id is not None:
            raise_err(ERR_VALIDATION, "EQUIPMENT lines require equipment_unit_id and a null accessory_kit_id.")
        if quantity != 1:
            raise_err(ERR_VALIDATION, "EQUIPMENT line quantity must be exactly 1.")
    else:
        if accessory_kit_id is None or equipment_unit_id is not None:
            raise_err(ERR_VALIDATION, "ACCESSORY_KIT lines require accessory_kit_id and a null equipment_unit_id.")
    if OCC_FIELD not in b:
        raise_err(ERR_VALIDATION, "expected_rental_contract_version is required.")
    # Tier 7: kit ampacity sizing.
    if line_type == "ACCESSORY_KIT":
        if contract["sized_kw"] is None:
            raise_err(ERR_KIT_UNDERSIZED, "sized_kw must be set before kit lines can be sized.")
        required = required_amps(contract["sized_kw"])
        if quantity * kit["max_ampacity_a"] < required:
            raise_err(ERR_KIT_UNDERSIZED, "Kit quantity * max_ampacity_a is below the required ampacity.")
    # Tier 9: fiscal gate last.
    _check_credit(contract)
    ts = now()
    if line_type == "EQUIPMENT":
        rate_source = unit
        demob = unit["demob_fee_cents"]
    else:
        rate_source = kit
        demob = 0
    rec = {
        "id": new_id(),
        "contract_id": cid,
        "line_type": line_type,
        "equipment_unit_id": equipment_unit_id if line_type == "EQUIPMENT" else None,
        "accessory_kit_id": accessory_kit_id if line_type == "ACCESSORY_KIT" else None,
        "quantity": quantity,
        "day_rate_cents": rate_source["day_rate_cents"],
        "week_rate_cents": rate_source["week_rate_cents"],
        "month_rate_cents": rate_source["month_rate_cents"],
        "demob_fee_cents": demob,
        "status": "PENDING",
        "final_charge_cents": None,
        "offhired_at": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": DB.next_seq(),
    }
    DB.lines[rec["id"]] = rec
    if line_type == "EQUIPMENT" and unit["status"] == "AVAILABLE":
        unit["status"] = "RESERVED"
        touch(unit, ts)
    touch(contract, ts)
    return success_object(line_out(rec), status=201)


@bp.get("/power-rental/rental-lines/<lid>")
def get_line(lid):
    uid, role = auth()
    require_roles(role, ["SalesEngineer", "DepotManager", "Customer"])
    rec = DB.lines.get(lid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "No rental line exists with id %s." % lid)
    if role == "Customer":
        contract = DB.contracts.get(rec["contract_id"])
        check_customer_owns(contract["customer_id"] if contract else None, uid)
    return success_object(line_out(rec))


@bp.get("/power-rental/rental-lines")
def list_lines():
    uid, role = auth()
    require_roles(role, ["SalesEngineer", "DepotManager", "Customer"])
    records = list(DB.lines.values())
    scoped = customer_scope_filter(role, uid)
    if scoped is not None:
        records = [
            r for r in records
            if DB.contracts.get(r["contract_id"]) is not None
            and DB.contracts[r["contract_id"]]["customer_id"] == scoped
        ]
    if request.args.get("contract_id") is not None:
        records = [r for r in records if r["contract_id"] == request.args.get("contract_id")]
    if request.args.get("equipment_unit_id") is not None:
        records = [r for r in records if r["equipment_unit_id"] == request.args.get("equipment_unit_id")]
    if request.args.get("accessory_kit_id") is not None:
        records = [r for r in records if r["accessory_kit_id"] == request.args.get("accessory_kit_id")]
    if request.args.get("status") is not None:
        records = [r for r in records if r["status"] == request.args.get("status")]
    return paginate(records, line_out)


@bp.post("/power-rental/rental-lines/<lid>/off-hire")
def off_hire_line(lid):
    uid, role = auth()
    require_roles(role, ["SalesEngineer", "Customer"])
    line = get_or_404(DB.lines, lid, "rental line")
    contract = DB.contracts.get(line["contract_id"])
    if role == "Customer":
        check_customer_owns(contract["customer_id"] if contract else None, uid)
    if line["status"] in LINE_TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "Line %s is terminal (%s)." % (lid, line["status"]))
    if line["status"] != "ON_RENT":
        raise_err(ERR_INVALID_STATE, "Only an ON_RENT line can be off-hired.")
    if contract is None or contract["status"] not in ("ON_RENT", "SUSPENDED"):
        raise_err(ERR_INVALID_STATE, "Parent contract must be ON_RENT or SUSPENDED for a partial off-hire.")
    finalize_line(line, now())
    return success_object(line_out(line))


@bp.post("/power-rental/rental-lines/<lid>/return")
def return_line(lid):
    uid, role = auth()
    require_roles(role, ["DepotManager"])
    line = get_or_404(DB.lines, lid, "rental line")
    contract = DB.contracts.get(line["contract_id"])
    if line["status"] in LINE_TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "Line %s is terminal (%s)." % (lid, line["status"]))
    if line["status"] != "OFF_HIRED":
        raise_err(ERR_INVALID_STATE, "Only an OFF_HIRED line can be returned.")
    if contract is None or contract["status"] not in ("OFF_HIRE", "CLOSED"):
        raise_err(ERR_INVALID_STATE, "Parent contract must be OFF_HIRE or CLOSED for a return.")
    ts = now()
    line["status"] = "RETURNED"
    touch(line, ts)
    if line["line_type"] == "EQUIPMENT":
        unit = DB.units.get(line["equipment_unit_id"])
        if unit is not None and unit["status"] == "OFF_RENT":
            unit["status"] = "MAINTENANCE"
            touch(unit, ts)
    return success_object(line_out(line))
