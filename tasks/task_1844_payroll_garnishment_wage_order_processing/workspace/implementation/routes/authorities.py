"""IssuingAuthority registration and reverse-reachability listings."""

import re

from flask import Blueprint

from db import logical_now, next_seq, store
from errors import ERR_INVALID_REQUEST, ERR_NOT_FOUND, fail
from middleware import (
    ALL_ROLES,
    ROLE_ADMIN,
    authorize,
    get_body,
    pagination,
    public,
    req_enum,
    req_str,
    sort_created,
)
from response import list_response, object_response
from util import new_uuid, render_instant

bp = Blueprint("authorities", __name__)

AUTHORITY_TYPES = ("COURT", "CHILD_SUPPORT_AGENCY", "FEDERAL_AGENCY", "STATE_AGENCY")


def get_authority_or_404(authority_id):
    authority = store.authorities.get(authority_id)
    if authority is None:
        fail(ERR_NOT_FOUND, 404, "IssuingAuthority '%s' does not exist." % authority_id)
    return authority


@bp.post("/authorities")
def create_authority():
    authorize(ROLE_ADMIN)
    body = get_body()
    name = req_str(body, "name")
    authority_type = req_enum(body, "authority_type", AUTHORITY_TYPES)
    state_code = req_str(body, "state_code")
    pattern = req_str(body, "accepted_case_number_pattern")
    try:
        re.compile(pattern)
    except re.error:
        fail(ERR_INVALID_REQUEST, 400,
             "accepted_case_number_pattern must be a valid regular expression.")

    authority = {
        "id": new_uuid(),
        "created_at": render_instant(logical_now()),
        "updated_at": render_instant(logical_now()),
        "version": 1,
        "name": name,
        "authority_type": authority_type,
        "state_code": state_code,
        "accepted_case_number_pattern": pattern,
        "_seq": next_seq(),
    }
    store.authorities[authority["id"]] = authority
    return object_response(public(authority), 201)


@bp.get("/authorities/<authorityId>")
def get_authority(authorityId):
    authorize(*ALL_ROLES)
    return object_response(public(get_authority_or_404(authorityId)))


@bp.get("/authorities/<authorityId>/remittances")
def list_authority_remittances(authorityId):
    authorize(*ALL_ROLES)
    get_authority_or_404(authorityId)
    limit, offset = pagination()
    items = sort_created(
        [r for r in store.remittances.values() if r["authority_id"] == authorityId]
    )
    page = items[offset:offset + limit]
    return list_response([public(r) for r in page], len(items), limit, offset)


@bp.get("/authorities/<authorityId>/orders")
def list_authority_orders(authorityId):
    authorize(*ALL_ROLES)
    get_authority_or_404(authorityId)
    limit, offset = pagination()
    items = sort_created(
        [o for o in store.orders.values() if o["issuing_authority_id"] == authorityId]
    )
    page = items[offset:offset + limit]
    return list_response([public(o) for o in page], len(items), limit, offset)
