"""FundingAuthorization endpoints."""

from flask import Blueprint, request

import errors
import validation as v
from db import store, new_entity, touch
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list

bp = Blueprint("funding", __name__)


@bp.post("/api/funding-authorizations")
def create_funding_authorization():
    require_roles(["FundingCoordinator"])
    body = v.require_body(request.get_json(silent=True))
    v.reject_unknown_fields(body, {
        "client_id", "payer_type", "payer_ref", "authorized_amount_cents",
        "valid_from", "valid_until",
    })
    client_id = v.req_string(body, "client_id")
    payer_type = v.req_enum(body, "payer_type", {"VR", "INSURANCE"})
    payer_ref = v.req_string(body, "payer_ref")
    authorized_amount_cents = v.req_int(body, "authorized_amount_cents", min_v=1)
    valid_from = v.req_datetime(body, "valid_from")
    valid_until = v.req_datetime(body, "valid_until")
    if valid_from > valid_until:
        raise errors.validation("valid_from must be on or before valid_until")

    if client_id not in store.clients:
        raise errors.not_found("Client not found")

    from db import format_instant
    auth = new_entity()
    auth.update({
        "client_id": client_id,
        "payer_type": payer_type,
        "payer_ref": payer_ref,
        "authorized_amount_cents": authorized_amount_cents,
        "remaining_amount_cents": authorized_amount_cents,
        "valid_from": format_instant(valid_from),
        "valid_until": format_instant(valid_until),
        "submitted_by_user_id": None,
        "adjudicated_by_user_id": None,
        "status": "DRAFT",
    })
    store.funding_authorizations[auth["id"]] = auth
    return success_object(auth, status=201)


@bp.get("/api/funding-authorizations/<aid>")
def get_funding_authorization(aid):
    require_roles(ALL_ROLES)
    auth = store.funding_authorizations.get(aid)
    if auth is None:
        raise errors.not_found("FundingAuthorization not found")
    return success_object(auth)


@bp.get("/api/funding-authorizations")
def list_funding_authorizations():
    require_roles(ALL_ROLES)
    limit, offset = v.parse_pagination(request.args)
    items = v.apply_filters(list(store.funding_authorizations.values()), [
        (request.args.get("client_id"), "client_id"),
        (request.args.get("status"), "status"),
    ])
    items = v.sort_by_created(items)
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.post("/api/funding-authorizations/<aid>/submit")
def submit_funding_authorization(aid):
    actor = require_roles(["FundingCoordinator"])
    auth = store.funding_authorizations.get(aid)
    if auth is None:
        raise errors.not_found("FundingAuthorization not found")
    if auth["status"] not in ("DRAFT", "APPEALED"):
        raise errors.invalid_state("Authorization cannot be submitted from its current state")
    auth["status"] = "SUBMITTED"
    auth["submitted_by_user_id"] = actor.user_id
    touch(auth)
    return success_object(auth)


@bp.post("/api/funding-authorizations/<aid>/adjudicate")
def adjudicate_funding_authorization(aid):
    actor = require_roles(["PayerAdjudicator"])
    body = v.require_body(request.get_json(silent=True))
    v.reject_unknown_fields(body, {"decision"})
    decision = v.req_enum(body, "decision", {"APPROVE", "DENY"})

    auth = store.funding_authorizations.get(aid)
    if auth is None:
        raise errors.not_found("FundingAuthorization not found")
    if auth["status"] != "SUBMITTED":
        raise errors.invalid_state("Authorization is not SUBMITTED")
    if auth["submitted_by_user_id"] == actor.user_id:
        raise errors.segregation()

    auth["status"] = "APPROVED" if decision == "APPROVE" else "DENIED"
    auth["adjudicated_by_user_id"] = actor.user_id
    touch(auth)
    return success_object(auth)


@bp.post("/api/funding-authorizations/<aid>/appeal")
def appeal_funding_authorization(aid):
    require_roles(["FundingCoordinator"])
    auth = store.funding_authorizations.get(aid)
    if auth is None:
        raise errors.not_found("FundingAuthorization not found")
    if auth["status"] != "DENIED":
        raise errors.invalid_state("Only a DENIED authorization can be appealed")
    auth["status"] = "APPEALED"
    touch(auth)
    return success_object(auth)
