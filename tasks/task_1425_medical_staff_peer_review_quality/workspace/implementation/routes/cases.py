from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_roles
from response import success, success_list, parse_pagination
from services import (
    REFERRAL_SOURCES, SCREEN_OUT_REASONS, NOTE_TYPES, NOTE_ALLOWED_STATES,
    REFERRAL_COOLDOWN, RESPONSE_WINDOW,
    get_body, req_str, opt_str, req_enum, is_int, get_case, pub, sort_created,
    make_versioned, make_ledger, touch, guard_case_state, require_chair,
    deliberation_for, notification_for, response_for, referral_for,
    submitted_assignments, case_assignments, active_focused_review,
    compute_rating, run_resolution_cascade, parse_dt, iso, now_iso,
)

bp = Blueprint("cases", __name__)

ALL_ROLES = ("QualityDirector", "PeerReviewCoordinator", "CommitteeMember", "Provider")
STAFF_ROLES = ("QualityDirector", "PeerReviewCoordinator", "CommitteeMember")


def _list_response(records):
    limit, offset = parse_pagination()
    total = len(records)
    page = records[offset:offset + limit]
    return success_list([pub(r) for r in page], limit, offset, total)


def _provider_scope(actor, case):
    if actor.role == "Provider" and actor.id != case["subject_provider_id"]:
        raise ApiError("ERR_FORBIDDEN_RESOURCE", 403, "providers may only access their own cases")


@bp.post("/peer-review/cases")
def create_case():
    require_roles("PeerReviewCoordinator")
    b = get_body()
    # stage 3: body FK existence
    pid = b.get("subject_provider_id")
    if pid is not None:
        if not isinstance(pid, str) or store.providers.get(pid) is None:
            raise ApiError("ERR_PROVIDER_NOT_FOUND", 404, "subject_provider_id does not resolve")
    # stage 8: input shape
    if not isinstance(pid, str) or not pid:
        raise ApiError("ERR_VALIDATION", 400, "subject_provider_id is required")
    referral_source = req_enum(b, "referral_source", REFERRAL_SOURCES)
    referred_raw = b.get("referred_at")
    if referred_raw is None:
        raise ApiError("ERR_VALIDATION", 400, "referred_at is required")
    parse_dt(referred_raw, "referred_at")  # well-formedness check; value echoed verbatim
    description = req_str(b, "description")
    # stage 9: referral cooldown window (PRD 3.2)
    screened = [c for c in store.cases.values()
                if c["subject_provider_id"] == pid and c["status"] == "SCREENED_OUT"]
    if screened:
        latest = max(screened, key=lambda c: c["_screened_out_dt"])
        if latest["_screened_out_dt"] > store.clock - REFERRAL_COOLDOWN:
            raise ApiError("ERR_DUPLICATE_REFERRAL_WINDOW", 409,
                           "subject provider was screened out within the last 30 days")
    rec = make_versioned()
    rec.update({
        "subject_provider_id": pid,
        "referral_source": referral_source,
        "referred_at": referred_raw,
        "description": description,
        "status": "REFERRED",
        "screened_out_reason": None,
        "screened_out_at": None,
        "_screened_out_dt": None,
        "focus_group_id": None,
        "closure_basis": None,
        "closed_at": None,
    })
    store.cases[rec["id"]] = rec
    return success(pub(rec), 201)


@bp.get("/peer-review/cases")
def list_cases():
    require_roles(*STAFF_ROLES)
    items = sort_created(list(store.cases.values()))
    q = request.args
    if q.get("status") is not None:
        items = [c for c in items if c["status"] == q.get("status")]
    if q.get("subject_provider_id") is not None:
        items = [c for c in items if c["subject_provider_id"] == q.get("subject_provider_id")]
    if q.get("focus_group_id") is not None:
        items = [c for c in items if c["focus_group_id"] == q.get("focus_group_id")]
    return _list_response(items)


@bp.get("/peer-review/cases/<cid>")
def get_one_case(cid):
    actor = require_roles(*ALL_ROLES)
    case = get_case(cid)
    _provider_scope(actor, case)
    return success(pub(case))


@bp.post("/peer-review/cases/<cid>/screen")
def screen_case(cid):
    require_roles("QualityDirector")
    case = get_case(cid)
    guard_case_state(case, ("REFERRED",))
    b = get_body()
    decision = req_enum(b, "decision", ("SCREEN_IN", "SCREEN_OUT"))
    if decision == "SCREEN_OUT":
        reason = b.get("screened_out_reason")
        if reason is None:
            raise ApiError("ERR_SCREEN_OUT_REASON_REQUIRED", 400,
                           "screened_out_reason is required when decision is SCREEN_OUT")
        if reason not in SCREEN_OUT_REASONS:
            raise ApiError("ERR_VALIDATION", 400, "invalid screened_out_reason")
        case["status"] = "SCREENED_OUT"
        case["screened_out_reason"] = reason
        case["_screened_out_dt"] = store.clock
        case["screened_out_at"] = now_iso()
    else:
        case["status"] = "SCREENED_IN"
    touch(case)
    return success(pub(case))


@bp.get("/peer-review/cases/<cid>/reviewer-candidates")
def reviewer_candidates(cid):
    require_roles("PeerReviewCoordinator", "QualityDirector")
    case = get_case(cid)
    subject = store.providers.get(case["subject_provider_id"])
    subject_specialty = subject["specialty"] if subject else None
    eligible = []
    for m in store.members.values():
        if m["status"] != "ACTIVE":
            continue
        if m["provider_id"] == case["subject_provider_id"]:
            continue
        if any(c for c in store.conflicts.values()
               if c["member_id"] == m["id"] and c["provider_id"] == case["subject_provider_id"]):
            continue
        if any(a for a in case_assignments(cid)
               if a["reviewer_id"] == m["id"] and a["status"] != "WAIVED"):
            continue
        eligible.append(m)
    eligible.sort(key=lambda m: (
        0 if m["specialty"] == subject_specialty else 1,
        -m["reliability_completed_count"],
        m["created_at"],
        m["_seq"],
    ))
    return _list_response(eligible)


@bp.post("/peer-review/cases/<cid>/assignments")
def create_assignment(cid):
    require_roles("PeerReviewCoordinator")
    case = get_case(cid)
    b = get_body()
    # stage 3: body FK existence (reviewer_id) when present
    rid = b.get("reviewer_id")
    member = None
    if rid is not None:
        member = store.members.get(rid) if isinstance(rid, str) else None
        if member is None:
            raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "reviewer_id does not resolve")
    # stage 5: state legality
    guard_case_state(case, ("SCREENED_IN", "ASSIGNED", "IN_REVIEW"))
    # stage 6: optimistic concurrency
    ecv = b.get("expected_case_version")
    if is_int(ecv) and ecv != case["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_case_version is stale")
    # stage 7: conflict-avoidance chain, pinned order
    if member is not None:
        if member["status"] != "ACTIVE":
            raise ApiError("ERR_REVIEWER_INACTIVE", 422, "reviewer is not ACTIVE")
        if member["provider_id"] == case["subject_provider_id"]:
            raise ApiError("ERR_REVIEWER_IS_SUBJECT", 422, "reviewer is the case subject")
        if any(c for c in store.conflicts.values()
               if c["member_id"] == member["id"] and c["provider_id"] == case["subject_provider_id"]):
            raise ApiError("ERR_REVIEWER_CONFLICT_DECLARED", 422,
                           "reviewer has a declared conflict against the subject")
    # stage 8: input shape and constraints
    if not isinstance(rid, str) or not rid:
        raise ApiError("ERR_VALIDATION", 400, "reviewer_id is required")
    if not is_int(ecv):
        raise ApiError("ERR_VALIDATION", 400, "expected_case_version is required and must be an integer")
    existing = case_assignments(cid)
    if any(a for a in existing if a["reviewer_id"] == rid and a["status"] != "WAIVED"):
        raise ApiError("ERR_REVIEWER_ALREADY_ASSIGNED", 422,
                       "reviewer already holds a non-WAIVED assignment on this case")
    if sum(1 for a in existing if a["status"] != "WAIVED") >= 3:
        raise ApiError("ERR_CASE_FULLY_ASSIGNED", 409, "case already has 3 non-WAIVED assignments")
    rec = make_versioned()
    rec.update({
        "case_id": cid,
        "reviewer_id": rid,
        "sequence": len(existing) + 1,  # all statuses incl. WAIVED; never reused
        "status": "PENDING",
        "care_appropriateness_score": None,
        "ofi_score": None,
        "submitted_at": None,
    })
    store.assignments[rec["id"]] = rec
    if case["status"] == "SCREENED_IN":
        case["status"] = "ASSIGNED"
    touch(case)
    return success(pub(rec), 201)


@bp.get("/peer-review/cases/<cid>/assignments")
def list_case_assignments(cid):
    require_roles(*STAFF_ROLES)
    get_case(cid)
    items = sorted(case_assignments(cid), key=lambda a: a["sequence"])  # sequence ASC
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return _list_response(items)


@bp.post("/peer-review/cases/<cid>/notes")
def create_note(cid):
    actor = require_roles("CommitteeMember")
    case = get_case(cid)
    guard_case_state(case, NOTE_ALLOWED_STATES)
    b = get_body()
    text = req_str(b, "body")
    note_type = b.get("note_type", "GENERAL")
    if note_type not in NOTE_TYPES:
        raise ApiError("ERR_VALIDATION", 400, "note_type must be GENERAL or DELIBERATION")
    rec = make_ledger()
    rec.update({
        "case_id": cid,
        "author_member_id": actor.id,  # stamped from X-User-ID, never the body
        "body": text,
        "note_type": note_type,
    })
    store.notes[rec["id"]] = rec
    return success(pub(rec), 201)


@bp.get("/peer-review/cases/<cid>/notes")
def list_notes(cid):
    require_roles(*STAFF_ROLES)
    get_case(cid)
    items = sort_created([n for n in store.notes.values() if n["case_id"] == cid])
    return _list_response(items)


@bp.get("/peer-review/cases/<cid>/deliberation")
def get_case_deliberation(cid):
    require_roles(*STAFF_ROLES)
    get_case(cid)
    d = deliberation_for(cid)
    return _list_response([d] if d is not None else [])


@bp.post("/peer-review/cases/<cid>/finalize-deliberation")
def finalize_deliberation(cid):
    actor = require_roles("CommitteeMember")
    case = get_case(cid)
    require_chair(actor)
    guard_case_state(case, ("DELIBERATION",))
    b = get_body()
    rationale = opt_str(b, "rationale_note")
    # focus panel quorum (PRD 3.5)
    fr = active_focused_review(case["subject_provider_id"])
    subs = submitted_assignments(cid)
    if fr is not None:
        group_ids = {g["id"] for g in store.focus_groups.values() if g["focus_id"] == fr["id"]}
        panel = {gm["member_id"] for gm in store.focus_group_members.values()
                 if gm["focus_group_id"] in group_ids}
        if sum(1 for a in subs if a["reviewer_id"] in panel) < 2:
            raise ApiError("ERR_FOCUS_PANEL_QUORUM_NOT_MET", 409,
                           "fewer than 2 SUBMITTED reviewers belong to the focused review's focus groups")
    d = deliberation_for(cid)
    d["rating"] = compute_rating(subs)
    d["status"] = "FINALIZED"
    d["finalized_at"] = now_iso()
    d["_finalized_dt"] = store.clock
    d["rationale_note"] = rationale
    touch(d)
    case["status"] = "NOTIFIED"
    touch(case)
    deadline = store.clock + RESPONSE_WINDOW
    nrec = make_ledger()
    nrec.update({
        "case_id": cid,
        "sent_at": now_iso(),
        "response_deadline": iso(deadline),
        "_deadline_dt": deadline,
    })
    store.notifications[nrec["id"]] = nrec
    return success(pub(d))


@bp.get("/peer-review/cases/<cid>/notifications")
def get_notifications(cid):
    actor = require_roles(*ALL_ROLES)
    case = get_case(cid)
    _provider_scope(actor, case)
    n = notification_for(cid)
    return _list_response([n] if n is not None else [])


@bp.post("/peer-review/cases/<cid>/response")
def submit_response(cid):
    actor = require_roles("Provider")
    case = get_case(cid)
    _provider_scope(actor, case)
    guard_case_state(case, ("NOTIFIED",))
    b = get_body()
    text = req_str(b, "response_text")
    notif = notification_for(cid)
    if store.clock > notif["_deadline_dt"]:
        raise ApiError("ERR_RESPONSE_WINDOW_CLOSED", 422, "response deadline has passed")
    rec = make_ledger()
    rec.update({"case_id": cid, "response_text": text, "submitted_at": now_iso()})
    store.responses[rec["id"]] = rec
    case["status"] = "RESPONDED"
    touch(case)
    return success(pub(rec), 201)


@bp.get("/peer-review/cases/<cid>/response")
def get_response(cid):
    actor = require_roles(*ALL_ROLES)
    case = get_case(cid)
    _provider_scope(actor, case)
    r = response_for(cid)
    return _list_response([r] if r is not None else [])


@bp.post("/peer-review/cases/<cid>/committee-review")
def committee_review(cid):
    actor = require_roles("CommitteeMember")
    case = get_case(cid)
    require_chair(actor)
    guard_case_state(case, ("RESPONDED",))
    case["status"] = "COMMITTEE_REVIEW"
    touch(case)
    return success(pub(case))


@bp.post("/peer-review/cases/<cid>/finalize-after-response")
def finalize_after_response(cid):
    actor = require_roles("CommitteeMember")
    case = get_case(cid)
    require_chair(actor)
    guard_case_state(case, ("COMMITTEE_REVIEW",))
    b = get_body()
    note = opt_str(b, "reconsideration_note")
    d = deliberation_for(cid)
    d["rating"] = compute_rating(submitted_assignments(cid))
    d["reconsideration_note"] = note
    d["reconsidered_at"] = now_iso()
    touch(d)
    case["status"] = "CLOSED"
    case["closure_basis"] = "POST_RESPONSE"
    case["closed_at"] = now_iso()
    touch(case)
    run_resolution_cascade(case)
    return success(pub(d))


@bp.post("/peer-review/cases/<cid>/close-no-response")
def close_no_response(cid):
    require_roles("QualityDirector")
    case = get_case(cid)
    guard_case_state(case, ("NOTIFIED",))
    notif = notification_for(cid)
    if store.clock <= notif["_deadline_dt"]:
        raise ApiError("ERR_RESPONSE_WINDOW_OPEN", 409, "response window is still open")
    case["status"] = "CLOSED"
    case["closure_basis"] = "NO_RESPONSE"
    case["closed_at"] = now_iso()
    touch(case)
    run_resolution_cascade(case)
    return success(pub(case))


@bp.post("/peer-review/cases/<cid>/refer-external")
def refer_external(cid):
    require_roles("QualityDirector")
    case = get_case(cid)
    guard_case_state(case, ("DELIBERATION", "COMMITTEE_REVIEW"))
    b = get_body()
    reason = req_str(b, "reason")
    rec = make_ledger()
    rec.update({"case_id": cid, "reason": reason, "referred_at": now_iso()})
    store.external_referrals[rec["id"]] = rec
    case["status"] = "EXTERNAL_REVIEW"
    touch(case)
    run_resolution_cascade(case)
    return success(pub(rec), 201)


@bp.get("/peer-review/cases/<cid>/external-referrals")
def list_external_referrals(cid):
    require_roles(*STAFF_ROLES)
    get_case(cid)
    r = referral_for(cid)
    return _list_response([r] if r is not None else [])
