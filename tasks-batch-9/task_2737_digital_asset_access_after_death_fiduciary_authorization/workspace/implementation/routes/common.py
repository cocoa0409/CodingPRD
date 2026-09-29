"""Shared list/detail plumbing for every route module."""
from db import sorted_records
from response import collection, public
from validation import apply_filters, pagination


def paged(records, args, filter_spec):
    limit, offset = pagination(args)
    records = apply_filters(list(records), args, filter_spec)
    records = sorted_records(records)
    total = len(records)
    page = records[offset:offset + limit]
    return collection([public(r) for r in page], limit, offset, total)
