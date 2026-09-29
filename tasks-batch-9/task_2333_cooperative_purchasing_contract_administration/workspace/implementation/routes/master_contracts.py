"""Master contracts: award, execution dimension, price sheet, sweep and quote."""

from flask import Blueprint, request

import calc
import services
from calc import num
from db import (create_row, db, get_dt, logical_now, ordered, serialize, set_dt)
from errors import fail
from middleware import (ROLE_AUDITOR, ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY,
                        ROLE_MEMBER, ROLE_SUPPLIER, commit, require_roles,
                        touch)
from response import created_response, object_response
from routes.common import (COMPLIANCE_POSTURE, CONTRACT_STATUS, FEE_STATUS,
                           LINE_ITEM_ORIGIN, LINE_ITEM_STATUS, REPORT_STATUS,
                           fetch, list_endpoint, render_list)
from validation import (ADD_ON_CODES, UNITS_OF_MEASURE, bad, json_body,
                        pagination, query_args, read_add_ons, read_bool,
                        read_dec, read_discount_tiers, read_dt, read_id,
                        read_int, read_str)

bp = Blueprint("master_contracts", __name__)

READ_ROLES = (ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY, ROLE_SUPPLIER, ROLE_MEMBER,
              ROLE_AUDITOR)
AWARD_STATUS_ACTIONS = ("EXECUTE", "SUSPEND", "REINSTATE", "EXPIRE", "TERMINATE")

CREATE_FIELDS = ("solicitation_id", "supplier_id", "contract_number",
                 "admin_fee_rate_bps", "base_term_start", "base_term_end",
                 "max_renewals", "price_escalation_cap_pct", "discount_tiers",
                 "permitted_add_ons", "nationwide_pricing_flag")


# =========================================================================
# creation and reads
# =========================================================================

@bp.route("/coop/master-contracts", methods=["POST"])
@require_roles(ROLE_LEAD_AGENCY)
def create_contract():
    body = json_body(
        allowed=CREATE_FIELDS,
        required=("solicitation_id", "supplier_id", "contract_number",
                  "admin_fee_rate_bps", "base_term_start", "base_term_end",
                  "max_renewals", "price_escalation_cap_pct", "discount_tiers"),
    )
    solicitation_id = read_id(body, "solicitation_id", required=True)
    supplier_id = read_id(body, "supplier_id", required=True)
    number = read_str(body, "contract_number", required=True, min_len=1, max_len=40)
    fee_bps = read_int(body, "admin_fee_rate_bps", required=True, minimum=1,
                       maximum=1000)
    start_raw, start_dt = read_dt(body, "base_term_start", required=True)
    end_raw, end_dt = read_dt(body, "base_term_end", required=True)
    if not start_dt < end_dt:
        bad("base_term_start must be strictly before base_term_end")
    max_renewals = read_int(body, "max_renewals", required=True, minimum=0, maximum=5)
    cap_pct = read_dec(body, "price_escalation_cap_pct", required=True,
                       minimum="0.0000", maximum="0.2500")
    tiers = read_discount_tiers(body)
    add_ons = read_add_ons(body)
    nationwide = read_bool(body, "nationwide_pricing_flag", default=True)

    # 5. body foreign keys, in entity field order
    solicitation = fetch(db.solicitations, solicitation_id,
                         "ERR_SOLICITATION_NOT_FOUND")
    supplier = fetch(db.suppliers, supplier_id, "ERR_SUPPLIER_NOT_FOUND")

    # 22. the solicitation must be AWARDED
    if solicitation["status"] != "AWARDED":
        fail("ERR_SOLICITATION_NOT_AWARDED", "the solicitation is not AWARDED")

    # 40. the named supplier must hold award_rank 1
    winner = services.rank_one_response(solicitation_id)
    if winner is None or winner["supplier_id"] != supplier_id:
        fail("ERR_AWARD_NOT_HIGHEST_RANKED",
             "the named supplier does not hold the rank-1 responsive position")

    # 57. global natural-key uniqueness
    for existing in db.contracts.values():
        if existing["contract_number"] == number:
            fail("ERR_DUPLICATE_CONTRACT_NUMBER",
                 "contract_number %s is already in use" % number)

    row = create_row(
        db.contracts,
        solicitation_id=solicitation_id,
        supplier_id=supplier_id,
        contract_number=number,
        status="PENDING_EXECUTION",
        compliance_posture="COMPLIANT",
        admin_fee_rate_bps=fee_bps,
        base_term_start=None,
        base_term_end=None,
        current_term_end=None,
        max_renewals=max_renewals,
        renewals_used=0,
        price_escalation_cap_pct=num(cap_pct),
        discount_tiers=[{"tier_index": t["tier_index"],
                         "min_annual_spend_cents": t["min_annual_spend_cents"],
                         "discount_pct": num(t["discount_pct"])} for t in tiers],
        permitted_add_ons=[{"code": a["code"], "rate_pct": num(a["rate_pct"]),
                            "cap_cents": a["cap_cents"]} for a in add_ons],
        nationwide_pricing_flag=nationwide,
        usage_chargeable_cents_total=0,
        fee_assessed_cents_total=0,
        fee_remitted_cents_total=0,
        fee_outstanding_cents=0,
        delinquent_report_count=0,
    )
    set_dt(row, "base_term_start", start_raw)
    set_dt(row, "base_term_end", end_raw)
    set_dt(row, "current_term_end", end_raw)
    return created_response(serialize(row))


@bp.route("/coop/master-contracts", methods=["GET"])
@require_roles(*READ_ROLES)
def list_contracts():
    return list_endpoint(
        lambda: ordered(db.contracts),
        {"solicitation_id": ("solicitation_id", None),
         "supplier_id": ("supplier_id", None),
         "status": ("status", CONTRACT_STATUS),
         "compliance_posture": ("compliance_posture", COMPLIANCE_POSTURE)},
    )


@bp.route("/coop/master-contracts/<contract_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def read_contract(contract_id):
    row = fetch(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")
    return object_response(serialize(row))


# =========================================================================
# execution dimension
# =========================================================================

@bp.route("/coop/master-contracts/<contract_id>/award-status", methods=["POST"])
@require_roles(ROLE_COOP_ADMIN)
def award_status(contract_id):
    body = json_body(allowed=("action", "note"), required=("action",))
    action = read_str(body, "action", required=True, enum=AWARD_STATUS_ACTIONS)
    read_str(body, "note")

    contract = fetch(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")
    now = logical_now()
    status = contract["status"]

    # 23. from-state plus the clock conditions for EXECUTE and EXPIRE
    expected = {
        "EXECUTE": ("PENDING_EXECUTION",),
        "SUSPEND": ("ACTIVE",),
        "REINSTATE": ("SUSPENDED",),
        "EXPIRE": ("ACTIVE", "SUSPENDED"),
        "TERMINATE": ("PENDING_EXECUTION", "ACTIVE", "SUSPENDED"),
    }[action]
    if status not in expected:
        fail("ERR_CONTRACT_INVALID_STATE",
             "%s is not a declared transition out of %s" % (action, status))
    if action == "EXECUTE" and not now < get_dt(contract, "base_term_end"):
        fail("ERR_CONTRACT_INVALID_STATE",
             "the logical clock is not strictly before base_term_end")
    if action == "REINSTATE":
        if contract["compliance_posture"] == "DELINQUENT":
            fail("ERR_CONTRACT_INVALID_STATE",
                 "a DELINQUENT compliance posture blocks reinstatement")
        if not now < get_dt(contract, "current_term_end"):
            fail("ERR_CONTRACT_INVALID_STATE",
                 "the logical clock is not strictly before current_term_end")
    if action == "EXPIRE" and now < get_dt(contract, "current_term_end"):
        fail("ERR_CONTRACT_INVALID_STATE",
             "the contract term has not elapsed yet")

    # 25. EXECUTE and REINSTATE require a QUALIFIED supplier
    supplier = db.suppliers[contract["supplier_id"]]
    if action in ("EXECUTE", "REINSTATE"):
        if supplier["qualification_status"] != "QUALIFIED":
            fail("ERR_SUPPLIER_NOT_QUALIFIED", "the supplier is not QUALIFIED")

    if action == "EXECUTE":
        solicitation = db.solicitations[contract["solicitation_id"]]
        if solicitation["status"] != "AWARDED":
            fail("ERR_SOLICITATION_NOT_AWARDED", "the solicitation is not AWARDED")

    # 59. execution requires a live price sheet
    active_lines = [li for li in services.line_items_of_contract(contract_id)
                    if li["status"] == "ACTIVE"]
    if action == "EXECUTE" and not active_lines:
        fail("ERR_NO_ACTIVE_LINE_ITEMS",
             "the contract has no ACTIVE price-sheet line")

    if action == "EXECUTE":
        contract["status"] = "ACTIVE"
        for line in active_lines:
            set_dt(line, "price_effective_from", contract["base_term_start"])
            touch(line)
        if contract["current_term_end"] is None:
            set_dt(contract, "current_term_end", contract["base_term_end"])
        touch(contract)
    elif action == "SUSPEND":
        contract["status"] = "SUSPENDED"
        touch(contract)
        services.void_contract_determined(contract, "CONTRACT_SUSPENDED")
    elif action == "REINSTATE":
        contract["status"] = "ACTIVE"
        touch(contract)
    elif action == "EXPIRE":
        contract["status"] = "EXPIRED"
        touch(contract)
        if status == "ACTIVE":
            services.void_contract_determined(contract, "CONTRACT_TERMINATED")
    else:  # TERMINATE
        contract["status"] = "TERMINATED"
        touch(contract)
        services.withdraw_line_items(contract)
        if status in ("ACTIVE", "SUSPENDED"):
            services.void_contract_determined(contract, "CONTRACT_TERMINATED")

    commit()
    return object_response(serialize(contract))


# =========================================================================
# delinquency sweep
# =========================================================================

@bp.route("/coop/master-contracts/<contract_id>/compliance-sweep", methods=["POST"])
@require_roles(ROLE_COOP_ADMIN)
def compliance_sweep(contract_id):
    body = json_body(allowed=("note",), required=())
    read_str(body, "note")

    contract = fetch(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")
    now = logical_now()

    due_reports = [r for r in services.reports_of_contract(contract_id)
                   if r["fee_status"] == "DUE"]
    newly_delinquent = []
    for report in due_reports:
        due_at = get_dt(report, "fee_due_at")
        if due_at is not None and due_at < now:
            report["fee_status"] = "DELINQUENT"
            touch(report)
            newly_delinquent.append(report["id"])

    services.recompute_compliance_posture(contract)
    supplier = db.suppliers[contract["supplier_id"]]
    services.recompute_supplier_performance(supplier)

    commit()
    return object_response({
        "contract_id": contract["id"],
        "swept_report_count": len(due_reports),
        "newly_delinquent_report_ids": newly_delinquent,
        "delinquent_report_count": contract["delinquent_report_count"],
        "compliance_posture": contract["compliance_posture"],
        "contract_status": contract["status"],
        "supplier_performance_score": supplier["performance_score"],
        "supplier_performance_tier": supplier["performance_tier"],
    })


# =========================================================================
# price sheet lines
# =========================================================================

@bp.route("/coop/master-contracts/<contract_id>/line-items", methods=["POST"])
@require_roles(ROLE_LEAD_AGENCY)
def create_line_item(contract_id):
    body = json_body(
        allowed=("sku", "item_description", "unit_of_measure",
                 "base_unit_price_cents", "price_floor_cents"),
        required=("sku", "item_description", "unit_of_measure",
                  "base_unit_price_cents", "price_floor_cents"),
    )
    sku = read_str(body, "sku", required=True, min_len=1, max_len=40)
    description = read_str(body, "item_description", required=True, min_len=1,
                           max_len=500)
    unit = read_str(body, "unit_of_measure", required=True, enum=UNITS_OF_MEASURE)
    base_price = read_int(body, "base_unit_price_cents", required=True, minimum=1)
    floor = read_int(body, "price_floor_cents", required=True, minimum=0)

    contract = fetch(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")

    # 56. sku uniqueness within the contract across non-withdrawn lines
    if sku in services.active_skus(contract_id):
        fail("ERR_DUPLICATE_SKU", "sku %s already exists on this contract" % sku)

    # 58. a floor above the base price is refused
    if floor > base_price:
        fail("ERR_PRICE_BELOW_FLOOR",
             "price_floor_cents must not exceed base_unit_price_cents")

    row = services.build_line_item(contract, {
        "sku": sku,
        "item_description": description,
        "unit_of_measure": unit,
        "base_unit_price_cents": base_price,
        "price_floor_cents": floor,
    }, "AWARD")
    commit()
    return created_response(serialize(row))


@bp.route("/coop/master-contracts/<contract_id>/line-items", methods=["GET"])
@require_roles(*READ_ROLES)
def list_contract_line_items(contract_id):
    filters = {"status": ("status", LINE_ITEM_STATUS),
               "origin": ("origin", LINE_ITEM_ORIGIN)}
    args = query_args(filters.keys())
    pagination()
    fetch(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")
    return render_list(services.line_items_of_contract(contract_id), args, filters)


@bp.route("/coop/master-contracts/<contract_id>/usage-reports", methods=["GET"])
@require_roles(ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY, ROLE_SUPPLIER, ROLE_AUDITOR)
def list_contract_usage_reports(contract_id):
    filters = {"status": ("status", REPORT_STATUS),
               "fee_status": ("fee_status", FEE_STATUS)}
    args = query_args(filters.keys())
    pagination()
    fetch(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")
    return render_list(services.reports_of_contract(contract_id), args, filters)


# =========================================================================
# read-only price quote
# =========================================================================

@bp.route("/coop/master-contracts/<contract_id>/price-quote", methods=["GET"])
@require_roles(ROLE_COOP_ADMIN, ROLE_MEMBER, ROLE_AUDITOR)
def price_quote(contract_id):
    args = query_args(("line_item_id", "member_agency_id", "quantity",
                       "add_on_codes"))
    line_item_id = args.get("line_item_id")
    member_agency_id = args.get("member_agency_id")
    if not line_item_id:
        bad("query parameter 'line_item_id' is required")
    if not member_agency_id:
        bad("query parameter 'member_agency_id' is required")
    raw_quantity = args.get("quantity")
    if raw_quantity is None:
        bad("query parameter 'quantity' is required")
    text = raw_quantity.strip()
    if not (text.lstrip("-").isdigit()):
        bad("quantity must be an integer")
    quantity = int(text)
    if quantity < 1:
        bad("quantity must be >= 1")
    codes = _elected_codes()

    contract = fetch(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")
    line = fetch(db.line_items, line_item_id, "ERR_LINE_ITEM_NOT_FOUND")
    member = fetch(db.members, member_agency_id, "ERR_MEMBER_NOT_FOUND")

    # 20. the line must be live
    if line["status"] != "ACTIVE":
        fail("ERR_LINE_ITEM_NOT_ACTIVE", "the price-sheet line is not ACTIVE")
    # 34. the line must belong to the named contract
    if line["contract_id"] != contract["id"]:
        fail("ERR_LINE_ITEM_CONTRACT_MISMATCH",
             "the line item does not belong to this contract")
    # 38. every elected add-on must be in the catalogue
    _check_add_ons(contract, codes)

    priced = calc.member_usage_total(contract, line, member, quantity, codes,
                                     member["committed_spend_cents"])
    return object_response({
        "line_item_id": line["id"],
        "member_agency_id": member["id"],
        "spend_basis_cents": priced["spend_basis_cents"],
        "discount_tier_index": priced["discount_tier_index"],
        "total_discount_pct": num(priced["total_discount_pct"]),
        "net_unit_price_cents": priced["net_unit_price_cents"],
        "subtotal_cents": priced["subtotal_cents"],
        "add_on_charges_cents": priced["add_on_charges_cents"],
        "chargeable_base_cents": priced["chargeable_base_cents"],
        "effective_fee_rate_bps": priced["effective_fee_rate_bps"],
        "admin_fee_cents": priced["admin_fee_cents"],
        "total_cents": priced["total_cents"],
        "floor_binding": priced["floor_binding"],
        "aggregate_add_on_cap_binding": priced["aggregate_add_on_cap_binding"],
    })


def _elected_codes():
    values = request.args.getlist("add_on_codes")
    codes = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part:
                codes.append(part)
    return codes


def _check_add_ons(contract, codes):
    permitted = set(entry["code"] for entry in contract["permitted_add_ons"])
    seen = set()
    for code in codes:
        if code not in ADD_ON_CODES or code not in permitted:
            fail("ERR_ADD_ON_NOT_PERMITTED",
                 "add-on code %s is not in the contract's catalogue" % code)
        if code in seen:
            fail("ERR_ADD_ON_NOT_PERMITTED",
                 "add-on code %s is elected more than once" % code)
        seen.add(code)
