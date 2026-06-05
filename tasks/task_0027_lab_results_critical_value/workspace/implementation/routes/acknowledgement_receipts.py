"""AcknowledgementReceipt read endpoints (creation lives in critical_notifications.py)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from middleware import require_auth
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import lookup_or_404


bp = Blueprint("acknowledgement_receipts", __name__)


@bp.get("/acknowledgement-receipts/<aid>")
def get_receipt(aid):
    require_auth(["LabTech", "LabDirector", "OrderingProvider"])()
    a = lookup_or_404(db.acknowledgement_receipts, aid, "AcknowledgementReceipt")
    return ok_object(a)


@bp.get("/acknowledgement-receipts")
def list_receipts():
    require_auth(["LabTech", "LabDirector", "OrderingProvider"])()
    limit, offset = paginate_params(request.args)
    items = list(db.acknowledgement_receipts.values())
    for key in ("critical_notification_id", "acknowledging_clinician_id"):
        val = request.args.get(key)
        if val is not None:
            items = [a for a in items if a.get(key) == val]
    items.sort(key=lambda x: x["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)
