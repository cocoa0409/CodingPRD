"""DeferredTaxItem endpoints: system-generated, read-only (list + get)."""
from flask import Blueprint

from db import db
from middleware import authorized, READER_ROLES
from response import success_object, success_list
from routes.common import get_or_404, apply_filters, paginate
from serializers import serialize

bp = Blueprint("deferred_items", __name__)


@bp.route("/tax/deferred-tax-items", methods=["GET"])
def list_deferred_items():
    authorized(READER_ROLES)
    recs = apply_filters(db.deferred_items.values(), {
        "tax_year_id": "tax_year_id",
        "source_difference_id": "source_difference_id",
        "item_kind": "item_kind",
    })
    page, total, limit, offset = paginate(recs)
    return success_list([serialize(r) for r in page], total, limit, offset)


@bp.route("/tax/deferred-tax-items/<deferredItemId>", methods=["GET"])
def get_deferred_item(deferredItemId):
    authorized(READER_ROLES)
    return success_object(serialize(get_or_404(db.deferred_items, deferredItemId, "DeferredTaxItem")))
