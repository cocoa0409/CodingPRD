from flask import Blueprint, request

import store as db
import logical_clock as clock
from auth import authorize
from envelope import obj, page
from errors import ApiError
from logic import (new_common, touch, get_or_404, resolve, month_add,
                   compute_drift, RISK_DELTA_MAX, AMENDMENT_QUORUM,
                   NONTERMINAL_PROPOSAL_STATES, cancel_open_trades,
                   expire_proposal)
from serialize import amendment_out
from validate import (body, no_unknown, req_str, opt_str, opt_int, req_int,
                      req_enum, pagination)

bp = Blueprint("amendments", __name__)

LEVERS = ("proposed_objective_text", "proposed_review_cadence_months",
          "proposed_risk_tolerance_score", "proposed_benchmark_id")


@bp.post("/advisory/ips-amendments")
def create_amendment():
    uid, _ = authorize("Advisor")
    b = body()
    no_unknown(b, {"ips_id"} | set(LEVERS))
    ips_id = req_str(b, "ips_id")
    obj_text = opt_str(b, "proposed_objective_text")
    cadence = opt_int(b, "proposed_review_cadence_months", 1, 24)
    risk = opt_int(b, "proposed_risk_tolerance_score", 1, 100)
    bench = opt_str(b, "proposed_benchmark_id")
    resolve(db.ips_policies, ips_id, "ips_id")
    if bench is not None:
        resolve(db.benchmarks, bench, "proposed_benchmark_id")
    if all(v is None for v in (obj_text, cadence, risk, bench)):
        raise ApiError("ERR_AMENDMENT_EMPTY_CHANGES", 422,
                       "Amendment must change at least one field")
    a = new_common()
    a.update({
        "ips_id": ips_id,
        "proposed_objective_text": obj_text,
        "proposed_review_cadence_months": cadence,
        "proposed_risk_tolerance_score": risk,
        "proposed_benchmark_id": bench,
        "proposed_by_user_id": uid,
        "status": "DRAFT",
        "approve_votes": 0, "reject_votes": 0, "voter_user_ids": [],
        "ratified_minute_id": None, "finalized_by_user_id": None,
        "finalized_at_dt": None,
    })
    db.amendments[a["id"]] = a
    return obj(amendment_out(a), 201)


@bp.get("/advisory/ips-amendments")
def list_amendments():
    authorize("Advisor", "ComplianceOfficer", "CommitteeMember", "CommitteeChair")
    limit, offset = pagination()
    rows = sorted(db.amendments.values(), key=lambda e: (e["created_dt"], e["_seq"]))
    ips_id = request.args.get("ips_id")
    if ips_id is not None:
        rows = [a for a in rows if a["ips_id"] == ips_id]
    rm = request.args.get("ratified_minute_id")
    if rm is not None:
        rows = [a for a in rows if a["ratified_minute_id"] == rm]
    status = request.args.get("status")
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    total = len(rows)
    return page([amendment_out(a) for a in rows[offset:offset + limit]],
                limit, offset, total)


@bp.get("/advisory/ips-amendments/<aid>")
def get_amendment(aid):
    authorize("Advisor", "ComplianceOfficer", "CommitteeMember", "CommitteeChair")
    a = get_or_404(db.amendments, aid)
    return obj(amendment_out(a))


@bp.post("/advisory/ips-amendments/<aid>/submit")
def submit_amendment(aid):
    authorize("Advisor")
    if request.data:
        no_unknown(body(), set())
    a = get_or_404(db.amendments, aid)
    if a["status"] != "DRAFT":
        raise ApiError("ERR_AMENDMENT_INVALID_STATE", 409,
                       "Amendment submit requires DRAFT")
    ips = db.ips_policies[a["ips_id"]]
    if ips["status"] != "ACTIVE":
        raise ApiError("ERR_IPS_INVALID_STATE", 409,
                       "Amendment submission requires an ACTIVE IPS")
    a["status"] = "SUBMITTED"
    touch(a)
    return obj(amendment_out(a))


@bp.post("/advisory/ips-amendments/<aid>/vote")
def vote_amendment(aid):
    uid, _ = authorize("CommitteeMember")
    b = body()
    no_unknown(b, {"decision"})
    decision = req_enum(b, "decision", {"APPROVE", "REJECT"})
    a = get_or_404(db.amendments, aid)
    if a["status"] != "SUBMITTED":
        raise ApiError("ERR_AMENDMENT_INVALID_STATE", 409,
                       "Voting requires SUBMITTED")
    if uid == a["proposed_by_user_id"]:
        raise ApiError("ERR_SOD_SELF_VOTE", 422,
                       "The proposer may not vote on their own amendment")
    if any(v["voter_user_id"] == uid for v in a["voter_user_ids"]):
        raise ApiError("ERR_DUPLICATE_VOTE", 422,
                       "Each committee member votes at most once")
    a["voter_user_ids"].append({"voter_user_id": uid, "decision": decision})
    a["approve_votes"] = sum(1 for v in a["voter_user_ids"]
                             if v["decision"] == "APPROVE")
    a["reject_votes"] = sum(1 for v in a["voter_user_ids"]
                            if v["decision"] == "REJECT")
    if a["approve_votes"] >= AMENDMENT_QUORUM:
        a["status"] = "QUORUM_REACHED"
    elif a["reject_votes"] >= AMENDMENT_QUORUM:
        a["status"] = "REJECTED"
    touch(a)
    return obj(amendment_out(a))


@bp.post("/advisory/ips-amendments/<aid>/finalize")
def finalize_amendment(aid):
    uid, _ = authorize("CommitteeChair")
    b = body()
    no_unknown(b, {"ratified_minute_id", "expected_ips_version"})
    ratified_minute_id = req_str(b, "ratified_minute_id")
    expected_ips_version = req_int(b, "expected_ips_version")
    a = get_or_404(db.amendments, aid)
    # PRD §2.7: quorum state check and stale-IPS rejection precede the
    # ratified-minute gate.
    if a["status"] != "QUORUM_REACHED":
        raise ApiError("ERR_AMENDMENT_INVALID_STATE", 409,
                       "Finalize requires QUORUM_REACHED")
    ips = db.ips_policies[a["ips_id"]]
    if expected_ips_version != ips["version"]:
        raise ApiError("ERR_STALE_IPS_VERSION", 412,
                       "expected_ips_version does not match current IPS version")
    minute = db.minutes.get(ratified_minute_id)
    if minute is None:
        raise ApiError("ERR_INVALID_REFERENCE", 422,
                       "ratified_minute_id does not resolve")
    if minute["status"] != "RATIFIED":
        raise ApiError("ERR_AMENDMENT_MINUTE_NOT_RATIFIED", 422,
                       "Referenced minute is not RATIFIED")
    if aid not in minute["amendment_refs"]:
        raise ApiError("ERR_AMENDMENT_NOT_IN_MINUTE", 422,
                       "Amendment is absent from the minute's amendment_refs")
    if a["proposed_benchmark_id"] is not None:
        if db.benchmarks[a["proposed_benchmark_id"]]["status"] != "ACTIVE":
            raise ApiError("ERR_BENCHMARK_NOT_ACTIVE", 422,
                           "Proposed benchmark is not ACTIVE")
    if a["proposed_risk_tolerance_score"] is not None:
        client = db.clients[ips["client_id"]]
        if abs(a["proposed_risk_tolerance_score"]
               - client["risk_tolerance_score"]) > RISK_DELTA_MAX:
            raise ApiError("ERR_RISK_TOLERANCE_MISMATCH", 422,
                           "Proposed risk score beyond +/-10 of the client's")
    # Apply every non-null lever; bump the IPS version exactly once.
    if a["proposed_objective_text"] is not None:
        ips["objective_text"] = a["proposed_objective_text"]
    cadence_changed = a["proposed_review_cadence_months"] is not None
    if cadence_changed:
        ips["review_cadence_months"] = a["proposed_review_cadence_months"]
    if a["proposed_risk_tolerance_score"] is not None:
        ips["risk_tolerance_score"] = a["proposed_risk_tolerance_score"]
    if a["proposed_benchmark_id"] is not None:
        ips["benchmark_id"] = a["proposed_benchmark_id"]
    a["ratified_minute_id"] = ratified_minute_id
    a["finalized_by_user_id"] = uid
    a["finalized_at_dt"] = clock.now()
    touch(ips)   # IPS.version += 1
    if cadence_changed:
        ips["next_review_due_dt"] = month_add(a["finalized_at_dt"],
                                              ips["review_cadence_months"])
    # Pin cascade: proposals pinned to this IPS now mismatch -> EXPIRED.
    for prop in db.proposals.values():
        if (prop["ips_id"] == ips["id"]
                and prop["status"] in NONTERMINAL_PROPOSAL_STATES
                and prop["pinned_ips_version"] != ips["version"]):
            expire_proposal(prop)
    # Drift recompute for the client's non-CLOSED portfolios.
    for pf in db.portfolios.values():
        if pf["client_id"] == ips["client_id"] and pf["lifecycle_status"] != "CLOSED":
            pf["drift_status"] = compute_drift(pf)
            touch(pf)
    a["status"] = "APPROVED"
    touch(a)
    return obj(amendment_out(a))


@bp.post("/advisory/ips-amendments/<aid>/withdraw")
def withdraw_amendment(aid):
    uid, _ = authorize("Advisor")
    if request.data:
        no_unknown(body(), set())
    a = get_or_404(db.amendments, aid)
    # Ownership (priority 3) precedes the state check (priority 7).
    if uid != a["proposed_by_user_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "Only the proposing advisor may withdraw")
    if a["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError("ERR_AMENDMENT_INVALID_STATE", 409,
                       "Withdraw requires DRAFT or SUBMITTED")
    a["status"] = "WITHDRAWN"
    touch(a)
    return obj(amendment_out(a))
