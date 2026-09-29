"""ContentEdit endpoints and the four-hop revision cascade (PRD 3.3)."""

import calc
import domain
import serializers as S
import validation as V
from db import apply_changes, base_record, db
from errors import fail
from middleware import authorize
from response import respond, respond_list

from flask import Blueprint

bp = Blueprint("content_edits", __name__)

READ_ROLES = (
    "PlatformAdmin",
    "PublisherEditor",
    "EditorialDirector",
    "StateAdoptionOfficer",
)

VERDICTS = ("APPROVE", "REJECT")


@bp.post("/content-edits")
def create_content_edit():
    user_id, _role = authorize(("PublisherEditor",))
    payload = V.body()

    title_id = V.get_str(payload, "title_id")
    state_id = V.get_str(payload, "state_id")
    edit_type = V.get_enum(payload, "edit_type", V.EDIT_TYPES)
    topic_code = V.get_str(
        payload, "topic_code", min_len=1, max_len=40, pattern=V.CODE_RE
    )
    pages_delta = V.get_int(payload, "pages_delta", minimum=-80, maximum=80)
    rationale = V.get_str(payload, "rationale", min_len=10, max_len=500)

    domain.find_title(title_id, "ERR_REFERENCED_RESOURCE_NOT_FOUND")
    domain.find_state(state_id, "ERR_REFERENCED_RESOURCE_NOT_FOUND")

    record = base_record()
    record.update(
        {
            "title_id": title_id,
            "state_id": state_id,
            "edit_type": edit_type,
            "topic_code": topic_code,
            "pages_delta": pages_delta,
            "rationale": rationale,
            "status": "PROPOSED",
            "revision_round": 1,
            "proposed_by_user_id": user_id,
            "reviewed_by_user_id": None,
            "rejection_reason": None,
            "_applied_revision": None,
        }
    )
    db.content_edits[record["id"]] = record
    return respond(S.serialize(record, S.CONTENT_EDIT_FIELDS), 201)


@bp.get("/content-edits/<edit_id>")
def get_content_edit(edit_id):
    authorize(READ_ROLES)
    record = domain.find_content_edit(edit_id)
    return respond(S.serialize(record, S.CONTENT_EDIT_FIELDS))


@bp.get("/content-edits")
def list_content_edits():
    authorize(READ_ROLES)
    limit, offset = V.pagination()
    title_id = V.query_str("title_id")
    state_id = V.query_str("state_id")
    edit_type = V.query_enum("edit_type", V.EDIT_TYPES)
    status = V.query_enum("status", V.EDIT_STATUSES)

    items = domain.ordered(list(db.content_edits.values()))
    if title_id is not None:
        items = [i for i in items if i["title_id"] == title_id]
    if state_id is not None:
        items = [i for i in items if i["state_id"] == state_id]
    if edit_type is not None:
        items = [i for i in items if i["edit_type"] == edit_type]
    if status is not None:
        items = [i for i in items if i["status"] == status]

    total = len(items)
    page = items[offset:offset + limit]
    return respond_list(
        S.serialize_many(page, S.CONTENT_EDIT_FIELDS), total, limit, offset
    )


@bp.post("/content-edits/<edit_id>/review")
def review_content_edit(edit_id):
    user_id, _role = authorize(("EditorialDirector",))
    payload = V.body()

    verdict = V.get_enum(payload, "verdict", VERDICTS)
    rejection_reason = V.get_str(
        payload, "rejection_reason", min_len=1, max_len=500,
        required=False, default=None,
    )
    if verdict == "REJECT" and rejection_reason is None:
        fail(
            "ERR_INVALID_REQUEST",
            "rejection_reason is required for a REJECT verdict.",
        )

    edit = domain.find_content_edit(edit_id)
    if edit["status"] != "PROPOSED":
        fail(
            "ERR_CONTENT_EDIT_STATE_INVALID",
            "Only a PROPOSED edit may be reviewed.",
        )
    if user_id == edit["proposed_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The reviewer must differ from the proposer.",
        )

    if verdict == "APPROVE":
        changes = {
            "status": "APPROVED",
            "reviewed_by_user_id": user_id,
            "rejection_reason": None,
        }
    else:
        changes = {
            "status": "REJECTED",
            "reviewed_by_user_id": user_id,
            "rejection_reason": rejection_reason,
        }
    apply_changes(edit, changes)
    return respond(S.serialize(edit, S.CONTENT_EDIT_FIELDS))


@bp.post("/content-edits/<edit_id>/resubmit")
def resubmit_content_edit(edit_id):
    user_id, _role = authorize(("PublisherEditor",))
    payload = V.body()

    topic_code = V.get_str(
        payload, "topic_code", min_len=1, max_len=40, pattern=V.CODE_RE,
        required=False, default=None,
    )
    pages_delta = V.get_int(
        payload, "pages_delta", minimum=-80, maximum=80,
        required=False, default=None,
    )
    rationale = V.get_str(
        payload, "rationale", min_len=10, max_len=500, required=False, default=None
    )

    edit = domain.find_content_edit(edit_id)
    if edit["status"] != "REJECTED":
        fail(
            "ERR_CONTENT_EDIT_STATE_INVALID",
            "Only a REJECTED edit may be resubmitted.",
        )
    if edit["revision_round"] >= calc.MAX_REVISION_ROUNDS:
        fail(
            "ERR_EDIT_REVISION_LIMIT_REACHED",
            "This edit has exhausted its %d review rounds."
            % calc.MAX_REVISION_ROUNDS,
        )

    changes = {
        "status": "PROPOSED",
        "revision_round": edit["revision_round"] + 1,
        "proposed_by_user_id": user_id,
    }
    if topic_code is not None:
        changes["topic_code"] = topic_code
    if pages_delta is not None:
        changes["pages_delta"] = pages_delta
    if rationale is not None:
        changes["rationale"] = rationale

    apply_changes(edit, changes)
    return respond(S.serialize(edit, S.CONTENT_EDIT_FIELDS))


def _tags_after_apply(tags, edit_type, topic_code):
    result = list(tags)
    if edit_type == "ADD_REQUIRED_TOPIC":
        if topic_code not in result:
            result.append(topic_code)
    elif edit_type == "REMOVE_PROHIBITED_TAG":
        result = [t for t in result if t != topic_code]
    return result


def _tags_after_revert(tags, edit_type, topic_code):
    result = list(tags)
    if edit_type == "ADD_REQUIRED_TOPIC":
        result = [t for t in result if t != topic_code]
    elif edit_type == "REMOVE_PROHIBITED_TAG":
        if topic_code not in result:
            result.append(topic_code)
    return result


@bp.post("/content-edits/<edit_id>/apply")
def apply_content_edit(edit_id):
    authorize(("EditorialDirector",))
    V.body()

    edit = domain.find_content_edit(edit_id)
    if edit["status"] != "APPROVED":
        fail(
            "ERR_CONTENT_EDIT_STATE_INVALID",
            "Only an APPROVED edit may be applied.",
        )

    title = domain.find_title(edit["title_id"])
    if title["status"] == "SUNSET":
        fail("ERR_TITLE_SUNSET", "A SUNSET edition can no longer be edited.")

    new_page_count = title["page_count"] + edit["pages_delta"]
    if new_page_count < 1 or new_page_count > title["signature_page_capacity"]:
        fail(
            "ERR_PAGE_BUDGET_EXCEEDED",
            "The resulting page count falls outside the signature budget.",
        )

    # HOP 1 - rewrite the edition.
    new_revision = title["content_revision"] + 1
    apply_changes(
        title,
        {
            "page_count": new_page_count,
            "page_budget_remaining": title["signature_page_capacity"] - new_page_count,
            "content_revision": new_revision,
            "content_tags": _tags_after_apply(
                title["content_tags"], edit["edit_type"], edit["topic_code"]
            ),
        },
    )
    edit["_applied_revision"] = new_revision
    apply_changes(edit, {"status": "APPLIED"})

    # HOPS 2 - 4.
    domain.cascade_content_revision(title)

    return respond(S.serialize(edit, S.CONTENT_EDIT_FIELDS))


@bp.post("/content-edits/<edit_id>/revert")
def revert_content_edit(edit_id):
    authorize(("EditorialDirector",))
    payload = V.body()
    V.get_str(payload, "reason", min_len=1, max_len=500, required=False, default=None)

    edit = domain.find_content_edit(edit_id)
    if edit["status"] != "APPLIED":
        fail(
            "ERR_CONTENT_EDIT_STATE_INVALID",
            "Only an APPLIED edit may be reverted.",
        )

    applied_revision = edit.get("_applied_revision")
    for submission in domain.submissions_of_title(edit["title_id"]):
        if submission["review_status"] not in ("ADOPTED", "ADOPTED_WITH_CONDITIONS"):
            continue
        pinned = submission["pinned_content_revision"]
        if (
            applied_revision is not None
            and pinned is not None
            and pinned >= applied_revision
        ):
            fail(
                "ERR_EDIT_REVERT_BLOCKED",
                "An adopted submission pinned the revision this edit produced.",
            )

    title = domain.find_title(edit["title_id"])
    new_page_count = title["page_count"] - edit["pages_delta"]
    apply_changes(
        title,
        {
            "page_count": new_page_count,
            "page_budget_remaining": title["signature_page_capacity"] - new_page_count,
            "content_revision": title["content_revision"] + 1,
            "content_tags": _tags_after_revert(
                title["content_tags"], edit["edit_type"], edit["topic_code"]
            ),
        },
    )
    apply_changes(edit, {"status": "REVERTED"})

    domain.recompute_live_submissions_of_title(title)

    return respond(S.serialize(edit, S.CONTENT_EDIT_FIELDS))
