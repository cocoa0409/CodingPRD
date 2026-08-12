"""Participant endpoints."""

import db
from errors import err_not_found, err_validation
from middleware import require_roles, get_json_body, require_fields, check_string, check_enum
from response import success_object
from services.common import new_entity, touch, compute_docs_complete, recompute_pipeline

PRIOR_RECORDS = {"NONE", "CLEAN", "FLAGGED"}
DOC_TYPES = {"STATE_ID", "SSN_CARD", "ITIN_LETTER", "MATRICULA_CONSULAR", "MUNICIPAL_ID", "FOREIGN_PASSPORT", "PROOF_OF_ADDRESS"}
DOC_STATUSES = {"SUBMITTED", "VERIFIED"}


def _validate_documents(docs):
    if not isinstance(docs, list):
        err_validation("id_documents must be an array")
    for entry in docs:
        if not isinstance(entry, dict):
            err_validation("Each id_documents entry must be an object")
        check_enum(entry.get("doc_type"), DOC_TYPES, "doc_type")
        check_enum(entry.get("status"), DOC_STATUSES, "status")


def _serialize(p):
    return dict(p)


def register(bp):
    @bp.route("/participants", methods=["POST"])
    def create_participant():
        user_id, role = require_roles("AgencyNavigator", "CoalitionAdmin")
        body = get_json_body()
        require_fields(body, ["full_name", "date_of_birth", "contact_zip", "prior_banking_record"])
        check_string(body["full_name"], "full_name")
        check_string(body["date_of_birth"], "date_of_birth")
        check_string(body["contact_zip"], "contact_zip")
        check_enum(body["prior_banking_record"], PRIOR_RECORDS, "prior_banking_record")
        docs = body.get("id_documents", [])
        if docs is None:
            docs = []
        _validate_documents(docs)

        p = new_entity()
        p.update({
            "full_name": body["full_name"],
            "date_of_birth": body["date_of_birth"],
            "contact_zip": body["contact_zip"],
            "prior_banking_record": body["prior_banking_record"],
            "id_documents": [dict(d) for d in docs],
            "docs_complete": False,
            "pipeline_stage": "REGISTERED",
            "registered_by_user_id": user_id,
        })
        p["docs_complete"] = compute_docs_complete(p)
        db.participants[p["id"]] = p
        recompute_pipeline(p["id"])
        return success_object(_serialize(p), status=201)

    @bp.route("/participants/<pid>", methods=["GET"])
    def get_participant(pid):
        require_roles("CoalitionAdmin", "AgencyNavigator", "InstitutionOfficer", "Participant")
        p = db.participants.get(pid)
        if p is None:
            err_not_found("Participant not found")
        return success_object(_serialize(p))

    @bp.route("/participants/<pid>/documents", methods=["PATCH"])
    def update_documents(pid):
        require_roles("AgencyNavigator", "CoalitionAdmin")
        p = db.participants.get(pid)
        if p is None:
            err_not_found("Participant not found")
        body = get_json_body()
        require_fields(body, ["id_documents"])
        docs = body["id_documents"]
        _validate_documents(docs)

        # upsert entries by doc_type
        existing = {d["doc_type"]: d for d in (p.get("id_documents") or [])}
        for entry in docs:
            existing[entry["doc_type"]] = {"doc_type": entry["doc_type"], "status": entry["status"]}
        p["id_documents"] = list(existing.values())
        p["docs_complete"] = compute_docs_complete(p)
        touch(p)
        recompute_pipeline(pid)
        return success_object(_serialize(p))
