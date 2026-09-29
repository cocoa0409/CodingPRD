"""State central registry batches, edit resolution and late assessments."""

from flask import Blueprint

import calcs
import db
import services
import spec
import validate
from db import all_of, clock_now, fmt_date, fmt_instant, mark, parse_date, parse_instant
from errors import ApiError, invalid
from middleware import ANY_ROLE, endpoint
from routes.common import PREFIX, need, ok, page

bp = Blueprint("submissions", __name__)


def _outstanding(submission):
    return (submission["assessment_due_cents"]
            - submission["assessment_paid_cents"])


def _recount(submission):
    items = services.items_of_submission(submission["id"])
    mark(submission)
    submission["total_case_count"] = len(items)
    submission["accepted_item_count"] = len(
        [i for i in items if i["edit_status"] == "ACCEPTED"])
    submission["failed_item_count"] = len(
        [i for i in items if i["edit_status"] == "EDIT_FAILED"])
    codes = set()
    for item in items:
        for code in item.get("edit_codes") or []:
            codes.add(code)
    submission["edit_error_codes"] = sorted(codes)


def _compute_assessment(submission):
    items = services.items_of_submission(submission["id"])
    late = 0
    for item in items:
        case = db.get("case", item["case_id"])
        if case is None:
            continue
        completed = parse_date(case.get("completed_on"))
        due = parse_date(case.get("abstract_due_date"))
        if completed is not None and due is not None and completed > due:
            late += 1
    transmitted = parse_instant(submission.get("transmitted_at"))
    deadline = parse_date(submission.get("deadline_date"))
    transmitted_late = bool(transmitted is not None and deadline is not None
                            and transmitted.date() > deadline)
    _pre, relief, due_cents = calcs.assessment(late, transmitted_late)
    mark(submission)
    submission["late_case_count"] = late
    submission["relief_pct"] = relief
    submission["assessment_due_cents"] = due_cents


# ------------------------------------------------------------------ batches

@bp.post(PREFIX + "/submissions")
@endpoint(["RegistryManager"])
def create_submission():
    body = validate.body()
    program_id = validate.f_str(body, "program_id")
    period_start = validate.f_date(body, "period_start")
    period_end = validate.f_date(body, "period_end")
    deadline_date = validate.f_date(body, "deadline_date")
    if period_end < period_start:
        raise invalid("period_end must not precede period_start.")

    program = need("program", program_id, "ERR_PROGRAM_NOT_FOUND")

    for existing in services.submissions_of_program(program_id):
        other_start = parse_date(existing["period_start"])
        other_end = parse_date(existing["period_end"])
        if other_start <= period_end and other_end >= period_start:
            raise ApiError("ERR_SUBMISSION_PERIOD_OVERLAP")

    frozen = program["registry_posture"] == "FROZEN"
    submission = db.new_entity("submission", {
        "program_id": program_id,
        "period_start": fmt_date(period_start),
        "period_end": fmt_date(period_end),
        "deadline_date": fmt_date(deadline_date),
        "submission_state": "HOLD" if frozen else "DRAFT",
        "total_case_count": 0,
        "accepted_item_count": 0,
        "failed_item_count": 0,
        "edit_error_codes": [],
        "resubmission_round": 0,
        "transmitted_at": None,
        "late_case_count": 0,
        "relief_pct": 0.0,
        "assessment_due_cents": 0,
        "assessment_paid_cents": 0,
        "pre_hold_state": "DRAFT" if frozen else None,
    })
    return ok(submission, 201)


@bp.get(PREFIX + "/submissions")
@endpoint(ANY_ROLE)
def list_submissions():
    program_id = validate.q_str("program_id")
    submission_state = validate.q_enum("submission_state",
                                       spec.SUBMISSION_STATES)
    items = all_of("submission")
    if program_id is not None:
        items = [s for s in items if s["program_id"] == program_id]
    if submission_state is not None:
        items = [s for s in items if s["submission_state"] == submission_state]
    return page(items)


@bp.get(PREFIX + "/submissions/<submission_id>")
@endpoint(ANY_ROLE)
def read_submission(submission_id):
    submission = need("submission", submission_id, "ERR_SUBMISSION_NOT_FOUND")
    return ok(submission)


# -------------------------------------------------------------------- items

@bp.post(PREFIX + "/submissions/<submission_id>/items")
@endpoint(["RegistryManager", "RegistryAbstractor"])
def add_item(submission_id):
    body = validate.body()
    case_id = validate.f_str(body, "case_id")
    expected_submission_version = validate.f_int(body,
                                                 "expected_submission_version")

    submission = need("submission", submission_id, "ERR_SUBMISSION_NOT_FOUND")
    case = need("case", case_id, "ERR_CASE_NOT_FOUND")

    if expected_submission_version != submission["version"]:
        raise ApiError("ERR_STALE_SUBMISSION_VERSION")
    if submission["submission_state"] != "DRAFT":
        raise ApiError("ERR_SUBMISSION_NOT_DRAFT")
    if case["case_state"] != "COMPLETED":
        raise ApiError("ERR_CASE_NOT_COMPLETED")
    if case["submission_state"] != "NOT_SUBMITTED":
        raise ApiError("ERR_CASE_ALREADY_IN_SUBMISSION")
    if case["program_id"] != submission["program_id"]:
        raise ApiError("ERR_CASE_PROGRAM_MISMATCH")

    item = db.new_entity("item", {
        "submission_id": submission_id,
        "case_id": case_id,
        "edit_status": "PENDING",
        "edit_codes": [],
        "resolution_note": None,
    })
    mark(case)
    case["submission_state"] = "PENDING_SUBMISSION"
    _recount(submission)
    return ok(item, 201)


@bp.get(PREFIX + "/submission-items")
@endpoint(ANY_ROLE)
def list_items():
    submission_id = validate.q_str("submission_id")
    case_id = validate.q_str("case_id")
    edit_status = validate.q_enum("edit_status", spec.ITEM_EDIT_STATUSES)
    items = all_of("item")
    if submission_id is not None:
        items = [i for i in items if i["submission_id"] == submission_id]
    if case_id is not None:
        items = [i for i in items if i["case_id"] == case_id]
    if edit_status is not None:
        items = [i for i in items if i["edit_status"] == edit_status]
    return page(items)


@bp.get(PREFIX + "/submission-items/<item_id>")
@endpoint(ANY_ROLE)
def read_item(item_id):
    item = need("item", item_id, "ERR_SUBMISSION_ITEM_NOT_FOUND")
    return ok(item)


# ----------------------------------------------------------------- transmit

@bp.post(PREFIX + "/submissions/<submission_id>/transmit")
@endpoint(["RegistryManager"])
def transmit(submission_id):
    body = validate.body()
    validate.f_str(body, "transmit_note", required=False)

    submission = need("submission", submission_id, "ERR_SUBMISSION_NOT_FOUND")
    if submission["submission_state"] != "DRAFT":
        raise ApiError("ERR_SUBMISSION_NOT_DRAFT")
    program = db.get("program", submission["program_id"])
    if program is not None and program["registry_posture"] == "FROZEN":
        raise ApiError("ERR_REGISTRY_FROZEN")
    items = services.items_of_submission(submission_id)
    if not items:
        raise ApiError("ERR_SUBMISSION_EMPTY")
    for item in items:
        case = db.get("case", item["case_id"])
        if case is None or case["case_state"] != "COMPLETED":
            raise ApiError("ERR_CASE_NOT_COMPLETED")
    if _outstanding(submission) > 0:
        raise ApiError("ERR_ASSESSMENT_UNPAID")

    mark(submission)
    submission["submission_state"] = "TRANSMITTED"
    submission["transmitted_at"] = fmt_instant(clock_now())
    for item in items:
        case = db.get("case", item["case_id"])
        if case is not None and case["submission_state"] == "PENDING_SUBMISSION":
            mark(case)
            case["submission_state"] = "SUBMITTED"
    return ok(submission)


@bp.post(PREFIX + "/submissions/<submission_id>/edit-results")
@endpoint(["StateRegistryLiaison"])
def edit_results(submission_id):
    body = validate.body()
    raw = body.get("item_results")
    if raw is None:
        raise invalid("Field 'item_results' is required.")
    if not isinstance(raw, list):
        raise invalid("Field 'item_results' must be an array.")
    results = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise invalid("Each item_results entry must be an object.")
        case_id = validate.f_str(entry, "case_id")
        edit_status = validate.f_enum(entry, "edit_status",
                                      ("ACCEPTED", "EDIT_FAILED"))
        edit_codes = validate.f_str_list(entry, "edit_codes", required=False,
                                         default=[])
        results.append((case_id, edit_status, list(edit_codes)))

    submission = need("submission", submission_id, "ERR_SUBMISSION_NOT_FOUND")
    if submission["submission_state"] != "TRANSMITTED":
        raise ApiError("ERR_SUBMISSION_NOT_TRANSMITTED")

    items = services.items_of_submission(submission_id)
    by_case = {i["case_id"]: i for i in items}
    for case_id, _status, _codes in results:
        if case_id not in by_case:
            raise ApiError("ERR_SUBMISSION_ITEM_NOT_FOUND")
    covered = set(case_id for case_id, _s, _c in results)
    if covered != set(by_case.keys()):
        raise invalid("item_results must cover every item on the submission.")

    for case_id, status, codes in results:
        item = by_case[case_id]
        mark(item)
        item["edit_status"] = status
        item["edit_codes"] = codes
        case = db.get("case", case_id)
        if case is not None:
            mark(case)
            case["submission_state"] = ("ACCEPTED" if status == "ACCEPTED"
                                        else "EDIT_REJECTED")

    _recount(submission)
    mark(submission)
    if submission["failed_item_count"] == 0:
        submission["submission_state"] = "ACCEPTED"
    else:
        submission["submission_state"] = "EDITS_RETURNED"
    _compute_assessment(submission)
    return ok(submission)


@bp.post(PREFIX + "/submissions/<submission_id>/items/<item_id>/resolve")
@endpoint(["RegistryAbstractor", "RegistryManager"])
def resolve_item(submission_id, item_id):
    body = validate.body()
    resolution_note = validate.f_str(body, "resolution_note")

    submission = need("submission", submission_id, "ERR_SUBMISSION_NOT_FOUND")
    item = db.get("item", item_id)
    if item is None or item["submission_id"] != submission_id:
        raise ApiError("ERR_SUBMISSION_ITEM_NOT_FOUND")
    if item["edit_status"] != "EDIT_FAILED":
        raise ApiError("ERR_ITEM_NOT_FAILED")

    mark(item)
    item["edit_status"] = "RESOLVED"
    item["resolution_note"] = resolution_note
    _recount(submission)
    return ok(item)


@bp.post(PREFIX + "/submissions/<submission_id>/retransmit")
@endpoint(["RegistryManager"])
def retransmit(submission_id):
    body = validate.body()
    validate.f_str(body, "retransmit_note", required=False)

    submission = need("submission", submission_id, "ERR_SUBMISSION_NOT_FOUND")
    if submission["submission_state"] != "EDITS_RETURNED":
        raise ApiError("ERR_SUBMISSION_NOT_IN_EDIT_RESOLUTION")
    if submission["failed_item_count"] != 0:
        raise ApiError("ERR_UNRESOLVED_EDITS")
    if submission["resubmission_round"] >= spec.RESUBMISSION_ROUND_MAX:
        raise ApiError("ERR_RESUBMISSION_LIMIT_EXCEEDED")
    program = db.get("program", submission["program_id"])
    if program is not None and program["registry_posture"] == "FROZEN":
        raise ApiError("ERR_REGISTRY_FROZEN")
    if _outstanding(submission) > 0:
        raise ApiError("ERR_ASSESSMENT_UNPAID")

    mark(submission)
    submission["submission_state"] = "TRANSMITTED"
    submission["resubmission_round"] = submission["resubmission_round"] + 1
    submission["transmitted_at"] = fmt_instant(clock_now())
    for item in services.items_of_submission(submission_id):
        if item["edit_status"] != "RESOLVED":
            continue
        mark(item)
        item["edit_status"] = "PENDING"
        case = db.get("case", item["case_id"])
        if case is not None and case["submission_state"] == "EDIT_REJECTED":
            mark(case)
            case["submission_state"] = "SUBMITTED"
    _recount(submission)
    return ok(submission)


@bp.post(PREFIX + "/submissions/<submission_id>/assessment-payments")
@endpoint(["RegistryManager", "PlatformAdmin"])
def assessment_payment(submission_id):
    body = validate.body()
    amount_cents = validate.f_int(body, "amount_cents", minimum=1)

    submission = need("submission", submission_id, "ERR_SUBMISSION_NOT_FOUND")
    if amount_cents > _outstanding(submission):
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE")

    mark(submission)
    submission["assessment_paid_cents"] = (
        submission["assessment_paid_cents"] + amount_cents)
    return ok(submission)
