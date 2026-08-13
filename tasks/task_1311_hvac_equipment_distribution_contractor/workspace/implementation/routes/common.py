"""Shared route helpers."""
from flask import request

import clock
import utils
from errors import ApiError, not_found, ref_not_found, ERR_INVALID_REQUEST
from middleware import pagination_params
from response import success_list
from utils import next_seq


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def get_path(store, entity_id):
    e = store.get(entity_id)
    if e is None:
        raise not_found()
    return e


def get_ref(store, entity_id, label="referenced resource"):
    e = store.get(entity_id)
    if e is None:
        raise ref_not_found("%s does not exist: %s" % (label, entity_id))
    return e


def new_common():
    now = clock.now()
    return {"id": utils.new_id(), "created_at": now, "updated_at": now,
            "version": 1, "_seq": next_seq()}


def list_response(items, serializer, filters=None, owner_field=None,
                  role=None, user_id=None):
    """Sort by created_at ASC (insertion order breaks ties), apply exact-match
    filters and ContractorUser ownership restriction, then paginate."""
    result = list(items)
    if role == "ContractorUser" and owner_field is not None:
        result = [e for e in result if e.get(owner_field) in (None, user_id)]
    if filters:
        for field, value in filters.items():
            if value is None:
                continue
            result = [e for e in result if e.get(field) == value]
    result.sort(key=lambda e: (e["created_at"], e.get("_seq", 0)))
    total = len(result)
    limit, offset = pagination_params()
    page = result[offset:offset + limit]
    return success_list([serializer(e) for e in page], limit, offset, total)
