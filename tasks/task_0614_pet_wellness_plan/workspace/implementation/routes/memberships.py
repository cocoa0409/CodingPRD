"""Membership aggregate endpoints (PRD §3.2, §3.3, §3.6, §3.8)."""
from flask import Blueprint, request

from db import db
from errors import (
    err, ERR_REFERENCE_NOT_FOUND, ERR_NOT_RESOURCE_OWNER, ERR_INVALID_STATE,
)
from middleware import authenticate, require_role
from response import success, list_success
from common import (
    parse_pagination, paginate, sort_by_created, get_json, stamp_new, touch,
    public, require_str, require_int, require_number, require_enum, require_bool,
)
from lookup import get_or_404
from services import membership_ops
from services.plan_change import apply_plan_change

bp = Blueprint("memberships", __name__)

SPECIES = {"DOG", "CAT"}


def _owned_membership(mid, user_id, role):
    """Resolve a membership in the path and enforce Member ownership.

    Path existence (ERR_NOT_FOUND) then ownership (ERR_NOT_RESOURCE_OWNER).
    """
    membership = get_or_404(db.memberships, mid)
    if role == "Member" and membership["member_account_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner")
    return membership


# --------------------------------------------------------------------------
# Create / list / get membership
# --------------------------------------------------------------------------
@bp.post("/wellness/memberships")
def create_membership():
    user_id, role = authenticate()
    require_role(role, {"Member"})
    body = get_json()
    member_account_id = require_str(body, "member_account_id")
    plan_id = require_str(body, "plan_id")
    anchor = require_int(body, "billing_anchor_day", minimum=1, maximum=28)
    auto_renew = require_bool(body, "auto_renew", default=True)

    # Member ownership: the owning account must be the caller's own account
    # (PRD §2.1). Account existence is a body FK (ERR_REFERENCE_NOT_FOUND).
    account = db.member_accounts.get(member_account_id)
    if account is None:
        raise err(ERR_REFERENCE_NOT_FOUND, "Referenced member account does not exist")
    plan = db.plans.get(plan_id)
    if plan is None:
        raise err(ERR_REFERENCE_NOT_FOUND, "Referenced plan does not exist")
    if member_account_id != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner")

    membership = {
        "member_account_id": member_account_id,
        "plan_id": plan_id,
        "billing_anchor_day": anchor,
        "monthly_fee_cents": plan["monthly_fee_cents"],
        "pet_count": 0,
        "auto_renew": auto_renew,
        "status": "PENDING_PAYMENT",
    }
    stamp_new(membership)
    db.memberships[membership["id"]] = membership
    return success(public(membership), 201)


@bp.get("/wellness/memberships")
def list_memberships():
    user_id, role = authenticate()
    require_role(role, {"PlanAdmin", "BillingAdmin", "Member"})
    limit, offset = parse_pagination()
    rows = list(db.memberships.values())
    if role == "Member":
        rows = [r for r in rows if r["member_account_id"] == user_id]
    for f in ("member_account_id", "plan_id", "status"):
        v = request.args.get(f)
        if v is not None:
            rows = [r for r in rows if r[f] == v]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)


@bp.get("/wellness/memberships/<mid>")
def get_membership(mid):
    user_id, role = authenticate()
    require_role(role, {"Member", "PlanAdmin", "BillingAdmin"})
    membership = _owned_membership(mid, user_id, role)
    return success(public(membership))


# --------------------------------------------------------------------------
# Pets
# --------------------------------------------------------------------------
@bp.post("/wellness/memberships/<mid>/pets")
def add_pet(mid):
    user_id, role = authenticate()
    require_role(role, {"Member"})
    membership = _owned_membership(mid, user_id, role)
    body = get_json()
    name = require_str(body, "name")
    species = require_enum(body, "species", SPECIES)
    weight_kg = require_number(body, "weight_kg", gt=0)

    # Pets may be added while PENDING_PAYMENT or ENROLLED (PRD §3.3).
    if membership["status"] not in ("PENDING_PAYMENT", "ENROLLED"):
        raise err(ERR_INVALID_STATE,
                  "Pets can only be added while PENDING_PAYMENT or ENROLLED")

    from db import now_iso
    pet = {
        "membership_id": mid,
        "name": name,
        "species": species,
        "weight_kg": weight_kg,
        "enrolled_at": now_iso(),
        "status": "ENROLLED",
    }
    stamp_new(pet)
    db.enrolled_pets[pet["id"]] = pet
    membership_ops.recompute_pet_count(membership)
    touch(membership)  # increments Membership.version by one (PRD §3.3)
    return success(public(pet), 201)


@bp.get("/wellness/memberships/<mid>/pets")
def list_pets(mid):
    user_id, role = authenticate()
    require_role(role, {"Member", "PlanAdmin", "BillingAdmin", "ClinicStaff"})
    membership = _owned_membership(mid, user_id, role)
    limit, offset = parse_pagination()
    rows = [p for p in db.enrolled_pets.values() if p["membership_id"] == mid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)


@bp.get("/wellness/memberships/<mid>/pets/<pet_id>")
def get_pet(mid, pet_id):
    user_id, role = authenticate()
    require_role(role, {"Member", "PlanAdmin", "BillingAdmin", "ClinicStaff"})
    membership = _owned_membership(mid, user_id, role)
    pet = db.enrolled_pets.get(pet_id)
    if pet is None or pet["membership_id"] != mid:
        raise _pet_404()
    return success(public(pet))


def _pet_404():
    from errors import ERR_NOT_FOUND
    return err(ERR_NOT_FOUND, "Pet not found")


@bp.post("/wellness/memberships/<mid>/pets/<pet_id>/remove")
def remove_pet(mid, pet_id):
    user_id, role = authenticate()
    require_role(role, {"Member"})
    membership = _owned_membership(mid, user_id, role)
    pet = db.enrolled_pets.get(pet_id)
    if pet is None or pet["membership_id"] != mid:
        raise _pet_404()
    # Removal permitted only when pet status IN {ENROLLED, SUSPENDED} (PRD §3.6).
    if pet["status"] not in ("ENROLLED", "SUSPENDED"):
        raise err(ERR_INVALID_STATE, "Pet is not in a removable state")
    pet["status"] = "REMOVED"
    touch(pet)
    membership_ops.recompute_pet_count(membership)
    touch(membership)  # increments Membership.version by one (PRD §3.6)
    return success(public(pet))


# --------------------------------------------------------------------------
# Lifecycle transitions
# --------------------------------------------------------------------------
@bp.post("/wellness/memberships/<mid>/activate")
def activate(mid):
    user_id, role = authenticate()
    require_role(role, {"Member"})
    membership = _owned_membership(mid, user_id, role)
    membership_ops.activate(membership)
    return success(public(membership))


@bp.post("/wellness/memberships/<mid>/suspend")
def suspend(mid):
    user_id, role = authenticate()
    require_role(role, {"Member"})
    membership = _owned_membership(mid, user_id, role)
    membership_ops.suspend(membership)
    return success(public(membership))


@bp.post("/wellness/memberships/<mid>/resume")
def resume(mid):
    user_id, role = authenticate()
    require_role(role, {"Member"})
    membership = _owned_membership(mid, user_id, role)
    membership_ops.resume(membership)
    return success(public(membership))


@bp.post("/wellness/memberships/<mid>/cancel")
def cancel(mid):
    user_id, role = authenticate()
    require_role(role, {"Member"})
    membership = _owned_membership(mid, user_id, role)
    membership_ops.cancel(membership)
    return success(public(membership))


@bp.post("/wellness/memberships/<mid>/finalize-cancel")
def finalize_cancel(mid):
    user_id, role = authenticate()
    require_role(role, {"BillingAdmin"})
    membership = get_or_404(db.memberships, mid)
    membership_ops.finalize_cancel(membership)
    return success(public(membership))


# --------------------------------------------------------------------------
# Plan change (OCC-guarded)
# --------------------------------------------------------------------------
@bp.post("/wellness/memberships/<mid>/plan-change")
def plan_change(mid):
    user_id, role = authenticate()
    require_role(role, {"Member"})
    membership = _owned_membership(mid, user_id, role)
    body = get_json()
    to_plan_id = require_str(body, "to_plan_id")
    expected_version = require_int(body, "expected_membership_version")
    pcr = apply_plan_change(membership, to_plan_id, expected_version)
    return success(public(pcr))


@bp.get("/wellness/memberships/<mid>/plan-changes")
def list_membership_plan_changes(mid):
    user_id, role = authenticate()
    require_role(role, {"Member", "PlanAdmin", "BillingAdmin"})
    membership = _owned_membership(mid, user_id, role)
    limit, offset = parse_pagination()
    rows = [p for p in db.plan_change_requests.values()
            if p["membership_id"] == mid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)
