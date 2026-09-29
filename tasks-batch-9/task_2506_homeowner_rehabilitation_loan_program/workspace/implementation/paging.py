"""Offset/limit collection helper (PRD 2.4)."""

import db
import response
import validation


def collection(rows, serializer):
    limit, offset = validation.pagination()
    ordered = db.ordered(rows)
    total_count = len(ordered)
    page = ordered[offset : offset + limit]
    return response.array_response(
        [serializer(row) for row in page], limit, offset, total_count
    )
