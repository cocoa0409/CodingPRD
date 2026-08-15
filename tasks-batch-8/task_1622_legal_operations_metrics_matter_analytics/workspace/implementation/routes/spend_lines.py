from flask import Blueprint, request

from db import store
from middleware import require_roles
from response import object_response, list_response
from serializers import spend_line_view
from validation import require_exists, pagination_params

bp = Blueprint("spend_lines", __name__, url_prefix="/legal-ops/spend-lines")

ALL = ("LegalOpsManager", "LegalOpsAnalyst", "LegalOpsExecutive")


def _invoice_created_at(line):
    inv = store.invoices.get(line["invoice_id"])
    return inv["created_at"] if inv is not None else ""


@bp.get("")
@require_roles(*ALL)
def list_spend_lines(user_id, role):
    items = list(store.spend_lines.values())
    for param in ("matter_id", "fiscal_period_id", "firm_id", "source_status",
                  "invoice_id", "reversal_of_id"):
        v = request.args.get(param)
        if v is not None:
            items = [l for l in items if l[param] == v]
    limit, offset = pagination_params()
    # created_at ASC default; posting order pins (posting_date, invoice.created_at)
    # for same-tick ties; spend line id is never a sort key.
    ordered = sorted(
        items,
        key=lambda l: (l["created_at"], l["posting_date"] or "", _invoice_created_at(l), l["_seq"]),
    )
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return list_response([spend_line_view(l) for l in page], total, limit, offset)


@bp.get("/<sid>")
@require_roles(*ALL)
def get_spend_line(user_id, role, sid):
    return object_response(spend_line_view(require_exists(store.spend_lines, sid, "spend line")))
