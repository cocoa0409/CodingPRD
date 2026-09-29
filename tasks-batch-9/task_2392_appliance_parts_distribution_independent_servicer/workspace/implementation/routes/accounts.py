"""Servicer accounts and technician certifications."""

from db import db, base_row, fmt, now, parse_stored, touch
from errors import ApiError
from flask import Blueprint
from middleware import authenticate, check_account_scope
from response import created, ok, ok_list
from services import calc, flows, serialize
from validation import parse_body, pagination, q_str

bp = Blueprint("accounts", __name__)

ALL_ROLES = ("PlatformAdmin", "CreditManager", "PricingAdmin", "WarrantyAdmin",
             "BranchCounterRep", "Servicer")
STAFF_ROLES = ("PlatformAdmin", "CreditManager", "PricingAdmin", "WarrantyAdmin",
               "BranchCounterRep")
CREDIT_WRITERS = ("CreditManager", "PlatformAdmin")
WARRANTY_WRITERS = ("WarrantyAdmin", "PlatformAdmin")

CREDIT_TERMS = {"PREPAY", "NET_15", "NET_30", "NET_45"}
ACCOUNT_STATUSES = {"ACTIVE", "CREDIT_HOLD", "SUSPENDED"}
CERT_LEVELS = {"BASIC", "ADVANCED", "SEALED_SYSTEM"}
CERT_STATUSES = {"ACTIVE", "EXPIRED", "REVOKED"}


# --------------------------------------------------------------------------
# servicer accounts
# --------------------------------------------------------------------------

@bp.post("/servicer-accounts")
def create_account():
    authenticate(CREDIT_WRITERS)
    body = parse_body([
        ("business_name", "str", True),
        ("oem_authorizations", "strarray", True),
        ("pricing_tier_id", "str", True),
        ("credit_terms", "enum", False, CREDIT_TERMS),
        ("credit_limit_cents", "money", False),
        ("core_liability_limit_cents", "money", False),
    ])
    flows.tier_or_404(body["pricing_tier_id"])
    row = base_row()
    row.update({
        "business_name": body["business_name"],
        "oem_authorizations": body["oem_authorizations"],
        "credit_terms": body.get("credit_terms", "PREPAY"),
        "credit_limit_cents": body.get("credit_limit_cents", 0),
        "core_liability_limit_cents": body.get("core_liability_limit_cents", 0),
        "pricing_tier_id": body["pricing_tier_id"],
        "account_status": "ACTIVE",
        "credit_used_cents": 0,
        "core_liability_cents": 0,
        "delinquency_score": 0,
        "rolling_12m_volume_cents": 0,
    })
    db.servicer_accounts[row["id"]] = row
    row["delinquency_score"] = flows.delinquency_score(row, "rolling")
    return created(serialize.servicer_account(row))


@bp.patch("/servicer-accounts/<account_id>")
def patch_account(account_id):
    authenticate(CREDIT_WRITERS)
    body = parse_body([
        ("credit_terms", "enum", False, CREDIT_TERMS),
        ("credit_limit_cents", "money", False),
        ("core_liability_limit_cents", "money", False),
        ("oem_authorizations", "strarray", False),
        ("pricing_tier_id", "str", False),
        ("account_status", "enum", False, ACCOUNT_STATUSES),
    ])
    account = flows.account_or_404(account_id)
    if "pricing_tier_id" in body:
        flows.tier_or_404(body["pricing_tier_id"])
    for field in ("credit_terms", "credit_limit_cents", "core_liability_limit_cents",
                  "oem_authorizations", "pricing_tier_id"):
        if field in body:
            account[field] = body[field]
    new_status = body.get("account_status")
    previous = account["account_status"]
    if new_status is not None and new_status != previous:
        account["account_status"] = new_status
    touch(account)
    if new_status is not None and new_status != previous:
        if previous == "ACTIVE" and new_status == "CREDIT_HOLD":
            flows.freeze_account_orders(account)
        elif previous == "CREDIT_HOLD" and new_status == "ACTIVE":
            flows.release_account_orders(account)
        elif new_status == "SUSPENDED" and previous in ("ACTIVE", "CREDIT_HOLD"):
            flows.suspend_account_orders(account)
    flows.sync_account(account)
    return ok(serialize.servicer_account(account))


@bp.post("/servicer-accounts/<account_id>/tier-review")
def tier_review(account_id):
    authenticate(CREDIT_WRITERS)
    parse_body([])
    account = flows.account_or_404(account_id)

    # 1. expire certifications whose expires_at lies before the logical clock
    for cert in flows.account_certs(account["id"]):
        if cert["cert_status"] != "ACTIVE":
            continue
        if parse_stored(cert["expires_at"]) < now():
            cert["cert_status"] = "EXPIRED"
            touch(cert)

    # 2. recompute rolling volume, 3. reassign the tier
    volume = flows.rolling_12m_volume_cents(account)
    account["rolling_12m_volume_cents"] = volume
    tier = flows.assign_pricing_tier(volume)
    if tier is not None:
        account["pricing_tier_id"] = tier["id"]

    # 4. lifetime delinquency, then the conditional credit hold
    account["delinquency_score"] = flows.delinquency_score(account, "lifetime")
    touch(account)
    if account["delinquency_score"] < calc.DELINQUENCY_HOLD_THRESHOLD:
        flows.apply_credit_hold(account)
    flows.sync_account(account)
    return ok(serialize.servicer_account(account))


@bp.get("/servicer-accounts")
def list_accounts():
    authenticate(STAFF_ROLES)
    limit, offset = pagination()
    rows = flows.rows_sorted(db.servicer_accounts)
    for field in ("pricing_tier_id", "account_status", "credit_terms"):
        value = q_str(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = serialize.paginate(rows, limit, offset)
    return ok_list([serialize.servicer_account(r) for r in page],
                   limit, offset, total)


@bp.get("/servicer-accounts/<account_id>")
def get_account(account_id):
    user_id, role = authenticate(ALL_ROLES)
    account = flows.account_or_404(account_id)
    check_account_scope(user_id, role, account_id)
    return ok(serialize.servicer_account(account))


@bp.get("/servicer-accounts/<account_id>/credit-summary")
def get_credit_summary(account_id):
    user_id, role = authenticate(("PlatformAdmin", "CreditManager", "Servicer"))
    account = flows.account_or_404(account_id)
    check_account_scope(user_id, role, account_id)
    return ok(serialize.credit_summary(account))


# --------------------------------------------------------------------------
# technician certifications
# --------------------------------------------------------------------------

@bp.post("/technician-certifications")
def create_certification():
    authenticate(WARRANTY_WRITERS)
    body = parse_body([
        ("servicer_account_id", "str", True),
        ("technician_name", "str", True),
        ("oem_code", "str", True),
        ("cert_level", "enum", True, CERT_LEVELS),
        ("training_completed_at", "dt", True),
        ("expires_at", "dt", True),
    ])
    flows.account_or_404(body["servicer_account_id"])
    trained = body["training_completed_at"]
    expires = body["expires_at"]

    # rule 37 precedes rule 38
    for peer in flows.account_certs(body["servicer_account_id"]):
        if peer["cert_status"] != "ACTIVE":
            continue
        if peer["technician_name"] != body["technician_name"]:
            continue
        if peer["oem_code"] != body["oem_code"]:
            continue
        peer_trained = parse_stored(peer["training_completed_at"])
        peer_expires = parse_stored(peer["expires_at"])
        if trained <= peer_expires and peer_trained <= expires:
            raise ApiError("ERR_CERT_WINDOW_OVERLAP",
                           "An ACTIVE certification already covers this interval")
    if not (trained < expires):
        raise ApiError("ERR_CERT_INTERVAL_INVALID",
                       "expires_at must be strictly after training_completed_at")

    row = base_row()
    row.update({
        "servicer_account_id": body["servicer_account_id"],
        "technician_name": body["technician_name"],
        "oem_code": body["oem_code"],
        "cert_level": body["cert_level"],
        "training_completed_at": fmt(trained),
        "expires_at": fmt(expires),
        "cert_status": "ACTIVE",
    })
    db.technician_certifications[row["id"]] = row
    return created(serialize.technician_certification(row))


@bp.post("/technician-certifications/<cert_id>/revoke")
def revoke_certification(cert_id):
    authenticate(WARRANTY_WRITERS)
    parse_body([("revocation_reason", "str", True)])
    cert = flows.find(db.technician_certifications, cert_id,
                      "ERR_TECHNICIAN_CERTIFICATION_NOT_FOUND")
    if cert["cert_status"] == "REVOKED":
        raise ApiError("ERR_CERT_ALREADY_REVOKED",
                       "Certification is already REVOKED")
    cert["cert_status"] = "REVOKED"
    touch(cert)
    return ok(serialize.technician_certification(cert))


@bp.get("/technician-certifications")
def list_certifications():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = flows.rows_sorted(db.technician_certifications)
    for field in ("servicer_account_id", "oem_code", "cert_status",
                  "technician_name"):
        value = q_str(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = serialize.paginate(rows, limit, offset)
    return ok_list([serialize.technician_certification(r) for r in page],
                   limit, offset, total)


@bp.get("/technician-certifications/<cert_id>")
def get_certification(cert_id):
    authenticate(ALL_ROLES)
    cert = flows.find(db.technician_certifications, cert_id,
                      "ERR_TECHNICIAN_CERTIFICATION_NOT_FOUND")
    return ok(serialize.technician_certification(cert))
