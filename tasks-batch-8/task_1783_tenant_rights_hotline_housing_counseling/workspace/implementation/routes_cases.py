"""Cases, case notes, and follow-ups."""

from datetime import timedelta

from flask import Blueprint, request

from db import store, now
from errors import (
    raise_err, invalid_request, not_found, forbidden, invalid_state,
    ERR_STALE_VERSION, ERR_CALLER_PII_PURGED, ERR_SCRIPT_REVIEWER_CONFLICT,
    ERR_SCRIPT_NOT_PUBLISHED, ERR_CASE_NOT_VERIFIED, ERR_CASE_HAS_OPEN_ITEMS,
    ERR_ANONYMOUS_FOLLOW_UP_FORBIDDEN, ERR_FOLLOW_UP_TOO_SOON,
)
from middleware import require_roles
from response import ok_object, ok_list
from serializers import case_out, note_out, follow_up_out
from services import (
    make_record, make_note, bump, recompute_case, current_published_script,
    escalate_case, bubble_up_case, create_follow_up, add_system_note,
    ISSUE_CATEGORIES, NONTERMINAL_FOLLOWUP, OPEN_COUNSELING_STATES,
)
from util import (
    get_payload, check_unknown, require, as_str, as_int, as_bool, as_enum,
    parse_dt, parse_date, page_of, query_enum,
)

bp = Blueprint("cases", __name__)

CASE_STATUSES = ("OPEN", "IN_PROGRESS", "PENDING_FOLLOW_UP", "ESCALATED", "RESOLVED", "CLOSED")
TIERS = ("STANDARD", "ELEVATED", "CRITICAL")
FOLLOWUP_STATUSES = ("SCHEDULED", "DUE", "COMPLETED", "MISSED", "CANCELLED")
CASE_ROLES = ("Counselor", "HotlineSupervisor")
FACT_FIELDS = (
    "eviction_notice_date", "notice_served_at", "habitability_reported_at",
    "deposit_amount_cents", "monthly_rent_cents", "deposit_days_held", "legal_hold",
)


def _parse_facts(data):
    facts = {}
    if "eviction_notice_date" in data:
        v = data["eviction_notice_date"]
        facts["eviction_notice_date"] = None if v is None else parse_date(v, "eviction_notice_date")
    if "notice_served_at" in data:
        v = data["notice_served_at"]
        facts["notice_served_at"] = None if v is None else parse_dt(v, "notice_served_at")
    if "habitability_reported_at" in data:
        v = data["habitability_reported_at"]
        facts["habitability_reported_at"] = None if v is None else parse_dt(v, "habitability_reported_at")
    for f in ("deposit_amount_cents", "monthly_rent_cents", "deposit_days_held"):
        if f in data:
            v = data[f]
            facts[f] = None if v is None else as_int(v, f)
    if "legal_hold" in data:
        facts["legal_hold"] = as_bool(data["legal_hold"], "legal_hold")
    return facts


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

@bp.route("/hotline/cases", methods=["POST"])
def create_case():
    _, uid = require_roles(*CASE_ROLES)
    data = get_payload()
    check_unknown(data, {
        "caller_id", "opened_from_session_id", "jurisdiction_id", "issue_category",
        *FACT_FIELDS,
    })
    caller_id = as_str(require(data, "caller_id"), "caller_id")
    session_id = as_str(require(data, "opened_from_session_id"), "opened_from_session_id")
    jurisdiction_id = as_str(require(data, "jurisdiction_id"), "jurisdiction_id")
    issue_category = as_enum(require(data, "issue_category"), "issue_category", ISSUE_CATEGORIES)
    facts = _parse_facts(data)
    caller = store.callers.get(caller_id)
    if caller is None:
        invalid_request("caller_id does not reference an existing caller")
    session = store.sessions.get(session_id)
    if session is None:
        invalid_request("opened_from_session_id does not reference an existing session")
    if jurisdiction_id not in store.jurisdictions:
        invalid_request("jurisdiction_id does not reference an existing jurisdiction")
    if session["caller_id"] != caller_id:
        invalid_request("case caller_id must equal the referenced session's caller_id")
    if session["session_status"] not in ("ACTIVE", "WRAPPED_UP"):
        invalid_state("a case can only be opened from an ACTIVE or WRAPPED_UP session")
    if caller["pii_purged"]:
        raise_err(ERR_CALLER_PII_PURGED, "caller PII has been purged; case opening refused")
    rec = make_record({
        "caller_id": caller_id,
        "opened_from_session_id": session_id,
        "jurisdiction_id": jurisdiction_id,
        "issue_category": issue_category,
        "opened_by_counselor_id": uid,
        "eviction_notice_date": facts.get("eviction_notice_date"),
        "notice_served_at": facts.get("notice_served_at"),
        "habitability_reported_at": facts.get("habitability_reported_at"),
        "deposit_amount_cents": facts.get("deposit_amount_cents"),
        "monthly_rent_cents": facts.get("monthly_rent_cents"),
        "deposit_days_held": facts.get("deposit_days_held"),
        "legal_hold": facts.get("legal_hold", False),
        "priority_score": 0,
        "urgency_tier": "STANDARD",
        "score_variant": "PROVISIONAL",
        "verified_by_counselor_id": None,
        "missed_follow_up_count": 0,
        "required_follow_up_count": 1,
        "escalation_level": 0,
        "last_escalated_at": None,
        "deposit_exposure_cents": None,
        "closed_at": None,
        "status": "OPEN",
    })
    recompute_case(rec)
    store.cases[rec["id"]] = rec
    return ok_object(case_out(rec), status=201)


@bp.route("/hotline/cases/<cid>", methods=["GET"])
def get_case(cid):
    require_roles("Counselor", "HotlineSupervisor", "DataProtectionOfficer")
    rec = store.cases.get(cid)
    if rec is None:
        not_found("case not found")
    return ok_object(case_out(rec))


@bp.route("/hotline/cases", methods=["GET"])
def list_cases():
    require_roles("Counselor", "HotlineSupervisor", "DataProtectionOfficer")
    caller_id = request.args.get("caller_id")
    jurisdiction_id = request.args.get("jurisdiction_id")
    session_id = request.args.get("opened_from_session_id")
    opened_by = request.args.get("opened_by_counselor_id")
    verified_by = request.args.get("verified_by_counselor_id")
    status = query_enum("status", CASE_STATUSES)
    tier = query_enum("urgency_tier", TIERS)
    recs = list(store.cases.values())
    if caller_id is not None:
        recs = [r for r in recs if r["caller_id"] == caller_id]
    if jurisdiction_id is not None:
        recs = [r for r in recs if r["jurisdiction_id"] == jurisdiction_id]
    if session_id is not None:
        recs = [r for r in recs if r["opened_from_session_id"] == session_id]
    if opened_by is not None:
        recs = [r for r in recs if r["opened_by_counselor_id"] == opened_by]
    if verified_by is not None:
        recs = [r for r in recs if r["verified_by_counselor_id"] == verified_by]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    if tier is not None:
        recs = [r for r in recs if r["urgency_tier"] == tier]
    page, total, limit, offset = page_of(recs)
    return ok_list([case_out(r) for r in page], total, limit, offset)


@bp.route("/hotline/cases/<cid>", methods=["PATCH"])
def patch_case(cid):
    require_roles(*CASE_ROLES)
    rec = store.cases.get(cid)
    if rec is None:
        not_found("case not found")
    data = get_payload()
    check_unknown(data, set(FACT_FIELDS))
    facts = _parse_facts(data)
    if rec["status"] == "CLOSED":
        # litigation holds legitimately attach after closure; other fact edits do not
        if any(f != "legal_hold" for f in facts):
            invalid_state("fact edits are rejected on a CLOSED case")
        if "legal_hold" in facts:
            rec["legal_hold"] = facts["legal_hold"]
            bump(rec)
        return ok_object(case_out(rec))
    for f, v in facts.items():
        rec[f] = v
    recompute_case(rec)
    bump(rec)
    return ok_object(case_out(rec))


@bp.route("/hotline/cases/<cid>/verify", methods=["POST"])
def verify_case(cid):
    _, uid = require_roles(*CASE_ROLES)
    rec = store.cases.get(cid)
    if rec is None:
        not_found("case not found")
    if uid == rec["opened_by_counselor_id"]:
        raise_err(ERR_SCRIPT_REVIEWER_CONFLICT,
                  "segregation of duties: verifier must differ from opener")
    rec["score_variant"] = "VERIFIED"
    rec["verified_by_counselor_id"] = uid
    recompute_case(rec)
    bump(rec)
    return ok_object(case_out(rec))


@bp.route("/hotline/cases/<cid>/state", methods=["POST"])
def transition_case(cid):
    role, uid = require_roles(*CASE_ROLES)
    rec = store.cases.get(cid)
    if rec is None:
        not_found("case not found")
    data = get_payload()
    check_unknown(data, {"to_status"})
    to_status = as_enum(require(data, "to_status"), "to_status", CASE_STATUSES)
    current = rec["status"]

    if current == "OPEN" and to_status == "IN_PROGRESS":
        if current_published_script(rec["jurisdiction_id"], rec["issue_category"]) is None:
            raise_err(ERR_SCRIPT_NOT_PUBLISHED,
                      "no PUBLISHED script exists for the case's pair")
        rec["status"] = "IN_PROGRESS"
        bump(rec)
        return ok_object(case_out(rec))

    if current == "IN_PROGRESS" and to_status == "ESCALATED":
        if rec["urgency_tier"] != "CRITICAL":
            invalid_state("only CRITICAL cases may be escalated manually")
        if rec["score_variant"] != "VERIFIED":
            raise_err(ERR_CASE_NOT_VERIFIED, "manual escalation requires a verified case")
        escalate_case(rec)
        return ok_object(case_out(rec))

    if current == "ESCALATED" and to_status == "IN_PROGRESS":
        if role != "HotlineSupervisor":
            forbidden("de-escalation is HotlineSupervisor-only")
        rec["status"] = "IN_PROGRESS"
        bump(rec)
        # compensation: auto-created SCHEDULED follow-ups are cancelled
        for fu in sorted(store.follow_ups.values(), key=lambda f: (f["created_at"], f["_seq"])):
            if fu["case_id"] == rec["id"] and fu["auto_created"] and fu["status"] == "SCHEDULED":
                fu["status"] = "CANCELLED"
                bump(fu)
        return ok_object(case_out(rec))

    if to_status == "RESOLVED" and current in ("IN_PROGRESS", "PENDING_FOLLOW_UP", "ESCALATED"):
        open_fu = any(
            f["case_id"] == rec["id"] and f["status"] in NONTERMINAL_FOLLOWUP
            for f in store.follow_ups.values()
        )
        open_ref = any(
            r["case_id"] == rec["id"] and r["status"] in ("PROPOSED", "DISPATCHED")
            for r in store.referrals.values()
        )
        if open_fu or open_ref:
            raise_err(ERR_CASE_HAS_OPEN_ITEMS,
                      "case has open follow-ups or referrals")
        rec["status"] = "RESOLVED"
        bump(rec)
        return ok_object(case_out(rec))

    if current == "RESOLVED" and to_status == "IN_PROGRESS":
        rec["status"] = "IN_PROGRESS"
        recompute_case(rec)  # reopen recomputes; missed_follow_up_count retained
        bump(rec)
        return ok_object(case_out(rec))

    if to_status == "CLOSED" and current in ("RESOLVED", "OPEN"):
        if role != "HotlineSupervisor":
            forbidden("case closure is HotlineSupervisor-only")
        rec["status"] = "CLOSED"
        rec["closed_at"] = now()
        bump(rec)
        return ok_object(case_out(rec))

    invalid_state("case transition %s -> %s is not allowed" % (current, to_status))


# ---------------------------------------------------------------------------
# Case notes (immutable, append-only; OCC on the case version)
# ---------------------------------------------------------------------------

@bp.route("/hotline/cases/<cid>/notes", methods=["POST"])
def create_note(cid):
    _, uid = require_roles(*CASE_ROLES)
    case = store.cases.get(cid)
    if case is None:
        not_found("case not found")
    data = get_payload()
    check_unknown(data, {"body", "is_confidential", "expected_case_version"})
    body = as_str(require(data, "body"), "body")
    is_confidential = as_bool(require(data, "is_confidential"), "is_confidential")
    expected = as_int(require(data, "expected_case_version"), "expected_case_version")
    if expected != case["version"]:
        raise_err(ERR_STALE_VERSION, "expected_case_version does not match the case's current version")
    if case["status"] not in OPEN_COUNSELING_STATES:
        invalid_state("notes may only be appended while the case is in an open counseling state")
    rec = make_note({
        "case_id": cid,
        "counselor_id": uid,
        "body": body,
        "is_confidential": is_confidential,
        "system_generated": False,
    })
    store.notes[rec["id"]] = rec
    bump(case)
    return ok_object(note_out(rec), status=201)


@bp.route("/hotline/cases/<cid>/notes", methods=["GET"])
def list_notes(cid):
    require_roles("Counselor", "HotlineSupervisor", "DataProtectionOfficer")
    case = store.cases.get(cid)
    if case is None:
        not_found("case not found")
    recs = [n for n in store.notes.values() if n["case_id"] == cid]
    page, total, limit, offset = page_of(recs)
    return ok_list([note_out(n) for n in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Follow-ups
# ---------------------------------------------------------------------------

@bp.route("/hotline/cases/<cid>/follow-ups", methods=["POST"])
def create_follow_up_route(cid):
    require_roles(*CASE_ROLES)
    case = store.cases.get(cid)
    if case is None:
        not_found("case not found")
    data = get_payload()
    check_unknown(data, {"scheduled_for"})
    scheduled_for = parse_dt(require(data, "scheduled_for"), "scheduled_for")
    if scheduled_for <= now():
        invalid_request("scheduled_for must lie strictly after the current logical time")
    if case["status"] not in OPEN_COUNSELING_STATES:
        invalid_state("follow-ups attach only to cases in an open counseling state")
    caller = store.callers[case["caller_id"]]
    if caller["is_anonymous"]:
        raise_err(ERR_ANONYMOUS_FOLLOW_UP_FORBIDDEN,
                  "anonymous callers cannot receive follow-ups")
    spacing = timedelta(hours=24)
    for fu in store.follow_ups.values():
        if fu["case_id"] == cid and fu["status"] in NONTERMINAL_FOLLOWUP:
            if abs(scheduled_for - fu["scheduled_for"]) < spacing:
                raise_err(ERR_FOLLOW_UP_TOO_SOON,
                          "scheduled_for is within 24h of another non-terminal follow-up")
    rec = create_follow_up(case, scheduled_for, auto_created=False)
    if case["status"] == "IN_PROGRESS":
        case["status"] = "PENDING_FOLLOW_UP"
        bump(case)
    return ok_object(follow_up_out(rec), status=201)


@bp.route("/hotline/cases/<cid>/follow-ups", methods=["GET"])
def list_follow_ups(cid):
    require_roles(*CASE_ROLES)
    case = store.cases.get(cid)
    if case is None:
        not_found("case not found")
    status = query_enum("status", FOLLOWUP_STATUSES)
    recs = [f for f in store.follow_ups.values() if f["case_id"] == cid]
    if status is not None:
        recs = [f for f in recs if f["status"] == status]
    page, total, limit, offset = page_of(recs)
    return ok_list([follow_up_out(f) for f in page], total, limit, offset)


@bp.route("/hotline/follow-ups/<fid>/state", methods=["POST"])
def transition_follow_up(fid):
    _, uid = require_roles(*CASE_ROLES)
    rec = store.follow_ups.get(fid)
    if rec is None:
        not_found("follow-up not found")
    data = get_payload()
    check_unknown(data, {"to_status", "outcome"})
    to_status = as_enum(require(data, "to_status"), "to_status", FOLLOWUP_STATUSES)
    current = rec["status"]
    case = store.cases.get(rec["case_id"])

    if current == "DUE" and to_status == "COMPLETED":
        outcome = data.get("outcome")
        if outcome is None:
            invalid_request("outcome is required for COMPLETED")
        as_str(outcome, "outcome")
        rec["status"] = "COMPLETED"
        rec["completed_at"] = now()
        rec["outcome"] = outcome
        bump(rec)
        if case is not None:
            add_system_note(case, "Follow-up completed. Outcome: %s" % outcome)
            bubble_up_case(case)
        return ok_object(follow_up_out(rec))

    if current == "SCHEDULED" and to_status == "CANCELLED":
        rec["status"] = "CANCELLED"
        bump(rec)
        if case is not None:
            bubble_up_case(case)
        return ok_object(follow_up_out(rec))

    invalid_state("follow-up transition %s -> %s is not allowed" % (current, to_status))
