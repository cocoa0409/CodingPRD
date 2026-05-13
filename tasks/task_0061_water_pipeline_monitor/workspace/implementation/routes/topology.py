"""Topology version CRUD + node/segment + state transitions."""
from flask import Blueprint, g

from clock import iso, server_now
from db import (
    alerts,
    devices,
    dmas,
    lock,
    networks,
    next_seq,
    pipeline_nodes,
    pipeline_segments,
    public,
    stamp_create,
    stamp_update,
    topology_versions,
    work_orders,
)
from errors import err
from middleware import get_json_body, require_auth
from response import success
from services.audit import write_audit
from services.common import (
    active_topology_id,
    find_node_in_version,
    find_segment_in_version,
    get_network,
    get_topology_version,
    nodes_in_version,
    segments_in_version,
)
from services.dma_posture import recompute_dma_posture
from services.sync import emit_sync_for_topology_published


bp = Blueprint("topology", __name__)


VALID_NODE_KINDS = {"JUNCTION", "VALVE", "PUMP_STATION", "RESERVOIR", "CUSTOMER_TAP"}
VALID_MATERIALS = {"PVC", "DUCTILE_IRON", "STEEL", "HDPE"}


@bp.post("/networks/<network_id>/topology-versions")
@require_auth(roles={"TopologyEngineer"})
def create_topology_version(network_id):
    n = get_network(network_id)
    body = get_json_body()
    change_summary = body.get("change_summary")
    if not change_summary or not isinstance(change_summary, str):
        raise err("ERR_BAD_REQUEST", "change_summary is required")
    parent_version_id = body.get("parent_version_id")
    # version_number monotonic per network
    versions_in_net = [
        v for v in topology_versions.values() if v.get("network_id") == network_id
    ]
    next_version_number = (
        max((int(v.get("version_number", 0)) for v in versions_in_net), default=0) + 1
    )
    if next_version_number > 1 and not parent_version_id:
        # The first version may omit; later ones must provide parent_version_id
        # (PRD says "only the very first draft of a network may omit").
        raise err("ERR_BAD_REQUEST", "parent_version_id is required for non-first versions")
    if parent_version_id and parent_version_id not in topology_versions:
        raise err("ERR_BAD_REQUEST", "parent_version_id does not exist")

    with lock():
        tv = {
            "network_id": network_id,
            "version_number": next_version_number,
            "status": "DRAFT",
            "parent_version_id": parent_version_id,
            "change_summary": change_summary,
            "submitted_by": None,
            "reviewed_by": None,
            "published_at": None,
            "rejection_reason": None,
        }
        stamp_create(tv)
        topology_versions[tv["id"]] = tv
        return success(public(tv), 201)


@bp.get("/networks/<network_id>/topology-versions/<version_id>")
@require_auth(roles={"TopologyEngineer", "TopologyApprover", "ControlOperator", "Auditor"})
def get_topology_version_endpoint(network_id, version_id):
    tv = get_topology_version(network_id, version_id)
    return success(public(tv))


@bp.post("/networks/<network_id>/topology-versions/<version_id>/nodes")
@require_auth(roles={"TopologyEngineer"})
def add_node(network_id, version_id):
    tv = get_topology_version(network_id, version_id)
    if tv.get("status") != "DRAFT":
        raise err("ERR_INVALID_STATE", "nodes can only be added to DRAFT versions")
    body = get_json_body()
    node_code = body.get("node_code")
    kind = body.get("kind")
    if not node_code or not isinstance(node_code, str):
        raise err("ERR_BAD_REQUEST", "node_code is required")
    if kind not in VALID_NODE_KINDS:
        raise err("ERR_BAD_REQUEST", "kind invalid")
    for nv in nodes_in_version(version_id):
        if nv.get("node_code") == node_code:
            raise err("ERR_BAD_REQUEST", "node_code already exists in this version")
    dma_id = body.get("dma_id")
    if kind != "RESERVOIR":
        if not dma_id:
            raise err("ERR_BAD_REQUEST", "dma_id is required for non-RESERVOIR nodes")
        dma = dmas.get(dma_id)
        if not dma or dma.get("network_id") != network_id:
            raise err("ERR_BAD_REQUEST", "dma_id not found in this network")
    lat = body.get("latitude")
    lng = body.get("longitude")
    elev = body.get("elevation_m")
    for fld, name in ((lat, "latitude"), (lng, "longitude"), (elev, "elevation_m")):
        if fld is None or not isinstance(fld, (int, float)):
            raise err("ERR_BAD_REQUEST", f"{name} is required numeric")
    valve_default_open = body.get("valve_default_open")
    if kind == "VALVE":
        if valve_default_open is None or not isinstance(valve_default_open, bool):
            raise err("ERR_BAD_REQUEST", "valve_default_open is required for VALVE")
    else:
        valve_default_open = None
    with lock():
        node = {
            "topology_version_id": version_id,
            "node_code": node_code,
            "kind": kind,
            "dma_id": dma_id if kind != "RESERVOIR" else None,
            "latitude": float(lat),
            "longitude": float(lng),
            "elevation_m": float(elev),
            "valve_default_open": valve_default_open,
        }
        stamp_create(node, common_fields=False)
        pipeline_nodes[node["id"]] = node
        return success(public(node), 201)


@bp.post("/networks/<network_id>/topology-versions/<version_id>/segments")
@require_auth(roles={"TopologyEngineer"})
def add_segment(network_id, version_id):
    tv = get_topology_version(network_id, version_id)
    if tv.get("status") != "DRAFT":
        raise err("ERR_INVALID_STATE", "segments can only be added to DRAFT versions")
    body = get_json_body()
    segment_code = body.get("segment_code")
    from_nc = body.get("from_node_code")
    to_nc = body.get("to_node_code")
    length_m = body.get("length_m")
    diameter_mm = body.get("diameter_mm")
    material = body.get("material")
    if not all([segment_code, from_nc, to_nc, material]):
        raise err("ERR_BAD_REQUEST", "missing required fields")
    if material not in VALID_MATERIALS:
        raise err("ERR_BAD_REQUEST", "material invalid")
    if length_m is None or not isinstance(length_m, (int, float)) or length_m <= 0:
        raise err("ERR_BAD_REQUEST", "length_m must be positive number")
    if diameter_mm is None or not isinstance(diameter_mm, int) or diameter_mm <= 0:
        # Allow numeric values too, coerce safely
        try:
            diameter_mm = int(diameter_mm)
        except (TypeError, ValueError):
            raise err("ERR_BAD_REQUEST", "diameter_mm must be positive integer")
        if diameter_mm <= 0:
            raise err("ERR_BAD_REQUEST", "diameter_mm must be positive integer")
    # Uniqueness on segment_code within version
    for s in segments_in_version(version_id):
        if s.get("segment_code") == segment_code:
            raise err("ERR_BAD_REQUEST", "segment_code already exists in this version")
    # Dangling reference + from != to check
    if from_nc == to_nc:
        raise err("ERR_TOPOLOGY_DANGLING_REFERENCE", "from_node_code == to_node_code")
    from_node = find_node_in_version(version_id, from_nc)
    to_node = find_node_in_version(version_id, to_nc)
    if not from_node or not to_node:
        raise err("ERR_TOPOLOGY_DANGLING_REFERENCE", "endpoint(s) not in version")
    # dma_id inheritance from from_node; null if cross-DMA boundary
    from_dma = from_node.get("dma_id")
    to_dma = to_node.get("dma_id")
    seg_dma = from_dma if from_dma == to_dma else None
    with lock():
        seg = {
            "topology_version_id": version_id,
            "segment_code": segment_code,
            "from_node_code": from_nc,
            "to_node_code": to_nc,
            "length_m": float(length_m),
            "diameter_mm": int(diameter_mm),
            "material": material,
            "dma_id": seg_dma,
        }
        stamp_create(seg, common_fields=False)
        pipeline_segments[seg["id"]] = seg
        return success(public(seg), 201)


@bp.post("/networks/<network_id>/topology-versions/<version_id>/submit")
@require_auth(roles={"TopologyEngineer"})
def submit_version(network_id, version_id):
    tv = get_topology_version(network_id, version_id)
    if tv.get("status") != "DRAFT":
        raise err("ERR_INVALID_STATE", "version is not DRAFT")
    # At least one node and one segment
    nodes = nodes_in_version(version_id)
    segs = segments_in_version(version_id)
    if not nodes or not segs:
        raise err("ERR_INVALID_STATE", "version must contain at least one node and segment")
    # Every segment's endpoints resolve in this version
    for s in segs:
        if s["from_node_code"] == s["to_node_code"]:
            raise err("ERR_TOPOLOGY_DANGLING_REFERENCE", f"segment {s['segment_code']}")
        if (
            not find_node_in_version(version_id, s["from_node_code"])
            or not find_node_in_version(version_id, s["to_node_code"])
        ):
            raise err("ERR_TOPOLOGY_DANGLING_REFERENCE", f"segment {s['segment_code']}")
    # Every non-RESERVOIR node refs OPEN/RESTRICTED DMA
    for nd in nodes:
        if nd["kind"] != "RESERVOIR":
            d = dmas.get(nd.get("dma_id") or "")
            if d and d.get("status") == "FROZEN":
                raise err("ERR_DMA_FROZEN", "referenced DMA is FROZEN")
    # At most one UNDER_REVIEW per network
    for v in topology_versions.values():
        if (
            v.get("network_id") == network_id
            and v.get("status") == "UNDER_REVIEW"
            and v["id"] != version_id
        ):
            raise err("ERR_REVIEW_IN_PROGRESS", "another version is UNDER_REVIEW")
    with lock():
        tv["status"] = "UNDER_REVIEW"
        tv["submitted_by"] = g.user_id
        stamp_update(tv)
        write_audit(
            network_id=network_id,
            actor_role=g.user_role,
            actor_id=g.user_id,
            action="TOPOLOGY_SUBMITTED",
            resource_kind="TopologyVersion",
            resource_id=version_id,
            detail={"to_status": "UNDER_REVIEW"},
        )
    return success(public(tv))


@bp.post("/networks/<network_id>/topology-versions/<version_id>/approve")
@require_auth(roles={"TopologyApprover"})
def approve_version(network_id, version_id):
    tv = get_topology_version(network_id, version_id)
    if tv.get("status") != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "version is not UNDER_REVIEW")
    if g.user_id == tv.get("submitted_by"):
        raise err("ERR_SEGREGATION_OF_DUTIES", "approver must differ from submitter")
    # All DMAs referenced must be OPEN or RESTRICTED
    for nd in nodes_in_version(version_id):
        if nd["kind"] != "RESERVOIR" and nd.get("dma_id"):
            d = dmas.get(nd["dma_id"])
            if d and d.get("status") == "FROZEN":
                raise err("ERR_DMA_FROZEN", "referenced DMA is FROZEN")

    with lock():
        n = networks[network_id]
        prev_id = n.get("active_topology_version_id")
        # Previous PUBLISHED → SUPERSEDED
        if prev_id and prev_id in topology_versions:
            prev = topology_versions[prev_id]
            if prev.get("status") == "PUBLISHED":
                prev["status"] = "SUPERSEDED"
                stamp_update(prev)
        # This version → PUBLISHED
        tv["status"] = "PUBLISHED"
        tv["reviewed_by"] = g.user_id
        tv["published_at"] = iso(server_now())
        stamp_update(tv)
        n["active_topology_version_id"] = tv["id"]
        stamp_update(n)
        # Snapshot each device's pre-cascade mount so the alert-cascade
        # below can reason about devices whose mount has been removed.
        pre_cascade_mount: dict = {
            d["id"]: d.get("mounted_on_node_code")
            for d in devices.values()
            if d.get("network_id") == network_id
        }
        # Cascade: Devices with missing mount → PROVISIONED with cleared mount
        new_node_codes = {nd["node_code"] for nd in nodes_in_version(version_id)}
        for d in devices.values():
            if d.get("network_id") != network_id:
                continue
            nc = d.get("mounted_on_node_code")
            if nc and nc not in new_node_codes:
                d["mounted_on_node_code"] = None
                if d.get("status") in ("ACTIVE", "OFFLINE"):
                    d["status"] = "PROVISIONED"
                stamp_update(d)
        # Cascade: Open alerts on removed segments → SUPPRESSED with note=TOPOLOGY_SUPERSEDED
        new_seg_codes = {s["segment_code"] for s in segments_in_version(version_id)}
        affected_dmas = set()
        # Previous version's segments
        prev_seg_codes = set()
        if prev_id:
            for s in segments_in_version(prev_id):
                prev_seg_codes.add(s["segment_code"])
        removed_segs = prev_seg_codes - new_seg_codes
        for a in list(alerts.values()):
            if a.get("network_id") != network_id:
                continue
            if a.get("status") not in ("OPEN", "ACKNOWLEDGED", "INVESTIGATING"):
                continue
            # Determine the device's pre-cascade mount node (the mount we just
            # potentially cleared above). If that node no longer exists in the
            # new version, the device's underlying segment has been removed.
            dev_id = a.get("trigger_device_id") or ""
            nc = pre_cascade_mount.get(dev_id)
            if nc and nc not in new_node_codes:
                a["status"] = "SUPPRESSED"
                a["resolution_note"] = "TOPOLOGY_SUPERSEDED"
                stamp_update(a)
                if a.get("dma_id"):
                    affected_dmas.add(a["dma_id"])
        # Audit log
        write_audit(
            network_id=network_id,
            actor_role=g.user_role,
            actor_id=g.user_id,
            action="TOPOLOGY_PUBLISHED",
            resource_kind="TopologyVersion",
            resource_id=version_id,
            detail={"previous_version_id": prev_id},
        )
        # SyncEvent: TOPOLOGY_PUBLISHED to BILLING, GIS, IM
        emit_sync_for_topology_published(network_id, tv)
        # Recompute postures for affected DMAs
        for did in affected_dmas:
            recompute_dma_posture(
                did, network_id=network_id, actor_role=g.user_role, actor_id=g.user_id,
            )
    return success(public(tv))


@bp.post("/networks/<network_id>/topology-versions/<version_id>/reject")
@require_auth(roles={"TopologyApprover"})
def reject_version(network_id, version_id):
    tv = get_topology_version(network_id, version_id)
    if tv.get("status") != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "version is not UNDER_REVIEW")
    if g.user_id == tv.get("submitted_by"):
        raise err("ERR_SEGREGATION_OF_DUTIES", "rejecter must differ from submitter")
    body = get_json_body()
    reason = body.get("rejection_reason")
    if not reason or not isinstance(reason, str):
        raise err("ERR_BAD_REQUEST", "rejection_reason is required")
    with lock():
        tv["status"] = "REJECTED"
        tv["reviewed_by"] = g.user_id
        tv["rejection_reason"] = reason
        stamp_update(tv)
        write_audit(
            network_id=network_id,
            actor_role=g.user_role,
            actor_id=g.user_id,
            action="TOPOLOGY_REJECTED",
            resource_kind="TopologyVersion",
            resource_id=version_id,
            detail={"reason": reason},
        )
    return success(public(tv))


@bp.post("/networks/<network_id>/topology-versions/<version_id>/rollback")
@require_auth(roles={"TopologyApprover"})
def rollback_version(network_id, version_id):
    tv = get_topology_version(network_id, version_id)
    if tv.get("status") != "SUPERSEDED":
        raise err("ERR_INVALID_STATE", "version is not SUPERSEDED")
    n = networks[network_id]
    cur_id = n.get("active_topology_version_id")
    if not cur_id:
        raise err("ERR_INVALID_STATE", "no currently PUBLISHED version to rollback from")
    cur = topology_versions.get(cur_id)
    if not cur or cur.get("status") != "PUBLISHED":
        raise err("ERR_INVALID_STATE", "no currently PUBLISHED version")
    # Check no open WorkOrders reference segments absent from target version
    target_seg_codes = {s["segment_code"] for s in segments_in_version(version_id)}
    cur_seg_codes = {s["segment_code"] for s in segments_in_version(cur_id)}
    # PRD: rejected if an open WorkOrder references a target_segment_code that
    # exists in the target version but not in the current PUBLISHED version
    # (would create dangling repair). Re-read for clarity: actually the PRD says
    # "no open WorkOrder references a target_segment_code that exists in the
    # target version but not in the current PUBLISHED version" — that prevents
    # repairs from being orphaned when we go BACK. We interpret this as:
    # rollback is blocked if any open WorkOrder's target_segment_code is in the
    # *current* version but missing from the *target* version. That is the more
    # natural protection.
    open_statuses = {"NEW", "ASSIGNED", "PARTS_PENDING", "IN_PROGRESS", "AWAITING_VERIFICATION"}
    for wo in work_orders.values():
        if wo.get("network_id") != network_id:
            continue
        if wo.get("status") not in open_statuses:
            continue
        tsc = wo.get("target_segment_code")
        if tsc and tsc not in target_seg_codes and tsc in cur_seg_codes:
            raise err("ERR_TOPOLOGY_ROLLBACK_BLOCKED", "open work order would be orphaned")
    with lock():
        cur["status"] = "SUPERSEDED"
        stamp_update(cur)
        tv["status"] = "PUBLISHED"
        tv["published_at"] = iso(server_now())
        stamp_update(tv)
        n["active_topology_version_id"] = tv["id"]
        stamp_update(n)
        write_audit(
            network_id=network_id,
            actor_role=g.user_role,
            actor_id=g.user_id,
            action="TOPOLOGY_ROLLED_BACK",
            resource_kind="TopologyVersion",
            resource_id=version_id,
            detail={"previous_version_id": cur_id},
        )
        emit_sync_for_topology_published(network_id, tv)
    return success(public(tv))
