"""Invoice endpoints (PRD §3.4). Invoices are append-only and immutable."""

from flask import Blueprint, request, g

import errors
from db import db
from helpers import parse_pagination, sort_by_created, paginate
from middleware import require_roles
from response import success, list_success
from serializers import serialize_invoice
from services.lookups import get_invoice_or_404

bp = Blueprint("invoices", __name__)


def _member_owns_invoice(inv):
    sub = db.subscriptions.get(inv["subscription_id"])
    return sub is not None and sub["member_id"] == g.user_id


@bp.get("/invoices")
@require_roles("PlatformAdmin", "LocationManager", "Member")
def list_invoices():
    limit, offset = parse_pagination()
    subscription_id = request.args.get("subscription_id")
    kind = request.args.get("kind")
    status = request.args.get("status")
    items = list(db.invoices.values())
    if g.user_role == "Member":
        items = [i for i in items if _member_owns_invoice(i)]
    if subscription_id is not None:
        items = [i for i in items if i["subscription_id"] == subscription_id]
    if kind is not None:
        items = [i for i in items if i["kind"] == kind]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_invoice(i) for i in page], limit, offset, total)


@bp.get("/invoices/<invoice_id>")
@require_roles("PlatformAdmin", "LocationManager", "Member")
def get_invoice(invoice_id):
    inv = get_invoice_or_404(invoice_id)
    if g.user_role == "Member" and not _member_owns_invoice(inv):
        raise errors.forbidden("A member may read only their own invoices")
    return success(serialize_invoice(inv), 200)
