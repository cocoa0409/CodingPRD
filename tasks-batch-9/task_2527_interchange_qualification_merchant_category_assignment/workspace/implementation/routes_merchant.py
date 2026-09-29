"""Merchant boarding, category verification and the reclassification review
cycle (PRD 3.3 and 3.4)."""

from flask import Blueprint, request

import calc
import listing
import resolve
import validate as v
from auth import ALL_ROLES, authenticate, require_scope
from envelope import array_response, object_response, paginate
from errors import (
    ERR_DOCUMENTATION_REQUIRED,
    ERR_INVALID_STATE,
    ERR_MCC_NOT_DEFINED,
    ERR_MERCHANT_MISREPRESENTED,
    ERR_MERCHANT_UNDER_CATEGORY_REVIEW,
    ERR_REVIEW_ROUND_LIMIT_EXCEEDED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    fail,
)
from store import (
    MAX_REVIEW_ROUNDS,
    new_row,
    serialize,
    serialize_many,
    sorted_rows,
    store,
    touch,
)

bp = Blueprint("merchant", __name__)


def acting_user():
    return request.headers.get("X-User-ID")


# ---------------------------------------------------------------------------
# Merchants
# ---------------------------------------------------------------------------

@bp.post("/merchants")
def create_merchant():
    caller = authenticate(["AcquirerOps", "NetworkAdmin"])
    data = v.body()

    acquirer_id = v.raw_id(data, "acquirer_id")
    if acquirer_id is not None:
        resolve.acquirer(acquirer_id)

    fields = {
        "legal_name": v.req_str(data, "legal_name", 1, 120),
        "business_type_key": v.req_business_type_key(data, "business_type_key"),
        "acquirer_id": v.req_str(data, "acquirer_id"),
        "home_country_code": v.req_country(data, "home_country_code"),
    }
    require_scope(caller, fields["acquirer_id"])

    # Priority 26: a category must be resolvable, or no merchant row is created.
    definition = calc.select_definition_for_business_type(fields["business_type_key"])
    if definition is None:
        fail(ERR_MCC_NOT_DEFINED,
             "No MCC definition carries that business_type_key.")

    fields.update({
        "assigned_mcc": definition["mcc_code"],
        "mcc_status": ("PENDING_VERIFICATION" if definition["requires_documentation"]
                       else "VERIFIED"),
        "mcc_status_before_review": None,
        "documentation_ref": None,
        "verified_by_user_id": None,
        "downgrade_count_current_quarter": 0,
        "lifetime_net_assessed_cents": 0,
    })
    row = new_row(fields)
    store.merchants[row["id"]] = row
    return object_response(serialize("Merchant", row), 201)


@bp.post("/merchants/<row_id>/verify-category")
def verify_category(row_id):
    authenticate(["CategoryAnalyst"])
    merchant = resolve.merchant(row_id)
    data = v.body()
    doc_ref = v.opt_str(data, "documentation_ref", 0, 500)

    status = merchant["mcc_status"]
    if status == "VERIFIED":
        fail(ERR_INVALID_STATE, "The merchant category is already VERIFIED.")
    if status == "UNDER_REVIEW":
        fail(ERR_MERCHANT_UNDER_CATEGORY_REVIEW)
    if status == "MISREPRESENTED":
        fail(ERR_MERCHANT_MISREPRESENTED)

    definition = calc.mcc_def_by_code(merchant["assigned_mcc"])
    requires_doc = bool(definition["requires_documentation"]) if definition else False
    if requires_doc and not (doc_ref and doc_ref.strip()):
        fail(ERR_DOCUMENTATION_REQUIRED)

    merchant["mcc_status"] = "VERIFIED"
    merchant["documentation_ref"] = doc_ref
    merchant["verified_by_user_id"] = acting_user()
    touch(merchant)
    return object_response(serialize("Merchant", merchant))


@bp.get("/merchants/<row_id>")
def get_merchant(row_id):
    caller = authenticate(ALL_ROLES)
    merchant = resolve.merchant(row_id)
    require_scope(caller, merchant["acquirer_id"])
    return object_response(serialize("Merchant", merchant))


@bp.get("/merchants")
def list_merchants():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(store.merchants.values()))
    rows = listing.apply_string_filters(rows, [
        ("acquirer_id", "acquirer_id"),
        ("mcc_status", "mcc_status"),
        ("assigned_mcc", "assigned_mcc"),
        ("business_type_key", "business_type_key"),
    ])
    page, meta = paginate(rows)
    return array_response(serialize_many("Merchant", page), meta)


# ---------------------------------------------------------------------------
# Reclassification requests
# ---------------------------------------------------------------------------

@bp.post("/reclassification-requests")
def create_reclass_request():
    caller = authenticate(["AcquirerOps"])
    data = v.body()

    merchant_id = v.raw_id(data, "merchant_id")
    if merchant_id is not None:
        resolve.merchant(merchant_id)

    fields = {
        "merchant_id": v.req_str(data, "merchant_id"),
        "requested_mcc": v.req_mcc(data, "requested_mcc"),
        "justification": v.req_str(data, "justification", 1, 1000),
    }
    expected = v.req_int(data, "expected_merchant_version")

    merchant = store.merchants[fields["merchant_id"]]
    require_scope(caller, merchant["acquirer_id"])

    # Priority 11 sits above every merchant-posture check below it.
    if expected != int(merchant["version"]):
        fail(ERR_STALE_VERSION)
    if merchant["mcc_status"] == "MISREPRESENTED":
        fail(ERR_MERCHANT_MISREPRESENTED)
    if merchant["mcc_status"] == "UNDER_REVIEW":
        fail(ERR_MERCHANT_UNDER_CATEGORY_REVIEW)
    if not calc.mcc_code_exists(fields["requested_mcc"]):
        fail(ERR_MCC_NOT_DEFINED, "requested_mcc names no MCC definition.")

    calc.supersede_live_requests(merchant["id"])
    fields.update({
        "supporting_doc_ref": None,
        "status": "SUBMITTED",
        "review_round": 1,
        "reviewer_user_id": None,
        "decider_user_id": None,
        "info_request_note": None,
        "decision_note": None,
        "decided_mcc": None,
        "prior_status_before_suspension": None,
    })
    row = new_row(fields)
    store.reclass_requests[row["id"]] = row
    touch(merchant)
    return object_response(serialize("ReclassificationRequest", row), 201)


@bp.post("/reclassification-requests/<row_id>/review")
def review_reclass_request(row_id):
    authenticate(["CategoryAnalyst"])
    row = resolve.reclass_request(row_id)
    if row["status"] != "SUBMITTED":
        fail(ERR_INVALID_STATE, "Only a SUBMITTED request may be taken under review.")
    row["status"] = "UNDER_REVIEW"
    row["reviewer_user_id"] = acting_user()
    touch(row)
    return object_response(serialize("ReclassificationRequest", row))


@bp.post("/reclassification-requests/<row_id>/request-info")
def request_info_reclass_request(row_id):
    authenticate(["CategoryAnalyst"])
    row = resolve.reclass_request(row_id)
    data = v.body()
    note = v.req_str(data, "info_request_note", 1, 1000)
    if row["status"] != "UNDER_REVIEW":
        fail(ERR_INVALID_STATE, "Only an UNDER_REVIEW request may be returned for information.")
    if int(row["review_round"]) >= MAX_REVIEW_ROUNDS:
        fail(ERR_REVIEW_ROUND_LIMIT_EXCEEDED)
    row["status"] = "INFO_REQUESTED"
    row["info_request_note"] = note
    touch(row)
    return object_response(serialize("ReclassificationRequest", row))


@bp.post("/reclassification-requests/<row_id>/resubmit")
def resubmit_reclass_request(row_id):
    caller = authenticate(["AcquirerOps"])
    row = resolve.reclass_request(row_id)
    data = v.body()
    doc_ref = v.opt_str(data, "supporting_doc_ref", 0, 500)

    merchant = store.merchants.get(row["merchant_id"])
    require_scope(caller, merchant["acquirer_id"] if merchant else None)

    if row["status"] != "INFO_REQUESTED":
        fail(ERR_INVALID_STATE, "Only an INFO_REQUESTED request may be answered.")
    if merchant is not None and merchant["mcc_status"] in ("UNDER_REVIEW", "MISREPRESENTED"):
        fail(ERR_INVALID_STATE, "The merchant's category posture blocks a resubmission.")
    if int(row["review_round"]) >= MAX_REVIEW_ROUNDS:
        fail(ERR_REVIEW_ROUND_LIMIT_EXCEEDED)

    definition = calc.mcc_def_by_code(row["requested_mcc"])
    if definition is not None and definition["requires_documentation"]:
        if not (doc_ref and doc_ref.strip()):
            fail(ERR_DOCUMENTATION_REQUIRED)

    row["status"] = "SUBMITTED"
    row["review_round"] = int(row["review_round"]) + 1
    row["supporting_doc_ref"] = doc_ref
    row["info_request_note"] = None
    touch(row)
    return object_response(serialize("ReclassificationRequest", row))


@bp.post("/reclassification-requests/<row_id>/decide")
def decide_reclass_request(row_id):
    authenticate(["CategoryApprover"])
    row = resolve.reclass_request(row_id)
    data = v.body()
    decision = v.req_enum(data, "decision", ("APPROVE", "DENY"))
    note = v.req_str(data, "decision_note", 1, 1000)

    if row["status"] != "UNDER_REVIEW":
        fail(ERR_INVALID_STATE, "Only an UNDER_REVIEW request may be decided.")
    if acting_user() == row["reviewer_user_id"]:
        fail(ERR_SEGREGATION_OF_DUTIES)

    definition = calc.mcc_def_by_code(row["requested_mcc"])
    if decision == "APPROVE":
        if (definition is not None and definition["requires_documentation"]
                and not row["supporting_doc_ref"]):
            fail(ERR_DOCUMENTATION_REQUIRED)

    row["decider_user_id"] = acting_user()
    row["decision_note"] = note
    if decision == "DENY":
        row["status"] = "DENIED"
        touch(row)
        return object_response(serialize("ReclassificationRequest", row))

    row["status"] = "APPROVED"
    row["decided_mcc"] = row["requested_mcc"]
    touch(row)

    merchant = store.merchants.get(row["merchant_id"])
    if merchant is not None:
        merchant["assigned_mcc"] = row["requested_mcc"]
        if definition is not None and definition["requires_documentation"]:
            merchant["mcc_status"] = "PENDING_VERIFICATION"
        touch(merchant)
        calc.terminate_ineligible_enrollments(merchant)
    return object_response(serialize("ReclassificationRequest", row))


@bp.get("/reclassification-requests/<row_id>")
def get_reclass_request(row_id):
    caller = authenticate(ALL_ROLES)
    row = resolve.reclass_request(row_id)
    merchant = store.merchants.get(row["merchant_id"])
    require_scope(caller, merchant["acquirer_id"] if merchant else None)
    return object_response(serialize("ReclassificationRequest", row))


@bp.get("/reclassification-requests")
def list_reclass_requests():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(store.reclass_requests.values()))
    rows = listing.apply_string_filters(rows, [
        ("merchant_id", "merchant_id"),
        ("status", "status"),
        ("requested_mcc", "requested_mcc"),
    ])
    page, meta = paginate(rows)
    return array_response(serialize_many("ReclassificationRequest", page), meta)
