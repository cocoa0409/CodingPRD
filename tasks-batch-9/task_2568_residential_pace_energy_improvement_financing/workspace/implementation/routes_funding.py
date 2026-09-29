"""Completion certificates, disbursements and workmanship complaints."""

from flask import Blueprint

import calc
import db
import response
import services
import validation as v
from errors import fail
from middleware import (
    ALL_ROLES,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_CONTRACTOR,
    ROLE_FUNDING_OFFICER,
    ROLE_PROPERTY_OWNER,
    authorize,
    require_contractor,
    require_property_owner,
)

bp = Blueprint("funding", __name__)

LIVE_CERTIFICATE_STATUSES = ("CONTRACTOR_ATTESTED", "HOMEOWNER_SIGNED", "VERIFIED")
LIVE_DRAW_STATUSES = ("REQUESTED", "HELD", "RELEASED")


def _list(rows, limit, offset):
    window, total = response.paginate(rows, limit, offset)
    return response.listing([db.public(row) for row in window], limit, offset, total)


def _signature_matches(submitted, owner_full_name):
    return submitted.strip() == str(owner_full_name).strip()


# --------------------------------------------------- completion certificates --
@bp.post("/pace/completion-certificates")
def file_certificate():
    caller = authorize([ROLE_CONTRACTOR])
    payload = v.body()
    application_id = v.req_id(payload, "application_id")
    measure_ids = v.req_str_array(payload, "measure_ids", no_duplicates=True)
    certified_cost_cents = v.req_int(payload, "certified_cost_cents", minimum=0)
    attestation_note = v.opt_str(payload, "contractor_attestation_note")
    application = services.get_application(application_id)
    measures = [services.get_measure(measure_id) for measure_id in measure_ids]
    require_contractor(caller, application["contractor_id"])
    for measure in measures:
        if (
            measure["application_id"] != application["id"]
            or measure["status"] != "APPROVED"
        ):
            fail(
                "ERR_MEASURE_NOT_IN_APPLICATION",
                "Every measure_id must name an APPROVED measure of this application",
            )
    if application["status"] not in ("FUNDING_PENDING", "FUNDING_HELD"):
        fail(
            "ERR_APPLICATION_STATE_INVALID",
            "Application is not FUNDING_PENDING or FUNDING_HELD",
        )
    claimed = set(measure_ids)
    for other in services.certificates_of(application["id"]):
        if other["status"] in LIVE_CERTIFICATE_STATUSES and claimed & set(
            other["measure_ids"]
        ):
            fail(
                "ERR_MEASURE_ALREADY_CERTIFIED",
                "Another live certificate already covers one of those measures",
            )
    ceiling = sum(int(measure["installed_cost_cents"]) for measure in measures)
    if certified_cost_cents > ceiling:
        fail(
            "ERR_CERTIFIED_COST_EXCEEDS_MEASURES",
            "certified_cost_cents exceeds the installed cost of the referenced measures",
        )
    certificate = db.create(
        "certificates",
        {
            "application_id": application["id"],
            "measure_ids": list(measure_ids),
            "certified_cost_cents": certified_cost_cents,
            "contractor_attestation_note": attestation_note,
            "status": "CONTRACTOR_ATTESTED",
            "homeowner_signature_name": None,
            "homeowner_signed_at": None,
            "verified_by_user_id": None,
            "verified_at": None,
            "rejection_reason": None,
        },
    )
    return response.created(db.public(certificate))


@bp.get("/pace/completion-certificates/<row_id>")
def read_certificate(row_id):
    authorize(ALL_ROLES)
    return response.ok(db.public(services.get_certificate(row_id)))


@bp.post("/pace/completion-certificates/<row_id>/sign")
def sign_certificate(row_id):
    caller = authorize([ROLE_PROPERTY_OWNER])
    payload = v.body()
    signature_name = v.req_str(payload, "homeowner_signature_name")
    certificate = services.get_certificate(row_id)
    application = services.get_application(certificate["application_id"])
    require_property_owner(caller, application["property_id"])
    if certificate["status"] != "CONTRACTOR_ATTESTED":
        fail("ERR_CERTIFICATE_STATE_INVALID", "Certificate is not CONTRACTOR_ATTESTED")
    prop = services.get_property(application["property_id"])
    if not _signature_matches(signature_name, prop["owner_full_name"]):
        fail(
            "ERR_SIGNATURE_NAME_MISMATCH",
            "homeowner_signature_name does not match the record owner",
        )
    certificate["homeowner_signature_name"] = signature_name
    certificate["homeowner_signed_at"] = db.now_iso()
    certificate["status"] = "HOMEOWNER_SIGNED"
    db.touch(certificate)
    return response.ok(db.public(certificate))


@bp.post("/pace/completion-certificates/<row_id>/verify")
def verify_certificate(row_id):
    caller = authorize([ROLE_FUNDING_OFFICER])
    payload = v.body()
    decision = v.req_enum(payload, "decision", ("APPROVE", "REJECT"))
    rejection_reason = v.opt_str(payload, "rejection_reason")
    if decision == "REJECT" and rejection_reason is None:
        fail("ERR_VALIDATION", "rejection_reason is required on a REJECT decision")
    certificate = services.get_certificate(row_id)
    application = services.get_application(certificate["application_id"])
    if application["status"] != "FUNDING_PENDING":
        fail("ERR_APPLICATION_STATE_INVALID", "Application is not FUNDING_PENDING")
    if certificate["status"] != "HOMEOWNER_SIGNED":
        fail("ERR_CERTIFICATE_STATE_INVALID", "Certificate is not HOMEOWNER_SIGNED")
    if decision == "APPROVE":
        certificate["status"] = "VERIFIED"
        certificate["verified_by_user_id"] = caller.user_id
        certificate["verified_at"] = db.now_iso()
        db.touch(certificate)
        for measure_id in certificate["measure_ids"]:
            measure = db.get("measures", measure_id)
            if measure is not None and measure["status"] == "APPROVED":
                measure["status"] = "COMPLETED"
                db.touch(measure)
    else:
        certificate["status"] = "REJECTED"
        certificate["rejection_reason"] = rejection_reason
        db.touch(certificate)
    return response.ok(db.public(certificate))


# ------------------------------------------------------------- disbursements --
@bp.post("/pace/disbursements")
def request_disbursement():
    authorize([ROLE_FUNDING_OFFICER])
    payload = v.body()
    application_id = v.req_id(payload, "application_id")
    certificate_id = v.req_id(payload, "completion_certificate_id")
    contractor_id = v.req_id(payload, "contractor_id")
    amount_cents = v.req_int(payload, "amount_cents", minimum=1)
    application = services.get_application(application_id)
    certificate = services.get_certificate(certificate_id)
    contractor = services.get_contractor(contractor_id)
    if contractor["enrollment_status"] not in ("ENROLLED", "PROBATION"):
        fail("ERR_CONTRACTOR_NOT_ENROLLED", "Contractor may not be paid")
    if certificate["application_id"] != application["id"]:
        fail(
            "ERR_CERTIFICATE_APPLICATION_MISMATCH",
            "The certificate belongs to a different application",
        )
    if contractor["id"] != application["contractor_id"]:
        fail("ERR_CONTRACTOR_MISMATCH", "contractor_id is not the application's contractor")
    if application["status"] != "FUNDING_PENDING":
        fail("ERR_APPLICATION_STATE_INVALID", "Application is not FUNDING_PENDING")
    if certificate["status"] != "VERIFIED":
        fail("ERR_CERTIFICATE_STATE_INVALID", "Certificate is not VERIFIED")
    against_certificate = sum(
        int(row["amount_cents"])
        for row in db.rows("disbursements")
        if row["completion_certificate_id"] == certificate["id"]
        and row["status"] in LIVE_DRAW_STATUSES
    )
    if against_certificate >= int(certificate["certified_cost_cents"]):
        fail(
            "ERR_CERTIFICATE_ALREADY_DISBURSED",
            "The certificate has already been drawn in full",
        )
    if amount_cents > int(certificate["certified_cost_cents"]):
        fail("ERR_AMOUNT_EXCEEDS_CERTIFICATE", "amount_cents exceeds the certified cost")
    agreement = services.live_agreement_of(application["id"])
    payable = int(agreement["contractor_payable_cents"]) if agreement else 0
    live_total = sum(
        int(row["amount_cents"])
        for row in services.disbursements_of_application(application["id"])
        if row["status"] in LIVE_DRAW_STATUSES
    )
    if live_total + amount_cents > payable:
        fail(
            "ERR_DISBURSEMENT_EXCEEDS_PAYABLE",
            "The draw would exceed the contractor payable",
        )
    on_probation = contractor["enrollment_status"] == "PROBATION"
    draw = db.create(
        "disbursements",
        {
            "application_id": application["id"],
            "completion_certificate_id": certificate["id"],
            "contractor_id": contractor["id"],
            "amount_cents": amount_cents,
            "status": "HELD" if on_probation else "REQUESTED",
            "hold_reason": "CONTRACTOR_PROBATION" if on_probation else None,
            "released_by_user_id": None,
            "released_at": None,
            "reversal_reason": None,
            "reversed_at": None,
        },
    )
    return response.created(db.public(draw))


@bp.get("/pace/disbursements/<row_id>")
def read_disbursement(row_id):
    authorize(ALL_ROLES)
    return response.ok(db.public(services.get_disbursement(row_id)))


@bp.get("/pace/disbursements")
def list_disbursements():
    authorize(ALL_ROLES)
    limit, offset = v.pagination()
    application_id = v.filter_value("application_id")
    contractor_id = v.filter_value("contractor_id")
    certificate_id = v.filter_value("completion_certificate_id")
    status = v.filter_value("status")
    rows = db.by_created_at(db.rows("disbursements"))
    if application_id:
        rows = [row for row in rows if row["application_id"] == application_id]
    if contractor_id:
        rows = [row for row in rows if row["contractor_id"] == contractor_id]
    if certificate_id:
        rows = [
            row for row in rows if row["completion_certificate_id"] == certificate_id
        ]
    if status:
        rows = [row for row in rows if row["status"] == status]
    return _list(rows, limit, offset)


@bp.post("/pace/disbursements/<row_id>/release")
def release_disbursement(row_id):
    caller = authorize([ROLE_FUNDING_OFFICER])
    v.body()
    draw = services.get_disbursement(row_id)
    application = services.get_application(draw["application_id"])
    contractor = services.get_contractor(draw["contractor_id"])
    certificate = services.get_certificate(draw["completion_certificate_id"])
    agreement = services.live_agreement_of(application["id"])
    if contractor["enrollment_status"] != "ENROLLED":
        fail("ERR_CONTRACTOR_NOT_ENROLLED", "Contractor is not ENROLLED")
    if agreement is None or agreement["status"] not in ("SIGNED", "EFFECTIVE"):
        fail("ERR_AGREEMENT_STATE_INVALID", "Agreement is not SIGNED or EFFECTIVE")
    if draw["status"] != "REQUESTED":
        fail("ERR_DISBURSEMENT_STATE_INVALID", "Disbursement is not REQUESTED")
    expiry = db.parse_instant(agreement.get("rescission_expires_at"))
    if expiry is None or db.now() < expiry:
        fail("ERR_RESCISSION_PERIOD_ACTIVE", "The right of rescission has not lapsed")
    if agreement["oral_confirmation_required"] and not agreement.get(
        "oral_confirmation_completed_at"
    ):
        fail("ERR_ORAL_CONFIRMATION_REQUIRED", "The oral confirmation call is not on file")
    if (
        certificate.get("verified_by_user_id") is not None
        and caller.user_id == certificate["verified_by_user_id"]
    ):
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The releasing officer may not be the verifying officer",
        )
    payable = int(agreement["contractor_payable_cents"])
    released_total = sum(
        int(row["amount_cents"])
        for row in services.disbursements_of_application(application["id"])
        if row["status"] == "RELEASED"
    )
    if released_total + int(draw["amount_cents"]) > payable:
        fail(
            "ERR_DISBURSEMENT_EXCEEDS_PAYABLE",
            "The release would exceed the contractor payable",
        )
    draw["status"] = "RELEASED"
    draw["released_by_user_id"] = caller.user_id
    draw["released_at"] = db.now_iso()
    db.touch(draw)
    services.recompute_contractor_cash(contractor)
    if agreement["status"] == "SIGNED":
        agreement["status"] = "EFFECTIVE"
        agreement["effective_at"] = db.now_iso()
        db.touch(agreement)
    if released_total + int(draw["amount_cents"]) == payable:
        application["status"] = "FUNDED"
        db.touch(application)
    return response.ok(db.public(draw))


@bp.post("/pace/disbursements/<row_id>/reverse")
def reverse_disbursement(row_id):
    authorize([ROLE_COMPLIANCE_OFFICER])
    payload = v.body()
    reversal_reason = v.req_str(payload, "reversal_reason")
    draw = services.get_disbursement(row_id)
    if draw["status"] != "RELEASED":
        fail("ERR_DISBURSEMENT_STATE_INVALID", "Disbursement is not RELEASED")
    escalated = [
        row
        for row in services.complaints_of_application(draw["application_id"])
        if row["status"] == "ESCALATED_RECOURSE"
    ]
    if not escalated:
        fail(
            "ERR_NO_RECOURSE_BASIS",
            "No complaint of this application stands at ESCALATED_RECOURSE",
        )
    draw["status"] = "REVERSED"
    draw["reversal_reason"] = reversal_reason
    draw["reversed_at"] = db.now_iso()
    db.touch(draw)
    services.recompute_contractor_cash(services.get_contractor(draw["contractor_id"]))
    return response.ok(db.public(draw))


# ----------------------------------------------------------------- complaints --
@bp.post("/pace/complaints")
def file_complaint():
    caller = authorize([ROLE_PROPERTY_OWNER])
    payload = v.body()
    application_id = v.req_id(payload, "application_id")
    contractor_id = v.req_id(payload, "contractor_id")
    category = v.req_enum(payload, "category", v.COMPLAINT_CATEGORIES)
    severity = v.req_enum(payload, "severity", v.SEVERITIES)
    description = v.req_str(payload, "description")
    application = services.get_application(application_id)
    contractor = services.get_contractor(contractor_id)
    require_property_owner(caller, application["property_id"])
    if contractor["id"] != application["contractor_id"]:
        fail("ERR_CONTRACTOR_MISMATCH", "contractor_id is not the application's contractor")
    if application["status"] not in ("FUNDED", "ASSESSED"):
        fail("ERR_APPLICATION_STATE_INVALID", "Application is not FUNDED or ASSESSED")
    if len(services.complaints_of_application(application["id"])) >= 3:
        fail(
            "ERR_COMPLAINT_LIMIT_EXCEEDED",
            "An application may carry at most three complaints",
        )
    complaint = db.create(
        "complaints",
        {
            "application_id": application["id"],
            "contractor_id": contractor["id"],
            "category": category,
            "severity": severity,
            "description": description,
            "status": "OPEN",
            "adjudicated_at": None,
            "adjudicated_by_user_id": None,
            "remedy_deadline_on": None,
            "closed_at": None,
        },
    )
    return response.created(db.public(complaint))


@bp.get("/pace/complaints/<row_id>")
def read_complaint(row_id):
    authorize(ALL_ROLES)
    return response.ok(db.public(services.get_complaint(row_id)))


@bp.get("/pace/complaints")
def list_complaints():
    authorize(ALL_ROLES)
    limit, offset = v.pagination()
    application_id = v.filter_value("application_id")
    contractor_id = v.filter_value("contractor_id")
    status = v.filter_value("status")
    severity = v.filter_value("severity")
    rows = db.by_created_at(db.rows("complaints"))
    if application_id:
        rows = [row for row in rows if row["application_id"] == application_id]
    if contractor_id:
        rows = [row for row in rows if row["contractor_id"] == contractor_id]
    if status:
        rows = [row for row in rows if row["status"] == status]
    if severity:
        rows = [row for row in rows if row["severity"] == severity]
    return _list(rows, limit, offset)


@bp.post("/pace/complaints/<row_id>/adjudicate")
def adjudicate_complaint(row_id):
    caller = authorize([ROLE_COMPLIANCE_OFFICER])
    payload = v.body()
    decision = v.req_enum(
        payload, "decision", ("UPHOLD_REMEDY", "DENY", "REMEDY_VERIFIED", "RECOURSE")
    )
    v.opt_str(payload, "note")
    remedy_deadline_on = v.opt_date(payload, "remedy_deadline_on")
    if decision == "UPHOLD_REMEDY" and remedy_deadline_on is None:
        fail("ERR_VALIDATION", "remedy_deadline_on is required on an UPHOLD_REMEDY decision")
    complaint = services.get_complaint(row_id)
    if decision in ("UPHOLD_REMEDY", "DENY"):
        if complaint["status"] != "OPEN":
            fail("ERR_COMPLAINT_STATE_INVALID", "Complaint is not OPEN")
    elif complaint["status"] != "REMEDY_ORDERED":
        fail("ERR_COMPLAINT_STATE_INVALID", "Complaint is not REMEDY_ORDERED")
    today = db.today()
    if decision == "UPHOLD_REMEDY":
        if calc.date_from_iso(remedy_deadline_on) <= today:
            fail(
                "ERR_REMEDY_DEADLINE_PASSED",
                "remedy_deadline_on must be strictly after the current logical date",
            )
    elif decision == "REMEDY_VERIFIED":
        if today > calc.date_from_iso(complaint["remedy_deadline_on"]):
            fail("ERR_REMEDY_DEADLINE_PASSED", "The remedy deadline has already passed")
    elif decision == "RECOURSE":
        if today <= calc.date_from_iso(complaint["remedy_deadline_on"]):
            fail(
                "ERR_REMEDY_DEADLINE_NOT_REACHED",
                "The remedy deadline has not yet passed",
            )
    instant = db.now_iso()
    contractor = services.get_contractor(complaint["contractor_id"])
    complaint["adjudicated_at"] = instant
    complaint["adjudicated_by_user_id"] = caller.user_id
    if decision == "UPHOLD_REMEDY":
        complaint["remedy_deadline_on"] = remedy_deadline_on
        complaint["status"] = "REMEDY_ORDERED"
        db.touch(complaint)
        services.recompute_workmanship_scores(contractor)
        services.apply_workmanship_enrollment_cascade(contractor)
        db.touch(contractor)
    elif decision == "DENY":
        complaint["status"] = "CLOSED_DENIED"
        complaint["closed_at"] = instant
        db.touch(complaint)
    elif decision == "REMEDY_VERIFIED":
        complaint["status"] = "CLOSED_REMEDIED"
        complaint["closed_at"] = instant
        db.touch(complaint)
        services.recompute_workmanship_scores(contractor)
        db.touch(contractor)
    else:
        was_suspended = contractor["enrollment_status"] == "SUSPENDED"
        complaint["status"] = "ESCALATED_RECOURSE"
        complaint["closed_at"] = instant
        db.touch(complaint)
        services.recompute_workmanship_scores(contractor)
        if was_suspended:
            contractor["enrollment_status"] = "TERMINATED"
            contractor["suspension_reason"] = "RECOURSE_WHILE_SUSPENDED"
        db.touch(contractor)
    return response.ok(db.public(complaint))
