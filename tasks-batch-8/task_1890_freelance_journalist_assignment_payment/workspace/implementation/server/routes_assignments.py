"""Assignment endpoints: editorial pipeline with parallel payment dimension."""

from flask import request

from . import calc
from .auth import ALL_ROLES, require, require_owner
from .blueprint import bp
from .envelope import ok_list, ok_obj
from .errors import ApiError, bad_request, invalid_state, not_found
from .serialize import ser_assignment
from .store import STORE, new_entity, now, touch
from .util import (
    body,
    opt_str,
    paged,
    pagination_params,
    req_dt,
    req_int,
    req_str,
    sort_created,
)

READ_ROLES = ["DeskAdmin", "Editor", "FinanceUser", "VerificationEditor", "Contributor"]


def get_assignment_or_404(aid):
    a = STORE.assignments.get(aid)
    if a is None:
        not_found("Assignment")
    return a


def _check_read_ownership(uid, role, assignment):
    if role == "Contributor":
        require_owner(uid, assignment["contributor_id"])


@bp.post("/freelance-desk/assignments")
def create_assignment():
    require(["Editor"])
    b = body()
    contributor_id = opt_str(b, "contributor_id")
    # Body-referenced FK resolves before remaining shape checks (existence precedes shape).
    if contributor_id is not None and contributor_id not in STORE.contributors:
        not_found("Contributor")
    if contributor_id is None:
        bad_request("contributor_id is required")
    title = req_str(b, "title")
    brief = req_str(b, "brief")
    cwc = req_int(b, "commissioned_word_count")
    if cwc < 100:
        bad_request("commissioned_word_count must be >= 100")
    deadline = req_dt(b, "deadline_utc")

    e = new_entity()
    e.update({
        "contributor_id": contributor_id,
        "rate_agreement_id": None,
        "title": title,
        "brief": brief,
        "commissioned_word_count": cwc,
        "final_word_count": None,
        "deadline_utc": deadline,
        "editorial_status": "DRAFT",
        "payment_status": "UNINVOICED",
        "kill_fee_tier": None,
        "agreed_fee_cents": 0,
        "final_fee_cents": None,
        "verification_cleared": False,
        "late_flag": False,
    })
    STORE.assignments[e["id"]] = e
    return ok_obj(ser_assignment(e), 201)


@bp.get("/freelance-desk/assignments")
def list_assignments():
    uid, role = require(READ_ROLES)
    items = list(STORE.assignments.values())
    if role == "Contributor":
        items = [a for a in items if a["contributor_id"] == uid]
    f = request.args.get("contributor_id")
    if f:
        items = [a for a in items if a["contributor_id"] == f]
    f = request.args.get("rate_agreement_id")
    if f:
        items = [a for a in items if a["rate_agreement_id"] == f]
    f = request.args.get("editorial_status")
    if f:
        items = [a for a in items if a["editorial_status"] == f]
    f = request.args.get("payment_status")
    if f:
        items = [a for a in items if a["payment_status"] == f]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_assignment(a) for a in page], limit, offset, total)


@bp.get("/freelance-desk/assignments/<aid>")
def get_assignment(aid):
    uid, role = require(READ_ROLES)
    a = get_assignment_or_404(aid)
    _check_read_ownership(uid, role, a)
    return ok_obj(ser_assignment(a))


@bp.post("/freelance-desk/assignments/<aid>/offer")
def offer_assignment(aid):
    require(["Editor"])
    a = get_assignment_or_404(aid)
    if a["editorial_status"] != "DRAFT":
        invalid_state("Only a DRAFT assignment can be offered")
    c = STORE.contributors.get(a["contributor_id"])
    if c is None or c["status"] != "ACTIVE":
        invalid_state("Assignments may only be offered to an ACTIVE contributor")
    n = now()
    agreement = None
    for r in STORE.rate_agreements.values():
        if (
            r["contributor_id"] == c["id"]
            and r["status"] == "ACTIVE"
            and r["effective_from"] <= n
            and (r["effective_to"] is None or n < r["effective_to"])
        ):
            agreement = r
            break
    if agreement is None:
        raise ApiError(
            "ERR_NO_ACTIVE_RATE_AGREEMENT",
            422,
            "No ACTIVE rate agreement covers the current time",
        )

    a["rate_agreement_id"] = agreement["id"]
    if agreement["pricing_mode"] == "PER_WORD":
        a["agreed_fee_cents"] = a["commissioned_word_count"] * agreement["per_word_rate_cents"]
    else:
        a["agreed_fee_cents"] = agreement["flat_fee_cents"]

    rp = new_entity()
    rp.update({
        "assignment_id": a["id"],
        "rights_kind": agreement["rights_default"],
        "reuse_count": 0,
        "reuse_fee_cents_total": 0,
        "buyout_uplift_cents": 0,
        "status": "ACTIVE",
    })
    STORE.rights_purchases[rp["id"]] = rp

    a["editorial_status"] = "OFFERED"
    touch(a)
    return ok_obj(ser_assignment(a))


@bp.post("/freelance-desk/assignments/<aid>/accept")
def accept_assignment(aid):
    uid, role = require(["Contributor"])
    a = get_assignment_or_404(aid)
    if a["editorial_status"] != "OFFERED":
        invalid_state("Only an OFFERED assignment can be accepted")
    require_owner(uid, a["contributor_id"])
    a["editorial_status"] = "ACCEPTED"
    touch(a)
    return ok_obj(ser_assignment(a))


@bp.post("/freelance-desk/assignments/<aid>/start")
def start_assignment(aid):
    uid, role = require(["Contributor"])
    a = get_assignment_or_404(aid)
    if a["editorial_status"] != "ACCEPTED":
        invalid_state("Only an ACCEPTED assignment can be started")
    require_owner(uid, a["contributor_id"])
    a["editorial_status"] = "IN_PROGRESS"
    touch(a)
    return ok_obj(ser_assignment(a))


@bp.post("/freelance-desk/assignments/<aid>/submit")
def submit_assignment(aid):
    uid, role = require(["Contributor"])
    a = get_assignment_or_404(aid)
    if a["editorial_status"] != "IN_PROGRESS":
        invalid_state("Only an IN_PROGRESS assignment can be submitted")
    require_owner(uid, a["contributor_id"])
    a["late_flag"] = now() > a["deadline_utc"]
    # SUBMITTED -> UNDER_VERIFICATION auto-transition; pinned report order:
    # index 0 PLAGIARISM, index 1 AI_CONTENT, both PENDING.
    for kind in ("PLAGIARISM", "AI_CONTENT"):
        r = new_entity()
        r.update({
            "assignment_id": a["id"],
            "checker_kind": kind,
            "similarity_score_bps": 0,
            "ai_probability_bps": 0,
            "status": "PENDING",
            "adjudication_note": "",
            "_recorded_by": None,
        })
        STORE.verification_reports[r["id"]] = r
    a["editorial_status"] = "UNDER_VERIFICATION"
    touch(a)
    return ok_obj(ser_assignment(a))


@bp.post("/freelance-desk/assignments/<aid>/kill")
def kill_assignment(aid):
    require(["Editor"])
    a = get_assignment_or_404(aid)
    if a["editorial_status"] in ("OFFERED", "ACCEPTED", "IN_PROGRESS"):
        a["editorial_status"] = "KILLED"
        a["kill_fee_tier"] = "PRE_DELIVERY"
        a["final_fee_cents"] = calc.fee_kill(a)
    elif a["editorial_status"] == "UNDER_VERIFICATION":
        a["editorial_status"] = "KILLED"
        a["kill_fee_tier"] = "POST_DELIVERY"
        a["final_fee_cents"] = calc.fee_kill(a)
        # verification_cleared stays false unless every report is already CLEARED/DISMISSED
        reports = calc.reports_of(a["id"])
        a["verification_cleared"] = bool(reports) and all(
            r["status"] in ("CLEARED", "DISMISSED") for r in reports
        )
    else:
        invalid_state(f"Assignment in {a['editorial_status']} cannot be killed")
    touch(a)
    return ok_obj(ser_assignment(a))


@bp.post("/freelance-desk/assignments/<aid>/accept-for-publication")
def accept_for_publication(aid):
    require(["Editor"])
    a = get_assignment_or_404(aid)
    if a["editorial_status"] != "UNDER_VERIFICATION":
        invalid_state("Only an UNDER_VERIFICATION assignment can be accepted for publication")
    reports = calc.reports_of(a["id"])
    if not all(r["status"] in ("CLEARED", "DISMISSED") for r in reports):
        invalid_state("All verification reports must be CLEARED or DISMISSED before acceptance")
    b = body()
    fwc = req_int(b, "final_word_count")
    if fwc < 0:
        bad_request("final_word_count must be >= 0")

    a["final_word_count"] = fwc
    agreement = STORE.rate_agreements.get(a["rate_agreement_id"])
    a["final_fee_cents"] = calc.fee_accepted(a, agreement)
    a["verification_cleared"] = True
    a["editorial_status"] = "ACCEPTED_FOR_PUBLICATION"
    touch(a)

    for rp in STORE.rights_purchases.values():
        if rp["assignment_id"] == a["id"] and rp["status"] == "ACTIVE":
            if rp["rights_kind"] == "ALL":
                rp["buyout_uplift_cents"] = calc.rights_uplift(a["final_fee_cents"])
                touch(rp)
            break
    return ok_obj(ser_assignment(a))
