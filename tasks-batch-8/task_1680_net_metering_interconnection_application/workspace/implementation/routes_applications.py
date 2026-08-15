"""Applications (intake, completeness, amend, withdraw, PTO) and documents
(PRD 3.3, 3.6, 3.8)."""

import clock as clockmod
import envelope
import serializers as ser
import services
from errors import ApiError
from flask import Blueprint
from middleware import (begin, must_exist, must_ref, opt_enum, opt_int,
                        opt_string, paginate, pagination, req_enum, req_int,
                        req_string)
from store import db, stamp_new, sorted_rows, touch

bp = Blueprint("applications", __name__)

TECHNOLOGIES = ("SOLAR_PV", "WIND", "FUEL_CELL")
DOC_TYPES = ("SITE_PLAN", "SINGLE_LINE_DIAGRAM", "INSURANCE_CERTIFICATE")
DECISION_OUTCOMES = ("COMPLETE", "INCOMPLETE")
REVIEW_OUTCOMES = ("ACCEPTED", "REJECTED")
UPLOAD_STATES = ("DRAFT", "PENDING_COMPLETENESS", "INCOMPLETE", "SUPPLEMENTAL_REVIEW")


def own_application(ctx, application):
    """Rung 3: the Applicant caller must own the application's account."""
    account = services.account_of(application)
    if account is None or account["customer_id"] != ctx.user_id:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")


# ---------------------------------------------------------------------------
# Applications (PRD 3.3)
# ---------------------------------------------------------------------------

@bp.route("/applications", methods=["POST"])
def create_application():
    ctx = begin("Applicant")
    body = ctx.body
    service_account_id = req_string(body, "service_account_id")
    program_id = req_string(body, "program_id")
    technology = req_enum(body, "technology", TECHNOLOGIES)
    system_size_watts_ac = req_int(body, "system_size_watts_ac", minimum=1)
    estimated_annual_production_wh = req_int(body, "estimated_annual_production_wh", minimum=1)
    account = must_ref(db.accounts, service_account_id)
    must_ref(db.programs, program_id)
    if account["customer_id"] != ctx.user_id:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    row = stamp_new({
        "program_id": program_id,
        "service_account_id": service_account_id,
        "technology": technology,
        "system_size_watts_ac": system_size_watts_ac,
        "estimated_annual_production_wh": estimated_annual_production_wh,
        "application_status": "DRAFT",
        "denial_reason": None,
        "withdrawal_reason": None,
        "queue_position": None,
        "capacity_reserved_watts": 0,
        "reservation_expires_at": None,
        "submission_round": 0,
        "submitted_at": None,
        "pto_granted_at": None,
    })
    db.applications[row["id"]] = row
    return envelope.created(ser.application(row))


@bp.route("/applications", methods=["GET"])
def list_applications():
    ctx = begin()
    rows = list(db.applications.values())
    service_account_id = ctx.query.get("service_account_id")
    if service_account_id is not None:
        rows = [r for r in rows if r["service_account_id"] == service_account_id]
    program_id = ctx.query.get("program_id")
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    application_status = ctx.query.get("application_status")
    if application_status is not None:
        rows = [r for r in rows if r["application_status"] == application_status]
    rows = sorted_rows(rows)
    limit, offset = pagination(ctx.query)
    page, total = paginate(rows, limit, offset)
    return envelope.listing([ser.application(r) for r in page], limit, offset, total)


@bp.route("/applications/<application_id>", methods=["GET"])
def get_application(application_id):
    begin()
    row = must_exist(db.applications, application_id)
    return envelope.ok(ser.application(row))


@bp.route("/applications/<application_id>/submit", methods=["POST"])
def submit_application(application_id):
    """Submit (DRAFT) or resubmit (INCOMPLETE) — PRD 3.3.  The duplicate
    active-application check applies to the DRAFT submission only; a
    resubmission is made under the same program-and-account conditions."""
    ctx = begin("Applicant")
    row = must_exist(db.applications, application_id)
    own_application(ctx, row)
    if row["application_status"] not in ("DRAFT", "INCOMPLETE"):
        raise ApiError("ERR_INVALID_STATE")
    account = services.account_of(row)
    program = services.program_of(row)
    if row["application_status"] == "DRAFT":
        for other in services.applications_of_account(account["id"]):
            if other["id"] != row["id"] and other["application_status"] not in services.TERMINAL:
                raise ApiError("ERR_DUPLICATE_ACTIVE_APPLICATION")
    if program["program_status"] not in ("OPEN", "CAP_REACHED"):
        raise ApiError("ERR_PROGRAM_NOT_ACCEPTING")
    if account["account_status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE")
    row["application_status"] = "PENDING_COMPLETENESS"
    row["submitted_at"] = clockmod.now()
    row["submission_round"] += 1
    touch(row)
    return envelope.ok(ser.application(row))


@bp.route("/applications/<application_id>/completeness-decision", methods=["POST"])
def completeness_decision(application_id):
    ctx = begin("InterconnectionCoordinator")
    row = must_exist(db.applications, application_id)
    body = ctx.body
    outcome = req_enum(body, "outcome", DECISION_OUTCOMES)
    deficiency_note = opt_string(body, "deficiency_note")
    if outcome == "INCOMPLETE" and not deficiency_note:
        raise ApiError("ERR_INVALID_REQUEST", "deficiency_note is required when outcome is INCOMPLETE.")
    if row["application_status"] != "PENDING_COMPLETENESS":
        raise ApiError("ERR_INVALID_STATE")

    documents = [d for d in db.documents.values() if d["application_id"] == row["id"]]
    if outcome == "INCOMPLETE":
        if not any(d["review_status"] == "REJECTED" for d in documents):
            raise ApiError("ERR_NO_REJECTED_DOCUMENTS")
        row["application_status"] = "INCOMPLETE"
        touch(row)
        return envelope.ok(ser.application(row))

    # COMPLETE: the full required document set must be ACCEPTED.
    for doc_type in services.REQUIRED_DOC_TYPES:
        if not any(d["doc_type"] == doc_type and d["review_status"] == "ACCEPTED" for d in documents):
            raise ApiError("ERR_INCOMPLETE_DOCUMENTS")

    account = services.account_of(row)
    program = services.program_of(row)

    denial = services.eligibility_denial_reason(
        account, row["system_size_watts_ac"], row["estimated_annual_production_wh"]
    )
    if denial is not None:
        row["application_status"] = "DENIED"
        row["denial_reason"] = denial
        touch(row)
        return envelope.ok(ser.application(row))

    if services.program_available(program) >= row["system_size_watts_ac"]:
        services.reserve_capacity(row)
    else:
        services.enqueue(row)
    return envelope.ok(ser.application(row))


@bp.route("/applications/<application_id>/amend", methods=["POST"])
def amend_application(application_id):
    """Amend the design in DRAFT, CAPACITY_RESERVED, or SUPPLEMENTAL_REVIEW
    (PRD 3.6)."""
    ctx = begin("Applicant")
    row = must_exist(db.applications, application_id)
    own_application(ctx, row)
    body = ctx.body

    touched_fields = [
        f for f in ("system_size_watts_ac", "estimated_annual_production_wh", "technology")
        if f in body and body[f] is not None
    ]
    if not touched_fields:
        raise ApiError("ERR_INVALID_REQUEST", "The amend payload must touch at least one field.")
    new_size = opt_int(body, "system_size_watts_ac", minimum=1)
    new_production = opt_int(body, "estimated_annual_production_wh", minimum=1)
    new_technology = opt_enum(body, "technology", TECHNOLOGIES)

    if row["application_status"] not in ("DRAFT", "CAPACITY_RESERVED", "SUPPLEMENTAL_REVIEW"):
        raise ApiError("ERR_INVALID_STATE")

    account = services.account_of(row)
    merged_size = new_size if new_size is not None else row["system_size_watts_ac"]
    merged_production = (
        new_production if new_production is not None else row["estimated_annual_production_wh"]
    )
    denial = services.eligibility_denial_reason(account, merged_size, merged_production)
    if denial == "SIZE_EXCEEDS_CLASS_CAP":
        raise ApiError("ERR_SIZE_EXCEEDS_CLASS_CAP")
    if denial == "PRODUCTION_EXCEEDS_LOAD":
        raise ApiError("ERR_PRODUCTION_EXCEEDS_LOAD")

    row["system_size_watts_ac"] = merged_size
    row["estimated_annual_production_wh"] = merged_production
    if new_technology is not None:
        row["technology"] = new_technology

    # The engineering record no longer describes the amended design.
    for report in db.reports.values():
        if report["application_id"] == row["id"] and report["report_status"] == "CURRENT":
            report["report_status"] = "SUPERSEDED"
            touch(report)
    for review in db.reviews.values():
        if review["application_id"] == row["id"] and review["review_status"] == "OPEN":
            review["review_status"] = "CLOSED"
            touch(review)

    if row["application_status"] in ("CAPACITY_RESERVED", "SUPPLEMENTAL_REVIEW"):
        program = services.program_of(row)
        old_reserved = row["capacity_reserved_watts"]
        delta = merged_size - old_reserved
        if delta > 0:
            if services.program_available(program) >= delta:
                program["reserved_watts"] += delta
                row["capacity_reserved_watts"] = merged_size
                touch(program)
                row["application_status"] = "CAPACITY_RESERVED"
            else:
                services.release_reservation(row)
                services.enqueue(row)
                services.promotion_scan(program)
        elif delta < 0:
            program["reserved_watts"] += delta
            row["capacity_reserved_watts"] = merged_size
            touch(program)
            row["application_status"] = "CAPACITY_RESERVED"
            services.promotion_scan(program)
        else:
            row["application_status"] = "CAPACITY_RESERVED"
        services.recompute_posture(program)

    touch(row)
    return envelope.ok(ser.application(row))


@bp.route("/applications/<application_id>/withdraw", methods=["POST"])
def withdraw_application(application_id):
    ctx = begin("Applicant")
    row = must_exist(db.applications, application_id)
    own_application(ctx, row)
    if row["application_status"] not in services.WITHDRAWABLE:
        raise ApiError("ERR_INVALID_STATE")
    services.withdraw_application(row, "APPLICANT_WITHDRAWN")
    return envelope.ok(ser.application(row))


@bp.route("/applications/<application_id>/grant-pto", methods=["POST"])
def grant_pto(application_id):
    """Permission to operate (PRD 3.8); the exchange gate is checked before
    the inspection gate."""
    begin("InterconnectionCoordinator")
    row = must_exist(db.applications, application_id)
    if row["application_status"] != "SCREEN_PASSED":
        raise ApiError("ERR_INVALID_STATE")
    account = services.account_of(row)
    program = services.program_of(row)
    if account["account_status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE")
    completed = [
        e for e in db.exchanges.values()
        if e["application_id"] == row["id"] and e["exchange_status"] == "COMPLETED"
    ]
    if not completed:
        raise ApiError("ERR_METER_EXCHANGE_NOT_COMPLETED")
    inspections = [i for i in db.inspections.values() if i["application_id"] == row["id"]]
    latest = None
    for inspection in inspections:
        if latest is None or (inspection["created_at"], inspection["_seq"]) > (
            latest["created_at"], latest["_seq"]
        ):
            latest = inspection
    if latest is None or latest["inspection_status"] != "RESULT_RECORDED" or latest["outcome"] != "PASSED":
        raise ApiError("ERR_INSPECTION_NOT_PASSED")
    if services.effective_tariff(program["id"], clockmod.now()) is None:
        raise ApiError("ERR_NO_EFFECTIVE_TARIFF")

    row["pto_granted_at"] = clockmod.now()
    program["reserved_watts"] -= row["capacity_reserved_watts"]
    program["interconnected_watts"] += row["capacity_reserved_watts"]
    row["capacity_reserved_watts"] = 0
    row["reservation_expires_at"] = None
    row["application_status"] = "PTO_GRANTED"
    touch(program)
    touch(row)
    if account["metering_status"] == "STANDARD":
        account["metering_status"] = "NET_METERING"
    touch(account)
    return envelope.ok(ser.application(row))


# ---------------------------------------------------------------------------
# Documents (PRD 3.3)
# ---------------------------------------------------------------------------

@bp.route("/documents", methods=["POST"])
def create_document():
    ctx = begin("Applicant")
    body = ctx.body
    application_id = req_string(body, "application_id")
    doc_type = req_enum(body, "doc_type", DOC_TYPES)
    title = req_string(body, "title")
    application = must_ref(db.applications, application_id)
    own_application(ctx, application)
    if application["application_status"] not in UPLOAD_STATES:
        raise ApiError("ERR_INVALID_STATE")
    row = stamp_new({
        "application_id": application_id,
        "doc_type": doc_type,
        "title": title,
        "review_status": "UPLOADED",
        "review_note": None,
    })
    db.documents[row["id"]] = row
    return envelope.created(ser.document(row))


@bp.route("/documents", methods=["GET"])
def list_documents():
    ctx = begin()
    rows = list(db.documents.values())
    application_id = ctx.query.get("application_id")
    if application_id is not None:
        rows = [r for r in rows if r["application_id"] == application_id]
    review_status = ctx.query.get("review_status")
    if review_status is not None:
        rows = [r for r in rows if r["review_status"] == review_status]
    rows = sorted_rows(rows)
    limit, offset = pagination(ctx.query)
    page, total = paginate(rows, limit, offset)
    return envelope.listing([ser.document(r) for r in page], limit, offset, total)


@bp.route("/documents/<document_id>", methods=["GET"])
def get_document(document_id):
    begin()
    row = must_exist(db.documents, document_id)
    return envelope.ok(ser.document(row))


@bp.route("/documents/<document_id>/review", methods=["POST"])
def review_document(document_id):
    ctx = begin("InterconnectionCoordinator")
    row = must_exist(db.documents, document_id)
    outcome = req_enum(ctx.body, "outcome", REVIEW_OUTCOMES)
    review_note = opt_string(ctx.body, "review_note")
    if row["review_status"] != "UPLOADED":
        raise ApiError("ERR_INVALID_STATE")
    row["review_status"] = outcome
    row["review_note"] = review_note
    touch(row)
    return envelope.ok(ser.document(row))
