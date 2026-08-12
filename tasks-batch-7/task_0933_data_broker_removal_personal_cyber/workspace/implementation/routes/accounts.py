"""Account lifecycle, roster growth, add-on purchase and derived reports."""

from flask import Blueprint, request

import calc
import cascades
import constants as K
import context
import derive
import envelope
import ids
import ledger
import rows
import serializers
import states
from clock import CLOCK, plus_days, whole_days_between
from context import Ctx
from errors import ApiError
from store import DB, ordered

bp = Blueprint("accounts", __name__)


# --- POST /accounts ---------------------------------------------------------

@bp.post("/accounts")
def open_account():
    ctx = Ctx(request, [K.ROLE_PLATFORM_ADMIN])
    ctx.load_body()
    fields = ctx.validate(
        [
            {"name": "plan_id", "type": "string", "required": True},
            {"name": "primary_member_email", "type": "string", "required": True},
            {"name": "primary_member_full_name", "type": "string", "required": True},
        ]
    )
    # Rung 11 -- body foreign key.
    plan = DB.plans.get(fields["plan_id"])
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND")

    account = rows.new_row(
        "accounts",
        {
            "plan_id": plan["id"],
            "primary_member_id": None,
            "status": "ACTIVE",
            "legal_hold": False,
            "legal_hold_set_at": None,
            "suspended_at": None,
            "cancelled_at": None,
        },
    )
    primary = rows.new_row(
        "members",
        {
            "account_id": account["id"],
            "email": fields["primary_member_email"],
            "full_name": fields["primary_member_full_name"],
            "role_in_family": "PRIMARY",
            "is_primary": True,
            "status": "ACTIVE",
            "authorization_status": "GRANTED",
            "invitation_token": None,
            "activated_at": None,
            "authorization_revoked_at": None,
        },
    )
    # Stamped at creation, so the account keeps version 1.
    account["primary_member_id"] = primary["id"]
    cycle = rows.new_row(
        "cycles",
        {
            "account_id": account["id"],
            "cycle_seq": 1,
            "starts_at": CLOCK.now,
            "ends_at": plus_days(CLOCK.now, K.CYCLE_LENGTH_DAYS),
            "status": "OPEN",
            "base_charge_cents": int(plan["monthly_fee_cents"]),
            "proration_charge_cents": 0,
            "proration_credit_cents": 0,
            "addon_charge_cents": 0,
            "addon_credit_cents": 0,
            "closed_at": None,
            "frozen_totals": None,
        },
    )
    ledger.grant_cycle(account, cycle, plan)
    return envelope.created(serializers.account(account))


# --- GET /accounts ----------------------------------------------------------

@bp.get("/accounts")
def list_accounts():
    ctx = Ctx(request, [K.ROLE_PLATFORM_ADMIN, K.ROLE_AUDITOR])
    status = context.enum_filter(request, "status", K.ACCOUNT_STATUSES)
    limit, offset = context.pagination(request)
    plan_id = context.plain_filter(request, "plan_id")
    primary_member_id = context.plain_filter(request, "primary_member_id")
    result = [
        a
        for a in DB.accounts.values()
        if (plan_id is None or a["plan_id"] == plan_id)
        and (primary_member_id is None or a["primary_member_id"] == primary_member_id)
        and (status is None or a["status"] == status)
    ]
    page, total = context.window(ordered(result), limit, offset)
    return envelope.listing([serializers.account(a) for a in page], limit, offset, total)


@bp.get("/accounts/<account_id>")
def read_account(account_id):
    ctx = Ctx(
        request,
        [
            K.ROLE_PLATFORM_ADMIN,
            K.ROLE_PRIVACY_AGENT,
            K.ROLE_ACCOUNT_OWNER,
            K.ROLE_MEMBER,
            K.ROLE_AUDITOR,
        ],
    )
    account = ctx.path("account", account_id)
    ctx.own(account["id"])  # account-level read
    return envelope.ok(serializers.account(account))


# --- state transitions ------------------------------------------------------

@bp.post("/accounts/<account_id>/suspend")
def suspend_account(account_id):
    ctx = Ctx(request, [K.ROLE_PLATFORM_ADMIN])
    account = ctx.path("account", account_id)
    ctx.write_gates(account)
    states.gate("account_status", account["status"], ("ACTIVE",))
    cascades.suspend_account(account)
    return envelope.ok(serializers.account(account))


@bp.post("/accounts/<account_id>/resume")
def resume_account(account_id):
    ctx = Ctx(request, [K.ROLE_PLATFORM_ADMIN])
    account = ctx.path("account", account_id)
    # Rung 15 exempt: resuming is how a suspension is undone.
    ctx.write_gates(account, skip_suspended=True)
    states.gate("account_status", account["status"], ("SUSPENDED",))
    cascades.resume_account(account)
    return envelope.ok(serializers.account(account))


@bp.post("/accounts/<account_id>/cancel")
def cancel_account(account_id):
    ctx = Ctx(request, [K.ROLE_PLATFORM_ADMIN, K.ROLE_ACCOUNT_OWNER])
    account = ctx.path("account", account_id)
    ctx.own(account["id"])
    # Rung 15 exempt: cancelling is how a suspended household terminates.
    ctx.write_gates(account, skip_suspended=True)
    states.gate("account_status", account["status"], ("ACTIVE", "SUSPENDED"))
    cascades.cancel_account(account)
    return envelope.ok(serializers.account(account))


@bp.post("/accounts/<account_id>/legal-hold")
def legal_hold(account_id):
    ctx = Ctx(request, [K.ROLE_PLATFORM_ADMIN])
    account = ctx.path("account", account_id)
    ctx.load_body()
    fields = ctx.validate(
        [{"name": "hold_state", "type": "string", "required": True, "enum": K.HOLD_STATES}]
    )
    # The single capability exempt from all three global write gates (PRD §2.7).
    current = "HOLD_ON" if account["legal_hold"] else "HOLD_OFF"
    target = fields["hold_state"]
    allowed = ("HOLD_OFF",) if target == "HOLD_ON" else ("HOLD_ON",)
    states.gate("account_legal_hold", current, allowed)
    if target == "HOLD_ON":
        account["legal_hold"] = True
        account["legal_hold_set_at"] = CLOCK.now
    else:
        account["legal_hold"] = False
        account["legal_hold_set_at"] = None
    rows.touch(account)
    return envelope.ok(serializers.account(account))


# --- plan changes -----------------------------------------------------------

@bp.post("/accounts/<account_id>/plan-changes")
def plan_change(account_id):
    ctx = Ctx(request, [K.ROLE_PLATFORM_ADMIN, K.ROLE_ACCOUNT_OWNER])
    account = ctx.path("account", account_id)
    ctx.load_body()
    fields = ctx.validate(
        [
            {"name": "new_plan_id", "type": "string", "required": True},
            {"name": "change_kind", "type": "string", "required": True, "enum": K.CHANGE_KINDS},
            {"name": "expected_account_version", "type": "integer", "required": True},
        ]
    )
    # Rung 11
    new_plan = DB.plans.get(fields["new_plan_id"])
    if new_plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND")
    # Rung 12
    ctx.own(account["id"])
    # Rungs 13-15
    ctx.write_gates(account)
    # Rung 17
    if fields["expected_account_version"] != account["version"]:
        raise ApiError("ERR_STALE_ACCOUNT_VERSION")
    # Rung 24
    cycle = derive.open_cycle(account["id"])
    if cycle is None:
        raise ApiError("ERR_CYCLE_CLOSED")
    # Rung 47 -- the downgrade guard; boundary is INCLUSIVE.
    pools = derive.pool_figures(account["id"])
    occupied = derive.occupied_seat_count(account["id"])
    if (
        int(new_plan["max_members"]) < occupied
        or int(new_plan["profile_quota_per_cycle"]) < pools["profile"]["consumed"]
    ):
        raise ApiError("ERR_PLAN_DOWNGRADE_BELOW_USAGE")

    old_plan = DB.plans.get(account["plan_id"])
    old_fee = int(old_plan["monthly_fee_cents"])
    new_fee = int(new_plan["monthly_fee_cents"])
    fee_delta = abs(new_fee - old_fee)
    remaining_days = max(0, whole_days_between(CLOCK.now, cycle["ends_at"]))
    kind = fields["change_kind"]

    # Adjudication of friction 6: variant selection when `change_kind`
    # contradicts the fee direction. Each variant requires BOTH a matching
    # change_kind AND a fee movement in the corresponding direction, and PRD
    # §3.9 explicitly refuses to extend either variant to the contradictory
    # case. Choosing the reading that keeps the most declared behaviour
    # reachable: no variant fires, so no money is booked (both figures 0),
    # while the plan change itself still succeeds -- it repoints plan_id and
    # bumps the account version, keeping the OCC guard, rung 47 and the
    # "re-grants nothing" rule all reachable. Inventing a third variant, or
    # rejecting the call, would delete declared behaviour instead.
    if kind == "UPGRADE" and new_fee > old_fee:
        charge = calc.plan_proration_upgrade(fee_delta, remaining_days)
        cycle["proration_charge_cents"] = int(cycle["proration_charge_cents"]) + charge
        rows.touch(cycle)
    elif kind == "DOWNGRADE" and new_fee < old_fee:
        credit = calc.plan_proration_downgrade(fee_delta, remaining_days)
        cycle["proration_credit_cents"] = int(cycle["proration_credit_cents"]) + credit
        rows.touch(cycle)

    account["plan_id"] = new_plan["id"]
    rows.touch(account)
    return envelope.ok(serializers.account(account))


# --- roster -----------------------------------------------------------------

@bp.get("/accounts/<account_id>/members")
def list_members(account_id):
    ctx = Ctx(
        request,
        [
            K.ROLE_PLATFORM_ADMIN,
            K.ROLE_PRIVACY_AGENT,
            K.ROLE_ACCOUNT_OWNER,
            K.ROLE_MEMBER,
            K.ROLE_AUDITOR,
        ],
    )
    account = ctx.path("account", account_id)
    status = context.enum_filter(request, "status", K.MEMBER_STATUSES)
    limit, offset = context.pagination(request)
    ctx.own(account["id"])  # account-level read
    result = [
        m
        for m in derive.account_members(account["id"])
        if status is None or m["status"] == status
    ]
    page, total = context.window(ordered(result), limit, offset)
    return envelope.listing([serializers.member(m) for m in page], limit, offset, total)


@bp.post("/accounts/<account_id>/members")
def invite_member(account_id):
    ctx = Ctx(request, [K.ROLE_PLATFORM_ADMIN, K.ROLE_ACCOUNT_OWNER])
    account = ctx.path("account", account_id)
    ctx.load_body()
    fields = ctx.validate(
        [
            {"name": "email", "type": "string", "required": True, "must_contain": "@"},
            {"name": "full_name", "type": "string", "required": True},
            {
                "name": "role_in_family",
                "type": "string",
                "required": True,
                "enum": K.ROLE_IN_FAMILY,
            },
            {"name": "expected_account_version", "type": "integer", "required": True},
        ]
    )
    ctx.own(account["id"])
    ctx.write_gates(account)
    # Rung 17
    if fields["expected_account_version"] != account["version"]:
        raise ApiError("ERR_STALE_ACCOUNT_VERSION")
    roster = derive.account_members(account["id"])
    # Rung 38
    for m in roster:
        if m["status"] in ("INVITED", "ACTIVE") and m["email"] == fields["email"]:
            raise ApiError("ERR_DUPLICATE_MEMBER_EMAIL")
    # Rung 41 -- STRICT boundary.
    plan = DB.plans.get(account["plan_id"])
    occupied = len([m for m in roster if m["status"] in ("INVITED", "ACTIVE")])
    if occupied >= int(plan["max_members"]):
        raise ApiError("ERR_MEMBER_CAP_EXCEEDED")

    # Adjudication of friction 7: "exactly one PRIMARY per Account" is declared
    # in the entity table but no rung and no error code guards it, and PRD §3.1
    # says the document does not invent one. Reachability-maximising reading:
    # the constraint is NOT enforced here -- enforcing it would require minting
    # an error code the catalogue does not contain and would make the declared
    # `role_in_family: PRIMARY` invitation path unreachable. `is_primary` stays
    # false on the invited row, so account-owner identity resolution (rung 4)
    # is unaffected and every downstream behaviour remains reachable.
    member = rows.new_row(
        "members",
        {
            "account_id": account["id"],
            "email": fields["email"],
            "full_name": fields["full_name"],
            "role_in_family": fields["role_in_family"],
            "is_primary": False,
            "status": "INVITED",
            "authorization_status": "GRANTED",
            "invitation_token": ids.new_token("inv_"),
            "activated_at": None,
            "authorization_revoked_at": None,
        },
    )
    rows.touch(account)
    return envelope.created(serializers.member(member))


# --- add-ons ----------------------------------------------------------------

@bp.get("/accounts/<account_id>/addons")
def list_addons(account_id):
    ctx = Ctx(
        request,
        [K.ROLE_PLATFORM_ADMIN, K.ROLE_ACCOUNT_OWNER, K.ROLE_MEMBER, K.ROLE_AUDITOR],
    )
    account = ctx.path("account", account_id)
    status = context.enum_filter(request, "status", K.ADDON_STATUSES)
    limit, offset = context.pagination(request)
    ctx.own(account["id"])  # account-level read
    result = [
        a
        for a in derive.account_addons(account["id"])
        if status is None or a["status"] == status
    ]
    page, total = context.window(ordered(result), limit, offset)
    return envelope.listing([serializers.addon(a) for a in page], limit, offset, total)


@bp.post("/accounts/<account_id>/addons")
def buy_addon(account_id):
    ctx = Ctx(request, [K.ROLE_PLATFORM_ADMIN, K.ROLE_ACCOUNT_OWNER])
    account = ctx.path("account", account_id)
    ctx.load_body()
    fields = ctx.validate(
        [
            {"name": "addon_type", "type": "string", "required": True, "enum": K.ADDON_TYPES},
            {"name": "seats_total", "type": "integer", "required": True, "min": 1, "max": 20},
            {"name": "per_seat_fee_cents", "type": "integer", "required": True, "min": 0},
        ]
    )
    ctx.own(account["id"])
    ctx.write_gates(account)
    # Rung 24
    cycle = derive.open_cycle(account["id"])
    if cycle is None:
        raise ApiError("ERR_CYCLE_CLOSED")
    # Rung 39 -- uniqueness scoped to live rows.
    for a in derive.account_addons(account["id"]):
        if a["addon_type"] == fields["addon_type"] and a["status"] in ("ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_DUPLICATE_ADDON")

    inclusive_days = cascades.addon_inclusive_remaining_days(cycle)
    charge = calc.addon_charge(
        int(fields["per_seat_fee_cents"]), int(fields["seats_total"]), inclusive_days
    )
    addon = rows.new_row(
        "addons",
        {
            "account_id": account["id"],
            "addon_type": fields["addon_type"],
            "seats_total": fields["seats_total"],
            "per_seat_fee_cents": fields["per_seat_fee_cents"],
            "status": "ACTIVE",
            "suspended_at": None,
            "prorated_charge_cents": charge,
        },
    )
    cycle["addon_charge_cents"] = int(cycle["addon_charge_cents"]) + charge
    rows.touch(cycle)
    return envelope.created(serializers.addon(addon))


# --- billing cycles ---------------------------------------------------------

@bp.get("/accounts/<account_id>/billing-cycles")
def list_cycles(account_id):
    ctx = Ctx(request, [K.ROLE_PLATFORM_ADMIN, K.ROLE_ACCOUNT_OWNER, K.ROLE_AUDITOR])
    account = ctx.path("account", account_id)
    status = context.enum_filter(request, "status", K.CYCLE_STATUSES)
    limit, offset = context.pagination(request)
    ctx.own(account["id"])
    result = [
        c
        for c in derive.account_cycles(account["id"])
        if status is None or c["status"] == status
    ]
    # Ordered by cycle_seq ASC (PRD §2.3 deviation).
    result.sort(key=lambda c: (c["cycle_seq"], c["id"]))
    page, total = context.window(result, limit, offset)
    return envelope.listing([serializers.cycle(c) for c in page], limit, offset, total)


# --- derived: entitlement statement -----------------------------------------

@bp.get("/accounts/<account_id>/entitlement-statement")
def entitlement_statement(account_id):
    ctx = Ctx(request, [K.ROLE_PLATFORM_ADMIN, K.ROLE_ACCOUNT_OWNER, K.ROLE_AUDITOR])
    account = ctx.path("account", account_id)
    ctx.own(account["id"])
    cycle = derive.open_cycle(account["id"])
    pools = derive.pool_figures(account["id"])
    plan = DB.plans.get(account["plan_id"])
    eligible = [
        m
        for m in derive.account_members(account["id"])
        if m["status"] in ("INVITED", "ACTIVE")
    ]
    breakdown = []
    for m in eligible:
        net = derive.member_removal_net(m)
        breakdown.append(
            {
                "member_id": m["id"],
                "removal_units_consumed_this_cycle": net,
                "per_member_removal_subcap": int(plan["per_member_removal_subcap"]),
                "subcap_remaining": int(plan["per_member_removal_subcap"]) - net,
                "_created_at": m["created_at"],
                "_id": m["id"],
            }
        )
    breakdown.sort(
        key=lambda e: (-e["removal_units_consumed_this_cycle"], e["_created_at"], e["_id"])
    )
    for e in breakdown:
        e.pop("_created_at")
        e.pop("_id")
    data = {
        "account_id": account["id"],
        "cycle_id": cycle["id"] if cycle else None,
        "cycle_seq": cycle["cycle_seq"] if cycle else None,
    }
    for resource in ("profile", "scan", "removal"):
        figures = pools[resource]
        data[f"{resource}_granted"] = figures["granted"]
        data[f"{resource}_consumed"] = figures["consumed"]
        data[f"{resource}_released"] = figures["released"]
        data[f"{resource}_remaining"] = figures["remaining"]
    data["member_breakdown"] = breakdown
    return envelope.ok(data)
