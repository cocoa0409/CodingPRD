"""ScholarshipAward routes (PRD §3.3, §3.6)."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint

from db import db
from errors import APIError, ERR_INVALID_STATE
from middleware import require_roles, ROLE_GUARDIAN, ROLE_DIRECTOR
from response import ok_object
from services.common import (
    make_record,
    serialize,
    touch,
    audit,
    get_body,
    require_str,
    require_enum,
)
from services.calculations import TIER_TABLE
from services.lookups import get_child, get_scholarship_award, require_child_owner
from services.state_machines import scholarship_reprice_cascade

bp = Blueprint("scholarships", __name__)


@bp.post("/scholarship-awards")
def create_scholarship():
    caller = require_roles(ROLE_GUARDIAN)
    body = get_body()
    child_id = require_str(body, "child_id")
    tier = require_enum(body, "tier", {"NONE", "PARTIAL", "FULL"})
    child = get_child(child_id)
    require_child_owner(child, caller.user_id)

    rec = make_record(
        {
            "child_id": child_id,
            "tier": tier,
            "status": "REQUESTED",
            "approved_discount_pct": 0,
        }
    )
    db.scholarship_awards[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.post("/scholarship-awards/<aid>/approve")
def approve_scholarship(aid):
    caller = require_roles(ROLE_DIRECTOR)
    award = get_scholarship_award(aid)
    if award["status"] != "REQUESTED":
        raise APIError(ERR_INVALID_STATE, 409, "Award is not REQUESTED")
    if award["tier"] == "NONE":
        raise APIError(ERR_INVALID_STATE, 409, "Cannot approve a NONE-tier award")
    award["status"] = "APPROVED"
    pct = TIER_TABLE[award["tier"]]
    # approved_discount_pct: fraction in [0,1], up to 2 decimals
    award["approved_discount_pct"] = float(pct)
    touch(award)
    audit("ScholarshipAward", award["id"], "SCHOLARSHIP_APPROVED", caller.role)
    # depth-3 cascade: re-price the child's DRAFT-invoice CONFIRMED lines with the
    # newly locked discount, then re-total each touched invoice.
    scholarship_reprice_cascade(award["child_id"])
    return ok_object(serialize(award), 200)


@bp.post("/scholarship-awards/<aid>/deny")
def deny_scholarship(aid):
    caller = require_roles(ROLE_DIRECTOR)
    award = get_scholarship_award(aid)
    if award["status"] != "REQUESTED":
        raise APIError(ERR_INVALID_STATE, 409, "Award is not REQUESTED")
    award["status"] = "DENIED"
    touch(award)
    audit("ScholarshipAward", award["id"], "SCHOLARSHIP_DENIED", caller.role)
    return ok_object(serialize(award), 200)


@bp.post("/scholarship-awards/<aid>/revoke")
def revoke_scholarship(aid):
    caller = require_roles(ROLE_DIRECTOR)
    award = get_scholarship_award(aid)
    if award["status"] != "APPROVED":
        raise APIError(ERR_INVALID_STATE, 409, "Award is not APPROVED")
    # may revoke only when no invoice referencing this child's enrollments is
    # FINALIZED, PAID, or VOID.
    child_id = award["child_id"]
    blocked_invoice_ids = set()
    for e in db.enrollments.values():
        if e["child_id"] == child_id and e.get("invoice_id"):
            blocked_invoice_ids.add(e["invoice_id"])
    for inv_id in blocked_invoice_ids:
        inv = db.invoices.get(inv_id)
        if inv and inv["status"] in ("FINALIZED", "PAID", "VOID"):
            raise APIError(ERR_INVALID_STATE, 409, "Child has a non-DRAFT invoice; cannot revoke")

    award["status"] = "REVOKED"
    award["approved_discount_pct"] = 0
    touch(award)
    audit("ScholarshipAward", award["id"], "SCHOLARSHIP_REVOKED", caller.role)
    # compensating re-price: restore each DRAFT line to undiscounted, then re-total
    scholarship_reprice_cascade(child_id, discount_pct=Decimal("0.0"))
    return ok_object(serialize(award), 200)
