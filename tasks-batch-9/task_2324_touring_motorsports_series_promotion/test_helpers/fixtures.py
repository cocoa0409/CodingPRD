"""Composite setup helpers.

Every helper drives the public API only — it never touches storage directly — so
the states it produces are exactly the states a real client could reach. Setup
steps are read with the lenient success reader, so a broken setup fails loudly
with the offending HTTP status rather than masquerading as a test failure.

Each helper accepts flat keyword overrides and routes them to the right request
body, so a caller can nudge one figure (a price, an allotment, a provisioning
level, a budget, a rental base, a market code, a floor type, a bay count) without
rebuilding the chain. Unknown keywords raise, so a typo cannot pass silently.

Every helper returns a dictionary carrying the ids it created and the raw rows it
fetched, so callers can read a version, a posture or a money field without an
extra round trip.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from .api_client import ApiClient
from .test_users import (
    make_finance_approver_headers,
    make_finance_preparer_headers,
    make_safety_author_headers,
    make_safety_certifier_headers,
    make_safety_inspector_headers,
    make_series_promoter_headers,
    make_ticketing_manager_headers,
)

# ---------------------------------------------------------------------------
# Keyword routing
# ---------------------------------------------------------------------------

#: Flat keyword -> (payload group, field name inside that payload).
_KEYWORD_ROUTES: Dict[str, Tuple[str, str]] = {
    # Season
    "season_name": ("season", "name"),
    "year": ("season", "year"),
    "season_start_date": ("season", "season_start_date"),
    "season_end_date": ("season", "season_end_date"),
    "total_marketing_budget_cents": ("season", "total_marketing_budget_cents"),
    "market_rotation_cooldown_days": ("season", "market_rotation_cooldown_days"),
    # Venue
    "venue_name": ("venue", "name"),
    "market_code": ("venue", "market_code"),
    "city": ("venue", "city"),
    "state_code": ("venue", "state_code"),
    "seat_capacity": ("venue", "seat_capacity"),
    "floor_type": ("venue", "floor_type"),
    "catch_fence_max_height_ft": ("venue", "catch_fence_max_height_ft"),
    "medical_bay_count": ("venue", "medical_bay_count"),
    "load_in_hours_required": ("venue", "load_in_hours_required"),
    "staging_bay_count": ("venue", "staging_bay_count"),
    "turnaround_hours": ("venue", "turnaround_hours"),
    # Booking
    "tour_date": ("booking", "tour_date"),
    "rental_base_cents": ("booking", "rental_base_cents"),
    "revenue_share_pct": ("booking", "revenue_share_pct"),
    "per_ticket_facility_fee_cents": ("booking", "per_ticket_facility_fee_cents"),
    "load_in_start_utc": ("booking", "load_in_start_utc"),
    "tear_down_end_utc": ("booking", "tear_down_end_utc"),
    # Stop logistics
    "doors_open_utc": ("logistics", "doors_open_utc"),
    "show_start_utc": ("logistics", "show_start_utc"),
    "show_window_minutes": ("logistics", "show_window_minutes"),
    "pit_party_price_cents": ("logistics", "pit_party_price_cents"),
    "pit_party_capacity": ("logistics", "pit_party_capacity"),
    "preceding_stop_id": ("logistics", "preceding_stop_id"),
    "haul_distance_miles": ("logistics", "haul_distance_miles"),
    # Run order
    "segment_type": ("segment", "segment_type"),
    "segment_title": ("segment", "title"),
    "run_order_position": ("segment", "run_order_position"),
    "duration_minutes": ("segment", "duration_minutes"),
    "featured_vehicle_entry_id": ("segment", "featured_vehicle_entry_id"),
    # Primary ticket tier
    "tier_code": ("tier", "tier_code"),
    "price_cents": ("tier", "price_cents"),
    "allotment": ("tier", "allotment"),
    "on_sale_start_utc": ("tier", "on_sale_start_utc"),
    "on_sale_end_utc": ("tier", "on_sale_end_utc"),
    "group_min_qty": ("tier", "group_min_qty"),
    "group_discount_pct": ("tier", "group_discount_pct"),
    # Secondary ticket tier
    "second_tier_code": ("second_tier", "tier_code"),
    "second_tier_price_cents": ("second_tier", "price_cents"),
    "second_tier_allotment": ("second_tier", "allotment"),
    # Safety plan provisioning
    "barrier_linear_feet": ("plan", "barrier_linear_feet"),
    "catch_fence_height_ft": ("plan", "catch_fence_height_ft"),
    "medical_als_staff_count": ("plan", "medical_als_staff_count"),
    "medical_bls_staff_count": ("plan", "medical_bls_staff_count"),
    "ambulance_count": ("plan", "ambulance_count"),
    "emergency_access_lanes": ("plan", "emergency_access_lanes"),
    # Marketing
    "channel": ("marketing", "channel"),
    "amount_cents": ("marketing", "amount_cents"),
    # Competitor
    "team_name": ("competitor", "team_name"),
    "driver_name": ("competitor", "driver_name"),
    "home_market_code": ("competitor", "home_market_code"),
    "vehicle_class": ("competitor", "vehicle_class"),
    # Vehicle entry
    "vehicle_number": ("entry", "vehicle_number"),
    "vehicle_weight_lbs": ("entry", "vehicle_weight_lbs"),
    "entry_haul_distance_miles": ("entry", "haul_distance_miles"),
    "scheduled_arrival_utc": ("entry", "scheduled_arrival_utc"),
    # Ticket order
    "qty": ("order", "qty"),
    "purchaser_name": ("order", "purchaser_name"),
    "purchaser_email": ("order", "purchaser_email"),
    "is_group": ("order", "is_group"),
    "pit_party_addon_qty": ("order", "pit_party_addon_qty"),
    # Sponsor
    "company_name": ("sponsor", "company_name"),
    "sponsor_category": ("sponsor", "category"),
    "contact_email": ("sponsor", "contact_email"),
    "exclusive_category": ("sponsor", "exclusive_category"),
    # Sponsorship activation
    "fee_cents": ("activation", "fee_cents"),
    "vehicle_branding_slots": ("activation", "vehicle_branding_slots"),
    "signage_units": ("activation", "signage_units"),
    "hospitality_seat_count": ("activation", "hospitality_seat_count"),
}

#: Keywords consumed by the helpers themselves rather than by a request body.
_CONTROL_KEYWORDS = {
    "check_in_clock_utc",
    "include_second_tier",
    "with_entry",
    "with_activation",
    "fulfill_activation",
}


def _route(kwargs: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Split flat keyword overrides into per-payload groups.

    Raises ``ValueError`` for any keyword that no request body accepts, so a
    misspelled override cannot be silently discarded.
    """
    groups: Dict[str, Dict[str, Any]] = {}
    control: Dict[str, Any] = {}
    for key, value in kwargs.items():
        if key in _CONTROL_KEYWORDS:
            control[key] = value
            continue
        if key not in _KEYWORD_ROUTES:
            raise ValueError(f"Unknown setup override: {key}")
        group, field = _KEYWORD_ROUTES[key]
        groups.setdefault(group, {})[field] = value
    groups["control"] = control
    return groups


def _group(groups: Dict[str, Dict[str, Any]], name: str) -> Dict[str, Any]:
    return dict(groups.get(name, {}))


def _control(groups: Dict[str, Dict[str, Any]], name: str, default: Any) -> Any:
    return groups.get("control", {}).get(name, default)


def _for_groups(
    kwargs: Dict[str, Any], groups: Set[str], controls: Set[str] = frozenset()
) -> Dict[str, Any]:
    """Keep only the keywords belonging to the named payload groups."""
    return {
        key: value
        for key, value in kwargs.items()
        if key in controls
        or (key not in _CONTROL_KEYWORDS and _KEYWORD_ROUTES[key][0] in groups)
    }


# ---------------------------------------------------------------------------
# Small read helpers
# ---------------------------------------------------------------------------


def set_clock(
    api: ApiClient, to_iso8601: str, headers: Optional[Dict[str, str]] = None
) -> str:
    """Move the logical clock and return the instant it now reads."""
    data = get_success_data(
        api.set_clock(to_iso8601, headers=headers or make_series_promoter_headers())
    )
    return data["current_utc"]


def reset_clock(api: ApiClient, headers: Optional[Dict[str, str]] = None) -> str:
    """Return the logical clock to the instant it reads before it is ever set."""
    return set_clock(api, C.CLOCK_DEFAULT_UTC, headers=headers)


def fetch_season(
    api: ApiClient, season_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Read a season row."""
    return get_success_data(
        api.get_season(season_id, headers=headers or make_series_promoter_headers())
    )


def fetch_season_version(
    api: ApiClient, season_id: str, headers: Optional[Dict[str, str]] = None
) -> int:
    """Read the season's current version, for the marketing concurrency token."""
    return fetch_season(api, season_id, headers=headers)["version"]


def fetch_tier(
    api: ApiClient, tier_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Read a ticket tier row."""
    return get_success_data(
        api.get_ticket_tier(tier_id, headers=headers or make_ticketing_manager_headers())
    )


def fetch_tier_version(
    api: ApiClient, tier_id: str, headers: Optional[Dict[str, str]] = None
) -> int:
    """Read the tier's current version, for the order concurrency token."""
    return fetch_tier(api, tier_id, headers=headers)["version"]


def fetch_stop(
    api: ApiClient, stop_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Read a tour stop row."""
    return get_success_data(
        api.get_tour_stop(stop_id, headers=headers or make_series_promoter_headers())
    )


def fetch_stop_for_booking(
    api: ApiClient, booking_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Read the tour stop that a confirmed booking synthesized."""
    rows = get_success_data(
        api.list_tour_stops(
            {"venue_booking_id": booking_id},
            headers=headers or make_series_promoter_headers(),
        )
    )
    assert rows, f"no tour stop was synthesized for booking {booking_id}"
    return rows[0]


def fetch_safety_plan(
    api: ApiClient, plan_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Read a safety plan row."""
    return get_success_data(
        api.get_safety_plan(plan_id, headers=headers or make_safety_author_headers())
    )


def fetch_entry(
    api: ApiClient, entry_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Read a vehicle entry row."""
    return get_success_data(
        api.get_vehicle_entry(entry_id, headers=headers or make_series_promoter_headers())
    )


def fetch_settlement(
    api: ApiClient, settlement_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Read a settlement row."""
    return get_success_data(
        api.get_settlement(settlement_id, headers=headers or make_finance_preparer_headers())
    )


# ---------------------------------------------------------------------------
# Tier 1 - standalone roots
# ---------------------------------------------------------------------------


def create_season(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Create a season.

    Accepts ``season_name``, ``year``, ``season_start_date``, ``season_end_date``,
    ``total_marketing_budget_cents`` and ``market_rotation_cooldown_days``.

    Returns ``season`` and ``season_id``.
    """
    groups = _route(kwargs)
    row = get_success_data(
        api.create_season(
            F.make_season_payload(**_group(groups, "season")),
            headers=make_series_promoter_headers(),
        )
    )
    return {"season": row, "season_id": row["id"]}


def create_venue(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Register a building.

    Accepts ``venue_name``, ``market_code``, ``city``, ``state_code``,
    ``seat_capacity``, ``floor_type``, ``catch_fence_max_height_ft``,
    ``medical_bay_count``, ``load_in_hours_required``, ``staging_bay_count`` and
    ``turnaround_hours``.

    Returns ``venue`` and ``venue_id``.
    """
    groups = _route(kwargs)
    row = get_success_data(
        api.create_venue(
            F.make_venue_payload(**_group(groups, "venue")),
            headers=make_series_promoter_headers(),
        )
    )
    return {"venue": row, "venue_id": row["id"]}


def create_competitor(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Register a competing team.

    Accepts ``team_name``, ``driver_name``, ``home_market_code`` and
    ``vehicle_class``.

    Returns ``competitor`` and ``competitor_id``.
    """
    groups = _route(kwargs)
    row = get_success_data(
        api.create_competitor(
            F.make_competitor_payload(**_group(groups, "competitor")),
            headers=make_series_promoter_headers(),
        )
    )
    return {"competitor": row, "competitor_id": row["id"]}


def create_sponsor(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Register a sponsor.

    Accepts ``company_name``, ``sponsor_category``, ``contact_email`` and
    ``exclusive_category``.

    Returns ``sponsor`` and ``sponsor_id``.
    """
    groups = _route(kwargs)
    row = get_success_data(
        api.create_sponsor(
            F.make_sponsor_payload(**_group(groups, "sponsor")),
            headers=make_series_promoter_headers(),
        )
    )
    return {"sponsor": row, "sponsor_id": row["id"]}


# ---------------------------------------------------------------------------
# Tier 2 - bookings and the stop they synthesize
# ---------------------------------------------------------------------------


def proposed_booking(
    api: ApiClient,
    season_id: Optional[str] = None,
    venue_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A season, a building and a booking sitting at the opening negotiation state.

    Reuses ``season_id`` and ``venue_id`` when supplied, otherwise creates them.

    Returns ``season``, ``season_id``, ``venue``, ``venue_id``, ``booking`` and
    ``booking_id``.
    """
    groups = _route(kwargs)
    state: Dict[str, Any] = {}

    if season_id is None:
        state.update(create_season(api, **_prefixed(groups, "season")))
        season_id = state["season_id"]
    else:
        state["season_id"] = season_id
        state["season"] = fetch_season(api, season_id)

    if venue_id is None:
        venue_payload = F.make_venue_payload(**_group(groups, "venue"))
        venue_row = get_success_data(
            api.create_venue(venue_payload, headers=make_series_promoter_headers())
        )
        state["venue"] = venue_row
        state["venue_id"] = venue_row["id"]
        venue_id = venue_row["id"]
    else:
        state["venue_id"] = venue_id
        state["venue"] = get_success_data(
            api.get_venue(venue_id, headers=make_series_promoter_headers())
        )

    booking_row = get_success_data(
        api.create_venue_booking(
            F.make_venue_booking_payload(
                season_id, venue_id, **_group(groups, "booking")
            ),
            headers=make_series_promoter_headers(),
        )
    )
    state["booking"] = booking_row
    state["booking_id"] = booking_row["id"]
    return state


def _prefixed(groups: Dict[str, Dict[str, Any]], group: str) -> Dict[str, Any]:
    """Re-expand one routed group back into its flat keyword form."""
    reverse = {
        route[1]: key for key, route in _KEYWORD_ROUTES.items() if route[0] == group
    }
    return {reverse[field]: value for field, value in _group(groups, group).items()}


def confirmed_booking(
    api: ApiClient,
    season_id: Optional[str] = None,
    venue_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A booking accepted by the promoter, together with the stop it synthesized.

    Accepts every season, venue and booking keyword.

    Returns the keys of :func:`proposed_booking` plus ``stop`` and ``stop_id``.
    """
    state = proposed_booking(api, season_id=season_id, venue_id=venue_id, **kwargs)
    state["booking"] = get_success_data(
        api.accept_venue_booking(
            state["booking_id"], headers=make_series_promoter_headers()
        )
    )
    stop = fetch_stop_for_booking(api, state["booking_id"])
    state["stop"] = stop
    state["stop_id"] = stop["id"]
    state["season"] = fetch_season(api, state["season_id"])
    return state


def countered_booking(
    api: ApiClient,
    season_id: Optional[str] = None,
    venue_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A booking the building has countered, so the promoter may revise it.

    The counter is filed by the manager of the booked venue, whose identity is
    that venue's id.

    Returns the keys of :func:`proposed_booking`, with ``booking`` refreshed.
    """
    from .test_users import make_venue_manager_headers

    state = proposed_booking(api, season_id=season_id, venue_id=venue_id, **kwargs)
    state["booking"] = get_success_data(
        api.counter_venue_booking(
            state["booking_id"],
            F.make_counter_terms_payload(),
            headers=make_venue_manager_headers(state["venue_id"]),
        )
    )
    return state


# ---------------------------------------------------------------------------
# Tier 3 - show timing on the stop
# ---------------------------------------------------------------------------


def stop_with_show_timing(
    api: ApiClient,
    season_id: Optional[str] = None,
    venue_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A confirmed stop whose doors, show start, window and pit party are set.

    Accepts every season, venue, booking and logistics keyword — including
    ``doors_open_utc``, ``show_start_utc``, ``show_window_minutes``,
    ``pit_party_price_cents``, ``pit_party_capacity``, ``preceding_stop_id`` and
    ``haul_distance_miles``.

    Returns the keys of :func:`confirmed_booking`, with ``stop`` refreshed.
    """
    groups = _route(kwargs)
    state = confirmed_booking(
        api,
        season_id=season_id,
        venue_id=venue_id,
        **_for_groups(kwargs, {"season", "venue", "booking"}),
    )
    state["stop"] = get_success_data(
        api.update_tour_stop_logistics(
            state["stop_id"],
            F.make_logistics_payload(**_group(groups, "logistics")),
            headers=make_series_promoter_headers(),
        )
    )
    return state


# ---------------------------------------------------------------------------
# Children of a stop
# ---------------------------------------------------------------------------


def create_show_segment(api: ApiClient, stop_id: str, **kwargs: Any) -> Dict[str, Any]:
    """Insert one run-order segment on the stop.

    Accepts ``segment_type``, ``segment_title``, ``run_order_position``,
    ``duration_minutes`` and ``featured_vehicle_entry_id``.

    Returns ``segment`` and ``segment_id``.
    """
    groups = _route(kwargs)
    row = get_success_data(
        api.create_show_segment(
            stop_id,
            F.make_show_segment_payload(**_group(groups, "segment")),
            headers=make_series_promoter_headers(),
        )
    )
    return {"segment": row, "segment_id": row["id"]}


def create_ticket_tier(api: ApiClient, stop_id: str, **kwargs: Any) -> Dict[str, Any]:
    """Add one pricing tier to the stop.

    Accepts ``tier_code``, ``price_cents``, ``allotment``, ``on_sale_start_utc``,
    ``on_sale_end_utc``, ``group_min_qty`` and ``group_discount_pct``.

    Returns ``tier`` and ``tier_id``.
    """
    groups = _route(kwargs)
    row = get_success_data(
        api.create_ticket_tier(
            stop_id,
            F.make_ticket_tier_payload(**_group(groups, "tier")),
            headers=make_ticketing_manager_headers(),
        )
    )
    return {"tier": row, "tier_id": row["id"]}


def create_vehicle_entry(
    api: ApiClient,
    stop_id: str,
    competitor_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Enter one vehicle in the stop, which also assigns its staging bay.

    Accepts every competitor keyword when a competitor has to be created, plus
    ``vehicle_number``, ``vehicle_weight_lbs``, ``entry_haul_distance_miles`` and
    ``scheduled_arrival_utc``.

    Returns ``competitor``, ``competitor_id``, ``entry`` and ``entry_id``.
    """
    groups = _route(kwargs)
    state: Dict[str, Any] = {}
    if competitor_id is None:
        state.update(create_competitor(api, **_prefixed(groups, "competitor")))
        competitor_id = state["competitor_id"]
    else:
        state["competitor_id"] = competitor_id
    row = get_success_data(
        api.create_vehicle_entry(
            F.make_vehicle_entry_payload(
                competitor_id, stop_id, **_group(groups, "entry")
            ),
            headers=headers or make_series_promoter_headers(),
        )
    )
    state["entry"] = row
    state["entry_id"] = row["id"]
    return state


def commit_marketing_allocation(
    api: ApiClient, stop_id: str, season_id: str, **kwargs: Any
) -> Dict[str, Any]:
    """Commit local marketing spend on one channel of the stop.

    The season's current version is read immediately before the write, because
    the commit carries it as its concurrency token.

    Accepts ``channel`` and ``amount_cents``.

    Returns ``allocation``, ``allocation_id`` and the refreshed ``season``.
    """
    groups = _route(kwargs)
    version = fetch_season_version(api, season_id)
    row = get_success_data(
        api.create_marketing_allocation(
            stop_id,
            F.make_marketing_allocation_payload(version, **_group(groups, "marketing")),
            headers=make_series_promoter_headers(),
        )
    )
    return {
        "allocation": row,
        "allocation_id": row["id"],
        "season": fetch_season(api, season_id),
    }


def place_ticket_order(
    api: ApiClient, stop_id: str, tier_id: str, **kwargs: Any
) -> Dict[str, Any]:
    """Place one order against the tier, leaving it pending.

    The tier's current version is read immediately before the write, because the
    order carries it as its concurrency token.

    Accepts ``qty``, ``purchaser_name``, ``purchaser_email``, ``is_group`` and
    ``pit_party_addon_qty``.

    Returns ``order``, ``order_id`` and the refreshed ``tier``.
    """
    groups = _route(kwargs)
    version = fetch_tier_version(api, tier_id)
    row = get_success_data(
        api.create_ticket_order(
            F.make_ticket_order_payload(
                stop_id, tier_id, version, **_group(groups, "order")
            ),
            headers=make_ticketing_manager_headers(),
        )
    )
    return {"order": row, "order_id": row["id"], "tier": fetch_tier(api, tier_id)}


def place_paid_ticket_order(
    api: ApiClient, stop_id: str, tier_id: str, **kwargs: Any
) -> Dict[str, Any]:
    """Place one order against the tier and settle it.

    Accepts the same keywords as :func:`place_ticket_order`.

    Returns ``order``, ``order_id`` and the refreshed ``tier``.
    """
    state = place_ticket_order(api, stop_id, tier_id, **kwargs)
    state["order"] = get_success_data(
        api.pay_ticket_order(state["order_id"], headers=make_ticketing_manager_headers())
    )
    state["tier"] = fetch_tier(api, tier_id)
    return state


# ---------------------------------------------------------------------------
# Tier 4 - the safety envelope
# ---------------------------------------------------------------------------


def draft_safety_plan(api: ApiClient, stop_id: str, **kwargs: Any) -> Dict[str, Any]:
    """Author the stop's safety plan and leave it in draft.

    Accepts ``barrier_linear_feet``, ``catch_fence_height_ft``,
    ``medical_als_staff_count``, ``medical_bls_staff_count``, ``ambulance_count``
    and ``emergency_access_lanes``.

    Returns ``plan`` and ``plan_id``.
    """
    groups = _route(kwargs)
    row = get_success_data(
        api.create_safety_plan(
            stop_id,
            F.make_safety_plan_payload(**_group(groups, "plan")),
            headers=make_safety_author_headers(),
        )
    )
    return {"plan": row, "plan_id": row["id"]}


def submitted_safety_plan(api: ApiClient, stop_id: str, **kwargs: Any) -> Dict[str, Any]:
    """Author and submit the stop's safety plan, leaving it awaiting certification.

    Accepts the same provisioning keywords as :func:`draft_safety_plan`.

    Returns ``plan`` and ``plan_id``.
    """
    state = draft_safety_plan(api, stop_id, **kwargs)
    state["plan"] = get_success_data(
        api.submit_safety_plan(state["plan_id"], headers=make_safety_author_headers())
    )
    return state


def certified_safety_plan(api: ApiClient, stop_id: str, **kwargs: Any) -> Dict[str, Any]:
    """Author, submit and certify the stop's safety plan.

    The plan is authored and submitted by one safety official and certified by a
    different one, because a plan may not be certified by its own author.

    Accepts the same provisioning keywords as :func:`draft_safety_plan`.

    Returns ``plan`` and ``plan_id``.
    """
    state = submitted_safety_plan(api, stop_id, **kwargs)
    state["plan"] = get_success_data(
        api.certify_safety_plan(
            state["plan_id"],
            F.make_certify_payload(),
            headers=make_safety_certifier_headers(),
        )
    )
    return state


def returned_safety_plan(api: ApiClient, stop_id: str, **kwargs: Any) -> Dict[str, Any]:
    """Author, submit and then return the stop's safety plan for rework.

    Accepts the same provisioning keywords as :func:`draft_safety_plan`.

    Returns ``plan`` and ``plan_id``.
    """
    state = submitted_safety_plan(api, stop_id, **kwargs)
    state["plan"] = get_success_data(
        api.return_safety_plan(
            state["plan_id"],
            F.make_return_plan_payload(),
            headers=make_safety_certifier_headers(),
        )
    )
    return state


def file_tech_inspection(api: ApiClient, entry_id: str, **overrides: Any) -> Dict[str, Any]:
    """File one technical inspection attempt against a staged entry.

    Accepts ``result``, ``defect_severity`` and ``notes``.

    Returns ``inspection``, ``inspection_id`` and the refreshed ``entry``.
    """
    row = get_success_data(
        api.create_tech_inspection(
            entry_id,
            F.make_tech_inspection_payload(**overrides),
            headers=make_safety_inspector_headers(),
        )
    )
    return {
        "inspection": row,
        "inspection_id": row["id"],
        "entry": fetch_entry(api, entry_id),
    }


def stop_ready_for_sale(
    api: ApiClient,
    season_id: Optional[str] = None,
    venue_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A stop that satisfies every readiness condition but is not yet on sale.

    Show timing is set, one competition segment is in the run order, the price
    card carries one or two tiers, the safety plan is certified and one committed
    marketing allocation puts money in the market — so the derived posture is the
    one from which sales may be opened.

    Tiers are created before the plan is certified, because adding a tier can
    raise the safety requirement floors and return an already-certified plan.

    Accepts every season, venue, booking, logistics, segment, tier, plan and
    marketing keyword, plus ``include_second_tier`` (default ``True``).

    Returns the keys of :func:`stop_with_show_timing` plus ``segment``,
    ``segment_id``, ``tier``, ``tier_id``, optionally ``second_tier`` and
    ``second_tier_id``, ``plan``, ``plan_id``, ``allocation``, ``allocation_id``.
    """
    groups = _route(kwargs)
    state = stop_with_show_timing(
        api,
        season_id=season_id,
        venue_id=venue_id,
        **_for_groups(kwargs, {"season", "venue", "booking", "logistics"}),
    )
    stop_id = state["stop_id"]

    state.update(
        create_show_segment(api, stop_id, **_prefixed(groups, "segment"))
    )

    tier_row = get_success_data(
        api.create_ticket_tier(
            stop_id,
            F.make_ticket_tier_payload(**_group(groups, "tier")),
            headers=make_ticketing_manager_headers(),
        )
    )
    state["tier"] = tier_row
    state["tier_id"] = tier_row["id"]

    if _control(groups, "include_second_tier", True):
        # The second tier shares the primary tier's selling window and group
        # terms, so a stop on a later date only needs its window stated once.
        shared_terms = {
            field: value
            for field, value in _group(groups, "tier").items()
            if field
            in {
                "on_sale_start_utc",
                "on_sale_end_utc",
                "group_min_qty",
                "group_discount_pct",
            }
        }
        shared_terms.update(_group(groups, "second_tier"))
        second_row = get_success_data(
            api.create_ticket_tier(
                stop_id,
                F.make_second_ticket_tier_payload(**shared_terms),
                headers=make_ticketing_manager_headers(),
            )
        )
        state["second_tier"] = second_row
        state["second_tier_id"] = second_row["id"]

    state.update(certified_safety_plan(api, stop_id, **_prefixed(groups, "plan")))
    state.update(
        commit_marketing_allocation(
            api, stop_id, state["season_id"], **_prefixed(groups, "marketing")
        )
    )

    state["stop"] = fetch_stop(api, stop_id)
    state["tier"] = fetch_tier(api, state["tier_id"])
    return state


# ---------------------------------------------------------------------------
# Tier 5 - the sales window, staging and settlement
# ---------------------------------------------------------------------------


def stop_on_sale(
    api: ApiClient,
    season_id: Optional[str] = None,
    venue_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A ready stop taken on sale by the ticketing desk.

    Accepts every keyword of :func:`stop_ready_for_sale`.

    Returns the keys of :func:`stop_ready_for_sale`, with ``stop`` refreshed.
    """
    state = stop_ready_for_sale(api, season_id=season_id, venue_id=venue_id, **kwargs)
    state["stop"] = get_success_data(
        api.open_tour_stop_sales(
            state["stop_id"], headers=make_ticketing_manager_headers()
        )
    )
    return state


def stop_with_pending_order(
    api: ApiClient,
    season_id: Optional[str] = None,
    venue_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """An on-sale stop carrying one order that has not been paid.

    Accepts every keyword of :func:`stop_on_sale` plus every order keyword.

    Returns the keys of :func:`stop_on_sale` plus ``order`` and ``order_id``.
    """
    groups = _route(kwargs)
    upstream = _for_groups(
        kwargs,
        {"season", "venue", "booking", "logistics", "segment", "tier", "second_tier", "plan", "marketing"},
        {"include_second_tier"},
    )
    state = stop_on_sale(api, season_id=season_id, venue_id=venue_id, **upstream)
    state.update(
        place_ticket_order(
            api, state["stop_id"], state["tier_id"], **_prefixed(groups, "order")
        )
    )
    state["stop"] = fetch_stop(api, state["stop_id"])
    return state


def stop_with_paid_order(
    api: ApiClient,
    season_id: Optional[str] = None,
    venue_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """An on-sale stop carrying one settled order, so the roll-ups carry money.

    Accepts every keyword of :func:`stop_on_sale` plus every order keyword.

    Returns the keys of :func:`stop_on_sale` plus ``order`` and ``order_id``.
    """
    state = stop_with_pending_order(api, season_id=season_id, venue_id=venue_id, **kwargs)
    state["order"] = get_success_data(
        api.pay_ticket_order(state["order_id"], headers=make_ticketing_manager_headers())
    )
    state["tier"] = fetch_tier(api, state["tier_id"])
    state["stop"] = fetch_stop(api, state["stop_id"])
    return state


def staged_entry(
    api: ApiClient,
    stop_id: str,
    competitor_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """One vehicle entry checked in against the stop, so it sits in its bay.

    Check-in only lands while the logical clock sits inside the staging window,
    which opens eight hours and closes two hours before the show starts, so the
    clock is moved into that window first.

    Accepts every competitor and entry keyword plus ``check_in_clock_utc``.

    Returns ``competitor``, ``competitor_id``, ``entry`` and ``entry_id``.
    """
    groups = _route(kwargs)
    state = create_vehicle_entry(
        api,
        stop_id,
        competitor_id=competitor_id,
        **_for_groups(kwargs, {"competitor", "entry"}),
    )
    set_clock(api, _control(groups, "check_in_clock_utc", C.DEFAULT_CHECK_IN_CLOCK_UTC))
    state["entry"] = get_success_data(
        api.check_in_vehicle_entry(
            state["entry_id"],
            F.make_check_in_payload(),
            headers=make_series_promoter_headers(),
        )
    )
    return state


def create_sponsorship_activation(
    api: ApiClient,
    stop_id: str,
    sponsor_id: Optional[str] = None,
    hospitality_tier_id: Optional[str] = None,
    branded_vehicle_entry_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Propose one activation package on the stop.

    Accepts every sponsor keyword when a sponsor has to be created, plus
    ``fee_cents``, ``vehicle_branding_slots``, ``signage_units`` and
    ``hospitality_seat_count``.

    Returns ``sponsor``, ``sponsor_id``, ``activation`` and ``activation_id``.
    """
    groups = _route(kwargs)
    state: Dict[str, Any] = {}
    if sponsor_id is None:
        state.update(create_sponsor(api, **_prefixed(groups, "sponsor")))
        sponsor_id = state["sponsor_id"]
    else:
        state["sponsor_id"] = sponsor_id
    row = get_success_data(
        api.create_sponsorship_activation(
            F.make_sponsorship_activation_payload(
                sponsor_id,
                stop_id,
                hospitality_tier_id=hospitality_tier_id,
                branded_vehicle_entry_id=branded_vehicle_entry_id,
                **_group(groups, "activation"),
            ),
            headers=make_series_promoter_headers(),
        )
    )
    state["activation"] = row
    state["activation_id"] = row["id"]
    return state


def activated_sponsorship_activation(
    api: ApiClient,
    stop_id: str,
    sponsor_id: Optional[str] = None,
    hospitality_tier_id: Optional[str] = None,
    branded_vehicle_entry_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """One activation package moved from proposed to live on the stop.

    Accepts the same keywords as :func:`create_sponsorship_activation`.

    Returns the same keys, with ``activation`` refreshed.
    """
    state = create_sponsorship_activation(
        api,
        stop_id,
        sponsor_id=sponsor_id,
        hospitality_tier_id=hospitality_tier_id,
        branded_vehicle_entry_id=branded_vehicle_entry_id,
        **kwargs,
    )
    state["activation"] = get_success_data(
        api.activate_sponsorship_activation(
            state["activation_id"], headers=make_series_promoter_headers()
        )
    )
    return state


def fulfilled_sponsorship_activation(
    api: ApiClient,
    stop_id: str,
    sponsor_id: Optional[str] = None,
    hospitality_tier_id: Optional[str] = None,
    branded_vehicle_entry_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """One activation package signed off as delivered.

    Accepts the same keywords as :func:`create_sponsorship_activation`.

    Returns the same keys, with ``activation`` refreshed.
    """
    state = activated_sponsorship_activation(
        api,
        stop_id,
        sponsor_id=sponsor_id,
        hospitality_tier_id=hospitality_tier_id,
        branded_vehicle_entry_id=branded_vehicle_entry_id,
        **kwargs,
    )
    state["activation"] = get_success_data(
        api.fulfill_sponsorship_activation(
            state["activation_id"],
            F.make_fulfill_payload(),
            headers=make_series_promoter_headers(),
        )
    )
    return state


def stop_sales_halted(
    api: ApiClient,
    season_id: Optional[str] = None,
    venue_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """An on-sale stop driven to a halt by releasing its only marketing money.

    Releasing the market's last committed allocation pulls the derived posture
    away from the one that permits sales, which the server answers by halting the
    stop and voiding its pending orders.

    Accepts every keyword of :func:`stop_on_sale`.

    Returns the keys of :func:`stop_on_sale`, with ``stop`` and ``allocation``
    refreshed.
    """
    state = stop_on_sale(api, season_id=season_id, venue_id=venue_id, **kwargs)
    state["allocation"] = get_success_data(
        api.release_marketing_allocation(
            state["allocation_id"], headers=make_series_promoter_headers()
        )
    )
    state["stop"] = fetch_stop(api, state["stop_id"])
    state["season"] = fetch_season(api, state["season_id"])
    return state


def stop_sales_closed(
    api: ApiClient,
    season_id: Optional[str] = None,
    venue_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A stop with one settled order whose sales window has been closed.

    Accepts every keyword of :func:`stop_with_paid_order`.

    Returns the keys of :func:`stop_with_paid_order`, with ``stop`` refreshed.
    """
    state = stop_with_paid_order(api, season_id=season_id, venue_id=venue_id, **kwargs)
    state["stop"] = get_success_data(
        api.close_tour_stop_sales(
            state["stop_id"], headers=make_ticketing_manager_headers()
        )
    )
    return state


def stage_and_close_stop(
    api: ApiClient,
    state: Dict[str, Any],
    sponsor_id: Optional[str] = None,
    competitor_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Add the remaining money sources to an on-sale stop and close its sales.

    Given the state dictionary of an on-sale stop that already carries a settled
    order, this stages one vehicle entry (which earns the competitor purse) and
    takes one activation package live (which earns sponsorship revenue), then
    closes the sales window. An existing competitor or sponsor may be reused, so
    several stops can share one team and one sponsor without tripping the
    uniqueness rules on their names.

    Accepts every competitor, entry, sponsor and activation keyword plus
    ``check_in_clock_utc``, ``with_entry`` (default ``True``),
    ``with_activation`` (default ``True``) and ``fulfill_activation``
    (default ``False``).

    Returns the same dictionary, updated in place.
    """
    groups = _route(kwargs)
    stop_id = state["stop_id"]

    if _control(groups, "with_entry", True):
        state.update(
            staged_entry(
                api,
                stop_id,
                competitor_id=competitor_id,
                **_for_groups(
                    kwargs, {"competitor", "entry"}, {"check_in_clock_utc"}
                ),
            )
        )

    if _control(groups, "with_activation", True):
        builder = (
            fulfilled_sponsorship_activation
            if _control(groups, "fulfill_activation", False)
            else activated_sponsorship_activation
        )
        state.update(
            builder(
                api,
                stop_id,
                sponsor_id=sponsor_id,
                hospitality_tier_id=state.get("second_tier_id"),
                branded_vehicle_entry_id=state.get("entry_id"),
                **_for_groups(kwargs, {"sponsor", "activation"}),
            )
        )

    state["stop"] = get_success_data(
        api.close_tour_stop_sales(stop_id, headers=make_ticketing_manager_headers())
    )
    state["tier"] = fetch_tier(api, state["tier_id"])
    state["season"] = fetch_season(api, state["season_id"])
    return state


def settlement_ready_stop(
    api: ApiClient,
    season_id: Optional[str] = None,
    venue_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A closed stop with every money source on it, ready for a settlement.

    The stop carries a settled order, one staged entry that earns the competitor
    purse, one live activation that earns sponsorship revenue, a certified safety
    plan whose provisioning bill becomes the safety cost, and one committed
    marketing allocation. No order is left pending and sales are closed, so both
    preparation and approval are admissible.

    Accepts every keyword of :func:`stop_with_paid_order` plus every competitor,
    entry, sponsor and activation keyword, plus ``check_in_clock_utc``,
    ``with_entry``, ``with_activation`` and ``fulfill_activation``.

    Returns the keys of :func:`stop_with_paid_order` plus, when built,
    ``competitor``, ``competitor_id``, ``entry``, ``entry_id``, ``sponsor``,
    ``sponsor_id``, ``activation`` and ``activation_id``.
    """
    upstream = _for_groups(
        kwargs,
        {
            "season",
            "venue",
            "booking",
            "logistics",
            "segment",
            "tier",
            "second_tier",
            "plan",
            "marketing",
            "order",
        },
        {"include_second_tier"},
    )
    state = stop_with_paid_order(api, season_id=season_id, venue_id=venue_id, **upstream)
    downstream = _for_groups(
        kwargs,
        {"competitor", "entry", "sponsor", "activation"},
        {"check_in_clock_utc", "with_entry", "with_activation", "fulfill_activation"},
    )
    return stage_and_close_stop(api, state, **downstream)


def settle_closed_stop(
    api: ApiClient, state: Dict[str, Any], approve: bool = True
) -> Dict[str, Any]:
    """Cut a settlement on an already-closed stop and, by default, approve it.

    Preparation is filed by one finance controller and approval by a different
    one, because a settlement may not be approved by its preparer. Approval
    settles the stop and rolls its figures up into the season.

    Returns the same dictionary, updated in place, with ``settlement`` and
    ``settlement_id`` added.
    """
    row = get_success_data(
        api.create_settlement(state["stop_id"], headers=make_finance_preparer_headers())
    )
    state["settlement"] = row
    state["settlement_id"] = row["id"]
    if approve:
        state["settlement"] = get_success_data(
            api.approve_settlement(
                row["id"],
                F.make_approve_settlement_payload(),
                headers=make_finance_approver_headers(),
            )
        )
        state["stop"] = fetch_stop(api, state["stop_id"])
        state["season"] = fetch_season(api, state["season_id"])
    return state


def prepared_settlement(
    api: ApiClient,
    season_id: Optional[str] = None,
    venue_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A settlement cut under the provisional variant on a closed stop.

    Accepts every keyword of :func:`settlement_ready_stop`.

    Returns the keys of :func:`settlement_ready_stop` plus ``settlement`` and
    ``settlement_id``.
    """
    state = settlement_ready_stop(api, season_id=season_id, venue_id=venue_id, **kwargs)
    return settle_closed_stop(api, state, approve=False)


def disputed_settlement(
    api: ApiClient,
    season_id: Optional[str] = None,
    venue_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A prepared settlement the building has pushed back on.

    Accepts every keyword of :func:`settlement_ready_stop`.

    Returns the keys of :func:`prepared_settlement`, with ``settlement``
    refreshed.
    """
    state = prepared_settlement(api, season_id=season_id, venue_id=venue_id, **kwargs)
    state["settlement"] = get_success_data(
        api.dispute_settlement(
            state["settlement_id"],
            F.make_dispute_settlement_payload(),
            headers=make_finance_preparer_headers(),
        )
    )
    return state


def approved_settlement(
    api: ApiClient,
    season_id: Optional[str] = None,
    venue_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A settlement approved under the final variant, settling the stop.

    Approval is filed by a finance controller other than the preparer, and it
    bubbles up to the season's counters. When this is the season's only stop, the
    season closes as a consequence.

    Accepts every keyword of :func:`settlement_ready_stop`.

    Returns the keys of :func:`prepared_settlement`, with ``settlement``, ``stop``
    and ``season`` refreshed.
    """
    state = settlement_ready_stop(api, season_id=season_id, venue_id=venue_id, **kwargs)
    return settle_closed_stop(api, state, approve=True)


# ---------------------------------------------------------------------------
# Multi-market seasons
# ---------------------------------------------------------------------------

#: Distinct markets, dates and show timings that never collide with each other,
#: so several stops can live in one season without an occupancy or rotation clash.
MARKET_PROFILES: List[Dict[str, Any]] = [
    {
        "venue_name": C.DEFAULT_VENUE_NAME,
        "market_code": C.DEFAULT_VENUE_MARKET_CODE,
        "city": C.DEFAULT_VENUE_CITY,
        "state_code": C.DEFAULT_VENUE_STATE_CODE,
        "tour_date": C.DEFAULT_TOUR_DATE,
        "load_in_start_utc": C.DEFAULT_LOAD_IN_START_UTC,
        "tear_down_end_utc": C.DEFAULT_TEAR_DOWN_END_UTC,
        "doors_open_utc": C.DEFAULT_DOORS_OPEN_UTC,
        "show_start_utc": C.DEFAULT_SHOW_START_UTC,
        "on_sale_end_utc": C.DEFAULT_ON_SALE_END_UTC,
        "scheduled_arrival_utc": C.DEFAULT_SCHEDULED_ARRIVAL_UTC,
        "check_in_clock_utc": C.DEFAULT_CHECK_IN_CLOCK_UTC,
    },
    {
        "venue_name": C.SECOND_VENUE_NAME,
        "market_code": C.SECOND_VENUE_MARKET_CODE,
        "city": C.SECOND_VENUE_CITY,
        "state_code": C.SECOND_VENUE_STATE_CODE,
        "tour_date": C.SECOND_TOUR_DATE,
        "load_in_start_utc": C.SECOND_LOAD_IN_START_UTC,
        "tear_down_end_utc": C.SECOND_TEAR_DOWN_END_UTC,
        "doors_open_utc": C.SECOND_DOORS_OPEN_UTC,
        "show_start_utc": C.SECOND_SHOW_START_UTC,
        "on_sale_end_utc": "2026-12-05T18:00:00Z",
        "scheduled_arrival_utc": "2026-12-05T16:00:00Z",
        "check_in_clock_utc": "2026-12-05T17:00:00Z",
    },
    {
        "venue_name": C.THIRD_VENUE_NAME,
        "market_code": C.THIRD_VENUE_MARKET_CODE,
        "city": C.THIRD_VENUE_CITY,
        "state_code": C.THIRD_VENUE_STATE_CODE,
        "tour_date": C.THIRD_TOUR_DATE,
        "load_in_start_utc": C.THIRD_LOAD_IN_START_UTC,
        "tear_down_end_utc": C.THIRD_TEAR_DOWN_END_UTC,
        "doors_open_utc": C.THIRD_DOORS_OPEN_UTC,
        "show_start_utc": C.THIRD_SHOW_START_UTC,
        "on_sale_end_utc": "2027-01-09T18:00:00Z",
        "scheduled_arrival_utc": "2027-01-09T16:00:00Z",
        "check_in_clock_utc": "2027-01-09T17:00:00Z",
    },
]

#: Keywords the multi-stop helpers supply themselves, one value per market.
_PROFILE_KEYWORDS: Set[str] = {
    "venue_name",
    "market_code",
    "city",
    "state_code",
    "tour_date",
    "load_in_start_utc",
    "tear_down_end_utc",
    "doors_open_utc",
    "show_start_utc",
    "on_sale_end_utc",
    "scheduled_arrival_utc",
}


def _profile_kwargs(index: int) -> Dict[str, Any]:
    """Market, calendar and timing keywords for the market at ``index``."""
    profile = MARKET_PROFILES[index % len(MARKET_PROFILES)]
    return {key: profile[key] for key in _PROFILE_KEYWORDS}


def multi_market_season(
    api: ApiClient,
    market_count: int = 2,
    settle: bool = True,
    **kwargs: Any,
) -> Dict[str, Any]:
    """One season carrying several stops in distinct markets.

    Every stop is built to the same depth — show timing, one competition segment,
    a price card, a certified safety plan, committed marketing money and a settled
    order — and then, when ``settle`` is set, each stop in turn is staged, closed
    and settled, which is the state the by-market report reads.

    All the stops are built before any of them is settled, because settling the
    last outstanding stop of a season closes that season and a closed season takes
    no further bookings. Within the settling pass the logical clock only ever
    moves forward, from each stop's staging window to the next.

    Because every stop lives in its own market on its own date, neither the
    building's calendar nor the market rotation cooldown can interfere. One team
    and one sponsor are shared across the stops, since their names are unique
    system-wide while a vehicle number is only unique within a stop.

    ``market_count`` may be 1, 2 or 3. Accepts every season keyword plus every
    keyword the per-stop chain accepts; the market, calendar and timing values are
    supplied per stop and may not be overridden here.

    Returns ``season``, ``season_id``, ``stops`` (the per-stop state
    dictionaries, in build order), ``stop_ids``, ``competitor``,
    ``competitor_id``, ``sponsor`` and ``sponsor_id``.
    """
    assert 1 <= market_count <= len(MARKET_PROFILES), (
        f"market_count must be between 1 and {len(MARKET_PROFILES)}"
    )
    groups = _route(kwargs)
    season_state = create_season(api, **_prefixed(groups, "season"))
    season_id = season_state["season_id"]

    shared = {
        key: value
        for key, value in kwargs.items()
        if key not in _PROFILE_KEYWORDS
        and (key in _CONTROL_KEYWORDS or _KEYWORD_ROUTES[key][0] != "season")
    }
    per_stop = _for_groups(
        shared,
        {
            "venue",
            "booking",
            "logistics",
            "segment",
            "tier",
            "second_tier",
            "plan",
            "marketing",
            "order",
        },
        {"include_second_tier"},
    )
    downstream = _for_groups(
        shared,
        {"competitor", "entry", "sponsor", "activation"},
        {"with_entry", "with_activation", "fulfill_activation"},
    )

    stops: List[Dict[str, Any]] = []
    for index in range(market_count):
        stop_kwargs = dict(per_stop)
        stop_kwargs.update(
            {
                key: value
                for key, value in _profile_kwargs(index).items()
                if key != "scheduled_arrival_utc"
            }
        )
        stops.append(stop_with_paid_order(api, season_id=season_id, **stop_kwargs))

    team = create_competitor(api, **_prefixed(groups, "competitor"))
    sponsor = create_sponsor(api, **_prefixed(groups, "sponsor"))

    if settle:
        for index, stop_state in enumerate(stops):
            profile = MARKET_PROFILES[index % len(MARKET_PROFILES)]
            stage_and_close_stop(
                api,
                stop_state,
                sponsor_id=sponsor["sponsor_id"],
                competitor_id=team["competitor_id"],
                check_in_clock_utc=profile["check_in_clock_utc"],
                scheduled_arrival_utc=profile["scheduled_arrival_utc"],
                **downstream,
            )
            settle_closed_stop(api, stop_state, approve=True)

    return {
        "season": fetch_season(api, season_id),
        "season_id": season_id,
        "stops": stops,
        "stop_ids": [stop["stop_id"] for stop in stops],
        "competitor": team["competitor"],
        "competitor_id": team["competitor_id"],
        "sponsor": sponsor["sponsor"],
        "sponsor_id": sponsor["sponsor_id"],
    }


def transport_chain_stops(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Two stops in one season, the second linked to the first as its predecessor.

    The link is what the one-sided haul buffer is measured against: the second
    stop's load-in may not begin sooner after the first stop's tear-down than the
    haul from the first market requires.

    Accepts every season keyword plus every keyword the per-stop chain accepts;
    the market, calendar and timing values are supplied per stop.

    Returns ``season``, ``season_id``, ``first`` and ``second`` (the two per-stop
    state dictionaries) and ``stop_ids``.
    """
    groups = _route(kwargs)
    season_state = create_season(api, **_prefixed(groups, "season"))
    season_id = season_state["season_id"]

    per_stop = _for_groups(
        {
            key: value
            for key, value in kwargs.items()
            if key not in _PROFILE_KEYWORDS
        },
        {"venue", "booking", "logistics"},
    )

    first_kwargs = dict(per_stop)
    first_kwargs.update(_for_groups(_profile_kwargs(0), {"venue", "booking", "logistics"}))
    first = stop_with_show_timing(api, season_id=season_id, **first_kwargs)

    second_kwargs = dict(per_stop)
    second_kwargs.update(_for_groups(_profile_kwargs(1), {"venue", "booking", "logistics"}))
    second_kwargs["preceding_stop_id"] = first["stop_id"]
    second_kwargs.setdefault("haul_distance_miles", C.DEFAULT_HAUL_DISTANCE_MILES)
    second = stop_with_show_timing(api, season_id=season_id, **second_kwargs)

    return {
        "season": fetch_season(api, season_id),
        "season_id": season_id,
        "first": first,
        "second": second,
        "stop_ids": [first["stop_id"], second["stop_id"]],
    }
