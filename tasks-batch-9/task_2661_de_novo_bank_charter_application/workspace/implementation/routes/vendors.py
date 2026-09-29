"""Vendor contract and core-conversion window writes."""
from flask import Blueprint

import calc
import cascade
import db
import response
import serialize
import validation as v
from errors import err
from middleware import authenticate
from routes.helpers import must_get

bp = Blueprint("vendors", __name__)

SERVICE_DOMAINS = ("CORE_PROCESSING", "DIGITAL_BANKING", "BSA_MONITORING", "ITSM")
CRITICALITIES = ("CRITICAL", "SIGNIFICANT", "ROUTINE")
VENDOR_STATUSES = ("EVALUATING", "SELECTED", "SIGNED", "TERMINATED")
VENDOR_TRANSITIONS = {
    "EVALUATING": ("SELECTED", "TERMINATED"),
    "SELECTED": ("SIGNED", "TERMINATED"),
    "SIGNED": ("TERMINATED",),
    "TERMINATED": (),
}


@bp.post("/de-novo/vendor-contracts")
def create_contract():
    authenticate(("CharterCounsel",))
    data = v.body()
    group_id = v.req_id(data, "group_id")
    service_domain = v.req_enum(data, "service_domain", SERVICE_DOMAINS)
    vendor_name = v.req_str(data, "vendor_name", 1, 120)
    annual_cost_cents = v.req_int(data, "annual_cost_cents", 0, None)
    contract_term_months = v.req_int(data, "contract_term_months", 1, 120)
    due_diligence_score = v.req_int(data, "due_diligence_score", 0, 100)
    criticality = v.req_enum(data, "criticality", CRITICALITIES)
    group = must_get("groups", group_id)
    if group["stage"] in ("OPEN", "ABANDONED"):
        raise err("ERR_GROUP_STAGE_LOCKED")
    contract = db.insert("contracts", {
        "group_id": group["id"],
        "service_domain": service_domain,
        "vendor_name": vendor_name,
        "annual_cost_cents": annual_cost_cents,
        "contract_term_months": contract_term_months,
        "due_diligence_score": due_diligence_score,
        "criticality": criticality,
        "status": "EVALUATING",
        "active_window_count": 0,
    })
    db.touch(group)
    db.commit()
    return response.object_response(serialize.contract(contract), 201)


@bp.post("/de-novo/vendor-contracts/<contract_id>/advance")
def advance_contract(contract_id):
    authenticate(("CharterCounsel",))
    data = v.body()
    target_status = v.req_enum(data, "target_status", VENDOR_STATUSES)
    contract = must_get("contracts", contract_id)
    if target_status not in VENDOR_TRANSITIONS.get(contract["status"], ()):
        raise err("ERR_VENDOR_STATUS_TRANSITION_NOT_ALLOWED")
    group = db.get("groups", contract["group_id"])
    if target_status == "SELECTED":
        if (contract["criticality"] == "CRITICAL"
                and contract["due_diligence_score"] < calc.MIN_CRITICAL_DUE_DILIGENCE_SCORE):
            raise err("ERR_DUE_DILIGENCE_INSUFFICIENT")
        for row in calc.contracts_of(contract["group_id"]):
            if (row["id"] != contract["id"]
                    and row["service_domain"] == contract["service_domain"]
                    and row["status"] in ("SELECTED", "SIGNED")):
                raise err("ERR_VENDOR_DOMAIN_ALREADY_SELECTED")
    if target_status == "TERMINATED":
        if group is not None and group["stage"] == "OPEN":
            raise err("ERR_VENDOR_TERMINATION_BLOCKED_AFTER_OPENING")
    contract["status"] = target_status
    db.touch(contract)
    if target_status == "TERMINATED":
        cascade.contract_terminated_cascade(contract)
    db.commit()
    return response.object_response(serialize.contract(contract))


@bp.post("/de-novo/conversion-windows")
def create_window():
    authenticate(("CharterCounsel",))
    data = v.body()
    contract_id = v.req_id(data, "vendor_contract_id")
    expected_version = v.req_int(data, "expected_vendor_contract_version", 0, None)
    window_start = v.req_dt(data, "window_start_utc")
    window_end = v.req_dt(data, "window_end_utc")
    contract = must_get("contracts", contract_id)
    if expected_version != contract["version"]:
        raise err("ERR_STALE_VENDOR_CONTRACT_VERSION")
    if contract["status"] not in ("SELECTED", "SIGNED"):
        raise err("ERR_VENDOR_NOT_CONVERTIBLE")
    duration_hours = calc.window_duration_hours(window_start, window_end)
    if duration_hours > calc.MAX_CONVERSION_WINDOW_HOURS:
        raise err("ERR_WINDOW_TOO_LONG")
    if (calc.conversion_overlap_count(contract["id"], window_start, window_end)
            >= calc.MAX_CONCURRENT_CONVERSIONS):
        raise err("ERR_CONVERSION_CAPACITY_EXCEEDED")
    if window_end <= window_start:
        raise err("ERR_WINDOW_END_NOT_AFTER_START")
    if window_start < db.clock():
        raise err("ERR_WINDOW_START_IN_PAST")
    window = db.insert("windows", {
        "vendor_contract_id": contract["id"],
        "window_start_utc": window_start,
        "window_end_utc": window_end,
        "status": "RESERVED",
        "duration_hours": duration_hours,
    })
    calc.recompute_contract_windows(contract)
    db.touch(contract)
    db.commit()
    return response.object_response(serialize.window(window), 201)


@bp.post("/de-novo/conversion-windows/<window_id>/confirm")
def confirm_window(window_id):
    authenticate(("CharterCounsel",))
    v.body()
    window = must_get("windows", window_id)
    if window["status"] != "RESERVED":
        raise err("ERR_WINDOW_NOT_CONFIRMABLE")
    contract = db.get("contracts", window["vendor_contract_id"])
    if contract is None or contract["status"] != "SIGNED":
        raise err("ERR_VENDOR_CONTRACT_NOT_SIGNED")
    window["status"] = "CONFIRMED"
    db.touch(window)
    db.commit()
    return response.object_response(serialize.window(window))
