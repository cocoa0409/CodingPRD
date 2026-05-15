"""Manuscript endpoints: CRUD plus the entire manuscript state machine.

Includes:
- POST /manuscripts (create DRAFT)
- GET /manuscripts/{id}, GET /manuscripts (list with filters)
- POST /manuscripts/{id}/submit
- POST /manuscripts/{id}/withdraw
- POST /manuscripts/{id}/coauthor-confirmations/{cid}/confirm
- POST /manuscripts/{id}/coauthor-confirmations/{cid}/decline
- GET  /manuscripts/{id}/coauthor-confirmations
- POST /manuscripts/{id}/assign-section-editor
- POST /manuscripts/{id}/desk-reject
- POST /manuscripts/{id}/assign-associate
- POST /manuscripts/{id}/revisions
- POST /manuscripts/{id}/reinvite-reviewers
- POST /manuscripts/{id}/retract
"""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g, request

from ..auth import require_auth
from ..calculations import (
    EDITOR_ASSIGNMENT_WINDOW_DAYS,
    MAJOR_DAYS,
    MINOR_DAYS,
)
from ..clock import clock
from ..errors import api_error
from ..response import list_envelope, success_envelope
from ..store import store
from ..utils import (
    check_version,
    get_json_body,
    optional_list,
    optional_str,
    page_slice,
    parse_iso_datetime,
    parse_pagination,
    require_str,
    validate_topic_tag,
)


manuscripts_bp = Blueprint("manuscripts", __name__)


_MS_STATUSES = {
    "DRAFT",
    "AWAITING_COAUTHOR",
    "SUBMITTED",
    "DESK_REJECTED",
    "UNDER_REVIEW",
    "REVISION_REQUIRED",
    "REVISION_SUBMITTED",
    "ACCEPTED",
    "REJECTED",
    "WITHDRAWN",
    "IN_PRODUCTION",
    "PUBLISHED",
    "RETRACTED",
}
_REVIEW_MODES = {"SINGLE_BLIND", "DOUBLE_BLIND", "OPEN"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_manuscript(mid: str) -> dict:
    m = store.manuscripts.get(mid)
    if not m:
        raise api_error("ERR_NOT_FOUND", "Manuscript not found")
    return m


def _own_as_author(manuscript: dict) -> None:
    if g.user_role == "Author" and g.user_id != manuscript["corresponding_author_id"]:
        raise api_error("ERR_FORBIDDEN", "Caller is not the corresponding author")


def _own_as_section_editor(manuscript: dict) -> None:
    if g.user_role == "SectionEditor" and g.user_id != manuscript.get("section_editor_id"):
        raise api_error("ERR_FORBIDDEN", "Caller is not the assigned section editor")


def _own_as_associate_editor(manuscript: dict) -> None:
    if g.user_role == "AssociateEditor" and g.user_id != manuscript.get("associate_editor_id"):
        raise api_error("ERR_FORBIDDEN", "Caller is not the assigned associate editor")


def _audit(entity: str, entity_id: str, action: str, from_state=None, to_state=None, details=None):
    store.append_audit(
        actor_role=g.user_role,
        actor_id=g.user_id,
        entity=entity,
        entity_id=entity_id,
        action=action,
        from_state=from_state,
        to_state=to_state,
        details=details,
    )


def _latest_plagiarism_check(manuscript_id: str) -> dict | None:
    rows = [p for p in store.plagiarism_checks.values() if p["manuscript_id"] == manuscript_id]
    if not rows:
        return None
    return sorted(rows, key=lambda r: r["created_at"])[-1]


def _coauthor_confirmations_for(manuscript_id: str) -> list[dict]:
    return [c for c in store.coauthor_confirmations.values() if c["manuscript_id"] == manuscript_id]


def _invitations_for(manuscript_id: str, revision_round: int | None = None) -> list[dict]:
    rows = [i for i in store.reviewer_invitations.values() if i["manuscript_id"] == manuscript_id]
    if revision_round is not None:
        rows = [i for i in rows if i["revision_round"] == revision_round]
    return rows


def _reviews_for_round(manuscript_id: str, revision_round: int) -> list[dict]:
    return [
        r for r in store.reviews.values()
        if r["manuscript_id"] == manuscript_id and r["revision_round"] == revision_round
    ]


def _cascade_withdraw_invitations_and_reviews(manuscript: dict, also_supersede_reviews: bool):
    """When manuscript is withdrawn from SUBMITTED or UNDER_REVIEW, withdraw
    PENDING invitations at the current round, and supersede DRAFT/SUBMITTED
    reviews at the current round (only when also_supersede_reviews=True)."""
    rd = manuscript["revision_round"]
    for inv in _invitations_for(manuscript["id"], rd):
        if inv["status"] == "PENDING":
            inv["status"] = "WITHDRAWN"
            store.stamp_update(inv)
    if also_supersede_reviews:
        for rv in _reviews_for_round(manuscript["id"], rd):
            if rv["status"] in ("DRAFT", "SUBMITTED"):
                prev = rv["status"]
                rv["status"] = "SUPERSEDED"
                if prev == "DRAFT":
                    rv["submitted_at"] = None
                store.stamp_update(rv)
                _audit("Review", rv["id"], "REVIEW_SUPERSEDED", prev, "SUPERSEDED")


# ---------------------------------------------------------------------------
# Create / Read manuscripts
# ---------------------------------------------------------------------------

@manuscripts_bp.route("/manuscripts", methods=["POST"])
@require_auth(["Author"])
def create_manuscript():
    body = get_json_body()
    title = require_str(body, "title")
    corresponding_author_id = require_str(body, "corresponding_author_id")
    topic_tag = require_str(body, "topic_tag")
    review_mode = require_str(body, "review_mode")
    # PRD §3.2: "draft must carry ... manuscript_file_uri, and all three
    # declarations". The non-empty check is at SUBMIT time per §3.2; at
    # create we only require the keys to be present (string type).
    for _k in ("manuscript_file_uri", "declaration_coi",
               "declaration_funding", "declaration_ethics"):
        if _k not in body or not isinstance(body.get(_k), str):
            raise api_error("ERR_VALIDATION",
                            f"Field '{_k}' is required and must be a string")
    manuscript_file_uri = body["manuscript_file_uri"]
    declaration_coi = body["declaration_coi"]
    declaration_funding = body["declaration_funding"]
    declaration_ethics = body["declaration_ethics"]

    co_author_ids = optional_list(body, "co_author_ids")
    supplementary_file_uris = optional_list(body, "supplementary_file_uris")
    suggested_reviewer_ids = optional_list(body, "suggested_reviewer_ids")
    excluded_reviewer_ids = optional_list(body, "excluded_reviewer_ids")

    validate_topic_tag(topic_tag)
    if review_mode not in _REVIEW_MODES:
        raise api_error("ERR_VALIDATION", "review_mode invalid")

    # Author ownership: caller is the corresponding author
    if g.user_id != corresponding_author_id:
        raise api_error("ERR_FORBIDDEN", "Author can only create manuscripts for themselves")

    with store.lock:
        # Existence checks for foreign keys
        if corresponding_author_id not in store.authors:
            raise api_error("ERR_NOT_FOUND", "corresponding_author_id does not exist")
        for cid in co_author_ids:
            if cid not in store.authors:
                raise api_error("ERR_NOT_FOUND", f"co_author_id {cid} does not exist")
        for sid in suggested_reviewer_ids:
            if sid not in store.reviewers:
                raise api_error("ERR_NOT_FOUND", f"suggested_reviewer_id {sid} does not exist")
        for eid in excluded_reviewer_ids:
            if eid not in store.reviewers:
                raise api_error("ERR_NOT_FOUND", f"excluded_reviewer_id {eid} does not exist")

        # Business validation: ERR_COAUTHOR_LIST_INVALID
        if corresponding_author_id in co_author_ids or len(set(co_author_ids)) != len(co_author_ids):
            raise api_error(
                "ERR_COAUTHOR_LIST_INVALID",
                "co_author_ids must not contain corresponding_author_id and must be unique",
            )
        # ERR_REVIEWER_LISTS_OVERLAP
        if set(suggested_reviewer_ids) & set(excluded_reviewer_ids):
            raise api_error(
                "ERR_REVIEWER_LISTS_OVERLAP",
                "suggested_reviewer_ids and excluded_reviewer_ids must be disjoint",
            )

        row = {
            "title": title,
            "corresponding_author_id": corresponding_author_id,
            "co_author_ids": list(co_author_ids),
            "topic_tag": topic_tag,
            "review_mode": review_mode,
            "manuscript_file_uri": manuscript_file_uri,
            "supplementary_file_uris": list(supplementary_file_uris),
            "declaration_coi": declaration_coi,
            "declaration_funding": declaration_funding,
            "declaration_ethics": declaration_ethics,
            "suggested_reviewer_ids": list(suggested_reviewer_ids),
            "excluded_reviewer_ids": list(excluded_reviewer_ids),
            "status": "DRAFT",
            "section_editor_id": None,
            "associate_editor_id": None,
            "associate_assigned_at": None,
            "associate_window_end_at": None,
            "revision_round": 0,
            "revision_deadline_at": None,
            "plagiarism_similarity": None,
            "doi": None,
            "issue_label": None,
        }
        store.stamp_create(row)
        store.manuscripts[row["id"]] = row
        _audit("Manuscript", row["id"], "MANUSCRIPT_CREATED", None, "DRAFT")
        return success_envelope(row, status=201, response_type="object")


@manuscripts_bp.route("/manuscripts/<mid>", methods=["GET"])
@require_auth(["PlatformAdmin", "Author", "EditorInChief", "SectionEditor", "AssociateEditor"])
def get_manuscript(mid: str):
    m = _require_manuscript(mid)
    return success_envelope(m, status=200, response_type="object")


@manuscripts_bp.route("/manuscripts", methods=["GET"])
@require_auth(["PlatformAdmin", "EditorInChief", "SectionEditor", "AssociateEditor"])
def list_manuscripts():
    limit, offset = parse_pagination()
    status_f = request.args.get("status")
    topic_tag = request.args.get("topic_tag")
    corr_author = request.args.get("corresponding_author_id")
    rows = sorted(store.manuscripts.values(), key=lambda r: r["created_at"])
    if status_f:
        rows = [r for r in rows if r.get("status") == status_f]
    if topic_tag:
        rows = [r for r in rows if r.get("topic_tag") == topic_tag]
    if corr_author:
        rows = [r for r in rows if r.get("corresponding_author_id") == corr_author]
    page, total = page_slice(rows, limit, offset)
    return list_envelope(page, total=total, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

@manuscripts_bp.route("/manuscripts/<mid>/submit", methods=["POST"])
@require_auth(["Author"])
def submit_manuscript(mid: str):
    body = get_json_body()
    with store.lock:
        m = _require_manuscript(mid)
        _own_as_author(m)
        if m["status"] != "DRAFT":
            raise api_error("ERR_INVALID_STATE", "Manuscript not in DRAFT state")
        check_version(body, m)
        # business validations: ORCID
        author = store.authors.get(m["corresponding_author_id"])
        if not author or not author.get("orcid_verified"):
            raise api_error("ERR_ORCID_NOT_VERIFIED", "Corresponding author orcid is not verified")
        # declarations + manuscript_file_uri non-empty
        if not all(
            isinstance(m.get(k), str) and m.get(k)
            for k in ("declaration_coi", "declaration_funding", "declaration_ethics", "manuscript_file_uri")
        ):
            raise api_error("ERR_DECLARATION_INCOMPLETE", "Declarations or manuscript file missing")

        co_authors = m["co_author_ids"]
        prev = m["status"]
        if co_authors:
            m["status"] = "AWAITING_COAUTHOR"
            store.stamp_update(m)
            for aid in co_authors:
                conf = {
                    "manuscript_id": m["id"],
                    "author_id": aid,
                    "status": "PENDING",
                    "responded_at": None,
                }
                store.stamp_create(conf)
                store.coauthor_confirmations[conf["id"]] = conf
            _audit("Manuscript", m["id"], "MANUSCRIPT_SUBMITTED", prev, m["status"])
        else:
            m["status"] = "SUBMITTED"
            store.stamp_update(m)
            _audit("Manuscript", m["id"], "MANUSCRIPT_SUBMITTED", prev, m["status"])
        return success_envelope(m, status=200, response_type="object")


# ---------------------------------------------------------------------------
# Withdraw
# ---------------------------------------------------------------------------

@manuscripts_bp.route("/manuscripts/<mid>/withdraw", methods=["POST"])
@require_auth(["Author"])
def withdraw_manuscript(mid: str):
    body = get_json_body()
    with store.lock:
        m = _require_manuscript(mid)
        _own_as_author(m)
        if m["status"] not in ("DRAFT", "SUBMITTED", "UNDER_REVIEW"):
            raise api_error("ERR_INVALID_STATE", "Manuscript cannot be withdrawn from current state")
        check_version(body, m)
        prev = m["status"]
        if prev == "DRAFT":
            m["status"] = "WITHDRAWN"
            store.stamp_update(m)
        elif prev == "SUBMITTED":
            _cascade_withdraw_invitations_and_reviews(m, also_supersede_reviews=False)
            m["status"] = "WITHDRAWN"
            store.stamp_update(m)
        else:  # UNDER_REVIEW
            _cascade_withdraw_invitations_and_reviews(m, also_supersede_reviews=True)
            m["status"] = "WITHDRAWN"
            store.stamp_update(m)
        _audit("Manuscript", m["id"], "WITHDRAWN_BY_AUTHOR", prev, "WITHDRAWN")
        return success_envelope(m, status=200, response_type="object")


# ---------------------------------------------------------------------------
# Co-author confirmation
# ---------------------------------------------------------------------------

@manuscripts_bp.route("/manuscripts/<mid>/coauthor-confirmations", methods=["GET"])
@require_auth(["PlatformAdmin", "Author", "EditorInChief", "SectionEditor", "AssociateEditor"])
def list_coauthor_confirmations(mid: str):
    _require_manuscript(mid)
    rows = sorted(_coauthor_confirmations_for(mid), key=lambda r: r["created_at"])
    limit, offset = parse_pagination()
    page, total = page_slice(rows, limit, offset)
    return list_envelope(page, total=total, limit=limit, offset=offset)


def _resolve_confirmation(mid: str, cid: str) -> tuple[dict, dict]:
    m = _require_manuscript(mid)
    conf = store.coauthor_confirmations.get(cid)
    if not conf or conf["manuscript_id"] != mid:
        raise api_error("ERR_NOT_FOUND", "CoAuthorConfirmation not found")
    return m, conf


@manuscripts_bp.route("/manuscripts/<mid>/coauthor-confirmations/<cid>/confirm", methods=["POST"])
@require_auth(["Author"])
def confirm_coauthor(mid: str, cid: str):
    with store.lock:
        m, conf = _resolve_confirmation(mid, cid)
        if g.user_id != conf["author_id"]:
            raise api_error("ERR_FORBIDDEN", "Caller is not the co-author of this confirmation")
        if conf["status"] != "PENDING":
            raise api_error("ERR_INVALID_STATE", "Confirmation already responded")
        if m["status"] != "AWAITING_COAUTHOR":
            raise api_error("ERR_INVALID_STATE", "Manuscript no longer awaiting co-authors")
        from ..store import now_ts
        prev = conf["status"]
        conf["status"] = "CONFIRMED"
        conf["responded_at"] = now_ts()
        store.stamp_update(conf)
        _audit("CoAuthorConfirmation", conf["id"], "COAUTHOR_CONFIRMED", prev, "CONFIRMED")
        # Bubble up: if all sibling rows are CONFIRMED, manuscript -> SUBMITTED
        siblings = _coauthor_confirmations_for(mid)
        if all(s["status"] == "CONFIRMED" for s in siblings):
            ms_prev = m["status"]
            m["status"] = "SUBMITTED"
            store.stamp_update(m)
            _audit("Manuscript", m["id"], "COAUTHORS_CONFIRMED", ms_prev, "SUBMITTED")
        return success_envelope(conf, status=200, response_type="object")


@manuscripts_bp.route("/manuscripts/<mid>/coauthor-confirmations/<cid>/decline", methods=["POST"])
@require_auth(["Author"])
def decline_coauthor(mid: str, cid: str):
    with store.lock:
        m, conf = _resolve_confirmation(mid, cid)
        if g.user_id != conf["author_id"]:
            raise api_error("ERR_FORBIDDEN", "Caller is not the co-author of this confirmation")
        if conf["status"] != "PENDING":
            raise api_error("ERR_INVALID_STATE", "Confirmation already responded")
        if m["status"] != "AWAITING_COAUTHOR":
            raise api_error("ERR_INVALID_STATE", "Manuscript no longer awaiting co-authors")
        from ..store import now_ts
        prev_conf = conf["status"]
        conf["status"] = "DECLINED"
        conf["responded_at"] = now_ts()
        store.stamp_update(conf)
        # Cascade: every other PENDING sibling -> DECLINED with responded_at=now, manuscript -> WITHDRAWN
        for sib in _coauthor_confirmations_for(mid):
            if sib["id"] != conf["id"] and sib["status"] == "PENDING":
                sib["status"] = "DECLINED"
                sib["responded_at"] = now_ts()
                store.stamp_update(sib)
        ms_prev = m["status"]
        m["status"] = "WITHDRAWN"
        store.stamp_update(m)
        _audit("CoAuthorConfirmation", conf["id"], "COAUTHOR_DECLINED", prev_conf, "DECLINED")
        _audit("Manuscript", m["id"], "COAUTHOR_DECLINED_AUTO_WITHDRAW", ms_prev, "WITHDRAWN")
        return success_envelope(conf, status=200, response_type="object")


# ---------------------------------------------------------------------------
# Section / Associate editor assignment, desk-reject
# ---------------------------------------------------------------------------

@manuscripts_bp.route("/manuscripts/<mid>/assign-section-editor", methods=["POST"])
@require_auth(["EditorInChief"])
def assign_section_editor(mid: str):
    body = get_json_body()
    sec_id = require_str(body, "section_editor_id")
    with store.lock:
        m = _require_manuscript(mid)
        if m["status"] != "SUBMITTED":
            raise api_error("ERR_INVALID_STATE", "Manuscript not in SUBMITTED state")
        check_version(body, m)
        editor = store.editors.get(sec_id)
        if not editor:
            raise api_error("ERR_NOT_FOUND", "section_editor_id does not exist")
        if editor.get("role") != "SECTION_EDITOR":
            raise api_error("ERR_VALIDATION", "section_editor_id must reference an editor with role=SECTION_EDITOR")
        m["section_editor_id"] = sec_id
        store.stamp_update(m)
        _audit("Manuscript", m["id"], "SECTION_EDITOR_ASSIGNED", details={"section_editor_id": sec_id})
        return success_envelope(m, status=200, response_type="object")


@manuscripts_bp.route("/manuscripts/<mid>/desk-reject", methods=["POST"])
@require_auth(["SectionEditor"])
def desk_reject(mid: str):
    body = get_json_body()
    with store.lock:
        m = _require_manuscript(mid)
        if not m.get("section_editor_id"):
            raise api_error("ERR_INVALID_STATE", "No section editor assigned yet")
        _own_as_section_editor(m)
        if m["status"] != "SUBMITTED":
            raise api_error("ERR_INVALID_STATE", "Manuscript not in SUBMITTED state")
        check_version(body, m)
        latest = _latest_plagiarism_check(mid)
        reason = optional_str(body, "reason")
        plag_fail = bool(latest and latest.get("result") == "FAIL")
        if not plag_fail and not (reason and reason.strip()):
            raise api_error(
                "ERR_DESK_REJECT_REASON_REQUIRED",
                "Desk-reject requires either plagiarism FAIL or a non-empty reason",
            )
        prev = m["status"]
        m["status"] = "DESK_REJECTED"
        store.stamp_update(m)
        _audit("Manuscript", m["id"], "DESK_REJECTED", prev, "DESK_REJECTED", details={"reason": reason})
        return success_envelope(m, status=200, response_type="object")


def _has_overlapping_window(candidate_id: str, exclude_mid: str | None = None) -> bool:
    """Return True if candidate associate editor has another manuscript whose
    associate_window_end_at is in the future."""
    now = clock.now()
    for other in store.manuscripts.values():
        if exclude_mid and other["id"] == exclude_mid:
            continue
        if other.get("associate_editor_id") != candidate_id:
            continue
        end = other.get("associate_window_end_at")
        if not end:
            continue
        end_dt = parse_iso_datetime(end)
        if end_dt > now:
            return True
    return False


@manuscripts_bp.route("/manuscripts/<mid>/assign-associate", methods=["POST"])
@require_auth(["SectionEditor"])
def assign_associate(mid: str):
    body = get_json_body()
    assoc_id = require_str(body, "associate_editor_id")
    with store.lock:
        m = _require_manuscript(mid)
        if not m.get("section_editor_id"):
            raise api_error("ERR_INVALID_STATE", "No section editor assigned")
        _own_as_section_editor(m)
        if m["status"] != "SUBMITTED":
            raise api_error("ERR_INVALID_STATE", "Manuscript not in SUBMITTED state")
        check_version(body, m)
        editor = store.editors.get(assoc_id)
        if not editor:
            raise api_error("ERR_NOT_FOUND", "associate_editor_id does not exist")
        # Latest plagiarism check must PASS
        latest = _latest_plagiarism_check(mid)
        if not latest or latest.get("result") != "PASS":
            raise api_error("ERR_INVALID_STATE", "Latest plagiarism check must be PASS")
        # Topic match
        if editor.get("role") != "ASSOCIATE_EDITOR":
            raise api_error("ERR_EDITOR_TOPIC_MISMATCH", "Editor is not an associate editor")
        if m["topic_tag"] not in (editor.get("topic_tags") or []):
            raise api_error("ERR_EDITOR_TOPIC_MISMATCH", "Associate editor does not handle this topic_tag")
        # No invitations exist for this manuscript at current round
        if _invitations_for(mid, m["revision_round"]):
            raise api_error("ERR_INVALID_STATE", "Invitations already exist for current round")
        # Window overlap check
        if _has_overlapping_window(assoc_id, exclude_mid=mid):
            raise api_error("ERR_EDITOR_WINDOW_OVERLAP", "Associate editor has an open assignment window")
        prev = m["status"]
        now = clock.now()
        end = now + timedelta(days=EDITOR_ASSIGNMENT_WINDOW_DAYS)
        from ..store import fmt_ts
        m["associate_editor_id"] = assoc_id
        m["associate_assigned_at"] = fmt_ts(now)
        m["associate_window_end_at"] = fmt_ts(end)
        m["status"] = "UNDER_REVIEW"
        store.stamp_update(m)
        _audit("Manuscript", m["id"], "ASSOCIATE_ASSIGNED", prev, "UNDER_REVIEW",
               details={"associate_editor_id": assoc_id})
        return success_envelope(m, status=200, response_type="object")


# ---------------------------------------------------------------------------
# Revisions and reinvitations
# ---------------------------------------------------------------------------

@manuscripts_bp.route("/manuscripts/<mid>/revisions", methods=["POST"])
@require_auth(["Author"])
def submit_revision(mid: str):
    body = get_json_body()
    response_letter = require_str(body, "response_letter")
    revised_file_uri = require_str(body, "revised_file_uri")
    with store.lock:
        m = _require_manuscript(mid)
        _own_as_author(m)
        if m["status"] != "REVISION_REQUIRED":
            raise api_error("ERR_INVALID_STATE", "Manuscript not in REVISION_REQUIRED state")
        check_version(body, m)
        # Deadline check
        deadline_str = m.get("revision_deadline_at")
        if deadline_str:
            deadline_dt = parse_iso_datetime(deadline_str)
            if clock.now() > deadline_dt:
                raise api_error("ERR_REVISION_DEADLINE_PASSED", "Revision deadline has passed")
        prev_round = m["revision_round"]
        # Supersede prior reviews at the old round
        for rv in _reviews_for_round(mid, prev_round):
            if rv["status"] in ("DRAFT", "SUBMITTED"):
                prev_rs = rv["status"]
                rv["status"] = "SUPERSEDED"
                if prev_rs == "DRAFT":
                    rv["submitted_at"] = None
                store.stamp_update(rv)
                _audit("Review", rv["id"], "REVIEW_SUPERSEDED", prev_rs, "SUPERSEDED")
        m["revision_round"] = prev_round + 1
        m["manuscript_file_uri"] = revised_file_uri  # convenience: track the revised file
        m["status"] = "REVISION_SUBMITTED"
        store.stamp_update(m)
        _audit("Manuscript", m["id"], "REVISION_SUBMITTED", "REVISION_REQUIRED", "REVISION_SUBMITTED",
               details={"response_letter": response_letter, "revised_file_uri": revised_file_uri,
                        "revision_round": m["revision_round"]})
        return success_envelope(m, status=200, response_type="object")


@manuscripts_bp.route("/manuscripts/<mid>/reinvite-reviewers", methods=["POST"])
@require_auth(["AssociateEditor"])
def reinvite_reviewers(mid: str):
    body = get_json_body()
    reviewer_ids = optional_list(body, "reviewer_ids")
    if not reviewer_ids:
        raise api_error("ERR_VALIDATION", "reviewer_ids must be a non-empty array")
    with store.lock:
        m = _require_manuscript(mid)
        _own_as_associate_editor(m)
        if m["status"] != "REVISION_SUBMITTED":
            raise api_error("ERR_INVALID_STATE", "Manuscript not in REVISION_SUBMITTED state")
        check_version(body, m)
        # Existence: each reviewer must exist
        from .invitations import _create_invitation_row  # avoid cycle at import time
        created = []
        for rid in reviewer_ids:
            if rid not in store.reviewers:
                raise api_error("ERR_NOT_FOUND", f"reviewer_id {rid} does not exist")
        # Create one invitation per reviewer at the new round
        for rid in reviewer_ids:
            inv = _create_invitation_row(m, rid)
            created.append(inv)
        prev = m["status"]
        m["status"] = "UNDER_REVIEW"
        store.stamp_update(m)
        _audit("Manuscript", m["id"], "NEW_ROUND_STARTED", prev, "UNDER_REVIEW",
               details={"new_invitations": [i["id"] for i in created]})
        return success_envelope(m, status=200, response_type="object")


# ---------------------------------------------------------------------------
# Retract
# ---------------------------------------------------------------------------

@manuscripts_bp.route("/manuscripts/<mid>/retract", methods=["POST"])
@require_auth(["EditorInChief"])
def retract_manuscript(mid: str):
    body = get_json_body()
    with store.lock:
        m = _require_manuscript(mid)
        if m["status"] != "PUBLISHED":
            raise api_error("ERR_INVALID_STATE", "Manuscript not in PUBLISHED state")
        check_version(body, m)
        prev = m["status"]
        m["status"] = "RETRACTED"
        store.stamp_update(m)
        # Cascade publication
        pub = next((p for p in store.publications.values() if p["manuscript_id"] == mid), None)
        if pub:
            pub_prev = pub["status"]
            pub["status"] = "RETRACTED"
            for target in list(pub.get("indexing_status", {}).keys()):
                pub["indexing_status"][target] = "FAILED"
            store.stamp_update(pub)
            _audit("Publication", pub["id"], "PUBLICATION_RETRACTED", pub_prev, "RETRACTED")
        _audit("Manuscript", m["id"], "RETRACTED", prev, "RETRACTED")
        return success_envelope(m, status=200, response_type="object")
