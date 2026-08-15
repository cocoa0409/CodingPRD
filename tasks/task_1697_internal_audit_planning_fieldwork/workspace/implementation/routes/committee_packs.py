"""CommitteePack endpoints (PRD 3.9): board-facing reporting with finalize-time
snapshot pinning (never recomputed afterwards)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_PACK_INVALID_STATE,
    ERR_PLAN_NOT_APPROVED,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, query_str
from services.calculations import compute_pack_snapshot
from services.core import new_record, public, touch
from util import CLOCK
from validate import (
    body_ref,
    check_unknown_fields,
    get_body,
    req_datetime,
    req_str,
    require_path,
)

bp = Blueprint("committee_packs", __name__)

CREATE_FIELDS = {"audit_plan_id", "meeting_date", "title"}


@bp.post("/audit/committee-packs")
def create_pack():
    authorized(["ChiefAuditExecutive"])
    body = get_body()
    # Stage 4: body FK existence
    body_ref(body, "audit_plan_id", "audit_plans")
    # Stage 5: shape
    check_unknown_fields(body, CREATE_FIELDS)
    audit_plan_id = req_str(body, "audit_plan_id")
    meeting_date = req_datetime(body, "meeting_date")
    title = req_str(body, "title")
    plan = db["audit_plans"][audit_plan_id]
    # Stage 11: the plan must be APPROVED or CLOSED
    if plan["status"] not in ("APPROVED", "CLOSED"):
        raise_error(ERR_PLAN_NOT_APPROVED,
                    f"committee packs require an APPROVED or CLOSED plan, not {plan['status']}")
    rec = new_record("committee_packs", {
        "audit_plan_id": audit_plan_id,
        "meeting_date": meeting_date,
        "title": title,
        "status": "DRAFT",
        "snapshot_plan_completion_pct": None,
        "snapshot_overdue_action_count": None,
        "snapshot_critical_findings": None,
        "snapshot_high_findings": None,
        "is_stale_snapshot": False,
        "finalized_at": None,
        "presented_at": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/audit/committee-packs")
def list_packs():
    filters = {
        "audit_plan_id": query_str("audit_plan_id"),
        "status": query_str("status"),
    }
    return list_response("committee_packs", filters)


@bp.get("/audit/committee-packs/<rid>")
def get_pack(rid):
    return get_one("committee_packs", rid)


@bp.post("/audit/committee-packs/<rid>/finalize")
def finalize_pack(rid):
    authorized(["ChiefAuditExecutive"])
    pack = require_path("committee_packs", rid)
    if pack["status"] != "DRAFT":
        raise_error(ERR_PACK_INVALID_STATE, "pack is not DRAFT")
    # Compute and permanently pin the snapshot aggregates (calculation 9)
    snapshot = compute_pack_snapshot(pack)
    pack.update(snapshot)
    pack["status"] = "FINALIZED"
    pack["finalized_at"] = CLOCK.now_iso()
    touch(pack)
    return success_object(public(pack))


@bp.post("/audit/committee-packs/<rid>/present")
def present_pack(rid):
    authorized(["AuditCommittee"])
    pack = require_path("committee_packs", rid)
    if pack["status"] != "FINALIZED":
        raise_error(ERR_PACK_INVALID_STATE, "pack is not FINALIZED")
    pack["status"] = "PRESENTED"
    pack["presented_at"] = CLOCK.now_iso()
    touch(pack)
    return success_object(public(pack))
