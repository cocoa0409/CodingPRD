"""Import-monitoring records (PRD 3.2) and sustainability certificates (PRD 3.5)."""

import serializers
import services
from auth import supplier_scope
from common import base_record, sort_records, touch
from envelope import obj_result
from errors import fail
from store import db
from validators import opt_id, opt_str, req_datetime, req_enum, req_str
from web import listing, route

SIMP_READ_ROLES = ("ChainAdmin", "SeafoodManager", "ComplianceOfficer", "SupplierRep")
CERT_READ_ROLES = (
    "ChainAdmin",
    "SeafoodManager",
    "ComplianceOfficer",
    "MerchandisingLead",
    "SupplierRep",
)
SIMP_DECISIONS = ("ACCEPT", "DEFICIENT")
CERT_REVIEW_DECISIONS = ("APPROVE", "REJECT")
CERT_ENFORCE_DECISIONS = ("REVOKE", "SWEEP")


def resolve_document(document_id):
    """SupplierRep scope reaches a document through its lot's supplier."""
    document = db.simp_documents.get(document_id)
    if document is not None:
        lot = db.lots.get(document["lot_id"])
        if lot is not None:
            supplier_scope(lot["supplier_id"])
    else:
        fail("ERR_SIMP_DOCUMENT_NOT_FOUND")
    return document


def resolve_certification(certification_id):
    certification = db.certifications.get(certification_id)
    if certification is not None:
        supplier_scope(certification["supplier_id"])
    else:
        fail("ERR_CERTIFICATION_NOT_FOUND")
    return certification


# --------------------------------------------------------------------------
# import-monitoring records
# --------------------------------------------------------------------------

@route("/simp-documents", methods=["POST"], roles=("SupplierRep",))
def create_document(body):
    raw_lot = opt_id(body, "lot_id")
    lot = None
    if raw_lot is not None:
        lot = db.lots.get(raw_lot)
        if lot is not None:
            supplier_scope(lot["supplier_id"])
        else:
            fail("ERR_LOT_NOT_FOUND")

    lot_id = req_str(body, "lot_id")
    harvesting_vessel_name = req_str(body, "harvesting_vessel_name")
    harvest_date = req_datetime(body, "harvest_date")
    landing_date = req_datetime(body, "landing_date")
    chain_of_custody_ref = req_str(body, "chain_of_custody_ref")

    if harvest_date > landing_date:
        fail("ERR_SIMP_DATE_ORDER")

    record = base_record("simp_document")
    record.update(
        {
            "lot_id": lot_id,
            "harvesting_vessel_name": harvesting_vessel_name,
            "harvest_date": harvest_date,
            "landing_date": landing_date,
            "chain_of_custody_ref": chain_of_custody_ref,
            "status": "DRAFT",
            "review_note": None,
            "reviewed_at": None,
            "amendment_count": 0,
        }
    )
    db.simp_documents[record["id"]] = record
    return obj_result(serializers.simp_document, record, 201)


@route("/simp-documents/<document_id>", methods=["GET"], roles=SIMP_READ_ROLES)
def get_document(body, document_id):
    return obj_result(serializers.simp_document, resolve_document(document_id))


@route("/simp-documents", methods=["GET"], roles=SIMP_READ_ROLES)
def list_documents(body):
    return listing(
        serializers.simp_document,
        list(db.simp_documents.values()),
        string_fields=("lot_id", "status"),
    )


@route("/simp-documents/<document_id>/submit", methods=["POST"], roles=("SupplierRep",))
def submit_document(body, document_id):
    document = resolve_document(document_id)
    chain_of_custody_ref = opt_str(body, "chain_of_custody_ref")

    if document["status"] not in ("DRAFT", "DEFICIENT"):
        fail("ERR_SIMP_STATE_INVALID")
    if document["harvest_date"] > document["landing_date"]:
        fail("ERR_SIMP_DATE_ORDER")

    if chain_of_custody_ref is not None:
        document["chain_of_custody_ref"] = chain_of_custody_ref
    if document["status"] == "DEFICIENT":
        document["amendment_count"] += 1
    document["status"] = "SUBMITTED"
    touch(document)
    return obj_result(serializers.simp_document, document)


@route("/simp-documents/<document_id>/review", methods=["POST"], roles=("ComplianceOfficer",))
def review_document(body, document_id):
    document = db.simp_documents.get(document_id)
    if document is None:
        fail("ERR_SIMP_DOCUMENT_NOT_FOUND")

    decision = req_enum(body, "decision", SIMP_DECISIONS)
    review_note = opt_str(body, "review_note")

    if document["status"] != "SUBMITTED":
        fail("ERR_SIMP_STATE_INVALID")

    lot = db.lots.get(document["lot_id"])
    counter = services.lot_counter(lot) if lot is not None else None

    document["review_note"] = review_note
    document["reviewed_at"] = db.clock
    if decision == "ACCEPT":
        document["status"] = "ACCEPTED"
        touch(document)
        findings = sort_records(
            [
                violation
                for violation in db.violations.values()
                if violation["lot_id"] == document["lot_id"]
                and violation["category"] == "SIMP_DEFICIENT"
                and violation["status"] == "OPEN"
            ]
        )
        for violation in findings:
            violation["status"] = "CURED"
            violation["cured_at"] = db.clock
            touch(violation)
        if findings:
            services.derive_posture(counter)
    else:
        document["status"] = "DEFICIENT"
        touch(document)
        services.create_violation(
            counter,
            document["lot_id"],
            "SIMP_DEFICIENT",
            "Import-monitoring record found deficient on review.",
        )
    return obj_result(serializers.simp_document, document)


# --------------------------------------------------------------------------
# sustainability certificates
# --------------------------------------------------------------------------

@route("/certifications", methods=["POST"], roles=("SupplierRep",))
def file_certification(body):
    raw_counter = opt_id(body, "counter_id")
    raw_supplier = opt_id(body, "supplier_id")
    raw_species = opt_id(body, "species_id")

    supplier_scope(raw_supplier)

    if raw_counter is not None and db.counters.get(raw_counter) is None:
        fail("ERR_COUNTER_NOT_FOUND")
    if raw_supplier is not None and db.suppliers.get(raw_supplier) is None:
        fail("ERR_SUPPLIER_NOT_FOUND")
    if raw_species is not None and db.species.get(raw_species) is None:
        fail("ERR_SPECIES_NOT_FOUND")

    counter_id = req_str(body, "counter_id")
    supplier_id = req_str(body, "supplier_id")
    species_id = req_str(body, "species_id")
    program_name = req_str(body, "program_name")
    certificate_number = req_str(body, "certificate_number")
    valid_from = req_datetime(body, "valid_from")
    valid_until = req_datetime(body, "valid_until")
    claim_text = req_str(body, "claim_text")

    record = base_record("certification")
    record.update(
        {
            "counter_id": counter_id,
            "supplier_id": supplier_id,
            "species_id": species_id,
            "program_name": program_name,
            "certificate_number": certificate_number,
            "valid_from": valid_from,
            "valid_until": valid_until,
            "claim_text": claim_text,
            "status": "PENDING_REVIEW",
            "review_note": None,
        }
    )
    db.certifications[record["id"]] = record
    return obj_result(serializers.certification, record, 201)


@route("/certifications/<certification_id>", methods=["GET"], roles=CERT_READ_ROLES)
def get_certification(body, certification_id):
    return obj_result(serializers.certification, resolve_certification(certification_id))


@route("/certifications", methods=["GET"], roles=CERT_READ_ROLES)
def list_certifications(body):
    return listing(
        serializers.certification,
        list(db.certifications.values()),
        string_fields=("counter_id", "supplier_id", "species_id", "status"),
    )


@route("/certifications/<certification_id>/review", methods=["POST"], roles=("ComplianceOfficer",))
def review_certification(body, certification_id):
    certification = db.certifications.get(certification_id)
    if certification is None:
        fail("ERR_CERTIFICATION_NOT_FOUND")

    decision = req_enum(body, "decision", CERT_REVIEW_DECISIONS)
    review_note = opt_str(body, "review_note")

    if certification["status"] != "PENDING_REVIEW":
        fail("ERR_CERTIFICATION_STATE_INVALID")

    if decision == "APPROVE":
        species = db.species.get(certification["species_id"])
        if species is None or not species["sustainability_program_eligible"]:
            fail("ERR_SPECIES_NOT_CLAIM_ELIGIBLE")
        services.check_validity_window(certification)
        certification["status"] = "ACTIVE"
    else:
        certification["status"] = "REVOKED"
    certification["review_note"] = review_note
    touch(certification)
    return obj_result(serializers.certification, certification)


@route("/certifications/<certification_id>/enforce", methods=["POST"], roles=("ComplianceOfficer",))
def enforce_certification(body, certification_id):
    certification = db.certifications.get(certification_id)
    if certification is None:
        fail("ERR_CERTIFICATION_NOT_FOUND")

    decision = req_enum(body, "decision", CERT_ENFORCE_DECISIONS)
    note = opt_str(body, "note")

    if certification["status"] != "ACTIVE":
        fail("ERR_CERTIFICATION_STATE_INVALID")
    if decision == "SWEEP" and db.clock < certification["valid_until"]:
        # The expiry sweep is only legal once the window has actually elapsed.
        fail("ERR_CERTIFICATION_STATE_INVALID")

    certification["status"] = "REVOKED" if decision == "REVOKE" else "EXPIRED"
    if note is not None:
        certification["review_note"] = note
    touch(certification)
    services.enforce_certification_cascade(certification)
    return obj_result(serializers.certification, certification)
