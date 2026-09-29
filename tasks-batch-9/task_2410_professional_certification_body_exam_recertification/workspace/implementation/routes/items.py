"""Item endpoints: authoring, peer review, statistics, retirement (PRD 3.2-3.4)."""

from flask import Blueprint

import serialize
from db import DB, mark_created, new_record, ordered, touch
from dispatch import api
from errors import ApiError
from middleware import (
    ROLE_ITEM_SPECIALIST,
    ROLE_PROGRAM_ADMIN,
    ROLE_PSYCHOMETRICIAN,
    authenticate,
    ensure_body,
    opt_str,
    peek_body,
    req_bool,
    req_enum,
    req_int,
    req_str,
)
from response import apply_filters, created_response, object_response, paginate, read_pagination
from services import calc, cascades, derive, lookup

bp = Blueprint("items", __name__)

COGNITIVE_LEVELS = ("RECALL", "APPLICATION", "ANALYSIS")
REVIEW_DECISIONS = ("APPROVE", "REVISE", "REJECT")
RETIREMENT_REASONS = ("PSYCHOMETRIC", "CONTENT_OBSOLETE", "EXPOSED", "PRETEST_FAILED")
STATS_ELIGIBLE_STATUSES = ("APPROVED", "PRETEST", "OPERATIONAL", "FLAGGED")

PRETEST_ACCUMULATORS = (
    ("response_count", "pretest_response_count"),
    ("correct_count", "pretest_correct_count"),
    ("upper_n", "pretest_upper_n"),
    ("upper_correct", "pretest_upper_correct"),
    ("lower_n", "pretest_lower_n"),
    ("lower_correct", "pretest_lower_correct"),
)
OPERATIONAL_ACCUMULATORS = (
    ("response_count", "operational_response_count"),
    ("correct_count", "operational_correct_count"),
    ("upper_n", "operational_upper_n"),
    ("upper_correct", "operational_upper_correct"),
    ("lower_n", "operational_lower_n"),
    ("lower_correct", "operational_lower_correct"),
)

ZERO_ACCUMULATORS = {
    "pretest_response_count": 0,
    "pretest_correct_count": 0,
    "pretest_upper_n": 0,
    "pretest_upper_correct": 0,
    "pretest_lower_n": 0,
    "pretest_lower_correct": 0,
    "operational_response_count": 0,
    "operational_correct_count": 0,
    "operational_upper_n": 0,
    "operational_upper_correct": 0,
    "operational_lower_n": 0,
    "operational_lower_correct": 0,
}


def _recompute_statistics(item, program):
    basis, p_value, discrimination = calc.item_statistics(item, program)
    item["stat_basis_applied"] = basis
    item["p_value"] = p_value
    item["discrimination_index"] = discrimination
    item["flag_reason"] = calc.item_flag_evaluation(program, basis, p_value, discrimination)


@bp.post("/items")
@api
def create_item():
    actor = authenticate([ROLE_ITEM_SPECIALIST])
    body = peek_body()

    # Layer 4: the foreign identifier in the body resolves before schema checks.
    program = lookup.program((body or {}).get("program_id"))

    body = ensure_body(body)
    domain_code = req_str(body, "domain_code")
    cognitive_level = req_enum(body, "cognitive_level", COGNITIVE_LEVELS)
    stem = req_str(body, "stem")

    known_domains = [spec["domain_code"] for spec in program["domain_specs"]]
    if domain_code not in known_domains:
        raise ApiError("ERR_ITEM_DOMAIN_MISMATCH")

    item = new_record(
        program_id=program["id"],
        domain_code=domain_code,
        cognitive_level=cognitive_level,
        stem=stem,
        author_user_id=actor.user_id,
        approver_user_ids=[],
        review_round=1,
        status="DRAFT",
        p_value=None,
        discrimination_index=None,
        stat_basis_applied="INSUFFICIENT_DATA",
        flag_reason=None,
        retirement_reason=None,
        retired_at=None,
        **dict(ZERO_ACCUMULATORS)
    )
    mark_created(item)
    DB.items[item["id"]] = item
    return created_response(serialize.item(item))


@bp.get("/items/<item_id>")
@api
def read_item(item_id):
    authenticate([ROLE_ITEM_SPECIALIST, ROLE_PSYCHOMETRICIAN, ROLE_PROGRAM_ADMIN])
    return object_response(serialize.item(lookup.item(item_id)))


@bp.get("/items")
@api
def list_items():
    authenticate([ROLE_ITEM_SPECIALIST, ROLE_PSYCHOMETRICIAN, ROLE_PROGRAM_ADMIN])
    limit, offset = read_pagination()
    rows = ordered(DB.items.values())
    rows = apply_filters(rows, {
        "program_id": "program_id",
        "domain_code": "domain_code",
        "status": "status",
        "flag_reason": "flag_reason",
    })
    return paginate(rows, serialize.item, limit, offset)


@bp.post("/items/<item_id>/submit-for-review")
@api
def submit_item_for_review(item_id):
    actor = authenticate([ROLE_ITEM_SPECIALIST])
    item = lookup.item(item_id)
    body = ensure_body(peek_body())
    opt_str(body, "revision_note")

    if item["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE")
    # Layer 19: submission is reserved to the item's own author.
    if actor.user_id != item["author_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if item["status"] == "REVISION_REQUESTED":
        item["review_round"] += 1
    item["approver_user_ids"] = []
    item["status"] = "IN_REVIEW"
    touch(item)
    return object_response(serialize.item(item))


@bp.post("/items/<item_id>/review")
@api
def review_item(item_id):
    actor = authenticate([ROLE_ITEM_SPECIALIST])
    item = lookup.item(item_id)
    body = ensure_body(peek_body())
    decision = req_enum(body, "decision", REVIEW_DECISIONS)
    opt_str(body, "review_note")

    if item["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE")
    if actor.user_id == item["author_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if decision == "APPROVE" and actor.user_id in item["approver_user_ids"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if decision == "APPROVE":
        item["approver_user_ids"] = item["approver_user_ids"] + [actor.user_id]
        if len(item["approver_user_ids"]) >= 2:
            item["status"] = "APPROVED"
    elif decision == "REVISE":
        item["approver_user_ids"] = []
        item["status"] = "REVISION_REQUESTED"
    else:
        item["status"] = "REJECTED"
    touch(item)
    return object_response(serialize.item(item))


@bp.post("/items/<item_id>/response-batches")
@api
def ingest_response_batch(item_id):
    authenticate([ROLE_PSYCHOMETRICIAN])
    item = lookup.item(item_id)
    body = ensure_body(peek_body())
    is_pretest = req_bool(body, "is_pretest")
    counts = {
        name: req_int(body, name, minimum=0)
        for name in ("response_count", "correct_count", "upper_n", "upper_correct",
                     "lower_n", "lower_correct")
    }

    # Layer 42: statistics may only be ingested against a settled item.
    if item["status"] not in STATS_ELIGIBLE_STATUSES:
        raise ApiError("ERR_ITEM_NOT_ELIGIBLE_FOR_STATS")

    program = DB.programs[item["program_id"]]
    mapping = PRETEST_ACCUMULATORS if is_pretest else OPERATIONAL_ACCUMULATORS
    for source, target in mapping:
        item[target] += counts[source]

    _recompute_statistics(item, program)

    was_operational = item["status"] == "OPERATIONAL"
    sufficient = item["stat_basis_applied"] != "INSUFFICIENT_DATA"
    flag = item["flag_reason"]

    if item["status"] == "APPROVED" and is_pretest:
        item["status"] = "PRETEST"

    if item["status"] == "PRETEST" and sufficient:
        if flag is None:
            item["status"] = "OPERATIONAL"
        else:
            item["status"] = "RETIRED"
            item["retirement_reason"] = "PRETEST_FAILED"
            item["retired_at"] = DB.now()
    elif item["status"] == "OPERATIONAL" and sufficient and flag is not None:
        item["status"] = "FLAGGED"
    elif item["status"] == "FLAGGED" and sufficient and flag is None:
        item["status"] = "OPERATIONAL"

    touch(item)

    if was_operational != (item["status"] == "OPERATIONAL"):
        derive.recompute_blueprint_posture(program)
    return object_response(serialize.item(item))


@bp.post("/items/<item_id>/retire")
@api
def retire_item(item_id):
    authenticate([ROLE_PSYCHOMETRICIAN])
    item = lookup.item(item_id)
    body = ensure_body(peek_body())
    reason = req_enum(body, "retirement_reason", RETIREMENT_REASONS)

    if item["status"] not in ("OPERATIONAL", "FLAGGED"):
        raise ApiError("ERR_INVALID_STATE")

    item["status"] = "RETIRED"
    item["retirement_reason"] = reason
    item["retired_at"] = DB.now()
    touch(item)

    cascades.cascade_item_retired(item)
    return object_response(serialize.item(item))
