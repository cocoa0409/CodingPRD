"""Scholarship programs, committees, applications, scoring, awards."""
from decimal import Decimal

from flask import Blueprint, g, request

from common import (
    STORE, body, err, get_path, get_ref, list_response, new_resource, now,
    parse_dt, q2, reactivate_if_inactive, req_decimal, req_int, req_present,
    require_roles, serialize, success, touch,
)

bp = Blueprint("scholarship", __name__)

W_ACADEMIC = Decimal("0.40")
W_NEED = Decimal("0.30")
W_ESSAY = Decimal("0.20")
W_INTERVIEW = Decimal("0.10")
MIN_AWARD_AMOUNT = Decimal("500.00")


def program_view(p):
    return serialize(p)


def member_view(m):
    return serialize(m)


def application_view(a):
    return serialize(a)


def score_view(s):
    return serialize(s)


def award_view(a):
    return serialize(a)


def quorum_for(committee_size):
    return committee_size // 2 + 1


def program_applications(program_id):
    return [a for a in STORE["applications"].values() if a["program_id"] == program_id]


def recompute_final_score(app):
    """final_score = mean of weighted_score over entries whose member was SEATED
    at scoring time, once their count reaches the program's current quorum."""
    program = STORE["programs"][app["program_id"]]
    entries = [
        s for s in STORE["scores"].values()
        if s["application_id"] == app["id"] and s["_seated_at_scoring"]
    ]
    if len(entries) >= program["quorum_threshold"]:
        mean = sum(s["weighted_score"] for s in entries) / Decimal(len(entries))
        new_score = q2(mean)
    else:
        new_score = None
    if new_score != app["final_score"]:
        app["final_score"] = new_score
        touch(app)


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------
@bp.post("/funds/<fundId>/scholarship-programs")
@require_roles("ProgramOfficer")
def create_program(fundId):
    f = get_path("funds", fundId)
    data = body()
    name = data.get("program_name")
    if name is not None:
        for p in STORE["programs"].values():
            if p["program_name"] == name:
                err("ERR_UNIQUENESS_VIOLATION", 409, "program_name must be unique")
    name = req_present(data, "program_name")
    award_amount = req_decimal(data, "award_amount")
    if award_amount < MIN_AWARD_AMOUNT:
        err("ERR_FIELD_CONSTRAINT", 422, "award_amount must be at least 500.00")
    max_awards = req_int(data, "max_awards")
    if max_awards < 1:
        err("ERR_FIELD_CONSTRAINT", 422, "max_awards must be >= 1")
    app_open = parse_dt(data.get("application_open"), "application_open")
    app_close = parse_dt(data.get("application_close"), "application_close")
    if not app_close > app_open:
        err("ERR_FIELD_CONSTRAINT", 422,
            "application_close must be strictly after application_open")
    if f["fund_type"] != "SCHOLARSHIP":
        err("ERR_FIELD_CONSTRAINT", 422,
            "Scholarship programs may be established only on SCHOLARSHIP funds")
    p = new_resource()
    p.update({
        "fund_id": f["id"],
        "program_name": name,
        "status": "SETUP",
        "application_open": app_open,
        "application_close": app_close,
        "award_amount": q2(award_amount),
        "max_awards": max_awards,
        "committee_size": 0,
        "quorum_threshold": quorum_for(0),
    })
    STORE["programs"][p["id"]] = p
    return success(program_view(p), code=201)


@bp.get("/funds/<fundId>/scholarship-programs")
@require_roles("FoundationAdmin", "ProgramOfficer", "Applicant", "CommitteeMember")
def list_fund_programs(fundId):
    f = get_path("funds", fundId)
    items = [p for p in STORE["programs"].values() if p["fund_id"] == f["id"]]
    return list_response(items, program_view)


@bp.get("/programs/<programId>")
@require_roles("FoundationAdmin", "ProgramOfficer", "Applicant", "CommitteeMember")
def get_program(programId):
    return success(program_view(get_path("programs", programId)))


@bp.get("/programs")
@require_roles("FoundationAdmin", "ProgramOfficer")
def list_programs():
    items = list(STORE["programs"].values())
    fid = request.args.get("fund_id")
    if fid is not None:
        items = [p for p in items if p["fund_id"] == fid]
    return list_response(items, program_view)


@bp.post("/programs/<programId>/open")
@require_roles("ProgramOfficer")
def open_program(programId):
    p = get_path("programs", programId)
    if p["status"] != "SETUP":
        err("ERR_INVALID_STATE", 409, "Only a SETUP program can be opened")
    if p["committee_size"] < 3:
        err("ERR_COMMITTEE_TOO_SMALL", 422,
            "Program requires a committee of at least 3 seated members")
    if not p["application_close"] > p["application_open"]:
        err("ERR_FIELD_CONSTRAINT", 422,
            "application_close must be strictly after application_open")
    if now() >= p["application_close"]:
        err("ERR_OUTSIDE_WINDOW", 422,
            "The application window has already closed")
    p["status"] = "OPEN"
    touch(p)
    return success(program_view(p))


@bp.post("/programs/<programId>/close-applications")
@require_roles("ProgramOfficer")
def close_applications(programId):
    p = get_path("programs", programId)
    if p["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "Only an OPEN program can close applications")
    if now() < p["application_close"]:
        err("ERR_OUTSIDE_WINDOW", 422,
            "The application window has not yet closed")
    apps = program_applications(p["id"])
    if len(apps) < 1:
        err("ERR_NO_APPLICATIONS", 422, "Program has no applications")
    p["status"] = "SCORING"
    touch(p)
    for a in apps:
        if a["status"] == "SUBMITTED":
            a["status"] = "UNDER_SCORING"
            touch(a)
    return success(program_view(p))


@bp.post("/programs/<programId>/select-winners")
@require_roles("ProgramOfficer")
def select_winners(programId):
    p = get_path("programs", programId)
    data = body()
    winners = data.get("winner_application_ids")
    # Body reference existence (priority 4).
    if winners is not None:
        if not isinstance(winners, list):
            err("ERR_FIELD_CONSTRAINT", 422, "winner_application_ids must be a list")
        for wid in winners:
            get_ref("applications", wid, "application")
    # State (priority 5).
    if p["status"] != "SCORING":
        err("ERR_INVALID_STATE", 409, "Only a SCORING program can select winners")
    if winners is None:
        err("ERR_FIELD_CONSTRAINT", 422, "winner_application_ids is required")
    apps = program_applications(p["id"])
    # PRD endpoint order: quorum, slate size, per-winner scoring, cross-reference, cash.
    if not any(a["final_score"] is not None for a in apps):
        err("ERR_QUORUM_NOT_MET", 422,
            "No application has reached the scoring quorum")
    if len(winners) > p["max_awards"]:
        err("ERR_TOO_MANY_WINNERS", 422, "Winner slate exceeds max_awards")
    winner_apps = [STORE["applications"][w] for w in winners]
    for a in winner_apps:
        if a["final_score"] is None:
            err("ERR_UNSCORED_WINNER", 422,
                "Every winner application must have a final score")
    for a in winner_apps:
        if a["program_id"] != p["id"]:
            err("ERR_CROSS_REFERENCE_MISMATCH", 422,
                "Winner applications must belong to this program")
    f = STORE["funds"][p["fund_id"]]
    if Decimal(p["max_awards"]) * p["award_amount"] > f["cash_balance"]:
        err("ERR_INSUFFICIENT_CASH", 422,
            "Program maximum outlay exceeds the fund's cash balance")
    winner_ids = set(winners)
    award_ids = []
    for a in apps:
        if a["status"] != "UNDER_SCORING":
            continue
        if a["id"] in winner_ids:
            a["status"] = "SELECTED"
        else:
            a["status"] = "NOT_SELECTED"
        touch(a)
    for a in winner_apps:
        aw = new_resource()
        aw.update({
            "application_id": a["id"],
            "program_id": p["id"],
            "fund_id": f["id"],
            "amount": q2(p["award_amount"]),
            "status": "OFFERED",
        })
        STORE["awards"][aw["id"]] = aw
        award_ids.append(aw["id"])
    p["status"] = "AWARDED"
    touch(p)
    return success({"award_ids": award_ids, "selected_count": len(award_ids)})


@bp.post("/programs/<programId>/close")
@require_roles("ProgramOfficer")
def close_program(programId):
    p = get_path("programs", programId)
    if p["status"] != "AWARDED":
        err("ERR_INVALID_STATE", 409, "Only an AWARDED program can be closed")
    if any(a for a in STORE["awards"].values()
           if a["program_id"] == p["id"] and a["status"] in ("OFFERED", "ACCEPTED")):
        err("ERR_AWARDS_PENDING", 409, "Program has awards still pending")
    p["status"] = "CLOSED"
    touch(p)
    return success(program_view(p))


@bp.post("/programs/<programId>/cancel")
@require_roles("ProgramOfficer")
def cancel_program(programId):
    p = get_path("programs", programId)
    if p["status"] != "SETUP":
        err("ERR_INVALID_STATE", 409, "Only a SETUP program can be cancelled")
    p["status"] = "CANCELLED"
    touch(p)
    return success(program_view(p))


# ---------------------------------------------------------------------------
# Committee members
# ---------------------------------------------------------------------------
@bp.post("/programs/<programId>/committee-members")
@require_roles("ProgramOfficer")
def seat_member(programId):
    p = get_path("programs", programId)
    data = body()
    email = data.get("email")
    if email is not None:
        for m in STORE["members"].values():
            if m["program_id"] == p["id"] and m["email"] == email:
                err("ERR_UNIQUENESS_VIOLATION", 409,
                    "Committee member email must be unique per program")
    name = req_present(data, "member_name")
    email = req_present(data, "email")
    if p["status"] not in ("SETUP", "OPEN"):
        err("ERR_PROGRAM_LOCKED", 409,
            "Committee mutation is allowed only while the program is SETUP or OPEN")
    m = new_resource()
    m.update({
        "program_id": p["id"],
        "member_name": name,
        "email": email,
        "status": "SEATED",
    })
    STORE["members"][m["id"]] = m
    p["committee_size"] += 1
    p["quorum_threshold"] = quorum_for(p["committee_size"])
    touch(p)
    return success(member_view(m), code=201)


@bp.get("/programs/<programId>/committee-members")
@require_roles("FoundationAdmin", "ProgramOfficer", "CommitteeMember")
def list_program_members(programId):
    p = get_path("programs", programId)
    items = [m for m in STORE["members"].values() if m["program_id"] == p["id"]]
    return list_response(items, member_view)


@bp.get("/committee-members/<memberId>")
@require_roles("FoundationAdmin", "ProgramOfficer", "CommitteeMember")
def get_member(memberId):
    return success(member_view(get_path("members", memberId)))


@bp.get("/committee-members")
@require_roles("FoundationAdmin", "ProgramOfficer")
def list_members():
    items = list(STORE["members"].values())
    pid = request.args.get("program_id")
    if pid is not None:
        items = [m for m in items if m["program_id"] == pid]
    return list_response(items, member_view)


def _shrink_committee(program):
    program["committee_size"] = max(0, program["committee_size"] - 1)
    program["quorum_threshold"] = quorum_for(program["committee_size"])
    touch(program)
    # Quorum may have dropped: maintain final_score continuously.
    for app in program_applications(program["id"]):
        recompute_final_score(app)


@bp.post("/committee-members/<memberId>/recuse")
@require_roles("CommitteeMember")
def recuse_member(memberId):
    m = get_path("members", memberId)
    if m["status"] != "SEATED":
        err("ERR_INVALID_STATE", 409, "Only a SEATED member can recuse")
    if g.uid != m["id"]:
        err("ERR_NOT_THE_MEMBER", 403, "A member may recuse only themself")
    m["status"] = "RECUSED"
    touch(m)
    _shrink_committee(STORE["programs"][m["program_id"]])
    return success(member_view(m))


@bp.post("/committee-members/<memberId>/remove")
@require_roles("ProgramOfficer")
def remove_member(memberId):
    m = get_path("members", memberId)
    if m["status"] != "SEATED":
        err("ERR_INVALID_STATE", 409, "Only a SEATED member can be removed")
    p = STORE["programs"][m["program_id"]]
    if p["status"] not in ("SETUP", "OPEN"):
        err("ERR_PROGRAM_LOCKED", 409,
            "Committee mutation is allowed only while the program is SETUP or OPEN")
    m["status"] = "REMOVED"
    touch(m)
    _shrink_committee(p)
    return success(member_view(m))


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
@bp.post("/programs/<programId>/applications")
@require_roles("Applicant")
def create_application(programId):
    p = get_path("programs", programId)
    data = body()
    email = data.get("applicant_email")
    # Time window (priority 7): clock at/after open and strictly before close.
    if not (p["application_open"] <= now() < p["application_close"]):
        err("ERR_OUTSIDE_WINDOW", 422,
            "Applications are accepted only inside [application_open, application_close)")
    # Uniqueness (priority 11).
    if email is not None:
        for a in STORE["applications"].values():
            if a["program_id"] == p["id"] and a["applicant_email"] == email:
                err("ERR_UNIQUENESS_VIOLATION", 409,
                    "applicant_email must be unique per program")
    name = req_present(data, "applicant_name")
    email = req_present(data, "applicant_email")
    a = new_resource()
    a.update({
        "program_id": p["id"],
        "applicant_name": name,
        "applicant_email": email,
        "status": "SUBMITTED",
        "final_score": None,
    })
    STORE["applications"][a["id"]] = a
    return success(application_view(a), code=201)


@bp.get("/programs/<programId>/applications")
@require_roles("FoundationAdmin", "ProgramOfficer", "CommitteeMember")
def list_program_applications(programId):
    p = get_path("programs", programId)
    items = program_applications(p["id"])
    st = request.args.get("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    return list_response(items, application_view)


@bp.get("/applications/<applicationId>")
@require_roles("FoundationAdmin", "ProgramOfficer", "CommitteeMember", "Applicant")
def get_application(applicationId):
    return success(application_view(get_path("applications", applicationId)))


@bp.get("/applications")
@require_roles("FoundationAdmin", "ProgramOfficer")
def list_applications():
    items = list(STORE["applications"].values())
    pid = request.args.get("program_id")
    if pid is not None:
        items = [a for a in items if a["program_id"] == pid]
    return list_response(items, application_view)


# ---------------------------------------------------------------------------
# Score entries
# ---------------------------------------------------------------------------
@bp.post("/applications/<applicationId>/scores")
@require_roles("CommitteeMember")
def create_score(applicationId):
    app = get_path("applications", applicationId)
    data = body()
    member_id = data.get("member_id")
    member = None
    if member_id is not None:
        member = get_ref("members", member_id, "committee member")
    member_id = req_present(data, "member_id")
    member = get_ref("members", member_id, "committee member")
    # State (priority 5): scoring happens while the application is UNDER_SCORING.
    if app["status"] != "UNDER_SCORING":
        err("ERR_INVALID_STATE", 409,
            "Only an UNDER_SCORING application can be scored")
    # Cross-reference (priority 8): member must be seated on this program's committee.
    if member["program_id"] != app["program_id"] or member["status"] != "SEATED":
        err("ERR_CROSS_REFERENCE_MISMATCH", 422,
            "The scoring member must be seated on the program that owns the application")
    # Self-service (priority 9): the acting member scores as themself.
    if g.uid != member["id"]:
        err("ERR_NOT_THE_MEMBER", 403,
            "A committee member may score only as themself")
    # Field domain (priority 12).
    components = {}
    for name in ("academic", "financial_need", "essay", "interview"):
        v = req_int(data, name)
        if v < 0 or v > 100:
            err("ERR_FIELD_CONSTRAINT", 422, f"{name} must be within 0-100")
        components[name] = v
    # One score per member per application (priority 15).
    for s in STORE["scores"].values():
        if s["application_id"] == app["id"] and s["member_id"] == member["id"]:
            err("ERR_DUPLICATE_SCORE", 409,
                "This member has already scored this application")
    weighted = q2(
        W_ACADEMIC * components["academic"]
        + W_NEED * components["financial_need"]
        + W_ESSAY * components["essay"]
        + W_INTERVIEW * components["interview"]
    )
    s = new_resource(common_fields=False)
    s.update({
        "application_id": app["id"],
        "member_id": member["id"],
        "academic": components["academic"],
        "financial_need": components["financial_need"],
        "essay": components["essay"],
        "interview": components["interview"],
        "weighted_score": weighted,
        "_seated_at_scoring": member["status"] == "SEATED",
    })
    STORE["scores"][s["id"]] = s
    recompute_final_score(app)
    return success(score_view(s), code=201)


@bp.get("/applications/<applicationId>/scores")
@require_roles("FoundationAdmin", "ProgramOfficer")
def list_application_scores(applicationId):
    app = get_path("applications", applicationId)
    items = [s for s in STORE["scores"].values() if s["application_id"] == app["id"]]
    return list_response(items, score_view)


@bp.get("/scores/<scoreId>")
@require_roles("FoundationAdmin", "ProgramOfficer")
def get_score(scoreId):
    return success(score_view(get_path("scores", scoreId)))


@bp.get("/scores")
@require_roles("FoundationAdmin", "ProgramOfficer")
def list_scores():
    items = list(STORE["scores"].values())
    aid = request.args.get("application_id")
    mid = request.args.get("member_id")
    if aid is not None:
        items = [s for s in items if s["application_id"] == aid]
    if mid is not None:
        items = [s for s in items if s["member_id"] == mid]
    return list_response(items, score_view)


# ---------------------------------------------------------------------------
# Awards
# ---------------------------------------------------------------------------
@bp.get("/programs/<programId>/awards")
@require_roles("FoundationAdmin", "ProgramOfficer", "FinanceOfficer", "Applicant")
def list_program_awards(programId):
    p = get_path("programs", programId)
    items = [a for a in STORE["awards"].values() if a["program_id"] == p["id"]]
    return list_response(items, award_view)


@bp.get("/awards/<awardId>")
@require_roles("FoundationAdmin", "ProgramOfficer", "FinanceOfficer", "Applicant")
def get_award(awardId):
    return success(award_view(get_path("awards", awardId)))


@bp.get("/awards")
@require_roles("FoundationAdmin", "ProgramOfficer", "FinanceOfficer")
def list_awards():
    items = list(STORE["awards"].values())
    aid = request.args.get("application_id")
    pid = request.args.get("program_id")
    fid = request.args.get("fund_id")
    if aid is not None:
        items = [a for a in items if a["application_id"] == aid]
    if pid is not None:
        items = [a for a in items if a["program_id"] == pid]
    if fid is not None:
        items = [a for a in items if a["fund_id"] == fid]
    return list_response(items, award_view)


def _award_self_check(award):
    app = STORE["applications"][award["application_id"]]
    if g.uid != app["id"]:
        err("ERR_NOT_THE_APPLICANT", 403,
            "Only the applicant themself may respond to the award offer")
    return app


@bp.post("/awards/<awardId>/accept")
@require_roles("Applicant")
def accept_award(awardId):
    aw = get_path("awards", awardId)
    if aw["status"] != "OFFERED":
        err("ERR_INVALID_STATE", 409, "Only an OFFERED award can be accepted")
    app = _award_self_check(aw)
    aw["status"] = "ACCEPTED"
    touch(aw)
    app["status"] = "ACCEPTED_AWARD"
    touch(app)
    return success(award_view(aw))


@bp.post("/awards/<awardId>/decline")
@require_roles("Applicant")
def decline_award(awardId):
    aw = get_path("awards", awardId)
    if aw["status"] != "OFFERED":
        err("ERR_INVALID_STATE", 409, "Only an OFFERED award can be declined")
    app = _award_self_check(aw)
    aw["status"] = "DECLINED"
    touch(aw)
    app["status"] = "DECLINED_AWARD"
    touch(app)
    # Declining never auto-closes the program.
    return success(award_view(aw))


@bp.post("/awards/<awardId>/disburse")
@require_roles("FinanceOfficer")
def disburse_award(awardId):
    aw = get_path("awards", awardId)
    if aw["status"] != "ACCEPTED":
        err("ERR_INVALID_STATE", 409, "Only an ACCEPTED award can be disbursed")
    f = STORE["funds"][aw["fund_id"]]
    # PRD §3.7 check order: cash capacity first, then fund-active.
    if aw["amount"] > f["cash_balance"]:
        err("ERR_INSUFFICIENT_CASH", 422, "Award amount exceeds the fund's cash balance")
    if f["status"] != "ACTIVE":
        err("ERR_FUND_NOT_ACTIVE_FOR_GRANTS", 409,
            "Fund must be ACTIVE for award disbursement")
    f["cash_balance"] = q2(f["cash_balance"] - aw["amount"])
    if f["endowed"]:
        f["allowance_used"] = q2(f["allowance_used"] + aw["amount"])
    f["last_activity_at"] = now()
    reactivate_if_inactive(f)
    touch(f)
    d = new_resource(common_fields=False)
    d.update({
        "source_kind": "SCHOLARSHIP_AWARD",
        "grant_id": None,
        "award_id": aw["id"],
        "fund_id": f["id"],
        "amount": q2(aw["amount"]),
    })
    STORE["disbursements"][d["id"]] = d
    aw["status"] = "DISBURSED"
    touch(aw)
    return success(award_view(aw))


@bp.post("/awards/<awardId>/forfeit")
@require_roles("ProgramOfficer")
def forfeit_award(awardId):
    aw = get_path("awards", awardId)
    if aw["status"] != "ACCEPTED":
        err("ERR_INVALID_STATE", 409, "Only an ACCEPTED award can be forfeited")
    aw["status"] = "FORFEITED"
    touch(aw)
    return success(award_view(aw))
