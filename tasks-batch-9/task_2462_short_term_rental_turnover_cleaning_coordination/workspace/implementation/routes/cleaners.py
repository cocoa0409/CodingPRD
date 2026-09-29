"""Cleaner onboarding, employment changes and the pay-line reads."""

from flask import Blueprint

import errors
import validation as v
from db import base_fields, db, touch
from errors import fail
from middleware import authenticate
from response import created, ok, ok_list
from services import lookup
from services.cascade import holds_active_assignment, revoke_open_work
from services.listing import sort_default
from services.money import round_half_up
from services.pay import sync_cleaner
from services.serialize import cleaner_view, pay_line_view

bp = Blueprint("cleaners", __name__)

CLEANER_STATUSES = ("ACTIVE", "SUSPENDED", "OFFBOARDED")
CLEANER_ACTIONS = ("SUSPEND", "REACTIVATE", "OFFBOARD")
PAY_LINE_STATUSES = ("PROVISIONAL", "FINAL", "ADJUSTED", "VOIDED")


@bp.post("/cleaners")
def create_cleaner():
    authenticate(("PlatformAdmin",))
    body = v.json_body()
    name = v.req_string(body, "name", allow_empty=False)
    home_zone_code = v.req_string(body, "home_zone_code", allow_empty=False)
    skill_level = v.req_int(body, "skill_level", minimum=1, maximum=5)
    secondary = v.opt_string_list(body, "secondary_zone_codes", None, max_items=5)
    accepts_cross_zone = v.opt_bool(body, "accepts_cross_zone", False)
    max_daily_turnovers = v.opt_int(body, "max_daily_turnovers", 2, minimum=1, maximum=6)
    initial_quality_score = v.opt_decimal(body, "initial_quality_score", None,
                                          minimum=0, maximum=100)
    status = v.opt_enum(body, "status", CLEANER_STATUSES, "ACTIVE")

    if secondary is None:
        secondary = []
    if len(set(secondary)) != len(secondary):
        fail(errors.ERR_INVALID_REQUEST, "Field 'secondary_zone_codes' may not repeat a token.")
    if home_zone_code in secondary:
        fail(errors.ERR_INVALID_REQUEST,
             "Field 'secondary_zone_codes' may not contain home_zone_code.")

    quality_score = (round_half_up(initial_quality_score, 2)
                     if initial_quality_score is not None
                     else round_half_up("80.00", 2))

    record = base_fields()
    record.update({
        "name": name,
        "home_zone_code": home_zone_code,
        "secondary_zone_codes": list(secondary),
        "accepts_cross_zone": accepts_cross_zone,
        "skill_level": skill_level,
        "max_daily_turnovers": max_daily_turnovers,
        "quality_score": quality_score,
        "status": status,
        "pending_payout_cents": 0,
        "completed_turnover_count": 0,
        "decline_count": 0,
        "strike_count": 0,
    })
    db.cleaners[record["id"]] = record
    return created(cleaner_view(record))


@bp.get("/cleaners/<cleaner_id>")
def read_cleaner(cleaner_id):
    authenticate(("PlatformAdmin", "Coordinator", "QualityAuditor"))
    return ok(cleaner_view(lookup.get_cleaner(cleaner_id)))


@bp.post("/cleaners/<cleaner_id>/status")
def change_cleaner_status(cleaner_id):
    authenticate(("PlatformAdmin",))
    body = v.json_body()
    action = v.req_enum(body, "action", CLEANER_ACTIONS)
    v.opt_string(body, "reason")

    cleaner = lookup.get_cleaner(cleaner_id)

    if action == "SUSPEND":
        if cleaner["status"] != "ACTIVE":
            fail(errors.ERR_INVALID_CLEANER_STATE,
                 "Only an ACTIVE cleaner may be suspended.")
        cleaner["status"] = "SUSPENDED"
        revoke_open_work(cleaner)
    elif action == "REACTIVATE":
        if cleaner["status"] != "SUSPENDED":
            fail(errors.ERR_INVALID_CLEANER_STATE,
                 "Only a SUSPENDED cleaner may be reactivated.")
        cleaner["status"] = "ACTIVE"
    else:
        if cleaner["status"] not in ("ACTIVE", "SUSPENDED"):
            fail(errors.ERR_INVALID_CLEANER_STATE,
                 "This cleaner may not be offboarded from its current status.")
        if holds_active_assignment(cleaner):
            fail(errors.ERR_INVALID_CLEANER_STATE,
                 "A cleaner holding an ACTIVE assignment may not be offboarded.")
        was_active = cleaner["status"] == "ACTIVE"
        cleaner["status"] = "OFFBOARDED"
        if was_active:
            # Offboarding from SUSPENDED performs no further cascade: suspension
            # already revoked the open offers (PRD 3.10).
            revoke_open_work(cleaner)

    sync_cleaner(cleaner, force=True)
    return ok(cleaner_view(cleaner))


@bp.get("/pay-lines")
def list_pay_lines():
    actor = authenticate(("PlatformAdmin", "Coordinator", "Cleaner"))
    limit, offset = v.pagination()
    assignment_id = v.query_string("assignment_id")
    cleaner_id = v.query_string("cleaner_id")
    turnover_id = v.query_string("turnover_id")
    status = v.query_enum("status", PAY_LINE_STATUSES)

    if actor.is_cleaner and cleaner_id != actor.user_id:
        fail(errors.ERR_UNAUTHORIZED,
             "A Cleaner must pass its own id as the cleaner_id filter.")

    rows = list(db.pay_lines.values())
    if assignment_id is not None:
        rows = [p for p in rows if p["assignment_id"] == assignment_id]
    if cleaner_id is not None:
        rows = [p for p in rows if p["cleaner_id"] == cleaner_id]
    if turnover_id is not None:
        rows = [p for p in rows if p["turnover_id"] == turnover_id]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    rows = sort_default(rows)
    page, total = v.paginate(rows, limit, offset)
    return ok_list([pay_line_view(r) for r in page], limit, offset, total)


@bp.get("/pay-lines/<pay_line_id>")
def read_pay_line(pay_line_id):
    actor = authenticate(("PlatformAdmin", "Coordinator", "Cleaner"))
    pay_line = lookup.get_pay_line(pay_line_id)
    if actor.is_cleaner and pay_line["cleaner_id"] != actor.user_id:
        fail(errors.ERR_UNAUTHORIZED,
             "A Cleaner may only read its own pay lines.")
    return ok(pay_line_view(pay_line))
