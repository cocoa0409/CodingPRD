"""Solicitations, requirements, addenda, questions and the lifecycle
transitions of PRD §3.2, §3.3, §3.4 and §3.8."""

from flask import Blueprint, g

import calc
import serializers
import services
import store
import validation as v
from errors import ApiError
from util import add_days

bp = Blueprint("solicitations", __name__)

MATERIALITY = ("MATERIAL", "INFORMALITY")
PROTESTABLE_STATUSES = (
    "ISSUED", "QUESTION_PERIOD_CLOSED", "BIDS_OPENED", "EVALUATION",
    "AWARD_PENDING", "AWARDED",
)
CANCELLABLE_STATUSES = (
    "ISSUED", "QUESTION_PERIOD_CLOSED", "BIDS_OPENED", "EVALUATION", "AWARD_PENDING",
)


def _requirement_defs(items, field):
    """Validate a list of requirement definitions."""
    out = []
    for entry in items:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", "each '%s' entry must be an object" % field)
        out.append({
            "requirement_code": v.req_str(entry, "requirement_code"),
            "description": v.req_str(entry, "description"),
            "materiality": v.req_enum(entry, "materiality", MATERIALITY),
            "is_waivable": v.opt_bool(entry, "is_waivable", False),
        })
    return out


def _create_requirement(solicitation, definition, sequence):
    return store.insert("requirements", store.row("requirements", {
        "solicitation_id": solicitation["id"],
        "requirement_code": definition["requirement_code"],
        "description": definition["description"],
        "materiality": definition["materiality"],
        "is_waivable": definition["is_waivable"],
        "introduced_by_addendum_sequence": sequence,
    }, versioned=False))


# --------------------------------------------------------------------------- #
# drafting, reading and advertising
# --------------------------------------------------------------------------- #

@bp.post("/procurement/solicitations")
@v.endpoint(["ProcurementOfficer"])
def draft_solicitation():
    data = v.body()
    solicitation_number = v.req_str(data, "solicitation_number")
    title = v.req_str(data, "title")
    issuing_agency_code = v.req_str(data, "issuing_agency_code")
    estimated_value_cents = v.req_int(data, "estimated_value_cents", minimum=1)
    original_bid_due_utc = v.req_dt(data, "original_bid_due_utc")
    original_question_deadline_utc = v.req_dt(data, "original_question_deadline_utc")
    if not original_question_deadline_utc < original_bid_due_utc:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "'original_question_deadline_utc' must be strictly before 'original_bid_due_utc'",
        )
    requirement_defs = _requirement_defs(
        v.req_array(data, "mandatory_requirements", non_empty=False), "mandatory_requirements"
    )
    predecessor_id = v.opt_str(data, "predecessor_solicitation_id")

    predecessor = None
    if predecessor_id is not None:
        predecessor = services.must("solicitations", predecessor_id)

    for existing in store.values("solicitations"):
        if existing["solicitation_number"] == solicitation_number:
            raise ApiError("ERR_DUPLICATE_SOLICITATION_NUMBER")

    codes = [d["requirement_code"] for d in requirement_defs]
    if len(set(codes)) != len(codes):
        raise ApiError("ERR_DUPLICATE_REQUIREMENT_CODE")

    solicitation = store.insert("solicitations", store.row("solicitations", {
        "solicitation_number": solicitation_number,
        "title": title,
        "issuing_agency_code": issuing_agency_code,
        "estimated_value_cents": estimated_value_cents,
        "original_bid_due_utc": original_bid_due_utc,
        "effective_bid_due_utc": None,
        "original_question_deadline_utc": original_question_deadline_utc,
        "question_deadline_utc": None,
        "status": "DRAFT",
        "issued_by_user_id": None,
        "bids_opened_at_utc": None,
        "cumulative_extension_days": 0,
        "addendum_count": 0,
        "apparent_low_bid_id": None,
        "protest_escrow_cents": 0,
        "predecessor_solicitation_id": predecessor["id"] if predecessor else None,
    }))
    for definition in requirement_defs:
        _create_requirement(solicitation, definition, 0)
    return ("obj", solicitation, serializers.solicitation, 201)


@bp.get("/procurement/solicitations/<solicitation_id>")
@v.endpoint(v.ALL_ROLES)
def read_solicitation(solicitation_id):
    return ("obj", services.must("solicitations", solicitation_id),
            serializers.solicitation, 200)


@bp.get("/procurement/solicitations")
@v.endpoint(v.ALL_ROLES)
def list_solicitations():
    limit, offset = v.pagination()
    filters = {
        "status": v.query("status"),
        "issuing_agency_code": v.query("issuing_agency_code"),
        "predecessor_solicitation_id": v.query("predecessor_solicitation_id"),
        "apparent_low_bid_id": v.query("apparent_low_bid_id"),
    }
    rows = [r for r in store.ordered(store.values("solicitations")) if v.match_filters(r, filters)]
    page, total = v.paginate(rows, limit, offset)
    return ("list", page, serializers.solicitation, limit, offset, total)


@bp.post("/procurement/solicitations/<solicitation_id>/issue")
@v.endpoint(["ProcurementOfficer"])
def issue_solicitation(solicitation_id):
    solicitation = services.must("solicitations", solicitation_id)
    if solicitation["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_SOLICITATION_STATE")
    if not solicitation["original_question_deadline_utc"] > store.now():
        raise ApiError(
            "ERR_INVALID_SOLICITATION_STATE",
            "the advertised question deadline has already expired",
        )
    if not services.requirements_of(solicitation):
        raise ApiError("ERR_NO_MANDATORY_REQUIREMENTS")

    v.set_field(solicitation, "issued_by_user_id", g.user_id)
    v.set_field(solicitation, "effective_bid_due_utc", solicitation["original_bid_due_utc"])
    v.set_field(solicitation, "cumulative_extension_days", 0)
    v.set_field(solicitation, "question_deadline_utc",
                solicitation["original_question_deadline_utc"])
    v.set_field(solicitation, "status", "ISSUED")
    v.touch(solicitation)
    return ("obj", solicitation, serializers.solicitation, 200)


# --------------------------------------------------------------------------- #
# addenda
# --------------------------------------------------------------------------- #

@bp.post("/procurement/solicitations/<solicitation_id>/addenda")
@v.endpoint(["ProcurementOfficer"])
def issue_addendum(solicitation_id):
    data = v.body()
    summary = v.req_str(data, "summary")
    extends_days = v.opt_int(data, "extends_bid_due_by_days", default=0, minimum=0, maximum=21)
    acknowledgment_required = v.opt_bool(data, "acknowledgment_required", True)
    requirement_defs = _requirement_defs(
        v.opt_array(data, "new_requirement_codes", default=[]), "new_requirement_codes"
    )
    question_ids = v.str_array(data, "answers_question_ids", default=[])

    solicitation = services.must("solicitations", solicitation_id)
    questions = [services.must("questions", qid) for qid in question_ids]

    new_codes = [d["requirement_code"] for d in requirement_defs]
    existing_codes = [r["requirement_code"] for r in services.requirements_of(solicitation)]
    if len(set(new_codes)) != len(new_codes):
        raise ApiError("ERR_DUPLICATE_REQUIREMENT_CODE")
    for code in new_codes:
        if code in existing_codes:
            raise ApiError("ERR_DUPLICATE_REQUIREMENT_CODE")

    if solicitation["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_SOLICITATION_STATE")

    if solicitation["cumulative_extension_days"] + extends_days > calc.MAX_CUMULATIVE_EXTENSION_DAYS:
        raise ApiError("ERR_EXTENSION_CAP_EXCEEDED")

    for question in questions:
        if question["solicitation_id"] != solicitation["id"]:
            raise ApiError("ERR_QUESTION_NOT_ON_SOLICITATION")

    sequence = solicitation["addendum_count"] + 1
    addendum = store.insert("addenda", store.row("addenda", {
        "solicitation_id": solicitation["id"],
        "sequence_number": sequence,
        "summary": summary,
        "extends_bid_due_by_days": extends_days,
        "acknowledgment_required": acknowledgment_required,
        "adds_material_requirement": any(d["materiality"] == "MATERIAL" for d in requirement_defs),
        "new_requirement_codes": requirement_defs,
        "issued_at_utc": store.now(),
    }, versioned=False))

    for definition in requirement_defs:
        _create_requirement(solicitation, definition, sequence)

    for question in questions:
        if question["status"] == "PENDING":
            question["status"] = "ANSWERED"
            question["answer_summary"] = summary
            question["answered_via_addendum_sequence"] = sequence

    total_days = services.recompute_addendum_aggregates(solicitation)
    v.set_field(solicitation, "effective_bid_due_utc",
                add_days(solicitation["original_bid_due_utc"], total_days))
    if solicitation["status"] == "ISSUED" and extends_days > 0:
        v.set_field(solicitation, "question_deadline_utc",
                    calc.question_deadline_from(solicitation["effective_bid_due_utc"]))
    v.touch(solicitation)
    return ("obj", addendum, serializers.addendum, 201)


@bp.get("/procurement/solicitations/<solicitation_id>/addenda")
@v.endpoint(v.ALL_ROLES)
def list_addenda(solicitation_id):
    limit, offset = v.pagination()
    solicitation = services.must("solicitations", solicitation_id)
    rows = services.addenda_of(solicitation)
    page, total = v.paginate(rows, limit, offset)
    return ("list", page, serializers.addendum, limit, offset, total)


@bp.get("/procurement/solicitations/<solicitation_id>/requirements")
@v.endpoint(v.ALL_ROLES)
def list_requirements(solicitation_id):
    limit, offset = v.pagination()
    solicitation = services.must("solicitations", solicitation_id)
    materiality = v.query("materiality")
    rows = [
        r for r in services.requirements_of(solicitation)
        if materiality is None or r["materiality"] == materiality
    ]
    page, total = v.paginate(rows, limit, offset)
    return ("list", page, serializers.requirement, limit, offset, total)


# --------------------------------------------------------------------------- #
# questions
# --------------------------------------------------------------------------- #

@bp.post("/procurement/solicitations/<solicitation_id>/questions")
@v.endpoint(["Vendor"])
def submit_question(solicitation_id):
    data = v.body()
    vendor_id = v.req_str(data, "vendor_id")
    question_text = v.req_str(data, "question_text")

    solicitation = services.must("solicitations", solicitation_id)
    vendor = services.must("vendors", vendor_id)
    if g.user_id != vendor["id"]:
        raise ApiError("ERR_VENDOR_IDENTITY_MISMATCH")

    if solicitation["status"] != "ISSUED":
        raise ApiError("ERR_QUESTION_PERIOD_CLOSED")

    deadline = solicitation["question_deadline_utc"]
    status = "PENDING"
    if deadline is not None and store.now() > deadline:
        status = "REJECTED_LATE"

    question = store.insert("questions", store.row("questions", {
        "solicitation_id": solicitation["id"],
        "vendor_id": vendor["id"],
        "question_text": question_text,
        "submitted_at_utc": store.now(),
        "status": status,
        "answer_summary": None,
        "answered_via_addendum_sequence": None,
    }, versioned=False))
    return ("obj", question, serializers.question, 201)


@bp.get("/procurement/solicitations/<solicitation_id>/questions")
@v.endpoint(v.ALL_ROLES)
def list_questions(solicitation_id):
    limit, offset = v.pagination()
    solicitation = services.must("solicitations", solicitation_id)
    status = v.query("status")
    rows = [
        q for q in services.questions_of(solicitation)
        if status is None or q["status"] == status
    ]
    page, total = v.paginate(rows, limit, offset)
    return ("list", page, serializers.question, limit, offset, total)


# --------------------------------------------------------------------------- #
# closing the question period, opening bids, cancelling, resoliciting
# --------------------------------------------------------------------------- #

@bp.post("/procurement/solicitations/<solicitation_id>/close-question-period")
@v.endpoint(["ProcurementOfficer"])
def close_question_period(solicitation_id):
    solicitation = services.must("solicitations", solicitation_id)
    if solicitation["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_SOLICITATION_STATE")
    if store.now() < solicitation["question_deadline_utc"]:
        raise ApiError("ERR_QUESTION_PERIOD_OPEN")
    v.set_field(solicitation, "status", "QUESTION_PERIOD_CLOSED")
    v.touch(solicitation)
    return ("obj", solicitation, serializers.solicitation, 200)


@bp.post("/procurement/solicitations/<solicitation_id>/open-bids")
@v.endpoint(["ProcurementOfficer"])
def open_bids(solicitation_id):
    solicitation = services.must("solicitations", solicitation_id)
    if solicitation["status"] != "QUESTION_PERIOD_CLOSED":
        raise ApiError("ERR_INVALID_SOLICITATION_STATE")
    if store.now() < solicitation["effective_bid_due_utc"]:
        raise ApiError("ERR_BID_PERIOD_OPEN")
    live = [b for b in services.bids_of(solicitation)
            if b["responsiveness_status"] != "WITHDRAWN"]
    if not live:
        raise ApiError("ERR_NO_BIDS_RECEIVED")

    v.set_field(solicitation, "status", "BIDS_OPENED")
    v.set_field(solicitation, "bids_opened_at_utc", store.now())
    for bid in live:
        # as-read variant: evaluated price is exactly the as-read price
        v.set_field(bid, "evaluated_price_cents", bid["total_price_cents"])
        v.set_field(bid, "informality_loading_cents", 0)
    services.recompute_apparent_low_bid(solicitation)
    v.touch(solicitation)
    return ("obj", solicitation, serializers.solicitation, 200)


@bp.post("/procurement/solicitations/<solicitation_id>/cancel")
@v.endpoint(["ProcurementOfficer"])
def cancel(solicitation_id):
    data = v.body()
    v.req_str(data, "cancellation_reason")
    solicitation = services.must("solicitations", solicitation_id)
    if solicitation["status"] not in CANCELLABLE_STATUSES:
        raise ApiError("ERR_INVALID_SOLICITATION_STATE")
    services.cancel_solicitation(solicitation)
    return ("obj", solicitation, serializers.solicitation, 200)


@bp.post("/procurement/solicitations/<solicitation_id>/resolicit")
@v.endpoint(["ProcurementOfficer"])
def resolicit(solicitation_id):
    data = v.body()
    new_number = v.req_str(data, "new_solicitation_number")
    original_bid_due_utc = v.req_dt(data, "original_bid_due_utc")
    original_question_deadline_utc = v.req_dt(data, "original_question_deadline_utc")
    if not original_question_deadline_utc < original_bid_due_utc:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "'original_question_deadline_utc' must be strictly before 'original_bid_due_utc'",
        )

    predecessor = services.must("solicitations", solicitation_id)

    for existing in store.values("solicitations"):
        if existing["solicitation_number"] == new_number:
            raise ApiError("ERR_DUPLICATE_SOLICITATION_NUMBER")

    if predecessor["status"] != "CANCELLED":
        raise ApiError("ERR_INVALID_SOLICITATION_STATE")

    for existing in store.values("solicitations"):
        if existing["predecessor_solicitation_id"] == predecessor["id"]:
            raise ApiError("ERR_ALREADY_RESOLICITED")

    v.set_field(predecessor, "status", "RESOLICITED")
    v.touch(predecessor)

    successor = store.insert("solicitations", store.row("solicitations", {
        "solicitation_number": new_number,
        "title": predecessor["title"],
        "issuing_agency_code": predecessor["issuing_agency_code"],
        "estimated_value_cents": predecessor["estimated_value_cents"],
        "original_bid_due_utc": original_bid_due_utc,
        "effective_bid_due_utc": None,
        "original_question_deadline_utc": original_question_deadline_utc,
        "question_deadline_utc": None,
        "status": "DRAFT",
        "issued_by_user_id": None,
        "bids_opened_at_utc": None,
        "cumulative_extension_days": 0,
        "addendum_count": 0,
        "apparent_low_bid_id": None,
        "protest_escrow_cents": 0,
        "predecessor_solicitation_id": predecessor["id"],
    }))
    for requirement in services.requirements_of(predecessor):
        if requirement["introduced_by_addendum_sequence"] == 0:
            _create_requirement(successor, {
                "requirement_code": requirement["requirement_code"],
                "description": requirement["description"],
                "materiality": requirement["materiality"],
                "is_waivable": requirement["is_waivable"],
            }, 0)
    return ("obj", successor, serializers.solicitation, 201)
