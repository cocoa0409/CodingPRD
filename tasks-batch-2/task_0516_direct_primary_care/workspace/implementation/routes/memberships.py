"""Membership read + membership-fee charge (PRD §3.3, §3.8)."""
from flask import Blueprint, request

import db
import errors
import response
import serialize
import validate
from clock import clock
from middleware import authenticate, require_roles
from routes.helpers import get_or_404, require_member_owns
from services import domain

bp = Blueprint("memberships", __name__)


@bp.route("/memberships/<msid>", methods=["GET"])
def get_membership(msid):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Member"})
    ms = get_or_404("membership", msid)
    if caller.role == "Member":
        require_member_owns(caller, ms["member_id"])
    return response.object_response(serialize.membership(ms), 200)


@bp.route("/memberships", methods=["GET"])
def list_memberships():
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Member", "Employer"})
    limit, offset = validate.pagination()
    member_id = request.args.get("member_id")
    employer_seat_id = request.args.get("employer_seat_id")

    rows = list(db.memberships.values())
    if caller.role == "Member":
        rows = [r for r in rows if r["member_id"] == caller.user_id]
    elif caller.role == "Employer":
        # Employer sees memberships tied to its seats.
        own_seats = {s["id"] for s in db.employer_seats.values()
                     if s["employer_id"] == caller.user_id}
        rows = [r for r in rows if r.get("employer_seat_id") in own_seats]
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    if employer_seat_id is not None:
        rows = [r for r in rows if r.get("employer_seat_id") == employer_seat_id]

    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(
        [serialize.membership(r) for r in page], limit, offset, total, 200
    )


@bp.route("/memberships/<msid>/charge", methods=["POST"])
def charge_membership(msid):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Member"})
    membership = get_or_404("membership", msid)
    member = db.members[membership["member_id"]]
    if caller.role == "Member":
        require_member_owns(caller, member["id"])

    data = validate.body()
    charge_kind = validate.require(data, "charge_kind", str)
    validate.enum(charge_kind, {"MEMBERSHIP_FEE", "INVOICE"}, "charge_kind")
    amount_cents = validate.require(data, "amount_cents", int)
    outcome = validate.require(data, "outcome", str)
    validate.enum(outcome, {"SUCCEEDED", "FAILED"}, "outcome")

    if charge_kind != "MEMBERSHIP_FEE":
        raise errors.invalid_request("charge_kind must be MEMBERSHIP_FEE here.")
    if amount_cents < 0:
        raise errors.invalid_request("amount_cents must be >= 0.")

    status = member["membership_status"]
    now = clock.now()

    # State validity (priority 5): a SUCCEEDED membership-fee charge only has a
    # defined transition from PENDING_PAYMENT, PAST_DUE, or SUSPENDED (§1.2).
    if outcome == "SUCCEEDED" and status not in ("PENDING_PAYMENT", "PAST_DUE", "SUSPENDED"):
        raise errors.invalid_state(
            "No membership transition defined from %s on a successful charge." % status
        )

    # Late fee applies only on the retry that exits PAST_DUE.
    late_fee = (status == "PAST_DUE")
    expected_amount = domain.compute_member_share(membership, late_fee=late_fee)

    # Charge-amount agreement (priority 15).
    if amount_cents != expected_amount:
        raise errors.amount_mismatch(
            "amount_cents (%d) does not equal member_share owed (%d)."
            % (amount_cents, expected_amount)
        )

    # PCP-before-activation (priority 16): PENDING_PAYMENT -> ACTIVE needs a PCP.
    if outcome == "SUCCEEDED" and status == "PENDING_PAYMENT" \
            and member.get("assigned_provider_id") is None:
        raise errors.pcp_required("A PCP must be assigned before activation.")

    # Apply wallet credit first (PRD §3.8); record wallet_applied_cents.
    wallet_available = member["wallet_credit_cents"]
    wallet_applied = min(wallet_available, amount_cents)

    payment = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "created_at": now,
        "member_id": member["id"],
        "membership_id": membership["id"],
        "invoice_id": None,
        "charge_kind": "MEMBERSHIP_FEE",
        "amount_cents": amount_cents,
        "outcome": outcome,
        "wallet_applied_cents": wallet_applied,
    }
    db.payments[payment["id"]] = payment

    if outcome == "SUCCEEDED":
        # Debit wallet by the applied portion (never below zero).
        member["wallet_credit_cents"] = max(0, wallet_available - wallet_applied)
        db.touch(member)
        _activate_or_reinstate(membership, member, status)
    else:
        # FAILED at period rollover from ACTIVE -> PAST_DUE.
        if status == "ACTIVE" and now >= membership["current_period_end"]:
            member["membership_status"] = "PAST_DUE"
            db.touch(member)
            membership["past_due_since"] = now
            # Late fee added to the next member_share owed.
            domain.set_member_share(membership, late_fee=True)
            db.touch(membership)
            provider = _provider_of(member)
            if provider is not None:
                domain.recompute_provider_panel(provider)

    return response.object_response(serialize.payment(payment), 201)


def _provider_of(member):
    pid = member.get("assigned_provider_id")
    if pid is None:
        return None
    return db.providers.get(pid)


def _activate_or_reinstate(membership, member, status):
    now = clock.now()
    if status == "PENDING_PAYMENT":
        member["membership_status"] = "ACTIVE"
        db.touch(member)
        membership["current_period_start"] = now
        membership["current_period_end"] = domain.compute_period_end(membership)
        domain.set_member_share(membership)
        db.touch(membership)
        provider = _provider_of(member)
        if provider is not None:
            domain.recompute_provider_panel(provider)
    elif status == "PAST_DUE":
        # Reinstate only within the grace window (PRD §3.3).
        practice = db.practices[member["practice_id"]]
        grace_end = membership["past_due_since"] + _days(practice["grace_period_days"])
        if not (now < grace_end):
            raise errors.invalid_state("Grace window has elapsed; cannot reinstate.")
        member["membership_status"] = "ACTIVE"
        db.touch(member)
        membership["past_due_since"] = None
        _advance_period(membership)
        domain.set_member_share(membership)  # clears late fee
        db.touch(membership)
        provider = _provider_of(member)
        if provider is not None:
            domain.recompute_provider_panel(provider)
    elif status == "SUSPENDED":
        provider = _provider_of(member)
        if provider is not None and provider["active_panel_count"] >= domain.effective_cap(provider):
            raise errors.no_panel_capacity("Provider panel full; cannot reinstate.")
        member["membership_status"] = "ACTIVE"
        db.touch(member)
        membership["past_due_since"] = None
        _advance_period(membership)
        domain.set_member_share(membership)
        db.touch(membership)
        if provider is not None:
            domain.recompute_provider_panel(provider)
    else:
        # No SUCCEEDED membership-fee transition is defined from ACTIVE or
        # CANCELLED in the state machine (§1.2) -> ERR_INVALID_STATE (priority 5).
        raise errors.invalid_state(
            "No membership transition defined from %s on a successful charge." % status
        )


def _advance_period(membership):
    from datetime import timedelta
    plen = domain.period_length_days(membership["plan_type"])
    start = membership["current_period_start"]
    if start is None:
        start = clock.now()
    new_start = start + timedelta(days=plen)
    membership["current_period_start"] = new_start
    membership["current_period_end"] = domain.compute_period_end(membership)


def _days(n):
    from datetime import timedelta
    return timedelta(days=n)
