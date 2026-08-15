"""Appeal endpoints (PRD 3.6): filing, officer assignment, decision cascades."""
from datetime import timedelta
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE_TRANSITION, ERR_CASE_ALREADY_TERMINAL,
    ERR_APPEAL_WINDOW_EXPIRED, ERR_APPEAL_TARGET_INVALID,
    ERR_APPEAL_OUTCOME_INCOMPATIBLE, ERR_REMAND_SCOPE_MISMATCH,
    ERR_PARTY_BINDING_MISMATCH, ERR_NOT_ASSIGNED_APPEAL_OFFICER,
    ERR_OFFICIAL_IS_CASE_PARTY, ERR_SANCTION_OUTSIDE_MATRIX,
    ERR_RESTITUTION_ITEMS_REQUIRED, ERR_INVALID_REQUEST,
)
from middleware import authorized, check_case_read_access, party_side_of, STAFF_READ_ROLES
from response import success_list, success_object
from services.core import (
    new_record, touch, public, bump_case, append_event, auto_notice, get_case,
    get_pagination, sort_items, apply_filters, check_not_case_party, check_segregation,
    TERMINAL_CASE_STATES, APPEAL_TARGETS, APPEAL_GROUNDS, APPEAL_OUTCOMES,
    REMAND_SCOPES, FILED_BY_SIDES, SANCTION_TYPES, APPEAL_WINDOW_DAYS,
)
from services.calculations import (
    tier_of, restitution_applied_cents, TIER_MATRIX, DURATION_TYPES, DURATION_LESS_TYPES,
)
from util import clock_iso, clock_dt, parse_datetime
from validate import (
    get_body, req_str, req_enum, req_enum_list, require_path, require_profile_fk,
    as_enum, as_list,
)

bp = Blueprint("appeals", __name__)

READ_ROLES = STAFF_READ_ROLES + ["Party"]


def _issued_determination(case_id):
    dets = [d for d in db["determinations"].values()
            if d["case_id"] == case_id and d["status"] == "ISSUED"]
    if not dets:
        return None
    return max(dets, key=lambda d: d["_seq"])


def _non_filing_side(filed_by_side):
    return "RESPONDENT" if filed_by_side == "COMPLAINANT" else "COMPLAINANT"


@bp.post("/cases/<cid>/appeals")
def file_appeal(cid):
    caller = authorized(["Party"])
    case = get_case(cid)
    body = get_body()
    target = as_enum(body, "appeal_target", APPEAL_TARGETS)

    # Tier 4: terminal guard — DISMISSED appeals are the express exemption.
    if case["status"] in TERMINAL_CASE_STATES:
        raise_error(ERR_CASE_ALREADY_TERMINAL,
                    f"case is in terminal state {case['status']}")
    det = None
    if target == "DETERMINATION":
        # The case-level appeal gate is single-shot.
        if case["status"] == "APPEAL_REVIEW":
            raise_error(ERR_INVALID_STATE_TRANSITION,
                        "case is already in APPEAL_REVIEW")
        det = _issued_determination(cid)
        # Tier 6: filing timeliness (inclusive deadline).
        if det is not None and clock_dt() > parse_datetime(det["appeal_deadline"]):
            raise_error(ERR_APPEAL_WINDOW_EXPIRED,
                        "the determination appeal window has expired")
        # Tier 8: target must exist and be appealable.
        if det is None:
            raise_error(ERR_APPEAL_TARGET_INVALID,
                        "no ISSUED determination on this case to appeal")
    elif target == "DISMISSAL":
        if case["status"] == "DISMISSED":
            deadline = parse_datetime(case["closed_at"]) + timedelta(days=APPEAL_WINDOW_DAYS)
            if clock_dt() > deadline:
                raise_error(ERR_APPEAL_WINDOW_EXPIRED,
                            "the dismissal appeal window has expired")
        else:
            raise_error(ERR_APPEAL_TARGET_INVALID,
                        "appeal_target DISMISSAL requires the case to be DISMISSED")
    # Tier 8: party binding — filed_by_side must match the acting party.
    side = as_enum(body, "filed_by_side", FILED_BY_SIDES)
    if side is not None:
        actor_side = party_side_of(case, caller.user_id)
        if actor_side is None or side != actor_side:
            raise_error(ERR_PARTY_BINDING_MISMATCH,
                        "filed_by_side does not match the acting party's binding on the case")
    # Tier 11: schema.
    filed_by_side = req_enum(body, "filed_by_side", FILED_BY_SIDES)
    appeal_target = req_enum(body, "appeal_target", APPEAL_TARGETS)
    grounds = req_enum_list(body, "grounds", APPEAL_GROUNDS)
    statement = req_str(body, "statement")

    rec = new_record("appeals", {
        "case_id": cid,
        "filed_by_side": filed_by_side,
        "filed_by_id": caller.user_id,
        "appeal_target": appeal_target,
        "grounds": grounds,
        "statement": statement,
        "filed_at": clock_iso(),
        "appeal_officer_id": None,
        "status": "FILED",
        "remand_scope": None,
        "decided_at": None,
    })
    if appeal_target == "DETERMINATION":
        case["status"] = "APPEAL_REVIEW"
    bump_case(case)
    append_event(cid, "APPEAL_FILED", caller,
                 {"appeal_id": rec["id"], "appeal_target": appeal_target,
                  "filed_by_side": filed_by_side})
    return success_object(public(rec), 201)


@bp.get("/cases/<cid>/appeals")
def list_appeals(cid):
    caller = authorized(READ_ROLES)
    case = get_case(cid)
    check_case_read_access(caller, case)
    items = [a for a in db["appeals"].values() if a["case_id"] == cid]
    items = apply_filters(items, {
        "status": request.args.get("status"),
        "appeal_target": request.args.get("appeal_target"),
    })
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.get("/appeals/<aid>")
def get_appeal(aid):
    caller = authorized(READ_ROLES)
    appeal = require_path("appeals", aid)
    case = get_case(appeal["case_id"])
    check_case_read_access(caller, case)
    return success_object(public(appeal))


@bp.get("/appeals")
def list_appeals_filtered():
    authorized(["TitleIXCoordinator", "CaseAdministrator", "AppealOfficer"])
    items = list(db["appeals"].values())
    items = apply_filters(items, {
        "filed_by_id": request.args.get("filed_by_id"),
        "appeal_officer_id": request.args.get("appeal_officer_id"),
        "status": request.args.get("status"),
    })
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.post("/appeals/<aid>/begin-review")
def begin_review(aid):
    caller = authorized(["TitleIXCoordinator"])
    appeal = require_path("appeals", aid)
    case = get_case(appeal["case_id"])
    if appeal["status"] != "FILED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"appeal is {appeal['status']}, not FILED")
    body = get_body()
    require_profile_fk(body, "appeal_officer_id")
    officer_id = body.get("appeal_officer_id")
    if isinstance(officer_id, str):
        # Tier 5: party bar then segregation.
        check_not_case_party(case, officer_id)
        check_segregation(case, officer_id, for_function="appeal_officer")
    appeal_officer_id = req_str(body, "appeal_officer_id")
    appeal["appeal_officer_id"] = appeal_officer_id
    appeal["status"] = "UNDER_REVIEW"
    touch(appeal)
    bump_case(case)
    append_event(case["id"], "APPEAL_REVIEW_STARTED", caller,
                 {"appeal_id": aid, "appeal_officer_id": appeal_officer_id})
    auto_notice(case["id"], "APPEAL_FILED", _non_filing_side(appeal["filed_by_side"]),
                "An appeal has been filed and review has begun.")
    append_event(case["id"], "NOTICE_SENT", caller,
                 {"notice_type": "APPEAL_FILED",
                  "recipient_side": _non_filing_side(appeal["filed_by_side"])})
    return success_object(public(appeal))


def _valid_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_modified_selections_matrix(det, selections):
    """Tier 7 for SANCTION_MODIFIED: selections within the determination's
    final-tier matrix bounds."""
    if not isinstance(selections, list) or len(selections) == 0:
        raise_error(ERR_SANCTION_OUTSIDE_MATRIX,
                    "modified_sanction_selections must be non-empty")
    final_tier = det["final_tier"]
    cap_tier = tier_of(det["final_severity_score"])
    for sel in selections:
        if not isinstance(sel, dict):
            continue
        st = sel.get("sanction_type")
        if not isinstance(st, str) or st not in SANCTION_TYPES:
            continue
        if st not in TIER_MATRIX[final_tier]:
            raise_error(ERR_SANCTION_OUTSIDE_MATRIX,
                        f"{st} is not offered by {final_tier}")
        if st == "RESTITUTION" and cap_tier in ("TIER_1", "TIER_2"):
            raise_error(ERR_SANCTION_OUTSIDE_MATRIX,
                        "RESTITUTION requires a cap tier of TIER_3 or TIER_4")
        if st in DURATION_TYPES:
            dur = sel.get("duration_days")
            if isinstance(dur, int) and not isinstance(dur, bool):
                lo, hi = TIER_MATRIX[final_tier][st]
                if not (lo <= dur <= hi):
                    raise_error(ERR_SANCTION_OUTSIDE_MATRIX,
                                f"duration_days {dur} outside {final_tier} bounds for {st}")


def _check_modified_selections_items(selections):
    """Tier 9 for SANCTION_MODIFIED: restitution item presence and positivity."""
    for sel in selections:
        if isinstance(sel, dict) and sel.get("sanction_type") == "RESTITUTION":
            items = sel.get("restitution_items")
            if not isinstance(items, list) or len(items) == 0:
                raise_error(ERR_RESTITUTION_ITEMS_REQUIRED,
                            "RESTITUTION requires a non-empty restitution_items array")
            for it in items:
                if not isinstance(it, dict) or not isinstance(it.get("description"), str) \
                        or it.get("description", "").strip() == "" \
                        or not _valid_num(it.get("amount_dollars")) \
                        or it.get("amount_dollars") <= 0:
                    raise_error(ERR_RESTITUTION_ITEMS_REQUIRED,
                                "every restitution item needs a description and amount_dollars > 0")


def _validate_selection_schema(selections):
    for sel in selections:
        if not isinstance(sel, dict):
            raise_error(ERR_INVALID_REQUEST, "each sanction selection must be an object")
        st = req_enum(sel, "sanction_type", SANCTION_TYPES)
        if st in DURATION_TYPES:
            dur = sel.get("duration_days")
            if not isinstance(dur, int) or isinstance(dur, bool) or dur <= 0:
                raise_error(ERR_INVALID_REQUEST,
                            f"duration_days is required and must be a positive integer for {st}")
        elif sel.get("duration_days") is not None:
            raise_error(ERR_INVALID_REQUEST, f"duration_days is forbidden for {st}")
        if st != "RESTITUTION" and sel.get("restitution_items") is not None:
            raise_error(ERR_INVALID_REQUEST, f"restitution_items is forbidden for {st}")


@bp.post("/appeals/<aid>/decide")
def decide_appeal(aid):
    caller = authorized(["AppealOfficer"])
    appeal = require_path("appeals", aid)
    case = get_case(appeal["case_id"])
    body = get_body()
    if appeal["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"appeal is {appeal['status']}, not UNDER_REVIEW")
    outcome = as_enum(body, "outcome", APPEAL_OUTCOMES)
    target = appeal["appeal_target"]
    det = _issued_determination(case["id"]) if target == "DETERMINATION" else None

    # Tier 7: SANCTION_MODIFIED matrix conformance (before tier-8 identity per
    # the validation table's priority order).
    modified = as_list(body, "modified_sanction_selections")
    if outcome == "SANCTION_MODIFIED" and target == "DETERMINATION" and det is not None \
            and modified is not None:
        _check_modified_selections_matrix(det, modified)

    # Tier 8: outcome/target compatibility.
    if outcome is not None:
        if outcome == "REINSTATED" and target != "DISMISSAL":
            raise_error(ERR_APPEAL_OUTCOME_INCOMPATIBLE,
                        "REINSTATED is only available for DISMISSAL appeals")
        if outcome in ("REVERSED", "REMANDED", "SANCTION_MODIFIED") and target != "DETERMINATION":
            raise_error(ERR_APPEAL_OUTCOME_INCOMPATIBLE,
                        f"{outcome} is only available for DETERMINATION appeals")
    # Tier 8: remand scope present and ground-compatible.
    remand_scope = None
    if outcome == "REMANDED":
        remand_scope = as_enum(body, "remand_scope", REMAND_SCOPES)
        grounds = appeal["grounds"]
        if remand_scope is None:
            raise_error(ERR_REMAND_SCOPE_MISMATCH,
                        "remand_scope is required for a REMANDED outcome")
        if "NEW_EVIDENCE" in grounds:
            if remand_scope != "INVESTIGATION":
                raise_error(ERR_REMAND_SCOPE_MISMATCH,
                            "NEW_EVIDENCE grounds require remand_scope INVESTIGATION")
        elif set(grounds) <= {"PROCEDURAL_IRREGULARITY", "CONFLICT_OF_INTEREST"}:
            if remand_scope != "HEARING_PREPARATION":
                raise_error(ERR_REMAND_SCOPE_MISMATCH,
                            "procedural/conflict-only grounds require remand_scope HEARING_PREPARATION")
    # Tier 8: only the assigned officer decides.
    if caller.user_id != appeal["appeal_officer_id"]:
        raise_error(ERR_NOT_ASSIGNED_APPEAL_OFFICER,
                    "only the appeal officer assigned at begin-review may decide")
    # Tier 9: restitution items on modified selections (fiscal follows
    # referential checks in the validation table order).
    if outcome == "SANCTION_MODIFIED" and target == "DETERMINATION" and det is not None:
        if modified is None:
            raise_error(ERR_SANCTION_OUTSIDE_MATRIX,
                        "modified_sanction_selections must be non-empty")
        _check_modified_selections_items(modified)

    # Tier 11: schema.
    outcome = req_enum(body, "outcome", APPEAL_OUTCOMES)
    if "remand_scope" in body and body.get("remand_scope") is not None:
        req_enum(body, "remand_scope", REMAND_SCOPES)
    if outcome == "SANCTION_MODIFIED":
        if not isinstance(body.get("modified_sanction_selections"), list):
            raise_error(ERR_INVALID_REQUEST,
                        "missing or invalid field: modified_sanction_selections")
        _validate_selection_schema(body["modified_sanction_selections"])

    # ---- Commit the decision and its cascades ----
    now_iso = clock_iso()
    appeal["status"] = outcome
    appeal["decided_at"] = now_iso
    if outcome == "REMANDED":
        appeal["remand_scope"] = remand_scope
    touch(appeal)

    if outcome == "AFFIRMED":
        if target == "DETERMINATION" and det is not None:
            det["status"] = "FINAL"
            touch(det)
            append_event(case["id"], "DETERMINATION_FINALIZED", caller,
                         {"determination_id": det["id"]})
        if case["status"] == "APPEAL_REVIEW":
            case["status"] = "CLOSED"
            case["closed_at"] = now_iso
            append_event(case["id"], "APPEAL_DECIDED", caller,
                         {"appeal_id": aid, "outcome": outcome})
            append_event(case["id"], "CASE_CLOSED", caller, {"status": "CLOSED"})
        else:
            # Dismissal affirmed: the case remains DISMISSED.
            append_event(case["id"], "APPEAL_DECIDED", caller,
                         {"appeal_id": aid, "outcome": outcome})
    elif outcome == "REVERSED":
        if det is not None:
            det["status"] = "REVERSED"
            touch(det)
            for s in db["sanctions"].values():
                if s["determination_id"] == det["id"] and s["status"] == "ACTIVE":
                    s["status"] = "LIFTED_ON_APPEAL"
                    touch(s)
        case["status"] = "CLOSED"
        case["closed_at"] = now_iso
        append_event(case["id"], "APPEAL_DECIDED", caller,
                     {"appeal_id": aid, "outcome": outcome})
        append_event(case["id"], "CASE_CLOSED", caller, {"status": "CLOSED"})
    elif outcome == "REMANDED":
        if det is not None:
            det["status"] = "SUPERSEDED"
            touch(det)
            for s in db["sanctions"].values():
                if s["determination_id"] == det["id"] and s["status"] == "ACTIVE":
                    s["status"] = "STAYED"
                    touch(s)
        case["status"] = "REMANDED"
        case["remand_target"] = remand_scope
        append_event(case["id"], "APPEAL_DECIDED", caller,
                     {"appeal_id": aid, "outcome": outcome, "remand_scope": remand_scope})
    elif outcome == "SANCTION_MODIFIED":
        cap_tier = tier_of(det["final_severity_score"])
        for s in db["sanctions"].values():
            if s["determination_id"] == det["id"] and s["status"] == "ACTIVE":
                s["status"] = "LIFTED_ON_APPEAL"
                touch(s)
        for sel in body["modified_sanction_selections"]:
            st = sel["sanction_type"]
            applied = 0
            if st == "RESTITUTION":
                applied = restitution_applied_cents(sel["restitution_items"], cap_tier)
            new_record("sanctions", {
                "determination_id": det["id"],
                "sanction_type": st,
                "duration_days": sel.get("duration_days") if st in DURATION_TYPES else None,
                "restitution_items": sel.get("restitution_items") if st == "RESTITUTION" else None,
                "applied_restitution_cents": applied,
                "effective_from": det["issued_at"],
                "status": "ACTIVE",
            })
        det["status"] = "FINAL"
        touch(det)
        append_event(case["id"], "DETERMINATION_FINALIZED", caller,
                     {"determination_id": det["id"]})
        case["status"] = "CLOSED"
        case["closed_at"] = now_iso
        append_event(case["id"], "APPEAL_DECIDED", caller,
                     {"appeal_id": aid, "outcome": outcome})
        append_event(case["id"], "CASE_CLOSED", caller, {"status": "CLOSED"})
    elif outcome == "REINSTATED":
        case["status"] = "AWAITING_FORMAL_COMPLAINT"
        case["dismissal_reason"] = None
        case["closed_at"] = None
        append_event(case["id"], "APPEAL_DECIDED", caller,
                     {"appeal_id": aid, "outcome": outcome})
        append_event(case["id"], "CASE_RESUMED", caller,
                     {"status": "AWAITING_FORMAL_COMPLAINT"})

    bump_case(case)
    auto_notice(case["id"], "APPEAL_OUTCOME", "BOTH",
                f"The appeal has been decided: {outcome}.")
    append_event(case["id"], "NOTICE_SENT", caller,
                 {"notice_type": "APPEAL_OUTCOME", "recipient_side": "BOTH"})
    return success_object(public(appeal))
