"""HELOC endpoints: create, read, list, activate, close."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

from config import DRAW_PERIOD_DAYS
from db import store
from errors import (
    err_balance_not_zero,
    err_borrower_bankrupt,
    err_borrower_property_mismatch,
    err_cltv_exceeded,
    err_heloc_closed,
    err_invalid_state,
    err_no_senior_lien,
    err_occupancy_not_primary,
    err_rate_bound_invalid,
    err_validation_failed,
)
from middleware import require_auth
from response import list_success, success
from services.engine import (
    maybe_assess_early_closure_fee,
    stamp_create,
    stamp_update,
)
from services.serializers import heloc_view

from routes._helpers import (
    check_version,
    enforce_borrower_owns_heloc,
    get_borrower_or_404,
    get_heloc_or_404,
    get_int,
    get_json,
    get_property_or_404,
    get_string,
    get_bool,
    parse_pagination,
    parse_version,
    paginate,
    sort_by_created_at,
)

bp = Blueprint("helocs", __name__)


_HELOC_STATUSES = {"PENDING", "DRAW", "REPAY", "DEFAULT", "CLOSED"}


# ────────────────────────────────────────────────────────────────────────────
# POST /helocs — create in PENDING
# ────────────────────────────────────────────────────────────────────────────


@bp.post("/helocs")
@require_auth(["Originator", "PlatformAdmin"], endpoint_key="POST /helocs")
def create_heloc():
    body = get_json()
    borrower_id = get_string(body, "borrower_id", required=True)
    property_id = get_string(body, "property_id", required=True)
    credit_limit = get_int(body, "credit_limit_cents", required=True)
    margin = get_int(body, "margin_bps", required=True)
    periodic_cap = get_int(body, "periodic_cap_bps", required=True)
    lifetime_cap = get_int(body, "lifetime_cap_bps", required=True)
    lifetime_floor = get_int(body, "lifetime_floor_bps", required=True)
    repayment_term_years = get_int(body, "repayment_term_years", required=True)
    annual_fee = get_int(body, "annual_fee_cents", required=True)
    annual_fee_waived = get_bool(body, "annual_fee_waived_first_year", default=False)
    early_closure_fee = get_int(body, "early_closure_fee_cents", required=True)

    # Field-shape bounds (ERR_VALIDATION_FAILED, 400).
    if not (1_000_000 <= credit_limit <= 50_000_000):
        raise err_validation_failed("credit_limit_cents out of [1000000, 50000000].")
    if not (0 <= margin <= 1000):
        raise err_validation_failed("margin_bps out of [0, 1000].")
    if not (0 < periodic_cap <= 500):
        raise err_validation_failed("periodic_cap_bps out of (0, 500].")
    if not (10 <= repayment_term_years <= 20):
        raise err_validation_failed("repayment_term_years out of [10, 20].")
    if not (0 <= annual_fee <= 25_000):
        raise err_validation_failed("annual_fee_cents out of [0, 25000].")
    if not (0 <= early_closure_fee <= 50_000):
        raise err_validation_failed("early_closure_fee_cents out of [0, 50000].")
    if lifetime_floor < 0:
        raise err_validation_failed("lifetime_floor_bps must be >= 0.")
    if lifetime_cap > 2500:
        # PRD §2.12 + §3.2: "rate-configuration check that drives
        # ERR_RATE_BOUND_INVALID" — the absolute upper bound on
        # lifetime_cap_bps is a configured rate/cap bound.
        raise err_rate_bound_invalid("lifetime_cap_bps must be <= 2500.")

    with store.lock:
        # Priority 7 — body-FK existence.
        borrower = get_borrower_or_404(borrower_id)
        prop = get_property_or_404(property_id)

        # Priority 20 — occupancy.
        if prop["occupancy"] != "PRIMARY":
            raise err_occupancy_not_primary()

        # Priority 21 — at least one CURRENT senior lien.
        senior_total = 0
        has_current_lien = False
        for s in store.senior_liens.values():
            if s["property_id"] != property_id:
                continue
            if s["status"] == "CURRENT":
                has_current_lien = True
                senior_total += s["principal_balance_cents"]
        if not has_current_lien:
            raise err_no_senior_lien()

        # Priority 22 — borrower not bankrupt.
        if borrower["bankruptcy_flag"]:
            raise err_borrower_bankrupt()

        # Priority 23 — CLTV at origination (strict greater-than).
        if prop["appraised_value_cents"] <= senior_total + credit_limit:
            raise err_cltv_exceeded()

        # Priority 26 — borrower owns property.
        if prop["borrower_id"] != borrower_id:
            raise err_borrower_property_mismatch()

        # Priority 32 — rate-bound configuration check.
        # initial_rate_bps is not known until activation, but the
        # scaffold's validation explicitly says "lifetime_floor_bps <
        # initial_rate_bps" and "lifetime_cap_bps > initial_rate_bps
        # + periodic_cap_bps".  At create time we cannot fully validate
        # these because initial_rate_bps depends on the activation
        # prime_rate.  We DO validate the strictly-creation-time
        # ordering constraints we can: floor < cap, cap headroom > 0.
        if lifetime_floor >= lifetime_cap:
            raise err_rate_bound_invalid("lifetime_floor_bps must be < lifetime_cap_bps.")
        if lifetime_cap - lifetime_floor <= periodic_cap:
            # cap must allow room for at least one periodic step beyond floor.
            raise err_rate_bound_invalid(
                "lifetime_cap_bps must exceed lifetime_floor_bps + periodic_cap_bps."
            )

        h = {
            "borrower_id": borrower_id,
            "property_id": property_id,
            "credit_limit_cents": credit_limit,
            "margin_bps": margin,
            "periodic_cap_bps": periodic_cap,
            "lifetime_cap_bps": lifetime_cap,
            "lifetime_floor_bps": lifetime_floor,
            "initial_rate_bps": None,
            "current_rate_bps": None,
            "origination_date": None,
            "draw_period_end_date": None,
            "repayment_period_end_date": None,
            "repayment_term_years": repayment_term_years,
            "principal_balance_cents": 0,
            "available_credit_cents": credit_limit,
            "accrued_interest_cents": 0,
            "status": "PENDING",
            "delinquency_days": 0,
            "annual_fee_cents": annual_fee,
            "annual_fee_waived_first_year": annual_fee_waived,
            "early_closure_fee_cents": early_closure_fee,
            "defaulted_at": None,
            "default_trigger": None,
            "closed_at": None,
            # Internal bookkeeping (not in API surface).
            "last_cycle_end_date": None,
        }
        stamp_create(h)
        store.helocs[h["id"]] = h
    return success(heloc_view(h, include_computed=False), 201)


# ────────────────────────────────────────────────────────────────────────────
# GET /helocs/{id} and GET /helocs
# ────────────────────────────────────────────────────────────────────────────


@bp.get("/helocs/<hid>")
@require_auth(
    ["Originator", "Servicer", "Borrower", "PlatformAdmin"],
    endpoint_key="GET /helocs/{id}",
)
def get_heloc(hid: str):
    h = get_heloc_or_404(hid)
    enforce_borrower_owns_heloc(h)
    return success(heloc_view(h, include_computed=True), 200)


@bp.get("/helocs")
@require_auth(
    ["Originator", "Servicer", "PlatformAdmin"],
    endpoint_key="GET /helocs",
)
def list_helocs():
    borrower_filter = request.args.get("borrower_id")
    property_filter = request.args.get("property_id")
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in _HELOC_STATUSES:
        raise err_validation_failed(f"status={status_filter!r} is not a valid HELOC status.")

    limit, offset = parse_pagination()
    items = list(store.helocs.values())
    if borrower_filter:
        items = [h for h in items if h["borrower_id"] == borrower_filter]
    if property_filter:
        items = [h for h in items if h["property_id"] == property_filter]
    if status_filter:
        items = [h for h in items if h["status"] == status_filter]
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success(
        [heloc_view(h, include_computed=True) for h in page],
        limit,
        offset,
        total,
        200,
    )


# ────────────────────────────────────────────────────────────────────────────
# POST /helocs/{id}/activate
# ────────────────────────────────────────────────────────────────────────────


@bp.post("/helocs/<hid>/activate")
@require_auth(
    ["Originator", "PlatformAdmin"],
    endpoint_key="POST /helocs/{id}/activate",
)
def activate_heloc(hid: str):
    body = get_json()
    prime_rate = get_int(body, "prime_rate_bps", required=True)
    if not (0 <= prime_rate <= 3000):
        raise err_validation_failed("prime_rate_bps out of [0, 3000].")
    version = parse_version(body)

    with store.lock:
        h = get_heloc_or_404(hid)
        # Priority 10 — must be PENDING.
        if h["status"] != "PENDING":
            raise err_invalid_state("Heloc is not PENDING.")
        # Priority 33 — OCC.
        check_version(h, version)

        # Re-evaluate CLTV gate (PRD §3.2: a senior-lien balance change
        # since /helocs creation cannot slip past).
        prop = store.properties.get(h["property_id"])
        senior_total = sum(
            s["principal_balance_cents"]
            for s in store.senior_liens.values()
            if s["property_id"] == h["property_id"] and s["status"] == "CURRENT"
        )
        if prop is None or prop["appraised_value_cents"] <= senior_total + h["credit_limit_cents"]:
            raise err_cltv_exceeded()

        # Compute origination-date derivatives.
        now = store.now()
        initial_unclamped = prime_rate + h["margin_bps"]
        # Clamp initial rate to lifetime bounds.
        # PRD §3.2: "computes initial_rate_bps as the sum of the supplied
        # prime_rate_bps and the HELOC's margin_bps clamped to the closed
        # interval bounded below by lifetime_floor_bps and above by
        # lifetime_cap_bps".  Activation explicitly only re-evaluates the
        # CLTV gate (PRD §3.2); the rate-bound ordering gate is a
        # configuration check at create-time, not re-evaluated here.
        initial_rate = max(h["lifetime_floor_bps"], min(h["lifetime_cap_bps"], initial_unclamped))

        h["origination_date"] = now
        h["draw_period_end_date"] = now + timedelta(days=DRAW_PERIOD_DAYS)
        h["repayment_period_end_date"] = h["draw_period_end_date"] + timedelta(
            days=h["repayment_term_years"] * 365
        )
        h["initial_rate_bps"] = initial_rate
        h["current_rate_bps"] = initial_rate
        h["available_credit_cents"] = h["credit_limit_cents"]
        h["status"] = "DRAW"
        h["last_cycle_end_date"] = now  # anchors the billing-cycle sweep
        stamp_update(h)

    return success(heloc_view(h, include_computed=True), 200)


# ────────────────────────────────────────────────────────────────────────────
# POST /helocs/{id}/close
# ────────────────────────────────────────────────────────────────────────────


@bp.post("/helocs/<hid>/close")
@require_auth(
    ["Servicer", "Borrower", "PlatformAdmin"],
    endpoint_key="POST /helocs/{id}/close",
)
def close_heloc(hid: str):
    body = get_json()
    version = parse_version(body)

    with store.lock:
        h = get_heloc_or_404(hid)
        # Borrower scope: borrower may only close own HELOC.
        enforce_borrower_owns_heloc(h)
        # Priority 14 first (more specific): already closed.
        if h["status"] == "CLOSED":
            raise err_heloc_closed()
        # Priority 11: must be in {DRAW, REPAY, DEFAULT}.
        if h["status"] not in ("DRAW", "REPAY", "DEFAULT"):
            raise err_invalid_state("Close requires status in {DRAW, REPAY, DEFAULT}.")
        # Priority 33 — OCC.
        check_version(h, version)
        # Priority 31 — balance must be flat.
        if h["principal_balance_cents"] != 0 or h["accrued_interest_cents"] != 0:
            raise err_balance_not_zero()

        h["status"] = "CLOSED"
        h["closed_at"] = store.now()
        stamp_update(h)
        # Early-closure fee evaluation.
        maybe_assess_early_closure_fee(h)
    return success(heloc_view(h, include_computed=True), 200)
