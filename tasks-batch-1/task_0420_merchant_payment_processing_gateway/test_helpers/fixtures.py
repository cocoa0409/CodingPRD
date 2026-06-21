"""Composite setup helpers for the Merchant Payment Processing Gateway.

Each helper builds its preconditions from scratch using only PRD-declared endpoints,
because the server database is empty at the start of every test. Setup calls use the
lenient get_success_data() validator so a setup break surfaces as a clear "Setup failed".

Identity threading: a MerchantUser is entity-backed by its Merchant. Every ownership-gated
call here uses make_merchant_user_headers(merchant["id"]) — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_merchant_user_headers,
)
from . import factories as f


OPERATOR = TEST_USERS["platform_operator_headers"]
OFFICER = TEST_USERS["underwriting_officer_headers"]


# ---------------------------------------------------------------------------
# Clock control
# ---------------------------------------------------------------------------

def set_clock(iso8601: str):
    """Pin the logical clock to a fixed UTC instant."""
    return get_success_data(api_client.set_clock(f.set_clock_payload(iso8601), OPERATOR))


def advance_clock(iso8601: str):
    """Advance the clock (runs the authorization-expiry sweep)."""
    return get_success_data(api_client.advance_clock(f.set_clock_payload(iso8601), OPERATOR))


# ---------------------------------------------------------------------------
# Tier 0: fee plans
# ---------------------------------------------------------------------------

def create_flat_plan(**overrides) -> dict:
    return get_success_data(api_client.create_fee_plan(f.create_flat_fee_plan_payload(**overrides)))


def create_interchange_plus_plan(**overrides) -> dict:
    return get_success_data(
        api_client.create_fee_plan(f.create_interchange_plus_fee_plan_payload(**overrides))
    )


# ---------------------------------------------------------------------------
# Tier 1: merchant state progression
# ---------------------------------------------------------------------------

def register_merchant(fee_plan_id, **overrides) -> dict:
    """Register a PENDING_REVIEW merchant (anonymous). Auto-creates an OPEN risk review."""
    return get_success_data(
        api_client.create_merchant(f.create_merchant_payload(fee_plan_id, **overrides))
    )


def get_open_risk_review_id(merchant_id) -> str:
    """Resolve the auto-created OPEN risk review id via the list endpoint."""
    data = get_success_data(api_client.list_risk_reviews(merchant_id, OFFICER))
    reviews = data if isinstance(data, list) else data.get("data", data)
    return reviews[0]["id"]


def create_approved_merchant(fee_plan_id=None, assigned_risk_band="LOW",
                             merchant_overrides=None, plan_overrides=None):
    """Create FLAT plan (unless fee_plan_id supplied) + merchant + approve underwriting.

    Returns (merchant, review_id) where merchant is the APPROVED merchant after approval
    (so merchant["version"] is the version after approve — the one to pass to settle).
    """
    if fee_plan_id is None:
        plan = create_flat_plan(**(plan_overrides or {}))
        fee_plan_id = plan["id"]
    merchant = register_merchant(fee_plan_id, **(merchant_overrides or {}))
    review_id = get_open_risk_review_id(merchant["id"])
    approved = get_success_data(
        api_client.approve_risk_review(
            merchant["id"], review_id,
            f.approve_review_payload(assigned_risk_band=assigned_risk_band),
            OFFICER,
        )
    )
    return approved, review_id


# ---------------------------------------------------------------------------
# Tier 2: charges
# ---------------------------------------------------------------------------

def create_authorized_charge(merchant_id, auth_amount_cents=10000, card_last4="4242"):
    """Authorize a charge against an APPROVED merchant. Returns the AUTHORIZED charge."""
    headers = make_merchant_user_headers(merchant_id)
    return get_success_data(
        api_client.create_charge(
            merchant_id,
            f.create_charge_payload(auth_amount_cents=auth_amount_cents, card_last4=card_last4),
            headers,
        )
    )


def create_captured_charge(merchant_id, auth_amount_cents=10000, capture_amount_cents=None):
    """Authorize + capture a charge. Returns the CAPTURED charge.

    capture_amount_cents defaults to auth_amount_cents (full capture).
    """
    if capture_amount_cents is None:
        capture_amount_cents = auth_amount_cents
    charge = create_authorized_charge(merchant_id, auth_amount_cents=auth_amount_cents)
    headers = make_merchant_user_headers(merchant_id)
    return get_success_data(
        api_client.capture_charge(charge["id"], f.capture_payload(capture_amount_cents), headers)
    )


# ---------------------------------------------------------------------------
# Tier 3: settlement pipeline
# ---------------------------------------------------------------------------

def open_and_settle_batch(merchant_id, expected_merchant_version, business_date="2026-01-01"):
    """Open a batch (sweeps eligible captured/pending charges) then settle it.

    Returns (settled_batch, merchant_version_after_settle).
    """
    batch = get_success_data(
        api_client.create_settlement_batch(
            merchant_id, f.create_settlement_batch_payload(business_date), OPERATOR
        )
    )
    settled = get_success_data(
        api_client.settle_batch(
            batch["id"], f.settle_batch_payload(expected_merchant_version), OPERATOR
        )
    )
    merchant = get_success_data(api_client.get_merchant(merchant_id, OPERATOR))
    return settled, merchant["version"]


def fund_batch(batch_id):
    """Fund a SETTLED batch. Caller must have advanced the clock past the funding maturity."""
    return get_success_data(api_client.fund_batch(batch_id, {}, OPERATOR))


def setup_funded_merchant(assigned_risk_band="LOW", auth_amount_cents=10000,
                          business_date="2026-01-01", settle_date="2026-01-01",
                          fund_date="2026-01-03", plan_overrides=None,
                          merchant_overrides=None):
    """Full lifecycle through a FUNDED batch with a single capture.

    Sequence: set clock -> FLAT plan -> merchant -> approve(band) -> charge ->
    capture(full) -> open+settle batch -> advance clock -> fund.

    For a LOW/FLAT merchant capturing 10000 (fee 320, reserve 0), the resulting
    available_balance_cents is 9680. For MEDIUM (reserve 500bps -> 500) it is 9180
    with reserved_balance_cents 500.

    Returns dict with keys: merchant_id, charge, batch, plan_id, version_after_approve,
    version_after_settle, review_id.
    """
    set_clock(f"{settle_date}T00:00:00Z")
    plan = create_flat_plan(**(plan_overrides or {}))
    merchant, review_id = create_approved_merchant(
        fee_plan_id=plan["id"], assigned_risk_band=assigned_risk_band,
        merchant_overrides=merchant_overrides,
    )
    version_after_approve = merchant["version"]
    charge = create_captured_charge(merchant["id"], auth_amount_cents=auth_amount_cents)
    batch, version_after_settle = open_and_settle_batch(
        merchant["id"], version_after_approve, business_date=business_date
    )
    advance_clock(f"{fund_date}T00:00:00Z")
    funded_batch = fund_batch(batch["id"])
    return {
        "merchant_id": merchant["id"],
        "plan_id": plan["id"],
        "review_id": review_id,
        "charge": charge,
        "batch": funded_batch,
        "version_after_approve": version_after_approve,
        "version_after_settle": version_after_settle,
    }


def setup_settled_charge(assigned_risk_band="LOW", auth_amount_cents=10000,
                         business_date="2026-01-01", clock="2026-01-01",
                         plan_overrides=None):
    """Lifecycle through a SETTLED (but not yet funded) charge.

    Sequence: set clock -> FLAT plan -> merchant -> approve -> charge -> capture ->
    open+settle batch. Returns dict with merchant_id, charge (post-capture),
    batch (settled), version_after_settle, version_after_approve, plan_id, review_id.
    """
    set_clock(f"{clock}T00:00:00Z")
    plan = create_flat_plan(**(plan_overrides or {}))
    merchant, review_id = create_approved_merchant(
        fee_plan_id=plan["id"], assigned_risk_band=assigned_risk_band
    )
    version_after_approve = merchant["version"]
    charge = create_captured_charge(merchant["id"], auth_amount_cents=auth_amount_cents)
    batch, version_after_settle = open_and_settle_batch(
        merchant["id"], version_after_approve, business_date=business_date
    )
    return {
        "merchant_id": merchant["id"],
        "plan_id": plan["id"],
        "review_id": review_id,
        "charge": charge,
        "batch": batch,
        "version_after_approve": version_after_approve,
        "version_after_settle": version_after_settle,
    }


# ---------------------------------------------------------------------------
# Tier 4: disputes
# ---------------------------------------------------------------------------

def open_dispute(merchant_id, charge_id, disputed_amount_cents):
    """Open a dispute on a SETTLED charge. Returns the OPEN dispute."""
    headers = make_merchant_user_headers(merchant_id)
    return get_success_data(
        api_client.create_dispute(charge_id, f.create_dispute_payload(disputed_amount_cents), headers)
    )


def setup_open_dispute(disputed_amount_cents=10000, fund=True, **funded_overrides):
    """Full lifecycle to a SETTLED+(optionally FUNDED) charge with an OPEN dispute.

    Returns dict adding 'dispute' to the setup base. When fund=True, balances are funded
    first (so a LOW/FLAT 10000 merchant is at available 9680 before the dispute open).
    """
    if fund:
        base = setup_funded_merchant(**funded_overrides)
    else:
        base = setup_settled_charge(**funded_overrides)
    dispute = open_dispute(base["merchant_id"], base["charge"]["id"], disputed_amount_cents)
    base["dispute"] = dispute
    return base


def setup_acknowledged_dispute(disputed_amount_cents=10000, fund=True, **funded_overrides):
    """OPEN dispute -> acknowledge -> UNDER_REVIEW. Returns base dict with 'dispute'."""
    base = setup_open_dispute(disputed_amount_cents=disputed_amount_cents, fund=fund, **funded_overrides)
    headers = make_merchant_user_headers(base["merchant_id"])
    acked = get_success_data(api_client.acknowledge_dispute(base["dispute"]["id"], {}, headers))
    base["dispute"] = acked
    return base


def setup_represented_dispute(disputed_amount_cents=10000, fund=True, **funded_overrides):
    """OPEN -> acknowledge -> represent -> REPRESENTED (round 1).

    Returns base dict with 'dispute' in REPRESENTED state.
    """
    base = setup_acknowledged_dispute(
        disputed_amount_cents=disputed_amount_cents, fund=fund, **funded_overrides
    )
    headers = make_merchant_user_headers(base["merchant_id"])
    represented = get_success_data(api_client.represent_dispute(base["dispute"]["id"], {}, headers))
    base["dispute"] = represented
    return base


# ---------------------------------------------------------------------------
# Tier 5: pending refund
# ---------------------------------------------------------------------------

def create_pending_refund(merchant_id, charge_id, amount_cents):
    """Create a PENDING refund on a captured charge. Returns the refund."""
    headers = make_merchant_user_headers(merchant_id)
    return get_success_data(
        api_client.create_refund(charge_id, f.create_refund_payload(amount_cents), headers)
    )
