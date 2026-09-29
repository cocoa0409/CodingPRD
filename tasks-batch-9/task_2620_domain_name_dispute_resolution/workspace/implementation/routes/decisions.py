"""Deliberation, issuance, publication, court challenges and execution."""

from flask import Blueprint, request

import db
import response
import validate as v
from errors import ApiError
from middleware import auth, body
from services import calc, logic

bp = Blueprint("decisions", __name__)

DRAFT_CASE_STATUSES = ("PANEL_APPOINTMENT", "PANEL_CONSTITUTED")
DRAFTING_SEATS = {1: "SOLE", 3: "PRESIDING"}


def _case_decisions(case_id):
    return db.ordered(db.decisions, lambda r: r["case_id"] == case_id)


def _decision_votes(decision_id):
    return db.ordered(db.votes, lambda r: r["decision_id"] == decision_id)


# ------------------------------------------------------------------- drafting
@bp.post("/udrp/cases/<case_id>/decisions")
def open_draft(case_id):
    auth("CaseManager")
    case = logic.case_or_404(case_id)
    payload = body()
    if v.present(payload, "drafted_by_panelist_id"):
        logic.resource_or_404(db.panelists, payload["drafted_by_panelist_id"])
    expected_version = v.req_int(payload, "expected_case_version", 0)
    drafter_id = v.req_str(payload, "drafted_by_panelist_id")
    draft_summary = v.req_str(payload, "draft_summary", 10, 8000)
    drafting_seat = DRAFTING_SEATS[case["required_seat_count"]]
    holds_drafting_seat = any(
        r["panelist_id"] == drafter_id and r["seat"] == drafting_seat
        for r in logic.accepted_seats(case_id))
    if not holds_drafting_seat:
        v.bad("drafted_by_panelist_id must hold the %s seat in ACCEPTED on this "
              "case." % drafting_seat)
    if case["status"] not in DRAFT_CASE_STATUSES:
        raise ApiError("ERR_INVALID_CASE_STATE")
    if expected_version != case["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION")

    row = db.base_row(
        case_id=case_id,
        drafted_by_panelist_id=drafter_id,
        draft_summary=draft_summary,
        status="DRAFT",
        publication_status="UNPUBLISHED",
        outcome=None,
        outcome_basis=None,
        rdnh_finding=False,
        dissent_present=False,
        transfer_votes=0,
        cancellation_votes=0,
        deny_votes=0,
        issued_at=None,
        implementation_deadline_at=None,
        implemented_at=None,
        voided_at=None,
    )
    db.decisions[row["id"]] = row
    db.touch(case)
    return response.ok(db.public(row), 201)


@bp.get("/udrp/cases/<case_id>/decisions")
def list_case_decisions(case_id):
    auth("ProviderAdmin", "CaseManager", "Complainant", "Respondent", "Panelist")
    logic.case_or_404(case_id)
    limit, offset = v.pagination(request.args)
    window, total = response.paginate(_case_decisions(case_id), limit, offset)
    return response.ok_list([db.public(r) for r in window], limit, offset, total)


@bp.get("/udrp/decisions/<decision_id>")
def read_decision(decision_id):
    auth("ProviderAdmin", "CaseManager", "Complainant", "Respondent", "Panelist",
         "RegistrarAgent")
    return response.ok(db.public(logic.decision_or_404(decision_id)))


# --------------------------------------------------------------------- ballots
@bp.post("/udrp/decisions/<decision_id>/votes")
def cast_vote(decision_id):
    user_id, _ = auth("Panelist")
    decision = logic.decision_or_404(decision_id)
    case = logic.case_or_404(decision["case_id"])
    payload = body()
    seat_claimed = payload.get("seat")
    held = next((r for r in logic.accepted_seats(case["id"])
                 if r["panelist_id"] == user_id), None)
    if held is None:
        raise ApiError("ERR_NOT_SEAT_HOLDER")
    if isinstance(seat_claimed, str) and seat_claimed != held["seat"]:
        raise ApiError("ERR_NOT_SEAT_HOLDER")
    seat = v.req_enum(payload, "seat", ("SOLE", "PRESIDING", "CO_PANELIST_1",
                                       "CO_PANELIST_2"))
    vote = v.req_enum(payload, "vote", ("TRANSFER", "CANCELLATION", "DENY"))
    rdnh_vote = v.opt_bool(payload, "rdnh_vote", False)
    rationale = v.opt_str(payload, "rationale", 1, 4000)
    if decision["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_DECISION_STATE")
    if any(r["seat"] == seat for r in _decision_votes(decision_id)):
        raise ApiError("ERR_VOTE_ALREADY_CAST")

    row = db.event_row(
        decision_id=decision_id,
        seat=seat,
        voter_panelist_id=held["panelist_id"],
        vote=vote,
        rdnh_vote=rdnh_vote,
        rationale=rationale,
        cast_at=db.now_str(),
    )
    db.votes[row["id"]] = row
    return response.ok(db.public(row), 201)


@bp.get("/udrp/decisions/<decision_id>/votes")
def list_votes(decision_id):
    auth("ProviderAdmin", "CaseManager", "Panelist")
    logic.decision_or_404(decision_id)
    limit, offset = v.pagination(request.args)
    window, total = response.paginate(_decision_votes(decision_id), limit, offset)
    return response.ok_list([db.public(r) for r in window], limit, offset, total)


# -------------------------------------------------------------------- issuance
@bp.post("/udrp/decisions/<decision_id>/issue")
def issue_decision(decision_id):
    auth("CaseManager")
    decision = logic.decision_or_404(decision_id)
    case = logic.case_or_404(decision["case_id"])
    body()
    if decision["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_DECISION_STATE")
    if case["status"] not in DRAFT_CASE_STATUSES:
        raise ApiError("ERR_INVALID_CASE_STATE")
    if case["status"] != "PANEL_CONSTITUTED" or not logic.panel_fully_constituted(case):
        raise ApiError("ERR_PANEL_NOT_CONSTITUTED")
    ballots = _decision_votes(decision_id)
    if len(ballots) != case["required_seat_count"]:
        raise ApiError("ERR_VOTES_INCOMPLETE")

    issued_at = db.now()
    tally = calc.panel_outcome_tally(ballots, case["required_seat_count"])
    decision.update(tally)
    decision["status"] = "ISSUED"
    decision["issued_at"] = db.fmt(issued_at)
    decision["implementation_deadline_at"] = db.fmt(
        calc.implementation_deadline(issued_at))
    db.touch(decision)
    case["status"] = "IMPLEMENTATION_WAITING"
    db.touch(case)
    if tally["rdnh_finding"]:
        complainant = db.complainants.get(case["complainant_id"])
        if complainant is not None:
            complainant["adverse_rdnh_findings"] += 1
            db.touch(complainant)
    return response.ok(db.public(decision))


# ----------------------------------------------------------------- publication
@bp.post("/udrp/decisions/<decision_id>/publish")
def publish_decision(decision_id):
    auth("ProviderAdmin")
    decision = logic.decision_or_404(decision_id)
    case = logic.case_or_404(decision["case_id"])
    payload = body()
    redaction = v.req_enum(payload, "redaction_level",
                           ("NONE", "PARTY_NAMES", "FULL"))
    tags = v.req_str_list(payload, "precedent_tags", 1, 10, distinct=False)
    for tag in tags:
        if tag != tag.lower():
            v.bad("precedent_tags must be lowercase.")
    v.opt_str(payload, "digest_text", 1, 4000)
    if decision["status"] == "DRAFT":
        raise ApiError("ERR_INVALID_DECISION_STATE")
    if decision["publication_status"] != "UNPUBLISHED":
        raise ApiError("ERR_ALREADY_PUBLISHED")

    # The stored digest is always assembled by the server, never taken from input.
    # rdnh_finding is a boolean and renders in this API's own wire vocabulary,
    # so it reads "true"/"false" rather than any host-language spelling.
    digest = "%s | %s | rdnh=%s" % (case["case_number"], decision["outcome"],
                                    "true" if decision["rdnh_finding"] else "false")
    entry = db.base_row(
        decision_id=decision_id,
        published_at=db.now_str(),
        redaction_level=redaction,
        precedent_tags=tags,
        digest_text=digest,
        citation_count=0,
        precedent_weight=0.0,
        citable=redaction != "FULL",
        superseded=False,
    )
    db.precedents[entry["id"]] = entry
    decision["publication_status"] = "PUBLISHED" if redaction == "NONE" else "REDACTED"
    db.touch(decision)
    return response.ok(logic.precedent_view(entry), 201)


@bp.get("/udrp/decisions/<decision_id>/precedent-entry")
def read_precedent_entry(decision_id):
    auth("ProviderAdmin", "CaseManager", "Complainant", "Respondent", "Panelist")
    logic.decision_or_404(decision_id)
    limit, offset = v.pagination(request.args)
    entry = logic.entry_for_decision(decision_id)
    rows = [entry] if entry is not None else []
    window, total = response.paginate(rows, limit, offset)
    return response.ok_list([logic.precedent_view(r) for r in window],
                            limit, offset, total)


@bp.get("/udrp/precedents")
def search_precedents():
    auth("ProviderAdmin", "CaseManager", "Complainant", "Respondent", "Panelist")
    limit, offset = v.pagination(request.args)
    outcome = v.query_enum(request.args, "outcome",
                           ("TRANSFER", "CANCELLATION", "COMPLAINT_DENIED"))
    citable = v.query_bool(request.args, "citable")
    include_superseded = v.query_bool(request.args, "include_superseded", False)
    views = []
    for entry in db.ordered(db.precedents):
        # A FULL redaction is never citable and never listed, whatever the filters.
        if entry["redaction_level"] == "FULL":
            continue
        view = logic.precedent_view(entry)
        if not include_superseded and view["superseded"]:
            continue
        if citable is not None and view["citable"] != citable:
            continue
        if outcome is not None:
            decision = db.decisions.get(entry["decision_id"])
            if decision is None or decision["outcome"] != outcome:
                continue
        views.append(view)
    window, total = response.paginate(views, limit, offset)
    return response.ok_list(window, limit, offset, total)


# ------------------------------------------------------------ court challenges
def _decision_challenges(decision_id):
    return db.ordered(db.challenges, lambda r: r["decision_id"] == decision_id)


@bp.post("/udrp/decisions/<decision_id>/court-challenges")
def file_challenge(decision_id):
    user_id, role = auth("Complainant", "Respondent")
    decision = logic.decision_or_404(decision_id)
    case = logic.case_or_404(decision["case_id"])
    payload = body()
    logic.ensure_case_owner(case, user_id, role)
    if role == "Respondent" and isinstance(payload.get("respondent_email"), str):
        logic.ensure_respondent_identity(case, payload["respondent_email"])
    jurisdiction = v.req_country(payload, "jurisdiction")
    docket_number = v.req_str(payload, "docket_number", 1, 128)
    filed_by = v.req_enum(payload, "filed_by", ("COMPLAINANT", "RESPONDENT"))
    if role == "Respondent":
        v.req_str(payload, "respondent_email", 1, 320)
    if decision["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_DECISION_STATE")
    deadline = decision.get("implementation_deadline_at")
    if deadline is not None and db.now() > db.parse_dt(deadline):
        raise ApiError("ERR_CHALLENGE_WINDOW_CLOSED")

    row = db.base_row(
        decision_id=decision_id,
        jurisdiction=jurisdiction,
        docket_number=docket_number,
        filed_by=filed_by,
        filed_at=db.now_str(),
        status="FILED",
        resolved_at=None,
        resolution_note=None,
    )
    db.challenges[row["id"]] = row
    decision["status"] = "STAYED"
    db.touch(decision)
    if case["status"] == "IMPLEMENTATION_WAITING":
        case["status"] = "STAYED"
    db.touch(case)
    return response.ok(db.public(row), 201)


@bp.get("/udrp/decisions/<decision_id>/court-challenges")
def list_challenges(decision_id):
    auth("ProviderAdmin", "CaseManager", "Complainant", "Respondent")
    logic.decision_or_404(decision_id)
    limit, offset = v.pagination(request.args)
    window, total = response.paginate(_decision_challenges(decision_id), limit, offset)
    return response.ok_list([db.public(r) for r in window], limit, offset, total)


@bp.post("/udrp/court-challenges/<challenge_id>/resolve")
def resolve_challenge(challenge_id):
    auth("ProviderAdmin")
    challenge = logic.resource_or_404(db.challenges, challenge_id)
    decision = db.decisions.get(challenge["decision_id"])
    case = db.cases.get(decision["case_id"]) if decision else None
    payload = body()
    outcome = v.req_enum(payload, "outcome",
                         ("DISMISSED", "WITHDRAWN", "SUSTAINED"))
    note = v.opt_str(payload, "resolution_note", 1, 4000)
    if challenge["status"] != "FILED":
        raise ApiError("ERR_INVALID_CASE_STATE")

    resolved_at = db.now()
    challenge["status"] = outcome
    challenge["resolved_at"] = db.fmt(resolved_at)
    challenge["resolution_note"] = note
    db.touch(challenge)

    if outcome in ("DISMISSED", "WITHDRAWN"):
        # The waiting period restarts in full from resolved_at.
        decision["status"] = "ISSUED"
        decision["implementation_deadline_at"] = db.fmt(
            calc.implementation_deadline(resolved_at))
        db.touch(decision)
        case["status"] = "IMPLEMENTATION_WAITING"
        db.touch(case)
        return response.ok(db.public(challenge))

    decision["status"] = "VOIDED"
    decision["voided_at"] = db.fmt(resolved_at)
    db.touch(decision)
    if decision["rdnh_finding"]:
        complainant = db.complainants.get(case["complainant_id"])
        if complainant is not None:
            complainant["adverse_rdnh_findings"] -= 1
            db.touch(complainant)
    entry = logic.entry_for_decision(decision["id"])
    if entry is not None and not entry["superseded"]:
        entry["superseded"] = True
        entry["citable"] = False
        db.touch(entry)
    logic.close_case(case, "TERMINATED_COURT", discharge=True)
    return response.ok(db.public(challenge))


# ------------------------------------------------------------------ execution
@bp.post("/udrp/decisions/<decision_id>/implement")
def implement_decision(decision_id):
    user_id, _ = auth("RegistrarAgent")
    decision = logic.decision_or_404(decision_id)
    case = logic.case_or_404(decision["case_id"])
    logic.ensure_registrar_of_record(case, user_id)
    payload = body()
    v.opt_str(payload, "registrar_action_reference", 1, 255)
    if decision["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_DECISION_STATE")
    if case["status"] != "IMPLEMENTATION_WAITING":
        raise ApiError("ERR_INVALID_CASE_STATE")
    domain = logic.case_domain(case)
    if domain["lock_status"] != "LOCKED":
        raise ApiError("ERR_DOMAIN_NOT_LOCKED")
    deadline = decision.get("implementation_deadline_at")
    if deadline is not None and db.now() <= db.parse_dt(deadline):
        raise ApiError("ERR_IMPLEMENTATION_PERIOD_ACTIVE")

    executed_at = db.now_str()
    decision["status"] = "IMPLEMENTED"
    decision["implemented_at"] = executed_at
    db.touch(decision)
    if decision["outcome"] == "TRANSFER":
        domain["lock_status"] = "TRANSFER_EXECUTED"
        domain["executed_at"] = executed_at
        db.touch(domain)
    elif decision["outcome"] == "CANCELLATION":
        domain["lock_status"] = "CANCELLATION_EXECUTED"
        domain["executed_at"] = executed_at
        db.touch(domain)
    else:
        logic.release_lock(domain)
    logic.close_case(case, "IMPLEMENTED", release_domain_lock=False, discharge=True)
    return response.ok(db.public(decision))
