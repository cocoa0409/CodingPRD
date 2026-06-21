"""Proposal endpoints — submission and negotiation state machine (PRD 3.2)."""
from flask import Blueprint

import db
from errors import err
from middleware import require_auth, require_role
from response import success
from services import common, derive

bp = Blueprint("proposals", __name__)

LIVE = {"SUBMITTED", "COUNTERED"}
MAX_COUNTER_ROUNDS = 5


@bp.post("/proposals")
def create_proposal():
    user_id, role = require_auth()
    require_role(role, ["Freelancer"])
    body = common.get_body()
    job_posting_id = common.require_str(body, "job_posting_id")
    freelancer_id = common.require_str(body, "freelancer_id")
    bid = common.require_int(body, "bid_amount_cents", minimum=1)
    cover = common.require_str(body, "cover_letter")
    # existence left-to-right: posting then freelancer (both body ids)
    posting = common.get_job_posting(job_posting_id)
    f = common.get_freelancer(freelancer_id)
    common.check_freelancer_owns(role, user_id, freelancer_id)
    # skill coverage (PRD 3.2)
    fskills = set(f["skills"])
    if not set(posting["required_skills"]).issubset(fskills):
        raise err("ERR_SKILLS_NOT_COVERED", "Freelancer skills do not cover required_skills")

    rec = db.new_common()
    rec.update({
        "job_posting_id": job_posting_id,
        "freelancer_id": freelancer_id,
        "bid_amount_cents": bid,
        "cover_letter": cover,
        "round_count": 0,
        "last_actor": "FREELANCER",
        "status": "SUBMITTED",
    })
    db.proposals[rec["id"]] = rec
    # first proposal moves OPEN -> UNDER_REVIEW (PRD 3.2)
    if posting["status"] == "OPEN":
        posting["status"] = "UNDER_REVIEW"
        db.touch(posting)
    return success(derive.proposal_view(rec), status=201)


@bp.get("/proposals/<pid>")
def get_proposal(pid):
    _, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client", "Freelancer"])
    p = common.get_proposal(pid)
    return success(derive.proposal_view(p))


def _opposite(actor):
    return "CLIENT" if actor == "FREELANCER" else "FREELANCER"


@bp.post("/proposals/<pid>/counter")
def counter(pid):
    user_id, role = require_auth()
    require_role(role, ["Client", "Freelancer"])
    p = common.get_proposal(pid)
    posting = db.job_postings[p["job_posting_id"]]
    body = common.get_body()
    actor_role = common.require_enum(body, "actor_role", {"CLIENT", "FREELANCER"})
    new_bid = common.require_int(body, "bid_amount_cents", minimum=1)
    # ownership: the acting party must own its side of the negotiation
    if actor_role == "CLIENT":
        common.check_client_owns(role, user_id, posting["client_id"])
    else:
        common.check_freelancer_owns(role, user_id, p["freelancer_id"])
    # state: proposal must be live
    if p["status"] not in LIVE:
        raise err("ERR_INVALID_PROPOSAL_STATE", "Proposal not open for countering")
    # cross-entity: posting OPEN/UNDER_REVIEW
    if posting["status"] not in ("OPEN", "UNDER_REVIEW"):
        raise err("ERR_INVALID_PROPOSAL_STATE", "Posting not open for negotiation")
    # turn alternation + round cap (PRD 3.2)
    if p["round_count"] >= MAX_COUNTER_ROUNDS:
        raise err("ERR_NOT_YOUR_TURN", "Counter round ceiling reached")
    if actor_role == p["last_actor"]:
        raise err("ERR_NOT_YOUR_TURN", "It is not your turn to counter")
    p["bid_amount_cents"] = new_bid
    p["round_count"] += 1
    p["last_actor"] = actor_role
    p["status"] = "COUNTERED"
    db.touch(p)
    return success(derive.proposal_view(p))


@bp.post("/proposals/<pid>/accept")
def accept(pid):
    user_id, role = require_auth()
    require_role(role, ["Client", "Freelancer"])
    p = common.get_proposal(pid)
    posting = db.job_postings[p["job_posting_id"]]
    body = common.get_body()
    actor_role = common.require_enum(body, "actor_role", {"CLIENT", "FREELANCER"})
    if actor_role == "CLIENT":
        common.check_client_owns(role, user_id, posting["client_id"])
    else:
        common.check_freelancer_owns(role, user_id, p["freelancer_id"])
    if p["status"] not in LIVE:
        raise err("ERR_INVALID_PROPOSAL_STATE", "Proposal not open for acceptance")
    if posting["status"] not in ("OPEN", "UNDER_REVIEW"):
        raise err("ERR_INVALID_PROPOSAL_STATE", "Posting not open for acceptance")
    # cannot accept your own live offer (PRD 3.2)
    if actor_role == p["last_actor"]:
        raise err("ERR_NOT_YOUR_TURN", "You cannot accept your own live offer")

    p["status"] = "ACCEPTED"
    db.touch(p)

    # posting -> AWARDED with awarded_proposal_id (PRD 3.2)
    posting["status"] = "AWARDED"
    posting["awarded_proposal_id"] = p["id"]
    db.touch(posting)

    # sibling live proposals -> DECLINED (cascade)
    for sib in db.proposals.values():
        if sib["id"] != p["id"] and sib["job_posting_id"] == posting["id"] \
                and sib["status"] in LIVE:
            sib["status"] = "DECLINED"
            db.touch(sib)

    # create Contract in DRAFT (PRD 3.3)
    contract = db.new_common()
    contract.update({
        "client_id": posting["client_id"],
        "freelancer_id": p["freelancer_id"],
        "proposal_id": p["id"],
        "billing_type": posting["billing_type"],
        "sow_text": None,
        "agreed_amount_cents": p["bid_amount_cents"],
        "hourly_cap_hours": None,
        "status": "DRAFT",
    })
    db.contracts[contract["id"]] = contract
    return success(derive.proposal_view(p))


@bp.post("/proposals/<pid>/decline")
def decline(pid):
    user_id, role = require_auth()
    require_role(role, ["Client"])
    p = common.get_proposal(pid)
    posting = db.job_postings[p["job_posting_id"]]
    common.check_client_owns(role, user_id, posting["client_id"])
    if p["status"] not in LIVE:
        raise err("ERR_INVALID_PROPOSAL_STATE", "Proposal not open for declining")
    p["status"] = "DECLINED"
    db.touch(p)
    return success(derive.proposal_view(p))


@bp.post("/proposals/<pid>/withdraw")
def withdraw(pid):
    user_id, role = require_auth()
    require_role(role, ["Freelancer"])
    p = common.get_proposal(pid)
    common.check_freelancer_owns(role, user_id, p["freelancer_id"])
    if p["status"] not in LIVE:
        raise err("ERR_INVALID_PROPOSAL_STATE", "Proposal not open for withdrawal")
    p["status"] = "WITHDRAWN"
    db.touch(p)
    return success(derive.proposal_view(p))
