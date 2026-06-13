"""Shared route helpers: list sorting + pagination (PRD §2.3)."""
import response
import validation


def sorted_by_creation(records):
    """Ascending by creation order (created_at asc, PRD §2.3).
    `_seq` is a monotonic tiebreaker for records minted in the same ms."""
    return sorted(records, key=lambda r: r["_seq"])


def list_response(records, args, serializer):
    """Sort by creation, paginate, serialize, wrap in the array envelope."""
    limit, offset = validation.parse_pagination(args)
    ordered = sorted_by_creation(records)
    page, total = validation.paginate(ordered, limit, offset)
    return response.array_response(
        [serializer(r) for r in page], limit, offset, total)
