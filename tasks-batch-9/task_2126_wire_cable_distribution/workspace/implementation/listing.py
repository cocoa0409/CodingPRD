"""List-endpoint helper: pagination window plus the standard array envelope."""
import response
import validation


def respond(rows, serializer):
    limit, offset = validation.pagination()
    page, total = validation.paginate(rows, limit, offset)
    return response.list_response([serializer(r) for r in page], limit, offset, total)
