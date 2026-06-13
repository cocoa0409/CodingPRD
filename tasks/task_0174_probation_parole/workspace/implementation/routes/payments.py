"""Payment endpoints (PRD §3.6).

Payment is an immutable posting record (PRD §2.4): it carries only id and
created_at — no updated_at, no version.
"""
from flask import Blueprint, request

import clock
import db
from errors import ApiError, ERR_SUPERVISEE_CLOSED
from middleware import require_roles
from response import object_response, array_response
from serialize import public, public_list
from services import payment as svc
from services.common import (
    TERMINAL_SUPERVISEE_STATES,
    apply_page,
    check_enum,
    get_body,
    get_child_or_404,
    get_supervisee_or_404,
    paginate,
    require_fields,
    require_int_min,
    sorted_by_created,
)
from timeutil import iso_now

bp = Blueprint("payments", __name__)

ALLOCATION_POLICIES = {"RESTITUTION_FIRST", "OLDEST_FIRST"}


@bp.post("/supervisees/<sid>/payments")
@require_roles("Officer")
def create(sid):
    s = get_supervisee_or_404(sid)
    body = get_body()
    require_fields(body, ["amount_cents"])
    require_int_min(body["amount_cents"], 1, "amount_cents")

    allocation_policy = body.get("allocation_policy", "RESTITUTION_FIRST")
    if allocation_policy is None:
        allocation_policy = "RESTITUTION_FIRST"
    check_enum(allocation_policy, ALLOCATION_POLICIES, "allocation_policy")

    # Closed-supervisee guard (PRD §3.11).
    if s["status"] in TERMINAL_SUPERVISEE_STATES:
        raise ApiError(*ERR_SUPERVISEE_CLOSED, "Supervisee case is closed.")

    applied = svc.apply_payment(s, body["amount_cents"], allocation_policy)

    # Payment carries only id + created_at (no updated_at / version).
    rec = db.common_create_fields(versioned=False)
    posted = iso_now(clock.now())
    rec.update(
        {
            "supervisee_id": s["id"],
            "amount_cents": body["amount_cents"],
            "allocation_policy": allocation_policy,
            "applied_breakdown": applied,
            "posted_at": posted,
        }
    )
    db.payments[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/supervisees/<sid>/payments")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def list_payments(sid):
    get_supervisee_or_404(sid)
    limit, offset = paginate(request.args)
    records = [p for p in db.payments.values() if p.get("supervisee_id") == sid]
    records = sorted_by_created(records)
    page, total = apply_page(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.get("/supervisees/<sid>/obligations/<oid>/payments")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def list_obligation_payments(sid, oid):
    get_supervisee_or_404(sid)
    get_child_or_404(db.obligations, oid, sid, label="Obligation")
    limit, offset = paginate(request.args)
    records = [
        p
        for p in db.payments.values()
        if p.get("supervisee_id") == sid and oid in (p.get("applied_breakdown") or {})
    ]
    records = sorted_by_created(records)
    page, total = apply_page(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)
