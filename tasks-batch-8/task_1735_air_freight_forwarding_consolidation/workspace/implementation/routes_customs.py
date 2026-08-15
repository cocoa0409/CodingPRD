"""Customs entries: creation and the broker handoff protocol (PRD §3.7)."""
from flask import Blueprint

import services as svc
from db import store
from errors import ApiError, ERR_FORBIDDEN_ROLE, ERR_HWB_NOT_CLEARED, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import get_body, opt_str, req_enum, require_roles
from response import ok

bp = Blueprint("customs_entries", __name__)

ENTRY_TYPES = ("INFORMAL", "CONSUMPTION", "TRANSIT")
TARGET_STATUSES = ("HANDED_OFF", "FILED", "RELEASED", "REJECTED", "PREPARING")
# Per-target role map (PRD §2.1): handoff/rework are ForwarderOps actions;
# filing and the authority decision belong to the licensed broker.
ROLE_FOR_TARGET = {
    "HANDED_OFF": "ForwarderOps",
    "PREPARING": "ForwarderOps",
    "FILED": "CustomsBroker",
    "RELEASED": "CustomsBroker",
    "REJECTED": "CustomsBroker",
}
FROM_STATE = {
    "HANDED_OFF": "PREPARING",
    "FILED": "HANDED_OFF",
    "RELEASED": "FILED",
    "REJECTED": "FILED",
    "PREPARING": "REJECTED",
}
# Handoff additionally requires the waybill to be past screening (§3.7).
HANDOFF_HWB_STATES = ("CLEARED", "CONSOLIDATED", "TENDERED", "IN_TRANSIT", "DELIVERED")


@bp.post("/house-waybills/<hid>/customs-entries")
@require_roles("ForwarderOps")
def create_customs_entry(hid):
    h = svc.get_hwb(hid)
    if h.status == "CANCELLED":
        raise ApiError(
            ERR_INVALID_STATE,
            "A customs entry cannot be opened on a CANCELLED waybill.",
            409,
        )
    body = get_body()
    entry_type = req_enum(body, "entry_type", ENTRY_TYPES)
    broker_reference = opt_str(body, "broker_reference", None)
    c = svc.fresh_rec(
        hwb_id=h.id,
        entry_type=entry_type,
        broker_reference=broker_reference,
        rejection_reason=None,
        status="PREPARING",
    )
    store.customs_entries[c.id] = c
    return ok(svc.customs_entry_json(c), 201)


@bp.post("/customs-entries/<cid>/transition")
@require_roles("ForwarderOps", "CustomsBroker")
def transition_customs_entry(cid):
    from flask import g

    # Peek at target_status to apply the per-target role map (priority 2).
    body = get_body()
    target = body.get("target_status")
    if isinstance(target, str) and target in ROLE_FOR_TARGET:
        required_role = ROLE_FOR_TARGET[target]
        if g.role != required_role:
            raise ApiError(
                ERR_FORBIDDEN_ROLE,
                f"Target status {target} requires role {required_role}.",
                403,
            )
    # Existence (priority 3).
    entry = svc.get_customs_entry(cid)
    # Request shape: target_status must be a declared target.
    target_status = req_enum(body, "target_status", TARGET_STATUSES)
    # State gate (priority 5).
    if entry.status != FROM_STATE[target_status]:
        raise ApiError(
            ERR_INVALID_STATE,
            f"Customs entry status is {entry.status}; transition to {target_status} requires {FROM_STATE[target_status]}.",
            409,
        )
    if target_status == "HANDED_OFF":
        hwb = svc.get_hwb(entry.hwb_id)
        if hwb.status not in HANDOFF_HWB_STATES:
            raise ApiError(
                ERR_HWB_NOT_CLEARED,
                f"House waybill status is {hwb.status}; handoff requires the waybill past screening.",
                409,
            )
    if target_status == "REJECTED":
        reason = opt_str(body, "rejection_reason", None)
        if reason is None or reason == "":
            raise ApiError(
                ERR_INVALID_REQUEST,
                "Field 'rejection_reason' is required when target_status is REJECTED.",
                400,
            )
        entry.rejection_reason = reason
    broker_reference = opt_str(body, "broker_reference", None)
    if target_status == "FILED" and broker_reference is not None:
        entry.broker_reference = broker_reference
    entry.status = target_status
    svc.touch(entry)
    return ok(svc.customs_entry_json(entry), 200)
