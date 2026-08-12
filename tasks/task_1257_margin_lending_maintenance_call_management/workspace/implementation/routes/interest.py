"""Rate tiers, interest ledger entries, interest summary (PRD 3.9)."""
from datetime import date

from flask import Blueprint, request

from authz import ANY_ROLE, SUPERVISOR, require_roles
from cascades import interest_summary
from db import store
from errors import interest_entry_not_found, rate_tier_not_found, rate_tier_overlap
from response import success
from serialize import ser_interest_entry, ser_rate_tier
from store_ops import (
    json_body,
    new_id,
    opt_iso_date,
    paginate,
    req_int,
    req_iso_date,
    sorted_by_creation,
    stamp_new,
)
from routes.accounts import get_account_or_404

bp = Blueprint("interest", __name__)


@bp.route("/margin/rate-tiers", methods=["POST"])
def create_rate_tier():
    data = json_body()
    tier_level = req_int(data, "tier_level")
    min_balance = req_int(data, "min_balance_cents")
    annual_rate = req_int(data, "annual_rate_bps")
    effective_from = req_iso_date(data, "effective_from")
    effective_to = opt_iso_date(data, "effective_to")
    require_roles([SUPERVISOR])
    # Closed intervals of the same tier_level may not share a calendar date;
    # back-to-back windows are allowed.
    for t in store.rate_tiers.values():
        if t["tier_level"] != tier_level:
            continue
        a_end = effective_to if effective_to is not None else date.max
        b_end = t["effective_to"] if t["effective_to"] is not None else date.max
        if effective_from <= b_end and t["effective_from"] <= a_end:
            raise rate_tier_overlap()
    tier = {
        "id": new_id(),
        "tier_level": tier_level,
        "min_balance_cents": min_balance,
        "annual_rate_bps": annual_rate,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    stamp_new(tier)
    store.rate_tiers[tier["id"]] = tier
    return success(ser_rate_tier(tier), status=201)


@bp.route("/margin/rate-tiers/<tid>", methods=["GET"])
def get_rate_tier(tid):
    require_roles(ANY_ROLE)
    tier = store.rate_tiers.get(tid)
    if tier is None:
        raise rate_tier_not_found()
    return success(ser_rate_tier(tier))


@bp.route("/margin/rate-tiers", methods=["GET"])
def list_rate_tiers():
    require_roles(ANY_ROLE)
    items = sorted_by_creation(list(store.rate_tiers.values()))
    page, pagination = paginate(items)
    return success([ser_rate_tier(t) for t in page], response_type="array",
                   pagination=pagination)


@bp.route("/margin/accounts/<aid>/interest-entries", methods=["GET"])
def list_interest_entries(aid):
    require_roles(ANY_ROLE)
    get_account_or_404(aid)
    entry_type = request.args.get("entry_type")
    items = [e for e in store.interest_entries.values() if e["account_id"] == aid]
    if entry_type is not None:
        items = [e for e in items if e["entry_type"] == entry_type]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_interest_entry(e) for e in page], response_type="array",
                   pagination=pagination)


@bp.route("/margin/interest-entries/<eid>", methods=["GET"])
def get_interest_entry(eid):
    require_roles(ANY_ROLE)
    entry = store.interest_entries.get(eid)
    if entry is None:
        raise interest_entry_not_found()
    return success(ser_interest_entry(entry))


@bp.route("/margin/accounts/<aid>/interest-summary", methods=["GET"])
def get_interest_summary(aid):
    require_roles(ANY_ROLE)
    account = get_account_or_404(aid)
    return success(interest_summary(account, store.clock.date()))
