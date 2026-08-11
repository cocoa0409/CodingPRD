"""ClientAgreement, SubmissionRound, and Submission endpoints."""
from flask import Blueprint

from core import (DB, F, ERR_AGR_NOT_SIGNED, ERR_AGR_SIGNED, ERR_DEAL_OPEN,
                  ERR_DUP_SUB, ERR_EDITOR_INACTIVE, ERR_EMPTY_ROUND, ERR_EXCL,
                  ERR_MS_NOT_ACCEPTED, ERR_NOT_ASSIGNED, ERR_OFFER_LIVE,
                  ERR_ROUND_CAP, ERR_ROUND_LIVE_OFFERS, ERR_ROUND_LIVE_SUBS,
                  ERR_ROUND_NOT_OPEN, ERR_ROUND_OPEN, ERR_STALE, ERR_STATE,
                  acting_agency, fail, get_ref, get_scoped, guard,
                  list_response, new_record, parse_body, public, success, touch)
from domain import (author_maybe_former, author_to_client,
                    signed_agreement_for_manuscript, subs_of_round,
                    offers_of_round)

bp = Blueprint("agreements", __name__)

ALL = ("AgencyAdmin", "Agent", "ContractsManager", "RoyaltiesAccountant")


# --------------------------------------------------------- client agreements ----
@bp.route("/client-agreements", methods=["POST"])
def create_agreement():
    ctx = guard("Agent")
    data = parse_body([
        F("author_id", "str", required=True),
        F("manuscript_id", "str", required=True),
        F("agent_id", "str", required=True),
        F("commission_pct_override", "num", lo=0, nullable=True),
        F("exclusive", "bool", default=True),
    ])
    aid = acting_agency(ctx)
    author = get_ref("authors", data["author_id"], aid)
    ms = get_ref("manuscripts", data["manuscript_id"], aid)
    get_ref("agents", data["agent_id"], aid)
    rec = new_record()
    rec.update({
        "agency_id": ms["agency_id"],
        "author_id": author["id"],
        "manuscript_id": ms["id"],
        "agent_id": data["agent_id"],
        "commission_pct_override": data["commission_pct_override"],
        "exclusive": data["exclusive"],
        "status": "DRAFT",
        "signed_period_index": None,
    })
    DB["client_agreements"][rec["id"]] = rec
    return success(public(rec), 201)


@bp.route("/client-agreements/<agreementId>", methods=["GET"])
def get_agreement(agreementId):
    ctx = guard(*ALL)
    return success(public(get_scoped("client_agreements", agreementId, ctx)))


@bp.route("/client-agreements", methods=["GET"])
def list_agreements():
    ctx = guard(*ALL)
    return list_response("client_agreements", ctx, {
        "agency_id": "str", "status": "str", "author_id": "str",
        "manuscript_id": "str", "agent_id": "str",
    })


@bp.route("/client-agreements/<agreementId>/offer", methods=["POST"])
def offer_agreement(agreementId):
    ctx = guard("Agent")
    parse_body([])
    ag = get_scoped("client_agreements", agreementId, ctx)
    if ag["status"] != "DRAFT":
        fail(ERR_STATE, 409, "agreement is not DRAFT")
    if ctx.uid != ag["agent_id"]:
        fail(ERR_NOT_ASSIGNED, 403, "acting agent is not the signing agent")
    ms = DB["manuscripts"].get(ag["manuscript_id"])
    if ms is None or ms["status"] != "ACCEPTED":
        fail(ERR_MS_NOT_ACCEPTED, 409, "manuscript is not ACCEPTED")
    ag["status"] = "OFFERED"
    touch(ag)
    return success(public(ag))


@bp.route("/client-agreements/<agreementId>/sign", methods=["POST"])
def sign_agreement(agreementId):
    ctx = guard("Agent")
    parse_body([])
    ag = get_scoped("client_agreements", agreementId, ctx)
    if ag["status"] != "OFFERED":
        fail(ERR_STATE, 409, "agreement is not OFFERED")
    if any(a for a in DB["client_agreements"].values()
           if a["manuscript_id"] == ag["manuscript_id"]
           and a["status"] == "SIGNED" and a["id"] != ag["id"]):
        fail(ERR_AGR_SIGNED, 409,
             "another SIGNED agreement already covers this manuscript")
    agency = DB["agencies"].get(ag["agency_id"])
    ag["status"] = "SIGNED"
    ag["signed_period_index"] = agency["period_index"] if agency else None
    touch(ag)
    author_to_client(ag["author_id"])
    return success(public(ag))


@bp.route("/client-agreements/<agreementId>/decline", methods=["POST"])
def decline_agreement(agreementId):
    ctx = guard("Agent")
    parse_body([])
    ag = get_scoped("client_agreements", agreementId, ctx)
    if ag["status"] != "OFFERED":
        fail(ERR_STATE, 409, "agreement is not OFFERED")
    ag["status"] = "DECLINED_BY_AUTHOR"
    touch(ag)
    return success(public(ag))


@bp.route("/client-agreements/<agreementId>/terminate", methods=["POST"])
def terminate_agreement(agreementId):
    ctx = guard("ContractsManager")
    parse_body([])
    ag = get_scoped("client_agreements", agreementId, ctx)
    if ag["status"] != "SIGNED":
        fail(ERR_STATE, 409, "agreement is not SIGNED")
    if any(d for d in DB["deals"].values()
           if d["client_agreement_id"] == ag["id"]
           and d["status"] in ("NEGOTIATING", "EXECUTED", "ACTIVE")):
        fail(ERR_DEAL_OPEN, 409, "an open deal blocks agreement termination")
    ag["status"] = "TERMINATED"
    touch(ag)
    author_maybe_former(ag["author_id"])
    return success(public(ag))


# ---------------------------------------------------------- submission rounds ----
@bp.route("/submission-rounds", methods=["POST"])
def create_round():
    ctx = guard("Agent")
    data = parse_body([
        F("manuscript_id", "str", required=True),
        F("agent_id", "str", required=True),
        F("max_editors", "int", required=True, lo=1),
        F("auction_mode", "bool", default=False),
        F("valuation_mode", "enum", default="FRONTLIST",
          enum=("FRONTLIST", "BACKLIST")),
    ])
    aid = acting_agency(ctx)
    ms = get_ref("manuscripts", data["manuscript_id"], aid)
    get_ref("agents", data["agent_id"], aid)
    prior = sum(1 for r in DB["submission_rounds"].values()
                if r["manuscript_id"] == ms["id"])
    rec = new_record()
    rec.update({
        "agency_id": ms["agency_id"],
        "manuscript_id": ms["id"],
        "agent_id": data["agent_id"],
        "round_index": prior + 1,
        "max_editors": data["max_editors"],
        "auction_mode": data["auction_mode"],
        "valuation_mode": data["valuation_mode"],
        "status": "DRAFT",
    })
    DB["submission_rounds"][rec["id"]] = rec
    return success(public(rec), 201)


@bp.route("/submission-rounds/<roundId>", methods=["GET"])
def get_round(roundId):
    ctx = guard(*ALL)
    return success(public(get_scoped("submission_rounds", roundId, ctx)))


@bp.route("/submission-rounds", methods=["GET"])
def list_rounds():
    ctx = guard(*ALL)
    return list_response("submission_rounds", ctx, {
        "agency_id": "str", "status": "str", "manuscript_id": "str",
        "agent_id": "str",
    })


@bp.route("/submission-rounds/<roundId>/open", methods=["POST"])
def open_round(roundId):
    ctx = guard("Agent")
    data = parse_body([
        F("expected_submission_round_version", "int", required=True, lo=0),
    ])
    rnd = get_scoped("submission_rounds", roundId, ctx)
    if data["expected_submission_round_version"] != rnd["version"]:
        fail(ERR_STALE, 412, "expected_submission_round_version is stale")
    if rnd["status"] != "DRAFT":
        fail(ERR_STATE, 409, "submission round is not DRAFT")
    if signed_agreement_for_manuscript(rnd["manuscript_id"]) is None:
        fail(ERR_AGR_NOT_SIGNED, 409,
             "no SIGNED client agreement for this manuscript")
    if any(r for r in DB["submission_rounds"].values()
           if r["manuscript_id"] == rnd["manuscript_id"]
           and r["status"] == "OPEN" and r["id"] != rnd["id"]):
        fail(ERR_ROUND_OPEN, 409,
             "another round for this manuscript is already OPEN")
    if not any(s for s in subs_of_round(rnd["id"]) if s["status"] == "QUEUED"):
        fail(ERR_EMPTY_ROUND, 409, "round has no QUEUED submission")
    rnd["status"] = "OPEN"
    touch(rnd)
    return success(public(rnd))


@bp.route("/submission-rounds/<roundId>/close", methods=["POST"])
def close_round(roundId):
    ctx = guard("Agent")
    parse_body([])
    rnd = get_scoped("submission_rounds", roundId, ctx)
    if rnd["status"] != "OPEN":
        fail(ERR_STATE, 409, "submission round is not OPEN")
    subs = subs_of_round(rnd["id"])
    if any(s for s in subs
           if s["status"] in ("UNDER_CONSIDERATION", "OFFER_EXTENDED")):
        fail(ERR_ROUND_LIVE_SUBS, 409, "round has live submissions")
    if any(o for o in offers_of_round(rnd["id"])
           if o["status"] in ("RECEIVED", "UNDER_NEGOTIATION")):
        fail(ERR_ROUND_LIVE_OFFERS, 409, "round has live offers")
    for s in subs:
        if s["status"] in ("QUEUED", "SENT"):
            s["status"] = "WITHDRAWN"
            touch(s)
    rnd["status"] = "CLOSED"
    touch(rnd)
    return success(public(rnd))


# ---------------------------------------------------------------- submissions ----
@bp.route("/submissions", methods=["POST"])
def create_submission():
    ctx = guard("Agent")
    data = parse_body([
        F("submission_round_id", "str", required=True),
        F("editor_id", "str", required=True),
    ])
    aid = acting_agency(ctx)
    rnd = get_ref("submission_rounds", data["submission_round_id"], aid)
    editor = get_ref("editors", data["editor_id"], aid)
    if rnd["status"] == "CLOSED":
        fail(ERR_STATE, 409, "submission round is CLOSED")
    subs = subs_of_round(rnd["id"])
    live = sum(1 for s in subs if s["status"] in (
        "QUEUED", "SENT", "UNDER_CONSIDERATION", "OFFER_EXTENDED"))
    if live >= rnd["max_editors"]:
        fail(ERR_ROUND_CAP, 409, "round live-submission capacity reached")
    if any(s for s in subs if s["editor_id"] == editor["id"]):
        fail(ERR_DUP_SUB, 409, "round already has a submission to this editor")
    rec = new_record()
    rec.update({
        "agency_id": rnd["agency_id"],
        "submission_round_id": rnd["id"],
        "editor_id": editor["id"],
        "sent_period_index": None,
        "response_period_index": None,
        "status": "QUEUED",
    })
    DB["submissions"][rec["id"]] = rec
    return success(public(rec), 201)


@bp.route("/submissions/<submissionId>", methods=["GET"])
def get_submission(submissionId):
    ctx = guard(*ALL)
    return success(public(get_scoped("submissions", submissionId, ctx)))


@bp.route("/submissions", methods=["GET"])
def list_submissions():
    ctx = guard(*ALL)
    return list_response("submissions", ctx, {
        "agency_id": "str", "status": "str", "submission_round_id": "str",
        "editor_id": "str",
    })


@bp.route("/submissions/<submissionId>/send", methods=["POST"])
def send_submission(submissionId):
    ctx = guard("Agent")
    parse_body([])
    sub = get_scoped("submissions", submissionId, ctx)
    if sub["status"] != "QUEUED":
        fail(ERR_STATE, 409, "submission is not QUEUED")
    rnd = DB["submission_rounds"].get(sub["submission_round_id"])
    if rnd is None or rnd["status"] != "OPEN":
        fail(ERR_ROUND_NOT_OPEN, 409, "parent round is not OPEN")
    editor = DB["editors"].get(sub["editor_id"])
    if editor is None or editor["status"] != "ACTIVE":
        fail(ERR_EDITOR_INACTIVE, 409, "editor is not ACTIVE")
    agency = DB["agencies"].get(sub["agency_id"])
    period = agency["period_index"]
    for other in DB["submissions"].values():
        if (other["id"] == sub["id"] or other["editor_id"] != sub["editor_id"]
                or other["status"] not in ("SENT", "UNDER_CONSIDERATION",
                                           "OFFER_EXTENDED")):
            continue
        p = other["sent_period_index"]
        if p is not None and period < p + 2:
            fail(ERR_EXCL, 409,
                 "editor exclusivity window is still in effect")
    sub["status"] = "SENT"
    sub["sent_period_index"] = period
    touch(sub)
    return success(public(sub))


@bp.route("/submissions/<submissionId>/mark-under-consideration",
          methods=["POST"])
def mark_under_consideration(submissionId):
    ctx = guard("Agent")
    parse_body([])
    sub = get_scoped("submissions", submissionId, ctx)
    if sub["status"] != "SENT":
        fail(ERR_STATE, 409, "submission is not SENT")
    sub["status"] = "UNDER_CONSIDERATION"
    touch(sub)
    return success(public(sub))


@bp.route("/submissions/<submissionId>/pass", methods=["POST"])
def pass_submission(submissionId):
    ctx = guard("Agent")
    parse_body([])
    sub = get_scoped("submissions", submissionId, ctx)
    if sub["status"] not in ("SENT", "UNDER_CONSIDERATION"):
        fail(ERR_STATE, 409,
             "submission is not SENT or UNDER_CONSIDERATION")
    agency = DB["agencies"].get(sub["agency_id"])
    sub["status"] = "PASSED"
    sub["response_period_index"] = agency["period_index"] if agency else None
    touch(sub)
    return success(public(sub))


@bp.route("/submissions/<submissionId>/withdraw", methods=["POST"])
def withdraw_submission(submissionId):
    ctx = guard("Agent")
    parse_body([])
    sub = get_scoped("submissions", submissionId, ctx)
    if sub["status"] in ("QUEUED", "SENT", "UNDER_CONSIDERATION"):
        pass
    elif sub["status"] == "OFFER_EXTENDED":
        offer = next((o for o in DB["offers"].values()
                      if o["submission_id"] == sub["id"]), None)
        if offer is not None and offer["status"] not in (
                "DECLINED", "WITHDRAWN_BY_EDITOR", "SUPERSEDED"):
            fail(ERR_OFFER_LIVE, 409,
                 "submission has a live offer; withdraw the offer first")
    else:
        fail(ERR_STATE, 409, "submission cannot be withdrawn from its state")
    sub["status"] = "WITHDRAWN"
    touch(sub)
    return success(public(sub))
