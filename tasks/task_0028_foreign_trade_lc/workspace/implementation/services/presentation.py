"""Presentation, document attachment, examination flow, refusal, returns."""

from flask import g
from datetime import timedelta

import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_VERSION_CONFLICT,
    ERR_INVALID_STATE_TRANSITION,
    ERR_PRESENTATION_AFTER_EXPIRY,
    ERR_SHIPMENT_OUT_OF_WINDOW,
    ERR_LC_INSUFFICIENT_AVAILABLE,
    ERR_DOCUMENT_NOT_REQUIRED_OR_DUPLICATE,
    ERR_DOCUMENTS_FROZEN,
    ERR_REVIEWER_SAME_PERSON,
    ERR_REVIEW_ALREADY_RECORDED,
    ERR_REVIEW_OUT_OF_ORDER,
    ERR_EXAMINATION_DEADLINE_PASSED,
    ERR_REFUSAL_DEADLINE_PASSED,
    ERR_RETURN_WINDOW_PASSED,
)
from services import audit
from services.banking import banking_days_between, add_banking_days


DOC_TYPES = {"COMMERCIAL_INVOICE", "BILL_OF_LADING", "PACKING_LIST",
             "INSURANCE_POLICY", "CERTIFICATE_OF_ORIGIN"}


def _check_version(row, payload):
    if payload and "version" in payload and payload["version"] is not None:
        if payload["version"] != row.get("version"):
            raise_error(ERR_VERSION_CONFLICT, "version mismatch")


def _enforce_presentation_visibility(p, lc, role, user_id):
    if role in ("Operator", "Auditor"):
        return
    if role == "Applicant" and lc.get("applicant_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "Applicant not on this LC")
    if role == "Beneficiary" and lc.get("beneficiary_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "Beneficiary not on this LC")
    if role == "IssuingBank" and lc.get("issuing_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "IssuingBank not on this LC")
    if role == "ConfirmingBank" and lc.get("confirming_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "ConfirmingBank not on this LC")
    if role == "NegotiatingBank":
        # Allowed if there's a NEGOTIATION settlement under this presentation
        for s in db.find_many("payment_settlements", presentation_id=p["id"]):
            if s.get("settlement_type") == "NEGOTIATION" and s.get("negotiating_bank_id") == user_id:
                return
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "NegotiatingBank not on this presentation")


# ---------- Presentation creation / listing ----------

def create_presentation(lc_id, payload, user_id):
    lc = db.get_by_id("letters_of_credit", lc_id)
    if lc is None:
        raise_error(ERR_NOT_FOUND, "lc not found")
    if lc.get("beneficiary_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "Beneficiary does not own this LC")
    if not isinstance(payload, dict):
        raise_error(ERR_INVALID_REQUEST, "JSON body required")

    if lc["lifecycle_status"] not in ("ACTIVE",):
        # Per PRD: presentations cannot be submitted while ADVISED waiting on confirmation;
        # presentation against expired LC is rejected with ERR_PRESENTATION_AFTER_EXPIRY.
        if lc["lifecycle_status"] == "EXPIRED":
            raise_error(ERR_PRESENTATION_AFTER_EXPIRY, "LC expired")
        raise_error(ERR_INVALID_STATE_TRANSITION, f"LC not active (status={lc['lifecycle_status']})")

    shipment_date = payload.get("shipment_date")
    drawing = payload.get("drawing_amount_minor_units")
    if shipment_date is None:
        raise_error(ERR_INVALID_REQUEST, "shipment_date required")
    if drawing is None:
        raise_error(ERR_INVALID_REQUEST, "drawing_amount_minor_units required")

    sd = db.parse_dt(shipment_date)
    if sd is None:
        raise_error(ERR_INVALID_REQUEST, "shipment_date invalid")
    latest = db.parse_dt(lc.get("latest_shipment_date"))
    now = db.now()
    if latest is None:
        raise_error(ERR_INVALID_REQUEST, "LC.latest_shipment_date invalid")
    if sd > latest or sd > now:
        raise_error(ERR_SHIPMENT_OUT_OF_WINDOW, "shipment_date out of window")

    expiry = db.parse_dt(lc.get("expiry_date"))
    if expiry is None or now > expiry:
        raise_error(ERR_PRESENTATION_AFTER_EXPIRY, "presentation after LC expiry")

    if not isinstance(drawing, int) or isinstance(drawing, bool) or drawing <= 0:
        raise_error(ERR_INVALID_REQUEST, "drawing_amount_minor_units must be positive integer")

    avail = lc.get("available_amount_minor_units", 0)
    if drawing > avail:
        raise_error(ERR_LC_INSUFFICIENT_AVAILABLE, "drawing exceeds available")

    seq = db.next_presentation_seq(lc_id)
    p = db.insert("presentations", {
        "lc_id": lc_id,
        "presentation_seq": seq,
        "shipment_date": shipment_date,
        "presented_at": db.now_iso(),
        "drawing_amount_minor_units": drawing,
        "status": "SUBMITTED",
        "refusal_notified_at": None,
        "refusal_deadline": None,
    })
    audit.append("presentation.create", "PRESENTATION", p["id"], lc_id=lc_id,
                 before_state=None, after_state="SUBMITTED", payload=payload)
    return p


def get_presentation(presentation_id, role, user_id):
    p = db.get_by_id("presentations", presentation_id)
    if p is None:
        raise_error(ERR_NOT_FOUND, "presentation not found")
    lc = db.get_by_id("letters_of_credit", p["lc_id"])
    if lc is None:
        raise_error(ERR_NOT_FOUND, "lc not found")
    _enforce_presentation_visibility(p, lc, role, user_id)
    return p


def list_presentations_under_lc(lc_id, filters, limit, offset, role, user_id):
    lc = db.get_by_id("letters_of_credit", lc_id)
    if lc is None:
        raise_error(ERR_NOT_FOUND, "lc not found")
    # Role-based visibility on the LC
    if role == "Applicant" and lc.get("applicant_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "Applicant not on this LC")
    if role == "Beneficiary" and lc.get("beneficiary_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "Beneficiary not on this LC")
    if role == "IssuingBank" and lc.get("issuing_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "IssuingBank not on this LC")
    if role == "ConfirmingBank" and lc.get("confirming_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "ConfirmingBank not on this LC")

    use_filters = {"lc_id": lc_id}
    if filters and filters.get("status"):
        use_filters["status"] = filters["status"]
    rows, total = db.list_table("presentations", filters=use_filters,
                                sort_keys=("created_at", "id"), limit=limit, offset=offset)
    return rows, total


# ---------- Document attachment ----------

def attach_document(presentation_id, payload, user_id):
    p = db.get_by_id("presentations", presentation_id)
    if p is None:
        raise_error(ERR_NOT_FOUND, "presentation not found")
    lc = db.get_by_id("letters_of_credit", p["lc_id"])
    if lc is None:
        raise_error(ERR_NOT_FOUND, "lc not found")
    if lc.get("beneficiary_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "Beneficiary does not own this LC")

    # Documents frozen check
    if p["status"] != "SUBMITTED":
        raise_error(ERR_DOCUMENTS_FROZEN, f"documents frozen for presentation status {p['status']}")

    if not isinstance(payload, dict):
        raise_error(ERR_INVALID_REQUEST, "JSON body required")

    document_type = payload.get("document_type")
    if document_type not in DOC_TYPES:
        raise_error(ERR_INVALID_REQUEST, "invalid document_type")

    issuer = payload.get("issuer")
    if not isinstance(issuer, str) or not issuer.strip():
        raise_error(ERR_INVALID_REQUEST, "issuer required")
    document_date = payload.get("document_date")
    if not isinstance(document_date, str):
        raise_error(ERR_INVALID_REQUEST, "document_date required")

    # Required-docs check: type must be in LC.required_documents
    rd = lc.get("required_documents") or []
    if document_type not in rd:
        raise_error(ERR_DOCUMENT_NOT_REQUIRED_OR_DUPLICATE, "document_type not in LC.required_documents")

    # Duplicate check (only COMMERCIAL_INVOICE may legitimately duplicate)
    if document_type != "COMMERCIAL_INVOICE":
        existing = db.find_many("documents", presentation_id=presentation_id, document_type=document_type)
        if existing:
            raise_error(ERR_DOCUMENT_NOT_REQUIRED_OR_DUPLICATE, "duplicate document_type")

    stated_amount = payload.get("stated_amount_minor_units", 0)
    if stated_amount is None:
        stated_amount = 0
    if not isinstance(stated_amount, int) or isinstance(stated_amount, bool) or stated_amount < 0:
        raise_error(ERR_INVALID_REQUEST, "stated_amount_minor_units must be non-negative integer")
    stated_currency = payload.get("stated_currency") or lc.get("currency")
    payload_obj = payload.get("payload") or {}
    if not isinstance(payload_obj, dict):
        raise_error(ERR_INVALID_REQUEST, "payload must be object")

    doc = db.insert("documents", {
        "presentation_id": presentation_id,
        "document_type": document_type,
        "issuer": issuer.strip(),
        "document_date": document_date,
        "stated_amount_minor_units": stated_amount,
        "stated_currency": stated_currency,
        "payload": payload_obj,
    })
    audit.append("document.attach", "DOCUMENT", doc["id"], lc_id=lc["id"],
                 before_state=None, after_state="ATTACHED", payload=payload)
    return doc


# ---------- Examination ----------

def start_examination(presentation_id, payload, user_id):
    p = db.get_by_id("presentations", presentation_id)
    if p is None:
        raise_error(ERR_NOT_FOUND, "presentation not found")
    lc = db.get_by_id("letters_of_credit", p["lc_id"])
    if lc is None:
        raise_error(ERR_NOT_FOUND, "lc not found")
    if lc.get("issuing_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "IssuingBank does not own this LC")

    if p["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE_TRANSITION, "presentation not in SUBMITTED")

    if not isinstance(payload, dict):
        raise_error(ERR_INVALID_REQUEST, "JSON body required")
    primary = payload.get("primary_reviewer_id")
    secondary = payload.get("secondary_reviewer_id")
    if not isinstance(primary, str) or not primary.strip():
        raise_error(ERR_INVALID_REQUEST, "primary_reviewer_id required")
    if not isinstance(secondary, str) or not secondary.strip():
        raise_error(ERR_INVALID_REQUEST, "secondary_reviewer_id required")
    if primary == secondary:
        raise_error(ERR_REVIEWER_SAME_PERSON, "secondary_reviewer must differ from primary")

    presented_at = db.parse_dt(p["presented_at"])
    deadline = add_banking_days(presented_at, 5)

    db.update("presentations", presentation_id, {"status": "UNDER_EXAMINATION"})
    report = db.insert("examination_reports", {
        "presentation_id": presentation_id,
        "primary_reviewer_id": primary,
        "secondary_reviewer_id": secondary,
        "status": "IN_PROGRESS",
        "primary_outcome": None,
        "secondary_outcome": None,
        "final_outcome": None,
        "examined_at": None,
        "deadline_at": db.fmt_dt(deadline),
        "report_payload": None,
    })
    audit.append("examination.start", "EXAMINATION", report["id"], lc_id=lc["id"],
                 before_state="SUBMITTED", after_state="UNDER_EXAMINATION", payload=payload)
    return report


def primary_review(examination_id, payload, user_id):
    rep = db.get_by_id("examination_reports", examination_id)
    if rep is None:
        raise_error(ERR_NOT_FOUND, "examination not found")
    if not isinstance(payload, dict):
        raise_error(ERR_INVALID_REQUEST, "JSON body required")
    _check_version(rep, payload)

    if user_id != rep.get("primary_reviewer_id"):
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "X-User-ID must match primary_reviewer_id")

    if rep["status"] != "IN_PROGRESS":
        if rep.get("primary_outcome") is not None:
            raise_error(ERR_REVIEW_ALREADY_RECORDED, "primary review already recorded")
        raise_error(ERR_INVALID_STATE_TRANSITION, f"report in {rep['status']}")

    outcome = payload.get("primary_outcome")
    if outcome not in ("CLEAN", "DISCREPANT"):
        raise_error(ERR_INVALID_REQUEST, "primary_outcome must be CLEAN or DISCREPANT")

    discrepancies = payload.get("discrepancies") or []
    if outcome == "DISCREPANT" and not discrepancies:
        raise_error(ERR_INVALID_REQUEST, "discrepancies required when DISCREPANT")
    _validate_discrepancies(discrepancies, rep["presentation_id"])

    db.update("examination_reports", examination_id, {
        "primary_outcome": outcome,
        "status": "PRIMARY_DONE",
    })
    # delete any prior discrepancies for safety (shouldn't be any) and insert new
    db.delete_where("discrepancies", examination_report_id=examination_id)
    p = db.get_by_id("presentations", rep["presentation_id"])
    for d in discrepancies:
        db.insert("discrepancies", {
            "examination_report_id": examination_id,
            "presentation_id": rep["presentation_id"],
            "discrepancy_code": d["discrepancy_code"],
            "description": d["description"],
            "cited_document_id": d.get("cited_document_id"),
            "applicant_action": "PENDING",
            "action_at": None,
        })
    audit.append("examination.primary_review", "EXAMINATION", examination_id,
                 lc_id=p["lc_id"] if p else None,
                 before_state="IN_PROGRESS", after_state="PRIMARY_DONE", payload=payload)
    return db.get_by_id("examination_reports", examination_id)


def cross_check(examination_id, payload, user_id):
    rep = db.get_by_id("examination_reports", examination_id)
    if rep is None:
        raise_error(ERR_NOT_FOUND, "examination not found")
    if not isinstance(payload, dict):
        raise_error(ERR_INVALID_REQUEST, "JSON body required")
    _check_version(rep, payload)

    if user_id != rep.get("secondary_reviewer_id"):
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "X-User-ID must match secondary_reviewer_id")
    if rep.get("primary_reviewer_id") == rep.get("secondary_reviewer_id"):
        raise_error(ERR_REVIEWER_SAME_PERSON, "secondary equals primary")

    if rep["status"] == "IN_PROGRESS":
        raise_error(ERR_REVIEW_OUT_OF_ORDER, "primary review not yet submitted")

    if rep["status"] != "PRIMARY_DONE":
        if rep.get("secondary_outcome") is not None:
            raise_error(ERR_REVIEW_ALREADY_RECORDED, "secondary review already recorded")
        raise_error(ERR_INVALID_STATE_TRANSITION, f"report in {rep['status']}")

    outcome = payload.get("secondary_outcome")
    if outcome not in ("CLEAN", "DISCREPANT"):
        raise_error(ERR_INVALID_REQUEST, "secondary_outcome must be CLEAN or DISCREPANT")

    discrepancies = payload.get("discrepancies") or []
    if outcome == "DISCREPANT" and not discrepancies:
        raise_error(ERR_INVALID_REQUEST, "discrepancies required when DISCREPANT")
    _validate_discrepancies(discrepancies, rep["presentation_id"])

    primary_outcome = rep.get("primary_outcome")
    new_status = "CROSS_CHECK_DONE" if outcome == primary_outcome else "CONFLICT"

    db.update("examination_reports", examination_id, {
        "secondary_outcome": outcome,
        "status": new_status,
    })
    p = db.get_by_id("presentations", rep["presentation_id"])
    audit.append("examination.cross_check", "EXAMINATION", examination_id,
                 lc_id=p["lc_id"] if p else None,
                 before_state="PRIMARY_DONE", after_state=new_status, payload=payload)
    return db.get_by_id("examination_reports", examination_id)


def reset_examination(examination_id, payload, user_id):
    rep = db.get_by_id("examination_reports", examination_id)
    if rep is None:
        raise_error(ERR_NOT_FOUND, "examination not found")
    p = db.get_by_id("presentations", rep["presentation_id"])
    lc = db.get_by_id("letters_of_credit", p["lc_id"]) if p else None
    if lc is None or lc.get("issuing_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "IssuingBank does not own this LC")
    _check_version(rep, payload)

    if rep["status"] != "CONFLICT":
        raise_error(ERR_INVALID_STATE_TRANSITION, "report not in CONFLICT")

    db.delete_where("discrepancies", examination_report_id=examination_id)
    db.update("examination_reports", examination_id, {
        "status": "IN_PROGRESS",
        "primary_outcome": None,
        "secondary_outcome": None,
    })
    audit.append("examination.reset", "EXAMINATION", examination_id, lc_id=lc["id"],
                 before_state="CONFLICT", after_state="IN_PROGRESS", payload=payload)
    return db.get_by_id("examination_reports", examination_id)


def finalize_examination(examination_id, payload, user_id):
    rep = db.get_by_id("examination_reports", examination_id)
    if rep is None:
        raise_error(ERR_NOT_FOUND, "examination not found")
    p = db.get_by_id("presentations", rep["presentation_id"])
    lc = db.get_by_id("letters_of_credit", p["lc_id"]) if p else None
    if lc is None or lc.get("issuing_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "IssuingBank does not own this LC")
    _check_version(rep, payload)

    if rep["status"] != "CROSS_CHECK_DONE":
        raise_error(ERR_INVALID_STATE_TRANSITION, f"report not CROSS_CHECK_DONE (status={rep['status']})")

    if rep.get("primary_outcome") != rep.get("secondary_outcome"):
        # Should be CONFLICT in this case
        raise_error(ERR_INVALID_STATE_TRANSITION, "outcomes inconsistent")

    deadline = db.parse_dt(rep.get("deadline_at"))
    if deadline is not None and db.now() > deadline:
        raise_error(ERR_EXAMINATION_DEADLINE_PASSED, "examination deadline passed")

    final_outcome = "CLEAN" if rep["primary_outcome"] == "CLEAN" and rep["secondary_outcome"] == "CLEAN" else "DISCREPANT"

    docs_present = sorted({d["document_type"] for d in db.find_many("documents", presentation_id=p["id"])})
    report_payload = {
        "checklist_outcome": final_outcome,
        "primary_outcome": rep["primary_outcome"],
        "secondary_outcome": rep["secondary_outcome"],
        "documents_present": docs_present,
        "lc_required": list(lc.get("required_documents") or []),
    }

    db.update("examination_reports", examination_id, {
        "status": "FINALIZED",
        "final_outcome": final_outcome,
        "examined_at": db.now_iso(),
        "report_payload": report_payload,
    })

    new_pres_status = "EXAMINED_CLEAN" if final_outcome == "CLEAN" else "EXAMINED_DISCREPANT"
    db.update("presentations", p["id"], {"status": new_pres_status})

    audit.append("examination.finalize", "EXAMINATION", examination_id, lc_id=lc["id"],
                 before_state="CROSS_CHECK_DONE", after_state="FINALIZED", payload=payload)
    return db.get_by_id("examination_reports", examination_id)


def get_examination(examination_id):
    rep = db.get_by_id("examination_reports", examination_id)
    if rep is None:
        raise_error(ERR_NOT_FOUND, "examination not found")
    return rep


def list_discrepancies(examination_id, limit, offset):
    rep = db.get_by_id("examination_reports", examination_id)
    if rep is None:
        raise_error(ERR_NOT_FOUND, "examination not found")
    rows, total = db.list_table("discrepancies", filters={"examination_report_id": examination_id},
                                sort_keys=("created_at", "id"), limit=limit, offset=offset)
    return rows, total


def _validate_discrepancies(items, presentation_id):
    if not isinstance(items, list):
        raise_error(ERR_INVALID_REQUEST, "discrepancies must be array")
    valid_codes = {"MISSING_DOCUMENT", "LATE_PRESENTATION", "LATE_SHIPMENT",
                   "AMOUNT_MISMATCH", "DESCRIPTION_MISMATCH", "INCONSISTENT_DOCS",
                   "EXPIRED_LC", "CURRENCY_MISMATCH"}
    for d in items:
        if not isinstance(d, dict):
            raise_error(ERR_INVALID_REQUEST, "discrepancy must be object")
        if d.get("discrepancy_code") not in valid_codes:
            raise_error(ERR_INVALID_REQUEST, "invalid discrepancy_code")
        if not isinstance(d.get("description"), str) or not d["description"].strip():
            raise_error(ERR_INVALID_REQUEST, "discrepancy.description required")
        cited = d.get("cited_document_id")
        if cited is not None:
            doc = db.get_by_id("documents", cited)
            if doc is None or doc.get("presentation_id") != presentation_id:
                raise_error(ERR_NOT_FOUND, "cited_document_id not found")


# ---------- Discrepancy / Refusal flow ----------

def applicant_decision(presentation_id, payload, user_id):
    p = db.get_by_id("presentations", presentation_id)
    if p is None:
        raise_error(ERR_NOT_FOUND, "presentation not found")
    lc = db.get_by_id("letters_of_credit", p["lc_id"])
    if lc is None or lc.get("applicant_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "Applicant does not own this LC")

    _check_version(p, payload)

    if p["status"] != "EXAMINED_DISCREPANT":
        raise_error(ERR_INVALID_STATE_TRANSITION, "presentation not in EXAMINED_DISCREPANT")

    if not isinstance(payload, dict):
        raise_error(ERR_INVALID_REQUEST, "JSON body required")
    decision = payload.get("decision")
    if decision not in ("ACCEPTED", "REJECTED"):
        raise_error(ERR_INVALID_REQUEST, "decision must be ACCEPTED or REJECTED")

    # Find the FINALIZED examination report for this presentation
    reports = db.find_many("examination_reports", presentation_id=presentation_id)
    rep = None
    for r in reports:
        if r["status"] == "FINALIZED":
            rep = r
            break

    if decision == "ACCEPTED":
        if rep is not None:
            for d in db.find_many("discrepancies", examination_report_id=rep["id"]):
                db.update("discrepancies", d["id"], {
                    "applicant_action": "ACCEPTED",
                    "action_at": db.now_iso(),
                })
        db.update("presentations", presentation_id, {"status": "ACCEPTED_BY_APPLICANT"})
        audit.append("presentation.applicant_accept", "PRESENTATION", presentation_id, lc_id=lc["id"],
                     before_state="EXAMINED_DISCREPANT", after_state="ACCEPTED_BY_APPLICANT", payload=payload)
    else:
        if rep is not None:
            for d in db.find_many("discrepancies", examination_report_id=rep["id"]):
                db.update("discrepancies", d["id"], {
                    "applicant_action": "REJECTED",
                    "action_at": db.now_iso(),
                })
        notified = db.now()
        deadline = add_banking_days(notified, 5)
        db.update("presentations", presentation_id, {
            "status": "REFUSED",
            "refusal_notified_at": db.now_iso(),
            "refusal_deadline": db.fmt_dt(deadline),
        })
        audit.append("presentation.applicant_reject", "PRESENTATION", presentation_id, lc_id=lc["id"],
                     before_state="EXAMINED_DISCREPANT", after_state="REFUSED", payload=payload)
    return db.get_by_id("presentations", presentation_id)


def refuse_presentation(presentation_id, payload, user_id):
    p = db.get_by_id("presentations", presentation_id)
    if p is None:
        raise_error(ERR_NOT_FOUND, "presentation not found")
    lc = db.get_by_id("letters_of_credit", p["lc_id"])
    if lc is None or lc.get("issuing_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "IssuingBank does not own this LC")
    _check_version(p, payload)

    if p["status"] != "EXAMINED_DISCREPANT":
        raise_error(ERR_INVALID_STATE_TRANSITION, "presentation not EXAMINED_DISCREPANT")

    presented_at = db.parse_dt(p["presented_at"])
    elapsed = banking_days_between(presented_at, db.now())
    if elapsed > 5:
        raise_error(ERR_REFUSAL_DEADLINE_PASSED, "refusal deadline passed")

    if not isinstance(payload, dict):
        raise_error(ERR_INVALID_REQUEST, "JSON body required")
    reason = payload.get("refusal_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise_error(ERR_INVALID_REQUEST, "refusal_reason required")

    notified = db.now()
    deadline = add_banking_days(notified, 5)
    db.update("presentations", presentation_id, {
        "status": "REFUSED",
        "refusal_notified_at": db.now_iso(),
        "refusal_deadline": db.fmt_dt(deadline),
    })
    audit.append("presentation.refuse", "PRESENTATION", presentation_id, lc_id=lc["id"],
                 before_state="EXAMINED_DISCREPANT", after_state="REFUSED", payload=payload)
    return db.get_by_id("presentations", presentation_id)


def applicant_override(presentation_id, payload, user_id):
    p = db.get_by_id("presentations", presentation_id)
    if p is None:
        raise_error(ERR_NOT_FOUND, "presentation not found")
    lc = db.get_by_id("letters_of_credit", p["lc_id"])
    if lc is None or lc.get("applicant_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "Applicant does not own this LC")
    _check_version(p, payload)

    if p["status"] != "REFUSED":
        raise_error(ERR_INVALID_STATE_TRANSITION, "presentation not REFUSED")
    deadline = db.parse_dt(p.get("refusal_deadline"))
    if deadline is not None and db.now() > deadline:
        raise_error(ERR_REFUSAL_DEADLINE_PASSED, "refusal deadline passed")

    # Each Discrepancy → ACCEPTED
    reports = db.find_many("examination_reports", presentation_id=presentation_id)
    for r in reports:
        for d in db.find_many("discrepancies", examination_report_id=r["id"]):
            db.update("discrepancies", d["id"], {
                "applicant_action": "ACCEPTED",
                "action_at": db.now_iso(),
            })

    db.update("presentations", presentation_id, {
        "status": "ACCEPTED_BY_APPLICANT",
        "refusal_notified_at": None,
        "refusal_deadline": None,
    })
    audit.append("presentation.applicant_override", "PRESENTATION", presentation_id, lc_id=lc["id"],
                 before_state="REFUSED", after_state="ACCEPTED_BY_APPLICANT", payload=payload)
    return db.get_by_id("presentations", presentation_id)


def return_documents(presentation_id, payload, user_id):
    p = db.get_by_id("presentations", presentation_id)
    if p is None:
        raise_error(ERR_NOT_FOUND, "presentation not found")
    lc = db.get_by_id("letters_of_credit", p["lc_id"])
    if lc is None or lc.get("issuing_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "IssuingBank does not own this LC")
    _check_version(p, payload)

    if p["status"] != "REFUSED":
        raise_error(ERR_INVALID_STATE_TRANSITION, "presentation not REFUSED")

    notified = db.parse_dt(p.get("refusal_notified_at"))
    if notified is not None:
        elapsed = banking_days_between(notified, db.now())
        if elapsed > 7:
            raise_error(ERR_RETURN_WINDOW_PASSED, "return window passed")

    db.update("presentations", presentation_id, {"status": "RETURNED"})
    audit.append("presentation.return", "PRESENTATION", presentation_id, lc_id=lc["id"],
                 before_state="REFUSED", after_state="RETURNED", payload=payload)
    return db.get_by_id("presentations", presentation_id)
