"""Listing helpers: conjunctive filters, created_at ASC order, pagination."""
import db
from response import ok_list
from services.serializers import serialize_many
from utils import paginate, pagination_args, sort_created


def filtered(store, params, args):
    """Filters combine conjunctively; unknown query params are ignored."""
    rows = db.all_of(store)
    for param in params:
        value = args.get(param)
        if value is None:
            continue
        rows = [row for row in rows
                if row.get(param) is not None and str(row.get(param)) == value]
    return sort_created(rows)


def paged(rows, args):
    limit, offset = pagination_args(args)
    page, total, has_more = paginate(rows, limit, offset)
    return ok_list(serialize_many(page), total, limit, offset, has_more)


def listing(store, params, args):
    return paged(filtered(store, params, args), args)
