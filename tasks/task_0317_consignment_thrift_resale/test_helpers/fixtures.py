"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so a broken setup step
surfaces as a clear "Setup failed" rather than a confusing assertion deep inside
a test. Every helper builds its preconditions from scratch — the server database
is empty at the start of every test.

The canonical chain to reach an ON_FLOOR item is:
  set clock -> create consignor -> create schedule -> create agreement
  -> open intake batch -> add item -> grade ACCEPT -> (auth if required) -> list

All roles are opaque; the grader's X-User-ID is pinned via make_intake_grader_headers
so separation-of-duties scenarios can drive a distinct authenticator id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_consignor_payload,
    create_markdown_schedule_payload,
    create_agreement_payload,
    create_intake_batch_payload,
    create_item_payload,
    grade_accept_payload,
    create_authentication_review_payload,
    create_sale_payload,
    create_settlement_payload,
    finalize_settlement_payload,
)
from .test_users import (
    TEST_USERS,
    make_intake_grader_headers,
    make_authenticator_headers,
)

ADMIN = TEST_USERS["store_admin_headers"]
GRADER = TEST_USERS["intake_grader_headers"]
AUTH = TEST_USERS["authenticator_headers"]
CASHIER = TEST_USERS["cashier_clerk_headers"]
SETTLER = TEST_USERS["settlement_manager_headers"]

# Single-tier age-0 no-discount schedule (the default used by most setups).
SINGLE_TIER = [{"min_age_days": 0, "discount_pct": 0.0}]


# ─── Tier 0: Clock control ───────────────────────────────────────────────────

def set_clock(iso8601: str):
    """Set the server's logical UTC clock (StoreAdmin-only)."""
    get_success_data(api_client.set_clock(iso8601, ADMIN))


# ─── Tier 1: Primitive creators ──────────────────────────────────────────────

def create_consignor(full_name="Test Consignor", email="consignor@example.com"):
    return get_success_data(api_client.create_consignor(
        create_consignor_payload(full_name=full_name, email=email), ADMIN))


def create_schedule(name="Standard Schedule", tiers=None, base_floor_pct=0.30):
    if tiers is None:
        tiers = [dict(t) for t in SINGLE_TIER]
    return get_success_data(api_client.create_markdown_schedule(
        create_markdown_schedule_payload(name=name, tiers=tiers, base_floor_pct=base_floor_pct),
        ADMIN))


def create_agreement(consignor_id, schedule_id, split_pct=0.50, **terms):
    return get_success_data(api_client.create_agreement(
        create_agreement_payload(consignor_id, schedule_id, split_pct=split_pct, **terms),
        ADMIN))


def open_batch(agreement_id):
    return get_success_data(api_client.create_intake_batch(
        create_intake_batch_payload(agreement_id), GRADER))


def add_item(batch_id, title="Test Garment", requires_authentication=False):
    return get_success_data(api_client.create_item(
        create_item_payload(batch_id, title=title,
                            requires_authentication=requires_authentication),
        GRADER))


# ─── Tier 2: Agreement setup ─────────────────────────────────────────────────

def setup_agreement(split_pct=0.50, split_basis=None, payout_method=None,
                    unsold_disposition=None, return_window_days=None,
                    base_floor_pct=0.30, tiers=None,
                    consignor_email="consignor@example.com",
                    consignor_name="Test Consignor"):
    """Consignor + schedule + agreement. Returns (consignor, schedule, agreement)."""
    consignor = create_consignor(full_name=consignor_name, email=consignor_email)
    schedule = create_schedule(tiers=tiers, base_floor_pct=base_floor_pct)
    terms = {}
    if split_basis is not None:
        terms["split_basis"] = split_basis
    if payout_method is not None:
        terms["payout_method"] = payout_method
    if unsold_disposition is not None:
        terms["unsold_disposition"] = unsold_disposition
    if return_window_days is not None:
        terms["return_window_days"] = return_window_days
    agreement = create_agreement(consignor["id"], schedule["id"], split_pct=split_pct, **terms)
    return consignor, schedule, agreement


# ─── Tier 3: Item lifecycle shortcuts ────────────────────────────────────────

def setup_graded_item(agreement_id, list_price_cents=8000, title="Test Garment",
                      requires_authentication=False, grader_user_id=None):
    """Open batch + add item + grade ACCEPT. Returns (batch, item-after-grade).
    Pins the grading operator's X-User-ID when grader_user_id is given (for SoD)."""
    headers = make_intake_grader_headers(grader_user_id) if grader_user_id else GRADER
    batch = get_success_data(api_client.create_intake_batch(
        create_intake_batch_payload(agreement_id), headers))
    item = get_success_data(api_client.create_item(
        create_item_payload(batch["id"], title=title,
                            requires_authentication=requires_authentication),
        headers))
    graded = get_success_data(api_client.grade_item(
        item["id"],
        grade_accept_payload(list_price_cents, item["version"]),
        headers))
    return batch, graded


def setup_on_floor_item(split_pct=0.50, split_basis=None, payout_method=None,
                        unsold_disposition=None, return_window_days=None,
                        base_floor_pct=0.30, tiers=None,
                        list_price_cents=8000, title="Test Garment",
                        consignor_email="onfloor@example.com",
                        consignor_name="On Floor"):
    """Full canonical chain to a single ON_FLOOR item (no authentication).
    Returns (consignor, schedule, agreement, batch, item).
    The item is listed at the current clock instant, so floor_date == now."""
    consignor, schedule, agreement = setup_agreement(
        split_pct=split_pct, split_basis=split_basis, payout_method=payout_method,
        unsold_disposition=unsold_disposition, return_window_days=return_window_days,
        base_floor_pct=base_floor_pct, tiers=tiers,
        consignor_email=consignor_email, consignor_name=consignor_name)
    batch, item = setup_graded_item(agreement["id"], list_price_cents=list_price_cents,
                                    title=title)
    listed = get_success_data(api_client.list_item(item["id"], GRADER))
    return consignor, schedule, agreement, batch, listed


def setup_sold_item(split_pct=0.50, split_basis=None, payout_method=None,
                    list_price_cents=8000, base_floor_pct=0.30, tiers=None,
                    payment_method="CARD", sold_price_cents=None,
                    consignor_email="sold@example.com", consignor_name="Sold Seller"):
    """ON_FLOOR item then rung in a single-line sale.
    Returns (consignor, agreement, item, sale)."""
    consignor, schedule, agreement, batch, item = setup_on_floor_item(
        split_pct=split_pct, split_basis=split_basis, payout_method=payout_method,
        list_price_cents=list_price_cents, base_floor_pct=base_floor_pct, tiers=tiers,
        consignor_email=consignor_email, consignor_name=consignor_name)
    line = {"item_id": item["id"]}
    if sold_price_cents is not None:
        line["sold_price_cents"] = sold_price_cents
    sale = get_success_data(api_client.create_sale(
        create_sale_payload(lines=[line], payment_method=payment_method), CASHIER))
    return consignor, agreement, item, sale


# ─── Tier 4: Authentication setup ────────────────────────────────────────────

def setup_item_with_open_review(list_price_cents=5000,
                                grader_user_id="U-GRADER",
                                authenticator_user_id="U-AUTH",
                                consignor_email="auth@example.com",
                                consignor_name="Auth Seller"):
    """Auth-required item graded ACCEPTED by grader_user_id, with an IN_REVIEW
    review opened by a DIFFERENT authenticator_user_id (satisfies separation of
    duties). Returns (agreement, item, review)."""
    _, _, agreement = setup_agreement(consignor_email=consignor_email,
                                      consignor_name=consignor_name)
    _, item = setup_graded_item(agreement["id"], list_price_cents=list_price_cents,
                                title="Branded item", requires_authentication=True,
                                grader_user_id=grader_user_id)
    review = get_success_data(api_client.create_authentication_review(
        create_authentication_review_payload(item["id"]),
        make_authenticator_headers(authenticator_user_id)))
    return agreement, item, review


def setup_graded_auth_item(list_price_cents=9000, grader_user_id="U-GRADER",
                           consignor_email="gradedauth@example.com",
                           consignor_name="Graded Auth"):
    """Auth-required item graded ACCEPTED (authentication_status PENDING_AUTH), no
    review yet. Returns (agreement, item). The grader id is pinned for SoD tests."""
    _, _, agreement = setup_agreement(consignor_email=consignor_email,
                                      consignor_name=consignor_name)
    _, item = setup_graded_item(agreement["id"], list_price_cents=list_price_cents,
                                title="Branded item", requires_authentication=True,
                                grader_user_id=grader_user_id)
    return agreement, item


# ─── Tier 5: Settlement setup ────────────────────────────────────────────────

def open_settlement(business_date):
    return get_success_data(api_client.create_settlement(
        create_settlement_payload(business_date), SETTLER))


def finalize_settlement(settlement):
    return get_success_data(api_client.finalize_settlement(
        settlement["id"],
        finalize_settlement_payload(settlement["version"]),
        SETTLER))


def setup_finalized_sale(list_price_cents=8000, business_date="2026-06-05",
                         clock_iso="2026-06-05T10:00:00Z", payout_method="CASH",
                         split_basis="GROSS", split_pct=0.50,
                         consignor_email="finalized@example.com",
                         consignor_name="Finalized Seller"):
    """Sell one item on `business_date`, open a settlement for that date, and
    finalize it so the sale carries a settlement_id.
    Returns (consignor, item, sale, settlement)."""
    set_clock(clock_iso)
    consignor, agreement, item, sale = setup_sold_item(
        split_pct=split_pct, split_basis=split_basis, payout_method=payout_method,
        list_price_cents=list_price_cents,
        consignor_email=consignor_email, consignor_name=consignor_name)
    settlement = open_settlement(business_date)
    finalized = finalize_settlement(settlement)
    return consignor, item, sale, finalized
