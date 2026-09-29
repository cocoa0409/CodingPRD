"""Shared list-endpoint plumbing (PRD §2.3)."""

from response import ok_list
from serializers import serialize_all
from validation import apply_filters, parse_filters, parse_pagination


def list_response(records):
    limit, offset = parse_pagination()
    filters = parse_filters()
    records = apply_filters(records, filters)
    total_count = len(records)
    page = records[offset : offset + limit]
    return ok_list(serialize_all(page), limit, offset, total_count)
