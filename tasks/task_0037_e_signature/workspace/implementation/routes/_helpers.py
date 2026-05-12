"""Shared helpers for route handlers."""

from flask import request

from errors import validation_failed


def parse_pagination():
    """Parse limit/offset with defaults from PRD §2.3."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise validation_failed("limit must be an integer")
        if limit < 1 or limit > 100:
            raise validation_failed("limit must be 1..100")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise validation_failed("offset must be an integer")
        if offset < 0:
            raise validation_failed("offset must be >= 0")
    return limit, offset


def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    return body
