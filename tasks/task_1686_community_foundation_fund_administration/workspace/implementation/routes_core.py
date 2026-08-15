"""Clock, funds, agreements, advisors."""
from decimal import Decimal

from flask import Blueprint, g, request

from common import (
    STORE, ALL_ROLES, ApiError, body, err, evaluate_time_transitions,
    executed_agreement, fmt_ts, fund_invested_units, fund_view, get_path,
    get_ref, list_response, new_resource, now, opt_decimal, opt_int,
    q2, req_decimal, req_enum, req_present, require_roles, serialize, success,
    touch,
)

bp = Blueprint("core", __name__)

FUND_TYPES = ("DONOR_ADVISED", "DESIGNATED", "SCHOLARSHIP")
SPENDING_FORMULAS = ("AVERAGE_12Q", "FIXED_3YR")
FEE_SCHEDULES = ("STANDARD", "FLAT")
ADVISOR_KINDS = ("PRIMARY", "SUCCESSOR")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
@require_roles("FoundationAdmin")
def set_clock():
    data = body()
    from common import CLOCK, parse_dt
    target = parse_dt(data.get("to_iso8601"), "to_iso8601")
    CLOCK["now"] = target
    evaluate_time_transitions()
    return success({"current_utc": fmt_ts(target)})


# ---------------------------------------------------------------------------
# Funds
# ---------------------------------------------------------------------------
@bp.post("/funds")
@require_roles("FoundationAdmin")
def create_fund():
    data = body()
    fund_name = data.get("fund_name")
    # Uniqueness (priority 11) precedes field-domain checks (priority 12).
    if fund_name is not None:
        for f in STORE["funds"].values():
            if f["fund_name"] == fund_name:
                err("ERR_UNIQUENESS_VIOLATION", 409, "fund_name must be unique")
    fund_name = req_present(data, "fund_name")
    fund_type = req_enum(data, "fund_type", FUND_TYPES)
    endowed = data.get("endowed")
    if not isinstance(endowed, bool):
        err("ERR_FIELD_CONSTRAINT", 422, "endowed must be a boolean")
    f = new_resource()
    f.update({
        "fund_name": fund_name,
        "fund_type": fund_type,
        "status": "PENDING_AGREEMENT",
        "endowed": endowed,
        "cash_balance": Decimal("0.00"),
        "current_spending_allowance": Decimal("0.00"),
        "allowance_used": Decimal("0.00"),
        "inception_date": None,
        "last_activity_at": None,
    })
    STORE["funds"][f["id"]] = f
    return success(fund_view(f), code=201)


@bp.get("/funds")
@require_roles(*ALL_ROLES)
def list_funds():
    items = list(STORE["funds"].values())
    ft = request.args.get("fund_type")
    st = request.args.get("status")
    if ft is not None:
        items = [f for f in items if f["fund_type"] == ft]
    if st is not None:
        items = [f for f in items if f["status"] == st]
    return list_response(items, fund_view)


@bp.get("/funds/<fundId>")
@require_roles(*ALL_ROLES)
def get_fund(fundId):
    return success(fund_view(get_path("funds", fundId)))


@bp.post("/funds/<fundId>/activate")
@require_roles("FoundationAdmin")
def activate_fund(fundId):
    f = get_path("funds", fundId)
    if f["status"] != "PENDING_AGREEMENT":
        err("ERR_INVALID_STATE", 409, "Only a PENDING_AGREEMENT fund can be activated")
    agr = executed_agreement(f["id"])
    if agr is None:
        err("ERR_AGREEMENT_NOT_EXECUTED", 409,
            "Fund has no EXECUTED agreement")
    min_req = agr["min_initial_contribution"]
    ok = any(
        c for c in STORE["contributions"].values()
        if c["fund_id"] == f["id"]
        and c["acceptance_status"] == "ACCEPTED"
        and c["net_proceeds"] is not None
        and c["net_proceeds"] >= min_req
    )
    if not ok:
        err("ERR_MIN_INITIAL_CONTRIBUTION", 422,
            "No ACCEPTED contribution meets the minimum initial contribution")
    f["status"] = "ACTIVE"
    f["inception_date"] = now()
    f["last_activity_at"] = now()
    touch(f)
    return success(fund_view(f))


@bp.post("/funds/<fundId>/close")
@require_roles("FoundationAdmin")
def close_fund(fundId):
    f = get_path("funds", fundId)
    if f["status"] not in ("ACTIVE", "DORMANT"):
        err("ERR_INVALID_STATE", 409,
            "Only an ACTIVE or DORMANT fund can be closed")
    if f["cash_balance"] != Decimal("0.00") or fund_invested_units(f["id"]) != Decimal("0.0000"):
        err("ERR_FUND_NOT_EMPTY", 409,
            "Fund must have zero cash balance and zero invested units")
    if f["status"] == "ACTIVE":
        pending = ("DRAFT", "SUBMITTED", "COMPLIANCE_REVIEW", "RETURNED", "APPROVED")
        if any(gr for gr in STORE["grants"].values()
               if gr["fund_id"] == f["id"] and gr["status"] in pending):
            err("ERR_PENDING_GRANTS", 409, "Fund has non-terminal grant recommendations")
        if any(p for p in STORE["programs"].values()
               if p["fund_id"] == f["id"]
               and p["status"] in ("SETUP", "OPEN", "SCORING", "AWARDED")):
            err("ERR_PROGRAM_OPEN", 409, "Fund has a non-terminal scholarship program")
    f["status"] = "CLOSED"
    touch(f)
    return success(fund_view(f))


# ---------------------------------------------------------------------------
# Agreements
# ---------------------------------------------------------------------------
def agreement_view(a):
    return serialize(a)


@bp.post("/funds/<fundId>/agreements")
@require_roles("FoundationAdmin")
def create_agreement(fundId):
    f = get_path("funds", fundId)
    data = body()
    succ_id = data.get("successor_advisor_id")
    adv = None
    if succ_id is not None:
        adv = get_ref("advisors", succ_id, "advisor")
    # OCC (priority 6): required only when an EXECUTED agreement exists (amendment).
    incumbent = executed_agreement(f["id"])
    if incumbent is not None:
        if data.get("expected_fund_version") != f["version"]:
            err("ERR_STALE_FUND_VERSION", 412,
                "expected_fund_version does not match the fund's current version")
    # Uniqueness (priority 11): successor must not be the fund's own PRIMARY advisor row.
    if adv is not None and adv["fund_id"] == f["id"] and adv["advisor_kind"] == "PRIMARY":
        err("ERR_UNIQUENESS_VIOLATION", 409,
            "successor_advisor_id must not name the fund's PRIMARY advisor")
    # Field domain (priority 12).
    rate = req_decimal(data, "spending_rate_pct")
    if rate < Decimal("0.00") or rate > Decimal("20.00"):
        err("ERR_FIELD_CONSTRAINT", 422, "spending_rate_pct must be within 0.00-20.00")
    formula = req_enum(data, "spending_formula", SPENDING_FORMULAS)
    schedule = req_enum(data, "fee_tier_schedule", FEE_SCHEDULES)
    inactivity = opt_int(data, "inactivity_trigger_months", 36)
    dormancy = opt_int(data, "dormancy_trigger_months", 24)
    min_init = opt_decimal(data, "min_initial_contribution", Decimal("10000.00"))
    if min_init < 0:
        err("ERR_FIELD_CONSTRAINT", 422, "min_initial_contribution must be >= 0")
    a = new_resource()
    version_no = 1 + sum(1 for x in STORE["agreements"].values()
                         if x["fund_id"] == f["id"])
    a.update({
        "fund_id": f["id"],
        "agreement_version_no": version_no,
        "status": "DRAFT",
        "spending_rate_pct": q2(rate),
        "spending_formula": formula,
        "fee_tier_schedule": schedule,
        "successor_advisor_id": succ_id,
        "inactivity_trigger_months": inactivity,
        "dormancy_trigger_months": dormancy,
        "min_initial_contribution": q2(min_init),
        "executed_at": None,
        "_created_as_amendment": incumbent is not None,
    })
    STORE["agreements"][a["id"]] = a
    return success(agreement_view(a), code=201)


@bp.get("/funds/<fundId>/agreements")
@require_roles("FoundationAdmin", "ComplianceOfficer", "FinanceOfficer")
def list_fund_agreements(fundId):
    f = get_path("funds", fundId)
    items = [a for a in STORE["agreements"].values() if a["fund_id"] == f["id"]]
    return list_response(items, agreement_view)


@bp.get("/agreements/<agreementId>")
@require_roles("FoundationAdmin", "ComplianceOfficer", "FinanceOfficer")
def get_agreement(agreementId):
    return success(agreement_view(get_path("agreements", agreementId)))


@bp.get("/agreements")
@require_roles("FoundationAdmin", "ComplianceOfficer", "FinanceOfficer")
def list_agreements():
    items = list(STORE["agreements"].values())
    fid = request.args.get("fund_id")
    sid = request.args.get("successor_advisor_id")
    if fid is not None:
        items = [a for a in items if a["fund_id"] == fid]
    if sid is not None:
        items = [a for a in items if a["successor_advisor_id"] == sid]
    return list_response(items, agreement_view)


@bp.post("/agreements/<agreementId>/execute")
@require_roles("FoundationAdmin")
def execute_agreement(agreementId):
    a = get_path("agreements", agreementId)
    if a["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Only a DRAFT agreement can be executed")
    f = STORE["funds"][a["fund_id"]]
    incumbent = executed_agreement(f["id"])
    if incumbent is not None and not a["_created_as_amendment"]:
        err("ERR_AGREEMENT_ALREADY_EXECUTED", 409,
            "Another EXECUTED agreement exists and this draft was not created as an amendment")
    if a["successor_advisor_id"] is not None:
        adv = STORE["advisors"].get(a["successor_advisor_id"])
        if adv is None or adv["fund_id"] != f["id"]:
            err("ERR_SUCCESSOR_NOT_ON_FUND", 422,
                "successor_advisor_id must reference an advisor serving the same fund")
    a["status"] = "EXECUTED"
    a["executed_at"] = now()
    touch(a)
    if incumbent is not None:
        incumbent["status"] = "SUPERSEDED"
        touch(incumbent)
    touch(f)
    return success(agreement_view(a))


@bp.post("/agreements/<agreementId>/terminate")
@require_roles("FoundationAdmin")
def terminate_agreement(agreementId):
    a = get_path("agreements", agreementId)
    if a["status"] != "EXECUTED":
        err("ERR_INVALID_STATE", 409, "Only an EXECUTED agreement can be terminated")
    f = STORE["funds"][a["fund_id"]]
    if f["status"] != "CLOSED":
        err("ERR_FUND_NOT_CLOSED", 409, "Agreement may be terminated only once its fund is CLOSED")
    a["status"] = "TERMINATED"
    touch(a)
    return success(agreement_view(a))


# ---------------------------------------------------------------------------
# Advisors
# ---------------------------------------------------------------------------
def advisor_view(a):
    return serialize(a)


@bp.post("/funds/<fundId>/advisors")
@require_roles("FoundationAdmin")
def invite_advisor(fundId):
    f = get_path("funds", fundId)
    data = body()
    email = data.get("email")
    if email is not None:
        for a in STORE["advisors"].values():
            if a["email"] == email:
                err("ERR_UNIQUENESS_VIOLATION", 409, "Advisor email must be unique")
    name = req_present(data, "advisor_name")
    email = req_present(data, "email")
    kind = req_enum(data, "advisor_kind", ADVISOR_KINDS)
    a = new_resource()
    a.update({
        "fund_id": f["id"],
        "advisor_name": name,
        "email": email,
        "advisor_kind": kind,
        "status": "INVITED",
        "activated_at": None,
    })
    STORE["advisors"][a["id"]] = a
    return success(advisor_view(a), code=201)


@bp.get("/funds/<fundId>/advisors")
@require_roles("FoundationAdmin", "ComplianceOfficer", "Advisor")
def list_fund_advisors(fundId):
    f = get_path("funds", fundId)
    items = [a for a in STORE["advisors"].values() if a["fund_id"] == f["id"]]
    return list_response(items, advisor_view)


@bp.get("/advisors/<advisorId>")
@require_roles("FoundationAdmin", "ComplianceOfficer", "Advisor")
def get_advisor(advisorId):
    return success(advisor_view(get_path("advisors", advisorId)))


@bp.get("/advisors")
@require_roles("FoundationAdmin", "ComplianceOfficer")
def list_advisors():
    items = list(STORE["advisors"].values())
    fid = request.args.get("fund_id")
    if fid is not None:
        items = [a for a in items if a["fund_id"] == fid]
    return list_response(items, advisor_view)


@bp.post("/advisors/<advisorId>/accept")
@require_roles("Advisor")
def accept_advisor(advisorId):
    a = get_path("advisors", advisorId)
    if a["status"] != "INVITED":
        err("ERR_INVALID_STATE", 409, "Only an INVITED advisor can accept")
    if g.uid != a["id"]:
        err("ERR_NOT_THE_INVITED_ADVISOR", 403,
            "An advisor invitation may be accepted only by the invited advisor")
    a["status"] = "ACTIVE"
    a["activated_at"] = now()
    touch(a)
    return success(advisor_view(a))


@bp.post("/advisors/<advisorId>/resign")
@require_roles("Advisor")
def resign_advisor(advisorId):
    a = get_path("advisors", advisorId)
    if a["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Only an ACTIVE advisor can resign")
    if g.uid != a["id"]:
        err("ERR_NOT_THE_INVITED_ADVISOR", 403,
            "An advisor may resign only as themself")
    a["status"] = "RESIGNED"
    # Resignation is deliberately not qualifying activity: last_activity_at unchanged.
    touch(a)
    return success(advisor_view(a))


@bp.post("/advisors/<advisorId>/revoke")
@require_roles("FoundationAdmin")
def revoke_advisor(advisorId):
    a = get_path("advisors", advisorId)
    if a["status"] != "INVITED":
        err("ERR_INVALID_STATE", 409, "Only an INVITED advisor can be revoked")
    a["status"] = "REVOKED"
    touch(a)
    for agr in STORE["agreements"].values():
        if agr["status"] == "DRAFT" and agr["successor_advisor_id"] == a["id"]:
            agr["successor_advisor_id"] = None
            touch(agr)
    return success(advisor_view(a))


@bp.post("/advisors/<advisorId>/record-deceased")
@require_roles("FoundationAdmin")
def record_deceased(advisorId):
    a = get_path("advisors", advisorId)
    if a["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Only an ACTIVE advisor can be recorded deceased")
    # Hop 1
    a["status"] = "DECEASED"
    touch(a)
    # Hop 2: named INVITED successor on the fund's EXECUTED agreement auto-activates.
    f = STORE["funds"][a["fund_id"]]
    agr = executed_agreement(f["id"])
    if agr is not None and agr["successor_advisor_id"] is not None:
        succ = STORE["advisors"].get(agr["successor_advisor_id"])
        if succ is not None and succ["status"] == "INVITED":
            succ["status"] = "ACTIVE"
            succ["activated_at"] = now()
            touch(succ)
            # Hop 3: succession event refreshes activity and wakes an INACTIVE fund.
            f["last_activity_at"] = now()
            if f["status"] == "INACTIVE":
                f["status"] = "ACTIVE"
            touch(f)
    return success(advisor_view(a))
