"""CMI snapshot read endpoints (creation lives under /api/cdi-programs)."""
from flask import Blueprint, request

import db
from helpers import get_or_404, list_page
from middleware import require_roles
from response import success_list, success_object
from serializers import snapshot_out

bp = Blueprint("snapshots", __name__)

ROLES = {"CDIManager", "CDISpecialist", "HIMCoder", "ComplianceAuditor"}


@bp.route("/api/cmi-snapshots", methods=["GET"])
def list_snapshots():
    require_roles(ROLES)
    program_id = request.args.get("cdi_program_id")
    items = list(db.snapshots.values())
    if program_id is not None:
        items = [s for s in items if s["cdi_program_id"] == program_id]
    page, limit, offset, total = list_page(items)
    return success_list([snapshot_out(s) for s in page], limit, offset, total)


@bp.route("/api/cmi-snapshots/<snapshotId>", methods=["GET"])
def get_snapshot(snapshotId):
    require_roles(ROLES)
    snapshot = get_or_404(db.snapshots, snapshotId, "CMI snapshot")
    return success_object(snapshot_out(snapshot))
