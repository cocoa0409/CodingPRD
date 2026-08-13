"""RiskModelSnapshot endpoints (PRD §3.11)."""
from flask import request

from db import STORE, make_entity, now, serialize, touch
from middleware import body, parse_pagination, req_enum, req_str, require_roles
from response import list_response, success
from services import FIELDS, generate_snapshot_fields, get_or_404, sorted_all
from . import bp

SNAPSHOT_KINDS = ["LEAK_SECTION", "CP_SECTION", "FULL"]


def ser(snap):
    return serialize(snap, FIELDS["risk_model_snapshots"])


@bp.post("/risk-model-snapshots")
@require_roles("IntegrityAnalyst")
def create_snapshot():
    d = body()
    label = req_str(d, "snapshot_label")
    kind = req_enum(d, "snapshot_kind", SNAPSHOT_KINDS)
    fields = generate_snapshot_fields(kind)
    snap = make_entity()
    snap.update({"snapshot_label": label, "snapshot_kind": kind,
                 "generated_at": now(), "status": "CURRENT"})
    snap.update(fields)
    STORE["risk_model_snapshots"][snap["id"]] = snap
    for other in STORE["risk_model_snapshots"].values():
        if (other["id"] != snap["id"] and other["snapshot_kind"] == kind
                and other["status"] == "CURRENT"):
            other["status"] = "STALE"
            touch(other)
    return success(ser(snap), code=201)


@bp.get("/risk-model-snapshots")
@require_roles("IntegrityAnalyst", "ComplianceOfficer")
def list_snapshots():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    kind = request.args.get("snapshot_kind")
    items = sorted_all("risk_model_snapshots")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if kind is not None:
        items = [s for s in items if s["snapshot_kind"] == kind]
    return list_response(items, ser, limit, offset)


@bp.get("/risk-model-snapshots/<sid>")
@require_roles("IntegrityAnalyst", "ComplianceOfficer")
def get_snapshot(sid):
    return success(ser(get_or_404("risk_model_snapshots", sid)))
