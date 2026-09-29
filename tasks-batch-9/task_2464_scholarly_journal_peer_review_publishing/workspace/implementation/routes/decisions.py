"""Editorial decisions, their category cascades, and appeal adjudication."""

from flask import Blueprint

import calc
import serializers as ser
import services as svc
import validate as v
from auth import authorise, require_editor_journal
from db import add_days, now, now_iso, ordered, parse_ts, stamp_new, store, touch
from errors import ApiError
from response import list_response, object_response
from routes.manuscripts import find_manuscript

bp = Blueprint("decisions", __name__)

CATEGORIES = ("ACCEPT", "MINOR_REVISION", "MAJOR_REVISION", "REJECT", "REJECT_AND_RESUBMIT")
OUTCOMES = ("UPHELD", "OVERTURNED")
APPEAL_WINDOW_DAYS = 30
EDITORIAL_ROLES = ("SystemAdmin", "EditorInChief", "HandlingEditor")


@bp.post("/manuscripts/<mid>/decisions")
def create_decision(mid):
    actor = authorise("HandlingEditor")
    manuscript = find_manuscript(mid)
    require_editor_journal(actor, manuscript)
    data = v.body()
    note = v.req_string(data, "editorial_note")
    category = v.opt_enum(data, "category", CATEGORIES)

    svc.guard_manuscript_terminal(manuscript)
    if manuscript["status"] != "DECISION_PENDING":
        raise ApiError("ERR_INVALID_MANUSCRIPT_STATE")

    journal = calc.journal_of(manuscript)
    if calc.has_high_ethics_hold(mid):
        raise ApiError("ERR_ETHICS_HOLD")

    counted = calc.submitted_review_count(manuscript)
    if counted < int(journal["min_completed_reviews_for_decision"]):
        raise ApiError("ERR_INSUFFICIENT_REVIEWS")

    mode = journal["consensus_mode"]
    index, reviews_counted = calc.consensus_index(manuscript, mode)
    auto_category = calc.auto_category_for(index) if index is not None else None
    resolved = category if category is not None else auto_category
    category_source = "EXPLICIT" if category is not None else "AUTO"

    if resolved in ("MINOR_REVISION", "MAJOR_REVISION"):
        if int(manuscript["revision_round"]) >= int(journal["max_revision_rounds"]):
            raise ApiError("ERR_REVISION_LIMIT_REACHED")
    elif resolved == "ACCEPT":
        if journal["requires_data_availability_statement"]:
            statement = manuscript.get("data_availability_statement")
            if not isinstance(statement, str) or statement.strip() == "":
                raise ApiError("ERR_DATA_AVAILABILITY_REQUIRED")

    row = {
        "manuscript_id": mid,
        "decided_by_editor_id": actor.user_id,
        "round": manuscript["revision_round"],
        "category": resolved,
        "category_source": category_source,
        "consensus_mode": mode,
        "consensus_index": index,
        "auto_category": auto_category,
        "reviews_counted": reviews_counted,
        "editorial_note": note,
    }
    stamp_new(row, versioned=False)
    store.decisions[row["id"]] = row

    manuscript["consensus_index_at_last_decision"] = index
    manuscript["decision_count"] = int(manuscript["decision_count"]) + 1

    if resolved in ("MINOR_REVISION", "MAJOR_REVISION"):
        manuscript["status"] = "REVISION_REQUESTED"
        touch(manuscript)
        svc.withdraw_open_invitations(manuscript, "DECISION_CASCADE")
    elif resolved == "ACCEPT":
        manuscript["status"] = "IN_PRODUCTION"
        touch(manuscript)
        svc.create_production_job(manuscript)
        svc.withdraw_open_invitations(manuscript, "DECISION_CASCADE")
        svc.release_active_assignment(manuscript)
    else:
        manuscript["status"] = "REJECTED"
        touch(manuscript)
        svc.withdraw_open_invitations(manuscript, "DECISION_CASCADE")
        svc.release_active_assignment(manuscript)
    return object_response(ser.decision_out(row), 201)


@bp.get("/decisions/<did>")
def get_decision(did):
    authorise("SystemAdmin", "EditorInChief", "HandlingEditor", "Author")
    decision = store.decisions.get(did)
    if decision is None:
        raise ApiError("ERR_DECISION_NOT_FOUND")
    return object_response(ser.decision_out(decision), 200)


@bp.get("/decisions")
def list_decisions():
    authorise("SystemAdmin", "EditorInChief", "HandlingEditor", "Author")
    limit, offset = v.pagination()
    manuscript_id = v.query_str("manuscript_id")
    editor_id = v.query_str("decided_by_editor_id")
    round_no = v.query_int("round")
    rows = []
    for row in store.decisions.values():
        if manuscript_id is not None and row["manuscript_id"] != manuscript_id:
            continue
        if editor_id is not None and row["decided_by_editor_id"] != editor_id:
            continue
        if round_no is not None and row["round"] != round_no:
            continue
        rows.append(row)
    rows = ordered(rows)
    page = v.window(rows, limit, offset)
    return list_response(ser.many(page, ser.decision_out), limit, offset, len(rows))


# ==========================================================================
# appeals
# ==========================================================================
@bp.post("/appeals")
def create_appeal():
    actor = authorise("Author")
    data = v.body()
    decision_id = v.req_id(data, "decision_id")
    decision = store.decisions.get(decision_id)
    if decision is None:
        raise ApiError("ERR_DECISION_NOT_FOUND")
    grounds = v.req_string(data, "grounds")

    manuscript = store.manuscripts.get(decision["manuscript_id"])
    if manuscript is None:
        raise ApiError("ERR_MANUSCRIPT_NOT_FOUND")
    if manuscript["corresponding_author_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    svc.guard_manuscript_terminal(manuscript)
    if manuscript["status"] != "REJECTED":
        raise ApiError("ERR_INVALID_MANUSCRIPT_STATE")

    history = calc.decisions_of_manuscript(manuscript["id"])
    latest = history[-1] if history else None
    if latest is None or latest["id"] != decision_id:
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED", "Only the most recent decision may be appealed.")
    if decision["category"] not in ("REJECT", "REJECT_AND_RESUBMIT"):
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED", "This decision is not a rejection.")
    decided_at = parse_ts(decision["created_at"])
    if decided_at is not None and now() > add_days(decided_at, APPEAL_WINDOW_DAYS):
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED", "The 30-day appeal window has closed.")
    for existing in store.appeals.values():
        if existing["decision_id"] == decision_id:
            raise ApiError(
                "ERR_APPEAL_WINDOW_CLOSED", "This decision has already been appealed."
            )

    row = {
        "decision_id": decision_id,
        "manuscript_id": manuscript["id"],
        "adjudicated_by_editor_id": None,
        "state": "FILED",
        "grounds": grounds,
        "rationale": None,
        "adjudicated_at": None,
    }
    stamp_new(row)
    store.appeals[row["id"]] = row

    manuscript["status"] = "UNDER_APPEAL"
    touch(manuscript)
    return object_response(ser.appeal_out(row), 201)


@bp.post("/appeals/<aid>/adjudication")
def adjudicate_appeal(aid):
    actor = authorise("EditorInChief")
    appeal = store.appeals.get(aid)
    if appeal is None:
        raise ApiError("ERR_APPEAL_NOT_FOUND")
    manuscript = store.manuscripts.get(appeal["manuscript_id"])
    decision = store.decisions.get(appeal["decision_id"])
    require_editor_journal(actor, manuscript)
    data = v.body()
    outcome = v.req_enum(data, "outcome", OUTCOMES)
    rationale = v.opt_string(data, "rationale")

    if decision is not None and decision["decided_by_editor_id"] == actor.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    svc.guard_appeal_terminal(appeal)
    if appeal["state"] != "FILED":
        raise ApiError("ERR_INVALID_APPEAL_STATE")

    appeal["state"] = outcome
    appeal["adjudicated_by_editor_id"] = actor.user_id
    appeal["adjudicated_at"] = now_iso()
    appeal["rationale"] = rationale
    touch(appeal)

    if manuscript is not None:
        if outcome == "UPHELD":
            manuscript["status"] = "REJECTED"
            touch(manuscript)
        else:
            manuscript["status"] = "UNDER_REVIEW"
            touch(manuscript)
            svc.recompute_shortfall(manuscript)
            excluded = ()
            if decision is not None:
                excluded = (decision["decided_by_editor_id"],)
            svc.run_replacement_selection(manuscript, None, excluded)
    return object_response(ser.appeal_out(appeal), 200)


@bp.get("/appeals/<aid>")
def get_appeal(aid):
    authorise("SystemAdmin", "EditorInChief", "HandlingEditor", "Author")
    appeal = store.appeals.get(aid)
    if appeal is None:
        raise ApiError("ERR_APPEAL_NOT_FOUND")
    return object_response(ser.appeal_out(appeal), 200)


@bp.get("/appeals")
def list_appeals():
    authorise("SystemAdmin", "EditorInChief", "HandlingEditor", "Author")
    limit, offset = v.pagination()
    manuscript_id = v.query_str("manuscript_id")
    decision_id = v.query_str("decision_id")
    adjudicator_id = v.query_str("adjudicated_by_editor_id")
    state = v.query_str("state")
    rows = []
    for row in store.appeals.values():
        if manuscript_id is not None and row["manuscript_id"] != manuscript_id:
            continue
        if decision_id is not None and row["decision_id"] != decision_id:
            continue
        if adjudicator_id is not None and row["adjudicated_by_editor_id"] != adjudicator_id:
            continue
        if state is not None and row["state"] != state:
            continue
        rows.append(row)
    rows = ordered(rows)
    page = v.window(rows, limit, offset)
    return list_response(ser.many(page, ser.appeal_out), limit, offset, len(rows))
