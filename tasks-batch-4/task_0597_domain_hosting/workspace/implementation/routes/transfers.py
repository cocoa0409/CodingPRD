"""Transfers and the EPP negotiation cycle (PRD 3.7)."""

from flask import Blueprint, request

import config
import db
import middleware as mw
import response
import validation as v
from errors import ApiError
from services import cascades, pricing
from services.serializers import transfer_out

bp = Blueprint("transfers", __name__)


@bp.post("/transfer-requests")
@mw.roles_required("Registrant")
def open_transfer():
    data = v.body()
    account_id = v.req_str(data, "account_id")
    direction = v.req_enum(data, "direction", config.TRANSFER_DIRECTIONS)
    domain_name = v.domain_label(v.req_str(data, "domain_name"))
    tld = v.req_enum(data, "tld", config.TLDS)
    epp_auth_code = v.req_str(data, "epp_auth_code")
    domain_id = v.opt_str(data, "domain_id", None, allow_empty=False)
    if direction == "OUT" and domain_id is None:
        raise v.bad("domain_id is required for an outbound transfer.")

    account = v.get_account(account_id)
    domain = v.get_domain(domain_id) if domain_id is not None else None

    mw.require_owner(account["id"])
    if domain is not None:
        mw.require_owner(domain["account_id"])
    mw.gate_account_suspended()

    if direction == "IN":
        fqdn = pricing.make_fqdn(domain_name, tld)
        if not pricing.is_available(fqdn):
            raise ApiError("ERR_DOMAIN_UNAVAILABLE")

    transfer = db.base_record()
    transfer.update(
        {
            "account_id": account_id,
            "domain_id": domain["id"] if (direction == "OUT" and domain) else None,
            "direction": direction,
            "domain_name": domain_name,
            "tld": tld,
            "epp_auth_code": epp_auth_code,
            "status": "INITIATED",
            "attempt_count": 0,
            "rejection_reason": None,
        }
    )
    db.transfer_requests[transfer["id"]] = transfer
    return response.created(transfer_out(transfer))


@bp.get("/transfer-requests/<transfer_id>")
@mw.roles_required("Registrant", "SupportAgent", "PlatformAdmin")
def read_transfer(transfer_id):
    transfer = v.get_transfer_request(transfer_id)
    mw.require_owner(transfer["account_id"])
    return response.ok(transfer_out(transfer))


@bp.get("/transfer-requests")
@mw.roles_required("Registrant", "SupportAgent", "PlatformAdmin")
def list_transfers():
    limit, offset = v.pagination()
    account_id = request.args.get("account_id")
    domain_id = request.args.get("domain_id")
    status = v.query_enum("status", config.TRANSFER_STATUSES)

    rows = db.ordered(
        db.transfer_requests,
        lambda t: (account_id is None or t["account_id"] == account_id)
        and (domain_id is None or t["domain_id"] == domain_id)
        and (status is None or t["status"] == status),
    )
    rows = mw.scope_to_registrant(rows, lambda t: t["account_id"])
    page, total = v.paginate(rows, limit, offset, transfer_out)
    return response.listing(page, limit, offset, total)


@bp.post("/transfer-requests/<transfer_id>/submit")
@mw.roles_required("Registrant")
def submit_transfer(transfer_id):
    transfer = v.get_transfer_request(transfer_id)
    mw.require_owner(transfer["account_id"])
    mw.gate_account_suspended()

    if transfer["status"] != "INITIATED":
        raise ApiError("ERR_TRANSFER_INVALID_STATE")

    if transfer["direction"] == "OUT":
        domain = db.domains.get(transfer["domain_id"])
        if domain is None:
            raise ApiError("ERR_DOMAIN_NOT_FOUND")

        # 1. lifecycle
        if domain["lifecycle_status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_DOMAIN_STATE")
        # 2. abuse hold — checked BEFORE the lock
        if cascades.has_abuse_hold(domain):
            raise ApiError("ERR_ABUSE_HOLD_ACTIVE")
        # 3. registrar lock
        if domain["lock_status"] != "UNLOCKED":
            raise ApiError("ERR_DOMAIN_LOCKED")
        # 4. 60-day post-registration lock period
        registered_at = domain["_registered_at"]
        now = db.clock_now()
        if registered_at is None or now < registered_at + db.days(config.TRANSFER_LOCK_DAYS):
            raise ApiError("ERR_TRANSFER_LOCK_PERIOD")
        # 5. EPP auth code
        if transfer["epp_auth_code"] != domain["epp_auth_code"]:
            raise ApiError("ERR_EPP_AUTH_MISMATCH")
    else:
        fqdn = pricing.make_fqdn(transfer["domain_name"], transfer["tld"])
        if not pricing.is_available(fqdn):
            raise ApiError("ERR_DOMAIN_UNAVAILABLE")

    transfer["status"] = "PENDING_ACK"
    transfer["attempt_count"] += 1
    db.touch(transfer)
    return response.ok(transfer_out(transfer))


@bp.post("/transfer-requests/<transfer_id>/registry-response")
@mw.roles_required("PlatformAdmin")
def registry_response(transfer_id):
    data = v.body()
    outcome = v.req_enum(data, "outcome", config.REGISTRY_OUTCOMES)
    reason = v.opt_str(data, "reason", None)

    transfer = v.get_transfer_request(transfer_id)
    if transfer["status"] != "PENDING_ACK":
        raise ApiError("ERR_TRANSFER_INVALID_STATE")

    if outcome == "APPROVED":
        if transfer["direction"] == "IN":
            _create_inbound_domain(transfer)
        else:
            domain = db.domains.get(transfer["domain_id"])
            if domain is not None and domain["lifecycle_status"] == "ACTIVE":
                domain["lifecycle_status"] = "TRANSFERRED_OUT"
                domain["auto_renew_enabled"] = False
                db.touch(domain)
                cascades.cascade_domain_terminal(domain)
        transfer["status"] = "COMPLETED"
        db.touch(transfer)
    else:
        if transfer["attempt_count"] >= config.MAX_TRANSFER_ATTEMPTS:
            transfer["status"] = "FAILED"
        else:
            transfer["status"] = "REJECTED"
        transfer["rejection_reason"] = reason
        db.touch(transfer)

    return response.ok(transfer_out(transfer))


def _create_inbound_domain(transfer):
    now = db.clock_now()
    account = db.accounts.get(transfer["account_id"])
    domain = db.base_record()
    domain.update(
        {
            "account_id": transfer["account_id"],
            "domain_name": transfer["domain_name"],
            "tld": transfer["tld"],
            "fqdn": pricing.make_fqdn(transfer["domain_name"], transfer["tld"]),
            "is_premium": pricing.is_premium(transfer["domain_name"]),
            "lifecycle_status": "ACTIVE",
            "lock_status": "LOCKED",
            "suspension_reason": None,
            "whois_privacy_enabled": False,
            "auto_renew_enabled": (
                account["auto_renew_default"] if account is not None else True
            ),
            "registrant_name": account["company_name"] if account is not None else None,
            "registrant_email": account["email"] if account is not None else None,
            "term_years": 1,
            "_registered_at": now,
            "_expires_at": now + db.years(1),
            "epp_auth_code": db.mint_code(16),
        }
    )
    db.domains[domain["id"]] = domain
    transfer["domain_id"] = domain["id"]
    return domain


@bp.post("/transfer-requests/<transfer_id>/retry")
@mw.roles_required("Registrant")
def retry_transfer(transfer_id):
    data = v.body()
    epp_auth_code = v.req_str(data, "epp_auth_code")

    transfer = v.get_transfer_request(transfer_id)
    mw.require_owner(transfer["account_id"])
    mw.gate_account_suspended()

    if transfer["status"] != "REJECTED":
        raise ApiError("ERR_TRANSFER_INVALID_STATE")
    if transfer["attempt_count"] >= config.MAX_TRANSFER_ATTEMPTS:
        raise ApiError("ERR_TRANSFER_MAX_ATTEMPTS")

    transfer["status"] = "INITIATED"
    transfer["epp_auth_code"] = epp_auth_code
    transfer["rejection_reason"] = None
    db.touch(transfer)
    return response.ok(transfer_out(transfer))
