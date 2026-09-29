"""Parity observations, case mediation and escalation (PRD 3.5)."""
from flask import Blueprint

import auth
import calc
import cascade
import clock
import response
import store
import validate
from errors import ApiError
from store import created_key, db, touch

from routes import common

bp = Blueprint("parity", __name__)

CHANNELS = ("SUPPLIER_WEB", "SUPPLIER_APP", "META")
SEVERITIES = ("NONE", "MINOR", "MAJOR", "SEVERE")
CASE_STATUSES = ("OPEN", "SUPPLIER_NOTIFIED", "SUPPLIER_RESPONDED", "ESCALATED",
                 "RESOLVED_COMPLIANT", "WAIVED")
RESPONSE_CODES = ("RATE_CORRECTED", "DISPUTED", "NO_ACTION")


def _guard_open(case):
    if case["status"] in calc.PARITY_TERMINAL:
        raise ApiError("ERR_PARITY_CASE_CLOSED")


def _open_case_for(rate_plan_id, travel_date):
    for row in sorted(db["parity_cases"].values(), key=lambda r: r["_seq"]):
        if row["rate_plan_id"] != rate_plan_id or row["travel_date"] != travel_date:
            continue
        if row["status"] in calc.PARITY_TERMINAL:
            continue
        return row
    return None


@bp.post("/rate-plans/<plan_id>/parity-observations")
def create_observation(plan_id):
    actor = auth.authenticate(("ParityAnalyst",))
    plan = common.find("rate_plans", plan_id)
    data = validate.body()
    travel_date = validate.date_req(data, "travel_date")
    channel = validate.enum_req(data, "channel", CHANNELS)
    observed_at = validate.instant_req(data, "observed_at")
    direct_total_cents = validate.int_req(data, "direct_total_cents", 1)
    common.guard_offboarded(common.plan_supplier(plan))

    offer = calc.compared_live_offer(plan["id"], travel_date)
    breach_bps = None
    severity = "NONE"
    if offer is not None:
        breach_bps = calc.breach_bps_for(offer["display_total_cents"], direct_total_cents)
        severity = calc.severity_for_bps(breach_bps)
    observation = store.new_row("observations", {
        "rate_plan_id": plan["id"],
        "travel_date": travel_date,
        "channel": channel,
        "observed_at": observed_at,
        "direct_total_cents": direct_total_cents,
        "compared_offer_id": offer["id"] if offer else None,
        "breach_bps": breach_bps,
        "severity": severity,
        "parity_case_id": None,
        "observed_by_user_id": actor.user_id,
    }, versioned=False)

    if plan["parity_monitored"] and severity != "NONE":
        case = _open_case_for(plan["id"], travel_date)
        if case is None:
            case = store.new_row("parity_cases", {
                "rate_plan_id": plan["id"],
                "travel_date": travel_date,
                "opening_observation_id": observation["id"],
                "severity": severity,
                "peak_breach_bps": breach_bps,
                "status": "OPEN",
                "notify_rounds": 0,
                "supplier_response_code": None,
                "opened_by_user_id": actor.user_id,
                "closed_by_user_id": None,
                "close_outcome": None,
                "escalated_at": None,
            })
        else:
            peak = max(int(case["peak_breach_bps"]), int(breach_bps))
            case["peak_breach_bps"] = peak
            case["severity"] = calc.severity_for_bps(peak)
            touch(case)
        observation["parity_case_id"] = case["id"]
    return response.obj(observation, 201)


@bp.get("/parity-observations/<observation_id>")
def read_observation(observation_id):
    auth.authenticate(auth.ALL_ROLES)
    return response.obj(common.find("observations", observation_id), 200)


@bp.get("/parity-observations")
def list_observations():
    auth.authenticate(auth.ALL_ROLES)
    rate_plan_id = validate.filter_str("rate_plan_id")
    travel_date = validate.filter_date("travel_date")
    severity = validate.filter_enum("severity", SEVERITIES)
    rows = []
    for row in db["observations"].values():
        if rate_plan_id is not None and row["rate_plan_id"] != rate_plan_id:
            continue
        if travel_date is not None and row["travel_date"] != travel_date:
            continue
        if severity is not None and row["severity"] != severity:
            continue
        rows.append(row)
    return common.paged(rows, key=lambda r: (r["observed_at"], created_key(r)))


@bp.get("/parity-cases/<case_id>")
def read_case(case_id):
    auth.authenticate(auth.ALL_ROLES)
    return response.obj(common.find("parity_cases", case_id), 200)


@bp.get("/parity-cases")
def list_cases():
    auth.authenticate(auth.ALL_ROLES)
    rate_plan_id = validate.filter_str("rate_plan_id")
    opening = validate.filter_str("opening_observation_id")
    status = validate.filter_enum("status", CASE_STATUSES)
    severity = validate.filter_enum("severity", ("MINOR", "MAJOR", "SEVERE"))
    rows = []
    for row in db["parity_cases"].values():
        if rate_plan_id is not None and row["rate_plan_id"] != rate_plan_id:
            continue
        if opening is not None and row["opening_observation_id"] != opening:
            continue
        if status is not None and row["status"] != status:
            continue
        if severity is not None and row["severity"] != severity:
            continue
        rows.append(row)
    return common.paged(rows)


@bp.post("/parity-cases/<case_id>/notify-supplier")
def notify_supplier(case_id):
    auth.authenticate(("ParityAnalyst",))
    case = common.find("parity_cases", case_id)
    data = validate.body()
    validate.str_opt(data, "note")
    common.guard_offboarded(common.plan_supplier(common.find("rate_plans", case["rate_plan_id"])))
    _guard_open(case)
    if case["status"] not in ("OPEN", "SUPPLIER_RESPONDED"):
        raise ApiError("ERR_PARITY_CASE_NOT_NOTIFIED",
                       "The case is not awaiting a notification round.")
    if case["notify_rounds"] >= calc.PARITY_MAX_NOTIFY_ROUNDS:
        raise ApiError("ERR_PARITY_ROUND_LIMIT")
    case["status"] = "SUPPLIER_NOTIFIED"
    case["notify_rounds"] = int(case["notify_rounds"]) + 1
    touch(case)
    return response.obj(case, 200)


@bp.post("/parity-cases/<case_id>/respond")
def respond(case_id):
    actor = auth.authenticate(("SupplierUser",))
    case = common.find("parity_cases", case_id)
    plan = common.find("rate_plans", case["rate_plan_id"])
    auth.require_supplier_scope(actor, plan["supplier_id"])
    data = validate.body()
    code = validate.enum_req(data, "supplier_response_code", RESPONSE_CODES)
    validate.str_opt(data, "note")
    common.guard_offboarded(common.plan_supplier(plan))
    _guard_open(case)
    if case["status"] != "SUPPLIER_NOTIFIED":
        raise ApiError("ERR_PARITY_CASE_NOT_NOTIFIED")
    case["status"] = "SUPPLIER_RESPONDED"
    case["supplier_response_code"] = code
    touch(case)
    return response.obj(case, 200)


@bp.post("/parity-cases/<case_id>/escalate")
def escalate(case_id):
    auth.authenticate(("ParityAnalyst", "ComplianceOfficer"))
    case = common.find("parity_cases", case_id)
    plan = common.find("rate_plans", case["rate_plan_id"])
    data = validate.body()
    validate.str_req(data, "escalation_reason")
    supplier = common.plan_supplier(plan)
    common.guard_offboarded(supplier)
    _guard_open(case)
    if case["status"] not in ("SUPPLIER_NOTIFIED", "SUPPLIER_RESPONDED"):
        raise ApiError("ERR_PARITY_CASE_NOT_ESCALATABLE")
    if case["severity"] not in ("MAJOR", "SEVERE"):
        raise ApiError("ERR_PARITY_CASE_NOT_ESCALATABLE",
                       "Only a MAJOR or SEVERE breach may be escalated.")
    case["status"] = "ESCALATED"
    case["escalated_at"] = clock.now_iso()
    touch(case)
    supplier["parity_strikes"] = int(supplier["parity_strikes"]) + 1
    touch(supplier)
    cascade.hold_rate_plan(plan, case)
    return response.obj(case, 200)


@bp.post("/parity-cases/<case_id>/close")
def close_case(case_id):
    actor = auth.authenticate(("ParityAnalyst", "ComplianceOfficer"))
    case = common.find("parity_cases", case_id)
    data = validate.body()
    outcome = validate.enum_req(data, "outcome", ("COMPLIANT", "WAIVED"))
    validate.str_opt(data, "note")
    common.guard_offboarded(common.plan_supplier(common.find("rate_plans", case["rate_plan_id"])))
    if outcome == "WAIVED" and actor.role != "ComplianceOfficer":
        raise ApiError("ERR_UNAUTHORIZED", "Only a ComplianceOfficer may waive a parity case.")
    _guard_open(case)
    if outcome == "WAIVED":
        if case["status"] != "SUPPLIER_NOTIFIED":
            raise ApiError("ERR_PARITY_CASE_NOT_NOTIFIED")
        auth.require_distinct(actor, case["opened_by_user_id"])
        case["status"] = "WAIVED"
    else:
        if case["status"] not in ("OPEN", "SUPPLIER_NOTIFIED", "SUPPLIER_RESPONDED", "ESCALATED"):
            raise ApiError("ERR_PARITY_CASE_NOT_NOTIFIED")
        case["status"] = "RESOLVED_COMPLIANT"
    case["close_outcome"] = outcome
    case["closed_by_user_id"] = actor.user_id
    touch(case)
    return response.obj(case, 200)
