"""
Payload factories.

Each factory returns a minimal valid payload for one create/action endpoint and
accepts keyword overrides. Money is always an ``int`` of cents and fractions are
always ``float`` — never strings — so a fixture never hands the API a typed
field it would have to coerce.
"""

import itertools
from typing import Any, Dict

# Monotonic counters keep uniqueness constraints satisfied when a single test
# creates several rows of the same collection. The server is restarted before
# every test, so restarting these counters per process is harmless.
_voyage_seq = itertools.count(1)
_category_seq = itertools.count(1)
_email_seq = itertools.count(1)
_promo_seq = itertools.count(1)
_tier_seq = itertools.count(1)


def _apply(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Merge overrides; an override of ``None`` keeps an explicit null."""
    payload.update(overrides)
    return payload


def sailing_payload(**overrides) -> Dict[str, Any]:
    """A 7-night AURORA voyage embarking 2027-01-10, 162 days out at the default clock."""
    n = next(_voyage_seq)
    return _apply(
        {
            "ship_code": "AURORA",
            "voyage_code": f"AUR-27{n:02d}",
            "embark_date": "2027-01-10T17:00:00Z",
            "nights": 7,
            "total_lower_berths": 200,
            "final_payment_days_before": 75,
            "deposit_due_days_after_booking": 7,
        },
        overrides,
    )


def cabin_category_payload(**overrides) -> Dict[str, Any]:
    """A four-berth category; caller normally overrides code/tier_rank/is_guarantee."""
    n = next(_category_seq)
    t = next(_tier_seq)
    return _apply(
        {
            "code": f"C{n:02d}",
            "tier_rank": t,
            "max_occupancy": 4,
            "onboard_spend_lower_per_night_cents": 9000,
            "onboard_spend_upper_per_night_cents": 6000,
        },
        overrides,
    )


def guarantee_category_payload(**overrides) -> Dict[str, Any]:
    """The IA guarantee category of the canonical world: tier 1, oversell-eligible."""
    base = cabin_category_payload(
        code="IA",
        tier_rank=1,
        is_guarantee=True,
        onboard_spend_lower_per_night_cents=9000,
        onboard_spend_upper_per_night_cents=6000,
    )
    return _apply(base, overrides)


def ocean_view_category_payload(**overrides) -> Dict[str, Any]:
    """The OV category: tier 2, the upgrade target of IA, richer onboard indices."""
    base = cabin_category_payload(
        code="OV",
        tier_rank=2,
        onboard_spend_lower_per_night_cents=11000,
        onboard_spend_upper_per_night_cents=7000,
    )
    return _apply(base, overrides)


def balcony_category_payload(**overrides) -> Dict[str, Any]:
    """The BA category: tier 3, the top of the canonical upgrade chain."""
    base = cabin_category_payload(
        code="BA",
        tier_rank=3,
        onboard_spend_lower_per_night_cents=13000,
        onboard_spend_upper_per_night_cents=8000,
    )
    return _apply(base, overrides)


def sailing_inventory_payload(
    sailing_id: str, cabin_category_id: str, **overrides
) -> Dict[str, Any]:
    """The canonical IA allotment: 60 physical cabins with an appetite of 4."""
    return _apply(
        {
            "sailing_id": sailing_id,
            "cabin_category_id": cabin_category_id,
            "physical_cabins": 60,
            "oversell_allowance": 4,
        },
        overrides,
    )


def fare_rule_payload(
    sailing_id: str, cabin_category_id: str, **overrides
) -> Dict[str, Any]:
    """The canonical far-out window [120, 365) at 189995 per lower berth."""
    return _apply(
        {
            "sailing_id": sailing_id,
            "cabin_category_id": cabin_category_id,
            "window_open_days_to_sail": 365,
            "window_close_days_to_sail": 120,
            "base_lower_berth_fare_cents": 189995,
            "third_berth_fare_cents": 64997,
            "fourth_berth_fare_cents": 49997,
        },
        overrides,
    )


def promotion_payload(
    sailing_id: str, expected_sailing_version: int, **overrides
) -> Dict[str, Any]:
    """A 10 percent GENERAL campaign live across the default clock instant."""
    n = next(_promo_seq)
    return _apply(
        {
            "sailing_id": sailing_id,
            "code": f"PROMO{n:03d}",
            "audience": "GENERAL",
            "discount_pct": 0.10,
            "starts_on": "2026-08-01T00:00:00Z",
            "ends_on": "2026-08-20T00:00:00Z",
            "max_redemptions": 5,
            "expected_sailing_version": expected_sailing_version,
        },
        overrides,
    )


def group_block_payload(
    sailing_id: str, cabin_category_id: str, **overrides
) -> Dict[str, Any]:
    """A three-cabin tentative hold reviewable from 2026-09-01."""
    return _apply(
        {
            "sailing_id": sailing_id,
            "cabin_category_id": cabin_category_id,
            "agency_name": "Meridian Travel",
            "cabins_held": 3,
            "review_date": "2026-09-01T00:00:00Z",
            "release_policy": "ATTRITION_50",
        },
        overrides,
    )


def guest_payload(**overrides) -> Dict[str, Any]:
    """A first-time guest: prior_sailings_count 0, so loyalty_tier NONE."""
    n = next(_email_seq)
    return _apply(
        {
            "full_name": f"Guest {n:03d}",
            "email": f"guest{n:03d}@example.com",
            "prior_sailings_count": 0,
        },
        overrides,
    )


def booking_payload(
    sailing_id: str, cabin_category_id: str, guest_id: str, **overrides
) -> Dict[str, Any]:
    """Two adults in a lower-berth pair, no upper berths, no promotion."""
    return _apply(
        {
            "sailing_id": sailing_id,
            "cabin_category_id": cabin_category_id,
            "guest_id": guest_id,
            "occupancy_adults": 2,
        },
        overrides,
    )


def payment_payload(kind: str, amount_cents: int, **overrides) -> Dict[str, Any]:
    return _apply({"kind": kind, "amount_cents": int(amount_cents)}, overrides)


def upgrade_bid_payload(
    target_cabin_category_id: str, bid_amount_per_guest_cents: int, **overrides
) -> Dict[str, Any]:
    return _apply(
        {
            "target_cabin_category_id": target_cabin_category_id,
            "bid_amount_per_guest_cents": int(bid_amount_per_guest_cents),
        },
        overrides,
    )


def itinerary_change_payload(sailing_id: str, **overrides) -> Dict[str, Any]:
    """A cancelled port compensated with onboard credit only."""
    return _apply(
        {
            "sailing_id": sailing_id,
            "kind": "PORT_CANCELLED",
            "affected_port_code": "GRC",
            "compensation_policy": "OBC_ONLY",
        },
        overrides,
    )
