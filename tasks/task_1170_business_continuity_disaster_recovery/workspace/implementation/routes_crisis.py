"""Comm trees, activations, notifications, attestations (PRD §3.8, §3.9)."""
import uuid

from flask import Blueprint

from calc import (SEV_CRITERIA, SIGN_THRESHOLD, approved_plan,
                  attestation_readiness, attestation_snapshot,
                  tree_nodes_in_order)
from core import (ALL_ROLES, DB, actor, apply_filters, as_bool, as_dt,
                  as_enum, as_int, as_str, body, bump, fail, new_id, next_seq,
                  not_found, now_dt, ok, opt_str, paginate, req,
                  sorted_by_created, stamp_new, tick_dt, validation)
from serializers import (activation_view, attestation_view, node_view,
                         notification_view)

bp = Blueprint("crisis", __name__)

CHANNELS = ["PHONE", "EMAIL", "SMS"]
SEVERITIES = ["SEV1", "SEV2", "SEV3"]
CRITERIA = ["CRITERION_A", "CRITERION_B", "CRITERION_C"]
ATTESTATION_TYPES = ["REGULATORY", "CUSTOMER"]
LIVE_ACTIVATION_STATES = ("ACTIVE", "ALL_NOTIFIED", "ACKNOWLEDGED")


def get_node_or_404(node_id):
    n = DB.nodes.get(node_id)
    if n is None:
        not_found("ERR_NODE_NOT_FOUND", "Comm node")
    return n


def get_activation_or_404(activation_id):
    a = DB.activations.get(activation_id)
    if a is None:
        not_found("ERR_ACTIVATION_NOT_FOUND", "Activation")
    return a


def get_notification_or_404(notification_id):
    n = DB.notifications.get(notification_id)
    if n is None:
        not_found("ERR_NOTIFICATION_NOT_FOUND", "Notification")
    return n


def get_attestation_or_404(attestation_id):
    a = DB.attestations.get(attestation_id)
    if a is None:
        not_found("ERR_ATTESTATION_NOT_FOUND", "Attestation")
    return a


# --------------------------------------------------------------------------
# Comm nodes (PRD §3.8)
# --------------------------------------------------------------------------

def _sibling_unique(tree_label, parent_id, order_index, exclude_id=None):
    for n in DB.nodes.values():
        if (n["tree_label"] == tree_label
                and n.get("parent_node_id") == parent_id
                and n["order_index"] == order_index
                and n["id"] != exclude_id):
            fail("ERR_DUPLICATE", 409,
                 "A sibling node with this order_index already exists")


def _root_check(tree_label, exclude_id=None):
    for n in DB.nodes.values():
        if (n["tree_label"] == tree_label and n.get("parent_node_id") is None
                and n["id"] != exclude_id):
            fail("ERR_TREE_ROOT_EXISTS", 409,
                 "A root node already exists for this tree_label")


def _cycle_check(node_id, new_parent_id):
    """Re-parenting must not make the node its own ancestor."""
    cur = new_parent_id
    seen = set()
    while cur is not None:
        if cur == node_id:
            fail("ERR_COMM_TREE_CYCLE", 422,
                 "Re-parenting would make the node its own ancestor")
        if cur in seen:
            break
        seen.add(cur)
        parent = DB.nodes.get(cur)
        cur = parent.get("parent_node_id") if parent else None


@bp.post("/resilience/comm-nodes")
def create_node():
    actor(["CrisisOfficer"])
    payload = body()
    tree_label = as_str(req(payload, "tree_label"), "tree_label")
    contact_name = as_str(req(payload, "contact_name"), "contact_name")
    role_title = as_str(req(payload, "role_title"), "role_title")
    parent_id = payload.get("parent_node_id")
    order_index = as_int(req(payload, "order_index"), "order_index")
    channel = as_enum(req(payload, "channel"), "channel", CHANNELS)
    ack_deadline = as_int(req(payload, "ack_deadline_minutes"),
                          "ack_deadline_minutes", minv=0)
    active_flag = True
    if "active_flag" in payload and payload["active_flag"] is not None:
        active_flag = as_bool(payload["active_flag"], "active_flag")
    if parent_id is not None:
        parent = DB.nodes.get(parent_id)
        if parent is None:
            not_found("ERR_NODE_NOT_FOUND", "Comm node")
        if parent["tree_label"] != tree_label:
            validation("parent_node_id must reference a node in the same tree")
    if parent_id is None:
        _root_check(tree_label)
    _sibling_unique(tree_label, parent_id, order_index)
    n = {"tree_label": tree_label, "contact_name": contact_name,
         "role_title": role_title, "parent_node_id": parent_id,
         "order_index": order_index, "channel": channel,
         "ack_deadline_minutes": ack_deadline, "active_flag": active_flag}
    stamp_new(n)
    DB.nodes[n["id"]] = n
    return ok(node_view(n), status=201)


@bp.get("/resilience/comm-nodes")
def list_nodes():
    actor(ALL_ROLES)
    items = apply_filters(list(DB.nodes.values()), [
        ("tree_label", "tree_label"),
        ("parent_node_id", "parent_node_id"),
        ("active_flag", "active_flag"),
    ])
    page, meta = paginate(sorted_by_created(items))
    return ok([node_view(n) for n in page], response_type="array",
              pagination=meta)


@bp.get("/resilience/comm-nodes/<nodeId>")
def get_node(nodeId):
    actor(ALL_ROLES)
    return ok(node_view(get_node_or_404(nodeId)))


@bp.put("/resilience/comm-nodes/<nodeId>")
def update_node(nodeId):
    actor(["CrisisOfficer"])
    n = get_node_or_404(nodeId)
    payload = body()
    updates = {}
    for key in ("contact_name", "role_title"):
        if key in payload and payload[key] is not None:
            updates[key] = as_str(payload[key], key)
    if "order_index" in payload and payload["order_index"] is not None:
        updates["order_index"] = as_int(payload["order_index"], "order_index")
    if "channel" in payload and payload["channel"] is not None:
        updates["channel"] = as_enum(payload["channel"], "channel", CHANNELS)
    if "ack_deadline_minutes" in payload \
            and payload["ack_deadline_minutes"] is not None:
        updates["ack_deadline_minutes"] = as_int(
            payload["ack_deadline_minutes"], "ack_deadline_minutes", minv=0)
    parent_changed = "parent_node_id" in payload \
        and payload["parent_node_id"] != n.get("parent_node_id")
    new_parent = n.get("parent_node_id")
    if parent_changed:
        new_parent = payload["parent_node_id"]
        if new_parent is not None:
            parent = DB.nodes.get(new_parent)
            if parent is None:
                not_found("ERR_NODE_NOT_FOUND", "Comm node")
            if parent["tree_label"] != n["tree_label"]:
                validation("parent_node_id must reference a node in the same "
                           "tree")
    new_active = n["active_flag"]
    if "active_flag" in payload and payload["active_flag"] is not None:
        new_active = as_bool(payload["active_flag"], "active_flag")
    # Structural checks (PRD §2.10 layer 9): duplicate -> root -> children ->
    # cycle.
    new_order = updates.get("order_index", n["order_index"])
    if parent_changed or new_order != n["order_index"]:
        _sibling_unique(n["tree_label"], new_parent, new_order,
                        exclude_id=n["id"])
    if parent_changed and new_parent is None:
        _root_check(n["tree_label"], exclude_id=n["id"])
    if n["active_flag"] and not new_active:
        for child in DB.nodes.values():
            if child.get("parent_node_id") == n["id"] and child["active_flag"]:
                fail("ERR_NODE_HAS_ACTIVE_CHILDREN", 409,
                     "A node may be deactivated only when all children are "
                     "inactive")
    if parent_changed and new_parent is not None:
        _cycle_check(n["id"], new_parent)
    for key, value in updates.items():
        n[key] = value
    if parent_changed:
        n["parent_node_id"] = new_parent
    n["active_flag"] = new_active
    bump(n)
    return ok(node_view(n))


# --------------------------------------------------------------------------
# Activations (PRD §3.8)
# --------------------------------------------------------------------------

@bp.post("/resilience/activations")
def create_activation():
    actor(["CrisisOfficer"])
    payload = body()
    process_id = req(payload, "process_id")
    process = DB.processes.get(process_id)
    if process is None:
        not_found("ERR_PROCESS_NOT_FOUND", "Process")
    severity = as_enum(req(payload, "declared_severity"), "declared_severity",
                       SEVERITIES)
    criterion = as_enum(req(payload, "activation_criterion"),
                        "activation_criterion", CRITERIA)
    justification = as_str(req(payload, "criterion_justification"),
                           "criterion_justification")
    if process["status"] != "ACTIVE":
        fail("ERR_PROCESS_NOT_ACTIVE", 409,
             "The referenced process must be ACTIVE")
    plan = approved_plan(process_id)
    if plan is None:
        fail("ERR_NO_APPROVED_PLAN", 422,
             "The process has no APPROVED plan")
    if any(a["process_id"] == process_id
           and a["status"] in LIVE_ACTIVATION_STATES
           for a in DB.activations.values()):
        fail("ERR_ACTIVATION_ALREADY_ACTIVE", 409,
             "A live activation already exists for the process")
    if criterion not in SEV_CRITERIA[severity]:
        fail("ERR_CRITERION_NOT_ALLOWED", 422,
             "The declared severity does not permit the requested criterion")
    a = {"process_id": process_id, "plan_id": plan["id"],
         "declared_severity": severity, "activation_criterion": criterion,
         "criterion_justification": justification,
         "expected_notifications": 0, "notified_count": 0, "acked_count": 0,
         "escalation_level": 0, "acknowledged_at": None,
         "deactivated_by_contact_id": None, "status": "ACTIVE"}
    stamp_new(a)
    DB.activations[a["id"]] = a

    # Fan-out: one SENT notification per active node, in tree order.
    tree_label = "TREE_" + process["name"]
    nodes = tree_nodes_in_order(tree_label)
    a["expected_notifications"] = len(nodes)
    for node in nodes:
        notification = {
            "id": new_id(),
            "activation_id": a["id"],
            "comm_node_id": node["id"],
            "channel": node["channel"],
            "status": "SENT",
            "sent_at": now_dt(),
            "acked_at": None,
            "ack_token": uuid.uuid4().hex,
        }
        notification["created_at"] = tick_dt()
        notification["_seq"] = next_seq()
        DB.notifications[notification["id"]] = notification
    a["notified_count"] = len(nodes)
    # Auto-advance ACTIVE -> ALL_NOTIFIED once fan-out completes.
    a["status"] = "ALL_NOTIFIED"
    bump(a)
    # Empty-tree guard: zero expected means zero acks already suffice.
    if a["expected_notifications"] == 0:
        a["status"] = "ACKNOWLEDGED"
        a["acknowledged_at"] = now_dt()
        bump(a)
    return ok(activation_view(a), status=201)


@bp.get("/resilience/activations")
def list_activations():
    actor(ALL_ROLES)
    items = apply_filters(list(DB.activations.values()), [
        ("process_id", "process_id"),
        ("status", "status"),
        ("declared_severity", "declared_severity"),
        ("plan_id", "plan_id"),
        ("deactivated_by_contact_id", "deactivated_by_contact_id"),
    ])
    page, meta = paginate(sorted_by_created(items))
    return ok([activation_view(a) for a in page], response_type="array",
              pagination=meta)


@bp.get("/resilience/activations/<activationId>")
def get_activation(activationId):
    actor(ALL_ROLES)
    return ok(activation_view(get_activation_or_404(activationId)))


@bp.post("/resilience/activations/<activationId>/deactivate")
def deactivate_activation(activationId):
    who = actor(["CrisisOfficer"])
    a = get_activation_or_404(activationId)
    if a["status"] not in LIVE_ACTIVATION_STATES:
        fail("ERR_INVALID_STATE", 409,
             "Activation must be ACTIVE, ALL_NOTIFIED, or ACKNOWLEDGED")
    a["status"] = "DEACTIVATED"
    a["deactivated_by_contact_id"] = who["id"]
    bump(a)
    return ok(activation_view(a))


@bp.get("/resilience/activations/<activationId>/notifications")
def activation_notifications(activationId):
    actor(ALL_ROLES)
    get_activation_or_404(activationId)
    items = [n for n in DB.notifications.values()
             if n["activation_id"] == activationId]
    page, meta = paginate(sorted_by_created(items))
    return ok([notification_view(n) for n in page], response_type="array",
              pagination=meta)


# --------------------------------------------------------------------------
# Notifications
# --------------------------------------------------------------------------

@bp.get("/resilience/notifications")
def list_notifications():
    actor(ALL_ROLES)
    items = apply_filters(list(DB.notifications.values()), [
        ("activation_id", "activation_id"),
        ("comm_node_id", "comm_node_id"),
        ("status", "status"),
    ])
    page, meta = paginate(sorted_by_created(items))
    return ok([notification_view(n) for n in page], response_type="array",
              pagination=meta)


@bp.get("/resilience/notifications/<notificationId>")
def get_notification(notificationId):
    actor(ALL_ROLES)
    return ok(notification_view(get_notification_or_404(notificationId)))


@bp.post("/resilience/notifications/<notificationId>/ack")
def ack_notification(notificationId):
    actor(["CrisisOfficer"])
    n = get_notification_or_404(notificationId)
    payload = body()
    token = as_str(req(payload, "ack_token"), "ack_token")
    activation = DB.activations.get(n["activation_id"])
    if token != n["ack_token"]:
        fail("ERR_ACK_TOKEN_MISMATCH", 403,
             "ack_token does not match the notification's token")
    if n["status"] != "SENT":
        fail("ERR_NOTIFICATION_ALREADY_ACKED", 409,
             "The notification is already acknowledged")
    if activation is not None and activation["status"] not in (
            "ACTIVE", "ALL_NOTIFIED"):
        fail("ERR_INVALID_STATE", 409,
             "The owning activation is no longer accepting acknowledgements")
    n["status"] = "ACKED"
    n["acked_at"] = now_dt()
    if activation is not None:
        activation["acked_count"] += 1
        if (activation["status"] == "ALL_NOTIFIED"
                and activation["acked_count"]
                >= activation["expected_notifications"]):
            activation["status"] = "ACKNOWLEDGED"
            activation["acknowledged_at"] = now_dt()
            bump(activation)
    return ok(notification_view(n))


# --------------------------------------------------------------------------
# Attestations (PRD §3.9)
# --------------------------------------------------------------------------

@bp.post("/resilience/attestations")
def create_attestation():
    actor(["AttestationSigner"])
    payload = body()
    process_id = req(payload, "process_id")
    if process_id not in DB.processes:
        not_found("ERR_PROCESS_NOT_FOUND", "Process")
    a_type = as_enum(req(payload, "attestation_type"), "attestation_type",
                     ATTESTATION_TYPES)
    period_start = as_dt(req(payload, "period_start"), "period_start")
    period_end = as_dt(req(payload, "period_end"), "period_end")
    if period_end <= period_start:
        validation("period_end must be strictly after period_start")
    declaration = None
    if "signer_declaration" in payload \
            and payload["signer_declaration"] is not None:
        declaration = as_bool(payload["signer_declaration"],
                              "signer_declaration")
    score, _ = attestation_readiness(process_id)
    a = {"process_id": process_id, "attestation_type": a_type,
         "period_start": period_start, "period_end": period_end,
         "readiness_score": score, "snapshot_payload": None,
         "signed_by_contact_id": None, "signer_declaration": declaration,
         "revoked_reason": None, "status": "DRAFT"}
    stamp_new(a)
    DB.attestations[a["id"]] = a
    return ok(attestation_view(a), status=201)


@bp.get("/resilience/attestations")
def list_attestations():
    actor(ALL_ROLES)
    items = apply_filters(list(DB.attestations.values()), [
        ("process_id", "process_id"),
        ("attestation_type", "attestation_type"),
        ("status", "status"),
        ("signed_by_contact_id", "signed_by_contact_id"),
    ])
    page, meta = paginate(sorted_by_created(items))
    return ok([attestation_view(a) for a in page], response_type="array",
              pagination=meta)


@bp.get("/resilience/attestations/<attestationId>")
def get_attestation(attestationId):
    actor(ALL_ROLES)
    return ok(attestation_view(get_attestation_or_404(attestationId)))


@bp.post("/resilience/attestations/<attestationId>/sign")
def sign_attestation(attestationId):
    who = actor(["AttestationSigner"])
    a = get_attestation_or_404(attestationId)
    payload = body()
    declaration = req(payload, "signer_declaration")
    if declaration is not True:
        fail("ERR_INVALID_REQUEST", 400,
             "signer_declaration must be true at signing")
    if a["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", 409,
             "An attestation may be signed only from DRAFT")
    score, inputs = attestation_readiness(a["process_id"])
    if score < SIGN_THRESHOLD:
        fail("ERR_READINESS_BELOW_THRESHOLD", 422,
             "attestation_readiness is below the signing threshold of 70")
    a["signer_declaration"] = True
    a["signed_by_contact_id"] = who["id"]
    a["readiness_score"] = score
    a["snapshot_payload"] = attestation_snapshot(a, score, inputs)
    a["status"] = "SIGNED"
    bump(a)
    return ok(attestation_view(a))


@bp.post("/resilience/attestations/<attestationId>/revoke")
def revoke_attestation(attestationId):
    who = actor(["RiskCommittee"], sod_identity=True)
    a = get_attestation_or_404(attestationId)
    payload = body()
    reason = opt_str(payload, "revoked_reason")
    if a["status"] != "SIGNED":
        fail("ERR_INVALID_STATE", 409,
             "An attestation may be revoked only from SIGNED")
    if a.get("signed_by_contact_id") is not None \
            and a["signed_by_contact_id"] == who["id"]:
        fail("ERR_SOD_VIOLATION", 403,
             "The revoking contact must differ from the signer")
    a["revoked_reason"] = reason
    a["status"] = "REVOKED"
    bump(a)
    return ok(attestation_view(a))
