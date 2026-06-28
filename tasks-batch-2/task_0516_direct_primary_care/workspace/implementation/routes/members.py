"""Member + member-scoped endpoints (PRD §3.3, §3.4, §3.9)."""
from flask import Blueprint, request

import db
import errors
import response
import serialize
import validate
from middleware import authenticate, require_roles
from routes.helpers import get_or_404, require_member_owns
from services import domain

bp = Blueprint("members", __name__)


def _membership_for_member(member_id):
    for ms in db.memberships.values():
        if ms["member_id"] == member_id:
            return ms
    return None


@bp.route("/members/register", methods=["POST"])
def register_member():
    # Anonymous-only self-service (no auth headers required).
    data = validate.body()
    practice_id = validate.require(data, "practice_id", str)
    email = validate.require(data, "email", str)
    full_name = validate.require(data, "full_name", str)
    plan_type = validate.optional(data, "plan_type", str, "MONTHLY")
    has_insurance = validate.optional(data, "has_insurance", bool, False)

    validate.enum(plan_type, {"MONTHLY", "ANNUAL_PREPAID"}, "plan_type")

    practice = get_or_404("practice", practice_id)

    # email unique per practice (PRD §3.3).
    for m in db.members.values():
        if m["practice_id"] == practice_id and m["email"] == email:
            raise errors.validation("email must be unique within the practice.")

    member = dict(db.common_fields())
    member["id"] = db.new_id()
    member["_seq"] = db.next_seq()
    member["practice_id"] = practice_id
    member["assigned_provider_id"] = None
    member["email"] = email
    member["full_name"] = full_name
    member["plan_type"] = plan_type
    member["membership_status"] = "PENDING_PAYMENT"
    member["has_insurance"] = has_insurance
    member["wallet_credit_cents"] = 0
    member["annual_physical_due_on"] = None
    db.members[member["id"]] = member

    membership = dict(db.common_fields())
    membership["id"] = db.new_id()
    membership["_seq"] = db.next_seq()
    membership["member_id"] = member["id"]
    membership["plan_type"] = plan_type
    membership["monthly_fee_cents"] = practice["monthly_fee_cents"]
    membership["employer_seat_id"] = None
    membership["current_period_start"] = None
    membership["current_period_end"] = None
    membership["past_due_since"] = None
    domain.set_member_share(membership)  # unsponsored
    db.memberships[membership["id"]] = membership

    return response.object_response(serialize.member(member), 201)


@bp.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Provider", "Member"})
    member = get_or_404("member", mid)
    if caller.role == "Member":
        require_member_owns(caller, mid)
    elif caller.role == "Provider":
        if member.get("assigned_provider_id") != caller.user_id:
            raise errors.forbidden("Provider does not own this member.")
    return response.object_response(serialize.member(member), 200)


@bp.route("/members", methods=["GET"])
def list_members():
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Provider"})
    limit, offset = validate.pagination()
    practice_id = request.args.get("practice_id")
    assigned_provider_id = request.args.get("assigned_provider_id")
    membership_status = request.args.get("membership_status")

    rows = list(db.members.values())
    if caller.role == "Provider":
        rows = [r for r in rows if r.get("assigned_provider_id") == caller.user_id]
    if practice_id is not None:
        rows = [r for r in rows if r["practice_id"] == practice_id]
    if assigned_provider_id is not None:
        rows = [r for r in rows if r.get("assigned_provider_id") == assigned_provider_id]
    if membership_status is not None:
        rows = [r for r in rows if r["membership_status"] == membership_status]

    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(
        [serialize.member(r) for r in page], limit, offset, total, 200
    )


@bp.route("/members/<mid>/assign-pcp", methods=["POST"])
def assign_pcp(mid):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin"})
    member = get_or_404("member", mid)
    data = validate.body()

    mode = validate.require(data, "mode", str)
    validate.enum(mode, {"AUTO", "MANUAL"}, "mode")

    if mode == "MANUAL":
        provider_id = validate.require(data, "provider_id", str)
        provider = get_or_404("provider", provider_id)
        # Panel capacity (priority 11): room required.
        if provider["active_panel_count"] >= domain.effective_cap(provider):
            raise errors.no_panel_capacity("Provider panel is full.")
    else:
        provider = domain.select_auto_provider(member)
        if provider is None:
            raise errors.no_panel_capacity("No eligible provider with panel capacity.")

    old_provider_id = member.get("assigned_provider_id")
    member["assigned_provider_id"] = provider["id"]
    db.touch(member)

    # If member is ACTIVE/PAST_DUE the panel counts change (PRD §3.3).
    if member["membership_status"] in ("ACTIVE", "PAST_DUE"):
        domain.recompute_provider_panel(provider)
        if old_provider_id is not None and old_provider_id != provider["id"]:
            old = db.providers.get(old_provider_id)
            if old is not None:
                domain.recompute_provider_panel(old)

    return response.object_response(serialize.member(member), 200)


@bp.route("/members/<mid>/cancel", methods=["POST"])
def cancel_member(mid):
    caller = authenticate()
    require_roles(caller, {"Member"})
    member = get_or_404("member", mid)
    require_member_owns(caller, mid)

    status = member["membership_status"]
    if status not in ("ACTIVE", "PAST_DUE", "SUSPENDED"):
        raise errors.invalid_state("Membership cannot be cancelled from %s." % status)

    membership = _membership_for_member(mid)

    # Proration only when cancelling from ACTIVE (PRD §3.9).
    if status == "ACTIVE" and membership is not None:
        refund = domain.compute_proration_refund(membership)
        member["wallet_credit_cents"] = member["wallet_credit_cents"] + refund

    # Release employer seat for all three paths if sponsored (PRD §3.3).
    if membership is not None and membership.get("employer_seat_id") is not None:
        domain.release_employer_seat(membership)

    member["membership_status"] = "CANCELLED"
    db.touch(member)

    # Recompute provider panel for ACTIVE/PAST_DUE/SUSPENDED transitions.
    provider_id = member.get("assigned_provider_id")
    if provider_id is not None:
        provider = db.providers.get(provider_id)
        if provider is not None:
            domain.recompute_provider_panel(provider)

    # Cancel open visits (BOOKED/CHECKED_IN) — PRD §3.3 lists this for ACTIVE
    # and PAST_DUE cancellations.
    if status in ("ACTIVE", "PAST_DUE"):
        domain.cancel_open_visits_for_member(member)

    return response.object_response(serialize.member(member), 200)


@bp.route("/members/<mid>/memberships", methods=["GET"])
def list_member_memberships(mid):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Provider", "Member"})
    member = get_or_404("member", mid)
    if caller.role == "Member":
        require_member_owns(caller, mid)
    elif caller.role == "Provider":
        if member.get("assigned_provider_id") != caller.user_id:
            raise errors.forbidden("Provider does not own this member.")
    limit, offset = validate.pagination()

    rows = [ms for ms in db.memberships.values() if ms["member_id"] == mid]
    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(
        [serialize.membership(r) for r in page], limit, offset, total, 200
    )


@bp.route("/members/<mid>/message-threads", methods=["GET"])
def list_member_threads(mid):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Provider", "Member"})
    member = get_or_404("member", mid)
    if caller.role == "Member":
        require_member_owns(caller, mid)
    elif caller.role == "Provider":
        if member.get("assigned_provider_id") != caller.user_id:
            raise errors.forbidden("Provider does not own this member.")
    limit, offset = validate.pagination()
    thread_status = request.args.get("thread_status")

    rows = [t for t in db.message_threads.values() if t["member_id"] == mid]
    if thread_status is not None:
        rows = [r for r in rows if r["thread_status"] == thread_status]
    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(
        [serialize.message_thread(r) for r in page], limit, offset, total, 200
    )
