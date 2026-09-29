"""Disclosure sections: the review loop, legal clearance and filing (PRD §3.6)."""

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

bp = Blueprint("cda", __name__)

SECTION_CODES = {"CD_AND_A", "SUMMARY_COMP_TABLE", "PAY_RATIO", "PVP_TABLE"}
NARRATIVE_WORD_FLOOR = 1500
SUBMITTABLE_PROGRAM_STATES = ("COMMITTEE_APPROVED", "DISCLOSED")


@bp.post("/exec-comp/pay-programs/<pid>/cda-drafts")
def open_section(pid):
    user_id, _ = authenticate([ROLE_COUNSEL, ROLE_COMP_CONSULTANT])
    program = fetch("pay_programs", pid)
    body = Body()
    section_code = body.enum("section_code", SECTION_CODES, required=True)
    word_count = body.integer("word_count", required=True, minimum=0)
    required_tables_included = body.boolean("required_tables_included", default=False)

    for existing in domain.program_drafts(program["id"]):
        if existing["section_code"] == section_code:
            raise ApiError("ERR_CDA_SECTION_ALREADY_EXISTS")

    draft = insert(
        store.cda_drafts,
        {
            "pay_program_id": program["id"],
            "section_code": section_code,
            "word_count": word_count,
            "required_tables_included": required_tables_included,
            "revision_round": 0,
            "authored_by_user_id": user_id,
            "cleared_by_user_id": None,
            "status": "DRAFTING",
            "filed_at": None,
        },
    )
    return object_response(draft, 201)


@bp.get("/exec-comp/pay-programs/<pid>/cda-drafts")
def list_sections(pid):
    authenticate([ROLE_COUNSEL, ROLE_COMP_CONSULTANT, ROLE_CHAIR, ROLE_IR_LEAD])
    program = fetch("pay_programs", pid)
    rows = domain.program_drafts(program["id"])
    section_code = request.args.get("section_code")
    if section_code is not None:
        rows = [r for r in rows if r["section_code"] == section_code]
    return paginated(rows)


@bp.post("/exec-comp/cda-drafts/<did>/submit-review")
def submit_review(did):
    user_id, _ = authenticate([ROLE_COUNSEL, ROLE_COMP_CONSULTANT])
    draft = fetch("cda_drafts", did)
    body = Body()
    word_count_supplied = body.present("word_count")
    word_count = body.integer("word_count", minimum=0)
    tables_supplied = body.present("required_tables_included")
    required_tables_included = body.boolean("required_tables_included")

    program = store.pay_programs[draft["pay_program_id"]]
    if program["design_status"] not in SUBMITTABLE_PROGRAM_STATES:
        raise ApiError("ERR_PROGRAM_NOT_MUTABLE")
    if draft["status"] != "DRAFTING":
        raise ApiError("ERR_CDA_STATE_INVALID")

    changes = {"status": "IN_REVIEW", "authored_by_user_id": user_id}
    if word_count_supplied:
        changes["word_count"] = word_count
    if tables_supplied:
        changes["required_tables_included"] = required_tables_included
    apply_changes(draft, changes)
    touch(draft)
    return object_response(draft)


@bp.post("/exec-comp/cda-drafts/<did>/request-revision")
def request_revision(did):
    authenticate([ROLE_COUNSEL, ROLE_CHAIR])
    draft = fetch("cda_drafts", did)
    body = Body()
    body.string("feedback_summary", max_len=2000)

    if draft["status"] not in ("IN_REVIEW", "FILED"):
        raise ApiError("ERR_CDA_STATE_INVALID")
    program = store.pay_programs[draft["pay_program_id"]]
    reopening = draft["status"] == "FILED"
    if reopening and program["vote_status"] != "NOT_VOTED":
        raise ApiError("ERR_VOTE_ALREADY_CERTIFIED")

    changes = {
        "status": "DRAFTING",
        "revision_round": draft["revision_round"] + 1,
        "cleared_by_user_id": None,
    }
    if reopening:
        changes["filed_at"] = None
    apply_changes(draft, changes)
    touch(draft)
    return object_response(draft)


@bp.post("/exec-comp/cda-drafts/<did>/legal-clear")
def legal_clear(did):
    user_id, _ = authenticate([ROLE_COUNSEL])
    draft = fetch("cda_drafts", did)
    if draft["authored_by_user_id"] is not None and (
        user_id == draft["authored_by_user_id"]
    ):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if draft["status"] != "IN_REVIEW":
        raise ApiError("ERR_CDA_STATE_INVALID")

    program = store.pay_programs[draft["pay_program_id"]]
    iss = next(
        (s for s in domain.program_screens(program["id"]) if s["advisor"] == "ISS"), None
    )
    if iss is None or iss["status"] != "SCREENED":
        raise ApiError("ERR_ISS_SCREEN_NOT_CURRENT")

    if not draft["required_tables_included"]:
        raise ApiError("ERR_CDA_TABLES_INCOMPLETE")
    if (
        draft["section_code"] == "CD_AND_A"
        and draft["word_count"] < NARRATIVE_WORD_FLOOR
    ):
        raise ApiError("ERR_CDA_TABLES_INCOMPLETE")

    apply_changes(
        draft, {"status": "LEGAL_CLEARED", "cleared_by_user_id": user_id}
    )
    touch(draft)
    return object_response(draft)


@bp.post("/exec-comp/cda-drafts/<did>/file")
def file_section(did):
    authenticate([ROLE_COUNSEL])
    draft = fetch("cda_drafts", did)
    if draft["status"] != "LEGAL_CLEARED":
        raise ApiError("ERR_CDA_STATE_INVALID")

    apply_changes(draft, {"status": "FILED", "filed_at": now()})
    touch(draft)
    if draft["section_code"] == "CD_AND_A":
        program = store.pay_programs[draft["pay_program_id"]]
        if program["design_status"] == "COMMITTEE_APPROVED":
            apply_changes(program, {"design_status": "DISCLOSED"})
            touch(program)
    return object_response(draft)
