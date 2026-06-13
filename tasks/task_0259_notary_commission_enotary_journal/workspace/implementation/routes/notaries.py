"""Notary lifecycle + audit-event read routes (PRD §3.2, §3.9)."""
from flask import Blueprint, request

from clock import to_iso8601_millis
from db import store, new_common_fields, touch
from domain import (
    find_notary, find_jurisdiction, audit, recompute_enotary_authorized,
    terminate_sessions_cascade, extend_expiry, CASCADE_TERMINATE_STATES,
    RISK_SUSPEND_THRESHOLD,
)
from errors import err
from middleware import endpoint
from response import success, list_response
from serialize import view, view_list
from validation import (
    get_body, require_str, optional_str, require_bool, parse_pagination, paginate,
)

bp = Blueprint("notaries", __name__)


@bp.post("/notaries")
@endpoint(("Anonymous",), exempt_auth=True)
def register_notary():
    body = get_body()
    jurisdiction_id = require_str(body, "jurisdiction_id")
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    enotary_requested = require_bool(body, "enotary_requested", default=False)

    # Existence (404) for the referenced jurisdiction (PRD §2.8).
    find_jurisdiction(jurisdiction_id)
    if any(n["email"] == email for n in store.notaries.values()):
        raise err("ERR_VALIDATION", "email must be unique")

    rec = dict(new_common_fields())
    rec.update({
        "jurisdiction_id": jurisdiction_id,
        "full_name": full_name,
        "email": email,
        "enotary_requested": enotary_requested,
        "enotary_authorized": False,
        "status": "APPLIED",
        "bond_id": None,
        "commission_starts_at": None,
        "commission_expires_at": None,
        "risk_score": 0,
        "lifetime_fees_collected_cents": 0,
    })
    store.notaries[rec["id"]] = rec
    return success(view(rec), status=201)


@bp.get("/notaries/<notary_id>")
@endpoint(("CommissionAuthority", "Notary"))
def get_notary(notary_id):
    return success(view(find_notary(notary_id)))


@bp.get("/notaries")
@endpoint(("CommissionAuthority", "Notary"))
def list_notaries():
    limit, offset = parse_pagination()
    recs = list(store.notaries.values())
    jid = request.args.get("jurisdiction_id")
    bid = request.args.get("bond_id")
    status = request.args.get("status")
    if jid is not None:
        recs = [r for r in recs if r["jurisdiction_id"] == jid]
    if bid is not None:
        recs = [r for r in recs if r.get("bond_id") == bid]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, total = paginate(recs, limit, offset)
    return list_response(view_list(page), limit, offset, total)


@bp.post("/notaries/<notary_id>/commission")
@endpoint(("CommissionAuthority",))
def commission_notary(notary_id):
    notary = find_notary(notary_id)
    if notary["status"] != "APPLIED":
        raise err("ERR_INVALID_STATE", "Notary is not APPLIED")
    juris = store.jurisdictions.get(notary["jurisdiction_id"])
    # Require an ACTIVE bond with face_value >= bond_minimum (PRD §3.2).
    qualifying = None
    for b in store.bonds.values():
        if (b["notary_id"] == notary_id and b["status"] == "ACTIVE"
                and b["face_value_cents"] >= juris["bond_minimum_cents"]):
            qualifying = b
            break
    if qualifying is None:
        raise err("ERR_BOND_BELOW_MINIMUM", "No qualifying ACTIVE bond")

    notary["status"] = "COMMISSIONED"
    notary["bond_id"] = qualifying["id"]
    now = store.clock.now()
    notary["commission_starts_at"] = to_iso8601_millis(now)
    extend_expiry(notary, juris, now)
    recompute_enotary_authorized(notary)
    touch(notary)
    audit(notary_id, "NOTARY", notary_id, "NOTARY_COMMISSIONED", "COMMISSION_AUTHORITY",
          "Notary commissioned")
    return success(view(notary))


@bp.post("/notaries/<notary_id>/reject")
@endpoint(("CommissionAuthority",))
def reject_notary(notary_id):
    notary = find_notary(notary_id)
    if notary["status"] != "APPLIED":
        raise err("ERR_INVALID_STATE", "Notary is not APPLIED")
    notary["status"] = "REJECTED"
    touch(notary)
    audit(notary_id, "NOTARY", notary_id, "NOTARY_REJECTED", "COMMISSION_AUTHORITY",
          "Notary rejected")
    return success(view(notary))


@bp.post("/notaries/<notary_id>/activate")
@endpoint(("CommissionAuthority",))
def activate_notary(notary_id):
    notary = find_notary(notary_id)
    if notary["status"] != "COMMISSIONED":
        raise err("ERR_INVALID_STATE", "Notary is not COMMISSIONED")
    bond = store.bonds.get(notary.get("bond_id"))
    if bond is None or bond["status"] != "ACTIVE":
        raise err("ERR_BOND_NOT_ACTIVE", "Bound bond is not ACTIVE")
    notary["status"] = "ACTIVE"
    touch(notary)
    audit(notary_id, "NOTARY", notary_id, "NOTARY_ACTIVATED", "COMMISSION_AUTHORITY",
          "Notary activated")
    return success(view(notary))


@bp.post("/notaries/<notary_id>/suspend")
@endpoint(("CommissionAuthority",))
def suspend_notary(notary_id):
    notary = find_notary(notary_id)
    if notary["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Notary is not ACTIVE")
    notary["status"] = "SUSPENDED"
    notary["enotary_authorized"] = False
    touch(notary)
    terminate_sessions_cascade(notary, CASCADE_TERMINATE_STATES)
    audit(notary_id, "NOTARY", notary_id, "NOTARY_SUSPENDED", "COMMISSION_AUTHORITY",
          "Notary suspended")
    return success(view(notary))


@bp.post("/notaries/<notary_id>/reinstate")
@endpoint(("CommissionAuthority",))
def reinstate_notary(notary_id):
    notary = find_notary(notary_id)
    if notary["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Notary is not SUSPENDED")
    if notary["risk_score"] >= RISK_SUSPEND_THRESHOLD:
        raise err("ERR_RISK_THRESHOLD_BLOCK", "risk_score at or above threshold")
    bond = store.bonds.get(notary.get("bond_id"))
    if bond is None or bond["status"] != "ACTIVE":
        raise err("ERR_BOND_NOT_ACTIVE", "Bound bond is not ACTIVE")
    notary["status"] = "ACTIVE"
    recompute_enotary_authorized(notary)
    touch(notary)
    audit(notary_id, "NOTARY", notary_id, "NOTARY_REINSTATED", "COMMISSION_AUTHORITY",
          "Notary reinstated")
    return success(view(notary))


@bp.post("/notaries/<notary_id>/revoke")
@endpoint(("CommissionAuthority",))
def revoke_notary(notary_id):
    notary = find_notary(notary_id)
    if notary["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Notary is not ACTIVE or SUSPENDED")
    from_active = notary["status"] == "ACTIVE"
    notary["status"] = "REVOKED"
    notary["enotary_authorized"] = False
    touch(notary)
    # Cascade non-terminal sessions only when revoking from ACTIVE (PRD §3.9).
    if from_active:
        terminate_sessions_cascade(notary, CASCADE_TERMINATE_STATES)
    # Bond -> CANCELLED (cross-entity) for the bound bond if present.
    bond = store.bonds.get(notary.get("bond_id"))
    if bond is not None and bond["status"] == "ACTIVE":
        bond["status"] = "CANCELLED"
        touch(bond)
    audit(notary_id, "NOTARY", notary_id, "NOTARY_REVOKED", "COMMISSION_AUTHORITY",
          "Notary revoked")
    return success(view(notary))


# ---- Audit-event read endpoints ----

@bp.get("/notaries/<notary_id>/audit-events")
@endpoint(("CommissionAuthority", "Notary"))
def list_notary_audit_events(notary_id):
    find_notary(notary_id)
    limit, offset = parse_pagination()
    recs = [a for a in store.audit_events.values() if a["notary_id"] == notary_id]
    entity_type = request.args.get("entity_type")
    if entity_type is not None:
        recs = [r for r in recs if r["entity_type"] == entity_type]
    page, total = paginate(recs, limit, offset)
    return list_response(view_list(page), limit, offset, total)


@bp.get("/audit-events/<audit_event_id>")
@endpoint(("CommissionAuthority", "Notary"))
def get_audit_event(audit_event_id):
    rec = store.audit_events.get(audit_event_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Audit event not found")
    return success(view(rec))


@bp.get("/audit-events")
@endpoint(("CommissionAuthority", "Notary"))
def list_audit_events():
    limit, offset = parse_pagination()
    recs = list(store.audit_events.values())
    nid = request.args.get("notary_id")
    entity_type = request.args.get("entity_type")
    if nid is not None:
        recs = [r for r in recs if r["notary_id"] == nid]
    if entity_type is not None:
        recs = [r for r in recs if r["entity_type"] == entity_type]
    page, total = paginate(recs, limit, offset)
    return list_response(view_list(page), limit, offset, total)
