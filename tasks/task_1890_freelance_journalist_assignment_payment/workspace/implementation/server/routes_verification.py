"""Verification report endpoints."""

from flask import request

from . import calc
from .auth import require
from .blueprint import bp
from .cascade import reject_after_flag
from .envelope import ok_list, ok_obj
from .errors import ApiError, invalid_state, not_found
from .serialize import ser_verification_report
from .store import STORE, touch
from .util import body, paged, pagination_params, req_int, sort_created
from .util import bad_request

READ_ROLES = ["DeskAdmin", "Editor", "VerificationEditor", "FinanceUser"]
OUTCOMES = ("DISMISSED", "CONFIRMED_VIOLATION")


@bp.get("/freelance-desk/assignments/<aid>/verification-reports")
def list_verification_reports(aid):
    require(READ_ROLES)
    if aid not in STORE.assignments:
        not_found("Assignment")
    items = calc.reports_of(aid)
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    kind = request.args.get("checker_kind")
    if kind:
        items = [r for r in items if r["checker_kind"] == kind]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_verification_report(r) for r in page], limit, offset, total)


@bp.get("/freelance-desk/verification-reports/<rid>")
def get_verification_report(rid):
    require(READ_ROLES)
    r = STORE.verification_reports.get(rid)
    if r is None:
        not_found("VerificationReport")
    return ok_obj(ser_verification_report(r))


@bp.post("/freelance-desk/verification-reports/<rid>/record-result")
def record_result(rid):
    uid, role = require(["VerificationEditor"])
    r = STORE.verification_reports.get(rid)
    if r is None:
        not_found("VerificationReport")
    if r["status"] != "PENDING":
        invalid_state("Only a PENDING report can have results recorded")
    b = body()
    sim = req_int(b, "similarity_score_bps")
    if not (0 <= sim <= 10000):
        bad_request("similarity_score_bps must be within 0..10000")
    ai = req_int(b, "ai_probability_bps")
    if not (0 <= ai <= 10000):
        bad_request("ai_probability_bps must be within 0..10000")

    r["similarity_score_bps"] = sim
    r["ai_probability_bps"] = ai
    if r["checker_kind"] == "PLAGIARISM":
        flagged = sim >= calc.cfg("flag_threshold_bps")
    else:
        flagged = ai >= calc.cfg("ai_flag_threshold_bps")
    r["status"] = "FLAGGED" if flagged else "CLEARED"
    r["_recorded_by"] = uid
    touch(r)

    assignment = STORE.assignments.get(r["assignment_id"])
    if assignment is not None:
        calc.sync_verification_cleared(assignment)
    return ok_obj(ser_verification_report(r))


@bp.post("/freelance-desk/verification-reports/<rid>/adjudicate")
def adjudicate(rid):
    uid, role = require(["VerificationEditor"])
    r = STORE.verification_reports.get(rid)
    if r is None:
        not_found("VerificationReport")
    if r["status"] != "FLAGGED":
        invalid_state("Only a FLAGGED report can be adjudicated")
    # Segregation of duties (priority 7) precedes body shape checks (priority 15)
    if r.get("_recorded_by") is not None and uid == r["_recorded_by"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "The VerificationEditor who recorded the flag may not adjudicate it",
        )
    b = body()
    outcome = b.get("outcome")
    if outcome not in OUTCOMES:
        bad_request("outcome must be DISMISSED or CONFIRMED_VIOLATION")
    note = b.get("adjudication_note")
    if not isinstance(note, str) or not note:
        bad_request("adjudication_note must be non-empty")

    r["adjudication_note"] = note
    r["status"] = outcome
    touch(r)

    assignment = STORE.assignments.get(r["assignment_id"])
    if assignment is not None:
        if outcome == "DISMISSED":
            calc.sync_verification_cleared(assignment)
        else:
            reject_after_flag(assignment)
    return ok_obj(ser_verification_report(r))
