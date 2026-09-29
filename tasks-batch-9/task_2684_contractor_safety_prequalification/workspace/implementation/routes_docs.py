"""Written safety programs: tender, review and re-tender."""
from flask import Blueprint

import auth
import calc
import cascade
import derive
import response
import serialize
import store
import validators as V
from errors import fail
from store import S, insert, now, touch

bp = Blueprint("docs", __name__)


@bp.route("/prequalifications/<prequalification_id>/written-programs", methods=["POST"])
def create_written_program(prequalification_id):
    user_id, role = auth.authenticate([auth.ROLE_CONTRACTOR_ADMIN])
    body = V.parse_body(
        [
            ("prequalification_id", "string", False),
            ("program_type", "string", True),
            ("revision_date", "string", True),
            ("document_ref", "string", True),
        ]
    )
    program_type = V.check_enum("program_type", body["program_type"], calc.PROGRAM_TYPES)
    revision_date = V.parse_instant("revision_date", body["revision_date"])
    document_ref = V.check_str_len("document_ref", body["document_ref"], 1, 120)
    if revision_date > now():
        fail("ERR_INVALID_FIELD_VALUE", "revision_date may not be in the future.")

    preq = V.get_prequalification(prequalification_id)
    auth.check_owner(role, user_id, contractor_id=preq["contractor_id"])

    if preq["status"] not in ("DRAFT", "SUBMITTED"):
        fail(
            "ERR_TRANSITION_NOT_ALLOWED",
            "Documents may only be tendered while the row is DRAFT or SUBMITTED.",
        )

    for existing in derive.programs_of(preq["id"]):
        if existing["program_type"] == program_type:
            fail("ERR_INVALID_FIELD_VALUE", "That program_type is already present.")

    row = store.base_row()
    row.update(
        {
            "prequalification_id": preq["id"],
            "program_type": program_type,
            "revision_date": revision_date,
            "document_ref": document_ref,
            "review_status": "SUBMITTED",
            "reviewer_note": None,
            "reviewed_by_user_id": None,
        }
    )
    insert(S.written_programs, row)
    return response.created(serialize.written_program(row))


@bp.route("/written-programs/<program_id>/review", methods=["POST"])
def review_written_program(program_id):
    user_id, role = auth.authenticate([auth.ROLE_CLIENT_SAFETY_MANAGER])
    body = V.parse_body(
        [("decision", "string", True), ("reviewer_note", "string", False)]
    )
    decision = V.check_enum("decision", body["decision"], ("ACCEPT", "WAIVE", "DEFICIENT"))

    row = V.get_leaf(S.written_programs, program_id)
    preq = S.prequalifications[row["prequalification_id"]]
    auth.check_owner(role, user_id, client_id=preq["client_id"])

    if row["review_status"] != "SUBMITTED":
        fail("ERR_TRANSITION_NOT_ALLOWED", "Only a SUBMITTED document may be reviewed.")

    row["review_status"] = {
        "ACCEPT": "ACCEPTED",
        "WAIVE": "WAIVED",
        "DEFICIENT": "DEFICIENT",
    }[decision]
    row["reviewer_note"] = body["reviewer_note"]
    row["reviewed_by_user_id"] = user_id
    touch(row)

    cascade.evaluate_join(preq)
    return response.ok(serialize.written_program(row))


@bp.route("/written-programs/<program_id>/resubmit", methods=["POST"])
def resubmit_written_program(program_id):
    user_id, role = auth.authenticate([auth.ROLE_CONTRACTOR_ADMIN])
    body = V.parse_body(
        [("document_ref", "string", True), ("revision_date", "string", True)]
    )
    document_ref = V.check_str_len("document_ref", body["document_ref"], 1, 120)
    revision_date = V.parse_instant("revision_date", body["revision_date"])
    if revision_date > now():
        fail("ERR_INVALID_FIELD_VALUE", "revision_date may not be in the future.")

    row = V.get_leaf(S.written_programs, program_id)
    preq = S.prequalifications[row["prequalification_id"]]
    auth.check_owner(role, user_id, contractor_id=preq["contractor_id"])

    if row["review_status"] != "DEFICIENT":
        fail("ERR_TRANSITION_NOT_ALLOWED", "Only a DEFICIENT document may be re-tendered.")

    row["document_ref"] = document_ref
    row["revision_date"] = revision_date
    row["review_status"] = "SUBMITTED"
    row["reviewer_note"] = None
    row["reviewed_by_user_id"] = None
    touch(row)

    cascade.evaluate_join(preq)
    return response.ok(serialize.written_program(row))
