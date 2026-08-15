"""Shortfall pledge deposit."""

from db import now
from errors import ApiError
from helpers import (
    get_body, check_allowed_fields, get_pledge_or_404, get_holdback_or_404,
    touch, append_ledger, refresh_holdback_derived, ser_pledge,
)
from middleware import authenticate, authorize
from response import success

from . import bp


@bp.post("/escrow/shortfall-pledges/<pid>/deposit")
def deposit_pledge(pid):
    _uid, role = authenticate()
    authorize(role, ["EscrowOfficer"])
    p = get_pledge_or_404(pid)
    data = get_body()
    check_allowed_fields(data, set())
    hb = get_holdback_or_404(p["holdback_id"])

    # Rung 7: only a PLEDGED pledge can be deposited.
    if p["status"] != "PLEDGED":
        raise ApiError("ERR_INVALID_STATE", "Shortfall pledge is not PLEDGED")

    p["status"] = "DEPOSITED"
    p["deposited_at"] = now()
    touch(p)
    append_ledger(hb, "SHORTFALL_DEPOSIT", p["amount_cents"],
                  "Shortfall deposit for pledge %s" % p["id"])
    hb["total_shortfall_deposited_cents"] += p["amount_cents"]
    refresh_holdback_derived(hb)
    touch(hb)
    return success(ser_pledge(p), response_type="object", status=200)
