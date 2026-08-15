"""Referral submission (eligibility gauntlet + bonus quote) and the recruiting
pipeline actions with the append-only audit log."""

from flask import Blueprint, request, g

from db import store
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_FORBIDDEN, ERR_NOT_FOUND,
                    ERR_INVALID_STATE, ERR_ALREADY_TERMINAL,
                    ERR_REQUISITION_NOT_OPEN, ERR_REFERRER_SUSPENDED,
                    ERR_SELF_REFERRAL, ERR_CANDIDATE_IN_COOLDOWN,
                    ERR_DUPLICATE_REFERRAL, ERR_REFERRER_NOT_ACTIVE,
                    ERR_REFERRER_INELIGIBLE_TENURE, ERR_REFERRER_EXCLUDED,
                    ERR_ROLE_NOT_REFERRAL_ELIGIBLE, ERR_NO_ACTIVE_POLICY,
                    ERR_HIRE_DATE_IN_FUTURE)
from middleware import require_role, ALL_ROLES
import services as svc
from services import new_entity, touch
from util import (opt_str, req_dt, check_enum, respond_object, respond_list,
                  parse_pagination, paginate, round_half_up_cents)
from views import referral_view, milestone_view, event_view
from routes.candidates import normalize_email

bp = Blueprint("referrals", __name__)

READ_ROLES = tuple(ALL_ROLES)


def _get_referral(referral_id):
    r = store.referrals.get(referral_id)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Referral not found")
    return r


def _state_gate(referral, allowed_from, action_desc):
    if referral["status"] in svc.REFERRAL_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "Referral is in terminal state %s" % referral["status"])
    if referral["status"] not in allowed_from:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Cannot %s a referral in state %s" % (action_desc, referral["status"]))


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------

@bp.post("/erp/referrals")
def submit_referral():
    body = request.get_json(silent=True) or {}
    # Step 2: request shape
    referrer_id = body.get("referrer_id")
    if not isinstance(referrer_id, str) or not referrer_id:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing or invalid required field: referrer_id")
    job_requisition_id = body.get("job_requisition_id")
    if not isinstance(job_requisition_id, str) or not job_requisition_id:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing or invalid required field: job_requisition_id")
    candidate_id = opt_str(body, "candidate_id", None)
    candidate_email = opt_str(body, "candidate_email", None)
    candidate_full_name = opt_str(body, "candidate_full_name", None)
    candidate_phone = opt_str(body, "candidate_phone", None)
    note = opt_str(body, "note", None)
    if candidate_id is None and candidate_email is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Either candidate_id or candidate_email must be supplied")
    # Step 4: role
    require_role("Employee", "Recruiter")
    # Step 5: ownership — an Employee acts only as itself.
    if g.role == "Employee" and referrer_id != g.user_id:
        raise ApiError(ERR_FORBIDDEN, 403,
                       "Employee may only submit referrals as itself")
    # Step 6: existence of body-referenced resources
    referrer = store.employees.get(referrer_id)
    if referrer is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Referrer employee not found")
    requisition = store.requisitions.get(job_requisition_id)
    if requisition is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Job requisition not found")

    # Resolve the candidate: by id, or match/create by normalized email.
    candidate = None
    pending_new_candidate = None
    if candidate_id is not None:
        candidate = store.candidates.get(candidate_id)
        if candidate is None:
            raise ApiError(ERR_NOT_FOUND, 404, "Candidate not found")
    else:
        target = normalize_email(candidate_email)
        for c in store.candidates.values():
            if c["normalized_email"] == target:
                candidate = c
                break
        if candidate is None:
            if not candidate_full_name:
                raise ApiError(ERR_INVALID_REQUEST, 400,
                               "candidate_full_name is required when candidate_email matches no candidate")
            pending_new_candidate = {
                "full_name": candidate_full_name,
                "email": candidate_email,
                "normalized_email": target,
                "phone": candidate_phone,
                "prior_application_at": None,
            }

    # --- Business gauntlet (PRD 3.3, fixed order) ---
    # 1. Requisition must be OPEN.
    if requisition["status"] != "OPEN":
        raise ApiError(ERR_REQUISITION_NOT_OPEN, 409,
                       "Requisition is not OPEN (currently %s)" % requisition["status"])
    # 2. Referrer must not be suspended.
    if svc.risk_score(referrer["id"]) >= svc.SUSPEND_THRESHOLD:
        raise ApiError(ERR_REFERRER_SUSPENDED, 422, "Referrer is suspended from the program")
    # 3. Self-referral: candidate normalized email must differ from referrer's.
    candidate_norm = (candidate["normalized_email"] if candidate is not None
                      else pending_new_candidate["normalized_email"])
    if candidate_norm == normalize_email(referrer["email"]):
        svc.create_abuse_case(referrer["id"], None, "SELF_REFERRAL", "system")
        raise ApiError(ERR_SELF_REFERRAL, 422, "Candidate is the referrer themselves")
    # 4. Candidate must be referable: not in cooldown, not currently HIRED.
    if candidate is not None:
        cooldown_until = svc.candidate_cooldown_until(candidate)
        if cooldown_until is not None and store.clock < cooldown_until:
            raise ApiError(ERR_CANDIDATE_IN_COOLDOWN, 422,
                           "Candidate is in the re-referral cooldown window")
        if candidate["global_status"] == "HIRED":
            raise ApiError(ERR_CANDIDATE_IN_COOLDOWN, 422,
                           "Candidate is currently hired through the program")
        # 5. No duplicate non-terminal referral for candidate + requisition.
        for r in store.referrals.values():
            if (r["candidate_id"] == candidate["id"]
                    and r["job_requisition_id"] == requisition["id"]
                    and r["status"] not in svc.REFERRAL_TERMINAL):
                raise ApiError(ERR_DUPLICATE_REFERRAL, 409,
                               "A non-terminal referral already exists for this candidate and requisition")
    # 6. Referrer must be ACTIVE.
    if referrer["employment_status"] != "ACTIVE":
        raise ApiError(ERR_REFERRER_NOT_ACTIVE, 422, "Referrer is not an ACTIVE employee")
    # 7. Tenure against the ACTIVE policy's min_tenure_days (vacuous when no
    #    ACTIVE policy exists — that failure surfaces at step 10).
    policy = svc.active_policy()
    if policy is not None and svc.tenure_days(referrer) < policy["min_tenure_days"]:
        raise ApiError(ERR_REFERRER_INELIGIBLE_TENURE, 422,
                       "Referrer tenure is below the policy minimum")
    # 8. Exclusions: recruiters and MANAGER+ may not refer into their own department.
    same_department = requisition["department"] == referrer["department"]
    if same_department and (referrer["is_recruiter"]
                            or referrer["job_level"] in ("MANAGER", "DIRECTOR", "EXECUTIVE")):
        raise ApiError(ERR_REFERRER_EXCLUDED, 422,
                       "Referrer is excluded from referring into their own department")
    # 9. Requisition must be referral-eligible.
    if not requisition["referral_eligible"]:
        raise ApiError(ERR_ROLE_NOT_REFERRAL_ELIGIBLE, 422,
                       "Requisition is not referral-eligible")
    # 10. An ACTIVE policy must exist to pin.
    if policy is None:
        raise ApiError(ERR_NO_ACTIVE_POLICY, 422, "No ACTIVE policy version exists")

    now = store.clock

    # Create the candidate (email path, no match).
    if candidate is None:
        candidate = new_entity(store.candidates, dict(pending_new_candidate,
                                                      global_status="AVAILABLE",
                                                      last_terminal_outcome_at=None,
                                                      hired_via_referral_id=None,
                                                      departed_at=None))

    # --- Bonus quote (pinned evaluation order, PRD 3.3) ---
    base = policy[svc.TIER_FIELD[requisition["level"]]]
    campaign = None
    for c in store.campaigns.values():
        if (c["job_requisition_id"] == requisition["id"] and c["status"] == "ACTIVE"
                and c["window_start"] <= now <= c["window_end"]):
            if c["max_payouts"] is None or svc.campaign_payouts_count(c) < c["max_payouts"]:
                campaign = c
            break
    uplift = 0
    if campaign is not None and referrer["job_level"] != "EXECUTIVE":
        raw = (round_half_up_cents(base * campaign["multiplier_bps"], 10000)
               - base + campaign["flat_addon_cents"])
        uplift = max(0, min(raw, svc.campaign_remaining(campaign)))
    provisional, _committed = svc.annual_accumulators(referrer["id"])
    cap_remaining = policy["annual_cap_cents"] - provisional
    bonus_total = max(0, min(base + uplift, cap_remaining))

    referral = new_entity(store.referrals, {
        "referrer_id": referrer["id"],
        "candidate_id": candidate["id"],
        "job_requisition_id": requisition["id"],
        "campaign_id": campaign["id"] if campaign is not None else None,
        "policy_version_id": policy["id"],
        "status": "SUBMITTED",
        "submitted_at": now,
        "note": note,
        "bonus_base_cents": base,
        "campaign_uplift_cents": uplift,
        "bonus_total_cents": bonus_total,
        "hire_date": None,
        "retention_due_at": None,
        "clawback_until": None,
        "last_decision_reason": None,
        "uplift_spent_cents": 0,
    })

    # Attachment reserves budget (uplift may be 0; attachment still counts).
    if campaign is not None:
        svc.campaign_reserve(campaign, uplift)

    # Candidate becomes IN_PROCESS.
    if candidate["global_status"] in ("AVAILABLE", "DEPARTED"):
        candidate["global_status"] = "IN_PROCESS"
        touch(candidate)

    svc.append_event(referral, "SUBMIT", None, "SUBMITTED", g.user_id, note)

    # Non-blocking automatic abuse detectors.
    svc.auto_velocity_check(referrer["id"], referral, policy)
    svc.auto_duplicate_ring_check(candidate["id"], referral)

    return respond_object(referral_view(referral), status=201)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

@bp.get("/erp/referrals")
def list_referrals():
    require_role(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = svc.sort_by_created(store.referrals.values())
    # The Employee role's list is always scoped to its own records.
    if g.role == "Employee":
        items = [r for r in items if r["referrer_id"] == g.user_id]
    for param in ("status", "referrer_id", "candidate_id", "job_requisition_id",
                  "campaign_id", "policy_version_id"):
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if r[param] == value]
    page, total = paginate(items, limit, offset)
    return respond_list([referral_view(r) for r in page], total, limit, offset)


@bp.get("/erp/referrals/<referral_id>")
def get_referral(referral_id):
    require_role(*READ_ROLES)
    referral = _get_referral(referral_id)
    if g.role == "Employee" and referral["referrer_id"] != g.user_id:
        raise ApiError(ERR_FORBIDDEN, 403, "Employee may only read its own referrals")
    return respond_object(referral_view(referral))


@bp.get("/erp/referrals/<referral_id>/milestones")
def referral_milestones(referral_id):
    require_role(*READ_ROLES)
    _get_referral(referral_id)
    limit, offset = parse_pagination(request.args)
    items = svc.milestones_of(referral_id)
    page, total = paginate(items, limit, offset)
    return respond_list([milestone_view(m) for m in page], total, limit, offset)


@bp.get("/erp/referrals/<referral_id>/events")
def referral_events(referral_id):
    require_role(*READ_ROLES)
    _get_referral(referral_id)
    limit, offset = parse_pagination(request.args)
    items = svc.sort_by_created(
        [e for e in store.events.values() if e["referral_id"] == referral_id])
    page, total = paginate(items, limit, offset)
    return respond_list([event_view(e) for e in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Pipeline actions
# ---------------------------------------------------------------------------

@bp.post("/erp/referrals/<referral_id>/review")
def review_referral(referral_id):
    require_role("Recruiter")
    referral = _get_referral(referral_id)
    _state_gate(referral, ("SUBMITTED",), "review")
    old = referral["status"]
    referral["status"] = "UNDER_REVIEW"
    touch(referral)
    svc.append_event(referral, "REVIEW", old, "UNDER_REVIEW", g.user_id)
    return respond_object(referral_view(referral))


@bp.post("/erp/referrals/<referral_id>/request-info")
def request_info(referral_id):
    body = request.get_json(silent=True) or {}
    note = opt_str(body, "note", None)
    require_role("Recruiter")
    referral = _get_referral(referral_id)
    _state_gate(referral, ("UNDER_REVIEW",), "request-info")
    old = referral["status"]
    referral["status"] = "NEEDS_INFO"
    touch(referral)
    svc.append_event(referral, "REQUEST_INFO", old, "NEEDS_INFO", g.user_id, note)
    return respond_object(referral_view(referral))


@bp.post("/erp/referrals/<referral_id>/provide-info")
def provide_info(referral_id):
    body = request.get_json(silent=True) or {}
    note = opt_str(body, "note", None)
    require_role("Recruiter", "Employee")
    referral = _get_referral(referral_id)
    if g.role == "Employee" and referral["referrer_id"] != g.user_id:
        raise ApiError(ERR_FORBIDDEN, 403,
                       "Employee may only provide info on its own referral")
    _state_gate(referral, ("NEEDS_INFO",), "provide-info")
    old = referral["status"]
    referral["status"] = "UNDER_REVIEW"
    touch(referral)
    svc.append_event(referral, "PROVIDE_INFO", old, "UNDER_REVIEW", g.user_id, note)
    return respond_object(referral_view(referral))


@bp.post("/erp/referrals/<referral_id>/qualify")
def qualify_referral(referral_id):
    require_role("Recruiter")
    referral = _get_referral(referral_id)
    _state_gate(referral, ("UNDER_REVIEW",), "qualify")
    old = referral["status"]
    referral["status"] = "QUALIFIED"
    touch(referral)
    svc.append_event(referral, "QUALIFY", old, "QUALIFIED", g.user_id)
    return respond_object(referral_view(referral))


@bp.post("/erp/referrals/<referral_id>/reject")
def reject_referral(referral_id):
    body = request.get_json(silent=True) or {}
    reason_code = body.get("reason_code")
    if not isinstance(reason_code, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing or invalid required field: reason_code")
    note = opt_str(body, "note", None)
    check_enum(reason_code, svc.REJECT_REASONS, "reason_code")
    require_role("Recruiter")
    referral = _get_referral(referral_id)
    _state_gate(referral, ("UNDER_REVIEW",), "reject")
    to_state = {
        "DUPLICATE": "REJECTED_DUPLICATE",
        "PRIOR_CANDIDATE": "REJECTED_PRIOR_CANDIDATE",
        "OTHER": "REJECTED_OTHER",
    }[reason_code]
    svc.transition_referral_terminal(referral, to_state, "REJECT", g.user_id,
                                     note=note, reason=reason_code)
    return respond_object(referral_view(referral))


# Advance pairs: (from_state, to_state) -> allowed role.
ADVANCE_PAIRS = {
    ("QUALIFIED", "SCREENING"): "Recruiter",
    ("SCREENING", "INTERVIEWING"): "Recruiter",
    ("INTERVIEWING", "OFFER_EXTENDED"): "HiringManager",
}


@bp.post("/erp/referrals/<referral_id>/advance")
def advance_referral(referral_id):
    body = request.get_json(silent=True) or {}
    to_state = body.get("to_state")
    if not isinstance(to_state, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing or invalid required field: to_state")
    note = opt_str(body, "note", None)
    check_enum(to_state, svc.ADVANCE_TARGETS, "to_state")
    require_role("Recruiter", "HiringManager")
    referral = _get_referral(referral_id)
    if referral["status"] in svc.REFERRAL_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "Referral is in terminal state %s" % referral["status"])
    pair = (referral["status"], to_state)
    if pair not in ADVANCE_PAIRS:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Cannot advance from %s to %s" % (referral["status"], to_state))
    if ADVANCE_PAIRS[pair] != g.role:
        raise ApiError(ERR_FORBIDDEN, 403,
                       "Role %s may not perform this advancement" % g.role)
    old = referral["status"]
    referral["status"] = to_state
    touch(referral)
    svc.append_event(referral, "ADVANCE", old, to_state, g.user_id, note)
    return respond_object(referral_view(referral))


@bp.post("/erp/referrals/<referral_id>/offer-declined")
def offer_declined(referral_id):
    body = request.get_json(silent=True) or {}
    note = opt_str(body, "note", None)
    require_role("Recruiter", "HiringManager")
    referral = _get_referral(referral_id)
    _state_gate(referral, ("OFFER_EXTENDED",), "offer-declined")
    old = referral["status"]
    referral["status"] = "INTERVIEWING"
    touch(referral)
    svc.append_event(referral, "OFFER_DECLINED", old, "INTERVIEWING", g.user_id, note)
    return respond_object(referral_view(referral))


@bp.post("/erp/referrals/<referral_id>/hire")
def hire(referral_id):
    body = request.get_json(silent=True) or {}
    hire_date = req_dt(body, "hire_date")
    note = opt_str(body, "note", None)
    require_role("HiringManager")
    referral = _get_referral(referral_id)
    _state_gate(referral, ("OFFER_EXTENDED",), "hire")
    if hire_date > store.clock:
        raise ApiError(ERR_HIRE_DATE_IN_FUTURE, 422, "hire_date must be at or before now")
    svc.hire_referral(referral, hire_date, g.user_id, note)
    return respond_object(referral_view(referral))


# Not-selected: from QUALIFIED/SCREENING/INTERVIEWING the decision belongs to a
# Recruiter; from OFFER_EXTENDED to a HiringManager.
NOT_SELECTED_ACTORS = {
    "QUALIFIED": "Recruiter",
    "SCREENING": "Recruiter",
    "INTERVIEWING": "Recruiter",
    "OFFER_EXTENDED": "HiringManager",
}


@bp.post("/erp/referrals/<referral_id>/not-selected")
def not_selected(referral_id):
    body = request.get_json(silent=True) or {}
    note = opt_str(body, "note", None)
    require_role("Recruiter", "HiringManager")
    referral = _get_referral(referral_id)
    if referral["status"] in svc.REFERRAL_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "Referral is in terminal state %s" % referral["status"])
    if referral["status"] not in NOT_SELECTED_ACTORS:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Cannot mark a referral in state %s as not selected" % referral["status"])
    if NOT_SELECTED_ACTORS[referral["status"]] != g.role:
        raise ApiError(ERR_FORBIDDEN, 403,
                       "Role %s may not make the not-selected decision from %s"
                       % (g.role, referral["status"]))
    svc.transition_referral_terminal(referral, "NOT_SELECTED", "NOT_SELECTED",
                                     g.user_id, note=note)
    return respond_object(referral_view(referral))


@bp.post("/erp/referrals/<referral_id>/withdraw")
def withdraw(referral_id):
    body = request.get_json(silent=True) or {}
    note = opt_str(body, "note", None)
    require_role("Employee")
    referral = _get_referral(referral_id)
    if referral["referrer_id"] != g.user_id:
        raise ApiError(ERR_FORBIDDEN, 403, "Only the referrer may withdraw this referral")
    _state_gate(referral, tuple(svc.REFERRAL_PRE_HIRE), "withdraw")
    svc.transition_referral_terminal(referral, "WITHDRAWN", "WITHDRAW",
                                     g.user_id, note=note)
    return respond_object(referral_view(referral))
