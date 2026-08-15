"""Warranty claim routes."""
from flask import Blueprint, request

from errors import err
from httpkit import (require_roles, body, req_enum, req_int, opt_int, opt_str,
                     paginate, sort_default, success)
from store import db, init_common, mark_dirty
from services import domain as dom
from services import serializers as ser
from routes.buses import ALL
from routes.workorders import get_wo_or_404

bp = Blueprint("claims", __name__)


def get_claim_or_404(claim_id):
    c = db["claims"].get(claim_id)
    if c is None:
        raise err("ERR_NOT_FOUND", f"WarrantyClaim {claim_id} not found")
    return c


@bp.post("/fleet/warranty-claims")
def create_claim():
    require_roles("WarrantyClerk")
    data = body()
    wo_id = data.get("work_order_id")
    wo = None
    if wo_id is not None:
        wo = db["work_orders"].get(wo_id)
        if wo is None:
            raise err("ERR_NOT_FOUND", f"WorkOrder {wo_id} not found")
    if wo_id is None:
        raise err("ERR_VALIDATION", "Missing required field: work_order_id")
    claim_type = req_enum(data, "claim_type", dom.CLAIM_TYPES)
    proration = data.get("proration_basis")
    if proration is not None and proration not in ("MILES", "TIME"):
        raise err("ERR_VALIDATION", "proration_basis must be MILES or TIME")
    manual = opt_int(data, "manual_claimed_cents")
    if claim_type == "EXTENDED" and proration is None:
        raise err("ERR_VALIDATION",
                  "proration_basis is required for EXTENDED claims")
    if claim_type == "GOODWILL" and manual is None:
        raise err("ERR_VALIDATION",
                  "manual_claimed_cents is required for GOODWILL claims")
    expected_wo_version = req_int(data, "expected_work_order_version")
    # state: work order must be CLOSED
    if wo["status"] != "CLOSED":
        raise err("ERR_INVALID_STATE",
                  "Warranty claims require a CLOSED work order")
    # OCC (priority 9)
    if expected_wo_version != wo["version"]:
        raise err("ERR_STALE_WORK_ORDER_VERSION",
                  "expected_work_order_version does not match current "
                  "WorkOrder.version")
    # eligibility gates (priority 44)
    bus = db["buses"][wo["bus_id"]]
    if claim_type == "BASE_OEM":
        if not dom.base_warranty_ok(bus, wo):
            raise err("ERR_WARRANTY_NOT_ELIGIBLE",
                      "Work order is outside the base warranty at open")
    elif claim_type == "EXTENDED":
        if not dom.extended_warranty_ok(bus, wo):
            raise err("ERR_WARRANTY_NOT_ELIGIBLE",
                      "Work order is not within extended warranty limits")
    elif claim_type == "PARTS_ONLY":
        has_eligible = False
        for line in dom.wo_lines(wo["id"]):
            part = db["parts"].get(line["part_id"])
            if part is not None and part.get("warranty_eligible"):
                has_eligible = True
                break
        if not has_eligible:
            raise err("ERR_WARRANTY_NOT_ELIGIBLE",
                      "No warranty-eligible part line on the work order")

    claim = init_common({
        "work_order_id": wo["id"],
        "bus_id": wo["bus_id"],
        "claim_type": claim_type,
        "proration_basis": proration,
        "manual_claimed_cents": manual,
        "status": "DRAFT",
        "eligible_cents": None,
        "claimed_cents": None,
        "approved_cents": None,
        "received_cents": None,
        "appeal_count": 0,
        "oem_reference": None,
        "auto_created": False,
        "submitted_by_user_id": None,
        "recovered_by_user_id": None,
    })
    db["claims"][claim["id"]] = claim
    mark_dirty("work_orders", wo["id"])  # +1 per PRD
    return success(ser.claim(claim), code=201)


@bp.get("/fleet/warranty-claims/<cid>")
def get_claim(cid):
    require_roles(*ALL)
    return success(ser.claim(get_claim_or_404(cid)))


@bp.get("/fleet/warranty-claims")
def list_claims():
    require_roles(*ALL)
    items = list(db["claims"].values())
    for param in ("work_order_id", "bus_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [c for c in items if c.get(param) == val]
    items = sort_default(items)
    page, meta_p = paginate(items)
    return success([ser.claim(c) for c in page], response_type="array",
                   pagination=meta_p)


_CLAIM_EVENT_ROLES = {
    "SUBMIT": ("WarrantyClerk",),
    "RECORD_OEM_DECISION": ("WarrantyClerk",),
    "APPEAL": ("WarrantyClerk",),
    "POST_RECOVERY": ("FleetManager",),
    "WITHDRAW": ("WarrantyClerk",),
}

_CLAIM_FROM = {
    "SUBMIT": {"DRAFT"},
    "RECORD_OEM_DECISION": {"SUBMITTED"},
    "APPEAL": {"DENIED"},
    "POST_RECOVERY": {"APPROVED", "PARTIALLY_APPROVED"},
    "WITHDRAW": {"DRAFT", "SUBMITTED", "DENIED"},
}


@bp.post("/fleet/warranty-claims/<cid>/events")
def claim_event(cid):
    uid, role = require_roles("WarrantyClerk", "FleetManager")
    claim = get_claim_or_404(cid)
    data = body()
    event_type = req_enum(data, "event_type", set(_CLAIM_EVENT_ROLES))
    if role not in _CLAIM_EVENT_ROLES[event_type]:
        raise err("ERR_FORBIDDEN", f"Role {role} may not perform {event_type}")
    if claim["status"] in dom.CLAIM_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL",
                  f"Warranty claim is {claim['status']}; transitions forbidden")
    if claim["status"] not in _CLAIM_FROM[event_type]:
        raise err("ERR_INVALID_STATE",
                  f"Cannot {event_type} a claim in {claim['status']}")
    handler = {
        "SUBMIT": _ev_submit,
        "RECORD_OEM_DECISION": _ev_record_decision,
        "APPEAL": _ev_appeal,
        "POST_RECOVERY": _ev_post_recovery,
        "WITHDRAW": _ev_withdraw,
    }[event_type]
    handler(claim, data, uid)
    return success(ser.claim(claim))


def _ev_submit(claim, data, uid):
    wo = db["work_orders"][claim["work_order_id"]]
    if wo["status"] != "CLOSED":
        raise err("ERR_INVALID_STATE",
                  "The underlying work order is no longer CLOSED")
    eligible, claimed = dom.compute_claim_amounts(claim)
    claim["eligible_cents"] = eligible
    claim["claimed_cents"] = claimed
    claim["submitted_by_user_id"] = uid
    claim["status"] = "SUBMITTED"
    mark_dirty("claims", claim["id"])


def _ev_record_decision(claim, data, uid):
    outcome = req_enum(data, "decision_outcome",
                       {"APPROVED", "PARTIAL", "DENIED"})
    oem_reference = opt_str(data, "oem_reference")
    if outcome == "APPROVED":
        claim["approved_cents"] = claim["claimed_cents"]
        claim["status"] = "APPROVED"
    elif outcome == "PARTIAL":
        approved = opt_int(data, "approved_cents")
        if approved is None:
            raise err("ERR_VALIDATION",
                      "approved_cents is required for a PARTIAL decision")
        if not (approved < claim["claimed_cents"]):
            raise err("ERR_VALIDATION",
                      "PARTIAL approved_cents must be less than claimed_cents")
        claim["approved_cents"] = approved
        claim["status"] = "PARTIALLY_APPROVED"
    else:  # DENIED
        claim["approved_cents"] = 0
        claim["status"] = "DENIED"
    if oem_reference is not None:
        claim["oem_reference"] = oem_reference
    mark_dirty("claims", claim["id"])


def _ev_appeal(claim, data, uid):
    if claim.get("appeal_count", 0) >= 2:
        raise err("ERR_APPEAL_LIMIT_EXCEEDED",
                  "A claim may be appealed at most twice")
    claim["appeal_count"] = claim.get("appeal_count", 0) + 1
    if claim["claim_type"] == "GOODWILL":
        manual = opt_int(data, "manual_claimed_cents")
        if manual is not None:
            claim["manual_claimed_cents"] = manual
            claim["claimed_cents"] = manual
            claim["eligible_cents"] = manual
    claim["status"] = "SUBMITTED"
    mark_dirty("claims", claim["id"])


def _ev_post_recovery(claim, data, uid):
    # SoD (priority 13) before fiscal (priority 45)
    if uid == claim.get("submitted_by_user_id"):
        raise err("ERR_SOD_RECOVERY_SELF_APPROVAL",
                  "The submitting clerk may not post the recovery")
    received = req_int(data, "received_cents")
    if received > claim.get("approved_cents", 0):
        raise err("ERR_RECOVERY_EXCEEDS_APPROVED",
                  "received_cents exceeds approved_cents")
    claim["received_cents"] = received
    claim["recovered_by_user_id"] = uid
    claim["status"] = "RECOVERED"
    mark_dirty("claims", claim["id"])


def _ev_withdraw(claim, data, uid):
    claim["status"] = "WITHDRAWN"
    mark_dirty("claims", claim["id"])
