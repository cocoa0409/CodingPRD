"""Projects, commissions, contracts, milestones."""
from decimal import Decimal

from flask import Blueprint

import db
import serialize as S
from util import (
    ApiError, guard, body, ok, ok_list, ok_array, new_record, touch,
    require_str, require_int, require_number,
    round_half_up_cents, paginate_params, sort_and_page,
)

bp = Blueprint("budget", __name__)

MIN_PERCENT_RATE = 0.005
MAX_PERCENT_RATE = 0.05
DEFAULT_PERCENT_RATE = 0.01

ALL_ROLES = {"ProgramAdmin", "Registrar", "Artist", "Panelist"}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def get_project(pid):
    rec = db.projects.get(pid)
    if rec is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND", "project not found")
    return rec


def get_commission(cid):
    rec = db.commissions.get(cid)
    if rec is None:
        raise ApiError("ERR_COMMISSION_NOT_FOUND", "commission not found")
    return rec


def get_contract(cid):
    rec = db.contracts.get(cid)
    if rec is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", "contract not found")
    return rec


def get_milestone(mid):
    rec = db.milestones.get(mid)
    if rec is None:
        raise ApiError("ERR_MILESTONE_NOT_FOUND", "milestone not found")
    return rec


# ---------------------------------------------------------------------------
# CapitalProject
# ---------------------------------------------------------------------------
@bp.post("/projects")
def create_project():
    guard({"ProgramAdmin"})
    data = body()
    name = require_str(data, "name")
    construction = require_int(data, "construction_budget_cents", minimum=1)
    rate = DEFAULT_PERCENT_RATE
    if data.get("percent_rate") is not None:
        rate = require_number(data, "percent_rate")
        if rate < MIN_PERCENT_RATE or rate > MAX_PERCENT_RATE:
            raise ApiError("ERR_VALIDATION", "percent_rate out of range")
    art_budget = round_half_up_cents(Decimal(construction) * Decimal(str(rate)))
    rec = new_record({
        "name": name,
        "construction_budget_cents": construction,
        "certified_construction_budget_cents": None,
        "percent_rate": rate,
        "art_budget_cents": art_budget,
        "status": "DRAFT",
    })
    db.projects[rec["id"]] = rec
    return ok(S.project(rec), 201)


@bp.get("/projects/<pid>")
def fetch_project(pid):
    guard(ALL_ROLES)
    return ok(S.project(get_project(pid)))


@bp.post("/projects/<pid>/certify")
def certify_project(pid):
    guard({"ProgramAdmin"})
    rec = get_project(pid)
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "project is not DRAFT")
    data = body()
    certified = require_int(data, "certified_construction_budget_cents", minimum=1)
    rec["certified_construction_budget_cents"] = certified
    rec["art_budget_cents"] = round_half_up_cents(
        Decimal(certified) * Decimal(str(rec["percent_rate"]))
    )
    rec["status"] = "BUDGET_CERTIFIED"
    touch(rec)
    return ok(S.project(rec))


@bp.post("/projects/<pid>/commissions")
def create_commission(pid):
    guard({"ProgramAdmin"})
    project = get_project(pid)
    data = body()
    title = require_str(data, "title")
    allocation = require_int(data, "allocation_cents", minimum=1)
    expected = require_int(data, "expected_project_version")
    # OCC on parent project version
    if expected != project["version"]:
        raise ApiError("ERR_STALE_VERSION", "project version is stale")
    # Fiscal ceiling (inclusive boundary)
    committed = S.project_committed(project["id"])
    if committed + allocation > project["art_budget_cents"]:
        raise ApiError("ERR_ALLOCATION_EXCEEDS_BUDGET", "allocation exceeds art budget")
    rec = new_record({
        "project_id": project["id"],
        "title": title,
        "allocation_cents": allocation,
        "awarded_submission_id": None,
        "status": "OPEN",
    })
    db.commissions[rec["id"]] = rec
    touch(project)  # commission create bumps project.version
    return ok(S.commission(rec), 201)


# ---------------------------------------------------------------------------
# Commission
# ---------------------------------------------------------------------------
@bp.get("/commissions/<cid>")
def fetch_commission(cid):
    guard(ALL_ROLES)
    return ok(S.commission(get_commission(cid)))


@bp.get("/commissions")
def list_commissions():
    guard(ALL_ROLES)
    from flask import request
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    recs = [
        c for c in db.commissions.values()
        if (project_id is None or c["project_id"] == project_id)
        and (status is None or c["status"] == status)
    ]
    limit, offset = paginate_params()
    page, total = sort_and_page(recs, limit, offset)
    return ok_list([S.commission(c) for c in page], limit, offset, total)


@bp.post("/commissions/<cid>/award")
def award_commission(cid):
    guard({"ProgramAdmin"})
    commission = get_commission(cid)
    data = body()
    submission_id = require_str(data, "submission_id")
    submission = db.submissions.get(submission_id)
    if submission is None:
        raise ApiError("ERR_SUBMISSION_NOT_FOUND", "submission not found")
    if commission["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "commission is not OPEN")
    call = db.calls.get(submission["call_id"])
    if call is None or call["commission_id"] != commission["id"]:
        raise ApiError("ERR_SUBMISSION_CALL_MISMATCH", "submission does not belong to this commission")
    if call["status"] != "TABULATED":
        raise ApiError("ERR_INVALID_STATE", "call is not TABULATED")
    if submission["status"] != "SCORED":
        raise ApiError("ERR_INVALID_STATE", "submission is not SCORED")
    if submission["composite_score"] is None or submission["composite_score"] <= 0:
        raise ApiError("ERR_INVALID_STATE", "submission composite_score is not positive")
    # Perform award
    submission["status"] = "AWARDED"
    touch(submission)
    for sib in db.submissions.values():
        if sib["call_id"] == call["id"] and sib["status"] == "SCORED":
            sib["status"] = "REJECTED"
            touch(sib)
    commission["awarded_submission_id"] = submission["id"]
    commission["status"] = "AWARDED"
    touch(commission)
    return ok(S.commission(commission))


@bp.post("/commissions/<cid>/cancel")
def cancel_commission(cid):
    guard({"ProgramAdmin"})
    commission = get_commission(cid)
    if commission["status"] not in ("OPEN", "AWARDED"):
        raise ApiError("ERR_INVALID_STATE", "commission cannot be cancelled")
    commission["status"] = "CANCELLED"
    touch(commission)
    # Cascade to linked calls and their submissions
    for call in db.calls.values():
        if call["commission_id"] != commission["id"]:
            continue
        if call["status"] in ("OPEN", "CLOSED"):
            call["status"] = "CANCELLED"
            touch(call)
            for sub in db.submissions.values():
                if sub["call_id"] == call["id"] and sub["status"] in (
                    "SUBMITTED", "REVISION_REQUESTED", "SCORED"
                ):
                    sub["status"] = "WITHDRAWN"
                    touch(sub)
    return ok(S.commission(commission))


@bp.post("/commissions/<cid>/contracts")
def create_contract(cid):
    guard({"ProgramAdmin"})
    commission = get_commission(cid)
    data = body()
    submission_id = require_str(data, "submission_id")
    amount = require_int(data, "contract_amount_cents", minimum=1)
    submission = db.submissions.get(submission_id)
    if submission is None:
        raise ApiError("ERR_SUBMISSION_NOT_FOUND", "submission not found")
    if commission["status"] != "AWARDED":
        raise ApiError("ERR_INVALID_STATE", "commission is not AWARDED")
    if submission_id != commission["awarded_submission_id"]:
        raise ApiError("ERR_VALIDATION", "submission_id is not the awarded submission")
    if amount > commission["allocation_cents"]:
        raise ApiError("ERR_CONTRACT_EXCEEDS_ALLOCATION", "contract amount exceeds allocation")
    rec = new_record({
        "commission_id": commission["id"],
        "submission_id": submission_id,
        "contract_amount_cents": amount,
        "status": "DRAFT",
    })
    db.contracts[rec["id"]] = rec
    commission["status"] = "CONTRACTED"
    touch(commission)
    return ok(S.contract(rec), 201)


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------
@bp.get("/contracts/<cid>")
def fetch_contract(cid):
    guard(ALL_ROLES)
    return ok(S.contract(get_contract(cid)))


@bp.get("/contracts")
def list_contracts():
    guard(ALL_ROLES)
    from flask import request
    commission_id = request.args.get("commission_id")
    submission_id = request.args.get("submission_id")
    status = request.args.get("status")
    recs = [
        c for c in db.contracts.values()
        if (commission_id is None or c["commission_id"] == commission_id)
        and (submission_id is None or c["submission_id"] == submission_id)
        and (status is None or c["status"] == status)
    ]
    limit, offset = paginate_params()
    page, total = sort_and_page(recs, limit, offset)
    return ok_list([S.contract(c) for c in page], limit, offset, total)


@bp.post("/contracts/<cid>/activate")
def activate_contract(cid):
    guard({"ProgramAdmin"})
    contract = get_contract(cid)
    if contract["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "contract is not DRAFT")
    commission = db.commissions.get(contract["commission_id"])
    project = db.projects.get(commission["project_id"]) if commission else None
    if project is None or project["status"] != "BUDGET_CERTIFIED":
        raise ApiError("ERR_INVALID_STATE", "funding project is not BUDGET_CERTIFIED")
    pct_sum = sum(
        (Decimal(str(m["pct"])) for m in db.milestones.values() if m["contract_id"] == contract["id"]),
        Decimal("0"),
    )
    if pct_sum != Decimal("1"):
        raise ApiError("ERR_INVALID_STATE", "milestone pct values do not sum to 1.0")
    contract["status"] = "ACTIVE"
    touch(contract)
    artwork = new_record({
        "title": commission["title"] if commission else "Commissioned Artwork",
        "acquisition_type": "COMMISSION",
        "contract_id": contract["id"],
        "site_id": None,
        "appraised_value_cents": None,
        "install_date": None,
        "location_status": "FABRICATION",
        "condition_status": "GOOD",
        "deaccession_method": None,
        "deaccession_proceeds_cents": None,
    })
    db.artworks[artwork["id"]] = artwork
    return ok(S.contract(contract))


@bp.post("/contracts/<cid>/milestone-schedule")
def schedule_milestones(cid):
    guard({"ProgramAdmin"})
    contract = get_contract(cid)
    data = body()
    milestones_in = data.get("milestones")
    if not isinstance(milestones_in, list) or len(milestones_in) == 0:
        raise ApiError("ERR_VALIDATION", "milestones must be a non-empty list")
    expected = require_int(data, "expected_contract_version")
    parsed = []
    seen_seq = set()
    for entry in milestones_in:
        if not isinstance(entry, dict):
            raise ApiError("ERR_VALIDATION", "each milestone must be an object")
        seq = require_int(entry, "sequence", minimum=1)
        if seq in seen_seq:
            raise ApiError("ERR_VALIDATION", "duplicate milestone sequence")
        seen_seq.add(seq)
        title = require_str(entry, "title")
        pct = require_number(entry, "pct")
        pct_dec = Decimal(str(pct))
        if pct_dec <= 0 or pct_dec > 1:
            raise ApiError("ERR_VALIDATION", "pct must be in (0, 1]")
        parsed.append({"sequence": seq, "title": title, "pct": pct, "pct_dec": pct_dec})
    # pct sum must equal exactly 1.0
    total_pct = sum((p["pct_dec"] for p in parsed), Decimal("0"))
    if total_pct != Decimal("1"):
        raise ApiError("ERR_MILESTONE_PCT_SUM", "milestone pct values must sum to 1.0")
    # OCC on parent contract version
    if expected != contract["version"]:
        raise ApiError("ERR_STALE_VERSION", "contract version is stale")
    # Pinned waterfall allocation: round per line, final (highest seq) absorbs remainder
    ordered = sorted(parsed, key=lambda p: p["sequence"])
    amount = contract["contract_amount_cents"]
    running = 0
    created = []
    for p in ordered[:-1]:
        p["amount_cents"] = round_half_up_cents(Decimal(amount) * p["pct_dec"])
        running += p["amount_cents"]
    ordered[-1]["amount_cents"] = amount - running
    for p in ordered:
        rec = new_record({
            "contract_id": contract["id"],
            "sequence": p["sequence"],
            "title": p["title"],
            "pct": p["pct"],
            "amount_cents": p["amount_cents"],
            "status": "PENDING",
        })
        db.milestones[rec["id"]] = rec
        created.append(rec)
    touch(contract)  # scheduling bumps contract.version
    created.sort(key=lambda r: r["sequence"])
    return ok_array([S.milestone(m) for m in created], 201)


@bp.get("/contracts/<cid>/milestones")
def list_milestones(cid):
    guard(ALL_ROLES)
    contract = get_contract(cid)
    recs = [m for m in db.milestones.values() if m["contract_id"] == contract["id"]]
    limit, offset = paginate_params()
    page, total = sort_and_page(recs, limit, offset)
    return ok_list([S.milestone(m) for m in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Milestone
# ---------------------------------------------------------------------------
@bp.post("/milestones/<mid>/submit")
def submit_milestone(mid):
    from flask import g
    guard({"Artist"})
    milestone = get_milestone(mid)
    # Ownership: X-User-ID must be the awarded artist behind this contract
    contract = db.contracts.get(milestone["contract_id"])
    submission = db.submissions.get(contract["submission_id"]) if contract else None
    awarded_artist = submission["artist_id"] if submission else None
    if awarded_artist != g.user_id:
        raise ApiError("ERR_NOT_OWNER", "not the awarded artist for this milestone")
    if milestone["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "milestone is not PENDING")
    if contract is None or contract["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "parent contract is not ACTIVE")
    milestone["status"] = "SUBMITTED"
    touch(milestone)
    return ok(S.milestone(milestone))


@bp.post("/milestones/<mid>/approve")
def approve_milestone(mid):
    guard({"ProgramAdmin"})
    milestone = get_milestone(mid)
    contract = db.contracts.get(milestone["contract_id"])
    if milestone["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "milestone is not SUBMITTED")
    if contract is None or contract["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "parent contract is not ACTIVE")
    milestone["status"] = "PAID"
    touch(milestone)
    # Cascade1: payment ledger -> contract COMPLETED -> artwork FABRICATED -> commission FULFILLED
    paid = S.contract_paid(contract["id"])
    if paid == contract["contract_amount_cents"] and contract["status"] == "ACTIVE":
        contract["status"] = "COMPLETED"
        touch(contract)
        for art in db.artworks.values():
            if art["contract_id"] == contract["id"] and art["location_status"] == "FABRICATION":
                art["location_status"] = "FABRICATED"
                touch(art)
                commission = db.commissions.get(contract["commission_id"])
                if commission is not None and commission["status"] == "CONTRACTED":
                    commission["status"] = "FULFILLED"
                    touch(commission)
                break
    return ok(S.milestone(milestone))
