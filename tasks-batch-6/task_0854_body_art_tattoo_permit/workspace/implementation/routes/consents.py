"""Minor-consent routes — PRD §3.6."""

from flask import Blueprint

import config
import domain
import serialize
import store
import validate as V
from auth import authenticate, require_owns_establishment
from envelope import array_response, send, watch
from errors import ApiError
from util import days

bp = Blueprint("consents", __name__)

READ_ROLES = ["HealthOfficer", "Inspector", "RecordsClerk", "EstablishmentOperator"]


@bp.post("/body-art/minor-consents")
def create_minor_consent():
    caller = authenticate(["EstablishmentOperator"])
    data = V.body()
    establishment_id = V.req_id(data, "establishment_id")
    minor_full_name = V.req_string(data, "minor_full_name", 1, 120)
    minor_age_at_signing = V.req_int(data, "minor_age_at_signing", minimum=0, maximum=17)
    guardian_full_name = V.req_string(data, "guardian_full_name", 1, 120)
    guardian_id_document_type = V.req_enum(
        data, "guardian_id_document_type", config.GUARDIAN_ID_DOCUMENT_TYPES
    )
    guardian_id_document_number = V.req_string(
        data, "guardian_id_document_number", 1, 40
    )
    authorized_procedure_type = V.req_enum(
        data, "authorized_procedure_type", config.PROCEDURE_TYPES
    )
    consent_signed_at = V.req_datetime(data, "consent_signed_at")

    est = V.get_establishment(establishment_id)
    require_owns_establishment(caller, establishment_id)

    rec = domain.new_record(
        {
            "establishment_id": est["id"],
            "minor_full_name": minor_full_name,
            "minor_age_at_signing": minor_age_at_signing,
            "guardian_full_name": guardian_full_name,
            "guardian_id_document_type": guardian_id_document_type,
            "guardian_id_document_number": guardian_id_document_number,
            "authorized_procedure_type": authorized_procedure_type,
            "consent_signed_at": consent_signed_at,
            "expires_at": consent_signed_at + days(config.MINOR_CONSENT_VALIDITY_DAYS),
            "verification_status": "PENDING",
            "verified_by_user_id": None,
            "rejection_reason": None,
        }
    )
    store.minor_consents[rec["id"]] = rec
    return send(lambda: serialize.minor_consent(rec), 201)


@bp.get("/body-art/minor-consents/<minor_consent_id>")
def read_minor_consent(minor_consent_id):
    authenticate(READ_ROLES)
    rec = V.get_minor_consent(minor_consent_id)
    return send(lambda: serialize.minor_consent(rec), 200)


@bp.get("/body-art/minor-consents")
def list_minor_consents():
    authenticate(READ_ROLES)
    limit, offset = V.pagination()
    establishment_id = V.filter_string("establishment_id")
    verification_status = V.filter_enum(
        "verification_status", config.CONSENT_VERIFICATION_STATUSES
    )

    rows = store.sorted_rows(store.minor_consents)
    if establishment_id is not None:
        rows = [r for r in rows if r["establishment_id"] == establishment_id]
    if verification_status is not None:
        rows = [r for r in rows if r["verification_status"] == verification_status]
    page, total = V.paginate(rows, limit, offset)
    return array_response(
        [serialize.minor_consent(r) for r in page], limit, offset, total
    )


@bp.post("/body-art/minor-consents/<minor_consent_id>/verify")
def verify_minor_consent(minor_consent_id):
    caller = authenticate(["RecordsClerk"])
    rec = V.get_minor_consent(minor_consent_id)
    data = V.body()
    decision = V.req_enum(data, "decision", config.CONSENT_DECISIONS)
    rejection_reason = V.opt_string(data, "rejection_reason", 0, None)

    if rec["verification_status"] != "PENDING":
        raise ApiError("ERR_CONSENT_STATE_INVALID")

    watch(rec)
    if decision == "VERIFY":
        if rec["expires_at"] <= store.now():
            raise ApiError("ERR_MINOR_CONSENT_EXPIRED")
        rec["verification_status"] = "VERIFIED"
        rec["verified_by_user_id"] = caller.user_id
    else:
        rec["verification_status"] = "REJECTED"
        rec["verified_by_user_id"] = caller.user_id
        rec["rejection_reason"] = rejection_reason
    return send(lambda: serialize.minor_consent(rec), 200)
