"""AuditEvent listing endpoint."""

import db
from middleware import require_roles
from response import success_list
from routes import make_bp
from util import paginate

bp = make_bp("audit")


@bp.route("/nrw/audit-events", methods=["GET"])
def list_audit_events():
    require_roles({"ProgramDirector", "RegulatorLiaison"})
    from flask import request
    items = [db.store["audit_events"][eid] for eid in db.audit_order]
    entity_type = request.args.get("entity_type")
    if entity_type is not None:
        items = [e for e in items if e["entity_type"] == entity_type]
    entity_id = request.args.get("entity_id")
    if entity_id is not None:
        items = [e for e in items if e["entity_id"] == entity_id]
    actor = request.args.get("actor_user_id")
    if actor is not None:
        items = [e for e in items if e["actor_user_id"] == actor]
    page, meta = paginate(items)
    return success_list([db.serialize_audit(e) for e in page], meta)
