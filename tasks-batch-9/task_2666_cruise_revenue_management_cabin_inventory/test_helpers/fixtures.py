"""
Composite setup helpers.

The test server is restarted with an empty database before every test, so every
helper here builds the state it needs from scratch through the public API only.
Helpers return the full entity dicts (not just ids) so a caller can read the
version it needs for an optimistic-concurrency guard without a second GET.

Layering, coarse to fine:

* tier 1 - single-entity creators (``make_sailing``, ``make_guest``, ...)
* tier 2 - state progression shortcuts (``open_sailing``, ``pay_deposit``,
  ``confirm``, ``run_ops``)
* tier 3 - entity hierarchies (``simple_world``, ``make_upgrade_chain``,
  ``upgrade_bid_world``, ``guest_with_booking``)
* tier 4 - threshold / accumulation targeting (``fill_bookings``,
  ``confirmed_booking``, ``bid_ready_booking``, ``block_at_review_time``)
* tier 5 - terminal / finalisation shortcuts (``cancelled_booking``,
  ``settled_booking``, ``payment_events``)
"""

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import DEFAULT_CLOCK
from .test_users import (
    GROUP_SALES_AGENT,
    GROUP_SALES_AGENT_2,
    PORT_OPS_COORDINATOR,
    RESERVATION_AGENT,
    REVENUE_MANAGER,
    make_guest_headers,
)

# ==========================================================================
# tier 0 - clock control
# ==========================================================================


def set_clock(api, to_iso8601: str = DEFAULT_CLOCK) -> dict:
    """Pin the logical clock. Every fixture starts here so days-to-sail is stable."""
    return get_success_data(api.set_clock(to_iso8601, REVENUE_MANAGER))


# ==========================================================================
# tier 1 - single-entity creators
# ==========================================================================


def make_sailing(api, **overrides) -> dict:
    return get_success_data(
        api.create_sailing(f.sailing_payload(**overrides), REVENUE_MANAGER)
    )


def make_category(api, payload: Optional[Dict[str, Any]] = None, **overrides) -> dict:
    body = payload if payload is not None else f.cabin_category_payload()
    body = dict(body)
    body.update(overrides)
    return get_success_data(api.create_cabin_category(body, REVENUE_MANAGER))


def make_guarantee_category(api, **overrides) -> dict:
    return get_success_data(
        api.create_cabin_category(
            f.guarantee_category_payload(**overrides), REVENUE_MANAGER
        )
    )


def make_inventory(api, sailing_id: str, category_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_sailing_inventory(
            f.sailing_inventory_payload(sailing_id, category_id, **overrides),
            REVENUE_MANAGER,
        )
    )


def make_fare_rule(api, sailing_id: str, category_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_fare_rule(
            f.fare_rule_payload(sailing_id, category_id, **overrides), REVENUE_MANAGER
        )
    )


def make_guest(api, **overrides) -> dict:
    return get_success_data(api.create_guest(f.guest_payload(**overrides), RESERVATION_AGENT))


def make_booking(
    api, sailing_id: str, category_id: str, guest_id: str, **overrides
) -> dict:
    return get_success_data(
        api.create_booking(
            f.booking_payload(sailing_id, category_id, guest_id, **overrides),
            RESERVATION_AGENT,
        )
    )


def make_group_block(
    api, sailing_id: str, category_id: str, headers=GROUP_SALES_AGENT, **overrides
) -> dict:
    return get_success_data(
        api.create_group_block(
            f.group_block_payload(sailing_id, category_id, **overrides), headers
        )
    )


def make_promotion(api, sailing_id: str, expected_sailing_version: int, **overrides) -> dict:
    return get_success_data(
        api.create_promotion(
            f.promotion_payload(sailing_id, expected_sailing_version, **overrides),
            REVENUE_MANAGER,
        )
    )


def make_itinerary_change(api, sailing_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_itinerary_change(
            f.itinerary_change_payload(sailing_id, **overrides), PORT_OPS_COORDINATOR
        )
    )


# ==========================================================================
# tier 2 - state progression shortcuts
# ==========================================================================


def open_sailing(api, sailing_id: str) -> dict:
    return get_success_data(api.open_for_sale(sailing_id, REVENUE_MANAGER))


def suspend_sailing(api, sailing_id: str, reason: str = "PRICING_REVIEW") -> dict:
    return get_success_data(
        api.suspend_sales(sailing_id, {"reason": reason}, REVENUE_MANAGER)
    )


def resume_sailing(api, sailing_id: str) -> dict:
    return get_success_data(api.resume_sales(sailing_id, REVENUE_MANAGER))


def close_sailing(api, sailing_id: str) -> dict:
    return get_success_data(api.close_inventory(sailing_id, REVENUE_MANAGER))


def pay(api, booking_id: str, kind: str, amount_cents: int) -> dict:
    return get_success_data(
        api.post_payment(
            booking_id, f.payment_payload(kind, amount_cents), RESERVATION_AGENT
        )
    )


def pay_deposit(api, booking: dict) -> dict:
    """Post exactly the booking's ``deposit_due_cents`` as a DEPOSIT."""
    return pay(api, booking["id"], "DEPOSIT", booking["deposit_due_cents"])


def pay_balance(api, booking_id: str) -> dict:
    """Post exactly the booking's current ``balance_due_cents`` as a FINAL_PAYMENT."""
    fresh = read_booking(api, booking_id)
    return pay(api, booking_id, "FINAL_PAYMENT", fresh["balance_due_cents"])


def confirm(api, booking_id: str) -> dict:
    return get_success_data(api.confirm_booking(booking_id, RESERVATION_AGENT))


def activate_promotion(api, promotion_id: str) -> dict:
    return get_success_data(api.activate_promotion(promotion_id, REVENUE_MANAGER))


def publish_itinerary_change(api, change_id: str) -> dict:
    return get_success_data(
        api.publish_itinerary_change(change_id, PORT_OPS_COORDINATOR)
    )


def sign_definite(
    api, block_id: str, contract_reference: str = "MER-9001", headers=GROUP_SALES_AGENT_2
) -> dict:
    return get_success_data(
        api.confirm_definite(block_id, {"contract_reference": contract_reference}, headers)
    )


def run_ops(api, sailing_id: str) -> dict:
    return get_success_data(api.ops_run(sailing_id, REVENUE_MANAGER))


# ==========================================================================
# read-back helpers
# ==========================================================================


def read_sailing(api, sailing_id: str) -> dict:
    return get_success_data(api.get_sailing(sailing_id, REVENUE_MANAGER))


def read_inventory(api, inventory_id: str) -> dict:
    return get_success_data(api.get_sailing_inventory(inventory_id, REVENUE_MANAGER))


def read_fare_rule(api, fare_rule_id: str) -> dict:
    return get_success_data(api.get_fare_rule(fare_rule_id, REVENUE_MANAGER))


def read_booking(api, booking_id: str) -> dict:
    return get_success_data(api.get_booking(booking_id, REVENUE_MANAGER))


def read_guest(api, guest_id: str) -> dict:
    return get_success_data(api.get_guest(guest_id, REVENUE_MANAGER))


def read_block(api, block_id: str) -> dict:
    return get_success_data(api.get_group_block(block_id, REVENUE_MANAGER))


def read_promotion(api, promotion_id: str) -> dict:
    return get_success_data(api.get_promotion(promotion_id, REVENUE_MANAGER))


def read_bid(api, bid_id: str) -> dict:
    return get_success_data(api.get_upgrade_bid(bid_id, REVENUE_MANAGER))


def read_itinerary_change(api, change_id: str) -> dict:
    return get_success_data(api.get_itinerary_change(change_id, REVENUE_MANAGER))


def read_category(api, category_id: str) -> dict:
    return get_success_data(api.get_cabin_category(category_id, REVENUE_MANAGER))


# ==========================================================================
# tier 3 - entity hierarchies
# ==========================================================================


def simple_world(
    api,
    *,
    clock: str = DEFAULT_CLOCK,
    voyage_code: Optional[str] = None,
    embark_date: str = "2027-01-10T17:00:00Z",
    nights: int = 7,
    total_lower_berths: int = 200,
    final_payment_days_before: int = 75,
    deposit_due_days_after_booking: int = 7,
    category: Optional[dict] = None,
    category_overrides: Optional[Dict[str, Any]] = None,
    physical_cabins: int = 60,
    oversell_allowance: int = 4,
    fare_overrides: Optional[Dict[str, Any]] = None,
    open_now: bool = True,
) -> SimpleNamespace:
    """One sailing, one category, one allotment, one fare window, optionally open.

    This is the backbone the majority of scenarios need: a sellable voyage whose
    days-to-sail figure is deterministic because the clock is pinned first.
    """
    set_clock(api, clock)
    cat = category or make_guarantee_category(api, **(category_overrides or {}))
    sailing_kwargs: Dict[str, Any] = {
        "embark_date": embark_date,
        "nights": nights,
        "total_lower_berths": total_lower_berths,
        "final_payment_days_before": final_payment_days_before,
        "deposit_due_days_after_booking": deposit_due_days_after_booking,
    }
    if voyage_code is not None:
        sailing_kwargs["voyage_code"] = voyage_code
    sailing = make_sailing(api, **sailing_kwargs)
    inventory = make_inventory(
        api,
        sailing["id"],
        cat["id"],
        physical_cabins=physical_cabins,
        oversell_allowance=oversell_allowance,
    )
    fare_rule = make_fare_rule(api, sailing["id"], cat["id"], **(fare_overrides or {}))
    if open_now:
        sailing = open_sailing(api, sailing["id"])
    return SimpleNamespace(
        category=cat,
        sailing=sailing,
        inventory=inventory,
        fare_rule=fare_rule,
    )


def add_allotment_and_fare(
    api,
    world: SimpleNamespace,
    category: dict,
    *,
    physical_cabins: int = 20,
    oversell_allowance: int = 0,
    fare_overrides: Optional[Dict[str, Any]] = None,
) -> SimpleNamespace:
    """Attach a second category's allotment and fare window to an existing world."""
    inventory = make_inventory(
        api,
        world.sailing["id"],
        category["id"],
        physical_cabins=physical_cabins,
        oversell_allowance=oversell_allowance,
    )
    fare_rule = make_fare_rule(
        api, world.sailing["id"], category["id"], **(fare_overrides or {})
    )
    return SimpleNamespace(category=category, inventory=inventory, fare_rule=fare_rule)


def make_upgrade_chain(api) -> SimpleNamespace:
    """IA (guarantee, tier 1) -> OV (tier 2) -> BA (tier 3).

    The chain has to be created from the top down because
    ``upgrade_to_category_id`` must name a category that already exists and whose
    ``tier_rank`` is strictly greater.
    """
    ba = get_success_data(
        api.create_cabin_category(f.balcony_category_payload(), REVENUE_MANAGER)
    )
    ov = get_success_data(
        api.create_cabin_category(
            f.ocean_view_category_payload(upgrade_to_category_id=ba["id"]),
            REVENUE_MANAGER,
        )
    )
    ia = get_success_data(
        api.create_cabin_category(
            f.guarantee_category_payload(upgrade_to_category_id=ov["id"]),
            REVENUE_MANAGER,
        )
    )
    return SimpleNamespace(ia=ia, ov=ov, ba=ba)


def upgrade_bid_world(
    api,
    *,
    clock: str = DEFAULT_CLOCK,
    voyage_code: Optional[str] = None,
    ov_physical_cabins: int = 30,
    ia_physical_cabins: int = 60,
) -> SimpleNamespace:
    """A two-category world with the near and far fare windows every bid needs.

    The bid floor is re-derived at the bid instant from the fare rules covering
    the *current* days-to-sail figure, so both categories carry a 365..120 window
    and a 120..60 window.
    """
    set_clock(api, clock)
    ov = get_success_data(
        api.create_cabin_category(f.ocean_view_category_payload(), REVENUE_MANAGER)
    )
    ia = get_success_data(
        api.create_cabin_category(
            f.guarantee_category_payload(upgrade_to_category_id=ov["id"]), REVENUE_MANAGER
        )
    )
    sailing_kwargs: Dict[str, Any] = {}
    if voyage_code is not None:
        sailing_kwargs["voyage_code"] = voyage_code
    sailing = make_sailing(api, **sailing_kwargs)
    inv_ia = make_inventory(
        api,
        sailing["id"],
        ia["id"],
        physical_cabins=ia_physical_cabins,
        oversell_allowance=4,
    )
    inv_ov = make_inventory(
        api,
        sailing["id"],
        ov["id"],
        physical_cabins=ov_physical_cabins,
        oversell_allowance=0,
    )
    make_fare_rule(api, sailing["id"], ia["id"])
    make_fare_rule(
        api,
        sailing["id"],
        ia["id"],
        window_open_days_to_sail=120,
        window_close_days_to_sail=60,
        base_lower_berth_fare_cents=219995,
        third_berth_fare_cents=69997,
        fourth_berth_fare_cents=54997,
    )
    make_fare_rule(
        api,
        sailing["id"],
        ov["id"],
        base_lower_berth_fare_cents=289995,
        third_berth_fare_cents=79997,
        fourth_berth_fare_cents=64997,
    )
    make_fare_rule(
        api,
        sailing["id"],
        ov["id"],
        window_open_days_to_sail=120,
        window_close_days_to_sail=60,
        base_lower_berth_fare_cents=289995,
        third_berth_fare_cents=79997,
        fourth_berth_fare_cents=64997,
    )
    sailing = open_sailing(api, sailing["id"])
    return SimpleNamespace(
        ia=ia,
        ov=ov,
        sailing=sailing,
        inventory_ia=inv_ia,
        inventory_ov=inv_ov,
    )


def guest_with_booking(
    api, world: SimpleNamespace, *, guest_overrides=None, **booking_overrides
) -> SimpleNamespace:
    """A fresh guest plus one booking on the world's sailing and category."""
    guest = make_guest(api, **(guest_overrides or {}))
    booking = make_booking(
        api,
        world.sailing["id"],
        world.category["id"],
        guest["id"],
        **booking_overrides,
    )
    return SimpleNamespace(guest=guest, booking=booking)


def waitlisted_bookings(
    api, world: SimpleNamespace, count: int
) -> List[SimpleNamespace]:
    """``count`` waitlist-opted bookings created in order, oldest first."""
    rows = []
    for _ in range(count):
        rows.append(guest_with_booking(api, world, allow_waitlist=True))
    return rows


# ==========================================================================
# tier 4 - threshold / accumulation targeting
# ==========================================================================


def fill_bookings(
    api, world: SimpleNamespace, count: int, **booking_overrides
) -> List[SimpleNamespace]:
    """Create ``count`` bookings on the world, each with its own guest.

    Used to walk a sailing's occupancy_pct up to a posture threshold. Keep the
    world's ``total_lower_berths`` small so the walk stays short.
    """
    rows = []
    for _ in range(count):
        rows.append(guest_with_booking(api, world, **booking_overrides))
    return rows


def deposited_booking(
    api, world: SimpleNamespace, *, guest_overrides=None, **booking_overrides
) -> SimpleNamespace:
    """A booking whose deposit has been paid in full: payment_status DEPOSIT_PAID."""
    pair = guest_with_booking(
        api, world, guest_overrides=guest_overrides, **booking_overrides
    )
    pay_deposit(api, pair.booking)
    pair.booking = read_booking(api, pair.booking["id"])
    return pair


def confirmed_booking(
    api, world: SimpleNamespace, *, guest_overrides=None, **booking_overrides
) -> SimpleNamespace:
    """A CONFIRMED booking that has paid its deposit."""
    pair = deposited_booking(
        api, world, guest_overrides=guest_overrides, **booking_overrides
    )
    confirm(api, pair.booking["id"])
    pair.booking = read_booking(api, pair.booking["id"])
    return pair


def paid_in_full_booking(
    api, world: SimpleNamespace, *, guest_overrides=None, **booking_overrides
) -> SimpleNamespace:
    """A CONFIRMED booking whose balance has been cleared: payment_status PAID_IN_FULL."""
    pair = confirmed_booking(
        api, world, guest_overrides=guest_overrides, **booking_overrides
    )
    pay_balance(api, pair.booking["id"])
    pair.booking = read_booking(api, pair.booking["id"])
    return pair


def bid_ready_booking(
    api,
    world: SimpleNamespace,
    *,
    bid_clock: str = "2026-11-11T17:00:00Z",
    category_id: Optional[str] = None,
    guest_overrides=None,
    **booking_overrides,
) -> SimpleNamespace:
    """A confirmed booking, then the clock moved inside the bid window.

    A bid may only be submitted while days-to-sail is inside the bid window, so
    the booking is created far out (where the far fare window applies) and the
    clock is then advanced to ``bid_clock``.
    """
    guest = make_guest(api, **(guest_overrides or {}))
    booking = make_booking(
        api,
        world.sailing["id"],
        category_id or world.ia["id"],
        guest["id"],
        **booking_overrides,
    )
    pay_deposit(api, booking)
    confirm(api, booking["id"])
    set_clock(api, bid_clock)
    return SimpleNamespace(
        guest=guest, booking=read_booking(api, booking["id"])
    )


def submit_bid(
    api, booking: dict, guest_id: str, target_category_id: str, amount_per_guest_cents: int
) -> dict:
    """Submit an upgrade bid as the owning guest (the only role allowed to rebid)."""
    return get_success_data(
        api.submit_upgrade_bid(
            booking["id"],
            f.upgrade_bid_payload(target_category_id, amount_per_guest_cents),
            make_guest_headers(guest_id),
        )
    )


def block_at_review_time(
    api,
    world: SimpleNamespace,
    *,
    cabins_held: int = 3,
    review_date: str = "2026-09-01T00:00:00Z",
    definite: bool = False,
    clock_at_review: Optional[str] = None,
    **block_overrides,
) -> dict:
    """A group block whose review date has arrived, so /review is callable.

    The hold is created while the clock is still before ``review_date``, then the
    clock is advanced to (or past) it.
    """
    block = make_group_block(
        api,
        world.sailing["id"],
        world.category["id"],
        cabins_held=cabins_held,
        review_date=review_date,
        **block_overrides,
    )
    if definite:
        sign_definite(api, block["id"])
    set_clock(api, clock_at_review or review_date)
    return read_block(api, block["id"])


# ==========================================================================
# tier 5 - terminal / finalisation shortcuts
# ==========================================================================


def cancelled_booking(
    api,
    booking_id: str,
    *,
    reason: str = "GUEST_REQUEST",
) -> dict:
    """Cancel a booking, producing the provisional penalty quote."""
    get_success_data(
        api.cancel_booking(booking_id, {"reason": reason}, RESERVATION_AGENT)
    )
    return read_booking(api, booking_id)


def settled_booking(api, booking_id: str) -> dict:
    """Settle an already-cancelled booking, producing the final penalty and refund."""
    get_success_data(api.settle_cancellation(booking_id, REVENUE_MANAGER))
    return read_booking(api, booking_id)


def payment_events(api, booking_id: str) -> List[dict]:
    """The booking's payment ledger, oldest first."""
    body = api.list_payment_events(booking_id, RESERVATION_AGENT).json()
    return body["data"]
