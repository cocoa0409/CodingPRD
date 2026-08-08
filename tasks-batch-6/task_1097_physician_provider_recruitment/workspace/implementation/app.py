"""Physician & Provider Recruitment API — Flask entry point.

In-memory only. Fresh process = empty store + default logical clock.
Nothing is seeded; every entity is created by test-driven API calls.
"""
import os

from flask import Flask, request

import calc
from calc import (
    OPEN_PIPELINE_STAGES,
    credentialing_overall_status,
    guarantee_credit_refund,
    guarantee_credit_replacement,
    match_score,
    open_pipeline_load,
    placement_fee,
    positions_filled,
    relocation_reimbursed,
)
from envelope import (
    ApiError,
    ERR_COMP_OUT_OF_RANGE,
    ERR_CREDENTIALING_NOT_CLEARED,
    ERR_FINAL_COMP_REQUIRED,
    ERR_GUARANTEE_WINDOW_EXPIRED,
    ERR_INTERVIEWER_DOUBLE_BOOKED,
    ERR_CANDIDATE_TRAVEL_CONFLICT,
    ERR_INTERVIEWER_INVALID,
    ERR_INVALID_STATE,
    ERR_NO_COMPLETED_SITE_VISIT,
    ERR_NO_ELIGIBLE_RECRUITER,
    ERR_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
    ERR_OPENING_FILLED,
    ERR_OPENING_NOT_OPEN,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SPECIALTY_MISMATCH,
    ERR_STALE_VERSION,
    ERR_VALIDATION,
    error_response,
    success,
)
from store import (
    S,
    add_days,
    new_id,
    parse_dt,
    whole_days_between,
)
import validate as V

app = Flask(__name__)


# --------------------------------------------------------------------------
# record helpers
# --------------------------------------------------------------------------
def stamp_new(fields):
    now = S.now_iso()
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    rec["_seq"] = S.next_seq()
    return rec


def touch(rec):
    rec["version"] += 1
    rec["updated_at"] = S.now_iso()


def find_or_404(coll, id_, label="Resource"):
    r = coll.get(id_)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, "%s not found" % label)
    return r


def get_pagination():
    args = request.args
    try:
        limit = int(args.get("limit")) if args.get("limit") is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset")) if args.get("offset") is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(records, serializer):
    limit, offset = get_pagination()
    recs = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(recs)
    page = recs[offset:offset + limit]
    data = [serializer(r) for r in page]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return success(data, "array", 200, pagination)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message), e.http_status


# --------------------------------------------------------------------------
# clock
# --------------------------------------------------------------------------
@app.post("/_clock/set_current_utc")
def set_clock():
    V.authorize({"PlatformAdmin"})
    body = V.get_body()
    iso = V.req_dt(body, "to_iso8601")
    S.clock = parse_dt(iso)
    return success({}, "object", 200)


# --------------------------------------------------------------------------
# StaffUser
# --------------------------------------------------------------------------
@app.post("/staff-users")
def create_staff():
    V.authorize({"PlatformAdmin"})
    body = V.get_body()
    role = V.req_enum(body, "role", V.STAFF_ROLES)
    full_name = V.req_str(body, "full_name")
    email = V.req_str(body, "email")
    covered = V.enum_array(body, "covered_specialties", V.SPECIALTIES, default=[])
    rec = stamp_new({
        "role": role, "full_name": full_name, "email": email,
        "covered_specialties": covered, "status": "ACTIVE",
    })
    S.staff_users[rec["id"]] = rec
    return success(calc.staff_user_dict(rec), "object", 201)


@app.get("/staff-users/<sid>")
def get_staff(sid):
    V.authorize({"PlatformAdmin", "Recruiter", "AccountManager", "CredentialingCoordinator"})
    r = find_or_404(S.staff_users, sid, "StaffUser")
    return success(calc.staff_user_dict(r))


@app.post("/staff-users/<sid>/transition")
def staff_transition(sid):
    role, uid = V.authorize({"PlatformAdmin"})
    body = V.get_body()
    action = V.req_str(body, "action")
    V.require_action_role(role, action, {"DEACTIVATE": {"PlatformAdmin"}, "ACTIVATE": {"PlatformAdmin"}})
    r = find_or_404(S.staff_users, sid, "StaffUser")
    if action == "DEACTIVATE":
        if r["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, "StaffUser not ACTIVE")
        r["status"] = "INACTIVE"
    else:
        if r["status"] != "INACTIVE":
            raise ApiError(ERR_INVALID_STATE, "StaffUser not INACTIVE")
        r["status"] = "ACTIVE"
    touch(r)
    return success(calc.staff_user_dict(r))


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------
@app.post("/clients")
def create_client():
    V.authorize({"AccountManager"})
    body = V.get_body()
    name = V.req_str(body, "name")
    region = V.req_str(body, "region")
    am_id = V.req_str(body, "account_manager_id")
    pct = V.req_number(body, "contingency_pct")
    if not (0 < pct <= 1):
        raise ApiError(ERR_VALIDATION, "contingency_pct must be in (0, 1]")
    min_fee = V.req_int(body, "min_fee_cents", min_val=0)
    guarantee_days = V.req_int(body, "guarantee_days", min_val=1)
    find_or_404(S.staff_users, am_id, "AccountManager")
    rec = stamp_new({
        "name": name, "region": region, "account_manager_id": am_id,
        "contingency_pct": pct, "min_fee_cents": min_fee, "guarantee_days": guarantee_days,
        "status": "ACTIVE",
    })
    S.clients[rec["id"]] = rec
    return success(calc.client_dict(rec), "object", 201)


@app.get("/clients/<cid>")
def get_client(cid):
    V.authorize({"PlatformAdmin", "AccountManager", "ClientContact"})
    r = find_or_404(S.clients, cid, "Client")
    return success(calc.client_dict(r))


@app.get("/clients")
def list_clients():
    V.authorize({"PlatformAdmin", "AccountManager"})
    am = request.args.get("account_manager_id")
    recs = [c for c in S.clients.values() if am is None or c["account_manager_id"] == am]
    return list_response(recs, calc.client_dict)


# --------------------------------------------------------------------------
# JobOpening
# --------------------------------------------------------------------------
@app.post("/job-openings")
def create_opening():
    V.authorize({"AccountManager"})
    body = V.get_body()
    client_id = V.req_str(body, "client_id")
    specialty = V.req_enum(body, "specialty", V.SPECIALTIES)
    region = V.req_str(body, "region")
    region_state = V.req_str(body, "region_state")
    comp_min = V.req_int(body, "comp_min_cents", min_val=0)
    comp_max = V.req_int(body, "comp_max_cents", min_val=0)
    if comp_max < comp_min:
        raise ApiError(ERR_VALIDATION, "comp_max_cents must be >= comp_min_cents")
    is_htf = V.opt_bool(body, "is_hard_to_fill", False)
    positions_total = V.opt_int(body, "positions_total", default=1, min_val=1)
    find_or_404(S.clients, client_id, "Client")
    rec = stamp_new({
        "client_id": client_id, "specialty": specialty, "region": region,
        "region_state": region_state, "comp_min_cents": comp_min, "comp_max_cents": comp_max,
        "is_hard_to_fill": is_htf, "positions_total": positions_total,
        "recruiter_id": None, "status": "DRAFT",
    })
    S.job_openings[rec["id"]] = rec
    return success(calc.opening_dict(rec), "object", 201)


@app.get("/job-openings/<oid>")
def get_opening(oid):
    V.authorize({"PlatformAdmin", "AccountManager", "Recruiter", "ClientContact"})
    r = find_or_404(S.job_openings, oid, "JobOpening")
    return success(calc.opening_dict(r))


@app.get("/job-openings")
def list_openings():
    V.authorize({"PlatformAdmin", "AccountManager", "Recruiter"})
    client_id = request.args.get("client_id")
    recruiter_id = request.args.get("recruiter_id")
    specialty = request.args.get("specialty")
    recs = [
        o for o in S.job_openings.values()
        if (client_id is None or o["client_id"] == client_id)
        and (recruiter_id is None or o["recruiter_id"] == recruiter_id)
        and (specialty is None or o["specialty"] == specialty)
    ]
    return list_response(recs, calc.opening_dict)


def run_recruiter_selector(opening):
    eligible = [
        s for s in S.staff_users.values()
        if s["role"] == "RECRUITER" and s["status"] == "ACTIVE"
        and opening["specialty"] in s["covered_specialties"]
    ]
    if not eligible:
        raise ApiError(ERR_NO_ELIGIBLE_RECRUITER, "No eligible recruiter for specialty")
    eligible.sort(key=lambda s: (open_pipeline_load(s["id"]), s["created_at"], s["_seq"]))
    return eligible[0]["id"]


@app.post("/job-openings/<oid>/transition")
def opening_transition(oid):
    role, uid = V.authorize({"AccountManager"})
    body = V.get_body()
    action = V.req_str(body, "action")
    V.require_action_role(role, action, {a: {"AccountManager"} for a in ("PUBLISH", "HOLD", "RESUME", "CLOSE")})
    o = find_or_404(S.job_openings, oid, "JobOpening")
    st = o["status"]
    if action == "PUBLISH":
        if st != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, "Opening not DRAFT")
        o["recruiter_id"] = run_recruiter_selector(o)
        o["status"] = "OPEN"
    elif action == "HOLD":
        if st != "OPEN":
            raise ApiError(ERR_INVALID_STATE, "Opening not OPEN")
        o["status"] = "ON_HOLD"
    elif action == "RESUME":
        if st != "ON_HOLD":
            raise ApiError(ERR_INVALID_STATE, "Opening not ON_HOLD")
        o["status"] = "OPEN"
    elif action == "CLOSE":
        if st not in ("OPEN", "ON_HOLD", "FILLED"):
            raise ApiError(ERR_INVALID_STATE, "Opening cannot be closed from %s" % st)
        o["status"] = "CLOSED"
    touch(o)
    return success(calc.opening_dict(o))


# --------------------------------------------------------------------------
# Candidate
# --------------------------------------------------------------------------
@app.post("/candidates")
def create_candidate():
    role, uid = V.authorize({"Recruiter"})
    body = V.get_body()
    recruiter_id = V.req_str(body, "recruiter_id")
    full_name = V.req_str(body, "full_name")
    specialty = V.req_enum(body, "specialty", V.SPECIALTIES)
    home_region = V.req_str(body, "home_region")
    license_states = V.req_str_array(body, "license_states", default=[])
    desired_comp = V.req_int(body, "desired_comp_cents", min_val=0)
    find_or_404(S.staff_users, recruiter_id, "Recruiter")
    if recruiter_id != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "recruiter_id must be the acting recruiter")
    rec = stamp_new({
        "recruiter_id": recruiter_id, "full_name": full_name, "specialty": specialty,
        "home_region": home_region, "license_states": license_states,
        "desired_comp_cents": desired_comp, "status": "ACTIVE",
    })
    S.candidates[rec["id"]] = rec
    return success(calc.candidate_dict(rec), "object", 201)


@app.get("/candidates/<cid>")
def get_candidate(cid):
    V.authorize({"PlatformAdmin", "Recruiter", "AccountManager"})
    r = find_or_404(S.candidates, cid, "Candidate")
    return success(calc.candidate_dict(r))


@app.get("/candidates")
def list_candidates():
    V.authorize({"PlatformAdmin", "Recruiter", "AccountManager"})
    recruiter_id = request.args.get("recruiter_id")
    specialty = request.args.get("specialty")
    recs = [
        c for c in S.candidates.values()
        if (recruiter_id is None or c["recruiter_id"] == recruiter_id)
        and (specialty is None or c["specialty"] == specialty)
    ]
    return list_response(recs, calc.candidate_dict)


# --------------------------------------------------------------------------
# Application
# --------------------------------------------------------------------------
@app.post("/applications")
def create_application():
    role, uid = V.authorize({"Recruiter"})
    body = V.get_body()
    candidate_id = V.req_str(body, "candidate_id")
    opening_id = V.req_str(body, "opening_id")
    cand = find_or_404(S.candidates, candidate_id, "Candidate")
    opening = find_or_404(S.job_openings, opening_id, "JobOpening")
    if cand["recruiter_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Recruiter does not own candidate")
    if opening["status"] == "FILLED":
        raise ApiError(ERR_OPENING_FILLED, "Opening already filled")
    rec = stamp_new({
        "candidate_id": candidate_id, "opening_id": opening_id,
        "recruiter_id": cand["recruiter_id"], "match_score": 0,
        "stage": "SOURCED", "reject_reason": None,
    })
    S.applications[rec["id"]] = rec
    return success(calc.application_dict(rec), "object", 201)


@app.get("/applications/<aid>")
def get_application(aid):
    V.authorize({"PlatformAdmin", "Recruiter", "AccountManager", "ClientContact"})
    r = find_or_404(S.applications, aid, "Application")
    return success(calc.application_dict(r))


@app.get("/applications")
def list_applications():
    V.authorize({"PlatformAdmin", "Recruiter", "AccountManager", "ClientContact"})
    opening_id = request.args.get("opening_id")
    candidate_id = request.args.get("candidate_id")
    recruiter_id = request.args.get("recruiter_id")
    stage = request.args.get("stage")
    recs = [
        a for a in S.applications.values()
        if (opening_id is None or a["opening_id"] == opening_id)
        and (candidate_id is None or a["candidate_id"] == candidate_id)
        and (recruiter_id is None or a["recruiter_id"] == recruiter_id)
        and (stage is None or a["stage"] == stage)
    ]
    return list_response(recs, calc.application_dict)


APP_ADVANCE_ROLES = {
    "SCREEN": {"Recruiter"},
    "SUBMIT": {"Recruiter"},
    "WITHDRAW": {"Recruiter"},
    "ADVANCE_TO_INTERVIEW": {"ClientContact"},
    "CLIENT_PASS": {"ClientContact"},
}


@app.post("/applications/<aid>/advance")
def advance_application(aid):
    role, uid = V.authorize({"Recruiter", "ClientContact"})
    body = V.get_body()
    action = V.req_str(body, "action")
    V.require_action_role(role, action, APP_ADVANCE_ROLES)
    a = find_or_404(S.applications, aid, "Application")
    opening = S.job_openings[a["opening_id"]]

    # ownership (priority 5)
    if action in ("SCREEN", "SUBMIT", "WITHDRAW"):
        if a["recruiter_id"] != uid:
            raise ApiError(ERR_NOT_RESOURCE_OWNER, "Recruiter does not own application")
    else:  # ClientContact actions
        if opening["client_id"] != uid:
            raise ApiError(ERR_NOT_RESOURCE_OWNER, "ClientContact does not own the opening's client")

    stage = a["stage"]
    if action == "SCREEN":
        if stage != "SOURCED":
            raise ApiError(ERR_INVALID_STATE, "Application not SOURCED")
        cand = S.candidates[a["candidate_id"]]
        a["match_score"] = match_score(cand, opening)
        a["stage"] = "SCREENED"
    elif action == "SUBMIT":
        if stage != "SCREENED":
            raise ApiError(ERR_INVALID_STATE, "Application not SCREENED")
        cand = S.candidates[a["candidate_id"]]
        if cand["specialty"] != opening["specialty"]:
            raise ApiError(ERR_SPECIALTY_MISMATCH, "Candidate specialty does not match opening")
        if opening["status"] != "OPEN":
            raise ApiError(ERR_OPENING_NOT_OPEN, "Opening is not OPEN")
        a["stage"] = "SUBMITTED"
    elif action == "ADVANCE_TO_INTERVIEW":
        if stage != "SUBMITTED":
            raise ApiError(ERR_INVALID_STATE, "Application not SUBMITTED")
        a["stage"] = "INTERVIEWING"
    elif action == "CLIENT_PASS":
        if stage != "SUBMITTED":
            raise ApiError(ERR_INVALID_STATE, "Application not SUBMITTED")
        a["stage"] = "REJECTED"
        a["reject_reason"] = "CLIENT_PASS"
    elif action == "WITHDRAW":
        if stage not in ("SOURCED", "SCREENED", "SUBMITTED", "INTERVIEWING"):
            raise ApiError(ERR_INVALID_STATE, "Application cannot be withdrawn from %s" % stage)
        a["stage"] = "WITHDRAWN"
        a["reject_reason"] = "WITHDRAWN_BY_CANDIDATE"
    touch(a)
    return success(calc.application_dict(a))


# --------------------------------------------------------------------------
# SiteVisit
# --------------------------------------------------------------------------
@app.post("/site-visits")
def create_site_visit():
    role, uid = V.authorize({"Recruiter"})
    body = V.get_body()
    application_id = V.req_str(body, "application_id")
    interviewer_user_id = V.req_str(body, "interviewer_user_id")
    scheduled_start = V.req_dt(body, "scheduled_start")
    scheduled_end = V.req_dt(body, "scheduled_end")
    location = V.req_str(body, "location")
    if parse_dt(scheduled_end) <= parse_dt(scheduled_start):
        raise ApiError(ERR_VALIDATION, "scheduled_end must be after scheduled_start")
    a = find_or_404(S.applications, application_id, "Application")
    interviewer = find_or_404(S.staff_users, interviewer_user_id, "StaffUser")
    if a["recruiter_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Recruiter does not own application")
    if interviewer["status"] != "ACTIVE":
        raise ApiError(ERR_INTERVIEWER_INVALID, "Interviewer is not an ACTIVE staff user")

    s = parse_dt(scheduled_start)
    e = parse_dt(scheduled_end)
    # interviewer overlap — half-open, adjacency allowed
    for x in S.site_visits.values():
        if x["status"] != "SCHEDULED" or x["interviewer_user_id"] != interviewer_user_id:
            continue
        xs = parse_dt(x["scheduled_start"])
        xe = parse_dt(x["scheduled_end"])
        if s < xe and xs < e:
            raise ApiError(ERR_INTERVIEWER_DOUBLE_BOOKED, "Interviewer double-booked")
    # candidate travel — buffered/closed, gap < 120 min rejected (== 120 allowed)
    buffer_secs = calc.CANDIDATE_TRAVEL_BUFFER_MINUTES * 60
    cand_id = a["candidate_id"]
    for y in S.site_visits.values():
        if y["status"] != "SCHEDULED":
            continue
        ya = S.applications.get(y["application_id"])
        if ya is None or ya["candidate_id"] != cand_id:
            continue
        ys = parse_dt(y["scheduled_start"])
        ye = parse_dt(y["scheduled_end"])
        if e <= ys:
            gap = (ys - e).total_seconds()
        elif ye <= s:
            gap = (s - ye).total_seconds()
        else:
            gap = -1  # overlapping
        if gap < buffer_secs:
            raise ApiError(ERR_CANDIDATE_TRAVEL_CONFLICT, "Candidate travel conflict")

    rec = stamp_new({
        "application_id": application_id, "interviewer_user_id": interviewer_user_id,
        "scheduled_start": scheduled_start, "scheduled_end": scheduled_end,
        "location": location, "status": "SCHEDULED",
    })
    S.site_visits[rec["id"]] = rec
    return success(calc.site_visit_dict(rec), "object", 201)


@app.get("/site-visits/<vid>")
def get_site_visit(vid):
    V.authorize({"PlatformAdmin", "Recruiter", "AccountManager"})
    r = find_or_404(S.site_visits, vid, "SiteVisit")
    return success(calc.site_visit_dict(r))


@app.get("/site-visits")
def list_site_visits():
    V.authorize({"PlatformAdmin", "Recruiter", "AccountManager"})
    application_id = request.args.get("application_id")
    interviewer_user_id = request.args.get("interviewer_user_id")
    recs = [
        v for v in S.site_visits.values()
        if (application_id is None or v["application_id"] == application_id)
        and (interviewer_user_id is None or v["interviewer_user_id"] == interviewer_user_id)
    ]
    return list_response(recs, calc.site_visit_dict)


@app.post("/site-visits/<vid>/transition")
def site_visit_transition(vid):
    role, uid = V.authorize({"Recruiter"})
    body = V.get_body()
    action = V.req_str(body, "action")
    V.require_action_role(role, action, {a: {"Recruiter"} for a in ("COMPLETE", "CANCEL", "NO_SHOW")})
    v = find_or_404(S.site_visits, vid, "SiteVisit")
    a = S.applications[v["application_id"]]
    if a["recruiter_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Recruiter does not own application")
    if v["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "SiteVisit not SCHEDULED")
    v["status"] = {"COMPLETE": "COMPLETED", "CANCEL": "CANCELLED", "NO_SHOW": "NO_SHOW"}[action]
    touch(v)
    return success(calc.site_visit_dict(v))


# --------------------------------------------------------------------------
# Offer
# --------------------------------------------------------------------------
@app.post("/offers")
def create_offer():
    role, uid = V.authorize({"AccountManager"})
    body = V.get_body()
    application_id = V.req_str(body, "application_id")
    base = V.req_int(body, "base_salary_cents", min_val=0)
    signon = V.opt_int(body, "sign_on_bonus_cents", default=0, min_val=0)
    start_date = V.req_dt(body, "start_date")
    expires_at = V.req_dt(body, "expires_at")
    reloc_cap = V.opt_int(body, "relocation_cap_cents", default=0, min_val=0)
    a = find_or_404(S.applications, application_id, "Application")
    opening = S.job_openings[a["opening_id"]]
    if a["stage"] != "INTERVIEWING":
        raise ApiError(ERR_INVALID_STATE, "Application not INTERVIEWING")
    if base < opening["comp_min_cents"] or base > opening["comp_max_cents"]:
        raise ApiError(ERR_COMP_OUT_OF_RANGE, "base_salary_cents outside opening band")
    has_completed = any(
        sv["application_id"] == application_id and sv["status"] == "COMPLETED"
        for sv in S.site_visits.values()
    )
    if not has_completed:
        raise ApiError(ERR_NO_COMPLETED_SITE_VISIT, "No COMPLETED site visit on application")
    rec = stamp_new({
        "application_id": application_id, "base_salary_cents": base,
        "sign_on_bonus_cents": signon, "start_date": start_date,
        "relocation_cap_cents": reloc_cap, "expires_at": expires_at,
        "round_number": 1, "extended_by_user_id": uid,
        "offered_first_year_comp_cents": base + signon, "status": "EXTENDED",
    })
    S.offers[rec["id"]] = rec
    # system: application INTERVIEWING -> OFFER_STAGE
    a["stage"] = "OFFER_STAGE"
    touch(a)
    return success(calc.offer_dict(rec), "object", 201)


@app.get("/offers/<oid>")
def get_offer(oid):
    V.authorize({"PlatformAdmin", "AccountManager", "Recruiter", "ClientContact"})
    r = find_or_404(S.offers, oid, "Offer")
    return success(calc.offer_dict(r))


@app.get("/offers")
def list_offers():
    V.authorize({"PlatformAdmin", "AccountManager", "Recruiter", "ClientContact"})
    application_id = request.args.get("application_id")
    recs = [o for o in S.offers.values() if application_id is None or o["application_id"] == application_id]
    return list_response(recs, calc.offer_dict)


OFFER_ACTION_ROLES = {
    "COUNTER": {"ClientContact"},
    "ACCEPT": {"Recruiter"},
    "DECLINE": {"Recruiter"},
    "RESCIND": {"AccountManager"},
    "EXPIRE": {"AccountManager"},
}


def opening_positions_change(opening):
    """Reopen a FILLED opening if its live count dropped below total."""
    if opening["status"] == "FILLED" and positions_filled(opening["id"]) < opening["positions_total"]:
        opening["status"] = "OPEN"
        touch(opening)


def handle_opening_fill(opening):
    if opening["status"] == "OPEN" and positions_filled(opening["id"]) == opening["positions_total"]:
        opening["status"] = "FILLED"
        touch(opening)
        for a in list(S.applications.values()):
            if a["opening_id"] == opening["id"] and a["stage"] in OPEN_PIPELINE_STAGES:
                a["stage"] = "REJECTED"
                a["reject_reason"] = "OPENING_FILLED"
                touch(a)
                for o in S.offers.values():
                    if o["application_id"] == a["id"] and o["status"] in ("EXTENDED", "COUNTERED"):
                        o["status"] = "RESCINDED"
                        touch(o)


def accept_offer(offer, uid):
    if S.clock > parse_dt(offer["expires_at"]):
        raise ApiError(ERR_INVALID_STATE, "Offer is past expiry")
    a = S.applications[offer["application_id"]]
    opening = S.job_openings[a["opening_id"]]
    client = S.clients[opening["client_id"]]
    cand = S.candidates[a["candidate_id"]]
    offer["status"] = "ACCEPTED"
    touch(offer)
    a["stage"] = "PLACED"
    touch(a)
    cand["status"] = "PLACED"
    touch(cand)
    fee_est = placement_fee(offer["offered_first_year_comp_cents"], client, opening)
    placement = stamp_new({
        "offer_id": offer["id"], "application_id": a["id"], "client_id": client["id"],
        "candidate_id": cand["id"], "opening_id": opening["id"],
        "start_date": offer["start_date"], "fee_estimate_cents": fee_est,
        "final_first_year_comp_cents": None, "placement_fee_cents": 0,
        "relocation_cap_cents": offer["relocation_cap_cents"],
        "relocation_reimbursed_cents": 0, "relocation_status": "NONE",
        "guarantee_end_date": None, "placement_status": "PRE_START", "fee_status": "PENDING",
    })
    S.placements[placement["id"]] = placement
    cf = stamp_new({
        "placement_id": placement["id"], "candidate_id": cand["id"],
        "overall_status": "NOT_STARTED",
    })
    S.cred_files[cf["id"]] = cf
    handle_opening_fill(opening)


@app.post("/offers/<oid>/transition")
def offer_transition(oid):
    role, uid = V.authorize({"AccountManager", "Recruiter", "ClientContact"})
    body = V.get_body()
    action = V.req_str(body, "action")
    V.require_action_role(role, action, OFFER_ACTION_ROLES)
    o = find_or_404(S.offers, oid, "Offer")
    a = S.applications[o["application_id"]]
    opening = S.job_openings[a["opening_id"]]

    # ownership (priority 5)
    if action == "COUNTER":
        if opening["client_id"] != uid:
            raise ApiError(ERR_NOT_RESOURCE_OWNER, "ClientContact does not own the opening's client")
    elif action in ("ACCEPT", "DECLINE"):
        if a["recruiter_id"] != uid:
            raise ApiError(ERR_NOT_RESOURCE_OWNER, "Recruiter does not own application")

    st = o["status"]
    if action == "COUNTER":
        if st != "EXTENDED":
            raise ApiError(ERR_INVALID_STATE, "Offer not EXTENDED")
        o["status"] = "COUNTERED"
        touch(o)
    elif action == "ACCEPT":
        if st != "EXTENDED":
            raise ApiError(ERR_INVALID_STATE, "Offer not EXTENDED")
        accept_offer(o, uid)
    elif action == "DECLINE":
        if st not in ("EXTENDED", "COUNTERED"):
            raise ApiError(ERR_INVALID_STATE, "Offer not EXTENDED/COUNTERED")
        o["status"] = "DECLINED"
        touch(o)
    elif action == "RESCIND":
        if st not in ("EXTENDED", "COUNTERED"):
            raise ApiError(ERR_INVALID_STATE, "Offer not EXTENDED/COUNTERED")
        o["status"] = "RESCINDED"
        touch(o)
    elif action == "EXPIRE":
        if st != "EXTENDED":
            raise ApiError(ERR_INVALID_STATE, "Offer not EXTENDED")
        if S.clock < parse_dt(o["expires_at"]):
            raise ApiError(ERR_INVALID_STATE, "Offer not yet expired")
        o["status"] = "EXPIRED"
        touch(o)
    return success(calc.offer_dict(o))


@app.post("/offers/<oid>/revise")
def revise_offer(oid):
    role, uid = V.authorize({"AccountManager"})
    body = V.get_body()
    expected = V.req_int(body, "expected_offer_version")
    base = V.opt_int(body, "base_salary_cents", default=None, min_val=0)
    signon = V.opt_int(body, "sign_on_bonus_cents", default=None, min_val=0)
    start_date = V.opt_dt(body, "start_date", default=None)
    expires_at = V.opt_dt(body, "expires_at", default=None)
    o = find_or_404(S.offers, oid, "Offer")
    a = S.applications[o["application_id"]]
    opening = S.job_openings[a["opening_id"]]
    # OCC (priority 7) before state legality (priority 8)
    if expected != o["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_offer_version does not match current version")
    if o["status"] != "COUNTERED":
        raise ApiError(ERR_INVALID_STATE, "Offer not COUNTERED")
    if base is not None:
        if base < opening["comp_min_cents"] or base > opening["comp_max_cents"]:
            raise ApiError(ERR_COMP_OUT_OF_RANGE, "base_salary_cents outside opening band")
        o["base_salary_cents"] = base
    if signon is not None:
        o["sign_on_bonus_cents"] = signon
    if start_date is not None:
        o["start_date"] = start_date
    if expires_at is not None:
        o["expires_at"] = expires_at
    o["status"] = "EXTENDED"
    o["round_number"] += 1
    o["offered_first_year_comp_cents"] = o["base_salary_cents"] + o["sign_on_bonus_cents"]
    o["extended_by_user_id"] = uid
    touch(o)
    return success(calc.offer_dict(o))


# --------------------------------------------------------------------------
# Placement
# --------------------------------------------------------------------------
@app.get("/placements/<pid>")
def get_placement(pid):
    V.authorize({"PlatformAdmin", "AccountManager", "Recruiter", "CredentialingCoordinator"})
    r = find_or_404(S.placements, pid, "Placement")
    return success(calc.placement_dict(r))


@app.get("/placements")
def list_placements():
    V.authorize({"PlatformAdmin", "AccountManager", "Recruiter", "CredentialingCoordinator"})
    q = request.args
    recs = [
        p for p in S.placements.values()
        if (q.get("opening_id") is None or p["opening_id"] == q.get("opening_id"))
        and (q.get("client_id") is None or p["client_id"] == q.get("client_id"))
        and (q.get("candidate_id") is None or p["candidate_id"] == q.get("candidate_id"))
        and (q.get("application_id") is None or p["application_id"] == q.get("application_id"))
        and (q.get("offer_id") is None or p["offer_id"] == q.get("offer_id"))
    ]
    return list_response(recs, calc.placement_dict)


PLACEMENT_ACTION_ROLES = {
    "ONBOARD": {"CredentialingCoordinator"},
    "MARK_GUARANTEE_MET": {"AccountManager"},
    "CANCEL": {"AccountManager"},
    "INVOICE": {"AccountManager"},
    "MARK_PAID": {"AccountManager"},
    "WAIVE": {"AccountManager"},
    "RELOCATION_APPROVE": {"AccountManager"},
    "RELOCATION_REJECT": {"AccountManager"},
    "RELOCATION_REIMBURSE": {"AccountManager"},
}


@app.post("/placements/<pid>/transition")
def placement_transition(pid):
    role, uid = V.authorize({"AccountManager", "CredentialingCoordinator"})
    body = V.get_body()
    action = V.req_str(body, "action")
    V.require_action_role(role, action, PLACEMENT_ACTION_ROLES)
    p = find_or_404(S.placements, pid, "Placement")

    if action == "ONBOARD":
        if p["placement_status"] != "PRE_START":
            raise ApiError(ERR_INVALID_STATE, "Placement not PRE_START")
        cf = _cred_file_for_placement(p["id"])
        if cf is None or cf["overall_status"] != "CLEARED":
            raise ApiError(ERR_CREDENTIALING_NOT_CLEARED, "Credentialing not CLEARED")
        if S.clock < parse_dt(p["start_date"]):
            raise ApiError(ERR_INVALID_STATE, "Start date not reached")
        client = S.clients[p["client_id"]]
        p["guarantee_end_date"] = add_days(p["start_date"], client["guarantee_days"])
        p["placement_status"] = "ACTIVE"
        touch(p)
    elif action == "MARK_GUARANTEE_MET":
        if p["placement_status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, "Placement not ACTIVE")
        if S.clock <= parse_dt(p["guarantee_end_date"]):
            raise ApiError(ERR_INVALID_STATE, "Guarantee window not yet passed")
        p["placement_status"] = "GUARANTEE_MET"
        touch(p)
    elif action == "CANCEL":
        if p["placement_status"] != "PRE_START":
            raise ApiError(ERR_INVALID_STATE, "Placement not PRE_START")
        p["placement_status"] = "CANCELLED"
        touch(p)
        cand = S.candidates[p["candidate_id"]]
        cand["status"] = "ACTIVE"
        touch(cand)
        opening_positions_change(S.job_openings[p["opening_id"]])
    elif action == "INVOICE":
        final = V.opt_int(body, "final_first_year_comp_cents", default=None, min_val=0)
        if p["fee_status"] != "PENDING":
            raise ApiError(ERR_INVALID_STATE, "Fee not PENDING")
        if p["placement_status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, "Placement not ACTIVE")
        if final is None:
            raise ApiError(ERR_FINAL_COMP_REQUIRED, "final_first_year_comp_cents required")
        client = S.clients[p["client_id"]]
        opening = S.job_openings[p["opening_id"]]
        p["final_first_year_comp_cents"] = final
        p["placement_fee_cents"] = placement_fee(final, client, opening)
        p["fee_status"] = "INVOICED"
        touch(p)
    elif action == "MARK_PAID":
        if p["fee_status"] != "INVOICED":
            raise ApiError(ERR_INVALID_STATE, "Fee not INVOICED")
        p["fee_status"] = "PAID"
        touch(p)
    elif action == "WAIVE":
        offer = S.offers[p["offer_id"]]
        if uid == offer["extended_by_user_id"]:
            raise ApiError(ERR_SEGREGATION_OF_DUTIES, "Waiver approver extended the offer")
        if p["fee_status"] != "PENDING":
            raise ApiError(ERR_INVALID_STATE, "Fee not PENDING")
        p["fee_status"] = "WAIVED"
        touch(p)
    elif action == "RELOCATION_APPROVE":
        expense_id = V.req_str(body, "expense_id")
        exp = _reloc_or_404(expense_id, p["id"])
        if exp["status"] != "SUBMITTED":
            raise ApiError(ERR_INVALID_STATE, "Expense not SUBMITTED")
        exp["status"] = "APPROVED"
        touch(exp)
        if p["relocation_status"] != "REIMBURSED":
            if p["relocation_status"] != "APPROVED":
                p["relocation_status"] = "APPROVED"
                touch(p)
    elif action == "RELOCATION_REJECT":
        expense_id = V.req_str(body, "expense_id")
        exp = _reloc_or_404(expense_id, p["id"])
        if exp["status"] != "SUBMITTED":
            raise ApiError(ERR_INVALID_STATE, "Expense not SUBMITTED")
        exp["status"] = "REJECTED"
        touch(exp)
    elif action == "RELOCATION_REIMBURSE":
        if p["relocation_status"] != "APPROVED":
            raise ApiError(ERR_INVALID_STATE, "Relocation not APPROVED")
        p["relocation_reimbursed_cents"] = relocation_reimbursed(p["id"], p["relocation_cap_cents"])
        p["relocation_status"] = "REIMBURSED"
        touch(p)
    return success(calc.placement_dict(p))


def _cred_file_for_placement(placement_id):
    for f in S.cred_files.values():
        if f["placement_id"] == placement_id:
            return f
    return None


def _reloc_or_404(expense_id, placement_id):
    exp = S.reloc_expenses.get(expense_id)
    if exp is None or exp["placement_id"] != placement_id:
        raise ApiError(ERR_NOT_FOUND, "RelocationExpense not found")
    return exp


@app.post("/placements/<pid>/relocation-expenses")
def create_reloc_expense(pid):
    V.authorize({"Recruiter", "AccountManager"})
    body = V.get_body()
    category = V.req_enum(body, "category", V.RELOC_CATEGORIES)
    amount = V.req_int(body, "amount_cents", min_val=0)
    is_taxable = V.opt_bool(body, "is_taxable", False)
    find_or_404(S.placements, pid, "Placement")
    rec = stamp_new({
        "placement_id": pid, "category": category, "amount_cents": amount,
        "is_taxable": is_taxable, "status": "SUBMITTED",
    })
    S.reloc_expenses[rec["id"]] = rec
    return success(calc.reloc_expense_dict(rec), "object", 201)


@app.get("/placements/<pid>/relocation-expenses")
def list_reloc_expenses(pid):
    V.authorize({"PlatformAdmin", "AccountManager", "Recruiter"})
    find_or_404(S.placements, pid, "Placement")
    recs = [e for e in S.reloc_expenses.values() if e["placement_id"] == pid]
    return list_response(recs, calc.reloc_expense_dict)


# --------------------------------------------------------------------------
# CredentialingFile / CredentialItem
# --------------------------------------------------------------------------
@app.get("/credentialing-files/<fid>")
def get_cred_file(fid):
    V.authorize({"PlatformAdmin", "CredentialingCoordinator", "AccountManager"})
    r = find_or_404(S.cred_files, fid, "CredentialingFile")
    return success(calc.cred_file_dict(r))


@app.get("/credentialing-files")
def list_cred_files():
    V.authorize({"PlatformAdmin", "CredentialingCoordinator", "AccountManager"})
    placement_id = request.args.get("placement_id")
    candidate_id = request.args.get("candidate_id")
    recs = [
        f for f in S.cred_files.values()
        if (placement_id is None or f["placement_id"] == placement_id)
        and (candidate_id is None or f["candidate_id"] == candidate_id)
    ]
    return list_response(recs, calc.cred_file_dict)


@app.post("/credentialing-files/<fid>/items")
def create_cred_item(fid):
    V.authorize({"CredentialingCoordinator"})
    body = V.get_body()
    item_type = V.req_enum(body, "item_type", V.ITEM_TYPES)
    is_required = V.opt_bool(body, "is_required", True)
    find_or_404(S.cred_files, fid, "CredentialingFile")
    rec = stamp_new({
        "credentialing_file_id": fid, "item_type": item_type,
        "is_required": is_required, "status": "PENDING",
    })
    S.cred_items[rec["id"]] = rec
    recompute_cred_file(fid)
    return success(calc.cred_item_dict(rec), "object", 201)


@app.get("/credentialing-files/<fid>/items")
def list_cred_items(fid):
    V.authorize({"PlatformAdmin", "CredentialingCoordinator", "AccountManager"})
    find_or_404(S.cred_files, fid, "CredentialingFile")
    recs = [i for i in S.cred_items.values() if i["credentialing_file_id"] == fid]
    return list_response(recs, calc.cred_item_dict)


def recompute_cred_file(file_id):
    f = S.cred_files.get(file_id)
    if f is None:
        return
    new_status = credentialing_overall_status(file_id)
    if new_status != f["overall_status"]:
        f["overall_status"] = new_status
        touch(f)


CRED_ITEM_TRANSITIONS = {
    "SUBMIT": ("PENDING", "SUBMITTED"),
    "VERIFY": ("SUBMITTED", "VERIFIED"),
    "RESUBMIT": ("FLAGGED", "SUBMITTED"),
}


@app.post("/credential-items/<iid>/transition")
def cred_item_transition(iid):
    role, uid = V.authorize({"CredentialingCoordinator"})
    body = V.get_body()
    action = V.req_str(body, "action")
    V.require_action_role(role, action, {a: {"CredentialingCoordinator"} for a in ("SUBMIT", "VERIFY", "FLAG", "RESUBMIT")})
    item = find_or_404(S.cred_items, iid, "CredentialItem")
    st = item["status"]
    if action == "FLAG":
        if st not in ("SUBMITTED", "VERIFIED"):
            raise ApiError(ERR_INVALID_STATE, "Item cannot be flagged from %s" % st)
        item["status"] = "FLAGGED"
    else:
        frm, to = CRED_ITEM_TRANSITIONS[action]
        if st != frm:
            raise ApiError(ERR_INVALID_STATE, "Item not %s" % frm)
        item["status"] = to
    touch(item)
    recompute_cred_file(item["credentialing_file_id"])
    return success(calc.cred_item_dict(item))


# --------------------------------------------------------------------------
# GuaranteeClaim
# --------------------------------------------------------------------------
@app.post("/guarantee-claims")
def create_guarantee_claim():
    V.authorize({"Recruiter", "AccountManager"})
    body = V.get_body()
    placement_id = V.req_str(body, "placement_id")
    fell_out_date = V.req_dt(body, "fell_out_date")
    reason = V.req_str(body, "reason")
    p = find_or_404(S.placements, placement_id, "Placement")
    days_worked = whole_days_between(p["start_date"], fell_out_date)
    rec = stamp_new({
        "placement_id": placement_id, "client_id": p["client_id"],
        "fell_out_date": fell_out_date, "reason": reason,
        "replacement_placement_id": None, "days_worked": days_worked,
        "credit_cents": 0, "status": "FILED",
    })
    S.guarantee_claims[rec["id"]] = rec
    return success(calc.guarantee_claim_dict(rec), "object", 201)


@app.get("/guarantee-claims/<gid>")
def get_guarantee_claim(gid):
    V.authorize({"PlatformAdmin", "AccountManager", "Recruiter"})
    r = find_or_404(S.guarantee_claims, gid, "GuaranteeClaim")
    return success(calc.guarantee_claim_dict(r))


@app.get("/guarantee-claims")
def list_guarantee_claims():
    V.authorize({"PlatformAdmin", "AccountManager", "Recruiter"})
    placement_id = request.args.get("placement_id")
    client_id = request.args.get("client_id")
    recs = [
        c for c in S.guarantee_claims.values()
        if (placement_id is None or c["placement_id"] == placement_id)
        and (client_id is None or c["client_id"] == client_id)
    ]
    return list_response(recs, calc.guarantee_claim_dict)


@app.post("/guarantee-claims/<gid>/transition")
def guarantee_claim_transition(gid):
    role, uid = V.authorize({"AccountManager"})
    body = V.get_body()
    action = V.req_str(body, "action")
    V.require_action_role(role, action, {a: {"AccountManager"} for a in ("APPROVE", "DENY", "RESOLVE_REFUND", "RESOLVE_REPLACEMENT")})
    claim = find_or_404(S.guarantee_claims, gid, "GuaranteeClaim")
    placement = S.placements[claim["placement_id"]]
    client = S.clients[claim["client_id"]]

    if action == "APPROVE":
        if claim["status"] != "FILED":
            raise ApiError(ERR_INVALID_STATE, "Claim not FILED")
        if placement["placement_status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, "Placement not ACTIVE")
        if parse_dt(claim["fell_out_date"]) > parse_dt(placement["guarantee_end_date"]):
            raise ApiError(ERR_GUARANTEE_WINDOW_EXPIRED, "fell_out_date after guarantee window")
        claim["status"] = "APPROVED"
        touch(claim)
        placement["placement_status"] = "FELL_OUT"
        placement["fee_status"] = "CREDITED"
        touch(placement)
        opening_positions_change(S.job_openings[placement["opening_id"]])
    elif action == "DENY":
        if claim["status"] != "FILED":
            raise ApiError(ERR_INVALID_STATE, "Claim not FILED")
        claim["status"] = "DENIED"
        touch(claim)
    elif action == "RESOLVE_REFUND":
        if claim["status"] != "APPROVED":
            raise ApiError(ERR_INVALID_STATE, "Claim not APPROVED")
        claim["credit_cents"] = guarantee_credit_refund(placement, client, claim["days_worked"])
        claim["status"] = "RESOLVED_REFUND"
        touch(claim)
    elif action == "RESOLVE_REPLACEMENT":
        replacement_id = V.req_str(body, "replacement_placement_id")
        replacement = find_or_404(S.placements, replacement_id, "Placement")
        if claim["status"] != "APPROVED":
            raise ApiError(ERR_INVALID_STATE, "Claim not APPROVED")
        if (replacement["opening_id"] != placement["opening_id"]
                or replacement["placement_status"] not in ("PRE_START", "ACTIVE")):
            raise ApiError(ERR_INVALID_STATE, "Invalid replacement placement")
        claim["replacement_placement_id"] = replacement_id
        claim["credit_cents"] = guarantee_credit_replacement(placement, replacement)
        claim["status"] = "RESOLVED_REPLACEMENT"
        touch(claim)
    return success(calc.guarantee_claim_dict(claim))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
