"""Client, SiteAudit, and client lifecycle routes."""
from flask import Blueprint, request

import calc
import services
from auth import require_auth, require_role, VALID_ROLES, Principal
from db import store, base_record, touch
from errors import err
from helpers import (
    get_body, require_str, opt_str, require_int, find, assert_owns_client,
    paginate, parse_pagination,
)
from response import ok_object, ok_list

bp = Blueprint("clients", __name__)


# ---------------------------------------------------------------------------
# Client CRUD
# ---------------------------------------------------------------------------


@bp.route("/clients", methods=["POST"])
def create_client():
    # Bootstrap endpoint: auth headers not required (priority-1 skip); priority-2
    # role check still applies if a role header is supplied.
    role = request.headers.get("X-User-Role")
    principal = None
    if role is not None:
        if role not in VALID_ROLES:
            raise err("ERR_MISSING_AUTH", "Malformed X-User-Role header")
        principal = Principal(request.headers.get("X-User-ID"), role)
        require_role(principal, ["AgencyAdmin", "Reseller"])

    body = get_body()
    company_name = require_str(body, "company_name")
    primary_domain = require_str(body, "primary_domain")
    reseller_id = opt_str(body, "reseller_id", default=None)

    if reseller_id is not None:
        find("reseller", reseller_id)  # FK existence

    # Reseller actor may only create clients for itself.
    if principal is not None and principal.role == "Reseller":
        if reseller_id != principal.user_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Reseller may only create its own clients")

    rec = base_record(versioned=True)
    rec.update({
        "reseller_id": reseller_id,
        "company_name": company_name,
        "primary_domain": primary_domain,
        "status": "PROSPECT",
        "health_score": 100,
        "open_dispute_count": 0,
    })
    store.clients[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.route("/clients/<cid>", methods=["GET"])
def get_client(cid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Reseller", "Client"])
    client = find("client", cid)
    assert_owns_client(principal, client)
    # Recompute health_score on read (per endpoint side effect).
    services.recompute_open_dispute_count(client)
    services.recompute_health_score(client)
    return ok_object(client, 200)


@bp.route("/clients", methods=["GET"])
def list_clients():
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Reseller"])
    parse_pagination()  # validate pagination params early
    reseller_filter = request.args.get("reseller_id")
    status_filter = request.args.get("status")

    records = list(store.clients.values())
    # Reseller actor scoped to own clients.
    if principal.role == "Reseller":
        records = [c for c in records if c.get("reseller_id") == principal.user_id]
    if reseller_filter is not None:
        records = [c for c in records if c.get("reseller_id") == reseller_filter]
    if status_filter is not None:
        records = [c for c in records if c["status"] == status_filter]

    page, limit, offset, total = paginate(records)
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Client lifecycle transitions
# ---------------------------------------------------------------------------


@bp.route("/clients/<cid>/pause", methods=["POST"])
def pause_client(cid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    client = find("client", cid)
    if client["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Client must be ACTIVE to pause")

    client["status"] = "PAUSED"
    # cascade: ACTIVE retainers -> SUSPENDED
    for r in store.retainers.values():
        if r["client_id"] == cid and r["status"] == "ACTIVE":
            r["status"] = "SUSPENDED"
            touch(r)
    # cascade: LIVE ad campaigns -> PAUSED
    for camp in store.ad_campaigns.values():
        if camp["client_id"] == cid and camp["lifecycle_status"] == "LIVE":
            camp["lifecycle_status"] = "PAUSED"
            touch(camp)
    touch(client)
    return ok_object(client, 200)


@bp.route("/clients/<cid>/resume", methods=["POST"])
def resume_client(cid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    client = find("client", cid)
    if client["status"] != "PAUSED":
        raise err("ERR_INVALID_STATE", "Client must be PAUSED to resume")

    client["status"] = "ACTIVE"
    # cascade: SUSPENDED retainers -> ACTIVE (campaigns are NOT relaunched)
    for r in store.retainers.values():
        if r["client_id"] == cid and r["status"] == "SUSPENDED":
            r["status"] = "ACTIVE"
            touch(r)
    touch(client)
    return ok_object(client, 200)


@bp.route("/clients/<cid>/churn", methods=["POST"])
def churn_client(cid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    client = find("client", cid)
    if client["status"] not in ("ACTIVE", "PAUSED"):
        raise err("ERR_INVALID_STATE", "Client must be ACTIVE or PAUSED to churn")

    # blocked while any contract is ACTIVE or RENEWED
    for contract in store.contracts.values():
        if contract["client_id"] == cid and contract["status"] in ("ACTIVE", "RENEWED"):
            raise err("ERR_CONTRACT_STILL_BINDING", "Terminate binding contracts before churn")

    was_active = client["status"] == "ACTIVE"
    client["status"] = "CHURNED"

    # cascade: all retainers -> CLOSED; each CLOSED retainer cancels its
    # non-terminal deliverables (depth-3 chain).
    for r in store.retainers.values():
        if r["client_id"] != cid:
            continue
        if r["status"] != "CLOSED":
            r["status"] = "CLOSED"
            services.cancel_non_terminal_deliverables_for_retainer(r)
            touch(r)

    # cascade from ACTIVE churn: ad campaigns DRAFT/LIVE/PAUSED -> ENDED
    if was_active:
        for camp in store.ad_campaigns.values():
            if camp["client_id"] != cid:
                continue
            if camp["lifecycle_status"] in ("DRAFT", "LIVE", "PAUSED"):
                camp["lifecycle_status"] = "ENDED"
                touch(camp)

    touch(client)
    return ok_object(client, 200)


# ---------------------------------------------------------------------------
# SiteAudit
# ---------------------------------------------------------------------------


@bp.route("/clients/<cid>/audits", methods=["POST"])
def create_audit(cid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    client = find("client", cid)

    body = get_body()
    technical_score = require_int(body, "technical_score", minimum=0, maximum=100)
    content_score = require_int(body, "content_score", minimum=0, maximum=100)
    backlink_score = require_int(body, "backlink_score", minimum=0, maximum=100)

    if client["status"] != "PROSPECT":
        raise err("ERR_INVALID_STATE", "Audit may only be recorded for a PROSPECT client")

    composite = calc.audit_composite_score(technical_score, content_score, backlink_score)

    rec = base_record(versioned=False)
    rec.update({
        "client_id": cid,
        "technical_score": technical_score,
        "content_score": content_score,
        "backlink_score": backlink_score,
        "composite_score": composite,
    })
    store.site_audits[rec["id"]] = rec

    client["status"] = "AUDITED"
    touch(client)
    return ok_object(rec, 201)


@bp.route("/audits/<aid>", methods=["GET"])
def get_audit(aid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Client"])
    audit = find("site_audit", aid)
    client = find("client", audit["client_id"])
    assert_owns_client(principal, client)
    return ok_object(audit, 200)


@bp.route("/clients/<cid>/audits", methods=["GET"])
def list_audits(cid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Client"])
    client = find("client", cid)
    assert_owns_client(principal, client)
    parse_pagination()
    records = [a for a in store.site_audits.values() if a["client_id"] == cid]
    page, limit, offset, total = paginate(records)
    return ok_list(page, limit, offset, total)
