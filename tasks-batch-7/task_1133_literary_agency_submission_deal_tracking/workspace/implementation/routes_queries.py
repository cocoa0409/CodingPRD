"""QueryLetter and Manuscript endpoints."""
from flask import Blueprint

from core import (DB, F, ERR_AGENT_INACTIVE, ERR_INTAKE, ERR_NOT_ASSIGNED,
                  ERR_NF, ERR_REVISION, ERR_SCORE, ERR_STATE, acting_agency,
                  fail, get_ref, get_scoped, guard, list_response, new_record,
                  parse_body, public, success, touch)
from domain import (author_to_client, open_slush_count, recompute_open_count,
                    refresh_posture, triage_score)

bp = Blueprint("queries", __name__)

ALL = ("AgencyAdmin", "Agent", "ContractsManager", "RoyaltiesAccountant")
GENRES = ("FICTION", "NONFICTION", "YA", "MEMOIR")


# ------------------------------------------------------------ query letters ----
@bp.route("/query-letters", methods=["POST"])
def create_query_letter():
    ctx = guard("Agent")
    data = parse_body([
        F("author_id", "str", required=True),
        F("genre", "enum", required=True, enum=GENRES),
        F("word_count", "int", required=True, lo=1),
    ])
    author = get_ref("authors", data["author_id"], acting_agency(ctx))
    agency = DB["agencies"].get(author["agency_id"])
    if agency is None:
        not_found("agency not found for author")
    if open_slush_count(agency["id"]) >= agency["slush_capacity"]:
        fail(ERR_INTAKE, 409, "agency intake is paused: slush pile at capacity")
    rec = new_record()
    rec.update({
        "agency_id": author["agency_id"],
        "author_id": author["id"],
        "assigned_agent_id": None,
        "genre": data["genre"],
        "word_count": data["word_count"],
        "triage_score": triage_score(data["genre"], data["word_count"],
                                     author["status"]),
        "requested_period_index": None,
        "status": "RECEIVED",
    })
    DB["query_letters"][rec["id"]] = rec
    refresh_posture(agency)
    return success(public(rec), 201)


@bp.route("/query-letters/<queryLetterId>", methods=["GET"])
def get_query_letter(queryLetterId):
    ctx = guard(*ALL)
    return success(public(get_scoped("query_letters", queryLetterId, ctx)))


@bp.route("/query-letters", methods=["GET"])
def list_query_letters():
    ctx = guard(*ALL)
    return list_response("query_letters", ctx, {
        "agency_id": "str", "status": "str", "author_id": "str",
        "assigned_agent_id": "str",
    })


@bp.route("/query-letters/<queryLetterId>/assign", methods=["POST"])
def assign_query_letter(queryLetterId):
    ctx = guard("Agent")
    data = parse_body([F("agent_id", "str", required=True)])
    q = get_scoped("query_letters", queryLetterId, ctx)
    agent = get_ref("agents", data["agent_id"], q["agency_id"])
    if q["status"] != "RECEIVED":
        fail(ERR_STATE, 409, "query letter is not RECEIVED")
    if agent["status"] != "ACTIVE":
        fail(ERR_AGENT_INACTIVE, 409, "referenced agent is not ACTIVE")
    prior = q["assigned_agent_id"]
    q["assigned_agent_id"] = agent["id"]
    q["status"] = "IN_REVIEW"
    touch(q)
    if prior and prior != agent["id"]:
        recompute_open_count(prior)
    recompute_open_count(agent["id"])
    agency = DB["agencies"].get(q["agency_id"])
    if agency:
        refresh_posture(agency)
    return success(public(q))


@bp.route("/query-letters/<queryLetterId>/request-manuscript", methods=["POST"])
def request_manuscript(queryLetterId):
    ctx = guard("Agent")
    data = parse_body([F("title", "str", required=True)])
    q = get_scoped("query_letters", queryLetterId, ctx)
    if q["status"] != "IN_REVIEW":
        fail(ERR_STATE, 409, "query letter is not IN_REVIEW")
    if ctx.uid != q["assigned_agent_id"]:
        fail(ERR_NOT_ASSIGNED, 403, "acting agent is not the assigned agent")
    agency = DB["agencies"].get(q["agency_id"])
    q["status"] = "REQUESTED"
    q["requested_period_index"] = agency["period_index"]
    touch(q)
    ms = new_record()
    ms.update({
        "agency_id": q["agency_id"],
        "query_letter_id": q["id"],
        "author_id": q["author_id"],
        "reader_agent_id": q["assigned_agent_id"],
        "title": data["title"],
        "revision_round": 0,
        "eval_score": None,
        "status": "SUBMITTED",
    })
    DB["manuscripts"][ms["id"]] = ms
    recompute_open_count(q["assigned_agent_id"])
    refresh_posture(agency)
    return success(public(ms))


@bp.route("/query-letters/<queryLetterId>/reject", methods=["POST"])
def reject_query_letter(queryLetterId):
    ctx = guard("Agent")
    parse_body([])
    q = get_scoped("query_letters", queryLetterId, ctx)
    if q["status"] not in ("RECEIVED", "IN_REVIEW"):
        fail(ERR_STATE, 409, "query letter cannot be rejected from its state")
    if q["status"] == "IN_REVIEW" and ctx.uid != q["assigned_agent_id"]:
        fail(ERR_NOT_ASSIGNED, 403, "acting agent is not the assigned agent")
    assigned = q["assigned_agent_id"]
    q["status"] = "REJECTED"
    touch(q)
    recompute_open_count(assigned)
    agency = DB["agencies"].get(q["agency_id"])
    if agency:
        refresh_posture(agency)
    return success(public(q))


@bp.route("/query-letters/<queryLetterId>/withdraw", methods=["POST"])
def withdraw_query_letter(queryLetterId):
    ctx = guard("Agent")
    parse_body([])
    q = get_scoped("query_letters", queryLetterId, ctx)
    if q["status"] not in ("RECEIVED", "IN_REVIEW"):
        fail(ERR_STATE, 409, "query letter cannot be withdrawn from its state")
    assigned = q["assigned_agent_id"]
    q["status"] = "WITHDRAWN"
    touch(q)
    recompute_open_count(assigned)
    agency = DB["agencies"].get(q["agency_id"])
    if agency:
        refresh_posture(agency)
    return success(public(q))


# --------------------------------------------------------------- manuscripts ----
@bp.route("/manuscripts/<manuscriptId>", methods=["GET"])
def get_manuscript(manuscriptId):
    ctx = guard(*ALL)
    return success(public(get_scoped("manuscripts", manuscriptId, ctx)))


@bp.route("/manuscripts", methods=["GET"])
def list_manuscripts():
    ctx = guard(*ALL)
    return list_response("manuscripts", ctx, {
        "agency_id": "str", "status": "str", "author_id": "str",
        "query_letter_id": "str", "reader_agent_id": "str",
    })


@bp.route("/manuscripts/<manuscriptId>/assign-reader", methods=["POST"])
def assign_reader(manuscriptId):
    ctx = guard("Agent")
    data = parse_body([F("agent_id", "str", required=True)])
    ms = get_scoped("manuscripts", manuscriptId, ctx)
    agent = get_ref("agents", data["agent_id"], ms["agency_id"])
    if ms["status"] != "SUBMITTED":
        fail(ERR_STATE, 409, "manuscript is not SUBMITTED")
    if agent["status"] != "ACTIVE":
        fail(ERR_AGENT_INACTIVE, 409, "referenced agent is not ACTIVE")
    ms["reader_agent_id"] = agent["id"]
    ms["status"] = "READER_ASSIGNED"
    touch(ms)
    return success(public(ms))


@bp.route("/manuscripts/<manuscriptId>/evaluate", methods=["POST"])
def evaluate_manuscript(manuscriptId):
    ctx = guard("Agent")
    data = parse_body([F("eval_score", "int", required=True, lo=0, hi=100)])
    ms = get_scoped("manuscripts", manuscriptId, ctx)
    if ms["status"] != "READER_ASSIGNED":
        fail(ERR_STATE, 409, "manuscript is not READER_ASSIGNED")
    if ctx.uid != ms["reader_agent_id"]:
        fail(ERR_NOT_ASSIGNED, 403, "acting agent is not the reader agent")
    ms["eval_score"] = data["eval_score"]
    ms["status"] = "EVALUATED"
    touch(ms)
    return success(public(ms))


@bp.route("/manuscripts/<manuscriptId>/request-revision", methods=["POST"])
def request_revision(manuscriptId):
    ctx = guard("Agent")
    parse_body([])
    ms = get_scoped("manuscripts", manuscriptId, ctx)
    if ms["status"] != "EVALUATED":
        fail(ERR_STATE, 409, "manuscript is not EVALUATED")
    if ms["revision_round"] >= 2:
        fail(ERR_REVISION, 409, "manuscript has consumed 2 revision rounds")
    ms["revision_round"] += 1
    ms["status"] = "REVISION_REQUESTED"
    touch(ms)
    return success(public(ms))


@bp.route("/manuscripts/<manuscriptId>/resubmit", methods=["POST"])
def resubmit_manuscript(manuscriptId):
    ctx = guard("Agent")
    parse_body([])
    ms = get_scoped("manuscripts", manuscriptId, ctx)
    if ms["status"] != "REVISION_REQUESTED":
        fail(ERR_STATE, 409, "manuscript is not REVISION_REQUESTED")
    ms["status"] = "SUBMITTED"
    touch(ms)
    return success(public(ms))


@bp.route("/manuscripts/<manuscriptId>/accept", methods=["POST"])
def accept_manuscript(manuscriptId):
    ctx = guard("Agent")
    parse_body([])
    ms = get_scoped("manuscripts", manuscriptId, ctx)
    if ms["status"] != "EVALUATED":
        fail(ERR_STATE, 409, "manuscript is not EVALUATED")
    if ms["eval_score"] is None or ms["eval_score"] < 70:
        fail(ERR_SCORE, 409, "manuscript accept requires eval_score >= 70")
    ms["status"] = "ACCEPTED"
    touch(ms)
    author_to_client(ms["author_id"])
    return success(public(ms))


@bp.route("/manuscripts/<manuscriptId>/decline", methods=["POST"])
def decline_manuscript(manuscriptId):
    ctx = guard("Agent")
    parse_body([])
    ms = get_scoped("manuscripts", manuscriptId, ctx)
    if ms["status"] != "EVALUATED":
        fail(ERR_STATE, 409, "manuscript is not EVALUATED")
    ms["status"] = "DECLINED"
    touch(ms)
    return success(public(ms))
