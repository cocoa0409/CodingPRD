"""Advance care documents and code-status orders (PRD 3.3, 3.4)."""

from flask import Blueprint

import calc
import cascades
import config
from envelope import created, listing, ok
from errors import (
    ERR_CODE_STATUS_LADDER_VIOLATION, ERR_EXECUTION_REQUIREMENT_UNMET,
    ERR_GOALS_CONFLICT, ERR_SIGNATURE_INCOMPLETE, ERR_STALE_PATIENT_VERSION,
    ERR_WITNESS_CONFLICT, api_error,
)
from ladder import (
    apply_filters, auth, field, fk, freeze_gate, occ, pagination, paginate,
    path_row, query_filters, raw_body, state, touch, validate,
)
from store import days, ordered, store

bp = Blueprint("documents", __name__)

_COUNTER_FOR = {
    "WITNESS": "witness_signature_count",
    "NOTARY": "notary_signature_count",
    "SIGNING_PHYSICIAN": "physician_signature_count",
    "PATIENT_OR_SURROGATE": "patient_or_surrogate_signature_count",
}


def _recompute_ready(document, patient):
    ready, _, _ = calc.document_execution_requirement(document, patient["jurisdiction_code"])
    document["execution_ready"] = ready
    return ready


@bp.post("/palliative/advance-care-documents")
def create_document():
    auth([config.ROLE_SOCIAL, config.ROLE_PHYSICIAN, config.ROLE_ADMIN])
    body = raw_body()
    data = validate(body, [
        field("patient_id", "string", required=True),
        field("document_type", "enum", required=True, enum=config.DOCUMENT_TYPES),
        field("stated_code_status", "enum", required=True, enum=config.CODE_STATUSES),
        field("supersedes_document_id", "string"),
    ])
    patient = fk(store.patients, data["patient_id"])
    predecessor = fk(store.documents, data["supersedes_document_id"])
    freeze_gate(patient)
    row = store.new_row({
        "patient_id": patient["id"],
        "document_type": data["document_type"],
        "stated_code_status": data["stated_code_status"],
        "supersedes_document_id": predecessor["id"] if predecessor else None,
        "witness_signature_count": 0,
        "notary_signature_count": 0,
        "physician_signature_count": 0,
        "patient_or_surrogate_signature_count": 0,
        "signature_log": [],
        "execution_ready": False,
        "executed_at": None,
        "reattest_due_at": None,
        "status": "DRAFT",
    })
    store.documents[row["id"]] = row
    return created(row)


@bp.post("/palliative/advance-care-documents/<did>/signatures")
def append_signature(did):
    auth([config.ROLE_SOCIAL, config.ROLE_PHYSICIAN, config.ROLE_CAREGIVER, config.ROLE_ADMIN])
    document = path_row(store.documents, did)
    body = raw_body()
    data = validate(body, [
        field("signature_type", "enum", required=True, enum=config.SIGNATURE_TYPES),
        field("signer_user_id", "string", required=True),
    ])
    patient = store.patients.get(document["patient_id"])
    freeze_gate(patient)
    state(document["status"] in ("DRAFT", "PENDING_EXECUTION"))

    if data["signature_type"] == "WITNESS":
        signer = data["signer_user_id"]
        if patient is not None and signer == patient["attending_clinician_user_id"]:
            raise api_error(ERR_WITNESS_CONFLICT)
        for des in cascades.rows_for_patient(store.surrogates, document["patient_id"]):
            if des["person_user_id"] != signer:
                continue
            if des["status"] in ("PROPOSED", "ACTIVE") or des["is_beneficiary"]:
                raise api_error(ERR_WITNESS_CONFLICT)

    document["signature_log"].append({
        "signature_type": data["signature_type"],
        "signer_user_id": data["signer_user_id"],
        "signed_at": store.now(),
    })
    document[_COUNTER_FOR[data["signature_type"]]] += 1
    ready = _recompute_ready(document, patient)
    if document["status"] == "DRAFT" and ready:
        document["status"] = "PENDING_EXECUTION"
    touch(document)
    return ok(document)


@bp.post("/palliative/advance-care-documents/<did>/execute")
def execute_document(did):
    auth([config.ROLE_PHYSICIAN, config.ROLE_ADMIN])
    document = path_row(store.documents, did)
    body = raw_body()
    data = validate(body, [field("expected_patient_version", "integer", required=True)])
    patient = store.patients.get(document["patient_id"])
    freeze_gate(patient)
    state(document["status"] in ("DRAFT", "PENDING_EXECUTION"))
    occ(data["expected_patient_version"], patient["version"], ERR_STALE_PATIENT_VERSION)
    _, base_ok, polst_ok = calc.document_execution_requirement(
        document, patient["jurisdiction_code"])
    if not base_ok:
        raise api_error(ERR_EXECUTION_REQUIREMENT_UNMET)
    if not polst_ok:
        raise api_error(ERR_SIGNATURE_INCOMPLETE)

    document["executed_at"] = store.now()
    document["reattest_due_at"] = document["executed_at"] + days(config.DIRECTIVE_REATTESTATION_DAYS)
    document["status"] = "EXECUTED"
    document["execution_ready"] = True
    touch(document)
    cascades.document_execution_cascade(document, patient)
    return ok(document)


@bp.post("/palliative/advance-care-documents/<did>/revoke")
def revoke_document(did):
    auth([config.ROLE_PHYSICIAN, config.ROLE_ADMIN])
    document = path_row(store.documents, did)
    body = raw_body()
    validate(body, [field("revocation_reason", "string", required=True)])
    patient = store.patients.get(document["patient_id"])
    freeze_gate(patient)
    state(document["status"] == "EXECUTED")
    document["status"] = "REVOKED"
    touch(document)
    cascades.document_revocation_cascade(document, patient)
    return ok(document)


@bp.get("/palliative/advance-care-documents/<did>")
def read_document(did):
    auth([config.ROLE_SOCIAL, config.ROLE_PHYSICIAN, config.ROLE_CAREGIVER, config.ROLE_ADMIN])
    return ok(path_row(store.documents, did))


@bp.get("/palliative/advance-care-documents")
def list_documents():
    auth([config.ROLE_SOCIAL, config.ROLE_PHYSICIAN, config.ROLE_CAREGIVER, config.ROLE_ADMIN])
    limit, offset = pagination()
    rows = apply_filters(
        ordered(store.documents.values()),
        query_filters(["patient_id", "supersedes_document_id", "document_type", "status"]))
    page, total = paginate(rows, limit, offset)
    return listing(page, limit, offset, total)


# ------------------------------------------------------------ code statuses
@bp.post("/palliative/code-status-orders")
def create_code_status_order():
    auth([config.ROLE_PHYSICIAN, config.ROLE_ADMIN])
    body = raw_body()
    data = validate(body, [
        field("patient_id", "string", required=True),
        field("requested_code_status", "enum", required=True, enum=config.CODE_STATUSES),
        field("source_document_id", "string"),
        field("surrogate_stated", "boolean", default=False),
        field("patient_prior_statement", "enum", enum=config.CODE_STATUSES),
    ])
    patient = fk(store.patients, data["patient_id"])
    source = fk(store.documents, data["source_document_id"])
    freeze_gate(patient)

    prior = patient["code_status"]
    requested = data["requested_code_status"]
    prior_rank = config.CODE_STATUS_RANKS[prior]
    requested_rank = config.CODE_STATUS_RANKS[requested]
    if requested_rank > prior_rank:
        direction = "DE_ESCALATION"
    elif requested_rank < prior_rank:
        direction = "RE_ESCALATION"
    else:
        direction = "NO_CHANGE"

    row = store.new_row({
        "patient_id": patient["id"],
        "source_document_id": source["id"] if source else None,
        "requested_code_status": requested,
        "prior_code_status": prior,
        "ladder_direction": direction,
        "surrogate_stated": bool(data["surrogate_stated"]),
        "patient_prior_statement": data["patient_prior_statement"],
        "attesting_clinician_user_id": None,
        "attesting_party_user_id": None,
        "conflict_resolution_note": None,
        "attestation_count": 0,
        "effective_at": None,
        "status": "DRAFT",
    })
    store.code_status_orders[row["id"]] = row
    return created(row)


def _recorded_roles(order):
    roles = set()
    if order["attesting_clinician_user_id"]:
        roles.add("CLINICIAN")
    if order["attesting_party_user_id"]:
        roles.add("PATIENT_OR_SURROGATE")
    return roles


@bp.post("/palliative/code-status-orders/<oid>/attestations")
def attest_code_status_order(oid):
    ctx = auth([config.ROLE_PHYSICIAN, config.ROLE_SOCIAL, config.ROLE_CAREGIVER, config.ROLE_ADMIN])
    order = path_row(store.code_status_orders, oid)
    body = raw_body()
    data = validate(body, [
        field("attestation_role", "enum", required=True, enum=config.ATTESTATION_ROLES),
        field("attestation_text", "string", required=True),
        field("conflict_resolution_note", "string"),
    ])
    patient = store.patients.get(order["patient_id"])
    freeze_gate(patient)
    state(order["status"] in ("DRAFT", "CONFLICT_HOLD", "ATTESTED"))

    # rung 14 — code-status ladder
    prior_rank = config.CODE_STATUS_RANKS[order["prior_code_status"]]
    requested_rank = config.CODE_STATUS_RANKS[order["requested_code_status"]]
    if abs(requested_rank - prior_rank) > config.MAX_LADDER_STEP_PER_ORDER:
        raise api_error(ERR_CODE_STATUS_LADDER_VIOLATION)
    if requested_rank < prior_rank:
        if patient["capacity_status"] != "HAS_CAPACITY" or order["surrogate_stated"]:
            raise api_error(ERR_CODE_STATUS_LADDER_VIOLATION)

    # rung 15 — goals conflict
    note = data["conflict_resolution_note"]
    if order["status"] == "CONFLICT_HOLD" and not (note and note.strip()):
        raise api_error(ERR_GOALS_CONFLICT)

    role = data["attestation_role"]
    stamp_field = ("attesting_clinician_user_id" if role == "CLINICIAN"
                   else "attesting_party_user_id")

    if order["status"] == "DRAFT":
        order[stamp_field] = ctx.user_id
        order["attestation_count"] = 1
        conflict = (order["surrogate_stated"]
                    and order["patient_prior_statement"] is not None
                    and order["patient_prior_statement"] != order["requested_code_status"])
        order["status"] = "CONFLICT_HOLD" if conflict else "ATTESTED"
        touch(order)
    elif order["status"] == "CONFLICT_HOLD":
        order[stamp_field] = ctx.user_id
        order["conflict_resolution_note"] = note
        order["attestation_count"] += 1
        order["status"] = "ATTESTED"
        touch(order)
    else:  # ATTESTED
        advances = (order["attestation_count"] == 1
                    and role not in _recorded_roles(order))
        order[stamp_field] = ctx.user_id
        if advances:
            order["attestation_count"] = config.CODE_STATUS_ATTESTATIONS_REQUIRED
            order["effective_at"] = store.now()
            order["status"] = "EFFECTIVE"
            touch(order)
            cascades.supersede_other_effective_orders(patient["id"], keep_id=order["id"])
            cascades.rewrite_code_status(patient, order["requested_code_status"])
        else:
            touch(order)
    return ok(order)


@bp.get("/palliative/code-status-orders/<oid>")
def read_code_status_order(oid):
    auth([config.ROLE_PHYSICIAN, config.ROLE_SOCIAL, config.ROLE_NURSE, config.ROLE_ADMIN])
    return ok(path_row(store.code_status_orders, oid))


@bp.get("/palliative/code-status-orders")
def list_code_status_orders():
    auth([config.ROLE_PHYSICIAN, config.ROLE_SOCIAL, config.ROLE_NURSE, config.ROLE_ADMIN])
    limit, offset = pagination()
    rows = apply_filters(
        ordered(store.code_status_orders.values()),
        query_filters(["patient_id", "source_document_id", "status"]))
    page, total = paginate(rows, limit, offset)
    return listing(page, limit, offset, total)
