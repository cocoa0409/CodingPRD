"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims in this PRD require the system to be driven through a
long onboarding + money-movement sequence before the behavior under test is
reachable. These helpers encapsulate those sequences so test bodies focus on
assertions.

All helpers use get_success_data() (lenient validator) internally, so setup
failures surface as clear "Setup failed" errors rather than confusing
assertions.

Identity threading: after a fixture creates a Seller, every ownership-gated
Seller call uses make_seller_headers(seller["id"]) — never the shared
TEST_USERS["seller_headers"] placeholder (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_seller_payload, create_payout_method_payload, create_fee_schedule_payload,
    create_order_payload, create_refund_payload, create_chargeback_payload,
    create_dispute_payload, create_payout_payload,
)
from .test_users import (
    TEST_USERS, make_seller_headers, make_reviewer_headers, make_finance_headers,
)
from .constants import ELECTRONICS_SCHEDULE, MEDIA_SCHEDULE


# Default operator ids. The KYC-approving reviewer and the releasing finance
# operator are deliberately distinct so the default release path does not trip
# segregation of duties (PRD §2.10).
DEFAULT_REVIEWER_ID = "reviewer-1"
DEFAULT_FINANCE_ID = "finance-2"

FINANCE = TEST_USERS["finance_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


# ─── Clock helpers (PRD §3.12) ──────────────────────────────────────────────

def set_clock(iso8601: str):
    """Set the simulated current UTC to a fixed instant."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso8601}, FINANCE))


def advance_clock(iso8601: str):
    """Advance the clock to an instant, running maturation + reserve-release sweeps."""
    return get_success_data(api_client.advance_clock({"to_iso8601": iso8601}, FINANCE))


# ─── Tier 0: primitives ─────────────────────────────────────────────────────

def create_fee_schedule(overrides=None):
    """Create a fee schedule (defaults to the canonical ELECTRONICS schedule)."""
    payload = dict(ELECTRONICS_SCHEDULE)
    if overrides:
        payload.update(overrides)
    return get_success_data(api_client.create_fee_schedule(payload, FINANCE))


def create_media_schedule():
    return get_success_data(api_client.create_fee_schedule(dict(MEDIA_SCHEDULE), FINANCE))


def create_seller(**overrides):
    """Register a fresh ONBOARDING seller (no onboarding progression)."""
    return get_success_data(
        api_client.create_seller(create_seller_payload(**overrides), REVIEWER)
    )


def create_order(seller_id, **overrides):
    """Create (and price) an order for a seller. PlatformFinance action."""
    return get_success_data(
        api_client.create_order(create_order_payload(seller_id, **overrides), FINANCE)
    )


# ─── Tier 1: State progression — onboard a seller to ACTIVE ─────────────────

def onboard_active_seller(reviewer_id=DEFAULT_REVIEWER_ID, schedule_overrides=None,
                          ensure_schedule=True, **seller_overrides):
    """Drive a seller all the way to account_status ACTIVE (PRD §3.1).

    Sequence: (optional) ELECTRONICS schedule → create seller → kyc submit →
    kyc decision APPROVE (by reviewer_id) → w9 submit → create payout method →
    verify payout method → w9 approve (final gate flips to ACTIVE).

    Returns (seller_dict_after_activation, payout_method_dict).
    The returned seller is re-fetched so all computed balances are current.
    """
    if ensure_schedule:
        create_fee_schedule(schedule_overrides)

    seller = create_seller(**seller_overrides)
    sid = seller["id"]
    seller_hdr = make_seller_headers(sid)
    reviewer_hdr = make_reviewer_headers(reviewer_id)

    get_success_data(api_client.submit_kyc(sid, seller_hdr))
    get_success_data(api_client.decide_kyc(sid, {"decision": "APPROVE"}, reviewer_hdr))
    get_success_data(api_client.submit_w9(sid, seller_hdr))

    pm = get_success_data(
        api_client.create_payout_method(create_payout_method_payload(sid), seller_hdr)
    )
    code = pm.get("micro_deposit_code")
    get_success_data(
        api_client.verify_payout_method(pm["id"], {"micro_deposit_code": code}, seller_hdr)
    )
    get_success_data(api_client.approve_w9(sid, reviewer_hdr))

    seller = get_success_data(api_client.get_seller(sid, FINANCE))
    return seller, pm


def seller_with_verified_method(**seller_overrides):
    """A fresh seller with one VERIFIED payout method but NOT yet ACTIVE
    (KYC/W-9 not progressed). For payout-method ownership/verification tests.

    Returns (seller_dict, payout_method_dict).
    """
    seller = create_seller(**seller_overrides)
    sid = seller["id"]
    seller_hdr = make_seller_headers(sid)
    pm = get_success_data(
        api_client.create_payout_method(create_payout_method_payload(sid), seller_hdr)
    )
    return seller, pm


# ─── Tier 2 / 4: matured balance + scheduled payout ─────────────────────────

def seller_with_matured_order(gross_amount_cents=10000, settle_iso="2026-01-01T00:00:00Z",
                              mature_iso="2026-01-10T00:00:00Z",
                              reviewer_id=DEFAULT_REVIEWER_ID, schedule_overrides=None):
    """ACTIVE seller + one order that has matured to AVAILABLE.

    set clock to settle_iso → onboard ACTIVE → create order → advance clock to
    mature_iso (>= settled_at + 7d) so the order matures.

    Returns (seller_dict, order_dict, payout_method_dict).
    """
    set_clock(settle_iso)
    seller, pm = onboard_active_seller(reviewer_id=reviewer_id,
                                       schedule_overrides=schedule_overrides)
    order = create_order(seller["id"], gross_amount_cents=gross_amount_cents)
    advance_clock(mature_iso)
    seller = get_success_data(api_client.get_seller(seller["id"], FINANCE))
    order = get_success_data(api_client.get_order(order["id"], FINANCE))
    return seller, order, pm


def schedule_payout(seller_id):
    """Schedule a payout (snapshots available balance; no disbursement yet)."""
    return get_success_data(
        api_client.create_payout(create_payout_payload(seller_id), FINANCE)
    )


def current_seller_version(seller_id):
    """Read the seller's current version (for the OCC expected_seller_version)."""
    seller = get_success_data(api_client.get_seller(seller_id, FINANCE))
    return seller["version"]


def seller_with_scheduled_payout(gross_amount_cents=10000, settle_iso="2026-01-01T00:00:00Z",
                                 mature_iso="2026-01-10T00:00:00Z",
                                 reviewer_id=DEFAULT_REVIEWER_ID, schedule_overrides=None):
    """ACTIVE seller + one matured order + a SCHEDULED payout.

    Returns (seller_dict, order_dict, payout_dict, payout_method_dict).
    """
    seller, order, pm = seller_with_matured_order(
        gross_amount_cents=gross_amount_cents, settle_iso=settle_iso,
        mature_iso=mature_iso, reviewer_id=reviewer_id,
        schedule_overrides=schedule_overrides,
    )
    payout = schedule_payout(seller["id"])
    return seller, order, payout, pm


def release_payout(payout_id, seller_id, finance_id=DEFAULT_FINANCE_ID):
    """Release a scheduled payout against the seller's current version.

    Uses a PlatformFinance operator distinct from the default reviewer so the
    segregation-of-duties gate is satisfied. Returns the released payout.
    """
    version = current_seller_version(seller_id)
    return get_success_data(
        api_client.release_payout(
            payout_id, {"expected_seller_version": version}, make_finance_headers(finance_id)
        )
    )


def seller_with_released_payout(gross_amount_cents=10000, settle_iso="2026-03-01T00:00:00Z",
                                mature_iso="2026-03-10T00:00:00Z",
                                finance_id=DEFAULT_FINANCE_ID):
    """ACTIVE STANDARD seller + matured order + a RELEASED payout (order PAID).

    Returns (seller_dict, order_dict, payout_dict).
    """
    seller, order, payout, _ = seller_with_scheduled_payout(
        gross_amount_cents=gross_amount_cents, settle_iso=settle_iso, mature_iso=mature_iso,
    )
    released = release_payout(payout["id"], seller["id"], finance_id=finance_id)
    seller = get_success_data(api_client.get_seller(seller["id"], FINANCE))
    order = get_success_data(api_client.get_order(order["id"], FINANCE))
    return seller, order, released


# ─── Tier 3: refund lifecycle ───────────────────────────────────────────────

def create_requested_refund(order_id, refund_amount_cents=4000, reason="DAMAGED"):
    """Create a REQUESTED refund against an order (PlatformFinance or Seller)."""
    return get_success_data(
        api_client.create_refund(
            create_refund_payload(order_id, refund_amount_cents=refund_amount_cents, reason=reason),
            FINANCE,
        )
    )


def apply_refund(refund_id):
    """Apply a REQUESTED refund (posts clawback, flips order)."""
    return get_success_data(api_client.apply_refund(refund_id, FINANCE))


def seller_order_with_applied_refund(order_gross=10000, refund_amount=4000,
                                     settle_iso="2026-02-01T00:00:00Z"):
    """Seller + order (PENDING) + one APPLIED refund (order REFUND_CLAWED).

    Returns (seller_dict, order_dict, refund_dict).
    """
    set_clock(settle_iso)
    create_fee_schedule()
    seller = create_seller()
    order = create_order(seller["id"], gross_amount_cents=order_gross)
    refund = create_requested_refund(order["id"], refund_amount_cents=refund_amount)
    refund = apply_refund(refund["id"])
    seller = get_success_data(api_client.get_seller(seller["id"], FINANCE))
    order = get_success_data(api_client.get_order(order["id"], FINANCE))
    return seller, order, refund


# ─── Tier 3: chargeback lifecycle ───────────────────────────────────────────

def create_chargeback(order_id):
    """Record an incoming chargeback (posts the flat fee immediately)."""
    return get_success_data(
        api_client.create_chargeback(create_chargeback_payload(order_id), FINANCE)
    )


def seller_order_with_chargeback_received(order_gross=10000,
                                          settle_iso="2026-02-01T00:00:00Z",
                                          mature_iso=None):
    """Seller + order + one chargeback in RECEIVED status.

    If mature_iso is given, the order is matured to AVAILABLE before the
    chargeback is recorded. Returns (seller_dict, order_dict, chargeback_dict).
    """
    set_clock(settle_iso)
    create_fee_schedule()
    seller = create_seller()
    order = create_order(seller["id"], gross_amount_cents=order_gross)
    if mature_iso:
        advance_clock(mature_iso)
    cb = create_chargeback(order["id"])
    seller = get_success_data(api_client.get_seller(seller["id"], FINANCE))
    order = get_success_data(api_client.get_order(order["id"], FINANCE))
    return seller, order, cb


# ─── Tier 3: dispute lifecycle ──────────────────────────────────────────────

def create_dispute(order_id, claim_type="ITEM_NOT_RECEIVED"):
    """File an A-to-Z claim (PlatformReviewer)."""
    return get_success_data(
        api_client.create_dispute(create_dispute_payload(order_id, claim_type=claim_type), REVIEWER)
    )


def dispute_in_under_review(order_gross=9000, settle_iso="2026-05-01T00:00:00Z"):
    """Seller + order + a Dispute driven FILED → UNDER_REVIEW.

    Returns (seller_dict, order_dict, dispute_dict).
    """
    set_clock(settle_iso)
    create_media_schedule()
    seller = create_seller()
    order = create_order(seller["id"], category="MEDIA", gross_amount_cents=order_gross)
    dispute = create_dispute(order["id"])
    dispute = get_success_data(api_client.open_review_dispute(dispute["id"], REVIEWER))
    return seller, order, dispute


def dispute_cycled(rounds, order_gross=9000, settle_iso="2026-05-01T00:00:00Z"):
    """Drive a dispute through `rounds` full open-review/respond cycles.

    After the call: response_round == rounds and status == SELLER_RESPONDED
    (the last action is a respond). Returns (seller_dict, order_dict, dispute_dict).
    """
    set_clock(settle_iso)
    create_media_schedule()
    seller = create_seller()
    sid = seller["id"]
    seller_hdr = make_seller_headers(sid)
    order = create_order(sid, category="MEDIA", gross_amount_cents=order_gross)
    dispute = create_dispute(order["id"])
    did = dispute["id"]
    for _ in range(rounds):
        get_success_data(api_client.open_review_dispute(did, REVIEWER))
        get_success_data(api_client.respond_dispute(did, seller_hdr))
    dispute = get_success_data(api_client.get_dispute(did, REVIEWER))
    return seller, order, dispute


# ─── Tier 5: tax-form lifecycle ─────────────────────────────────────────────

def create_tax_form(seller_id, tax_year=2026):
    from .factories import create_tax_form_payload
    return get_success_data(
        api_client.create_tax_form(create_tax_form_payload(seller_id, tax_year=tax_year), FINANCE)
    )


def seller_with_settled_gross(total_gross, num_orders, tax_year=2026,
                              settle_iso="2026-01-15T00:00:00Z",
                              mature_iso="2026-01-25T00:00:00Z"):
    """Seller with `num_orders` ELECTRONICS orders summing to total_gross,
    all matured to AVAILABLE in the tax year, plus a DRAFT tax form.

    The orders are split as evenly as possible; the final order absorbs the
    remainder so the sum is exactly total_gross.

    Returns (seller_dict, [order_dicts], tax_form_dict).
    """
    set_clock(settle_iso)
    create_fee_schedule()
    seller = create_seller()
    sid = seller["id"]
    per = total_gross // num_orders
    orders = []
    for i in range(num_orders):
        amt = per if i < num_orders - 1 else total_gross - per * (num_orders - 1)
        orders.append(create_order(sid, gross_amount_cents=amt))
    advance_clock(mature_iso)
    form = create_tax_form(sid, tax_year=tax_year)
    seller = get_success_data(api_client.get_seller(sid, FINANCE))
    orders = [get_success_data(api_client.get_order(o["id"], FINANCE)) for o in orders]
    return seller, orders, form
