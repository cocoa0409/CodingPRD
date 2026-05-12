"""Contract endpoints + signing-step + signing-party + activate/void + progress + audit-logs."""

from flask import Blueprint, g, request

from db import DB, LOCK
from middleware import require_roles
from response import success_object, success_array
from services import contracts as csvc
from services.serializers import (
    serialize_contract, serialize_signing_step, serialize_signing_party,
    serialize_audit_log,
)
from services.calculations import compute_signing_progress
from ._helpers import parse_pagination, get_json_body


bp = Blueprint("contracts", __name__)


# ---- Contract --------------------------------------------------------------

@bp.route("/contracts", methods=["POST"])
@require_roles("ContractInitiator")
def post_contract():
    body = get_json_body()
    org_hint = request.headers.get("X-Org-ID")
    with LOCK:
        c = csvc.create_contract(
            body, actor_user_id=g.user_id, actor_role=g.role,
            actor_org_id_hint=org_hint,
        )
    return success_object(serialize_contract(c), 201)


@bp.route("/contracts", methods=["GET"])
@require_roles("ContractInitiator", "EvidenceArchivist", "PlatformAdmin")
def list_contracts_route():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    initiator_org_id = request.args.get("initiator_org_id")
    with LOCK:
        rows, total = csvc.list_contracts(status, initiator_org_id, limit, offset)
        data = [serialize_contract(r) for r in rows]
    return success_array(data, limit, offset, total)


@bp.route("/contracts/<cid>", methods=["GET"])
@require_roles("ContractInitiator", "Signer", "EvidenceArchivist", "PlatformAdmin")
def get_contract_route(cid):
    with LOCK:
        c = csvc.get_contract(cid)
    return success_object(serialize_contract(c))


@bp.route("/contracts/<cid>", methods=["PATCH"])
@require_roles("ContractInitiator")
def patch_contract_route(cid):
    body = get_json_body()
    with LOCK:
        c = csvc.patch_contract(cid, body)
    return success_object(serialize_contract(c))


# ---- SigningStep -----------------------------------------------------------

@bp.route("/contracts/<cid>/signing-steps", methods=["POST"])
@require_roles("ContractInitiator")
def post_signing_step(cid):
    body = get_json_body()
    with LOCK:
        s = csvc.append_signing_step(cid, body)
    return success_object(serialize_signing_step(s), 201)


# ---- SigningParty (under SigningStep) -------------------------------------

@bp.route("/contracts/<cid>/signing-steps/<sid>/parties", methods=["POST"])
@require_roles("ContractInitiator")
def post_signing_party(cid, sid):
    body = get_json_body()
    with LOCK:
        p = csvc.append_signing_party(cid, sid, body)
    return success_object(serialize_signing_party(p), 201)


# ---- Activate / Void -------------------------------------------------------

@bp.route("/contracts/<cid>/activate", methods=["POST"])
@require_roles("ContractInitiator")
def activate_contract_route(cid):
    with LOCK:
        c = csvc.activate_contract(cid, actor_user_id=g.user_id, actor_role=g.role)
    return success_object(serialize_contract(c))


@bp.route("/contracts/<cid>/void", methods=["POST"])
@require_roles("ContractInitiator")
def void_contract_route(cid):
    with LOCK:
        c = csvc.void_contract_manual(cid, actor_user_id=g.user_id, actor_role=g.role)
    return success_object(serialize_contract(c))


# ---- Progress --------------------------------------------------------------

@bp.route("/contracts/<cid>/progress", methods=["GET"])
@require_roles("ContractInitiator", "Signer", "EvidenceArchivist", "PlatformAdmin")
def progress_route(cid):
    variant = request.args.get("variant", "chronological")
    if variant not in ("chronological", "forward_looking"):
        from errors import validation_failed
        raise validation_failed("variant must be chronological or forward_looking")
    with LOCK:
        c = csvc.get_contract(cid)
        pct, breakdown = compute_signing_progress(cid, variant)
    return success_object({
        "progress_percent": pct,
        "variant": variant,
        "breakdown": breakdown,
    })


# ---- Audit logs ------------------------------------------------------------

@bp.route("/contracts/<cid>/audit-logs", methods=["GET"])
@require_roles("ContractInitiator", "EvidenceArchivist", "PlatformAdmin")
def audit_logs_route(cid):
    limit, offset = parse_pagination()
    with LOCK:
        csvc.get_contract(cid)
        rows = [a for a in DB.audit_logs if a.get("contract_id") == cid]
        rows.sort(key=lambda r: r["occurred_at"])
        total = len(rows)
        page = rows[offset:offset + limit]
        data = [serialize_audit_log(r) for r in page]
    return success_array(data, limit, offset, total)
