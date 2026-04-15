"""Pagination helper using opaque page_token (base64-encoded offset)."""
import base64
import json
from flask import request
from errors import raise_error, INVALID_PAGE_PARAMS


def parse_page_params():
    """Parse page_size and page_token from query params. Returns (page_size, offset)."""
    page_size_str = request.args.get("page_size", "20")
    page_token = request.args.get("page_token", None)

    try:
        page_size = int(page_size_str)
    except (ValueError, TypeError):
        raise_error(INVALID_PAGE_PARAMS, "page_size must be an integer")

    if page_size < 1 or page_size > 50:
        raise_error(INVALID_PAGE_PARAMS, "page_size must be between 1 and 50")

    offset = 0
    if page_token:
        try:
            decoded = base64.b64decode(page_token).decode("utf-8")
            token_data = json.loads(decoded)
            offset = token_data["off"]
        except Exception:
            raise_error(INVALID_PAGE_PARAMS, "page_token is malformed")

    return page_size, offset


def make_page_token(offset):
    """Create an opaque page_token encoding the offset."""
    data = json.dumps({"off": offset})
    return base64.b64encode(data.encode("utf-8")).decode("utf-8")


def paginate(items, page_size, offset):
    """Paginate a list of items. Returns (page_items, total_results, next_page_token)."""
    total_results = len(items)
    page_items = items[offset:offset + page_size]
    next_offset = offset + page_size
    next_page_token = make_page_token(next_offset) if next_offset < total_results else None
    return page_items, total_results, next_page_token
