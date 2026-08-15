"""Discrepancies: owner decisions (OCC), rectification, independent
verification with segregation of duties (PRD 3.5, 3.6)."""

from flask import Blueprint, g

import db
import envelope
import ops
from errors import ApiError
from middleware import require_roles
from validate import (
    apply_filters,
    body,
    get_row,
    paginate,
    req_enum,
    req_str,
    req_version,
)

bp = Blueprint("discrepancies", __name__)


def _disc(rid):
    return get_row(db.DISCREPANCIES, rid)


def _disc_out(disc):
    return envelope.ok(ops.pub(disc, ops.DISCREPANCY_F))


def _aircraft_for(disc):
    wo = db.WORK_ORDERS.get(disc["work_order_id"])
    return db.AIRCRAFT.get(wo["aircraft_id"]) if wo else None


@bp.get("/api/discrepancies/<rid>")
@require_roles("ShopManager", "Mechanic", "Owner")
def get_discrepancy(rid):
    return _disc_out(_disc(rid))


@bp.get("/api/discrepancies")
@require_roles("ShopManager", "Mechanic", "Owner")
def list_discrepancies():
    rows = apply_filters(
        list(db.DISCREPANCIES.values()),
        {
            "work_order_id": "work_order_id",
            "status": "status",
            "checklist_item_id": "checklist_item_id",
            "decided_by_owner_id": "decided_by_owner_id",
        },
    )
    return paginate(rows, ops.DISCREPANCY_F)


@bp.post("/api/discrepancies/<rid>/decide")
@require_roles("Owner")
def decide_discrepancy(rid):
    disc = _disc(rid)
    b = body()
    decision = req_enum(b, "decision", ("APPROVE", "REJECT", "DEFER"))
    expected_version = req_version(b, "expected_discrepancy_version")
    # OCC (PRD 2.6): the client's observed discrepancy version must match.
    if expected_version != disc["version"]:
        raise ApiError("ERR_STALE_VERSION")
    if disc["status"] != "PENDING_OWNER_DECISION":
        raise ApiError("ERR_INVALID_STATE", "Discrepancy is not awaiting owner decision.")
    wo = get_row(db.WORK_ORDERS, disc["work_order_id"])
    aircraft = get_row(db.AIRCRAFT, wo["aircraft_id"])
    if aircraft["owner_id"] != g.user_id:
        raise ApiError(
            "ERR_OWNER_DECISION_REQUIRED",
            "Only the aircraft's registered owner may decide.",
        )
    if decision in ("REJECT", "DEFER") and disc["severity"] != "NON_AIRWORTHINESS":
        raise ApiError(
            "ERR_AIRWORTHINESS_BLOCKED",
            "An airworthiness finding may never be rejected or deferred.",
        )
    disc["decided_by_owner_id"] = g.user_id
    disc["status"] = {
        "APPROVE": "APPROVED",
        "REJECT": "REJECTED",
        "DEFER": "DEFERRED",
    }[decision]
    db.touch(disc)
    ops.recompute_wo_counts(wo)
    ops.maybe_auto_advance(wo)
    ops.recompute_posture(aircraft)
    return _disc_out(disc)


@bp.post("/api/discrepancies/<rid>/rectify")
@require_roles("Mechanic")
def rectify_discrepancy(rid):
    disc = _disc(rid)
    if disc["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED discrepancy can be rectified.")
    parts = ops.discrepancy_parts(disc["id"])
    installed = [p for p in parts if p["status"] == "INSTALLED"]
    blocking = [p for p in parts if p["status"] not in ("INSTALLED", "RETURNED")]
    if blocking:
        raise ApiError(
            "ERR_INVALID_STATE",
            "Every non-returned part linked to the discrepancy must be INSTALLED.",
        )
    if parts and not installed:
        raise ApiError(
            "ERR_INVALID_STATE",
            "At least one installed part is required when parts were requested.",
        )
    if ops.invoice_locked(disc["work_order_id"]):
        raise ApiError("ERR_INVOICE_LOCKED")
    disc["status"] = "RECTIFIED"
    disc["_rectified_by"] = g.user_id
    db.touch(disc)
    wo = db.WORK_ORDERS.get(disc["work_order_id"])
    if wo is not None:
        ops.recompute_wo_counts(wo)
    aircraft = _aircraft_for(disc)
    if aircraft is not None:
        ops.recompute_posture(aircraft)
    return _disc_out(disc)


@bp.post("/api/discrepancies/<rid>/verify")
@require_roles("Mechanic")
def verify_discrepancy(rid):
    disc = _disc(rid)
    b = body()
    outcome = req_enum(b, "outcome", ("PASS", "FAIL"))
    verified_by = req_str(b, "verified_by_mechanic_id")
    mechanic = get_row(db.MECHANICS, verified_by)
    if disc["status"] != "RECTIFIED":
        raise ApiError("ERR_INVALID_STATE", "Only a RECTIFIED discrepancy can be verified.")
    wo = get_row(db.WORK_ORDERS, disc["work_order_id"])
    if outcome == "PASS":
        # Segregation of duties: the verifier must differ from the rectifier;
        # ANNUAL scope additionally requires an IA certificate (PRD 3.6).
        if verified_by == disc.get("_rectified_by"):
            raise ApiError(
                "ERR_AIRWORTHINESS_BLOCKED",
                "The verifying mechanic must differ from the rectifying mechanic.",
            )
        if wo["scope_type"] == "ANNUAL" and mechanic["certificate_class"] != "IA":
            raise ApiError(
                "ERR_AIRWORTHINESS_BLOCKED",
                "Verification on ANNUAL-scope work requires an IA certificate.",
            )
        disc["status"] = "VERIFIED"
    else:
        # Rework cycle: the finding reopens and posture may regress.
        disc["status"] = "OPEN"
    db.touch(disc)
    ops.recompute_wo_counts(wo)
    aircraft = _aircraft_for(disc)
    if aircraft is not None:
        ops.recompute_posture(aircraft)
    return _disc_out(disc)
