"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures surface as clear
"Setup step failed" errors rather than confusing assertion failures.

Every helper builds its preconditions from scratch — the server database is empty
at the start of every test.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_impound_lot_payload,
    create_tow_provider_payload,
    create_lienholder_payload,
    create_tow_order_payload,
    create_notification_payload,
    create_inventory_item_payload,
    create_fee_waiver_payload,
    create_auction_payload,
)
from .test_users import (
    TEST_USERS,
    make_claimant_headers,
    make_tow_provider_headers,
)

OP = TEST_USERS["lot_operator_headers"]
POLICE = TEST_USERS["police_officer_headers"]
CLAIMANT = TEST_USERS["claimant_headers"]
AUCTION = TEST_USERS["auction_official_headers"]


# ─── Clock helper ─────────────────────────────────────────────────────────────
def set_clock(iso: str):
    """Set the server logical clock; LotOperator-driven (PRD §2.4)."""
    get_success_data(api_client.set_clock(iso, OP))


# ─── Tier 1/2: lots, providers, lienholders, basic orders ─────────────────────
def create_lot(**overrides):
    """Create an OPEN impound lot. Returns the lot dict (carries id + version)."""
    return get_success_data(api_client.create_impound_lot(create_impound_lot_payload(**overrides), OP))


def create_provider(**overrides):
    """Register an ACTIVE tow provider. Returns the provider dict."""
    return get_success_data(api_client.create_tow_provider(create_tow_provider_payload(**overrides), OP))


def create_lienholder(**overrides):
    """Create a lienholder reference record."""
    return get_success_data(api_client.create_lienholder(create_lienholder_payload(**overrides), OP))


def create_order(lot_id, **overrides):
    """Create a TOWED tow order on the given lot."""
    return get_success_data(api_client.create_tow_order(create_tow_order_payload(lot_id, **overrides), OP))


def add_inventory(order_id, **overrides):
    """Document one inventory item (precondition for store)."""
    return get_success_data(api_client.create_inventory_item(order_id, create_inventory_item_payload(**overrides), OP))


def create_stored_order(lot_overrides=None, order_overrides=None, with_inventory=True):
    """Lot + order + one inventory item + store. Returns (lot, order)."""
    lot = create_lot(**(lot_overrides or {}))
    order = create_order(lot["id"], **(order_overrides or {}))
    if with_inventory:
        add_inventory(order["id"])
    get_success_data(api_client.store_order(order["id"], OP))
    order = get_success_data(api_client.get_tow_order(order["id"], OP))
    return lot, order


def create_stored_lien_order(lot_overrides=None, order_overrides=None):
    """Lot + lienholder + lien order + inventory + store. Returns (lot, lienholder, order)."""
    lot = create_lot(**(lot_overrides or {}))
    lh = create_lienholder()
    extra = dict(order_overrides or {})
    extra.setdefault("tow_type", "PRIVATE")
    extra["lienholder_id"] = lh["id"]
    order = create_order(lot["id"], **extra)
    add_inventory(order["id"])
    get_success_data(api_client.store_order(order["id"], OP))
    order = get_success_data(api_client.get_tow_order(order["id"], OP))
    return lot, lh, order


# ─── Tier 3: notice + statutory eligibility chains ────────────────────────────
def create_delivered_notice(order_id, method="CERTIFIED_MAIL", recipient_type="OWNER"):
    """Create a notice, send it, and confirm delivery (starts the grace clock).
    Returns the DELIVERY_CONFIRMED notification dict."""
    n = get_success_data(api_client.create_notification(
        order_id, create_notification_payload(method=method, recipient_type=recipient_type), OP))
    get_success_data(api_client.send_notification(order_id, n["id"], OP))
    get_success_data(api_client.confirm_delivery(order_id, n["id"], OP))
    return get_success_data(api_client.get_notification(order_id, n["id"], OP))


def setup_auction_eligible_order(intake_iso, eligible_iso,
                                 lot_overrides=None, order_overrides=None,
                                 with_lien=False):
    """Full chain to an AUCTION_ELIGIBLE order:
       set clock(intake) -> lot -> order -> inventory -> store
       -> notice send+confirm -> set clock(eligible past statutory+grace)
       -> mark-auction-eligible.
    Returns (lot, order) — order refreshed after mark-eligible.
    """
    set_clock(intake_iso)
    lot = create_lot(**(lot_overrides or {}))
    lh = None
    extra = dict(order_overrides or {})
    if with_lien:
        lh = create_lienholder()
        extra.setdefault("tow_type", "PRIVATE")
        extra["lienholder_id"] = lh["id"]
    else:
        extra.setdefault("tow_type", "ABANDONED")
    order = create_order(lot["id"], **extra)
    add_inventory(order["id"])
    get_success_data(api_client.store_order(order["id"], OP))
    create_delivered_notice(order["id"])
    set_clock(eligible_iso)
    get_success_data(api_client.mark_auction_eligible(order["id"], OP))
    order = get_success_data(api_client.get_tow_order(order["id"], OP))
    if with_lien:
        return lot, lh, order
    return lot, order


def setup_open_auction_with_swept_order(intake_iso, eligible_iso,
                                        window_start, window_end,
                                        lot_overrides=None, order_overrides=None,
                                        with_lien=False):
    """AUCTION_ELIGIBLE order + scheduled+opened auction + sweep.
    Returns (lot, order, auction) or (lot, lienholder, order, auction) when with_lien.
    """
    result = setup_auction_eligible_order(
        intake_iso, eligible_iso, lot_overrides, order_overrides, with_lien)
    if with_lien:
        lot, lh, order = result
    else:
        lot, order = result
    auction = get_success_data(api_client.create_auction(
        create_auction_payload(lot["id"], window_start=window_start, window_end=window_end), AUCTION))
    get_success_data(api_client.open_auction(auction["id"], AUCTION))
    get_success_data(api_client.sweep_order(auction["id"], {"tow_order_id": order["id"]}, AUCTION))
    order = get_success_data(api_client.get_tow_order(order["id"], OP))
    auction = get_success_data(api_client.get_auction(auction["id"], AUCTION))
    if with_lien:
        return lot, lh, order, auction
    return lot, order, auction


# ─── Tier 3: rotation dispatch chains ─────────────────────────────────────────
def setup_lot_with_providers(num_providers=1, lot_overrides=None):
    """Lot (max_provider_concurrent_offers default high) + N providers ranked 1..N.
    Returns (lot, [providers])."""
    lo = dict(lot_overrides or {})
    lo.setdefault("max_provider_concurrent_offers", 5)
    lot = create_lot(**lo)
    providers = []
    for rank in range(1, num_providers + 1):
        providers.append(create_provider(company_name=f"P{rank}", rotation_rank=rank))
    return lot, providers


def dispatch_offer(lot_id, expected_lot_version, **payload_extra):
    """Dispatch one rotation call. Returns (assignment, new_lot_version)."""
    payload = {"expected_lot_version": expected_lot_version}
    payload.update(payload_extra)
    ra = get_success_data(api_client.dispatch_rotation(lot_id, payload, OP))
    lot = get_success_data(api_client.get_impound_lot(lot_id, OP))
    return ra, lot["version"]


def setup_offered_assignment(num_providers=1, lot_overrides=None, offer_ttl_minutes=None):
    """Lot + N providers + one dispatched OFFERED assignment to rank-1.
    Returns (lot, providers, assignment, lot_version_after_dispatch)."""
    lot, providers = setup_lot_with_providers(num_providers, lot_overrides)
    extra = {}
    if offer_ttl_minutes is not None:
        extra["offer_ttl_minutes"] = offer_ttl_minutes
    ra, v_after = dispatch_offer(lot["id"], lot["version"], **extra)
    return lot, providers, ra, v_after


# ─── Tier 3: fee-waiver chains ────────────────────────────────────────────────
def file_waiver(order_id, filer_user_id="claimant-filer", **overrides):
    """File a fee waiver as a Claimant with an explicit filer id. Returns the waiver."""
    return get_success_data(api_client.create_fee_waiver(
        order_id, create_fee_waiver_payload(**overrides), make_claimant_headers(filer_user_id)))


def file_and_review_waiver(order_id, filer_user_id="claimant-filer", **overrides):
    """File a waiver then move it to UNDER_REVIEW. Returns the waiver dict."""
    w = file_waiver(order_id, filer_user_id, **overrides)
    get_success_data(api_client.start_review(order_id, w["id"], OP))
    return w


# ─── Tier 3: release chain ────────────────────────────────────────────────────
def pay(order_id, amount_cents, user_id="claimant-payer"):
    """Record a payment toward the order balance as a Claimant."""
    return get_success_data(api_client.record_payment(
        order_id, {"amount_cents": amount_cents}, make_claimant_headers(user_id)))


def take_order_to_released(intake_iso, advance_iso, net_due_cents,
                           lot_overrides=None, order_overrides=None):
    """Stored order -> pay net_due -> authorize-release -> release-record (RELEASED).
    Caller supplies the known net_due_cents to pay. Returns (lot, order)."""
    set_clock(intake_iso)
    lot, order = create_stored_order(lot_overrides=lot_overrides, order_overrides=order_overrides)
    set_clock(advance_iso)
    pay(order["id"], net_due_cents)
    get_success_data(api_client.authorize_release(order["id"], OP))
    get_success_data(api_client.create_release_record(
        order["id"], {"amount_paid_cents": 0, "released_to_name": "Owner"}, OP))
    order = get_success_data(api_client.get_tow_order(order["id"], OP))
    return lot, order
