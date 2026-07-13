"""Cases: read/list plus close, cross-report, recover-funds, refer-guardianship,
service-plan (PRD 3.6, 3.7, 3.8)."""
from flask import Blueprint, request

from store import store
from errors import ApiError
from envelope import success
from helpers import (authenticate, authorize, get_body, require_str, require_int,
                     require_array, resolve, touch, paginate, sort_key, serialize)
from calc import distribute_recovery, MANDATORY_CROSS_REPORT_THRESHOLD_CENTS
from recompute import (recompute_case_financials, recompute_client_placement,
                       active_freezes_in_case)

bp = Blueprint("cases", __name__)


@bp.get("/cases/<cid>")
def get_case(cid):
    uid, role = authenticate()
    authorize(role, {"Caseworker", "Supervisor", "IntakeWorker"})
    case = resolve("case", cid)
    return success(serialize(case, "case")), 200


@bp.get("/cases")
def list_cases():
    uid, role = authenticate()
    authorize(role, {"Caseworker", "Supervisor"})
    items = list(store.cases.values())
    for key in ("report_id", "client_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c[key] == val]
    items.sort(key=sort_key)
    page, pag = paginate(items)
    return success([serialize(c, "case") for c in page], "array", pag), 200


@bp.post("/cases/<cid>/close")
def close_case(cid):
    uid, role = authenticate()
    authorize(role, {"Supervisor"})
    case = resolve("case", cid)
    body = get_body()
    closure_reason = require_str(body, "closure_reason")
    if case["status"] != "READY_FOR_CLOSURE":
        raise ApiError("ERR_CASE_INVALID_STATE", "Case is not READY_FOR_CLOSURE", 409)
    if (case["estimated_exposure_cents"] >= MANDATORY_CROSS_REPORT_THRESHOLD_CENTS
            and case["cross_report_agency"] is None):
        raise ApiError("ERR_CROSS_REPORT_REQUIRED",
                       "A cross-report is required before closure", 422)

    # cascade: discharge ACTIVE placements -> release beds
    for p in store.placements.values():
        if p["case_id"] == case["id"] and p["status"] == "ACTIVE":
            p["status"] = "DISCHARGED"
            p["discharged_at"] = store.clock
            touch(p)
            facility = store.facilities[p["facility_id"]]
            facility["occupied_beds"] -= 1
            facility["available_beds"] += 1
            touch(facility)
    # cascade: lift ACTIVE freezes -> unfreeze accounts
    for f in store.freezes.values():
        if f["case_id"] == case["id"] and f["status"] == "ACTIVE":
            f["status"] = "LIFTED"
            f["lifted_at"] = store.clock
            touch(f)
            account = store.accounts[f["account_id"]]
            account["frozen_amount_cents"] = 0
            account["available_balance_cents"] = account["total_balance_cents"]
            account["flagged_amount_cents"] = 0
            account["status"] = "ACTIVE"
            touch(account)
    recompute_case_financials(case)
    if case["service_plan_status"] == "ACTIVE":
        case["service_plan_status"] = "TERMINATED"

    case["closed_at"] = store.clock
    case["closure_reason"] = closure_reason
    case["status"] = "CLOSED"
    touch(case)

    client = store.clients[case["client_id"]]
    client["status"] = "CLOSED"
    client["open_case_count"] -= 1
    recompute_client_placement(client)
    touch(client)
    return success(serialize(case, "case")), 200


@bp.post("/cases/<cid>/cross-report")
def cross_report(cid):
    uid, role = authenticate()
    authorize(role, {"Caseworker", "Supervisor"})
    case = resolve("case", cid)
    body = get_body()
    recipient_agency = require_str(body, "recipient_agency")
    if case["status"] == "CLOSED":
        raise ApiError("ERR_CASE_INVALID_STATE", "Case is CLOSED", 409)
    case["cross_report_agency"] = recipient_agency
    case["cross_reported_at"] = store.clock
    touch(case)
    return success(serialize(case, "case")), 200


@bp.post("/cases/<cid>/recover-funds")
def recover_funds(cid):
    uid, role = authenticate()
    authorize(role, {"Supervisor"})
    case = resolve("case", cid)
    body = get_body()
    recovered = require_int(body, "recovered_amount_cents")
    if case["status"] == "CLOSED":
        raise ApiError("ERR_CASE_INVALID_STATE", "Case is CLOSED", 409)
    active = active_freezes_in_case(case["id"])
    if recovered <= 0 or len(active) == 0:
        raise ApiError("ERR_NO_ACTIVE_FREEZE",
                       "No active freeze or non-positive amount", 409)

    accounts = [store.accounts[f["account_id"]] for f in active]
    accounts.sort(key=sort_key)  # created_at ASC, seq tie-break (never id)
    shares = distribute_recovery(recovered, accounts)
    for a in accounts:
        share = shares[a["id"]]
        a["restitution_cents"] += share
        a["available_balance_cents"] += share
        touch(a)

    recompute_case_financials(case)
    return success(serialize(case, "case")), 200


@bp.post("/cases/<cid>/refer-guardianship")
def refer_guardianship(cid):
    uid, role = authenticate()
    authorize(role, {"Caseworker"})
    case = resolve("case", cid)
    if case["status"] == "CLOSED":
        raise ApiError("ERR_CASE_INVALID_STATE", "Case is CLOSED", 409)
    client = store.clients[case["client_id"]]
    if client["capacity_status"] != "IMPAIRED":
        raise ApiError("ERR_CAPACITY_NOT_IMPAIRED", "Client capacity is not IMPAIRED", 422)
    case["guardianship_status"] = "REFERRED"
    touch(case)
    return success(serialize(case, "case")), 200


@bp.post("/cases/<cid>/service-plan")
def service_plan(cid):
    uid, role = authenticate()
    authorize(role, {"Caseworker"})
    case = resolve("case", cid)
    body = get_body()
    benefit_programs = require_array(body, "benefit_programs")
    if case["status"] == "CLOSED":
        raise ApiError("ERR_CASE_INVALID_STATE", "Case is CLOSED", 409)
    case["service_plan_status"] = "ACTIVE"
    case["benefit_programs"] = list(benefit_programs)
    touch(case)
    client = store.clients[case["client_id"]]
    if client["status"] == "SERVICES_PENDING":
        client["status"] = "SERVICES_ACTIVE"
        touch(client)
    return success(serialize(case, "case")), 200
