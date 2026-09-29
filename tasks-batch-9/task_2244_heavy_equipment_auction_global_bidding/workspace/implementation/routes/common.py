"""Shared imports and small helpers for the route modules."""
from flask import Blueprint  # noqa: F401  (re-exported)

from db import db, new_entity, ordered, touch  # noqa: F401
from errors import ApiError  # noqa: F401
from middleware import (  # noqa: F401
    ANY_ROLE, endpoint, field_bool, field_country, field_currency, field_dt,
    field_decimal, field_enum, field_int, field_str, json_body, pagination,
    paginate, query_bool, query_enum, query_str, require_owner,
)
from response import list_response, object_response  # noqa: F401
from services import constants as C  # noqa: F401
from services.derive import fetch, rows_of  # noqa: F401


def collection_response(rows, limit, offset):
    page, total = paginate(ordered(rows), limit, offset)
    return list_response(page, limit, offset, total)


def invalid_state(message="The resource is not in a state that permits this operation."):
    return ApiError("ERR_INVALID_STATE", message)
