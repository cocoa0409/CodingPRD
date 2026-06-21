"""Contract, Milestone and TimeLog endpoints (PRD 3.3-3.8)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_auth, require_role
from response import success
from services import calc, common, derive, escrow

bp = Blueprint("contracts", __name__)

MILESTONE_TERMINAL = {"RELEASED", "REFUNDED", "CANCELLED"}


# ==========================================================================
# Contract lifecycle
# ==========================================================================
@bp.get("/contracts/<cid>")
def get_contract(cid):
    _, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client", "Freelancer"])
    c = common.get_contract(cid)
    return success(derive.contract_view(c))


@bp.post("/contracts/<cid>/activate")
def activate(cid):
    user_id, role = require_auth()
    require_role(role, ["Client"])
    c = common.get_contract(cid)
    common.check_client_owns(role, user_id, c["client_id"])
    body = common.get_body()
    sow_text = common.require_str(body, "sow_text")
    hourly_cap = body.get("hourly_cap_hours")
    if hourly_cap is not None:
        if isinstance(hourly_cap, bool) or not isinstance(hourly_cap, (int, float)):
            raise err("ERR_INVALID_REQUEST", "hourly_cap_hours must be a number")
    if c["status"] != "DRAFT":
        raise err("ERR_INVALID_CONTRACT_STATE", "Contract must be DRAFT to activate")
    c["sow_text"] = sow_text
    if c["billing_type"] == "HOURLY":
        c["hourly_cap_hours"] = hourly_cap
    c["status"] = "ACTIVE"
    db.touch(c)
    # cross-entity: awarded posting -> CLOSED
    posting = db.job_postings.get(_posting_for_contract(c))
    if posting and posting["status"] == "AWARDED":
        posting["status"] = "CLOSED"
        db.touch(posting)
    return success(derive.contract_view(c))


def _posting_for_contract(contract):
    prop = db.proposals.get(contract["proposal_id"])
    return prop["job_posting_id"] if prop else None


@bp.post("/contracts/<cid>/complete")
def complete(cid):
    user_id, role = require_auth()
    require_role(role, ["Client"])
    c = common.get_contract(cid)
    common.check_client_owns(role, user_id, c["client_id"])
    if c["status"] != "ACTIVE":
        raise err("ERR_INVALID_CONTRACT_STATE", "Contract must be ACTIVE to complete")
    if derive.contract_open_milestone_count(cid) > 0 \
            or derive.contract_open_dispute_count(cid) > 0:
        raise err("ERR_CONTRACT_HAS_OPEN_ITEMS", "Contract has open milestones or disputes")
    c["status"] = "COMPLETED"
    db.touch(c)
    freelancer = db.freelancers[c["freelancer_id"]]
    derive.recompute_freelancer_reputation(freelancer)
    return success(derive.contract_view(c))


@bp.post("/contracts/<cid>/terminate")
def terminate(cid):
    user_id, role = require_auth()
    require_role(role, ["Client"])
    c = common.get_contract(cid)
    common.check_client_owns(role, user_id, c["client_id"])
    if c["status"] not in ("DRAFT", "ACTIVE"):
        raise err("ERR_INVALID_CONTRACT_STATE", "Contract not in DRAFT/ACTIVE to terminate")
    if derive.contract_open_dispute_count(cid) > 0:
        raise err("ERR_CONTRACT_HAS_OPEN_ITEMS", "Contract has open disputes")
    # cascade hop 1: cancel milestones; hop 2: refund held escrow
    for m in db.milestones.values():
        if m["contract_id"] != cid:
            continue
        if m["status"] in ("DRAFT", "FUNDED", "SUBMITTED", "APPROVED"):
            funded = derive.milestone_funded_cents(m["id"])
            m["status"] = "CANCELLED"
            db.touch(m)
            if funded > 0:
                escrow.refund_full(c, m)
    c["status"] = "TERMINATED"
    db.touch(c)
    derive.recompute_freelancer_reputation(db.freelancers[c["freelancer_id"]])
    return success(derive.contract_view(c))


# ==========================================================================
# Contract-scoped lists
# ==========================================================================
@bp.get("/contracts/<cid>/milestones")
def list_milestones(cid):
    _, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client", "Freelancer"])
    common.get_contract(cid)
    items = [m for m in db.milestones.values() if m["contract_id"] == cid]
    items = common.sort_by_created(items)
    page, meta = common.paginate(items)
    return success([derive.milestone_view(m) for m in page], pagination=meta)


@bp.get("/contracts/<cid>/timelogs")
def list_timelogs(cid):
    _, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client", "Freelancer"])
    common.get_contract(cid)
    milestone_id = request.args.get("milestone_id")
    work_date = request.args.get("work_date")
    items = [t for t in db.timelogs.values() if t["contract_id"] == cid]
    if milestone_id is not None:
        items = [t for t in items if t["milestone_id"] == milestone_id]
    if work_date is not None:
        items = [t for t in items if t["work_date"] == work_date]
    items = common.sort_by_created(items)
    page, meta = common.paginate(items)
    return success([derive.timelog_view(t) for t in page], pagination=meta)


@bp.get("/contracts/<cid>/escrow-transactions")
def list_escrow(cid):
    _, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client", "Freelancer"])
    common.get_contract(cid)
    milestone_id = request.args.get("milestone_id")
    items = [e for e in db.escrow_transactions.values() if e["contract_id"] == cid]
    if milestone_id is not None:
        items = [e for e in items if e["milestone_id"] == milestone_id]
    items = common.sort_by_created(items)
    page, meta = common.paginate(items)
    return success([derive.escrow_view(e) for e in page], pagination=meta)


@bp.get("/contracts/<cid>/disputes")
def list_disputes(cid):
    _, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client", "Freelancer", "Arbitrator"])
    common.get_contract(cid)
    items = [d for d in db.disputes.values() if d["contract_id"] == cid]
    items = common.sort_by_created(items)
    page, meta = common.paginate(items)
    return success([derive.dispute_view(d) for d in page], pagination=meta)


@bp.get("/contracts/<cid>/reviews")
def list_reviews(cid):
    _, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client", "Freelancer"])
    common.get_contract(cid)
    items = [r for r in db.reviews.values() if r["contract_id"] == cid]
    items = common.sort_by_created(items)
    page, meta = common.paginate(items)
    return success([derive.review_view(r) for r in page], pagination=meta)


# ==========================================================================
# Milestones
# ==========================================================================
@bp.post("/contracts/<cid>/milestones")
def create_milestone(cid):
    user_id, role = require_auth()
    require_role(role, ["Client"])
    c = common.get_contract(cid)
    common.check_client_owns(role, user_id, c["client_id"])
    body = common.get_body()
    title = common.require_str(body, "title")
    ordinal = common.require_int(body, "ordinal", minimum=1)
    # FIXED requires amount_cents >= 100; HOURLY recomputed from verified time
    if c["billing_type"] == "FIXED":
        amount = common.require_int(body, "amount_cents", minimum=100)
    else:
        amount = 0
    if c["status"] != "ACTIVE":
        raise err("ERR_INVALID_CONTRACT_STATE", "Contract must be ACTIVE to add milestones")
    # ordinal unique within contract
    for m in db.milestones.values():
        if m["contract_id"] == cid and m["ordinal"] == ordinal:
            raise err("ERR_DUPLICATE_MILESTONE_ORDINAL", "Ordinal already used in contract")
    rec = db.new_common()
    rec.update({
        "contract_id": cid,
        "title": title,
        "amount_cents": amount,
        "ordinal": ordinal,
        "status": "DRAFT",
    })
    db.milestones[rec["id"]] = rec
    return success(derive.milestone_view(rec), status=201)


@bp.get("/contracts/<cid>/milestones/<mid>")
def get_milestone_scoped(cid, mid):
    _, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client", "Freelancer"])
    common.get_contract(cid)
    m = common.get_milestone_in_contract(cid, mid)
    return success(derive.milestone_view(m))


@bp.post("/contracts/<cid>/milestones/<mid>/fund")
def fund_milestone(cid, mid):
    user_id, role = require_auth()
    require_role(role, ["Client"])
    c = common.get_contract(cid)
    m = common.get_milestone_in_contract(cid, mid)
    common.check_client_owns(role, user_id, c["client_id"])
    body = common.get_body()
    expected = common.require_int(body, "expected_contract_version")
    # state: milestone DRAFT
    if m["status"] != "DRAFT":
        raise err("ERR_INVALID_MILESTONE_STATE", "Milestone must be DRAFT to fund")
    # cross-entity: contract ACTIVE
    if c["status"] != "ACTIVE":
        raise err("ERR_CONTRACT_NOT_ACTIVE", "Contract must be ACTIVE to fund")
    # wallet sufficiency (priority 13)
    client = db.clients[c["client_id"]]
    if client["wallet_balance_cents"] < m["amount_cents"]:
        raise err("ERR_INSUFFICIENT_WALLET", "Wallet balance below funding amount")
    # OCC (priority 14)
    if expected != c["version"]:
        raise err("ERR_STALE_CONTRACT_VERSION", "expected_contract_version is stale")
    escrow.fund(c, m, m["amount_cents"])
    m["status"] = "FUNDED"
    db.touch(m)
    c["version"] += 1
    from response import now_iso
    c["updated_at"] = now_iso()
    return success(derive.milestone_view(m))


@bp.post("/contracts/<cid>/milestones/<mid>/submit-work")
def submit_work(cid, mid):
    user_id, role = require_auth()
    require_role(role, ["Freelancer"])
    c = common.get_contract(cid)
    m = common.get_milestone_in_contract(cid, mid)
    common.check_freelancer_owns(role, user_id, c["freelancer_id"])
    if m["status"] != "FUNDED":
        raise err("ERR_INVALID_MILESTONE_STATE", "Milestone must be FUNDED to submit")
    if c["status"] != "ACTIVE":
        raise err("ERR_CONTRACT_NOT_ACTIVE", "Contract must be ACTIVE to submit")
    if c["billing_type"] == "HOURLY":
        has_verified = any(
            t["milestone_id"] == mid and t["status"] == "VERIFIED"
            for t in db.timelogs.values()
        )
        if not has_verified:
            raise err("ERR_NO_VERIFIED_TIMELOGS", "No VERIFIED timelogs for milestone")
    m["status"] = "SUBMITTED"
    db.touch(m)
    return success(derive.milestone_view(m))


@bp.post("/contracts/<cid>/milestones/<mid>/approve")
def approve_milestone(cid, mid):
    user_id, role = require_auth()
    require_role(role, ["Client"])
    c = common.get_contract(cid)
    m = common.get_milestone_in_contract(cid, mid)
    common.check_client_owns(role, user_id, c["client_id"])
    if m["status"] != "SUBMITTED":
        raise err("ERR_INVALID_MILESTONE_STATE", "Milestone must be SUBMITTED to approve")
    m["status"] = "APPROVED"
    db.touch(m)
    return success(derive.milestone_view(m))


@bp.post("/contracts/<cid>/milestones/<mid>/release")
def release_milestone(cid, mid):
    user_id, role = require_auth()
    require_role(role, ["Client"])
    c = common.get_contract(cid)
    m = common.get_milestone_in_contract(cid, mid)
    common.check_client_owns(role, user_id, c["client_id"])
    body = common.get_body()
    expected = common.require_int(body, "expected_contract_version")
    if m["status"] != "APPROVED":
        raise err("ERR_INVALID_MILESTONE_STATE", "Milestone must be APPROVED to release")
    if expected != c["version"]:
        raise err("ERR_STALE_CONTRACT_VERSION", "expected_contract_version is stale")
    escrow.release_full(c, m)
    return success(derive.milestone_view(m))


@bp.post("/contracts/<cid>/milestones/<mid>/dispute")
def open_dispute(cid, mid):
    user_id, role = require_auth()
    require_role(role, ["Client", "Freelancer"])
    c = common.get_contract(cid)
    m = common.get_milestone_in_contract(cid, mid)
    body = common.get_body()
    raised_by = common.require_enum(body, "raised_by", {"CLIENT", "FREELANCER"})
    reason = common.require_str(body, "reason")
    funded = derive.milestone_funded_cents(mid)
    claimed = common.require_int(body, "claimed_release_cents", minimum=0, maximum=funded)
    # ownership: acting party must own its side
    if role == "Client":
        common.check_client_owns(role, user_id, c["client_id"])
    else:
        common.check_freelancer_owns(role, user_id, c["freelancer_id"])
    if m["status"] != "SUBMITTED":
        raise err("ERR_INVALID_MILESTONE_STATE", "Milestone must be SUBMITTED to dispute")
    m["status"] = "DISPUTED"
    db.touch(m)
    rec = db.new_common()
    rec.update({
        "contract_id": cid,
        "milestone_id": mid,
        "raised_by": raised_by,
        "reason": reason,
        "claimed_release_cents": claimed,
        "arbitrator_award_cents": None,
        "resolution": None,
        "status": "OPEN",
    })
    db.disputes[rec["id"]] = rec
    return success(derive.dispute_view(rec), status=201)


# ==========================================================================
# TimeLogs
# ==========================================================================
@bp.post("/contracts/<cid>/timelogs")
def create_timelog(cid):
    user_id, role = require_auth()
    require_role(role, ["Freelancer"])
    c = common.get_contract(cid)
    common.check_freelancer_owns(role, user_id, c["freelancer_id"])
    body = common.get_body()
    milestone_id = common.require_str(body, "milestone_id")
    work_date = common.require_str(body, "work_date")
    start_minute = common.require_int(body, "start_minute", minimum=0, maximum=1439)
    end_minute = common.require_int(body, "end_minute", minimum=1, maximum=1440)
    memo = common.require_str(body, "memo")
    if end_minute <= start_minute:
        raise err("ERR_INVALID_REQUEST", "end_minute must be greater than start_minute")
    # existence: milestone belongs to this contract
    m = common.get_milestone_in_contract(cid, milestone_id)
    billable = end_minute - start_minute

    # (A) same-milestone half-open overlap check (priority 9)
    for t in db.timelogs.values():
        if t["milestone_id"] != milestone_id or t["work_date"] != work_date:
            continue
        if t["status"] not in ("LOGGED", "VERIFIED"):
            continue
        if start_minute < t["end_minute"] and t["start_minute"] < end_minute:
            raise err("ERR_TIMELOG_OVERLAP", "Interval overlaps an existing timelog")

    # (B) cross-contract daily aggregate cap (priority 10)
    existing = 0
    for t in db.timelogs.values():
        if t["freelancer_id"] != c["freelancer_id"] or t["work_date"] != work_date:
            continue
        if t["status"] in ("LOGGED", "VERIFIED"):
            existing += t["billable_minutes"]
    if existing + billable > calc.GLOBAL_DAILY_MINUTE_CAP:
        raise err("ERR_DAILY_HOURS_CAP_EXCEEDED", "Daily hours cap exceeded")

    rec = db.new_common()
    rec.update({
        "contract_id": cid,
        "milestone_id": milestone_id,
        "freelancer_id": c["freelancer_id"],
        "work_date": work_date,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "billable_minutes": billable,
        "memo": memo,
        "status": "LOGGED",
    })
    db.timelogs[rec["id"]] = rec
    return success(derive.timelog_view(rec), status=201)


@bp.post("/contracts/<cid>/timelogs/<tid>/verify")
def verify_timelog(cid, tid):
    user_id, role = require_auth()
    require_role(role, ["Client"])
    c = common.get_contract(cid)
    t = common.get_timelog_in_contract(cid, tid)
    common.check_client_owns(role, user_id, c["client_id"])
    if t["status"] != "LOGGED":
        raise err("ERR_INVALID_TIMELOG_STATE", "TimeLog must be LOGGED to verify")
    if c["status"] != "ACTIVE":
        raise err("ERR_CONTRACT_NOT_ACTIVE", "Contract must be ACTIVE to verify")
    t["status"] = "VERIFIED"
    db.touch(t)
    _recompute_hourly_milestone(c, t["milestone_id"])
    return success(derive.timelog_view(t))


@bp.post("/contracts/<cid>/timelogs/<tid>/reject")
def reject_timelog(cid, tid):
    user_id, role = require_auth()
    require_role(role, ["Client"])
    c = common.get_contract(cid)
    t = common.get_timelog_in_contract(cid, tid)
    common.check_client_owns(role, user_id, c["client_id"])
    if t["status"] != "LOGGED":
        raise err("ERR_INVALID_TIMELOG_STATE", "TimeLog must be LOGGED to reject")
    t["status"] = "REJECTED"
    db.touch(t)
    return success(derive.timelog_view(t))


def _recompute_hourly_milestone(contract, milestone_id):
    m = db.milestones.get(milestone_id)
    if not m:
        return
    verified = [
        t for t in db.timelogs.values()
        if t["milestone_id"] == milestone_id and t["status"] == "VERIFIED"
    ]
    m["amount_cents"] = calc.hourly_milestone_amount(verified, contract["agreed_amount_cents"])
    db.touch(m)
