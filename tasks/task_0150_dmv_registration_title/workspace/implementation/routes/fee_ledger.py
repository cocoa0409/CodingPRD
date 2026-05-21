"""FeeLedgerEntry listing endpoint — append-only audit view."""

from flask import Blueprint

from config import ROLE_APPLICANT, ROLE_PLATFORM_ADMIN, ROLE_TAX_ASSESSOR
from db import store
from errors import make_error
from middleware import require_auth
from response import success
from routes._helpers import (
    build_pagination_meta,
    paginate_and_sort,
    parse_pagination,
)
from services.serializers import serialize_ledger_entry

ledger_bp = Blueprint("ledger", __name__)


@ledger_bp.route("/transfer-applications/<app_id>/fee-ledger", methods=["GET"])
@require_auth(allowed_roles=[ROLE_PLATFORM_ADMIN, ROLE_TAX_ASSESSOR, ROLE_APPLICANT])
def list_fee_ledger(app_id: str):
    limit, offset = parse_pagination()
    app = store.transfer_applications.get(app_id)
    if app is None:
        raise make_error("ERR_RESOURCE_NOT_FOUND")
    rows = [e for e in store.fee_ledger if e["application_id"] == app_id]
    page, total = paginate_and_sort(rows, limit, offset, sort_key="occurred_at")
    return success([serialize_ledger_entry(e) for e in page],
                   pagination=build_pagination_meta(limit, offset, total))
