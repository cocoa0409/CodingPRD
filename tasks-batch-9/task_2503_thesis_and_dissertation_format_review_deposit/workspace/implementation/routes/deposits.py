"""Repository deposit, handle assignment and fee settlement (PRD section 3.8)."""

import lookup
import serializers
import validate
from db import db, new_row, write
from errors import fail
from flask import Blueprint
from logical_clock import clock
from middleware import endpoint
from response import object_response
from routes import common
from routes.common import PREFIX
from services import calc
from services.clearance import recompute_for_thesis

bp = Blueprint("deposits", __name__, url_prefix=PREFIX)

ACCESS_LEVELS = ("OPEN_ACCESS", "CAMPUS_ONLY", "EMBARGOED")


def _next_handle_sequence(term_id, new_row_key):
    """Sequence over DEPOSITED rows of the same term, created_at asc, version asc."""
    keys = []
    for deposit in db.repository_deposits.values():
        if deposit["status"] != "DEPOSITED":
            continue
        thesis = db.theses.get(deposit["thesis_id"])
        if thesis is None or thesis["term_id"] != term_id:
            continue
        keys.append((deposit["created_at"], deposit["version"], deposit["_seq"]))
    return sum(1 for key in keys if key < new_row_key) + 1


@bp.post("/repository-deposits")
@endpoint(["GradSchoolAnalyst"])
def create_deposit(user_id, role):
    body = validate.get_body()
    thesis_id = validate.req_str(body, "thesis_id")
    abstract_word_count = validate.req_int(body, "abstract_word_count", minimum=0)
    subject_keywords = validate.req_str_list(body, "subject_keywords")
    late_fee_paid_cents = validate.req_int(body, "late_fee_paid_cents", minimum=0)
    requested_access_level = validate.opt_enum(
        body, "requested_access_level", ACCESS_LEVELS, default="OPEN_ACCESS"
    )
    advisor_name = validate.opt_str(body, "advisor_name")
    department_code = validate.opt_str(body, "department_code")

    thesis = lookup.get_thesis(thesis_id)
    term = common.require_term_open(thesis)

    if thesis["workflow_state"] != "FORMAT_ACCEPTED":
        fail(
            "ERR_THESIS_STATE_INVALID",
            "Only a FORMAT_ACCEPTED document may be deposited",
        )

    # Stage 12.
    if thesis["integrity_state"] == "NOT_SCREENED":
        fail("ERR_SCREENING_REQUIRED", "The document has not been screened")
    if thesis["integrity_state"] in common.INTEGRITY_HOLD_STATES:
        fail("ERR_INTEGRITY_HOLD_ACTIVE", "An integrity hold is active on the document")

    # Stage 13: the accepting analyst may not also deposit.
    accepted = common.accepted_format_review(thesis)
    if accepted is not None and accepted["decided_by_user_id"] == user_id:
        fail(
            "ERR_DUTY_SEGREGATION_VIOLATION",
            "The analyst who accepted the format review may not perform the deposit",
        )

    # Stage 16, in the declared order.
    if not common.permissions_complete(thesis):
        fail(
            "ERR_PERMISSIONS_INCOMPLETE",
            "The third-party permission dossier is not complete",
        )
    if common.embargo_undecided(thesis):
        fail(
            "ERR_EMBARGO_UNDECIDED",
            "An embargo request for the document is still undecided",
        )
    if any(
        row["status"] == "DEPOSITED" for row in lookup.deposits_of_thesis(thesis["id"])
    ):
        fail("ERR_DEPOSIT_ALREADY_EXISTS", "The document has already been deposited")

    score = calc.metadata_completeness_score(
        abstract_word_count, subject_keywords, advisor_name, department_code
    )
    if score < calc.METADATA_MIN_SCORE:
        fail(
            "ERR_METADATA_INCOMPLETE",
            "The metadata completeness score of %s is below the required %s"
            % (score, calc.METADATA_MIN_SCORE),
        )

    now = clock.now()
    computed_fee = calc.deposit_late_fee_cents(thesis, term, now) if term else 0
    if late_fee_paid_cents != computed_fee:
        fail(
            "ERR_LATE_FEE_MISMATCH",
            "The tendered %d cents does not equal the computed late fee of %d cents"
            % (late_fee_paid_cents, computed_fee),
        )

    governing = calc.governing_embargo_request(thesis["id"])
    access_level = "EMBARGOED" if governing is not None else requested_access_level

    release_date = None
    if access_level == "EMBARGOED" and governing is not None and term is not None:
        release_date, release_anchor = calc.embargo_release_date(governing, now, term)
        write(governing, release_date=release_date, release_anchor=release_anchor)

    row = new_row(
        thesis_id=thesis["id"],
        handle=None,
        abstract_word_count=abstract_word_count,
        subject_keywords=subject_keywords,
        advisor_name=advisor_name,
        department_code=department_code,
        metadata_completeness_score=score,
        access_level=access_level,
        embargo_release_date=release_date,
        deposited_at=now,
        depositor_user_id=user_id,
        late_fee_cents=computed_fee,
        status="DEPOSITED",
    )

    sequence = _next_handle_sequence(
        thesis["term_id"], (row["created_at"], row["version"], row["_seq"])
    )
    code = term["code"] if term is not None else ""
    row["handle"] = "%s/%05d" % (code, sequence)

    db.repository_deposits[row["id"]] = row

    write(thesis, workflow_state="DEPOSITED")
    recompute_for_thesis(thesis)

    return object_response(serializers.repository_deposit(row), 201)
