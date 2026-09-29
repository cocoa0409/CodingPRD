"""Workforce dispositions (PRD 3.6) and premises dispositions (PRD 3.7)."""
from flask import Blueprint

import calc
import services as svc
from core import (DB, all_of, fail, new_record, public, touch, object_response,
                  list_response, clock_today_iso, day_diff)
from validation import (authorize, json_body, pagination, filter_value, window,
                        req_int, req_str, req_enum, req_date)

bp = Blueprint("dispositions", __name__)

READ_STAFF = ("NetworkStrategist", "ConsolidationApprover", "ComplianceOfficer", "HRPartner",
              "NetworkOpsAdmin", "BranchManager")
READ_PROPERTY = ("NetworkStrategist", "ConsolidationApprover", "ComplianceOfficer",
                 "RealEstateManager", "NetworkOpsAdmin", "BranchManager")
HR_CASE_STATUSES = ("APPROVED", "NOTICE_FILED")
PROPERTY_CASE_STATUSES = ("NOTICE_FILED", "CLOSURE_EXECUTED", "POST_CLOSE_MONITORING")

PROPOSED_DISPOSITIONS = ("REDEPLOYMENT", "SEVERANCE")
DISPOSITION_STATES = ("PROPOSED", "OFFER_ACCEPTED", "SEVERED", "COMPLETED")
NOTIFICATION_STATES = ("PENDING", "NOTIFIED")
ATM_DISPOSITIONS = ("RETAIN_OFFSITE", "RELOCATE", "DECOMMISSION")
PROPERTY_STATUSES = ("PENDING", "MARKETED", "ASSIGNMENT_PENDING", "SALE_PENDING",
                     "HOLDOVER", "DISPOSED")


def _hr_case_gate(case):
    if case is None or case["status"] not in HR_CASE_STATUSES:
        fail("ERR_CASE_STATE_INVALID",
             "The funding case must stand in APPROVED or NOTICE_FILED status.")
    return case


# --------------------------------------------------------------------------- #
# Staff dispositions
# --------------------------------------------------------------------------- #
@bp.post("/distribution/staff-dispositions")
def create_staff_disposition():
    authorize(("HRPartner",))
    body = json_body()
    case_id = req_str(body, "consolidation_case_id")
    employee_ref = req_str(body, "employee_ref", min_len=1, max_len=40)
    role_title = req_str(body, "role_title", min_len=1)
    tenure_months = req_int(body, "tenure_months", minimum=0)
    annual_salary_cents = req_int(body, "annual_salary_cents", minimum=0)
    proposed = req_enum(body, "proposed_disposition", PROPOSED_DISPOSITIONS)
    target_branch_id = req_str(body, "target_branch_id", required=False, default=None)

    case = svc.ref_lookup("consolidation_cases", case_id, "consolidation case")
    if target_branch_id is not None:
        svc.ref_lookup("branches", target_branch_id, "target branch")

    for d in svc.children_of("staff_dispositions", "consolidation_case_id", case_id):
        if d["employee_ref"] == employee_ref:
            fail("ERR_DUPLICATE_KEY",
                 "Employee '%s' already has a disposition on this case." % employee_ref)

    source_branch_id = case["closing_branch_id"]
    if proposed == "REDEPLOYMENT":
        if target_branch_id is None:
            fail("ERR_DISPOSITION_TARGET_INVALID",
                 "A redeployment must name a target branch.")
        if target_branch_id == source_branch_id:
            fail("ERR_DISPOSITION_TARGET_INVALID",
                 "A redeployment target may not be the closing branch.")
    elif target_branch_id is not None:
        fail("ERR_DISPOSITION_TARGET_INVALID",
             "A severance must not name a target branch.")

    weeks, weekly, amount = calc.severance_terms(proposed, tenure_months, annual_salary_cents)
    rec = new_record("staff_dispositions", {
        "consolidation_case_id": case_id,
        "source_branch_id": source_branch_id,
        "target_branch_id": target_branch_id,
        "employee_ref": employee_ref,
        "role_title": role_title,
        "tenure_months": tenure_months,
        "annual_salary_cents": annual_salary_cents,
        "proposed_disposition": proposed,
        "disposition_state": "PROPOSED",
        "notification_state": "PENDING",
        "notified_on": None,
        "service_years": calc.service_years_of(tenure_months),
        "severance_weeks": weeks,
        "weekly_pay_cents": weekly,
        "severance_amount_cents": amount,
        "severed_on": None,
    })

    case["pending_disposition_count"] = case["pending_disposition_count"] + 1
    calc.recompute_severance_pool(case)
    svc.refresh_case_savings(case)
    return object_response(public(rec), 201)


@bp.get("/distribution/staff-dispositions/<disposition_id>")
def read_staff_disposition(disposition_id):
    authorize(READ_STAFF)
    rec = svc.path_lookup("staff_dispositions", disposition_id, "Staff disposition")
    return object_response(public(rec))


@bp.get("/distribution/staff-dispositions")
def list_staff_dispositions():
    authorize(READ_STAFF)
    limit, offset = pagination()
    case_id = filter_value("consolidation_case_id")
    source_branch_id = filter_value("source_branch_id")
    target_branch_id = filter_value("target_branch_id")
    disposition_state = filter_value("disposition_state", DISPOSITION_STATES)
    notification_state = filter_value("notification_state", NOTIFICATION_STATES)
    rows = all_of("staff_dispositions")
    if case_id is not None:
        rows = [r for r in rows if r["consolidation_case_id"] == case_id]
    if source_branch_id is not None:
        rows = [r for r in rows if r["source_branch_id"] == source_branch_id]
    if target_branch_id is not None:
        rows = [r for r in rows if r["target_branch_id"] == target_branch_id]
    if disposition_state is not None:
        rows = [r for r in rows if r["disposition_state"] == disposition_state]
    if notification_state is not None:
        rows = [r for r in rows if r["notification_state"] == notification_state]
    rows = svc.oldest_first(rows)
    page, total = window(rows, limit, offset)
    return list_response([public(r) for r in page], limit, offset, total)


@bp.post("/distribution/staff-dispositions/<disposition_id>/notify")
def notify_staff_disposition(disposition_id):
    authorize(("HRPartner",))
    d = svc.path_lookup("staff_dispositions", disposition_id, "Staff disposition")
    if d["notification_state"] != "PENDING":
        fail("ERR_DISPOSITION_STATE_INVALID",
             "The notification axis already reads %s." % d["notification_state"])
    _hr_case_gate(DB["consolidation_cases"].get(d["consolidation_case_id"]))
    d["notification_state"] = "NOTIFIED"
    d["notified_on"] = clock_today_iso()
    touch(d)
    return object_response(public(d))


@bp.post("/distribution/staff-dispositions/<disposition_id>/accept")
def accept_staff_disposition(disposition_id):
    authorize(("HRPartner",))
    d = svc.path_lookup("staff_dispositions", disposition_id, "Staff disposition")
    if d["proposed_disposition"] != "REDEPLOYMENT":
        fail("ERR_DISPOSITION_STATE_INVALID",
             "Only a redeployment offer can be accepted.")
    if d["disposition_state"] != "PROPOSED":
        fail("ERR_DISPOSITION_STATE_INVALID",
             "The outcome axis reads %s, not PROPOSED." % d["disposition_state"])
    if d["notification_state"] != "NOTIFIED":
        fail("ERR_DISPOSITION_STATE_INVALID",
             "The employee has not been notified yet.")
    case = _hr_case_gate(DB["consolidation_cases"].get(d["consolidation_case_id"]))
    target = DB["branches"].get(d["target_branch_id"]) if d["target_branch_id"] else None
    if target is not None and target["status"] != "ACTIVE":
        fail("ERR_RECEIVING_BRANCH_NOT_ACTIVE",
             "The target branch is in %s status, not ACTIVE." % target["status"])
    if d["target_branch_id"] is None or d["target_branch_id"] == d["source_branch_id"]:
        fail("ERR_DISPOSITION_TARGET_INVALID",
             "The redeployment target is not a coherent branch.")
    source = DB["branches"].get(d["source_branch_id"])

    d["disposition_state"] = "OFFER_ACCEPTED"
    touch(d)
    if source is not None:
        source["fte_count"] = source["fte_count"] - 1
        touch(source)
    target["fte_count"] = target["fte_count"] + 1
    touch(target)
    case["redeployed_fte_count"] = case["redeployed_fte_count"] + 1
    case["pending_disposition_count"] = case["pending_disposition_count"] - 1
    touch(case)
    return object_response(public(d))


@bp.post("/distribution/staff-dispositions/<disposition_id>/rescind")
def rescind_staff_disposition(disposition_id):
    authorize(("HRPartner",))
    body = json_body()
    req_str(body, "rescind_reason_code")
    d = svc.path_lookup("staff_dispositions", disposition_id, "Staff disposition")
    if d["disposition_state"] != "OFFER_ACCEPTED":
        fail("ERR_DISPOSITION_STATE_INVALID",
             "The outcome axis reads %s, not OFFER_ACCEPTED." % d["disposition_state"])
    case = _hr_case_gate(DB["consolidation_cases"].get(d["consolidation_case_id"]))
    source = DB["branches"].get(d["source_branch_id"])
    target = DB["branches"].get(d["target_branch_id"]) if d["target_branch_id"] else None

    d["disposition_state"] = "PROPOSED"
    touch(d)
    if source is not None:
        source["fte_count"] = source["fte_count"] + 1
        touch(source)
    if target is not None:
        target["fte_count"] = target["fte_count"] - 1
        touch(target)
    case["redeployed_fte_count"] = case["redeployed_fte_count"] - 1
    case["pending_disposition_count"] = case["pending_disposition_count"] + 1
    touch(case)
    return object_response(public(d))


@bp.post("/distribution/staff-dispositions/<disposition_id>/sever")
def sever_staff_disposition(disposition_id):
    authorize(("HRPartner",))
    d = svc.path_lookup("staff_dispositions", disposition_id, "Staff disposition")
    if d["proposed_disposition"] != "SEVERANCE":
        fail("ERR_DISPOSITION_STATE_INVALID",
             "Only a severance record can be severed.")
    if d["disposition_state"] != "PROPOSED":
        fail("ERR_DISPOSITION_STATE_INVALID",
             "The outcome axis reads %s, not PROPOSED." % d["disposition_state"])
    if d["notification_state"] != "NOTIFIED":
        fail("ERR_DISPOSITION_STATE_INVALID",
             "The employee has not been notified yet.")
    case = _hr_case_gate(DB["consolidation_cases"].get(d["consolidation_case_id"]))
    today = clock_today_iso()
    if day_diff(today, d["notified_on"]) < calc.WARN_WAITING_DAYS:
        fail("ERR_WARN_PERIOD_NOT_ELAPSED",
             "The statutory 60-day WARN period has not elapsed.")
    source = DB["branches"].get(d["source_branch_id"])

    d["severed_on"] = today
    d["disposition_state"] = "SEVERED"
    touch(d)
    if source is not None:
        source["fte_count"] = source["fte_count"] - 1
        touch(source)
    case["severed_fte_count"] = case["severed_fte_count"] + 1
    case["pending_disposition_count"] = case["pending_disposition_count"] - 1
    touch(case)
    return object_response(public(d))


# --------------------------------------------------------------------------- #
# Premises dispositions
# --------------------------------------------------------------------------- #
@bp.post("/distribution/property-dispositions")
def create_property_disposition():
    authorize(("RealEstateManager",))
    body = json_body()
    branch_id = req_str(body, "branch_id")
    case_id = req_str(body, "consolidation_case_id")
    atm_disposition = req_enum(body, "atm_disposition", ATM_DISPOSITIONS)
    atm_cost = req_int(body, "atm_monthly_cost_cents", minimum=0)
    atm_revenue = req_int(body, "atm_monthly_surcharge_revenue_cents", minimum=0)
    monthly_rent = req_int(body, "monthly_rent_cents", minimum=0, required=False, default=None)
    lease_end_date = req_date(body, "lease_end_date", required=False, default=None)
    buyout_offer = req_int(body, "buyout_offer_cents", minimum=0, required=False, default=None)
    book_value = req_int(body, "book_value_cents", minimum=0, required=False, default=None)
    list_price = req_int(body, "list_price_cents", minimum=0, required=False, default=None)

    branch = svc.ref_lookup("branches", branch_id, "branch")
    case = svc.ref_lookup("consolidation_cases", case_id, "consolidation case")

    for p in all_of("property_dispositions"):
        if p["branch_id"] == branch_id and p["consolidation_case_id"] == case_id:
            fail("ERR_DUPLICATE_KEY",
                 "A premises disposition already exists for this branch and case.")

    tenure_class = branch["tenure_class"]
    if tenure_class == "LEASED":
        if monthly_rent is None or lease_end_date is None or buyout_offer is None:
            fail("ERR_PROPERTY_TERMS_INCOMPLETE",
                 "A leased premises requires monthly_rent_cents, lease_end_date and "
                 "buyout_offer_cents.")
    else:
        if book_value is None or list_price is None:
            fail("ERR_PROPERTY_TERMS_INCOMPLETE",
                 "An owned premises requires book_value_cents and list_price_cents.")

    _margin, breakeven, final = calc.atm_adjudication(atm_disposition, atm_cost, atm_revenue)
    rec = new_record("property_dispositions", {
        "branch_id": branch_id,
        "consolidation_case_id": case_id,
        "tenure_class": tenure_class,
        "monthly_rent_cents": monthly_rent,
        "lease_end_date": lease_end_date,
        "buyout_offer_cents": buyout_offer,
        "book_value_cents": book_value,
        "list_price_cents": list_price,
        "atm_disposition": atm_disposition,
        "atm_monthly_cost_cents": atm_cost,
        "atm_monthly_surcharge_revenue_cents": atm_revenue,
        "atm_breakeven_met": breakeven,
        "atm_decision_final": final,
        "status": "PENDING",
        "marketing_started_on": None,
        "counterparty_ref": None,
        "agreed_amount_cents": None,
        "selling_costs_cents": None,
        "annual_carry_cents": 0,
        "net_disposition_cents": None,
        "settled_on": None,
    })
    calc.refresh_carry(rec)
    svc.refresh_case_savings(case)
    return object_response(public(rec), 201)


@bp.get("/distribution/property-dispositions/<disposition_id>")
def read_property_disposition(disposition_id):
    authorize(READ_PROPERTY)
    rec = svc.path_lookup("property_dispositions", disposition_id, "Property disposition")
    return object_response(public(rec))


@bp.get("/distribution/property-dispositions")
def list_property_dispositions():
    authorize(READ_PROPERTY)
    limit, offset = pagination()
    branch_id = filter_value("branch_id")
    case_id = filter_value("consolidation_case_id")
    status = filter_value("status", PROPERTY_STATUSES)
    atm_disposition = filter_value("atm_disposition", ATM_DISPOSITIONS)
    rows = all_of("property_dispositions")
    if branch_id is not None:
        rows = [r for r in rows if r["branch_id"] == branch_id]
    if case_id is not None:
        rows = [r for r in rows if r["consolidation_case_id"] == case_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if atm_disposition is not None:
        rows = [r for r in rows if r["atm_disposition"] == atm_disposition]
    rows = svc.oldest_first(rows)
    page, total = window(rows, limit, offset)
    return list_response([public(r) for r in page], limit, offset, total)


@bp.post("/distribution/property-dispositions/<disposition_id>/contract")
def contract_property_disposition(disposition_id):
    authorize(("RealEstateManager",))
    body = json_body()
    counterparty_ref = req_str(body, "counterparty_ref", min_len=1)
    agreed_amount = req_int(body, "agreed_amount_cents", minimum=0)
    selling_costs = req_int(body, "selling_costs_cents", minimum=0)
    p = svc.path_lookup("property_dispositions", disposition_id, "Property disposition")

    if p["tenure_class"] == "LEASED":
        if p["status"] not in ("MARKETED", "HOLDOVER"):
            fail("ERR_PROPERTY_STATE_INVALID",
                 "A leased premises in %s status cannot be contracted." % p["status"])
        destination = "ASSIGNMENT_PENDING"
    else:
        if p["status"] != "MARKETED":
            fail("ERR_PROPERTY_STATE_INVALID",
                 "An owned premises in %s status cannot be contracted." % p["status"])
        destination = "SALE_PENDING"

    case = DB["consolidation_cases"].get(p["consolidation_case_id"])
    if case is None or case["status"] not in PROPERTY_CASE_STATUSES:
        fail("ERR_CASE_STATE_INVALID",
             "The owning case must stand in NOTICE_FILED, CLOSURE_EXECUTED or "
             "POST_CLOSE_MONITORING status.")

    p["counterparty_ref"] = counterparty_ref
    p["agreed_amount_cents"] = agreed_amount
    p["selling_costs_cents"] = selling_costs
    p["status"] = destination
    calc.refresh_carry(p)
    touch(p)
    svc.refresh_case_savings(case)
    return object_response(public(p))


@bp.post("/distribution/property-dispositions/<disposition_id>/settle")
def settle_property_disposition(disposition_id):
    authorize(("RealEstateManager",))
    p = svc.path_lookup("property_dispositions", disposition_id, "Property disposition")
    if p["status"] not in ("ASSIGNMENT_PENDING", "SALE_PENDING"):
        fail("ERR_PROPERTY_STATE_INVALID",
             "A premises in %s status cannot be settled." % p["status"])
    agreed = p["agreed_amount_cents"] or 0
    selling_costs = p["selling_costs_cents"] or 0
    if p["status"] == "ASSIGNMENT_PENDING":
        net = agreed - (p["buyout_offer_cents"] or 0) - selling_costs
    else:
        net = agreed - selling_costs - (p["book_value_cents"] or 0)
    p["net_disposition_cents"] = net
    p["status"] = "DISPOSED"
    p["settled_on"] = clock_today_iso()
    calc.refresh_carry(p)
    touch(p)
    case = DB["consolidation_cases"].get(p["consolidation_case_id"])
    if case is not None:
        svc.refresh_case_savings(case)
    return object_response(public(p))
