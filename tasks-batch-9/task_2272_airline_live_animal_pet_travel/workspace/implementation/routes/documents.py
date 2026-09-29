"""Health documents: submission and the review lifecycle."""
from db import base_row, parse_iso, store, touch
from middleware import (ALL_ROLES, ROLE_RESERVATIONS_AGENT, ROLE_VETERINARY_REVIEWER,
                        register, resolve_fk)
from response import created_response, object_response
from services import calc, domain, serialize
from routes.helpers import COUNTRY_PATTERN, DOCUMENT_TYPES, listing

AGENT = [ROLE_RESERVATIONS_AGENT]
VET = [ROLE_VETERINARY_REVIEWER]

DOCUMENT_SCHEMA = {
    "animal_record_id": {"type": "string", "required": True},
    "document_type": {"type": "enum", "required": True, "values": DOCUMENT_TYPES},
    "issuing_country_code": {"type": "string", "required": True,
                             "pattern": COUNTRY_PATTERN},
    "issued_at": {"type": "datetime", "required": True},
    "expires_at": {"type": "datetime", "required": True},
}

RESUBMIT_SCHEMA = {
    "issued_at": {"type": "datetime", "required": True},
    "expires_at": {"type": "datetime", "required": True},
}

REJECT_SCHEMA = {"rejection_reason": {"type": "string", "nullable": True}}


def _set_compliance(document, status):
    animal = store.animals.get(document["animal_record_id"])
    if animal is None:
        return None
    reservation = domain.reservation_of_animal(animal)
    if reservation["compliance_status"] != status:
        reservation["compliance_status"] = status
        touch(reservation)
    return reservation


def init(app):
    @register(app, "/health-documents", "POST", AGENT, schema=DOCUMENT_SCHEMA)
    def create_document(ctx):
        body = ctx.body
        animal = resolve_fk("animal", body["animal_record_id"])
        domain.require(animal["status"] in ("DRAFT", "SCREENED", "TRAVEL_READY"),
                       "ERR_ANIMAL_INVALID_STATE",
                       "a %s animal cannot receive a document" % animal["status"])
        domain.require(parse_iso(body["expires_at"]) > parse_iso(body["issued_at"]),
                       "ERR_INVALID_TIME_RANGE",
                       "expires_at must be strictly after issued_at")
        row = base_row()
        row.update({
            "animal_record_id": animal["id"],
            "document_type": body["document_type"],
            "issuing_country_code": body["issuing_country_code"],
            "issued_at": body["issued_at"],
            "expires_at": body["expires_at"],
            "revision_count": 0,
            "reviewed_by_user_id": None,
            "status": "SUBMITTED",
        })
        store.docs[row["id"]] = row
        return created_response(serialize.dump("document", row))

    @register(app, "/animal-records/<rid>/health-documents", "GET", ALL_ROLES,
              paginated=True, path_entity="animal")
    def list_animal_documents(ctx):
        rows = domain.documents_of_animal(ctx.row)
        return listing("document", rows, ctx,
                       [("document_type", "document_type", "str"),
                        ("status", "status", "str")])

    @register(app, "/health-documents/<rid>", "GET", ALL_ROLES, path_entity="document")
    def get_document(ctx):
        return object_response(serialize.dump("document", ctx.row))

    @register(app, "/health-documents/<rid>/start-review", "POST", VET, schema={},
              path_entity="document")
    def start_review(ctx):
        document = ctx.row
        domain.require(document["status"] == "SUBMITTED", "ERR_DOCUMENT_INVALID_STATE",
                       "a %s document cannot be taken under review"
                       % document["status"])
        animal = store.animals[document["animal_record_id"]]
        domain.require(animal["status"] not in ("DENIED", "DECEASED", "DELIVERED"),
                       "ERR_ANIMAL_INVALID_STATE",
                       "a %s animal has no reviewable document" % animal["status"])
        document["status"] = "UNDER_REVIEW"
        touch(document)
        reservation = domain.reservation_of_animal(animal)
        if reservation["compliance_status"] in ("UNVERIFIED", "DEFICIENT", "EXPIRED"):
            reservation["compliance_status"] = "IN_REVIEW"
            touch(reservation)
        return object_response(serialize.dump("document", document))

    @register(app, "/health-documents/<rid>/verify", "POST", VET, schema={},
              path_entity="document")
    def verify_document(ctx):
        document = ctx.row
        domain.require(document["status"] == "UNDER_REVIEW",
                       "ERR_DOCUMENT_INVALID_STATE",
                       "a %s document cannot be verified" % document["status"])
        animal = store.animals[document["animal_record_id"]]
        first = domain.first_segment(animal)
        if first is not None:
            leg = domain.leg_of_segment(first)
            origin_country = store.stations[leg["origin_station_id"]]["country_code"]
            domain.require(document["issuing_country_code"] == origin_country,
                           "ERR_DOCUMENT_ISSUER_MISMATCH",
                           "the document was issued in %s but the itinerary starts in %s"
                           % (document["issuing_country_code"], origin_country))
        if parse_iso(document["expires_at"]) > store.clock:
            document["status"] = "VERIFIED"
        else:
            document["status"] = "EXPIRED"
        document["reviewed_by_user_id"] = ctx.user_id
        touch(document)
        return object_response(serialize.dump("document", document))

    @register(app, "/health-documents/<rid>/reject", "POST", VET, schema=REJECT_SCHEMA,
              path_entity="document")
    def reject_document(ctx):
        document = ctx.row
        domain.require(document["status"] == "UNDER_REVIEW",
                       "ERR_DOCUMENT_INVALID_STATE",
                       "a %s document cannot be rejected" % document["status"])
        document["status"] = "REJECTED"
        document["reviewed_by_user_id"] = ctx.user_id
        touch(document)
        _set_compliance(document, "DEFICIENT")
        animal = store.animals.get(document["animal_record_id"])
        if animal is not None and animal["status"] == "TRAVEL_READY":
            animal["status"] = "SCREENED"
            touch(animal)
        return object_response(serialize.dump("document", document))

    @register(app, "/health-documents/<rid>/resubmit", "POST", AGENT,
              schema=RESUBMIT_SCHEMA, path_entity="document")
    def resubmit_document(ctx):
        document = ctx.row
        domain.require(document["status"] == "REJECTED", "ERR_DOCUMENT_INVALID_STATE",
                       "a %s document cannot be resubmitted" % document["status"])
        domain.require(document["revision_count"] < calc.MAX_DOCUMENT_REVISIONS,
                       "ERR_DOC_REVISION_LIMIT_REACHED",
                       "the document has reached %d revisions"
                       % calc.MAX_DOCUMENT_REVISIONS)
        domain.require(parse_iso(ctx.body["expires_at"])
                       > parse_iso(ctx.body["issued_at"]),
                       "ERR_INVALID_TIME_RANGE",
                       "expires_at must be strictly after issued_at")
        document["issued_at"] = ctx.body["issued_at"]
        document["expires_at"] = ctx.body["expires_at"]
        document["revision_count"] += 1
        document["reviewed_by_user_id"] = None
        document["status"] = "SUBMITTED"
        touch(document)
        return object_response(serialize.dump("document", document))
