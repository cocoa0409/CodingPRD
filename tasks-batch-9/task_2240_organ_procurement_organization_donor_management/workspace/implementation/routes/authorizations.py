"""Authorization packets: registry branch, next-of-kin hierarchy, documents, finalize."""

from flask import Blueprint

from constants import (
    AUTHORIZATION_TERMINAL,
    DOCUMENT_TYPES,
    NOK_RANK,
    NOK_RESPONSES,
    RELATIONSHIPS,
)
from db import base_record, clock_now, db, lock, ordered
from errors import ApiError
from middleware import authenticate
from response import ok, paginated
from services.domain import (
    contacts_of_authorization,
    recompute_documentation,
    rescission_cascade,
    touch,
)
from validation import Body, page, pagination

bp = Blueprint("authorizations", __name__)


def resolve_authorization(auth_id):
    record = db.authorizations.get(auth_id)
    if record is None:
        raise ApiError("ERR_AUTHORIZATION_NOT_FOUND")
    return record


def resolve_referral(referral_id):
    record = db.death_referrals.get(referral_id)
    if record is None:
        raise ApiError("ERR_REFERRAL_NOT_FOUND")
    return record


@bp.post("/opo/death-referrals/<referral_id>/authorizations")
def open_authorization(referral_id):
    authenticate("AuthorizationSpecialist")
    with lock:
        referral = resolve_referral(referral_id)
        body = Body()
        registry_hit = body.boolean("registry_hit", required=True)
        registry_document_ref = body.string("registry_document_ref", min_len=1)
        if registry_hit and registry_document_ref is None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "registry_document_ref is required when registry_hit is true.",
            )

        if referral["status"] != "SCREEN_CLEARED":
            raise ApiError("ERR_AUTHORIZATION_NOT_OPENABLE")
        for existing in db.authorizations.values():
            if existing["referral_id"] == referral_id and existing["status"] not in AUTHORIZATION_TERMINAL:
                raise ApiError("ERR_AUTHORIZATION_NOT_OPENABLE")

        record = base_record()
        record.update(
            {
                "referral_id": referral_id,
                "status": "PENDING_REGISTRY",
                "registry_hit": registry_hit,
                "registry_document_ref": registry_document_ref,
                "authorization_basis": None,
                "consenting_rank": None,
                "highest_rank_attempted": None,
                "document_types_present": [],
                "required_document_types": [],
                "documentation_complete": False,
                "witness_name": None,
                "consent_recorded_by_user_id": None,
                "finalized_by_user_id": None,
                "rescinded_reason": None,
            }
        )
        if registry_hit:
            record["status"] = "REGISTRY_CONFIRMED"
            record["authorization_basis"] = "FIRST_PERSON_REGISTRY"
            record["document_types_present"] = ["REGISTRY_SCREENSHOT"]
        else:
            record["status"] = "NOK_REQUIRED"
            record["authorization_basis"] = "LEGAL_NEXT_OF_KIN"
        recompute_documentation(record)
        db.authorizations[record["id"]] = record

        referral["status"] = "AUTH_PENDING"
        touch(referral)
        return ok(record, 201)


@bp.get("/opo/death-referrals/<referral_id>/authorizations")
def list_authorizations_for_referral(referral_id):
    authenticate("OpoAdmin", "AuthorizationSpecialist", "MedicalDirector", "DonorCoordinator")
    with lock:
        resolve_referral(referral_id)
        limit, offset = pagination()
        rows = ordered([a for a in db.authorizations.values() if a["referral_id"] == referral_id])
        return paginated(page(rows, limit, offset), limit, offset, len(rows))


@bp.get("/opo/authorizations/<auth_id>")
def read_authorization(auth_id):
    authenticate("OpoAdmin", "AuthorizationSpecialist", "MedicalDirector", "DonorCoordinator")
    with lock:
        return ok(resolve_authorization(auth_id))


@bp.post("/opo/authorizations/<auth_id>/nok-contacts")
def record_nok_contact(auth_id):
    user_id, _role = authenticate("AuthorizationSpecialist")
    with lock:
        auth = resolve_authorization(auth_id)
        body = Body()
        relationship = body.enum("relationship", RELATIONSHIPS, required=True)
        response = body.enum("response", NOK_RESPONSES, required=True)
        contact_note = body.string("contact_note")

        contactable = auth["status"] == "NOK_REQUIRED" or (
            response == "OBJECTION" and auth["status"] == "AUTHORIZED"
        )
        if not contactable:
            raise ApiError("ERR_AUTHORIZATION_NOT_CONTACTABLE")

        rank = NOK_RANK[relationship]
        existing = contacts_of_authorization(auth_id)

        if response in ("CONSENT", "DECLINE"):
            for better in range(1, rank):
                if not any(
                    c["rank"] == better and c["response"] in ("DECLINE", "UNREACHABLE")
                    for c in existing
                ):
                    raise ApiError("ERR_NOK_HIERARCHY_VIOLATION")
        if response == "CONSENT":
            if any(c["rank"] < rank and c["response"] == "OBJECTION" for c in existing):
                raise ApiError("ERR_NOK_HIERARCHY_VIOLATION")

        record = base_record(managed=False)
        record.update(
            {
                "authorization_id": auth_id,
                "relationship": relationship,
                "rank": rank,
                "contacted_at": clock_now(),
                "response": response,
                "contact_note": contact_note,
                "recorded_by_user_id": user_id,
            }
        )
        db.nok_contacts[record["id"]] = record
        all_contacts = existing + [record]

        current_high = auth["highest_rank_attempted"]
        auth["highest_rank_attempted"] = rank if current_high is None else min(current_high, rank)
        touch(auth)

        referral = db.death_referrals.get(auth["referral_id"])

        if response == "CONSENT" and auth["status"] == "NOK_REQUIRED":
            auth["status"] = "NOK_CONSENTED"
            auth["consenting_rank"] = rank
            auth["consent_recorded_by_user_id"] = user_id
            touch(auth)
        elif response == "DECLINE" and rank == 1 and auth["status"] == "NOK_REQUIRED":
            auth["status"] = "DECLINED"
            touch(auth)
            if referral is not None and referral["status"] == "AUTH_PENDING":
                referral["status"] = "NOT_CONVERTED"
                touch(referral)
        elif response == "UNREACHABLE" and auth["status"] == "NOK_REQUIRED":
            covered = {c["relationship"] for c in all_contacts}
            consented = any(c["response"] == "CONSENT" for c in all_contacts)
            if set(RELATIONSHIPS).issubset(covered) and not consented:
                auth["status"] = "UNABLE_TO_LOCATE"
                touch(auth)
                if referral is not None and referral["status"] == "AUTH_PENDING":
                    referral["status"] = "NOT_CONVERTED"
                    touch(referral)
        elif response == "OBJECTION" and auth["status"] == "AUTHORIZED":
            if (
                auth["authorization_basis"] == "LEGAL_NEXT_OF_KIN"
                and auth["consenting_rank"] is not None
                and rank < auth["consenting_rank"]
            ):
                auth["status"] = "RESCINDED"
                auth["rescinded_reason"] = "HIGHER_RANK_OBJECTION"
                touch(auth)
                rescission_cascade(auth)

        return ok(record, 201)


@bp.get("/opo/authorizations/<auth_id>/nok-contacts")
def list_nok_contacts(auth_id):
    authenticate("OpoAdmin", "AuthorizationSpecialist", "MedicalDirector")
    with lock:
        resolve_authorization(auth_id)
        limit, offset = pagination()
        rows = contacts_of_authorization(auth_id)
        return paginated(page(rows, limit, offset), limit, offset, len(rows))


@bp.post("/opo/authorizations/<auth_id>/documents")
def file_document(auth_id):
    authenticate("AuthorizationSpecialist")
    with lock:
        auth = resolve_authorization(auth_id)
        body = Body()
        document_type = body.enum("document_type", DOCUMENT_TYPES, required=True)
        witness_name = body.string("witness_name", min_len=1)

        if auth["status"] not in ("NOK_CONSENTED", "DOCUMENT_DEFICIENT"):
            raise ApiError("ERR_AUTHORIZATION_NOT_FINALIZABLE")

        present = list(auth["document_types_present"] or [])
        if document_type not in present:
            present.append(document_type)
        auth["document_types_present"] = present
        if witness_name is not None:
            auth["witness_name"] = witness_name
        recompute_documentation(auth)
        if auth["status"] == "DOCUMENT_DEFICIENT":
            auth["status"] = "NOK_CONSENTED"
        touch(auth)
        return ok(auth)


@bp.post("/opo/authorizations/<auth_id>/finalize")
def finalize_authorization(auth_id):
    user_id, _role = authenticate("AuthorizationSpecialist")
    with lock:
        auth = resolve_authorization(auth_id)
        Body()

        if auth["status"] not in ("REGISTRY_CONFIRMED", "NOK_CONSENTED", "DOCUMENT_DEFICIENT"):
            raise ApiError("ERR_AUTHORIZATION_NOT_FINALIZABLE")

        if (
            auth["consent_recorded_by_user_id"] is not None
            and auth["consent_recorded_by_user_id"] == user_id
        ):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

        recompute_documentation(auth)
        if auth["documentation_complete"]:
            auth["status"] = "AUTHORIZED"
            auth["finalized_by_user_id"] = user_id
            touch(auth)
            return ok(auth)

        # The deficiency move is recorded even though the caller receives 422.
        if auth["status"] == "NOK_CONSENTED":
            auth["status"] = "DOCUMENT_DEFICIENT"
            touch(auth)
        raise ApiError("ERR_AUTHORIZATION_DOCUMENTATION_INCOMPLETE")
