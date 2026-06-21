"""JobPosting endpoints (PRD 3.2)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_auth, require_role
from response import success
from services import common, derive
from services.calc import match_score

bp = Blueprint("job_postings", __name__)

LIVE = {"SUBMITTED", "COUNTERED"}


@bp.post("/job-postings")
def create_job_posting():
    user_id, role = require_auth()
    require_role(role, ["Client"])
    body = common.get_body()
    client_id = common.require_str(body, "client_id")
    title = common.require_str(body, "title")
    billing_type = common.require_enum(body, "billing_type", {"FIXED", "HOURLY"})
    budget = common.require_int(body, "budget_cents", minimum=100)
    skills = body.get("required_skills")
    if not isinstance(skills, list) or not all(isinstance(s, str) for s in skills):
        raise err("ERR_INVALID_REQUEST", "required_skills must be an array of strings")
    # existence + ownership: the acting Client must own the posting (PRD 2.1)
    common.get_client(client_id)
    common.check_client_owns(role, user_id, client_id)
    rec = db.new_common()
    rec.update({
        "client_id": client_id,
        "title": title,
        "billing_type": billing_type,
        "budget_cents": budget,
        "required_skills": list(skills),
        "status": "OPEN",
        "awarded_proposal_id": None,
    })
    db.job_postings[rec["id"]] = rec
    return success(derive.job_posting_view(rec), status=201)


@bp.get("/job-postings")
def list_job_postings():
    _, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client", "Freelancer"])
    client_id = request.args.get("client_id")
    status = request.args.get("status")
    items = list(db.job_postings.values())
    if client_id is not None:
        items = [j for j in items if j["client_id"] == client_id]
    if status is not None:
        items = [j for j in items if j["status"] == status]
    items = common.sort_by_created(items)
    page, meta = common.paginate(items)
    return success([derive.job_posting_view(j) for j in page], pagination=meta)


@bp.get("/job-postings/<jid>")
def get_job_posting(jid):
    _, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client", "Freelancer"])
    j = common.get_job_posting(jid)
    return success(derive.job_posting_view(j))


@bp.post("/job-postings/<jid>/cancel")
def cancel_job_posting(jid):
    user_id, role = require_auth()
    require_role(role, ["Client"])
    j = common.get_job_posting(jid)
    common.check_client_owns(role, user_id, j["client_id"])
    if j["status"] not in ("OPEN", "UNDER_REVIEW"):
        raise err("ERR_INVALID_CONTRACT_STATE", "Posting not cancellable in its state")
    # cascade: decline every live proposal
    for p in db.proposals.values():
        if p["job_posting_id"] == jid and p["status"] in LIVE:
            p["status"] = "DECLINED"
            db.touch(p)
    j["status"] = "CANCELLED"
    db.touch(j)
    return success(derive.job_posting_view(j))


@bp.get("/job-postings/<jid>/proposals")
def job_posting_proposals(jid):
    _, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client", "Freelancer"])
    common.get_job_posting(jid)
    items = [p for p in db.proposals.values() if p["job_posting_id"] == jid]
    items = common.sort_by_created(items)
    page, meta = common.paginate(items)
    return success([derive.proposal_view(p) for p in page], pagination=meta)


@bp.get("/job-postings/<jid>/ranked-proposals")
def ranked_proposals(jid):
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client"])
    j = common.get_job_posting(jid)
    required = j["required_skills"]
    denom = max(1, len(required))
    candidates = []
    for p in db.proposals.values():
        if p["job_posting_id"] != jid or p["status"] not in LIVE:
            continue
        f = db.freelancers.get(p["freelancer_id"])
        fskills = set(f["skills"]) if f else set()
        coverage = sum(1 for s in required if s in fskills) / denom
        rep = f["reputation_score"] if f else 0.0
        score = match_score(coverage, rep, j["budget_cents"], p["bid_amount_cents"])
        candidates.append((score, p["_seq"], p))
    # rank DESC by match; tie-break created_at (== _seq) ASC
    candidates.sort(key=lambda t: (-t[0], t[1]))
    ordered = [t[2] for t in candidates]
    page, meta = common.paginate(ordered)
    return success([derive.proposal_view(p) for p in page], pagination=meta)
