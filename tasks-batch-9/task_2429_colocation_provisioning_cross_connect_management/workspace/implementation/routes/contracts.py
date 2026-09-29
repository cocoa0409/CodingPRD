"""Contracts, the fiscal lifecycle and the invoice-line ledger
(PRD §3.1 and §3.9)."""

from flask import Blueprint

import refs
from auth import authorize
from billing import (
    contract_power_billing,
    cross_connect_period_billing,
    reversal_line,
)
from errors import ApiError
from response import created, ok, ok_list, paginate, pagination, serialize
from rollups import cabinets_of_contract, recompute_contract
from store import (
    BILLING_MODES,
    CONTRACT_STATUSES,
    LINE_TYPES,
    REDUNDANCY_REQUIREMENTS,
    base_row,
    store,
    touch,
)
from validate import (
    json_body,
    opt_enum,
    opt_int,
    opt_number,
    qfilter,
    qfilter_bool,
    req_bool,
    req_datetime,
    req_enum,
    req_id,
    req_int,
    req_number,
    req_string,
)

bp = Blueprint("contracts", __name__)

READ_ROLES = ("BillingOperator", "FacilityManager", "ProvisioningEngineer", "CustomerAdmin")

OCCUPYING = ("RESERVED", "CAPACITY_HELD", "INSTALLED", "ACTIVE", "DECOMMISSIONING")
ACTIVATION_CABINET_STATUSES = ("RESERVED", "CAPACITY_HELD", "INSTALLED", "ACTIVE")

TRANSITIONS = {
    ("DRAFT", "PENDING_ACTIVATION"),
    ("PENDING_ACTIVATION", "ACTIVE"),
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "WIND_DOWN"),
    ("WIND_DOWN", "TERMINATED"),
}


@bp.route("/contracts", methods=["POST"])
def create_contract():
    authorize("BillingOperator", "FacilityManager")
    body = json_body()
    refs.body_fk(body, "customer_id", refs.CUSTOMER)

    customer_id = req_id(body, "customer_id")
    contract_number = req_string(body, "contract_number")
    billing_mode = req_enum(body, "billing_mode", BILLING_MODES)
    committed_cabinet_count = req_int(body, "committed_cabinet_count", minimum=1)
    power_commit_kw = req_number(body, "power_commit_kw", exclusive_minimum=0)
    committed_bandwidth_mbps = req_int(body, "committed_bandwidth_mbps", minimum=0)
    cross_connect_cap = req_int(body, "cross_connect_cap", minimum=1)
    term_start_date = req_datetime(body, "term_start_date")
    term_end_date = req_datetime(body, "term_end_date")
    if term_end_date <= term_start_date:
        raise ApiError("ERR_INVALID_REQUEST", "term_end_date must be strictly after term_start_date")
    committed_cage_sqft = opt_number(body, "committed_cage_sqft", 0, minimum=0)
    redundancy_requirement = opt_enum(body, "redundancy_requirement", REDUNDANCY_REQUIREMENTS, "N")
    cross_connect_allowance = opt_int(body, "cross_connect_allowance", 0, minimum=0)
    remote_hands_included_minutes = opt_int(
        body, "remote_hands_included_minutes", 0, minimum=0, multiple_of=15
    )

    for existing in store.contracts.values():
        if existing["contract_number"] == contract_number:
            raise ApiError("ERR_INVALID_REQUEST", "contract_number must be unique across contracts")

    contract = base_row()
    contract.update(
        {
            "customer_id": customer_id,
            "contract_number": contract_number,
            "status": "DRAFT",
            "billing_mode": billing_mode,
            "committed_cabinet_count": committed_cabinet_count,
            "committed_cage_sqft": committed_cage_sqft,
            "power_commit_kw": power_commit_kw,
            "committed_bandwidth_mbps": committed_bandwidth_mbps,
            "redundancy_requirement": redundancy_requirement,
            "cross_connect_allowance": cross_connect_allowance,
            "cross_connect_cap": cross_connect_cap,
            "remote_hands_included_minutes": remote_hands_included_minutes,
            "remote_hands_remaining_minutes": remote_hands_included_minutes,
            "credit_hold": False,
            "term_start_date": term_start_date,
            "term_end_date": term_end_date,
            "provisioned_power_kw": 0.0,
            "stranded_commit_kw": 0.0,
            "commit_utilization_pct": 0.0,
            "active_cross_connect_count": 0,
            "billed_total_usd": 0.0,
            "cross_connect_billed_usd": 0.0,
            "last_closed_period_end": None,
        }
    )
    store.contracts[contract["id"]] = contract
    return created(serialize(contract))


@bp.route("/contracts/<contract_id>/state", methods=["POST"])
def contract_state(contract_id):
    authorize("BillingOperator", "FacilityManager")
    contract = refs.path_row(refs.CONTRACT, contract_id)
    body = json_body()
    to_state = req_enum(body, "to_state", CONTRACT_STATUSES)

    current = contract["status"]
    if (current, to_state) not in TRANSITIONS:
        raise ApiError(
            "ERR_INVALID_STATE", "contract cannot move from %s to %s" % (current, to_state)
        )

    if to_state == "ACTIVE" and current == "PENDING_ACTIVATION":
        held = [
            c
            for c in cabinets_of_contract(contract_id)
            if c["status"] in ACTIVATION_CABINET_STATUSES
        ]
        if not held:
            raise ApiError(
                "ERR_NO_CABINET_ASSIGNED",
                "activation requires at least one reserved, held, installed or active cabinet",
            )

    if to_state == "ACTIVE" and current == "SUSPENDED" and contract["credit_hold"]:
        raise ApiError("ERR_CREDIT_HOLD_ACTIVE", "a contract on credit hold cannot be reinstated")

    if to_state == "TERMINATED":
        blocking = [c for c in cabinets_of_contract(contract_id) if c["status"] in OCCUPYING]
        if blocking:
            raise ApiError(
                "ERR_INVALID_STATE", "termination requires every cabinet to be released first"
            )
        if contract["active_cross_connect_count"] != 0:
            raise ApiError(
                "ERR_INVALID_STATE", "termination requires no active cross-connect to remain"
            )

    if to_state == "PENDING_ACTIVATION":
        contract["remote_hands_remaining_minutes"] = contract["remote_hands_included_minutes"]

    contract["status"] = to_state
    touch(contract)
    return ok(serialize(contract))


@bp.route("/contracts/<contract_id>/credit-hold", methods=["POST"])
def credit_hold(contract_id):
    authorize("BillingOperator")
    contract = refs.path_row(refs.CONTRACT, contract_id)
    body = json_body()
    flag = req_bool(body, "credit_hold")
    contract["credit_hold"] = flag
    touch(contract)
    return ok(serialize(contract))


@bp.route("/contracts/<contract_id>/billing-close", methods=["POST"])
def billing_close(contract_id):
    authorize("BillingOperator")
    contract = refs.path_row(refs.CONTRACT, contract_id)
    body = json_body()
    period_start = req_datetime(body, "period_start")
    period_end = req_datetime(body, "period_end")
    if period_end <= period_start:
        raise ApiError(
            "ERR_BILLING_PERIOD_INVALID", "period_end must be strictly after period_start"
        )
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "the contract is not ACTIVE")

    contract_power_billing(contract, period_start, period_end)
    cross_connect_period_billing(contract, period_start, period_end)
    contract["last_closed_period_end"] = period_end
    recompute_contract(contract, force=True)
    return ok(serialize(contract))


@bp.route("/contracts/<contract_id>/invoice-adjustments", methods=["POST"])
def invoice_adjustment(contract_id):
    authorize("BillingOperator")
    contract = refs.path_row(refs.CONTRACT, contract_id)
    body = json_body()
    line = refs.body_fk(body, "invoice_line_id", refs.INVOICE_LINE)
    if line is not None and line["contract_id"] != contract_id:
        # §2.10 — a line on a different contract is treated as unresolved.
        raise ApiError("ERR_INVOICE_LINE_NOT_FOUND", "invoice line does not belong to this contract")
    req_id(body, "invoice_line_id")
    req_string(body, "reason")

    if line["reversed"] or line["line_type"] == "REVERSAL":
        raise ApiError(
            "ERR_LINE_ALREADY_REVERSED", "the line is already reversed or is itself a reversal"
        )

    reversal = reversal_line(contract, line)
    line["reversed"] = True
    if line["line_type"] == "REMOTE_HANDS":
        contract["remote_hands_remaining_minutes"] = (
            contract["remote_hands_remaining_minutes"] + (line["included_minutes_consumed"] or 0)
        )
    recompute_contract(contract, force=True)
    return created(serialize(reversal))


@bp.route("/contracts/<contract_id>", methods=["GET"])
def get_contract(contract_id):
    actor = authorize(*READ_ROLES)
    contract = refs.path_row(refs.CONTRACT, contract_id)
    actor.scope_contract(contract)
    return ok(serialize(contract))


@bp.route("/contracts", methods=["GET"])
def list_contracts():
    actor = authorize(*READ_ROLES)
    actor.require_customer()
    actor.scope_query(("customer", "customer_id"))
    limit, offset = pagination()
    rows = qfilter(list(store.contracts.values()), "customer_id", "status", "billing_mode")
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


# --------------------------------------------------------------------------
# Invoice lines
# --------------------------------------------------------------------------

@bp.route("/invoice-lines/<invoice_line_id>", methods=["GET"])
def get_invoice_line(invoice_line_id):
    actor = authorize("BillingOperator", "CustomerAdmin")
    line = refs.path_row(refs.INVOICE_LINE, invoice_line_id)
    actor.scope_contract_id(line["contract_id"])
    return ok(serialize(line))


@bp.route("/invoice-lines", methods=["GET"])
def list_invoice_lines():
    actor = authorize("BillingOperator", "CustomerAdmin")
    actor.require_customer()
    actor.scope_query(("contract", "contract_id"))
    limit, offset = pagination()
    rows = qfilter(list(store.invoice_lines.values()), "contract_id", "line_type")
    rows = qfilter_bool(rows, "reversed")
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)
