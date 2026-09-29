"""Members, the membership state machine and the logical clock."""
from flask import Blueprint

import auth
import calc
import cascade
import clock
import db
import derive
import helpers
import response
import validate

bp = Blueprint("members", __name__)


# --------------------------------------------------------------------------- #
# Logical clock                                                               #
# --------------------------------------------------------------------------- #
@bp.post("/_clock/set_current_utc")
@auth.require("ClubAdmin")
def set_clock():
    data = validate.body()
    moment, _raw = validate.datetime_field(data, "to_iso8601")
    clock.set_now(moment)
    return response.ok({})


# --------------------------------------------------------------------------- #
# Members                                                                     #
# --------------------------------------------------------------------------- #
@bp.post("/members")
@auth.require("ClubAdmin")
def create_member():
    data = validate.body()
    full_name = validate.string(data, "full_name")
    tier = validate.enum(data, "tier", calc.TIERS)
    body_weight = validate.number(data, "body_weight_kg", one_dp=True)
    club_roles = validate.enum_array(data, "club_roles", calc.CLUB_ROLES, default=[])
    swim, swim_raw = validate.datetime_field(data, "swim_test_passed_on", required=False, nullable=True)
    cox, cox_raw = validate.datetime_field(data, "coxswain_cert_expires_at", required=False, nullable=True)
    coach, coach_raw = validate.datetime_field(data, "coach_cert_expires_at", required=False, nullable=True)
    launch, launch_raw = validate.datetime_field(data, "safety_launch_cert_expires_at", required=False, nullable=True)
    limit = validate.integer(data, "launch_supervision_limit", required=False, default=2,
                             minimum=1, maximum=4)

    member = db.base_record()
    member["full_name"] = full_name
    member["tier"] = tier
    member["club_roles"] = club_roles
    member["membership_status"] = "ACTIVE"
    member["body_weight_kg"] = body_weight
    db.set_dt(member, "swim_test_passed_on", swim, swim_raw)
    db.set_dt(member, "coxswain_cert_expires_at", cox, cox_raw)
    db.set_dt(member, "coach_cert_expires_at", coach, coach_raw)
    db.set_dt(member, "safety_launch_cert_expires_at", launch, launch_raw)
    member["launch_supervision_limit"] = limit
    db.members[member["id"]] = member
    return response.created(derive.member_out(member))


@bp.get("/members/<ident>")
@auth.require("ClubAdmin", "Member", "Coach", "SafetyOfficer", "EquipmentManager",
              "RaceOfficial", "JuryChair")
def get_member(ident):
    member = helpers.load("member", ident)
    return response.ok(derive.member_out(member))


@bp.get("/members")
@auth.require("ClubAdmin", "Coach", "SafetyOfficer", "RaceOfficial")
def list_members():
    wanted = response.filters("tier", "membership_status")
    rows = db.ordered(db.members, lambda m: response.matches(m, wanted))
    return response.paginate(rows, derive.member_out)


@bp.patch("/members/<ident>/certifications")
@auth.require("ClubAdmin")
def amend_certifications(ident):
    member = helpers.load("member", ident)
    data = validate.body()
    fields = ("swim_test_passed_on", "coxswain_cert_expires_at",
              "coach_cert_expires_at", "safety_launch_cert_expires_at")
    parsed = {}
    for field in fields:
        if field in data:
            parsed[field] = validate.datetime_field(data, field, required=False, nullable=True)
    limit = None
    if "launch_supervision_limit" in data:
        limit = validate.integer(data, "launch_supervision_limit", minimum=1, maximum=4)

    for field, (value, raw) in parsed.items():
        db.set_dt(member, field, value, raw)
    if limit is not None:
        member["launch_supervision_limit"] = limit
    db.touch(member)
    cascade.recompute_member_seats(member)
    return response.ok(derive.member_out(member))


@bp.post("/members/<ident>/status-transitions")
@auth.require("ClubAdmin")
def member_status_transition(ident):
    member = helpers.load("member", ident)
    data = validate.body()
    to_status = validate.enum(data, "to_status", calc.MEMBER_STATUSES)
    helpers.not_terminal("member", member, "membership_status")

    current = member["membership_status"]
    if to_status == "SUSPENDED" and current in ("ACTIVE", "DUES_HOLD"):
        if cascade.member_on_launched_session(member["id"]):
            helpers.invalid_transition("The member is currently on the water.")
        member["membership_status"] = "SUSPENDED"
        db.touch(member)
        cascade.cancel_sessions_for_member(member["id"])
    elif to_status == "ACTIVE" and current == "SUSPENDED":
        if derive.dues_balance_cents(member["id"]) != 0:
            helpers.invalid_transition("Outstanding dues must be settled first.")
        member["membership_status"] = "ACTIVE"
        db.touch(member)
    elif to_status == "WITHDRAWN" and current in ("ACTIVE", "SUSPENDED"):
        for seat in db.seats.values():
            if seat["member_id"] != member["id"]:
                continue
            entry = db.entries.get(seat["regatta_entry_id"])
            if entry is not None and entry["status"] in cascade.LIVE_ENTRY_STATUSES:
                helpers.invalid_transition("The member still holds an active lineup seat.")
        member["membership_status"] = "WITHDRAWN"
        db.touch(member)
    else:
        helpers.invalid_transition(
            "%s -> %s is not a declared member transition." % (current, to_status))
    return response.ok(derive.member_out(member))


@bp.get("/members/<ident>/dues-invoices")
@auth.require("ClubAdmin", "Member")
def list_member_invoices(ident):
    member = helpers.load("member", ident)
    wanted = response.filters("status")
    rows = db.ordered(db.invoices, lambda i: i["member_id"] == member["id"]
                      and response.matches(i, wanted))
    return response.paginate(rows, derive.invoice_out)
