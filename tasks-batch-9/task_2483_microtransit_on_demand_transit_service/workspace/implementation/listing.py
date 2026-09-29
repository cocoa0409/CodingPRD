"""Shared collection-listing helper (PRD Section 2.3)."""
import response
import serializers
import validation


def list_endpoint(rows, fields, filter_spec=None):
    limit, offset = validation.pagination()
    if filter_spec:
        rows = validation.filters(rows, filter_spec)
    total_count = len(rows)
    page = validation.paginate(rows, limit, offset)
    return response.list_response(serializers.many(page, fields), limit, offset,
                                  total_count)
