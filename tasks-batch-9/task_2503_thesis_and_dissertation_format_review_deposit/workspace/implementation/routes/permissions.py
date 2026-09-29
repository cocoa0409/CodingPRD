"""The third-party permission dossier (PRD section 3.5)."""

import lookup
import serializers
import validate
from db import db, new_row, write
from errors import fail
from flask import Blueprint
from middleware import endpoint
from response import object_response
from routes import common
from routes.common import PREFIX
from services import calc, counters
from services.clearance import recompute_for_thesis

bp = Blueprint("permissions", __name__, url_prefix=PREFIX)

MATERIAL_TYPES = (
    "FIGURE",
    "TABLE",
    "EXCERPT",
    "PREVIOUSLY_PUBLISHED_CHAPTER",
    "DATASET",
)

RIGHTS_BASES = (
    "WRITTEN_PERMISSION",
    "FAIR_USE_ASSERTION",
    "PUBLIC_DOMAIN",
    "OPEN_LICENSE",
)

REVIEW_DECISIONS = ("ACCEPT", "DEFICIENT", "WAIVE")

BLOCKED_THESIS_STATES = ("DEFENSE_FAILED", "DEPOSITED", "CONFERRED", "TERMINATED")


@bp.post("/permission-records")
@endpoint(["Student"])
def create_permission_record(user_id, role):
    body = validate.get_body()
    thesis_id = validate.req_str(body, "thesis_id")
    material_type = validate.req_enum(body, "material_type", MATERIAL_TYPES)
    rights_basis = validate.req_enum(body, "rights_basis", RIGHTS_BASES)
    page_reference = validate.req_str(body, "page_reference")
    expected_version = validate.req_int(body, "expected_thesis_version", minimum=1)
    excerpt_word_count = validate.opt_int(
        body, "excerpt_word_count", default=0, minimum=0
    )
    document_uri = validate.opt_str(body, "document_uri")

    thesis = lookup.get_thesis(thesis_id)
    common.require_owner(role, user_id, thesis)
    common.require_thesis_version(thesis, expected_version)
    common.require_term_open(thesis)

    if thesis["workflow_state"] in BLOCKED_THESIS_STATES:
        fail(
            "ERR_THESIS_STATE_INVALID",
            "Third-party material cannot be documented while the document is '%s'"
            % thesis["workflow_state"],
        )

    if rights_basis == "WRITTEN_PERMISSION" and not document_uri:
        fail(
            "ERR_PERMISSION_EVIDENCE_MISSING",
            "A WRITTEN_PERMISSION basis requires a non-empty document_uri",
        )
    if (
        rights_basis == "FAIR_USE_ASSERTION"
        and excerpt_word_count > calc.FAIR_USE_MAX_WORDS
    ):
        fail(
            "ERR_FAIR_USE_LIMIT_EXCEEDED",
            "A fair-use assertion may not reuse more than %d words"
            % calc.FAIR_USE_MAX_WORDS,
        )

    row = new_row(
        thesis_id=thesis["id"],
        material_type=material_type,
        rights_basis=rights_basis,
        page_reference=page_reference,
        excerpt_word_count=excerpt_word_count,
        document_uri=document_uri,
        status="SUBMITTED",
        reviewed_by_user_id=None,
        review_note=None,
    )
    db.permission_records[row["id"]] = row

    values = counters.thesis_counter_values(thesis)
    write(
        thesis,
        documented_permission_count=values["documented_permission_count"],
    )
    recompute_for_thesis(thesis)

    return object_response(serializers.permission_record(row), 201)


@bp.post("/permission-records/<record_id>/review")
@endpoint(["GradSchoolAnalyst"])
def review_permission_record(user_id, role, record_id):
    record = lookup.get_permission_record(record_id)
    body = validate.get_body()
    decision = validate.req_enum(body, "decision", REVIEW_DECISIONS)
    review_note = validate.opt_str(body, "review_note")

    thesis = db.theses.get(record["thesis_id"])
    if thesis is not None:
        common.require_term_open(thesis)

    if decision == "DEFICIENT":
        allowed = ("SUBMITTED",)
    else:
        allowed = ("SUBMITTED", "DEFICIENT")
    if record["status"] not in allowed:
        fail(
            "ERR_PERMISSION_RECORD_STATE_INVALID",
            "A %s decision is not legal from status '%s'" % (decision, record["status"]),
        )

    new_status = {"ACCEPT": "ACCEPTED", "DEFICIENT": "DEFICIENT", "WAIVE": "WAIVED"}[
        decision
    ]
    write(
        record,
        status=new_status,
        reviewed_by_user_id=user_id,
        review_note=review_note,
    )

    if thesis is not None:
        counters.sync_thesis_counters(thesis)
        recompute_for_thesis(thesis)
    return object_response(serializers.permission_record(record))
