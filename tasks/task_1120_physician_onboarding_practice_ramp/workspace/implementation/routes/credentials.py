"""Credential item endpoints (PRD 3.3)."""

from flask import Blueprint, request

import domain as D
from db import store, new_record, bump
from errors import (
    ApiError, ERR_VALIDATION, ERR_CASE_NOT_FOUND,
    ERR_CREDENTIAL_ITEM_NOT_FOUND, ERR_INVALID_STATE,
    ERR_ITEM_NOT_SUBMITTED, ERR_ITEM_NOT_VERIFIED, ERR_ITEM_NOT_FILED,
    ERR_ITEM_DEPENDENCY_NOT_APPROVED, ERR_SEGREGATION_OF_DUTIES,
)
from middleware import get_context, require_role
from response import success_object, paginate

bp = Blueprint("credentials", __name__)


def _get_item(iid):
    item = store.credential_items.get(iid)
    if item is None:
        raise ApiError(ERR_CREDENTIAL_ITEM_NOT_FOUND, 404, "CredentialItem not found")
    return item


def _touch_item_and_case(item):
    bump(item)
    case = store.cases.get(item["onboarding_case_id"])
    if case is not None:
        bump(case)
    return case


def _recompute_case_credentials(case):
    D.recompute_credential_status(case)
    D.recompute_posture(case)


@bp.route("/onboarding/credential-items", methods=["POST"])
def create_item():
    _uid, role = get_context()
    require_role(role, ["CredentialingSpecialist"])
    body = D.get_body()
    case_id = D.req_str(body, "onboarding_case_id")
    item_type = D.req_enum(body, "item_type", D.ITEM_TYPES)
    document_ref = D.req_str(body, "document_ref")
    payer_code = D.opt_str(body, "payer_code")
    expires_on = D.opt_str(body, "expires_on")

    case = store.cases.get(case_id)
    if case is None:
        raise ApiError(ERR_CASE_NOT_FOUND, 404, "OnboardingCase not found")

    if item_type in D.PAYER_ITEM_TYPES and not payer_code:
        raise ApiError(ERR_VALIDATION, 400,
                       "payer_code is required for payer enrollment item types")
    if item_type in ("STATE_LICENSE", "DEA_REGISTRATION") and not expires_on:
        raise ApiError(ERR_VALIDATION, 400,
                       "expires_on is required for STATE_LICENSE and DEA_REGISTRATION")
    if expires_on is not None:
        D.parse_date(expires_on, "expires_on")

    depends_on = body.get("depends_on_item_ids")
    if depends_on is None:
        depends_on = []
    if not isinstance(depends_on, list) or any(not isinstance(x, str) for x in depends_on):
        raise ApiError(ERR_VALIDATION, 400, "depends_on_item_ids must be an array of ids")
    for dep_id in depends_on:
        if dep_id not in store.credential_items:
            raise ApiError(ERR_CREDENTIAL_ITEM_NOT_FOUND, 404,
                           "Dependency item %s not found" % dep_id)

    rec = new_record()
    rec.update({
        "onboarding_case_id": case_id,
        "item_type": item_type,
        "payer_code": payer_code,
        "depends_on_item_ids": list(depends_on),
        "document_ref": document_ref,
        "expires_on": expires_on,
        "submitted_by_user_id": None,
        "verified_by_user_id": None,
        "blocked_from_status": None,
        "status": "PENDING",
    })
    store.credential_items[rec["id"]] = rec
    _recompute_case_credentials(case)
    bump(case)
    return success_object(D.serialize_credential_item(rec), status=201)


@bp.route("/onboarding/credential-items/<iid>", methods=["GET"])
def get_item(iid):
    get_context()
    return success_object(D.serialize_credential_item(_get_item(iid)))


@bp.route("/onboarding/credential-items", methods=["GET"])
def list_items():
    get_context()
    case_id = request.args.get("onboarding_case_id")
    item_type = request.args.get("item_type")
    status = request.args.get("status")
    dep = request.args.get("depends_on_item_ids")
    records = sorted(store.credential_items.values(), key=lambda r: r["_seq"])
    if case_id is not None:
        records = [r for r in records if r["onboarding_case_id"] == case_id]
    if item_type is not None:
        records = [r for r in records if r["item_type"] == item_type]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if dep is not None:
        records = [r for r in records if dep in r["depends_on_item_ids"]]
    return paginate([D.serialize_credential_item(r) for r in records], request.args)


@bp.route("/onboarding/credential-items/<iid>/submit-docs", methods=["POST"])
def submit_docs(iid):
    uid, role = get_context()
    require_role(role, ["CredentialingSpecialist"])
    item = _get_item(iid)
    if item["status"] not in ("PENDING", "REJECTED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Documents can be submitted only from PENDING or REJECTED")
    body = D.get_body()
    document_ref = D.opt_str(body, "document_ref")
    item["status"] = "DOCS_SUBMITTED"
    item["submitted_by_user_id"] = uid
    if document_ref is not None:
        item["document_ref"] = document_ref
    _touch_item_and_case(item)
    return success_object(D.serialize_credential_item(item))


@bp.route("/onboarding/credential-items/<iid>/verify", methods=["POST"])
def verify_item(iid):
    uid, role = get_context()
    require_role(role, ["CredentialingSpecialist"])
    item = _get_item(iid)
    if item["status"] != "DOCS_SUBMITTED":
        raise ApiError(ERR_ITEM_NOT_SUBMITTED, 409,
                       "Item must be DOCS_SUBMITTED before verification")
    if uid == item["submitted_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 422,
                       "The verifier must differ from the submitter of record")
    item["status"] = "VERIFIED"
    item["verified_by_user_id"] = uid
    _touch_item_and_case(item)
    return success_object(D.serialize_credential_item(item))


@bp.route("/onboarding/credential-items/<iid>/file", methods=["POST"])
def file_item(iid):
    _uid, role = get_context()
    require_role(role, ["CredentialingSpecialist"])
    item = _get_item(iid)
    if item["status"] != "VERIFIED":
        raise ApiError(ERR_ITEM_NOT_VERIFIED, 409, "Item must be VERIFIED before filing")
    for dep_id in item["depends_on_item_ids"]:
        dep = store.credential_items.get(dep_id)
        if dep is None or dep["status"] != "APPROVED":
            raise ApiError(ERR_ITEM_DEPENDENCY_NOT_APPROVED, 422,
                           "Every dependency item must be APPROVED before filing")
    item["status"] = "FILED"
    _touch_item_and_case(item)
    return success_object(D.serialize_credential_item(item))


@bp.route("/onboarding/credential-items/<iid>/approve", methods=["POST"])
def approve_item(iid):
    _uid, role = get_context()
    require_role(role, ["OnboardingDirector"])
    item = _get_item(iid)
    if item["status"] != "FILED":
        raise ApiError(ERR_ITEM_NOT_FILED, 409, "Item must be FILED before approval")
    item["status"] = "APPROVED"
    bump(item)
    D.restore_blocked_items(item["onboarding_case_id"])
    case = store.cases.get(item["onboarding_case_id"])
    if case is not None:
        _recompute_case_credentials(case)
        bump(case)
    return success_object(D.serialize_credential_item(item))


@bp.route("/onboarding/credential-items/<iid>/reject", methods=["POST"])
def reject_item(iid):
    _uid, role = get_context()
    require_role(role, ["OnboardingDirector"])
    item = _get_item(iid)
    body = D.get_body()
    reason = body.get("reason")
    if not isinstance(reason, str) or reason == "":
        raise ApiError(ERR_VALIDATION, 400, "reason is required")
    if item["status"] not in ("DOCS_SUBMITTED", "VERIFIED", "FILED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an item in flight can be rejected")
    item["status"] = "REJECTED"
    bump(item)
    D.cascade_credential_failure(item)
    case = store.cases.get(item["onboarding_case_id"])
    if case is not None:
        _recompute_case_credentials(case)
        bump(case)
    return success_object(D.serialize_credential_item(item))
