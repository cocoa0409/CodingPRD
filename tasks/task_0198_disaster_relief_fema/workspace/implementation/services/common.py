"""Shared helpers: existence lookups, pagination parsing, list filtering."""
from flask import request

from db import STORE
from errors import ApiError
from response import paginate
from services.models import serialize, sort_by_created

# collection attribute -> not-found error id
_NOT_FOUND = {
    "declarations": "ERR_DECLARATION_NOT_FOUND",
    "inspectors": "ERR_INSPECTOR_NOT_FOUND",
    "caseworkers": "ERR_CASEWORKER_NOT_FOUND",
    "applicants": "ERR_APPLICANT_NOT_FOUND",
    "assessments": "ERR_ASSESSMENT_NOT_FOUND",
    "ihp_cases": "ERR_CASE_NOT_FOUND",
    "award_line_items": "ERR_LINE_ITEM_NOT_FOUND",
    "dob_records": "ERR_DOB_NOT_FOUND",
    "appeals": "ERR_APPEAL_NOT_FOUND",
    "sba_referrals": "ERR_REFERRAL_NOT_FOUND",
    "disbursements": "ERR_DISBURSEMENT_NOT_FOUND",
    "recoupments": "ERR_RECOUPMENT_NOT_FOUND",
    "rental_periods": None,  # rental periods have no dedicated not-found in catalog
}


def lookup(collection_attr, entity_id):
    """Fetch an entity by id from a collection or raise its not-found error."""
    coll = getattr(STORE, collection_attr)
    ent = coll.get(entity_id)
    if ent is None:
        err = _NOT_FOUND.get(collection_attr)
        if err is None:
            # No dedicated catalog error (e.g. rental periods); generic 404.
            raise ApiError("ERR_NOT_FOUND", "Resource not found.", 404)
        raise ApiError(err)
    return ent


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3): limit default 10, min 1, max 100; offset default 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            offset = 0
    return limit, offset


def list_response(items, filters=None):
    """Apply equality filters from query params, sort by creation, paginate, serialize.

    filters: dict of {query_param: entity_field}. Values matched as strings.
    Returns (data_list, pagination_dict).
    """
    items = list(items)
    if filters:
        for param, field in filters.items():
            val = request.args.get(param)
            if val is not None:
                items = [e for e in items if str(e.get(field)) == val]
    items = sort_by_created(items)
    total = len(items)
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    data = [serialize(e) for e in page]
    return data, paginate(page, limit, offset, total)
