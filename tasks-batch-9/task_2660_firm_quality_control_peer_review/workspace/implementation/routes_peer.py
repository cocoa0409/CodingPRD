"""The external peer review cycle: roster, scheduling, scope, selections, rating,
issuance and the corrective-action fork (PRD 3.9)."""

from flask import Blueprint

import auth
import calc
import clock
import response as envelope
import shapes
import store
import vocab
from errors import ApiError

bp = Blueprint("peer", __name__)

A = auth.SYSTEM_ADMIN
FMP = auth.FIRM_MANAGING_PARTNER
QCD = auth.QUALITY_CONTROL_DIRECTOR
PR = auth.PEER_REVIEWER
PRC = auth.PEER_REVIEW_COMMITTEE


# --------------------------------------------------------------------------- #
# The roster
# --------------------------------------------------------------------------- #

def _reviewer_inputs(body):
    out = {}
    if shapes.has(body, "accepts_out_of_state"):
        out["accepts_out_of_state"] = shapes.as_bool(body, "accepts_out_of_state")
    if shapes.has(body, "qualified_categories"):
        out["qualified_categories"] = shapes.as_enum_list(
            body, "qualified_categories", vocab.MUST_SELECT_CATEGORY)
    if shapes.has(body, "independence_conflict_firm_names"):
        out["independence_conflict_firm_names"] = shapes.as_str_list(
            body, "independence_conflict_firm_names", 200)
    if shapes.has(body, "max_concurrent_reviews"):
        out["max_concurrent_reviews"] = shapes.as_int(body, "max_concurrent_reviews", 1, 10)
    if shapes.has(body, "experience_hours"):
        out["experience_hours"] = shapes.as_int(body, "experience_hours", 0)
    if shapes.has(body, "status"):
        out["status"] = shapes.as_enum(body, "status", vocab.REVIEWER_STATUS)
    return out


@bp.post("/peer-reviewers")
def create_reviewer():
    auth.authenticate((A, PRC))
    body = shapes.body()
    shapes.require_present(body, ["reviewer_firm_name", "license_state"])
    name = shapes.as_str(body, "reviewer_firm_name", 1, 200)
    license_state = shapes.as_state_code(body, "license_state")
    extras = _reviewer_inputs(body)
    for existing in store.rows(store.PEER_REVIEWERS):
        if existing["reviewer_firm_name"] == name:
            raise ApiError("ERR_VALIDATION_FAILED", "reviewer_firm_name must be unique.")
    fields = {
        "reviewer_firm_name": name,
        "license_state": license_state,
        "accepts_out_of_state": False,
        "qualified_categories": [],
        "independence_conflict_firm_names": [],
        "max_concurrent_reviews": 2,
        "experience_hours": 0,
        "status": "ACTIVE",
        "active_review_count": 0,
        "committed_hours_balance": 0,
    }
    fields.update(extras)
    reviewer = store.insert(store.PEER_REVIEWERS, fields)
    return envelope.object_response(
        store.serialize(store.PEER_REVIEWERS, reviewer), 201)


@bp.patch("/peer-reviewers/<reviewer_id>")
def patch_reviewer(reviewer_id):
    auth.authenticate((A, PRC))
    reviewer = shapes.need_reviewer(reviewer_id)
    body = shapes.body()
    updates = _reviewer_inputs(body)
    # A revision never retroactively unassigns a review already in flight.
    reviewer.update(updates)
    store.mutate(reviewer, {}, force=True)
    return envelope.object_response(store.serialize(store.PEER_REVIEWERS, reviewer))


# --------------------------------------------------------------------------- #
# Scheduling
# --------------------------------------------------------------------------- #

@bp.post("/firms/<firm_id>/peer-reviews")
def create_peer_review(firm_id):
    auth.authenticate((A, PRC))
    firm = shapes.need_firm(firm_id)
    body = shapes.body()
    shapes.require_present(body, ["review_type", "year_end", "scheduled_window_start",
                                 "scheduled_window_end"])
    year_end = shapes.as_date(body, "year_end")
    start = shapes.as_date(body, "scheduled_window_start")
    end = shapes.as_date(body, "scheduled_window_end")
    review_type = shapes.as_enum(body, "review_type", vocab.REVIEW_TYPE)
    if end <= start:
        raise ApiError("ERR_VALIDATION_FAILED",
                       "scheduled_window_end must be after scheduled_window_start.")
    review = store.insert(store.PEER_REVIEWS, {
        "firm_id": firm["id"],
        "prior_peer_review_id": None,
        "assigned_reviewer_id": None,
        "review_type": review_type,
        "year_end": year_end.isoformat(),
        "scheduled_window_start": start.isoformat(),
        "scheduled_window_end": end.isoformat(),
        "must_select_categories": [],
        "total_scope_hours": None,
        "unallocated_hours": None,
        "rating": "NONE",
        "is_follow_up": False,
        "scope_limitation_count": 0,
        "report_issued_at": None,
        "state": "SCHEDULED",
    })
    return envelope.object_response(store.serialize(store.PEER_REVIEWS, review), 201)


# --------------------------------------------------------------------------- #
# Choosing a reviewer
# --------------------------------------------------------------------------- #

@bp.post("/peer-reviews/<peer_review_id>/reviewer-assignment")
def assign_reviewer(peer_review_id):
    auth.authenticate((A, PRC))
    review = shapes.need_peer_review(peer_review_id)
    firm = store.get(store.FIRMS, review["firm_id"])
    body = shapes.body()
    named = None
    if shapes.has(body, "reviewer_id"):
        named = shapes.need_reviewer(body.get("reviewer_id"))
    if review["state"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_TRANSITION")

    calc.refresh_all_reviewers()
    targets = calc.firm_must_select_categories(firm, review["year_end"])
    if named is not None:
        calc.check_named_reviewer(firm, review, named, targets)
        winner = named
    else:
        pool = calc.reviewer_pool(firm, review, targets)
        if not pool:
            store.mutate(firm, {"unassigned_review_flag": True})
            raise ApiError("ERR_NO_ELIGIBLE_REVIEWER")
        winner = pool[0]

    store.mutate(review, {"assigned_reviewer_id": winner["id"], "state": "PLANNING"},
                 force=True)
    calc.refresh_reviewer(winner)
    store.mutate(firm, {"unassigned_review_flag": False})
    return envelope.object_response(store.serialize(store.PEER_REVIEWS, review))


# --------------------------------------------------------------------------- #
# Determining scope
# --------------------------------------------------------------------------- #

@bp.post("/peer-reviews/<peer_review_id>/scope")
def determine_scope(peer_review_id):
    actor = auth.authenticate((A, PR, PRC))
    review = shapes.need_peer_review(peer_review_id)
    firm = store.get(store.FIRMS, review["firm_id"])
    auth.require_owner(actor, review["assigned_reviewer_id"], roles=(PR,))
    if review["state"] != "PLANNING":
        raise ApiError("ERR_INVALID_TRANSITION")

    categories = calc.firm_must_select_categories(firm, review["year_end"])
    reviewer = store.get(store.PEER_REVIEWERS, review["assigned_reviewer_id"])
    if reviewer is None or not set(categories).issubset(
            set(reviewer["qualified_categories"])):
        raise ApiError("ERR_MUST_SELECT_CATEGORY_NOT_QUALIFIED")
    total = calc.peer_review_hours_scope(firm, categories)
    store.mutate(review, {
        "must_select_categories": categories,
        "total_scope_hours": total,
        "unallocated_hours": total,
        "state": "SCOPE_SET",
    }, force=True)
    return envelope.object_response(store.serialize(store.PEER_REVIEWS, review))


# --------------------------------------------------------------------------- #
# Selecting engagements and committing hours
# --------------------------------------------------------------------------- #

@bp.post("/peer-reviews/<peer_review_id>/selections")
def commit_selection(peer_review_id):
    actor = auth.authenticate((A, PR))
    review = shapes.need_peer_review(peer_review_id)
    body = shapes.body()
    engagement = None
    if shapes.has(body, "engagement_id"):
        engagement = shapes.need_engagement(body.get("engagement_id"))
    shapes.require_present(body, ["engagement_id", "hours_committed",
                                 "expected_peer_review_version"])
    hours = shapes.as_int(body, "hours_committed", 1, 200)
    limitation = shapes.as_bool(body, "is_scope_limitation") \
        if shapes.has(body, "is_scope_limitation") else False
    auth.require_owner(actor, review["assigned_reviewer_id"], roles=(PR,))
    shapes.check_version(body, "expected_peer_review_version", review)
    if review["state"] not in ("SCOPE_SET", "FIELDWORK"):
        raise ApiError("ERR_PEER_REVIEW_ALREADY_RATED")
    if engagement["firm_id"] != review["firm_id"]:
        raise ApiError("ERR_ENGAGEMENT_FIRM_MISMATCH")
    if engagement["period_end"] > review["year_end"]:
        raise ApiError("ERR_ENGAGEMENT_OUTSIDE_REVIEW_SCOPE")
    for existing in calc.committed_selections(review["id"]):
        if existing["engagement_id"] == engagement["id"]:
            raise ApiError("ERR_DUPLICATE_SELECTION")
    if hours > (review["unallocated_hours"] or 0):
        raise ApiError("ERR_SCOPE_HOURS_EXCEEDED")

    selection = store.insert(store.PR_SELECTIONS, {
        "peer_review_id": review["id"],
        "engagement_id": engagement["id"],
        "must_select_category": calc.engagement_must_select_category(engagement),
        "hours_committed": hours,
        "is_scope_limitation": limitation,
        "disposition": "NONE",
        "non_conforming": False,
        "status": "COMMITTED",
    })
    _rebalance(review)
    return envelope.object_response(store.serialize(store.PR_SELECTIONS, selection), 201)


def _rebalance(review):
    """total_scope_hours == unallocated_hours + sum(hours_committed) at every instant."""
    committed = calc.committed_hours(review["id"])
    total = review["total_scope_hours"] or 0
    limitations = len([s for s in calc.committed_selections(review["id"])
                       if s["is_scope_limitation"]])
    store.mutate(review, {
        "unallocated_hours": total - committed,
        "scope_limitation_count": limitations,
    }, force=True)
    reviewer = store.get(store.PEER_REVIEWERS, review["assigned_reviewer_id"])
    if reviewer is not None:
        calc.refresh_reviewer(reviewer)


@bp.delete("/peer-reviews/<peer_review_id>/selections/<selection_id>")
def withdraw_selection(peer_review_id, selection_id):
    actor = auth.authenticate((A, PR))
    review = shapes.need_peer_review(peer_review_id)
    selection = shapes.need_pr_selection(selection_id)
    if selection["peer_review_id"] != review["id"]:
        raise ApiError("ERR_PEER_REVIEW_SELECTION_NOT_FOUND")
    auth.require_owner(actor, review["assigned_reviewer_id"], roles=(PR,))
    if selection["status"] != "COMMITTED":
        raise ApiError("ERR_INVALID_TRANSITION")
    if review["state"] not in ("SCOPE_SET", "FIELDWORK"):
        raise ApiError("ERR_PEER_REVIEW_ALREADY_RATED")
    # The row is retained, never deleted.
    store.mutate(selection, {"status": "WITHDRAWN"}, force=True)
    _rebalance(review)
    return envelope.object_response({}, 204)


@bp.post("/peer-review-selections/<selection_id>/disposition")
def record_disposition(selection_id):
    actor = auth.authenticate((A, PR))
    selection = shapes.need_pr_selection(selection_id)
    review = store.get(store.PEER_REVIEWS, selection["peer_review_id"])
    body = shapes.body()
    shapes.require_present(body, ["disposition", "non_conforming"])
    non_conforming = shapes.as_bool(body, "non_conforming")
    disposition = shapes.as_enum(body, "disposition", vocab.DISPOSITION_INPUT)
    if review is not None:
        auth.require_owner(actor, review["assigned_reviewer_id"], roles=(PR,))
    if selection["status"] != "COMMITTED" or review is None or \
            review["state"] == "SCOPE_SET":
        raise ApiError("ERR_INVALID_TRANSITION")
    if review["state"] != "FIELDWORK":
        raise ApiError("ERR_PEER_REVIEW_ALREADY_RATED")
    store.mutate(selection, {"disposition": disposition,
                             "non_conforming": non_conforming}, force=True)
    return envelope.object_response(store.serialize(store.PR_SELECTIONS, selection))


# --------------------------------------------------------------------------- #
# The review lifecycle, issuance and the fork
# --------------------------------------------------------------------------- #

PEER_REVIEW_NEXT = {
    "SCHEDULED": (),
    "PLANNING": (),
    "SCOPE_SET": ("FIELDWORK",),
    "FIELDWORK": ("RATING_DRAFTED",),
    "RATING_DRAFTED": ("REPORT_ISSUED",),
    "REPORT_ISSUED": ("ACCEPTED",),
    # PRD 3.9: "attempting that direct acceptance on a review whose rating is not PASS
    # is refused with ERR_CORRECTIVE_ACTION_OUTSTANDING".  A non-PASS review never rests
    # in REPORT_ISSUED (issuance forks it in the same request), so the acceptance attempt
    # this sentence describes is the one made here, and it must reach the outstanding
    # corrective-action check rather than be turned away as an unreachable state.
    "CORRECTIVE_ACTION_REQUIRED": ("ACCEPTED",),
    "REMEDIATION_SUBMITTED": ("ACCEPTED",),
    "ACCEPTED": (),
    "FOLLOW_UP_REQUIRED": (),
}

FORK_ACTION = {
    "PASS_WITH_DEFICIENCY": ("MONITORING_VISIT", 90),
    "FAIL": ("PREISSUANCE_REVIEW", 45),
}


def _close_out(review):
    """Shared closing leg: the firm records the rating, the reviewer rotates on and the
    posture ladder re-runs."""
    firm = store.get(store.FIRMS, review["firm_id"])
    reviewer_id = review["assigned_reviewer_id"]
    if firm is not None:
        if reviewer_id is not None:
            prior = [reviewer_id] + [
                row for row in firm["prior_reviewer_ids"] if row != reviewer_id]
            store.mutate(firm, {"prior_reviewer_ids": prior[:3]})
        calc.recompute_posture(firm)
    reviewer = store.get(store.PEER_REVIEWERS, reviewer_id)
    if reviewer is not None:
        calc.refresh_reviewer(reviewer)


@bp.post("/peer-reviews/<peer_review_id>/transitions")
def peer_review_transition(peer_review_id):
    actor = auth.authenticate((A, PRC, PR))
    review = shapes.need_peer_review(peer_review_id)
    firm = store.get(store.FIRMS, review["firm_id"])
    body = shapes.body()
    shapes.require_present(body, ["to_state"])
    to_state = shapes.as_enum(body, "to_state", vocab.PEER_REVIEW_STATE)
    auth.require_owner(actor, review["assigned_reviewer_id"], roles=(PR,))
    if to_state not in PEER_REVIEW_NEXT[review["state"]]:
        raise ApiError("ERR_INVALID_TRANSITION")

    if to_state == "FIELDWORK":
        cycles = [row for row in store.rows(store.INSPECTIONS)
                  if row["firm_id"] == review["firm_id"]]
        latest = None
        if cycles:
            cycles.sort(key=lambda r: (r["inspection_year"], store.order_key(r)))
            latest = cycles[-1]
        if latest is None or latest["state"] != "CONCLUDED":
            raise ApiError("ERR_INSPECTION_NOT_CONCLUDED")
        covered = {s["must_select_category"]
                   for s in calc.committed_selections(review["id"])}
        for category in review["must_select_categories"]:
            if category not in covered:
                raise ApiError("ERR_MUST_SELECT_CATEGORY_NOT_COVERED")
        store.mutate(review, {"state": "FIELDWORK"}, force=True)

    elif to_state == "RATING_DRAFTED":
        if review["rating"] != "NONE":
            raise ApiError("ERR_PEER_REVIEW_ALREADY_RATED")
        for selection in calc.committed_selections(review["id"]):
            if selection["disposition"] == "NONE":
                raise ApiError("ERR_SELECTION_DISPOSITION_MISSING")
        rating, limitations = calc.peer_review_rating(review)
        store.mutate(review, {"rating": rating, "scope_limitation_count": limitations,
                              "state": "RATING_DRAFTED"}, force=True)

    elif to_state == "REPORT_ISSUED":
        if review["rating"] == "NONE":
            raise ApiError("ERR_INVALID_TRANSITION")
        issued_at = clock.now_iso()
        forked = FORK_ACTION.get(review["rating"])
        store.mutate(review, {
            "report_issued_at": issued_at,
            "state": "REPORT_ISSUED" if forked is None
                     else "CORRECTIVE_ACTION_REQUIRED",
        }, force=True)
        if forked is not None:
            action_code, offset = forked
            due = clock.add_days(clock.today(), offset)
            store.insert(store.CAPS, {
                "peer_review_id": review["id"],
                "action_code": action_code,
                "due_date": due.isoformat(),
                "evidence_summary": None,
                "evidence_submitted_at": None,
                "rejection_count": 0,
                "status": "REQUIRED",
            })

    elif review["state"] == "REPORT_ISSUED":
        if review["rating"] != "PASS":
            raise ApiError("ERR_CORRECTIVE_ACTION_OUTSTANDING")
        store.mutate(review, {"state": "ACCEPTED"}, force=True)
        _close_out(review)

    else:
        plans = calc.children(store.CAPS, "peer_review_id", review["id"])
        for plan in plans:
            if plan["status"] != "ACCEPTED":
                raise ApiError("ERR_CORRECTIVE_ACTION_OUTSTANDING")
        store.mutate(review, {"state": "ACCEPTED"}, force=True)
        _close_out(review)
    return envelope.object_response(store.serialize(store.PEER_REVIEWS, review))


# --------------------------------------------------------------------------- #
# Corrective action and the follow-up cascade
# --------------------------------------------------------------------------- #

@bp.post("/corrective-action-plans/<cap_id>/evidence")
def submit_evidence(cap_id):
    actor = auth.authenticate((A, FMP, QCD))
    plan = shapes.need_cap(cap_id)
    review = store.get(store.PEER_REVIEWS, plan["peer_review_id"])
    body = shapes.body()
    shapes.require_present(body, ["evidence_summary"])
    summary = shapes.as_str(body, "evidence_summary", 1, 1000)
    if review is not None:
        auth.require_same_firm(actor, review["firm_id"])
    if plan["status"] not in ("REQUIRED", "REJECTED"):
        raise ApiError("ERR_INVALID_TRANSITION")
    due = clock.parse_date(plan["due_date"])
    if clock.today() > due:
        raise ApiError("ERR_CORRECTIVE_ACTION_PAST_DUE")
    store.mutate(plan, {
        "evidence_summary": summary,
        "evidence_submitted_at": clock.now_iso(),
        "status": "EVIDENCE_SUBMITTED",
    }, force=True)

    if review is not None and review["state"] == "CORRECTIVE_ACTION_REQUIRED":
        siblings = calc.children(store.CAPS, "peer_review_id", review["id"])
        if all(row["evidence_submitted_at"] is not None for row in siblings):
            store.mutate(review, {"state": "REMEDIATION_SUBMITTED"}, force=True)
    return envelope.object_response(store.serialize(store.CAPS, plan))


@bp.post("/corrective-action-plans/<cap_id>/disposition")
def dispose_cap(cap_id):
    auth.authenticate((A, PRC))
    plan = shapes.need_cap(cap_id)
    review = store.get(store.PEER_REVIEWS, plan["peer_review_id"])
    body = shapes.body()
    shapes.require_present(body, ["outcome"])
    outcome = shapes.as_enum(body, "outcome", vocab.CAP_OUTCOME)
    if plan["status"] != "EVIDENCE_SUBMITTED":
        raise ApiError("ERR_INVALID_TRANSITION")

    if outcome == "ACCEPTED":
        # The review waits in REMEDIATION_SUBMITTED until the committee transitions it.
        store.mutate(plan, {"status": "ACCEPTED"}, force=True)
        return envelope.object_response(store.serialize(store.CAPS, plan))

    # ---- link 1 -----------------------------------------------------------
    store.mutate(plan, {"status": "REJECTED",
                        "rejection_count": plan["rejection_count"] + 1}, force=True)
    if review is None or review["state"] != "REMEDIATION_SUBMITTED":
        return envelope.object_response(store.serialize(store.CAPS, plan))

    # ---- link 2 -----------------------------------------------------------
    store.mutate(review, {"state": "FOLLOW_UP_REQUIRED"}, force=True)

    # ---- link 3: the follow-up review the cascade synthesises -------------
    old_end = clock.parse_date(review["scheduled_window_end"])
    new_start = clock.add_days(old_end, 180)
    new_end = clock.add_days(new_start, 14)
    store.insert(store.PEER_REVIEWS, {
        "firm_id": review["firm_id"],
        "prior_peer_review_id": review["id"],
        "assigned_reviewer_id": None,
        "review_type": "SYSTEM_REVIEW",
        "year_end": review["year_end"],
        "scheduled_window_start": new_start.isoformat(),
        "scheduled_window_end": new_end.isoformat(),
        "must_select_categories": [],
        "total_scope_hours": None,
        "unallocated_hours": None,
        "rating": "NONE",
        "is_follow_up": True,
        "scope_limitation_count": 0,
        "report_issued_at": None,
        "state": "SCHEDULED",
    })

    # ---- links 4 and 5: the firm records the rating and the posture re-runs
    _close_out(review)
    return envelope.object_response(store.serialize(store.CAPS, plan))


# --------------------------------------------------------------------------- #
# The logical clock
# --------------------------------------------------------------------------- #

@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.authenticate((A,))
    body = shapes.body()
    shapes.require_present(body, ["current_utc"])
    moment = shapes.as_instant(body, "current_utc")
    clock.set_now(moment)
    # No entity is mutated and no version is incremented.
    return envelope.object_response({"current_utc": clock.now_iso()})
