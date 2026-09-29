"""Access-code batches, minted codes, assignment, sign-off and void."""
from flask import Blueprint

import authz
import calc
import cascade
import validation as V
from authz import require, find, deny_scope
from envelope import ok
from errors import ApiError
from helpers import paged, scoped_filter, match
from store import store

codes_bp = Blueprint("codes", __name__)


def _read_line_items(body):
    if not V.present(body, "line_items"):
        V.bad("line_items is required")
    raw = body["line_items"]
    if not isinstance(raw, list) or len(raw) < 1 or len(raw) > 4:
        V.bad("line_items must hold between one and four lines")
    seen = []
    lines = []
    for entry in raw:
        if not isinstance(entry, dict):
            V.bad("each line_items entry must be an object")
        bundle_type = V.req_enum(entry, "bundle_type", V.BUNDLE_TYPES)
        quantity = V.req_int(entry, "quantity", 1, 500)
        if bundle_type in seen:
            V.bad("line_items entries must carry distinct bundle_type values")
        seen.append(bundle_type)
        lines.append({"bundle_type": bundle_type, "quantity": quantity})
    return lines


def _batch_scope(batch, user_id, role):
    if role == authz.PROVIDER_ADMIN \
            and batch["training_provider_id"] != user_id:
        deny_scope()


@codes_bp.post("/access-code-batches")
def purchase_batch():
    user_id, role = require(authz.PROVIDER_ADMIN)
    body = V.get_body()
    provider_id = V.req_id(body, "training_provider_id")
    form_id = V.req_id(body, "exam_form_id")
    lines = _read_line_items(body)
    expires_at = V.req_datetime(body, "expires_at")
    if provider_id != user_id:
        deny_scope("a provider may only purchase against its own ledger")
    provider = find("provider", provider_id)
    form = find("exam_form", form_id)
    if form["status"] != "ACTIVE":
        raise ApiError("ERR_EXAM_FORM_RETIRED",
                       "no new batch may be purchased against a retired form")
    jurisdiction = store.jurisdictions.get(provider["jurisdiction_id"])
    surcharge = jurisdiction["exam_fee_surcharge_pct"] if jurisdiction \
        else V.Decimal("0")
    total_price = calc.price_line_items(lines, surcharge)
    quantity = sum(line["quantity"] for line in lines)
    cascade.check_credit(provider, total_price)
    batch = store.base()
    batch.update({
        "training_provider_id": provider_id,
        "exam_form_id": form_id,
        "line_items": [dict(line) for line in lines],
        "quantity_purchased": quantity,
        "total_price_cents": total_price,
        "available_count": quantity,
        "assigned_count": 0,
        "consumed_count": 0,
        "voided_count": 0,
        "expires_at": expires_at,
        "status": "ACTIVE",
        "void_gross_credit_cents": None,
        "void_restock_fee_cents": None,
        "void_net_credit_cents": None,
    })
    store.batches[batch["id"]] = batch
    for line in lines:
        for _ in range(line["quantity"]):
            code = store.base()
            code.update({
                "batch_id": batch["id"],
                "candidate_id": None,
                "code": store.next_code_value(),
                "bundle_type": line["bundle_type"],
                "status": "AVAILABLE",
                "assigned_at": None,
                "consumed_at": None,
                "course_completed_at": None,
                "course_instructor_proctor_id": None,
                "assignment_release_count": 0,
            })
            store.codes[code["id"]] = code
    cascade.debit_provider(provider, total_price)
    return ok(batch, 201)


@codes_bp.get("/access-code-batches/<batch_id>")
def read_batch(batch_id):
    user_id, role = require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN)
    batch = find("batch", batch_id)
    _batch_scope(batch, user_id, role)
    return ok(batch)


@codes_bp.get("/access-code-batches")
def list_batches():
    user_id, role = require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN)
    provider_filter = V.query_id("training_provider_id")
    if role == authz.PROVIDER_ADMIN:
        provider_filter = scoped_filter(provider_filter, user_id)
    form_id = V.query_id("exam_form_id")
    status = V.query_enum("status", V.BATCH_STATUS)
    rows = [r for r in store.batches.values()
            if match(r, "training_provider_id", provider_filter)
            and match(r, "exam_form_id", form_id)
            and match(r, "status", status)]
    return paged(rows)


@codes_bp.post("/access-code-batches/<batch_id>/assignments")
def assign_code(batch_id):
    user_id, role = require(authz.PROVIDER_ADMIN)
    batch = find("batch", batch_id)
    _batch_scope(batch, user_id, role)
    body = V.get_body()
    candidate_id = V.req_id(body, "candidate_id")
    bundle_type = V.req_enum(body, "bundle_type", V.BUNDLE_TYPES)
    expected_version = V.req_int(body, "expected_batch_version")
    candidate = find("candidate", candidate_id)
    if candidate["training_provider_id"] != batch["training_provider_id"]:
        deny_scope("the candidate belongs to another provider")
    if expected_version != batch["version"]:
        raise ApiError("ERR_STALE_BATCH_VERSION",
                       "expected_batch_version does not match the batch")
    if batch["status"] == "VOIDED":
        raise ApiError("ERR_BATCH_STATE_INVALID", "the batch is voided")
    if candidate["security_hold"]:
        raise ApiError("ERR_CANDIDATE_SECURITY_HOLD",
                       "the candidate is under a security hold")
    if batch["status"] == "EXPIRED" or store.clock > batch["expires_at"]:
        raise ApiError("ERR_BATCH_EXPIRED", "the batch has expired")
    pool = [c for c in store.codes.values()
            if c["batch_id"] == batch["id"] and c["status"] == "AVAILABLE"
            and c["bundle_type"] == bundle_type]
    if not pool:
        raise ApiError("ERR_BATCH_DEPLETED",
                       "the batch holds no available code of that bundle_type")
    code = store.ordered(pool)[0]
    code["status"] = "ASSIGNED"
    code["candidate_id"] = candidate_id
    code["assigned_at"] = store.clock
    store.touch(code)
    cascade.recount_batch(batch)
    if batch["available_count"] == 0 and batch["status"] == "ACTIVE":
        batch["status"] = "DEPLETED"
    store.touch(batch)
    return ok(code, 201)


@codes_bp.post("/access-code-batches/<batch_id>/void")
def void_batch(batch_id):
    user_id, role = require(authz.PROVIDER_ADMIN)
    batch = find("batch", batch_id)
    _batch_scope(batch, user_id, role)
    body = V.get_body()
    V.req_str(body, "reason", 1)
    expected_version = V.req_int(body, "expected_batch_version")
    if expected_version != batch["version"]:
        raise ApiError("ERR_STALE_BATCH_VERSION",
                       "expected_batch_version does not match the batch")
    if batch["status"] in ("VOIDED", "EXPIRED"):
        raise ApiError("ERR_BATCH_STATE_INVALID",
                       "the batch may not be voided from this state")
    if batch["available_count"] < 1:
        raise ApiError("ERR_BATCH_DEPLETED",
                       "the batch has no available code left to void")
    refundable = [c for c in cascade.batch_codes(batch["id"])
                  if c["status"] == "AVAILABLE"]
    gross, fee, net = calc.void_refund(batch["total_price_cents"],
                                      len(refundable),
                                      batch["quantity_purchased"])
    for code in store.ordered(refundable):
        code["status"] = "VOIDED"
        store.touch(code)
    cascade.recount_batch(batch)
    batch["void_gross_credit_cents"] = gross
    batch["void_restock_fee_cents"] = fee
    batch["void_net_credit_cents"] = net
    batch["status"] = "VOIDED"
    store.touch(batch)
    provider = store.providers.get(batch["training_provider_id"])
    if provider is not None:
        cascade.void_credit_buckets(provider, net)
    return ok(batch)


# --- access codes ----------------------------------------------------------

@codes_bp.get("/access-codes/<code_id>")
def read_code(code_id):
    user_id, role = require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN,
                            authz.CANDIDATE)
    code = find("code", code_id)
    if role == authz.PROVIDER_ADMIN \
            and authz.provider_of_code(code) != user_id:
        deny_scope()
    if role == authz.CANDIDATE and code["candidate_id"] != user_id:
        deny_scope()
    return ok(code)


@codes_bp.get("/access-codes")
def list_codes():
    user_id, role = require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN)
    batch_filter = V.query_id("batch_id")
    candidate_filter = V.query_id("candidate_id")
    instructor_filter = V.query_id("course_instructor_proctor_id")
    status = V.query_enum("status", V.CODE_STATUS)
    if batch_filter is not None:
        batch = find("batch", batch_filter)
        _batch_scope(batch, user_id, role)
    rows = [r for r in store.codes.values()
            if match(r, "batch_id", batch_filter)
            and match(r, "candidate_id", candidate_filter)
            and match(r, "course_instructor_proctor_id", instructor_filter)
            and match(r, "status", status)]
    if role == authz.PROVIDER_ADMIN:
        rows = [r for r in rows if authz.provider_of_code(r) == user_id]
    return paged(rows)


@codes_bp.post("/access-codes/<code_id>/course-completion")
def course_completion(code_id):
    user_id, role = require(authz.PROVIDER_ADMIN)
    code = find("code", code_id)
    if authz.provider_of_code(code) != user_id:
        deny_scope()
    body = V.get_body()
    instructor_id = V.req_id(body, "course_instructor_proctor_id")
    instructor = find("proctor", instructor_id)
    if code["status"] not in ("AVAILABLE", "ASSIGNED") \
            or code["course_completed_at"] is not None:
        raise ApiError("ERR_ACCESS_CODE_STATE_INVALID",
                       "the code may not be signed off from this state")
    if instructor["registration_status"] != "REGISTERED":
        raise ApiError("ERR_PROCTOR_NOT_REGISTERED",
                       "the signing instructor is not REGISTERED")
    if "INSTRUCTOR" not in instructor["roles_held"] \
            or instructor["training_provider_id"] \
            != authz.provider_of_code(code):
        raise ApiError("ERR_INSTRUCTOR_NOT_AUTHORIZED",
                       "the signing instructor is not authorized")
    code["course_completed_at"] = store.clock
    code["course_instructor_proctor_id"] = instructor_id
    store.touch(code)
    return ok(code)
