"""Warranty reserve reads, ledger reads, and OCC-guarded adjustments (PRD 3.7)."""
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request

from db import db, sorted_items
from errors import (
    raise_error,
    ERR_INVALID_ADJUSTMENT,
    ERR_INVALID_REQUEST,
    ERR_RESERVE_NOT_FOUND,
    ERR_STALE_VERSION,
)
from middleware import get_caller, require_role
from response import success_list, success_object
from services.calc import expected_accrual_cents, monthly_accrual_cents
from services.reserve import post_entry
from util import months_elapsed, serialize
from validate import (
    apply_page,
    get_body,
    pagination_params,
    req_enum,
    req_int,
    req_number,
    opt_nullable_str,
)
from clock import CLOCK

bp = Blueprint("reserves", __name__)

ADJUSTMENT_KINDS = {"MANUAL_ADJUSTMENT", "TRUE_UP"}
READ_ROLES = {"WarrantyManager", "FinanceAdmin", "WarrantyRep"}


def _get_reserve_or_404(rid):
    reserve = db["warranty_reserves"].get(rid)
    if reserve is None:
        raise_error(ERR_RESERVE_NOT_FOUND, f"warranty reserve id does not resolve: {rid}")
    return reserve


@bp.get("/warranty-reserves/<rid>")
def fetch_reserve(rid):
    _uid, role = get_caller()
    require_role(role, READ_ROLES)
    return success_object(serialize(_get_reserve_or_404(rid)))


@bp.get("/warranty-reserves")
def list_reserves():
    _uid, role = get_caller()
    require_role(role, READ_ROLES)
    limit, offset = pagination_params()
    home_id = request.args.get("home_id")
    alert_status = request.args.get("alert_status")
    items = sorted_items("warranty_reserves")
    if home_id is not None:
        items = [r for r in items if r["home_id"] == home_id]
    if alert_status is not None:
        items = [r for r in items if r["alert_status"] == alert_status]
    page, total = apply_page(items, limit, offset)
    return success_list([serialize(r) for r in page], total, limit, offset)


@bp.get("/warranty-reserves/<rid>/entries")
def list_entries(rid):
    _uid, role = get_caller()
    require_role(role, READ_ROLES)
    reserve = _get_reserve_or_404(rid)
    limit, offset = pagination_params()
    kind = request.args.get("kind")
    # Chronological order: created_at ascending with insertion order as tie-break.
    items = sorted(
        (e for e in db["reserve_entries"].values() if e["reserve_id"] == reserve["id"]),
        key=lambda e: (e["created_at"], e["_seq"]),
    )
    if kind is not None:
        items = [e for e in items if e["kind"] == kind]
    page, total = apply_page(items, limit, offset)
    return success_list([serialize(e) for e in page], total, limit, offset)


@bp.post("/warranty-reserves/<rid>/adjustments")
def post_adjustment(rid):
    _uid, role = get_caller()
    require_role(role, {"FinanceAdmin"})
    reserve = _get_reserve_or_404(rid)
    body = get_body()
    # Shape (precedence 5): kind, the kind-specific field, and the OCC field are
    # all required; a missing kind-required field is ERR_INVALID_REQUEST.
    kind = req_enum(body, "kind", ADJUSTMENT_KINDS)
    amount_cents = None
    revised_accrual_rate = None
    if kind == "MANUAL_ADJUSTMENT":
        amount_cents = req_int(body, "amount_cents")
    else:
        revised_accrual_rate = req_number(body, "revised_accrual_rate")
    expected_reserve_version = req_int(body, "expected_reserve_version")
    note = opt_nullable_str(body, "note")
    # Stale-version guard (precedence 7, OCC): the only OCC-guarded endpoint.
    if expected_reserve_version != reserve["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_reserve_version does not match the reserve's current version")
    # Adjustment bounds (precedence 8).
    if kind == "MANUAL_ADJUSTMENT":
        if amount_cents == 0:
            raise_error(ERR_INVALID_ADJUSTMENT,
                        "MANUAL_ADJUSTMENT requires a non-zero amount_cents")
        entry = post_entry(reserve, "MANUAL_ADJUSTMENT", amount_cents, note=note)
    else:
        try:
            rate = Decimal(str(revised_accrual_rate))
        except (InvalidOperation, ValueError):
            raise_error(ERR_INVALID_REQUEST, "revised_accrual_rate must be numeric")
        if rate <= 0:
            raise_error(ERR_INVALID_ADJUSTMENT,
                        "TRUE_UP requires a revised_accrual_rate > 0")
        home = db["homes"].get(reserve["home_id"])
        new_expected = expected_accrual_cents(home["sale_price_cents"], rate)
        new_monthly = monthly_accrual_cents(new_expected)
        # The true-up re-rates the schedule: accrual-to-date is brought in line
        # with the NEW schedule for the months already elapsed.
        elapsed = months_elapsed(home["closing_date"], CLOCK.today())
        true_up_amount = elapsed * new_monthly - reserve["accrued_to_date_cents"]
        reserve["expected_lifetime_accrual_cents"] = new_expected
        if elapsed > reserve["last_accrual_month_index"]:
            reserve["last_accrual_month_index"] = elapsed
        entry = post_entry(reserve, "TRUE_UP", true_up_amount, note=note)
    return success_object(serialize(entry), 201)
