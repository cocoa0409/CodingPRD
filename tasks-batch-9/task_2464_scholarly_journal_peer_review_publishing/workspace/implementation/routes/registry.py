"""Journals, editors, authors and reviewers (PRD Section 3.1)."""

from flask import Blueprint

import calc
import serializers as ser
import validate as v
from auth import authorise
from db import ordered, stamp_new, store, touch
from errors import ApiError
from response import list_response, object_response

bp = Blueprint("registry", __name__)

ALL_ROLES = (
    "SystemAdmin",
    "EditorInChief",
    "HandlingEditor",
    "ProductionStaff",
    "Reviewer",
    "Author",
)
EDITORIAL_ROLES = ("SystemAdmin", "EditorInChief", "HandlingEditor")

CONSENSUS_MODES = ("UNWEIGHTED", "RELIABILITY_WEIGHTED")
ROLE_LEVELS = ("HANDLING", "CHIEF")
EDITOR_STATUSES = ("ACTIVE", "ON_LEAVE")
INCOME_BANDS = ("HIGH", "UPPER_MIDDLE", "LOWER_MIDDLE", "LOW")
REVIEWER_STATUSES = ("ACTIVE", "PROBATION", "RETIRED")

# name -> (kind, default, minimum) for the journal configuration block
JOURNAL_CONFIG = (
    ("doi_prefix", "string", "10.5555", None),
    ("min_completed_reviews_for_decision", "int", 2, 1),
    ("max_revision_rounds", "int", 2, 0),
    ("review_target_days", "int", 21, 1),
    ("reminder_cadence_days", "int", 7, 1),
    ("max_reminders_per_invitation", "int", 2, 0),
    ("reviewer_concurrent_window_limit", "int", 3, 1),
    ("consensus_mode", "enum", "UNWEIGHTED", CONSENSUS_MODES),
    ("max_page_count", "int", 30, 1),
    ("max_figure_count", "int", 10, 0),
    ("requires_data_availability_statement", "bool", True, None),
    ("apc_base_cents", "int", 180000, 0),
    ("page_charge_cents_per_page", "int", 4000, 0),
    ("color_figure_charge_cents", "int", 25000, 0),
    ("embargo_months", "int", 12, 0),
    ("typeset_changeover_buffer_days", "int", 2, 0),
    ("max_proof_rounds", "int", 2, 1),
)
PATCHABLE = tuple(name for name, _, _, _ in JOURNAL_CONFIG if name != "doi_prefix")


def _read_config(data, name, kind, default, extra):
    if kind == "int":
        return v.opt_int(data, name, default=default, minimum=extra)
    if kind == "bool":
        return v.opt_bool(data, name, default=default)
    if kind == "enum":
        return v.opt_enum(data, name, extra, default=default)
    return v.opt_string(data, name, default=default, allow_empty=False)


# ==========================================================================
# journals
# ==========================================================================
@bp.post("/journals")
def create_journal():
    authorise("SystemAdmin")
    data = v.body()
    row = {
        "name": v.req_string(data, "name"),
        "subject_areas": v.req_string_array(data, "subject_areas"),
    }
    for name, kind, default, extra in JOURNAL_CONFIG:
        row[name] = _read_config(data, name, kind, default, extra)
    for existing in store.journals.values():
        if existing["name"] == row["name"]:
            raise ApiError("ERR_DUPLICATE_KEY", "A journal with this name already exists.")
    row["manuscript_intake_count"] = 0
    row["published_article_count"] = 0
    row["retracted_article_count"] = 0
    row["apc_receivable_cents"] = 0
    row["apc_waived_cents"] = 0
    stamp_new(row)
    store.journals[row["id"]] = row
    return object_response(ser.journal_out(row), 201)


@bp.patch("/journals/<jid>")
def patch_journal(jid):
    authorise("SystemAdmin")
    journal = store.journals.get(jid)
    if journal is None:
        raise ApiError("ERR_JOURNAL_NOT_FOUND")
    data = v.body()
    updates = {}
    for name, kind, default, extra in JOURNAL_CONFIG:
        if name not in PATCHABLE or name not in data or data[name] is None:
            continue
        updates[name] = _read_config(data, name, kind, journal[name], extra)
    journal.update(updates)
    touch(journal)
    return object_response(ser.journal_out(journal), 200)


@bp.get("/journals/<jid>")
def get_journal(jid):
    authorise(*ALL_ROLES)
    journal = store.journals.get(jid)
    if journal is None:
        raise ApiError("ERR_JOURNAL_NOT_FOUND")
    return object_response(ser.journal_out(journal), 200)


@bp.get("/journals")
def list_journals():
    authorise(*ALL_ROLES)
    limit, offset = v.pagination()
    rows = ordered(list(store.journals.values()))
    page = v.window(rows, limit, offset)
    return list_response(ser.many(page, ser.journal_out), limit, offset, len(rows))


@bp.get("/journals/<jid>/metrics")
def journal_metrics(jid):
    authorise("SystemAdmin", "EditorInChief")
    journal = store.journals.get(jid)
    if journal is None:
        raise ApiError("ERR_JOURNAL_NOT_FOUND")
    return object_response(calc.journal_metrics(journal), 200)


# ==========================================================================
# editors
# ==========================================================================
@bp.post("/editors")
def create_editor():
    authorise("SystemAdmin")
    data = v.body()
    journal_id = v.req_id(data, "journal_id")
    if journal_id not in store.journals:
        raise ApiError("ERR_JOURNAL_NOT_FOUND")
    row = {
        "journal_id": journal_id,
        "email": v.req_string(data, "email"),
        "full_name": v.req_string(data, "full_name"),
        "affiliation": v.req_string(data, "affiliation"),
        "subject_areas": v.req_string_array(data, "subject_areas"),
        "role_level": v.req_enum(data, "role_level", ROLE_LEVELS),
        "status": v.opt_enum(data, "status", EDITOR_STATUSES, default="ACTIVE"),
        "max_concurrent_assignments": v.opt_int(
            data, "max_concurrent_assignments", default=3, minimum=1
        ),
    }
    for existing in store.editors.values():
        if existing["journal_id"] == journal_id and existing["email"] == row["email"]:
            raise ApiError("ERR_DUPLICATE_KEY", "This journal already has an editor with that email.")
    row["active_assignment_count"] = 0
    stamp_new(row)
    store.editors[row["id"]] = row
    return object_response(ser.editor_out(row), 201)


@bp.get("/editors/<eid>")
def get_editor(eid):
    authorise(*EDITORIAL_ROLES)
    editor = store.editors.get(eid)
    if editor is None:
        raise ApiError("ERR_EDITOR_NOT_FOUND")
    return object_response(ser.editor_out(editor), 200)


@bp.get("/editors")
def list_editors():
    authorise(*EDITORIAL_ROLES)
    limit, offset = v.pagination()
    journal_id = v.query_str("journal_id")
    role_level = v.query_str("role_level")
    status = v.query_str("status")
    rows = []
    for editor in store.editors.values():
        if journal_id is not None and editor["journal_id"] != journal_id:
            continue
        if role_level is not None and editor["role_level"] != role_level:
            continue
        if status is not None and editor["status"] != status:
            continue
        rows.append(editor)
    rows = ordered(rows)
    page = v.window(rows, limit, offset)
    return list_response(ser.many(page, ser.editor_out), limit, offset, len(rows))


# ==========================================================================
# authors
# ==========================================================================
@bp.post("/authors")
def create_author():
    authorise("SystemAdmin")
    data = v.body()
    row = {
        "email": v.req_string(data, "email"),
        "full_name": v.req_string(data, "full_name"),
        "affiliation": v.req_string(data, "affiliation"),
        "country_income_band": v.opt_enum(
            data, "country_income_band", INCOME_BANDS, default="HIGH"
        ),
        "institutional_agreement": v.opt_bool(data, "institutional_agreement", default=False),
    }
    for existing in store.authors.values():
        if existing["email"] == row["email"]:
            raise ApiError("ERR_DUPLICATE_KEY", "An author with this email already exists.")
    stamp_new(row)
    store.authors[row["id"]] = row
    return object_response(ser.author_out(row), 201)


@bp.get("/authors/<aid>")
def get_author(aid):
    authorise("SystemAdmin", "EditorInChief", "HandlingEditor", "ProductionStaff", "Author")
    author = store.authors.get(aid)
    if author is None:
        raise ApiError("ERR_AUTHOR_NOT_FOUND")
    return object_response(ser.author_out(author), 200)


# ==========================================================================
# reviewers
# ==========================================================================
@bp.post("/reviewers")
def create_reviewer():
    authorise("SystemAdmin", "EditorInChief")
    data = v.body()
    row = {
        "email": v.req_string(data, "email"),
        "full_name": v.req_string(data, "full_name"),
        "affiliation": v.req_string(data, "affiliation"),
        "subject_areas": v.req_string_array(data, "subject_areas"),
        "status": v.opt_enum(data, "status", REVIEWER_STATUSES, default="ACTIVE"),
    }
    for existing in store.reviewers.values():
        if existing["email"] == row["email"]:
            raise ApiError("ERR_DUPLICATE_KEY", "A reviewer with this email already exists.")
    row["invited_count"] = 0
    row["accepted_count"] = 0
    row["declined_count"] = 0
    row["expired_count"] = 0
    row["submitted_count"] = 0
    row["late_days_total"] = 0
    row["open_invitation_count"] = 0
    row["reliability_score_rolling"] = calc.NEUTRAL_SEED
    row["reliability_score_lifetime"] = calc.NEUTRAL_SEED
    stamp_new(row)
    store.reviewers[row["id"]] = row
    return object_response(ser.reviewer_out(row), 201)


@bp.get("/reviewers/<rid>")
def get_reviewer(rid):
    authorise("SystemAdmin", "EditorInChief", "HandlingEditor", "Reviewer")
    reviewer = store.reviewers.get(rid)
    if reviewer is None:
        raise ApiError("ERR_REVIEWER_NOT_FOUND")
    return object_response(ser.reviewer_out(reviewer), 200)


@bp.get("/reviewers")
def list_reviewers():
    authorise(*EDITORIAL_ROLES)
    limit, offset = v.pagination()
    status = v.query_str("status")
    subject_area = v.query_str("subject_area")
    rows = []
    for reviewer in store.reviewers.values():
        if status is not None and reviewer["status"] != status:
            continue
        if subject_area is not None and subject_area not in (reviewer["subject_areas"] or []):
            continue
        rows.append(reviewer)
    rows = ordered(rows)
    page = v.window(rows, limit, offset)
    return list_response(ser.many(page, ser.reviewer_out), limit, offset, len(rows))
