"""Proxy-advisor screens: the two methodologies and the re-run refresh (PRD §3.6)."""

from flask import Blueprint, request

from db import apply_changes, insert, now, store, touch
from errors import ApiError
from middleware import (
    ROLE_CHAIR,
    ROLE_COMP_CONSULTANT,
    ROLE_COUNSEL,
    ROLE_IR_LEAD,
    authenticate,
)
from response import object_response
from routes.common import fetch, paginated
from services import domain
from validation import Body

bp = Blueprint("screens", __name__)

ADVISORS = {"ISS", "GLASS_LEWIS"}


@bp.post("/exec-comp/pay-programs/<pid>/proxy-advisor-screens")
def create_screen(pid):
    authenticate([ROLE_IR_LEAD, ROLE_COMP_CONSULTANT])
    program = fetch("pay_programs", pid)
    body = Body()
    advisor = body.enum("advisor", ADVISORS, required=True)

    for existing in domain.program_screens(program["id"]):
        if existing["advisor"] == advisor:
            raise ApiError("ERR_SCREEN_ALREADY_EXISTS")

    values = domain.screen_values(program, advisor)
    screen = insert(
        store.proxy_advisor_screens,
        {
            "pay_program_id": program["id"],
            "advisor": advisor,
            "alignment_component": values["alignment_component"],
            "mix_component": values["mix_component"],
            "rigor_component": values["rigor_component"],
            "outreach_component": values["outreach_component"],
            "concern_score": values["concern_score"],
            "concern_level": values["concern_level"],
            "recommendation": values["recommendation"],
            "status": "SCREENED",
            "screened_at": now(),
        },
    )
    return object_response(screen, 201)


@bp.get("/exec-comp/pay-programs/<pid>/proxy-advisor-screens")
def list_screens(pid):
    authenticate([ROLE_IR_LEAD, ROLE_COMP_CONSULTANT, ROLE_CHAIR, ROLE_COUNSEL])
    program = fetch("pay_programs", pid)
    rows = domain.program_screens(program["id"])
    advisor = request.args.get("advisor")
    if advisor is not None:
        rows = [r for r in rows if r["advisor"] == advisor]
    return paginated(rows)


@bp.post("/exec-comp/proxy-advisor-screens/<sid>/rerun")
def rerun_screen(sid):
    authenticate([ROLE_IR_LEAD, ROLE_COMP_CONSULTANT])
    screen = fetch("proxy_advisor_screens", sid)
    program = store.pay_programs[screen["pay_program_id"]]
    values = dict(domain.screen_values(program, screen["advisor"]))
    values["status"] = "SCREENED"
    values["screened_at"] = now()
    apply_changes(screen, values)
    touch(screen)
    return object_response(screen)
