"""Clients, service agreements, access grants (client-scoped)."""

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_AGREEMENT_EXISTS,
    ERR_INVALID_STATE,
)
from middleware import require_roles, check_client_user_scope
from response import success_object, success_list, parse_pagination
from util import (
    get_body,
    require_fields,
    reject_unknown,
    as_str,
    as_bool,
    as_int,
    as_number,
    as_enum,
    parse_iso8601,
    make_entity,
    bump,
    now_iso,
)
from services.serializers import (
    client_view,
    agreement_view,
    batch_view,
    access_grant_view,
    invoice_view,
)

bp = Blueprint("clients", __name__)

ALL_ROLES = (
    "PlatformAdmin", "IntakeClerk", "PrepTechnician", "ScanOperator", "QAReviewer",
    "Indexer", "DestructionSpecialist", "ComplianceOfficer", "BillingClerk", "ClientUser",
)
STAFF_ROLES = (
    "PlatformAdmin", "IntakeClerk", "PrepTechnician", "ScanOperator", "QAReviewer",
    "Indexer", "DestructionSpecialist", "ComplianceOfficer", "BillingClerk",
)


def _get_client_or_404(client_id):
    c = db.clients.get(client_id)
    if not c:
        raise ApiError(ERR_NOT_FOUND, "Client not found", 404)
    return c


@bp.route("/clients", methods=["POST"])
@require_roles("PlatformAdmin")
def create_client(_user_id, _role):
    body = get_body()
    require_fields(body, ["name", "hipaa_covered"])
    reject_unknown(body, {"name", "hipaa_covered"})
    client = make_entity(
        {
            "name": as_str(body["name"], "name"),
            "hipaa_covered": as_bool(body["hipaa_covered"], "hipaa_covered"),
            "status": "ACTIVE",
        }
    )
    db.clients[client["id"]] = client
    return success_object(client_view(client), status=201)


@bp.route("/clients", methods=["GET"])
@require_roles(*STAFF_ROLES)
def list_clients(_user_id, _role):
    limit, offset = parse_pagination(request.args)
    items = sorted(db.clients.values(), key=lambda c: (c["created_at"], c["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([client_view(c) for c in page], limit, offset, total)


@bp.route("/clients/<id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_client(id, _user_id, _role):
    client = _get_client_or_404(id)
    check_client_user_scope(_user_id, _role, client["id"])
    return success_object(client_view(client))


@bp.route("/clients/<id>/suspend", methods=["POST"])
@require_roles("PlatformAdmin")
def suspend_client(id, _user_id, _role):
    client = _get_client_or_404(id)
    if client["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Client is not ACTIVE", 409)
    client["status"] = "SUSPENDED"
    bump(client)
    return success_object(client_view(client))


@bp.route("/clients/<id>/reactivate", methods=["POST"])
@require_roles("PlatformAdmin")
def reactivate_client(id, _user_id, _role):
    client = _get_client_or_404(id)
    if client["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, "Client is not SUSPENDED", 409)
    client["status"] = "ACTIVE"
    bump(client)
    return success_object(client_view(client))


@bp.route("/clients/<id>/service-agreements", methods=["POST"])
@require_roles("PlatformAdmin")
def create_agreement(id, _user_id, _role):
    client = _get_client_or_404(id)
    body = get_body()
    require_fields(
        body,
        [
            "price_tier",
            "rush_multiplier",
            "storage_free_days",
            "storage_daily_rate_cents",
            "retention_days",
            "max_boxes_per_batch",
        ],
    )
    reject_unknown(
        body,
        {
            "price_tier",
            "rush_multiplier",
            "storage_free_days",
            "storage_daily_rate_cents",
            "retention_days",
            "max_boxes_per_batch",
        },
    )
    price_tier = as_enum(body["price_tier"], "price_tier", {"STANDARD", "VOLUME"})
    rush_multiplier = as_number(body["rush_multiplier"], "rush_multiplier")
    storage_free_days = as_int(body["storage_free_days"], "storage_free_days", minimum=0)
    storage_daily_rate_cents = as_int(
        body["storage_daily_rate_cents"], "storage_daily_rate_cents", minimum=0
    )
    retention_days = as_int(body["retention_days"], "retention_days", minimum=0)
    max_boxes_per_batch = as_int(body["max_boxes_per_batch"], "max_boxes_per_batch", minimum=1)
    # At most one agreement per client
    for a in db.service_agreements.values():
        if a["client_id"] == client["id"]:
            raise ApiError(ERR_AGREEMENT_EXISTS, "Client already has a service agreement", 409)
    agreement = make_entity(
        {
            "client_id": client["id"],
            "price_tier": price_tier,
            "rush_multiplier": rush_multiplier,
            "storage_free_days": storage_free_days,
            "storage_daily_rate_cents": storage_daily_rate_cents,
            "retention_days": retention_days,
            "max_boxes_per_batch": max_boxes_per_batch,
        }
    )
    db.service_agreements[agreement["id"]] = agreement
    return success_object(agreement_view(agreement), status=201)


@bp.route("/clients/<id>/service-agreements", methods=["GET"])
@require_roles("PlatformAdmin", "BillingClerk", "ComplianceOfficer")
def list_agreements(id, _user_id, _role):
    client = _get_client_or_404(id)
    limit, offset = parse_pagination(request.args)
    items = [a for a in db.service_agreements.values() if a["client_id"] == client["id"]]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([agreement_view(a) for a in page], limit, offset, total)


@bp.route("/service-agreements/<id>", methods=["GET"])
@require_roles("PlatformAdmin", "BillingClerk", "ComplianceOfficer")
def get_agreement(id, _user_id, _role):
    a = db.service_agreements.get(id)
    if not a:
        raise ApiError(ERR_NOT_FOUND, "Service agreement not found", 404)
    return success_object(agreement_view(a))


@bp.route("/clients/<id>/batches", methods=["GET"])
@require_roles(*ALL_ROLES)
def client_batches(id, _user_id, _role):
    client = _get_client_or_404(id)
    check_client_user_scope(_user_id, _role, client["id"])
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [b for b in db.batches.values() if b["client_id"] == client["id"]]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items.sort(key=lambda b: (b["created_at"], b["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([batch_view(b) for b in page], limit, offset, total)


@bp.route("/clients/<id>/access-grants", methods=["GET"])
@require_roles("PlatformAdmin", "ComplianceOfficer", "ClientUser")
def client_grants(id, _user_id, _role):
    client = _get_client_or_404(id)
    check_client_user_scope(_user_id, _role, client["id"])
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [g for g in db.access_grants.values() if g["client_id"] == client["id"]]
    if status is not None:
        items = [g for g in items if g["status"] == status]
    items.sort(key=lambda g: (g["created_at"], g["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([access_grant_view(g) for g in page], limit, offset, total)


@bp.route("/clients/<id>/access-grants", methods=["POST"])
@require_roles("ClientUser")
def create_grant(id, _user_id, _role):
    client = _get_client_or_404(id)
    check_client_user_scope(_user_id, _role, client["id"])
    body = get_body()
    require_fields(body, ["batch_id", "scope", "expires_at"])
    reject_unknown(body, {"batch_id", "scope", "expires_at"})
    batch_id = as_str(body["batch_id"], "batch_id")
    scope = as_enum(body["scope"], "scope", {"METADATA_ONLY", "FULL_IMAGE"})
    expires_dt = parse_iso8601(body["expires_at"], "expires_at")
    batch = db.batches.get(batch_id)
    if not batch or batch["client_id"] != client["id"]:
        raise ApiError(ERR_NOT_FOUND, "Batch not found for this client", 404)
    # Client suspension check (grant creation is a client-subtree mutation)
    if client["status"] == "SUSPENDED":
        from errors import ERR_CLIENT_SUSPENDED

        raise ApiError(ERR_CLIENT_SUSPENDED, "Client is suspended", 403)
    # vault_only: client hipaa_covered AND any doc in batch contains_phi
    vault_only = False
    if client["hipaa_covered"]:
        for d in db.documents.values():
            if d["batch_id"] == batch["id"] and d.get("contains_phi"):
                vault_only = True
                break
    from response import iso_ts

    grant = make_entity(
        {
            "client_id": client["id"],
            "batch_id": batch["id"],
            "scope": scope,
            "expires_at": iso_ts(expires_dt),
            "vault_only": vault_only,
            "status": "ACTIVE",
        }
    )
    db.access_grants[grant["id"]] = grant
    return success_object(access_grant_view(grant), status=201)


@bp.route("/clients/<id>/invoices", methods=["GET"])
@require_roles("PlatformAdmin", "BillingClerk", "ClientUser")
def client_invoices(id, _user_id, _role):
    client = _get_client_or_404(id)
    check_client_user_scope(_user_id, _role, client["id"])
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [i for i in db.invoices.values() if i["client_id"] == client["id"]]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items.sort(key=lambda i: (i["created_at"], i["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([invoice_view(i) for i in page], limit, offset, total)
