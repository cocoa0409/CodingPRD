"""Submission intake, integrity screening, licensing, desk screening and revisions."""

from flask import Blueprint

import calc
import serializers as ser
import services as svc
import validate as v
from auth import authorise, require_editor_journal
from db import ordered, stamp_new, store, touch
from errors import ApiError
from response import list_response, object_response

bp = Blueprint("manuscripts", __name__)

LICENSES = ("CC_BY", "CC_BY_NC", "CC_BY_NC_ND", "GREEN_SELF_ARCHIVE")
SCAN_TYPES = ("PLAGIARISM", "IMAGE_FORENSICS")
SCREENING_ACTIONS = ("ADVANCE_TO_REVIEW", "DESK_REJECT")
MANUSCRIPT_READ_ROLES = (
    "SystemAdmin",
    "EditorInChief",
    "HandlingEditor",
    "ProductionStaff",
    "Author",
)
LICENSE_LOCKED_STATES = ("PUBLISHED", "CORRECTED", "RETRACTED", "DESK_REJECTED")


def find_manuscript(mid):
    manuscript = store.manuscripts.get(mid)
    if manuscript is None:
        raise ApiError("ERR_MANUSCRIPT_NOT_FOUND")
    return manuscript


# ==========================================================================
# intake
# ==========================================================================
@bp.post("/manuscripts")
def create_manuscript():
    actor = authorise("Author")
    data = v.body()

    # rule 5: every foreign key resolves before the rest of the body is read
    journal_id = v.req_id(data, "journal_id")
    if journal_id not in store.journals:
        raise ApiError("ERR_JOURNAL_NOT_FOUND")
    author_id = v.req_id(data, "corresponding_author_id")
    if author_id not in store.authors:
        raise ApiError("ERR_AUTHOR_NOT_FOUND")
    supersedes_id = v.opt_id(data, "supersedes_manuscript_id")
    if supersedes_id is not None and supersedes_id not in store.manuscripts:
        raise ApiError("ERR_MANUSCRIPT_NOT_FOUND")

    row = {
        "journal_id": journal_id,
        "corresponding_author_id": author_id,
        "supersedes_manuscript_id": supersedes_id,
        "title": v.req_string(data, "title"),
        "subject_area": v.req_string(data, "subject_area"),
        "oa_license": v.req_enum(data, "oa_license", LICENSES),
        "page_count": v.req_int(data, "page_count", minimum=1),
        "figure_count": v.req_int(data, "figure_count", minimum=0),
        "coauthor_emails": v.opt_string_array(data, "coauthor_emails", default=[]),
        "data_availability_statement": v.opt_string(data, "data_availability_statement"),
    }

    # rule 11: an author submits only on their own behalf
    if author_id != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "corresponding_author_id must equal X-User-ID.")

    if supersedes_id is not None:
        previous = calc.decisions_of_manuscript(supersedes_id)
        latest = previous[-1] if previous else None
        if latest is None or latest["category"] != "REJECT_AND_RESUBMIT":
            raise ApiError(
                "ERR_INVALID_MANUSCRIPT_STATE",
                "supersedes_manuscript_id must point at a manuscript whose latest decision was "
                "REJECT_AND_RESUBMIT.",
            )

    journal = store.journals[journal_id]
    row["status"] = "SUBMITTED"
    row["revision_round"] = 0
    row["journal_sequence_number"] = int(journal["manuscript_intake_count"]) + 1
    row["review_shortfall_flag"] = False
    row["handling_gap_flag"] = False
    row["consensus_index_at_last_decision"] = None
    row["decision_count"] = 0
    row["publication_date"] = None
    row["embargo_end_date"] = None
    row["doi"] = None
    row["retracted_at"] = None
    stamp_new(row)
    store.manuscripts[row["id"]] = row

    journal["manuscript_intake_count"] = int(journal["manuscript_intake_count"]) + 1
    touch(journal)
    return object_response(ser.manuscript_out(row), 201)


# ==========================================================================
# integrity screening
# ==========================================================================
@bp.post("/manuscripts/<mid>/integrity-screenings")
def create_screening(mid):
    actor = authorise("SystemAdmin", "HandlingEditor")
    manuscript = find_manuscript(mid)
    require_editor_journal(actor, manuscript)
    data = v.body()

    scan_type = v.req_enum(data, "scan_type", SCAN_TYPES)
    similarity = None
    manipulated = None
    if scan_type == "PLAGIARISM":
        if data.get("manipulated_figure_count") is not None:
            v.bad("manipulated_figure_count", "must be omitted for a PLAGIARISM scan")
        similarity = v.req_number(data, "similarity_pct", minimum=0, maximum=100)
    else:
        if data.get("similarity_pct") is not None:
            v.bad("similarity_pct", "must be omitted for an IMAGE_FORENSICS scan")
        manipulated = v.req_int(data, "manipulated_figure_count", minimum=0)

    round_no = manuscript["revision_round"]
    for existing in calc.screenings_of_manuscript(mid):
        if existing["round"] == round_no and existing["scan_type"] == scan_type:
            raise ApiError(
                "ERR_DUPLICATE_KEY",
                "This manuscript already has a %s screening for round %s." % (scan_type, round_no),
            )

    svc.guard_manuscript_terminal(manuscript)

    verdict = calc.screening_verdict(scan_type, similarity, manipulated)
    row = {
        "manuscript_id": mid,
        "round": round_no,
        "scan_type": scan_type,
        "similarity_pct": similarity,
        "manipulated_figure_count": manipulated,
        "verdict": verdict,
    }
    stamp_new(row, versioned=False)
    store.screenings[row["id"]] = row

    if verdict == "BLOCK":
        case_type = "PLAGIARISM" if scan_type == "PLAGIARISM" else "IMAGE_INTEGRITY"
        if not calc.has_unresolved_case(mid, case_type):
            svc.open_ethics_case(
                manuscript,
                case_type,
                "HIGH",
                "Automatically opened by a BLOCK %s screening in round %s."
                % (scan_type, round_no),
                "SCREENING_CASCADE",
                None,
            )

    if (
        manuscript["status"] == "REVISION_SUBMITTED"
        and verdict in ("PASS", "FLAG")
        and calc.formatting_status(manuscript) == "COMPLIANT"
    ):
        manuscript["review_shortfall_flag"] = False
        manuscript["status"] = "UNDER_REVIEW"

    touch(manuscript)
    return object_response(ser.screening_out(row), 201)


@bp.get("/manuscripts/<mid>/integrity-screenings")
def list_screenings(mid):
    actor = authorise("SystemAdmin", "EditorInChief", "HandlingEditor")
    find_manuscript(mid)
    limit, offset = v.pagination()
    round_no = v.query_int("round")
    rows = [
        s
        for s in calc.screenings_of_manuscript(mid)
        if round_no is None or s["round"] == round_no
    ]
    rows = ordered(rows)
    page = v.window(rows, limit, offset)
    return list_response(ser.many(page, ser.screening_out), limit, offset, len(rows))


# ==========================================================================
# licensing
# ==========================================================================
@bp.post("/manuscripts/<mid>/licensing")
def change_licence(mid):
    actor = authorise("Author")
    manuscript = find_manuscript(mid)
    data = v.body()
    oa_license = v.req_enum(data, "oa_license", LICENSES)
    embargo_requested = v.opt_bool(data, "embargo_requested", default=False)

    if manuscript["corresponding_author_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if manuscript["status"] in LICENSE_LOCKED_STATES:
        raise ApiError("ERR_LICENSE_LOCKED")
    if embargo_requested and oa_license != "GREEN_SELF_ARCHIVE":
        raise ApiError("ERR_EMBARGO_NOT_APPLICABLE")

    manuscript["oa_license"] = oa_license
    touch(manuscript)
    return object_response(ser.manuscript_out(manuscript), 200)


# ==========================================================================
# desk screening decision
# ==========================================================================
@bp.post("/manuscripts/<mid>/screening-decision")
def screening_decision(mid):
    actor = authorise("HandlingEditor")
    manuscript = find_manuscript(mid)
    require_editor_journal(actor, manuscript)
    data = v.body()
    action = v.req_enum(data, "action", SCREENING_ACTIONS)
    v.opt_string(data, "note")

    svc.guard_manuscript_terminal(manuscript)
    if manuscript["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_MANUSCRIPT_STATE")
    svc.require_active_assignment(manuscript, actor)

    journal = calc.journal_of(manuscript)
    if action == "ADVANCE_TO_REVIEW":
        if calc.integrity_status(manuscript) == "BLOCK":
            raise ApiError("ERR_INTEGRITY_BLOCK")
        if calc.formatting_status(manuscript) != "COMPLIANT":
            raise ApiError("ERR_FORMATTING_NON_COMPLIANT")
        if manuscript["subject_area"] not in (journal["subject_areas"] or []):
            raise ApiError("ERR_SUBJECT_AREA_OUT_OF_SCOPE")
        manuscript["review_shortfall_flag"] = False
        manuscript["status"] = "UNDER_REVIEW"
        touch(manuscript)
    else:
        manuscript["status"] = "DESK_REJECTED"
        touch(manuscript)
        svc.release_active_assignment(manuscript)
    return object_response(ser.manuscript_out(manuscript), 200)


# ==========================================================================
# revisions
# ==========================================================================
@bp.post("/manuscripts/<mid>/revisions")
def submit_revision(mid):
    actor = authorise("Author")
    manuscript = find_manuscript(mid)
    data = v.body()
    page_count = v.req_int(data, "page_count", minimum=1)
    figure_count = v.req_int(data, "figure_count", minimum=0)
    v.req_string(data, "response_letter")
    das_supplied = "data_availability_statement" in data and (
        data["data_availability_statement"] is not None
    )
    das = v.opt_string(data, "data_availability_statement")

    if manuscript["corresponding_author_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    svc.guard_manuscript_terminal(manuscript)
    if manuscript["status"] != "REVISION_REQUESTED":
        raise ApiError("ERR_INVALID_MANUSCRIPT_STATE")

    manuscript["status"] = "REVISION_SUBMITTED"
    manuscript["revision_round"] = int(manuscript["revision_round"]) + 1
    manuscript["page_count"] = page_count
    manuscript["figure_count"] = figure_count
    if das_supplied:
        manuscript["data_availability_statement"] = das
    touch(manuscript)
    return object_response(ser.manuscript_out(manuscript), 200)


# ==========================================================================
# reads
# ==========================================================================
@bp.get("/manuscripts/<mid>")
def get_manuscript(mid):
    authorise(*MANUSCRIPT_READ_ROLES)
    manuscript = find_manuscript(mid)
    return object_response(ser.manuscript_out(manuscript), 200)


@bp.get("/manuscripts")
def list_manuscripts():
    authorise(*MANUSCRIPT_READ_ROLES)
    limit, offset = v.pagination()
    journal_id = v.query_str("journal_id")
    author_id = v.query_str("corresponding_author_id")
    supersedes_id = v.query_str("supersedes_manuscript_id")
    status = v.query_str("status")
    rows = []
    for manuscript in store.manuscripts.values():
        if journal_id is not None and manuscript["journal_id"] != journal_id:
            continue
        if author_id is not None and manuscript["corresponding_author_id"] != author_id:
            continue
        if supersedes_id is not None and manuscript["supersedes_manuscript_id"] != supersedes_id:
            continue
        if status is not None and manuscript["status"] != status:
            continue
        rows.append(manuscript)
    rows = ordered(rows)
    page = v.window(rows, limit, offset)
    return list_response(ser.many(page, ser.manuscript_out), limit, offset, len(rows))
