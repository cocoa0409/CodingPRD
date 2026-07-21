"""Policy cases, strikes and the takedown cascade."""
from flask import Blueprint, g

from core import (
    authenticate,
    db,
    fail,
    filter_eq,
    get_body,
    new_record,
    ok,
    ok_list,
    ordered,
    pagination,
    paginate,
    public,
    req_enum,
    req_str,
    require_owner,
    touch,
)
from services import delist_app, lookup, recompute_risk

bp = Blueprint("policy_cases", __name__)

CATEGORIES = {"FRAUD", "IP_INFRINGEMENT", "MALWARE", "CONTENT", "PAYMENT_ABUSE"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH"}
OPEN_STATUSES = {"OPEN", "INVESTIGATING", "APPEALED"}


def _guard_sod(case):
    if g.user_id == case["opened_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The officer who opened this case may not decide it.")


@bp.post("/api/policy-cases")
def open_case():
    authenticate({"PolicyOfficer"})
    body = get_body()
    app_id = req_str(body, "app_id")
    category = req_enum(body, "category", CATEGORIES)
    severity = req_enum(body, "severity", SEVERITIES)
    app = lookup("apps", app_id)
    rec = new_record(
        app_id=app["id"],
        developer_id=app["developer_id"],
        category=category,
        severity=severity,
        status="OPEN",
        opened_by_user_id=g.user_id,
        decided_by_user_id=None,
    )
    db.policy_cases[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.get("/api/policy-cases")
def list_cases():
    authenticate({"PolicyOfficer", "PlatformAdmin", "Developer"})
    limit, offset = pagination()
    rows = ordered(db.policy_cases)
    for field in ("app_id", "developer_id", "status", "category"):
        rows = filter_eq(rows, field)
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/api/policy-cases/<policy_case_id>")
def read_case(policy_case_id):
    authenticate({"PolicyOfficer", "PlatformAdmin", "Developer"})
    case = lookup("policy_cases", policy_case_id)
    require_owner(case["developer_id"])
    return ok(public(case))


@bp.post("/api/policy-cases/<policy_case_id>/investigate")
def investigate(policy_case_id):
    authenticate({"PolicyOfficer"})
    case = lookup("policy_cases", policy_case_id)
    if case["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "Case is not OPEN.")
    case["status"] = "INVESTIGATING"
    touch(case)
    dev = db.developers.get(case["developer_id"])
    if dev is not None:
        dev["risk_watch"] = True
        recompute_risk(dev)
        touch(dev)
    return ok(public(case))


@bp.post("/api/policy-cases/<policy_case_id>/decide")
def decide(policy_case_id):
    authenticate({"PolicyOfficer"})
    case = lookup("policy_cases", policy_case_id)
    _guard_sod(case)
    body = get_body()
    outcome = req_enum(body, "outcome", {"UPHELD", "DISMISSED"})
    req_str(body, "rationale")
    if case["status"] != "INVESTIGATING":
        fail("ERR_INVALID_STATE", "Case is not INVESTIGATING.")

    case["status"] = outcome
    case["decided_by_user_id"] = g.user_id
    touch(case)

    dev = db.developers.get(case["developer_id"])
    if outcome == "UPHELD":
        app = db.apps.get(case["app_id"])
        if app is not None and app["status"] != "DELISTED":
            delist_app(app)
        if dev is not None:
            recompute_risk(dev)
            touch(dev)
    else:
        if dev is not None:
            others = [
                c for c in ordered(db.policy_cases)
                if c["developer_id"] == dev["id"]
                and c["id"] != case["id"]
                and c["status"] in OPEN_STATUSES
            ]
            if not others:
                dev["risk_watch"] = False
            recompute_risk(dev)
            touch(dev)
    return ok(public(case))


@bp.post("/api/policy-cases/<policy_case_id>/appeal")
def appeal(policy_case_id):
    authenticate({"Developer"})
    case = lookup("policy_cases", policy_case_id)
    require_owner(case["developer_id"])
    body = get_body()
    req_str(body, "appeal_statement")
    if case["status"] != "UPHELD":
        fail("ERR_INVALID_STATE", "Case is not UPHELD.")
    case["status"] = "APPEALED"
    touch(case)
    return ok(public(case))


@bp.post("/api/policy-cases/<policy_case_id>/appeal-decision")
def appeal_decision(policy_case_id):
    authenticate({"PolicyOfficer"})
    case = lookup("policy_cases", policy_case_id)
    _guard_sod(case)
    body = get_body()
    outcome = req_enum(body, "outcome", {"GRANTED", "DENIED"})
    req_str(body, "rationale")
    if case["status"] != "APPEALED":
        fail("ERR_INVALID_STATE", "Case is not APPEALED.")

    if outcome == "DENIED":
        case["status"] = "UPHELD"
        touch(case)
        return ok(public(case))

    case["status"] = "REINSTATED"
    touch(case)
    app = db.apps.get(case["app_id"])
    if app is not None:
        app["policy_strike_count"] = max(0, app.get("policy_strike_count", 0) - 1)
        touch(app)
    dev = db.developers.get(case["developer_id"])
    if dev is not None:
        dev["policy_strike_count"] = max(0, dev.get("policy_strike_count", 0) - 1)
        touch(dev)
    return ok(public(case))
