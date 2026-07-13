"""Income-document endpoints (§3.3)."""
from flask import request

from store import db, stamp_new, touch, public
from common import (
    endpoint, object_response, get_body, req_int, req_str, req_enum, ApiError,
)
from helpers import get_path, get_ref, list_collection, forbid, household_of_income_document

DOC_TYPES = {"PAYSTUB", "TAX_RETURN", "BENEFIT_LETTER", "SELF_ATTESTATION"}
VERIFY_OUTCOMES = {"VERIFIED", "REJECTED"}


def register(app):
    @app.route("/liheap/income-documents", methods=["POST"])
    @endpoint(["Applicant", "Caseworker"])
    def create_income_document(role, user_id):
        body = get_body()
        application_id = req_str(body, "application_id")
        doc_type = req_enum(body, "doc_type", DOC_TYPES)
        reported_income_cents = req_int(body, "reported_income_cents", minimum=0)
        application = get_ref(db.applications, application_id)
        if role == "Applicant" and application["household_id"] != user_id:
            forbid()
        doc = {
            "application_id": application_id,
            "doc_type": doc_type,
            "reported_income_cents": reported_income_cents,
            "verified_income_cents": None,
            "status": "PENDING",
        }
        stamp_new(doc)
        db.income_documents[doc["id"]] = doc
        return object_response(public(doc), 201)

    @app.route("/liheap/income-documents/<id_>", methods=["GET"])
    @endpoint(["Applicant", "Caseworker"])
    def get_income_document(role, user_id, id_):
        doc = get_path(db.income_documents, id_)
        if role == "Applicant" and household_of_income_document(doc) != user_id:
            forbid()
        return object_response(public(doc), 200)

    @app.route("/liheap/income-documents", methods=["GET"])
    @endpoint(["Caseworker", "ProgramAdmin"])
    def list_income_documents(role, user_id):
        filters = {
            "application_id": request.args.get("application_id"),
            "status": request.args.get("status"),
        }
        return list_collection(db.income_documents, "income_documents", filters)

    @app.route("/liheap/income-documents/<id_>/verify", methods=["POST"])
    @endpoint(["Caseworker"])
    def verify_income_document(role, user_id, id_):
        doc = get_path(db.income_documents, id_)
        body = get_body()
        outcome = req_enum(body, "outcome", VERIFY_OUTCOMES)
        verified_income_cents = None
        if outcome == "VERIFIED":
            verified_income_cents = req_int(body, "verified_income_cents", minimum=0)
        if doc["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", "Document is not PENDING")
        if outcome == "VERIFIED":
            doc["status"] = "VERIFIED"
            doc["verified_income_cents"] = verified_income_cents
        else:
            doc["status"] = "REJECTED"
        touch(doc)
        return object_response(public(doc), 200)
