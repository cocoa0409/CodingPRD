"""RenewalReminder list-under-contract route (PRD §3.8)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from middleware import require_auth, current_role, current_user_id
from response import ok_array, paginate_params, slice_page
from services.validation import lookup_or_404
from services.ownership import assert_customer_owns_contract


bp = Blueprint("renewal_reminders", __name__)


@bp.get("/contracts/<cid>/renewal-reminders")
def list_renewal_reminders(cid: str):
    require_auth(["PlatformAdmin", "Customer"])()
    contract = lookup_or_404(db.contracts, cid, "Contract")
    assert_customer_owns_contract(contract, current_role(), current_user_id())

    limit, offset = paginate_params(request.args)
    items = [r for r in db.renewal_reminders.values() if r["contract_id"] == cid]
    items.sort(key=lambda r: r["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)
