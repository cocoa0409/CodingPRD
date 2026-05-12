"""EvidencePackage endpoints (read, preview, seal, export)."""

from flask import Blueprint, g

from db import LOCK
from middleware import require_roles
from response import success_object
from services import evidence as svc
from services.serializers import serialize_evidence_package
from ._helpers import get_json_body


bp = Blueprint("evidence", __name__)


@bp.route("/contracts/<cid>/evidence", methods=["GET"])
@require_roles("ContractInitiator", "EvidenceArchivist", "PlatformAdmin")
def get_evidence(cid):
    with LOCK:
        pkg = svc.get_evidence_package(cid)
    return success_object(serialize_evidence_package(pkg))


@bp.route("/contracts/<cid>/evidence/preview", methods=["GET"])
@require_roles("ContractInitiator", "EvidenceArchivist", "PlatformAdmin")
def preview_evidence(cid):
    with LOCK:
        data = svc.get_provisional(cid)
    return success_object(data)


@bp.route("/contracts/<cid>/evidence/seal", methods=["POST"])
@require_roles("EvidenceArchivist")
def seal_route(cid):
    body = get_json_body()
    with LOCK:
        pkg = svc.seal_evidence(cid, body, actor_user_id=g.user_id, actor_role=g.role)
    return success_object(serialize_evidence_package(pkg))


@bp.route("/contracts/<cid>/evidence/export", methods=["POST"])
@require_roles("EvidenceArchivist")
def export_route(cid):
    with LOCK:
        pkg = svc.export_evidence(cid, actor_user_id=g.user_id, actor_role=g.role)
    return success_object(serialize_evidence_package(pkg))
