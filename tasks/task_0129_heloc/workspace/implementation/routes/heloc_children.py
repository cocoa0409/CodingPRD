"""Child-collection endpoints under /helocs/{id}/...

Includes the state-priority logic for state-precondition errors,
which differ per child endpoint (draws use ERR_HELOC_DEFAULTED and
ERR_DRAW_PERIOD_ENDED; rate-resets use ERR_HELOC_CLOSED / generic
ERR_INVALID_STATE; payments only reject CLOSED with ERR_HELOC_CLOSED).
"""
from __future__ import annotations

from flask import Blueprint

from db import store
from errors import (
    err_draw_period_ended,
    err_heloc_closed,
    err_heloc_defaulted,
    err_insufficient_credit,
    err_invalid_state,
    err_payment_below_minimum,
    err_validation_failed,
)
from middleware import require_auth
from response import list_success, success
from services.engine import (
    apply_payment_waterfall,
    compute_applied_rate_bps,
    minimum_payment_due_cents,
    stamp_ledger,
    stamp_update,
)
from services.serializers import (
    default_event_view,
    draw_view,
    fee_view,
    payment_view,
    rate_reset_view,
)

from routes._helpers import (
    check_version,
    enforce_borrower_owns_heloc,
    get_heloc_or_404,
    get_int,
    get_json,
    parse_pagination,
    parse_version,
    paginate,
    sort_by_created_at,
)

bp = Blueprint("heloc_children", __name__)


# ────────────────────────────────────────────────────────────────────────────
# Draws
# ────────────────────────────────────────────────────────────────────────────


@bp.post("/helocs/<hid>/draws")
@require_auth(
    ["Borrower", "PlatformAdmin"],
    endpoint_key="POST /helocs/{id}/draws",
)
def create_draw(hid: str):
    body = get_json()
    amount = get_int(body, "amount_cents", required=True)
    version = parse_version(body)
    if amount < 10_000:
        raise err_validation_failed("amount_cents must be >= 10000.")

    with store.lock:
        h = get_heloc_or_404(hid)
        enforce_borrower_owns_heloc(h)
        # State priority (PRD §2.10 in-group ordering): CLOSED first,
        # then DEFAULT, then REPAY, then everything-else-not-DRAW.
        status = h["status"]
        if status == "CLOSED":
            raise err_heloc_closed()
        if status == "DEFAULT":
            raise err_heloc_defaulted()
        if status == "REPAY":
            raise err_draw_period_ended()
        if status != "DRAW":
            raise err_invalid_state("Draw requires status==DRAW.")
        # Priority 33 — OCC.
        check_version(h, version)
        # Priority 30 — available credit.
        if amount > h["available_credit_cents"]:
            raise err_insufficient_credit()

        d = {
            "heloc_id": hid,
            "amount_cents": amount,
            "drawn_at": store.now(),
        }
        stamp_ledger(d)
        store.draws[d["id"]] = d
        # Adjust HELOC.
        h["principal_balance_cents"] += amount
        h["available_credit_cents"] -= amount
        stamp_update(h)
    return success(draw_view(d), 201)


@bp.get("/helocs/<hid>/draws")
@require_auth(
    ["Originator", "Servicer", "Borrower", "PlatformAdmin"],
    endpoint_key="GET /helocs/{id}/draws",
)
def list_draws(hid: str):
    h = get_heloc_or_404(hid)
    enforce_borrower_owns_heloc(h)
    limit, offset = parse_pagination()
    items = [d for d in store.draws.values() if d["heloc_id"] == hid]
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([draw_view(d) for d in page], limit, offset, total, 200)


# ────────────────────────────────────────────────────────────────────────────
# Payments
# ────────────────────────────────────────────────────────────────────────────


@bp.post("/helocs/<hid>/payments")
@require_auth(
    ["Borrower", "Servicer", "PlatformAdmin"],
    endpoint_key="POST /helocs/{id}/payments",
)
def create_payment(hid: str):
    body = get_json()
    amount = get_int(body, "amount_cents", required=True)
    version = parse_version(body)
    if amount <= 0:
        raise err_validation_failed("amount_cents must be > 0.")

    with store.lock:
        h = get_heloc_or_404(hid)
        enforce_borrower_owns_heloc(h)
        status = h["status"]
        if status == "CLOSED":
            raise err_heloc_closed()
        if status not in ("DRAW", "REPAY", "DEFAULT"):
            raise err_invalid_state("Payment requires status in {DRAW, REPAY, DEFAULT}.")
        check_version(h, version)
        # Priority 24 — minimum payment floor.
        minimum = minimum_payment_due_cents(h)
        if amount < minimum:
            raise err_payment_below_minimum(
                f"amount_cents={amount} < minimum_payment_due_cents={minimum}."
            )

        interest_part, principal_part = apply_payment_waterfall(h, amount)
        p = {
            "heloc_id": hid,
            "amount_cents": amount,
            "interest_component_cents": interest_part,
            "principal_component_cents": principal_part,
            "posted_at": store.now(),
        }
        stamp_ledger(p)
        store.payments[p["id"]] = p
        stamp_update(h)
    return success(payment_view(p), 201)


@bp.get("/helocs/<hid>/payments")
@require_auth(
    ["Originator", "Servicer", "Borrower", "PlatformAdmin"],
    endpoint_key="GET /helocs/{id}/payments",
)
def list_payments(hid: str):
    h = get_heloc_or_404(hid)
    enforce_borrower_owns_heloc(h)
    limit, offset = parse_pagination()
    items = [p for p in store.payments.values() if p["heloc_id"] == hid]
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([payment_view(p) for p in page], limit, offset, total, 200)


# ────────────────────────────────────────────────────────────────────────────
# Rate resets
# ────────────────────────────────────────────────────────────────────────────


@bp.post("/helocs/<hid>/rate-resets")
@require_auth(
    ["Servicer", "PlatformAdmin"],
    endpoint_key="POST /helocs/{id}/rate-resets",
)
def create_rate_reset(hid: str):
    body = get_json()
    prime_rate = get_int(body, "prime_rate_bps", required=True)
    version = parse_version(body)
    if not (0 <= prime_rate <= 3000):
        raise err_validation_failed("prime_rate_bps out of [0, 3000].")

    with store.lock:
        h = get_heloc_or_404(hid)
        status = h["status"]
        if status == "CLOSED":
            raise err_heloc_closed()
        # Priority 15 — RateReset allowed only in {DRAW, REPAY, DEFAULT}.
        if status not in ("DRAW", "REPAY", "DEFAULT"):
            raise err_invalid_state(
                "Rate reset requires status in {DRAW, REPAY, DEFAULT}."
            )
        check_version(h, version)
        requested, applied = compute_applied_rate_bps(
            prime_rate_bps=prime_rate,
            margin_bps=h["margin_bps"],
            current_rate_bps=h["current_rate_bps"],
            periodic_cap_bps=h["periodic_cap_bps"],
            lifetime_floor_bps=h["lifetime_floor_bps"],
            lifetime_cap_bps=h["lifetime_cap_bps"],
        )
        r = {
            "heloc_id": hid,
            "prime_rate_bps": prime_rate,
            "requested_rate_bps": requested,
            "applied_rate_bps": applied,
            "reset_at": store.now(),
        }
        stamp_ledger(r)
        store.rate_resets[r["id"]] = r
        h["current_rate_bps"] = applied
        stamp_update(h)
    return success(rate_reset_view(r), 201)


@bp.get("/helocs/<hid>/rate-resets")
@require_auth(
    ["Originator", "Servicer", "Borrower", "PlatformAdmin"],
    endpoint_key="GET /helocs/{id}/rate-resets",
)
def list_rate_resets(hid: str):
    h = get_heloc_or_404(hid)
    enforce_borrower_owns_heloc(h)
    limit, offset = parse_pagination()
    items = [r for r in store.rate_resets.values() if r["heloc_id"] == hid]
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([rate_reset_view(r) for r in page], limit, offset, total, 200)


# ────────────────────────────────────────────────────────────────────────────
# Fees and default events (read-only collections)
# ────────────────────────────────────────────────────────────────────────────


@bp.get("/helocs/<hid>/fees")
@require_auth(
    ["Originator", "Servicer", "Borrower", "PlatformAdmin"],
    endpoint_key="GET /helocs/{id}/fees",
)
def list_fees(hid: str):
    h = get_heloc_or_404(hid)
    enforce_borrower_owns_heloc(h)
    limit, offset = parse_pagination()
    items = [f for f in store.fees.values() if f["heloc_id"] == hid]
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([fee_view(f) for f in page], limit, offset, total, 200)


@bp.get("/helocs/<hid>/default-events")
@require_auth(
    ["Originator", "Servicer", "Borrower", "PlatformAdmin"],
    endpoint_key="GET /helocs/{id}/default-events",
)
def list_default_events(hid: str):
    h = get_heloc_or_404(hid)
    enforce_borrower_owns_heloc(h)
    limit, offset = parse_pagination()
    items = [e for e in store.default_events.values() if e["heloc_id"] == hid]
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([default_event_view(e) for e in page], limit, offset, total, 200)
