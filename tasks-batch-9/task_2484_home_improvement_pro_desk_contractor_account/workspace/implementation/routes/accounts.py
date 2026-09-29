"""Pro accounts, credit lines and resale-exemption certificates."""
from flask import Blueprint, request

import clock
import db
import response
import validate as v
from errors import ApiError
from middleware import auth, check_scope, scope_list
from services import credit as credit_svc
from services import tier as tier_svc

bp = Blueprint("accounts", __name__)

TIER_REVIEW_MODES = ("ROLLING_365_INCLUSIVE", "PINNED_AT_REVIEW")

ACCOUNT_READ_ROLES = ("PlatformAdmin", "CreditManager", "ProDeskAssociate",
                      "ContractorAdmin", "StoreOperations", "TaxComplianceOfficer")
CREDIT_READ_ROLES = ("CreditManager", "ProDeskAssociate", "ContractorAdmin")
CERT_ROLES = ("ContractorAdmin", "TaxComplianceOfficer", "ProDeskAssociate")


# --------------------------------------------------------------- pro accounts
@bp.post("/pro/pro-accounts")
def create_account():
    auth("PlatformAdmin")
    data = v.body()
    store = v.resolve_fk(data, "home_store_id", "stores", "ERR_STORE_NOT_FOUND")
    if store is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field 'home_store_id' is required.")
    rec = db.new_record("pro_accounts", {
        "business_name": v.req_str(data, "business_name"),
        "home_store_id": store["id"],
        "po_required": v.opt_bool(data, "po_required", False),
        "job_name_required": v.opt_bool(data, "job_name_required", False),
        "tier_review_mode": v.opt_enum(data, "tier_review_mode", TIER_REVIEW_MODES,
                                       default="PINNED_AT_REVIEW"),
        "baseline_volume_cents": v.opt_int(data, "baseline_volume_cents", default=0, minimum=0),
        "trailing_volume_cents": 0,
        "tier_code": "MEMBER",
        "tier_discount_pct": 0.0,
        "tier_reviewed_at": None,
        "rebate_accrued_cents": 0,
        "tax_exempt_state_codes": [],
        "status": "ACTIVE",
    })
    tier_svc.tier_review(rec)
    return response.obj(tier_svc.account_view(rec), 201)


@bp.get("/pro/pro-accounts/<pro_account_id>")
def get_account(pro_account_id):
    _user_id, role = auth(*ACCOUNT_READ_ROLES)
    account = db.require("pro_accounts", pro_account_id)
    check_scope(role, _user_id, account["id"])
    return response.obj(tier_svc.account_view(account))


@bp.get("/pro/pro-accounts")
def list_accounts():
    auth("PlatformAdmin", "CreditManager", "ProDeskAssociate")
    records = db.all_of("pro_accounts")
    for key in ("home_store_id", "tier_code", "status"):
        value = request.args.get(key)
        if value is not None:
            records = [r for r in records if r[key] == value]
    items, meta = v.paginate(records, serializer=tier_svc.account_view)
    return response.array(items, 200, meta)


@bp.post("/pro/pro-accounts/<pro_account_id>/volume-adjustments")
def volume_adjustment(pro_account_id):
    auth("CreditManager")
    account = db.require("pro_accounts", pro_account_id)
    data = v.body()
    delta = v.req_int(data, "delta_cents")
    v.req_str(data, "memo")
    account["baseline_volume_cents"] = (account.get("baseline_volume_cents") or 0) + delta
    tier_svc.tier_review(account)
    return response.obj(tier_svc.account_view(account))


@bp.post("/pro/pro-accounts/<pro_account_id>/reinstate")
def reinstate_account(pro_account_id):
    auth("CreditManager")
    account = db.require("pro_accounts", pro_account_id)
    if account["status"] != "HOLD":
        raise ApiError("ERR_INVALID_STATE", 409)
    line = credit_svc.credit_line_of(account["id"])
    if line is None or line["status"] != "ACTIVE":
        raise ApiError("ERR_CREDIT_LINE_FROZEN", 409)
    account["status"] = "ACTIVE"
    db.touch(account)
    return response.obj(tier_svc.account_view(account))


# --------------------------------------------------------------- credit lines
@bp.post("/pro/credit-lines")
def create_credit_line():
    auth("CreditManager")
    data = v.body()
    account = v.resolve_fk(data, "pro_account_id", "pro_accounts", "ERR_PRO_ACCOUNT_NOT_FOUND")
    if account is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field 'pro_account_id' is required.")
    limit_cents = v.req_int(data, "limit_cents", minimum=1)
    terms_days = v.req_int(data, "terms_days", minimum=1)
    if credit_svc.credit_line_of(account["id"]) is not None:
        raise ApiError("ERR_CREDIT_LINE_EXISTS", 409)
    rec = db.new_record("credit_lines", {
        "pro_account_id": account["id"],
        "limit_cents": limit_cents,
        "terms_days": terms_days,
        "exposure_cents": 0,
        "available_cents": limit_cents,
        "status": "ACTIVE",
        "frozen_reason_code": None,
    })
    credit_svc.recompute_exposure(rec)
    return response.obj(db.public(rec), 201)


@bp.get("/pro/credit-lines/<credit_line_id>")
def get_credit_line(credit_line_id):
    user_id, role = auth(*CREDIT_READ_ROLES)
    line = db.require("credit_lines", credit_line_id)
    check_scope(role, user_id, line["pro_account_id"])
    return response.obj(db.public(line))


@bp.get("/pro/credit-lines")
def list_credit_lines():
    user_id, role = auth(*CREDIT_READ_ROLES)
    records = db.all_of("credit_lines")
    for key in ("pro_account_id", "status"):
        value = request.args.get(key)
        if value is not None:
            records = [r for r in records if r[key] == value]
    records = scope_list(role, user_id, records, lambda r: r["pro_account_id"])
    items, meta = v.paginate(records)
    return response.array(items, 200, meta)


@bp.post("/pro/credit-lines/<credit_line_id>/freeze")
def freeze_credit_line(credit_line_id):
    auth("CreditManager")
    line = db.require("credit_lines", credit_line_id)
    data = v.body()
    reason_code = v.req_str(data, "reason_code")
    if line["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409)
    credit_svc.freeze(line, reason_code)
    return response.obj(db.public(line))


@bp.post("/pro/credit-lines/<credit_line_id>/reinstate")
def reinstate_credit_line(credit_line_id):
    auth("CreditManager")
    line = db.require("credit_lines", credit_line_id)
    if line["status"] == "ACTIVE":
        raise ApiError("ERR_CREDIT_LINE_NOT_FROZEN", 409)
    if line["exposure_cents"] >= credit_svc.freeze_threshold_cents(line):
        raise ApiError("ERR_UTILIZATION_STILL_HIGH", 409)
    line["status"] = "ACTIVE"
    line["frozen_reason_code"] = None
    db.touch(line)
    return response.obj(db.public(line))


# ------------------------------------------------------ tax-exempt certificates
@bp.post("/pro/tax-exempt-certificates")
def create_certificate():
    user_id, role = auth("ContractorAdmin")
    data = v.body()
    account = v.resolve_fk(data, "pro_account_id", "pro_accounts", "ERR_PRO_ACCOUNT_NOT_FOUND")
    if account is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field 'pro_account_id' is required.")
    state_code = v.req_str(data, "state_code")
    certificate_number = v.req_str(data, "certificate_number")
    expires_on = v.req_date(data, "expires_on")
    expected_version = v.req_int(data, "expected_pro_account_version")
    if expected_version != account["version"]:
        raise ApiError("ERR_STALE_VERSION", 412)
    check_scope(role, user_id, account["id"])
    rec = db.new_record("tax_exempt_certificates", {
        "pro_account_id": account["id"],
        "state_code": state_code,
        "certificate_number": certificate_number,
        "expires_on": clock.fmt_date(expires_on),
        "_expires_on": expires_on,
        "status": "PENDING",
        "verified_at": None,
        "revoke_reason_code": None,
    })
    # A filing mutates the account's exemption picture: bump the account version.
    db.touch(account)
    return response.obj(db.public(rec), 201)


@bp.get("/pro/tax-exempt-certificates/<tax_exempt_certificate_id>")
def get_certificate(tax_exempt_certificate_id):
    user_id, role = auth(*CERT_ROLES)
    cert = db.require("tax_exempt_certificates", tax_exempt_certificate_id)
    check_scope(role, user_id, cert["pro_account_id"])
    return response.obj(db.public(cert))


@bp.get("/pro/tax-exempt-certificates")
def list_certificates():
    user_id, role = auth(*CERT_ROLES)
    records = db.all_of("tax_exempt_certificates")
    for key in ("pro_account_id", "state_code", "status"):
        value = request.args.get(key)
        if value is not None:
            records = [r for r in records if r[key] == value]
    records = scope_list(role, user_id, records, lambda r: r["pro_account_id"])
    items, meta = v.paginate(records)
    return response.array(items, 200, meta)


def _refresh_account_exemptions(account):
    account["tax_exempt_state_codes"] = tier_svc.tax_exempt_state_codes(account)
    db.touch(account)


@bp.post("/pro/tax-exempt-certificates/<tax_exempt_certificate_id>/verify")
def verify_certificate(tax_exempt_certificate_id):
    auth("TaxComplianceOfficer")
    cert = db.require("tax_exempt_certificates", tax_exempt_certificate_id)
    if cert["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409)
    if not cert["_expires_on"] > clock.today():
        raise ApiError("ERR_CERTIFICATE_STATE_MISMATCH", 422)
    cert["status"] = "VERIFIED"
    cert["verified_at"] = clock.now_iso()
    db.touch(cert)
    for other in db.where("tax_exempt_certificates",
                          pro_account_id=cert["pro_account_id"],
                          state_code=cert["state_code"]):
        if other["id"] != cert["id"] and other["status"] == "VERIFIED":
            other["status"] = "SUPERSEDED"
            db.touch(other)
    account = db.get("pro_accounts", cert["pro_account_id"])
    if account is not None:
        _refresh_account_exemptions(account)
    return response.obj(db.public(cert))


@bp.post("/pro/tax-exempt-certificates/<tax_exempt_certificate_id>/revoke")
def revoke_certificate(tax_exempt_certificate_id):
    auth("TaxComplianceOfficer")
    cert = db.require("tax_exempt_certificates", tax_exempt_certificate_id)
    data = v.body()
    reason_code = v.req_str(data, "reason_code")
    if cert["status"] != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE", 409)
    cert["status"] = "REVOKED"
    cert["revoke_reason_code"] = reason_code
    db.touch(cert)
    account = db.get("pro_accounts", cert["pro_account_id"])
    if account is not None:
        _refresh_account_exemptions(account)
    return response.obj(db.public(cert))
