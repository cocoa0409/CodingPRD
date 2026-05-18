"""Application endpoints (SCAFFOLD §1.5).

Covers the full Application surface plus its nested resources:
  POST   /applications
  GET    /applications/{id}
  PATCH  /applications/{id}
  GET    /applications
  POST   /applications/{id}/fees
  GET    /applications/{id}/fees
  POST   /applications/{id}/file
  POST   /applications/{id}/begin-examination
  POST   /applications/{id}/office-actions
  GET    /applications/{id}/office-actions
  POST   /applications/{id}/allow
  POST   /applications/{id}/grant
  POST   /applications/{id}/abandon
  POST   /applications/{id}/pct-phases
  GET    /applications/{id}/maintenance-fees
  GET    /applications/{id}/audit-events
"""

from flask import Blueprint, g, request

from config import (
    APPLICATION_STATUSES,
    APPLICATION_TYPES,
    APP_STATUS_GRANTED,
    APP_TYPE_UTILITY,
    CONTINUATION_TYPES,
    FEE_CATEGORIES,
    HEADER_IDEMPOTENCY_KEY,
    IDEMPOTENCY_TTL_SECONDS,
    MAINTENANCE_STATUSES,
    OA_STATUSES,
    ROLE_APPLICANT,
    ROLE_EXAMINER,
    ROLE_USPTO_ADMIN,
)
from db import store
from errors import ApiError, make_error
from middleware import parse_json_body, require_auth
from response import success
from routes._helpers import build_pagination_meta, parse_pagination, slice_and_sort
from services.patent_engine import (
    _check_ownership_application,
    abandon_application,
    allow_application,
    begin_examination,
    create_application,
    create_pct_phase,
    file_application,
    grant_application,
    issue_office_action,
    record_fee_transaction,
    update_application,
)
from services.serializers import (
    serialize_application,
    serialize_audit_event,
    serialize_fee_transaction,
    serialize_maintenance_fee,
    serialize_office_action,
    serialize_pct_phase,
)
from utils import parse_iso8601


applications_bp = Blueprint("applications", __name__)


# ---------------------------------------------------------------------------
# Idempotency helpers
# ---------------------------------------------------------------------------
def _idempotency_lookup(route: str, key: str, applicant_id: str, payload_fp: str):
    """Look up a cached idempotent response. Returns (cached_dict | None).

    If a key/route/applicant combination exists with a different payload
    fingerprint within the TTL, raise ERR_IDEMPOTENCY_CONFLICT.
    """
    if not key:
        return None
    cached = store.idempotency_cache.get((route, key, applicant_id))
    if cached is None:
        return None
    # TTL check
    from utils import iso_now, parse_iso8601 as p
    from datetime import timezone
    created = p(cached["created_at"])
    if (store.now() - created).total_seconds() > IDEMPOTENCY_TTL_SECONDS:
        del store.idempotency_cache[(route, key, applicant_id)]
        return None
    if cached["payload_fingerprint"] != payload_fp:
        raise make_error("ERR_IDEMPOTENCY_CONFLICT",
                         "Idempotency-Key reused with a different payload.")
    return cached


def _idempotency_store(route: str, key: str, applicant_id: str, payload_fp: str,
                       body: dict, http_status: int):
    if not key:
        return
    from utils import iso_now
    store.idempotency_cache[(route, key, applicant_id)] = {
        "payload_fingerprint": payload_fp,
        "body": body,
        "http_status": http_status,
        "created_at": iso_now(store.now()),
    }


def _payload_fingerprint(payload) -> str:
    import json
    return json.dumps(payload, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# POST /applications
# ---------------------------------------------------------------------------
@applications_bp.post("/applications")
@require_auth(allowed_roles=[ROLE_APPLICANT])
def create_application_route():
    body = parse_json_body(required_fields=[
        "applicant_id", "application_type", "title", "claim_count", "independent_claim_count",
    ])
    if body["application_type"] not in APPLICATION_TYPES:
        raise make_error("ERR_VALIDATION", "Unknown application_type.")
    if not isinstance(body["title"], str):
        raise make_error("ERR_VALIDATION", "title must be a string.")
    claim_count = body["claim_count"]
    indep = body["independent_claim_count"]
    if not isinstance(claim_count, int) or isinstance(claim_count, bool) or claim_count < 0:
        raise make_error("ERR_VALIDATION", "claim_count must be a non-negative integer.")
    if not isinstance(indep, int) or isinstance(indep, bool) or indep < 0:
        raise make_error("ERR_VALIDATION", "independent_claim_count must be a non-negative integer.")
    cont_type = body.get("continuation_type")
    if cont_type is not None and cont_type not in CONTINUATION_TYPES:
        raise make_error("ERR_VALIDATION", "Unknown continuation_type.")
    with store.lock:
        application = create_application(
            applicant_id=body["applicant_id"],
            application_type=body["application_type"],
            title=body["title"],
            claim_count=claim_count,
            independent_claim_count=indep,
            parent_application_id=body.get("parent_application_id"),
            continuation_type=cont_type,
        )
    return success(serialize_application(application), status=201)


# ---------------------------------------------------------------------------
# GET /applications/{id}
# ---------------------------------------------------------------------------
@applications_bp.get("/applications/<application_id>")
@require_auth(allowed_roles=[ROLE_APPLICANT, ROLE_EXAMINER, ROLE_USPTO_ADMIN])
def get_application_route(application_id: str):
    application = store.applications.get(application_id)
    if application is None:
        raise make_error("ERR_NOT_FOUND", f"Application {application_id} not found.")
    _check_ownership_application(application)
    return success(serialize_application(application))


# ---------------------------------------------------------------------------
# PATCH /applications/{id}
# ---------------------------------------------------------------------------
@applications_bp.patch("/applications/<application_id>")
@require_auth(allowed_roles=[ROLE_APPLICANT])
def update_application_route(application_id: str):
    body = parse_json_body()
    with store.lock:
        application = update_application(
            application_id,
            title=body.get("title"),
            claim_count=body.get("claim_count"),
            independent_claim_count=body.get("independent_claim_count"),
            version=body.get("version"),
        )
    return success(serialize_application(application))


# ---------------------------------------------------------------------------
# GET /applications
# ---------------------------------------------------------------------------
@applications_bp.get("/applications")
@require_auth(allowed_roles=[ROLE_APPLICANT, ROLE_EXAMINER, ROLE_USPTO_ADMIN])
def list_applications_route():
    limit, offset = parse_pagination()
    applicant_id = request.args.get("applicant_id")
    application_type = request.args.get("application_type")
    status = request.args.get("status")
    if application_type is not None and application_type not in APPLICATION_TYPES:
        raise make_error("ERR_VALIDATION", "Unknown application_type filter.")
    if status is not None and status not in APPLICATION_STATUSES:
        raise make_error("ERR_VALIDATION", "Unknown status filter.")
    rows = []
    role = getattr(g, "user_role", None)
    user_id = getattr(g, "user_id", None)
    for a in store.applications.values():
        if applicant_id is not None and a["applicant_id"] != applicant_id:
            continue
        if application_type is not None and a["application_type"] != application_type:
            continue
        if status is not None and a["status"] != status:
            continue
        # Applicants only see their own
        if role == ROLE_APPLICANT and a["applicant_id"] != user_id:
            continue
        rows.append(a)
    total = len(rows)
    page = slice_and_sort(rows, limit, offset)
    return success(
        [serialize_application(a) for a in page],
        pagination=build_pagination_meta(limit, offset, total),
    )


# ---------------------------------------------------------------------------
# POST /applications/{id}/fees
# ---------------------------------------------------------------------------
@applications_bp.post("/applications/<application_id>/fees")
@require_auth(allowed_roles=[ROLE_APPLICANT])
def create_fee_route(application_id: str):
    body = parse_json_body(required_fields=["fee_category", "amount_cents"])
    # Existence of application is validated inside engine; but we still need
    # ownership-aware idempotency keying.
    application = store.applications.get(application_id)
    if application is None:
        raise make_error("ERR_NOT_FOUND", f"Application {application_id} not found.")
    applicant_id = application["applicant_id"]
    # Idempotency
    idem_key = request.headers.get(HEADER_IDEMPOTENCY_KEY)
    route_key = f"POST /applications/{application_id}/fees"
    payload_fp = _payload_fingerprint(body)
    with store.lock:
        if idem_key:
            cached = _idempotency_lookup(route_key, idem_key, applicant_id, payload_fp)
            if cached is not None:
                return success(cached["body"], status=cached["http_status"])
        ft = record_fee_transaction(
            application_id=application_id,
            fee_category=body["fee_category"],
            amount_cents=body["amount_cents"],
            maintenance_fee_id=body.get("maintenance_fee_id"),
            office_action_id=body.get("office_action_id"),
        )
        serialized = serialize_fee_transaction(ft)
        _idempotency_store(route_key, idem_key, applicant_id, payload_fp, serialized, 201)
    return success(serialized, status=201)


# ---------------------------------------------------------------------------
# GET /applications/{id}/fees
# ---------------------------------------------------------------------------
@applications_bp.get("/applications/<application_id>/fees")
@require_auth(allowed_roles=[ROLE_APPLICANT, ROLE_EXAMINER, ROLE_USPTO_ADMIN])
def list_fees_route(application_id: str):
    application = store.applications.get(application_id)
    if application is None:
        raise make_error("ERR_NOT_FOUND", f"Application {application_id} not found.")
    _check_ownership_application(application)
    limit, offset = parse_pagination()
    fee_category = request.args.get("fee_category")
    if fee_category is not None and fee_category not in FEE_CATEGORIES:
        raise make_error("ERR_VALIDATION", "Unknown fee_category filter.")
    rows = []
    for t in store.fee_transactions.values():
        if t["application_id"] != application_id:
            continue
        if fee_category is not None and t["fee_category"] != fee_category:
            continue
        rows.append(t)
    total = len(rows)
    page = slice_and_sort(rows, limit, offset)
    return success(
        [serialize_fee_transaction(t) for t in page],
        pagination=build_pagination_meta(limit, offset, total),
    )


# ---------------------------------------------------------------------------
# POST /applications/{id}/file
# ---------------------------------------------------------------------------
@applications_bp.post("/applications/<application_id>/file")
@require_auth(allowed_roles=[ROLE_APPLICANT])
def file_application_route(application_id: str):
    application = store.applications.get(application_id)
    if application is None:
        raise make_error("ERR_NOT_FOUND", f"Application {application_id} not found.")
    applicant_id = application["applicant_id"]
    idem_key = request.headers.get(HEADER_IDEMPOTENCY_KEY)
    route_key = f"POST /applications/{application_id}/file"
    payload_fp = _payload_fingerprint({})
    with store.lock:
        if idem_key:
            cached = _idempotency_lookup(route_key, idem_key, applicant_id, payload_fp)
            if cached is not None:
                return success(cached["body"], status=cached["http_status"])
        application = file_application(application_id)
        body = serialize_application(application)
        _idempotency_store(route_key, idem_key, applicant_id, payload_fp, body, 200)
    return success(body)


# ---------------------------------------------------------------------------
# POST /applications/{id}/begin-examination
# ---------------------------------------------------------------------------
@applications_bp.post("/applications/<application_id>/begin-examination")
@require_auth(allowed_roles=[ROLE_EXAMINER])
def begin_examination_route(application_id: str):
    with store.lock:
        application = begin_examination(application_id)
    return success(serialize_application(application))


# ---------------------------------------------------------------------------
# POST /applications/{id}/office-actions
# ---------------------------------------------------------------------------
@applications_bp.post("/applications/<application_id>/office-actions")
@require_auth(allowed_roles=[ROLE_EXAMINER])
def issue_office_action_route(application_id: str):
    body = parse_json_body(required_fields=["action_type"])
    with store.lock:
        oa = issue_office_action(application_id, action_type=body["action_type"])
    return success(serialize_office_action(oa), status=201)


# ---------------------------------------------------------------------------
# GET /applications/{id}/office-actions
# ---------------------------------------------------------------------------
@applications_bp.get("/applications/<application_id>/office-actions")
@require_auth(allowed_roles=[ROLE_APPLICANT, ROLE_EXAMINER, ROLE_USPTO_ADMIN])
def list_office_actions_route(application_id: str):
    application = store.applications.get(application_id)
    if application is None:
        raise make_error("ERR_NOT_FOUND", f"Application {application_id} not found.")
    _check_ownership_application(application)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    if status is not None and status not in OA_STATUSES:
        raise make_error("ERR_VALIDATION", "Unknown status filter.")
    rows = [oa for oa in store.office_actions.values()
            if oa["application_id"] == application_id
            and (status is None or oa["status"] == status)]
    total = len(rows)
    page = slice_and_sort(rows, limit, offset)
    return success(
        [serialize_office_action(oa) for oa in page],
        pagination=build_pagination_meta(limit, offset, total),
    )


# ---------------------------------------------------------------------------
# POST /applications/{id}/allow
# ---------------------------------------------------------------------------
@applications_bp.post("/applications/<application_id>/allow")
@require_auth(allowed_roles=[ROLE_EXAMINER])
def allow_application_route(application_id: str):
    with store.lock:
        application = allow_application(application_id)
    return success(serialize_application(application))


# ---------------------------------------------------------------------------
# POST /applications/{id}/grant
# ---------------------------------------------------------------------------
@applications_bp.post("/applications/<application_id>/grant")
@require_auth(allowed_roles=[ROLE_EXAMINER])
def grant_application_route(application_id: str):
    with store.lock:
        application = grant_application(application_id)
    return success(serialize_application(application))


# ---------------------------------------------------------------------------
# POST /applications/{id}/abandon
# ---------------------------------------------------------------------------
@applications_bp.post("/applications/<application_id>/abandon")
@require_auth(allowed_roles=[ROLE_APPLICANT])
def abandon_application_route(application_id: str):
    with store.lock:
        application = abandon_application(application_id)
    return success(serialize_application(application))


# ---------------------------------------------------------------------------
# POST /applications/{id}/pct-phases
# ---------------------------------------------------------------------------
@applications_bp.post("/applications/<application_id>/pct-phases")
@require_auth(allowed_roles=[ROLE_APPLICANT])
def create_pct_phase_route(application_id: str):
    with store.lock:
        pct = create_pct_phase(application_id)
    return success(serialize_pct_phase(pct), status=201)


# ---------------------------------------------------------------------------
# GET /applications/{id}/maintenance-fees
# ---------------------------------------------------------------------------
@applications_bp.get("/applications/<application_id>/maintenance-fees")
@require_auth(allowed_roles=[ROLE_APPLICANT, ROLE_EXAMINER, ROLE_USPTO_ADMIN])
def list_maintenance_fees_route(application_id: str):
    application = store.applications.get(application_id)
    if application is None:
        raise make_error("ERR_NOT_FOUND", f"Application {application_id} not found.")
    _check_ownership_application(application)
    # MAINTENANCE_NOT_APPLICABLE — non-UTILITY or non-GRANTED rejected
    if application["application_type"] != APP_TYPE_UTILITY or application["status"] != APP_STATUS_GRANTED:
        raise make_error("ERR_MAINTENANCE_NOT_APPLICABLE")
    limit, offset = parse_pagination()
    status = request.args.get("status")
    if status is not None and status not in MAINTENANCE_STATUSES:
        raise make_error("ERR_VALIDATION", "Unknown status filter.")
    rows = [mf for mf in store.maintenance_fees.values()
            if mf["application_id"] == application_id
            and (status is None or mf["status"] == status)]
    total = len(rows)
    page = slice_and_sort(rows, limit, offset)
    return success(
        [serialize_maintenance_fee(mf) for mf in page],
        pagination=build_pagination_meta(limit, offset, total),
    )


# ---------------------------------------------------------------------------
# GET /applications/{id}/audit-events
# ---------------------------------------------------------------------------
@applications_bp.get("/applications/<application_id>/audit-events")
@require_auth(allowed_roles=[ROLE_USPTO_ADMIN, ROLE_EXAMINER, ROLE_APPLICANT])
def list_audit_events_route(application_id: str):
    application = store.applications.get(application_id)
    if application is None:
        raise make_error("ERR_NOT_FOUND", f"Application {application_id} not found.")
    _check_ownership_application(application)
    limit, offset = parse_pagination()
    rows = [ae for ae in store.audit_events if ae["application_id"] == application_id]
    total = len(rows)
    page = slice_and_sort(rows, limit, offset)
    return success(
        [serialize_audit_event(ae) for ae in page],
        pagination=build_pagination_meta(limit, offset, total),
    )
