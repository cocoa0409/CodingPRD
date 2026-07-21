"""Developer account lifecycle."""
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
    req_bool,
    req_int,
    req_str,
    opt_bool,
    opt_str,
    require_owner,
    touch,
)
from services import (
    delist_app,
    developer_entries,
    lookup,
    recompute_risk,
    suspend_developer,
)

bp = Blueprint("developers", __name__)


def _new_developer(legal_name, email, country_code, tax_id_provided):
    return new_record(
        legal_name=legal_name,
        email=email,
        country_code=country_code,
        tax_id_provided=tax_id_provided,
        status="PENDING_VERIFICATION",
        payout_hold=False,
        risk_watch=False,
        policy_strike_count=0,
        lifetime_revenue_base_cents=0,
        unpaid_accrual_cents=0,
        negative_balance_cents=0,
        carryover_cents=0,
        risk_score=0,
        risk_variant="STANDARD",
    )


@bp.post("/api/developers")
def create_developer():
    authenticate({"PlatformAdmin"})
    body = get_body()
    legal_name = req_str(body, "legal_name")
    email = req_str(body, "email")
    country_code = req_str(body, "country_code")
    tax_id_provided = opt_bool(body, "tax_id_provided", False)
    rec = _new_developer(legal_name, email, country_code, tax_id_provided)
    db.developers[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.get("/api/developers")
def list_developers():
    authenticate({"PlatformAdmin", "FinanceOps", "PolicyOfficer"})
    limit, offset = pagination()
    rows = ordered(db.developers)
    rows = filter_eq(rows, "status")
    rows = filter_eq(rows, "country_code")
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/api/developers/<developer_id>")
def read_developer(developer_id):
    authenticate({"PlatformAdmin", "FinanceOps", "PolicyOfficer", "Developer"})
    dev = lookup("developers", developer_id)
    require_owner(dev["id"])
    return ok(public(dev))


@bp.get("/api/developers/<developer_id>/summary")
def developer_summary(developer_id):
    authenticate({"PlatformAdmin", "FinanceOps", "Developer"})
    dev = lookup("developers", developer_id)
    require_owner(dev["id"])
    return ok(
        {
            "developer_id": dev["id"],
            "unpaid_accrual_cents": dev["unpaid_accrual_cents"],
            "negative_balance_cents": dev["negative_balance_cents"],
            "carryover_cents": dev["carryover_cents"],
            "lifetime_revenue_base_cents": dev["lifetime_revenue_base_cents"],
            "risk_score": dev["risk_score"],
            "risk_variant": dev["risk_variant"],
            "payout_hold": dev["payout_hold"],
        }
    )


@bp.get("/api/developers/<developer_id>/ledger-entries")
def developer_ledger(developer_id):
    authenticate({"FinanceOps", "PlatformAdmin", "Developer"})
    dev = lookup("developers", developer_id)
    require_owner(dev["id"])
    limit, offset = pagination()
    rows = developer_entries(dev["id"])
    rows = filter_eq(rows, "entry_type")
    rows = filter_eq(rows, "settled")
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.post("/api/developers/<developer_id>/verify")
def verify_developer(developer_id):
    authenticate({"PlatformAdmin"})
    dev = lookup("developers", developer_id)
    if dev["status"] != "PENDING_VERIFICATION":
        fail("ERR_INVALID_STATE", "Developer is not PENDING_VERIFICATION.")
    if not dev["tax_id_provided"]:
        fail("ERR_TAX_ID_REQUIRED", "A tax identification number is required.")
    dev["status"] = "ACTIVE"
    touch(dev)
    return ok(public(dev))


@bp.post("/api/developers/<developer_id>/suspend")
def suspend_developer_route(developer_id):
    authenticate({"PolicyOfficer"})
    dev = lookup("developers", developer_id)
    body = get_body()
    req_str(body, "reason")
    if dev["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Developer is not ACTIVE.")
    suspend_developer(dev)
    return ok(public(dev))


@bp.post("/api/developers/<developer_id>/reinstate")
def reinstate_developer(developer_id):
    authenticate({"PolicyOfficer"})
    dev = lookup("developers", developer_id)
    body = get_body()
    req_str(body, "reason")
    if dev["status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE", "Developer is not SUSPENDED.")
    dev["status"] = "ACTIVE"
    dev["risk_watch"] = False
    if dev["negative_balance_cents"] == 0:
        dev["payout_hold"] = False
    recompute_risk(dev)
    touch(dev)
    return ok(public(dev))


@bp.post("/api/developers/<developer_id>/terminate")
def terminate_developer(developer_id):
    authenticate({"PlatformAdmin"})
    dev = lookup("developers", developer_id)
    body = get_body()
    req_str(body, "reason")
    if dev["status"] == "TERMINATED":
        fail("ERR_INVALID_STATE", "Developer is already TERMINATED.")
    previous = dev["status"]
    dev["status"] = "TERMINATED"
    touch(dev)
    if previous in ("ACTIVE", "SUSPENDED"):
        for app in ordered(db.apps):
            if app["developer_id"] == dev["id"] and app["status"] != "DELISTED":
                delist_app(app)
    return ok(public(dev))


@bp.post("/api/developers/<developer_id>/payout-holds")
def set_payout_hold(developer_id):
    authenticate({"FinanceOps"})
    dev = lookup("developers", developer_id)
    body = get_body()
    hold = req_bool(body, "hold")
    expected = req_int(body, "expected_developer_version")
    opt_str(body, "reason")
    if expected != dev["version"]:
        fail("ERR_STALE_DEVELOPER_VERSION", "expected_developer_version is stale.")
    dev["payout_hold"] = hold
    touch(dev)
    return ok(public(dev))


@bp.post("/api/developers/<developer_id>/tax-profile")
def set_tax_profile(developer_id):
    authenticate({"PlatformAdmin"})
    dev = lookup("developers", developer_id)
    body = get_body()
    tax_id_provided = req_bool(body, "tax_id_provided")
    opt_str(body, "reason")
    dev["tax_id_provided"] = tax_id_provided
    touch(dev)
    return ok(public(dev))
