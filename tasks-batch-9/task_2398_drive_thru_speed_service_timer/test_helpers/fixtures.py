"""Composite setup helpers.

Every test starts against an empty store of record, so all preconditions are
built here through the declared endpoints only. These helpers use the lenient
`get_success_data` so that a precondition never asserts an exact status code on
behalf of the test that follows it.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import DriveThruApiClient
from .constants import (
    BASE_GREET_TARGET,
    BASE_ORDER_TARGET,
    BASE_PULL_FORWARD_TARGET,
    BASE_WINDOW_TARGET,
    FOUR_TIER_BANDS,
    UNBOUNDED_BAND,
)
from .test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    COACH_HEADERS,
    make_operator_headers,
    make_shift_leader_headers,
)

# The single operating day every fixture works inside (PRD §2.4 clock epoch).
OPERATING_DAY = "2026-08-01"


def at(hour: int, minute: int = 0, second: int = 0) -> str:
    """An instant on the operating day, as the whole-second UTC literal."""
    return f"{OPERATING_DAY}T{hour:02d}:{minute:02d}:{second:02d}Z"


DAY_START = at(0, 0, 0)


# --- Clock --------------------------------------------------------------------
def set_clock(client: DriveThruApiClient, instant: str) -> Dict[str, Any]:
    """Move the logical clock to `instant` (ProgramAdmin only)."""
    return get_success_data(client.set_clock(f.clock_body(instant), ADMIN_HEADERS))


# --- Volume tier bands --------------------------------------------------------
def create_tier_band(client: DriveThruApiClient, band: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(
        client.create_volume_tier_policy(f.tier_policy_body(**band), ADMIN_HEADERS)
    )


def setup_single_unbounded_band(client: DriveThruApiClient) -> Dict[str, Any]:
    """One TIER_1 band covering every rate: relief 0.00 and min_oot 0 throughout."""
    return create_tier_band(client, dict(UNBOUNDED_BAND))


def setup_four_tier_bands(
    client: DriveThruApiClient, bands: Sequence[Dict[str, Any]] = FOUR_TIER_BANDS
) -> List[Dict[str, Any]]:
    """The full four-band ladder, created before any store exists."""
    return [create_tier_band(client, dict(band)) for band in bands]


# --- Store ---------------------------------------------------------------------
@dataclass
class StoreContext:
    """A registered store plus the identities that may act on it."""

    restaurant: Dict[str, Any]
    operator_headers: Dict[str, str]
    profile: Optional[Dict[str, Any]] = None
    staff: Optional[Dict[str, Any]] = None
    leader_headers: Optional[Dict[str, str]] = None

    @property
    def restaurant_id(self) -> str:
        return self.restaurant["id"]

    @property
    def profile_id(self) -> str:
        assert self.profile is not None, "no daypart profile in this context"
        return self.profile["id"]

    @property
    def staff_id(self) -> str:
        assert self.staff is not None, "no staff member in this context"
        return self.staff["id"]


def register_restaurant(
    client: DriveThruApiClient, store_number: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.register_restaurant(
            f.restaurant_body(store_number, **overrides), ADMIN_HEADERS
        )
    )


def get_restaurant(
    client: DriveThruApiClient, restaurant_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        client.get_restaurant(restaurant_id, headers or ADMIN_HEADERS)
    )


def current_restaurant_version(
    client: DriveThruApiClient, restaurant_id: str, headers: Optional[Dict[str, str]] = None
) -> int:
    """Read the store's current version, for the optimistic-concurrency token."""
    return get_restaurant(client, restaurant_id, headers)["version"]


def add_staff_member(
    client: DriveThruApiClient,
    restaurant_id: str,
    full_name: str = "Avery Lane",
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_staff_member(
            f.staff_member_body(restaurant_id, full_name, **overrides),
            make_operator_headers(restaurant_id),
        )
    )


def create_daypart_profile(
    client: DriveThruApiClient, restaurant_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.create_daypart_profile(
            f.daypart_profile_body(restaurant_id, **overrides),
            make_operator_headers(restaurant_id),
        )
    )


def activate_profile(
    client: DriveThruApiClient, restaurant_id: str, profile_id: str
) -> Dict[str, Any]:
    return get_success_data(
        client.activate_daypart_profile(
            profile_id, make_operator_headers(restaurant_id)
        )
    )


def setup_store(
    client: DriveThruApiClient,
    store_number: str,
    lane_config: str = "SINGLE",
    merge_slots_capacity: int = 1,
    labor_minutes_budget: int = 300,
    with_staff: bool = True,
    staff_name: str = "Avery Lane",
    oot_certified: bool = True,
    window_certified: bool = True,
    with_active_lunch_profile: bool = True,
    profile_overrides: Optional[Dict[str, Any]] = None,
    **restaurant_overrides: Any,
) -> StoreContext:
    """Register a store and, by default, give it a staff member and an ACTIVE LUNCH
    profile whose four targets are 25 / 95 / 40 / 75.
    """
    restaurant = register_restaurant(
        client,
        store_number,
        lane_config=lane_config,
        merge_slots_capacity=merge_slots_capacity,
        labor_minutes_budget=labor_minutes_budget,
        **restaurant_overrides,
    )
    ctx = StoreContext(
        restaurant=restaurant, operator_headers=make_operator_headers(restaurant["id"])
    )
    if with_staff:
        ctx.staff = add_staff_member(
            client,
            restaurant["id"],
            staff_name,
            oot_certified=oot_certified,
            window_certified=window_certified,
        )
        ctx.leader_headers = make_shift_leader_headers(ctx.staff["id"])
    if with_active_lunch_profile:
        profile = create_daypart_profile(
            client, restaurant["id"], **(profile_overrides or {})
        )
        ctx.profile = activate_profile(client, restaurant["id"], profile["id"])
    return ctx


def freeze_store(
    client: DriveThruApiClient, ctx: StoreContext, freeze_reason: str
) -> Dict[str, Any]:
    return get_success_data(
        client.freeze_restaurant(
            ctx.restaurant_id, f.freeze_body(freeze_reason), ctx.operator_headers
        )
    )


def unfreeze_store(client: DriveThruApiClient, ctx: StoreContext) -> Dict[str, Any]:
    return get_success_data(
        client.unfreeze_restaurant(ctx.restaurant_id, ctx.operator_headers)
    )


# --- Deployments ---------------------------------------------------------------
def plan_deployment(
    client: DriveThruApiClient,
    ctx: StoreContext,
    planned_start_at: str,
    planned_end_at: str,
    staff_member_id: Optional[str] = None,
    position: str = "OOT_LANE_A",
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_deployment(
            f.deployment_body(
                ctx.restaurant_id,
                staff_member_id or ctx.staff_id,
                ctx.profile_id,
                planned_start_at,
                planned_end_at,
                position=position,
                **overrides,
            ),
            ctx.operator_headers,
        )
    )


def activate_deployment(
    client: DriveThruApiClient, ctx: StoreContext, deployment_id: str
) -> Dict[str, Any]:
    return get_success_data(
        client.activate_deployment(deployment_id, ctx.operator_headers)
    )


def release_deployment(
    client: DriveThruApiClient, ctx: StoreContext, deployment_id: str
) -> Dict[str, Any]:
    return get_success_data(
        client.release_deployment(deployment_id, ctx.operator_headers)
    )


# --- Timer loops ---------------------------------------------------------------
def open_loop(
    client: DriveThruApiClient,
    ctx: StoreContext,
    lane: str = "SINGLE",
    leader_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_timer_loop(
            f.timer_loop_body(ctx.restaurant_id, ctx.profile_id, lane, **overrides),
            leader_headers or ctx.leader_headers,
        )
    )


def greet_loop(
    client: DriveThruApiClient,
    ctx: StoreContext,
    loop_id: str,
    leader_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.greet_timer_loop(loop_id, leader_headers or ctx.leader_headers)
    )


def complete_order(
    client: DriveThruApiClient,
    ctx: StoreContext,
    loop_id: str,
    order_items_count: int = 4,
    leader_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.complete_order(
            loop_id,
            f.order_complete_body(order_items_count),
            leader_headers or ctx.leader_headers,
        )
    )


def arrive_at_window(
    client: DriveThruApiClient,
    ctx: StoreContext,
    loop_id: str,
    leader_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.window_arrive(loop_id, leader_headers or ctx.leader_headers)
    )


def depart_loop(
    client: DriveThruApiClient,
    ctx: StoreContext,
    loop_id: str,
    leader_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.depart_timer_loop(loop_id, leader_headers or ctx.leader_headers)
    )


def drive_loop(
    client: DriveThruApiClient,
    ctx: StoreContext,
    lane: str = "SINGLE",
    arrive_at: str = at(11, 0, 0),
    greet_at: Optional[str] = at(11, 0, 20),
    order_complete_at: Optional[str] = at(11, 1, 0),
    window_arrive_at: Optional[str] = at(11, 2, 0),
    depart_at: Optional[str] = at(11, 4, 10),
    order_items_count: int = 4,
    leader_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Open a loop at `arrive_at` and advance it through the stamps supplied.

    Passing `None` for a stamp stops the walk there, which is how a test parks a
    loop in OPEN / GREETED / ORDERED / AT_WINDOW.
    """
    headers = leader_headers or ctx.leader_headers
    set_clock(client, arrive_at)
    loop = open_loop(client, ctx, lane=lane, leader_headers=headers)
    loop_id = loop["id"]
    if greet_at is None:
        return loop
    set_clock(client, greet_at)
    loop = greet_loop(client, ctx, loop_id, headers)
    if order_complete_at is None:
        return loop
    set_clock(client, order_complete_at)
    loop = complete_order(client, ctx, loop_id, order_items_count, headers)
    if window_arrive_at is None:
        return loop
    set_clock(client, window_arrive_at)
    loop = arrive_at_window(client, ctx, loop_id, headers)
    if depart_at is None:
        return loop
    set_clock(client, depart_at)
    return depart_loop(client, ctx, loop_id, headers)


# --- Merge slots ---------------------------------------------------------------
def award_merge_slot(
    client: DriveThruApiClient,
    ctx: StoreContext,
    leader_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.award_merge_slot(
            ctx.restaurant_id, leader_headers or ctx.leader_headers
        )
    )


def commit_slot(
    client: DriveThruApiClient,
    ctx: StoreContext,
    slot_id: str,
    leader_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.commit_merge_slot(slot_id, leader_headers or ctx.leader_headers)
    )


# --- Pull-forward orders -------------------------------------------------------
def issue_pull_forward(
    client: DriveThruApiClient,
    ctx: StoreContext,
    loop_id: str,
    reason: str = "ITEM_LAG",
    lag_seconds: Optional[int] = None,
    leader_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_pull_forward_order(
            f.pull_forward_body(loop_id, reason, lag_seconds),
            leader_headers or ctx.leader_headers,
        )
    )


# --- Accuracy incidents --------------------------------------------------------
def log_incident(
    client: DriveThruApiClient,
    ctx: StoreContext,
    loop_id: str,
    incident_type: str = "WRONG_ITEM",
    logged_by_staff_id: Optional[str] = None,
    leader_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_accuracy_incident(
            f.accuracy_incident_body(
                loop_id, logged_by_staff_id or ctx.staff_id, incident_type
            ),
            leader_headers or ctx.leader_headers,
        )
    )


def deliver_remake(
    client: DriveThruApiClient,
    ctx: StoreContext,
    incident_id: str,
    remade_by_staff_id: str,
    leader_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.deliver_remake(
            incident_id,
            f.deliver_remake_body(remade_by_staff_id),
            leader_headers or ctx.leader_headers,
        )
    )


def waive_incident(
    client: DriveThruApiClient, incident_id: str, waiver_reason: str
) -> Dict[str, Any]:
    return get_success_data(
        client.waive_accuracy_incident(
            incident_id, f.waive_body(waiver_reason), AUDITOR_HEADERS
        )
    )


def close_incident(client: DriveThruApiClient, incident_id: str) -> Dict[str, Any]:
    return get_success_data(client.close_accuracy_incident(incident_id, AUDITOR_HEADERS))


# --- Throughput reports --------------------------------------------------------
def create_report(
    client: DriveThruApiClient,
    ctx: StoreContext,
    window_start_at: str,
    window_end_at: str,
    variant: str = "PROVISIONAL",
    supersedes_report_id: Optional[str] = None,
    expected_restaurant_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create a report, reading the store's current version unless one is given."""
    version = (
        expected_restaurant_version
        if expected_restaurant_version is not None
        else current_restaurant_version(client, ctx.restaurant_id)
    )
    return get_success_data(
        client.create_throughput_report(
            f.throughput_report_body(
                ctx.restaurant_id,
                window_start_at,
                window_end_at,
                version,
                variant=variant,
                supersedes_report_id=supersedes_report_id,
            ),
            headers or COACH_HEADERS,
        )
    )


def publish_report(
    client: DriveThruApiClient, report_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        client.publish_throughput_report(report_id, headers or COACH_HEADERS)
    )


def create_published_report(
    client: DriveThruApiClient,
    ctx: StoreContext,
    window_start_at: str,
    window_end_at: str,
    variant: str = "PROVISIONAL",
    supersedes_report_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    report = create_report(
        client,
        ctx,
        window_start_at,
        window_end_at,
        variant=variant,
        supersedes_report_id=supersedes_report_id,
        headers=headers,
    )
    return publish_report(client, report["id"], headers)


# --- Coaching interventions ----------------------------------------------------
def create_coaching(
    client: DriveThruApiClient,
    report_id: str,
    staff_member_id: str,
    focus_segment: str = "GREET",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_coaching_intervention(
            f.coaching_body(report_id, staff_member_id, focus_segment),
            headers or COACH_HEADERS,
        )
    )


def issue_coaching(
    client: DriveThruApiClient, coaching_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        client.issue_coaching_intervention(coaching_id, headers or COACH_HEADERS)
    )


def acknowledge_coaching(
    client: DriveThruApiClient, ctx: StoreContext, coaching_id: str
) -> Dict[str, Any]:
    return get_success_data(
        client.acknowledge_coaching_intervention(coaching_id, ctx.leader_headers)
    )


def contest_coaching(
    client: DriveThruApiClient, ctx: StoreContext, coaching_id: str, contest_reason: str
) -> Dict[str, Any]:
    return get_success_data(
        client.contest_coaching_intervention(
            coaching_id, f.contest_body(contest_reason), ctx.leader_headers
        )
    )


# --- Forecast overrides --------------------------------------------------------
def propose_override(
    client: DriveThruApiClient,
    ctx: StoreContext,
    effective_start_at: str,
    effective_end_at: str,
    projected_cars_delta_pct: float,
    source: str = "WEATHER",
    target_relief_pct_override: Optional[float] = None,
    expected_restaurant_version: Optional[int] = None,
) -> Dict[str, Any]:
    version = (
        expected_restaurant_version
        if expected_restaurant_version is not None
        else current_restaurant_version(client, ctx.restaurant_id)
    )
    return get_success_data(
        client.create_forecast_override(
            f.forecast_override_body(
                ctx.restaurant_id,
                effective_start_at,
                effective_end_at,
                projected_cars_delta_pct,
                version,
                source=source,
                target_relief_pct_override=target_relief_pct_override,
            ),
            ctx.operator_headers,
        )
    )


def approve_override(client: DriveThruApiClient, override_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.approve_forecast_override(override_id, ADMIN_HEADERS)
    )


def apply_override(
    client: DriveThruApiClient, ctx: StoreContext, override_id: str
) -> Dict[str, Any]:
    return get_success_data(
        client.apply_forecast_override(override_id, ctx.operator_headers)
    )


def applied_override(
    client: DriveThruApiClient,
    ctx: StoreContext,
    effective_start_at: str,
    effective_end_at: str,
    projected_cars_delta_pct: float,
    source: str = "WEATHER",
    target_relief_pct_override: Optional[float] = None,
) -> Dict[str, Any]:
    """Propose, approve and apply one override in a single step."""
    override = propose_override(
        client,
        ctx,
        effective_start_at,
        effective_end_at,
        projected_cars_delta_pct,
        source=source,
        target_relief_pct_override=target_relief_pct_override,
    )
    approve_override(client, override["id"])
    return apply_override(client, ctx, override["id"])


# --- Convenience: the unrelieved LUNCH target ladder ---------------------------
BASE_SEGMENT_TARGETS = (
    BASE_GREET_TARGET,
    BASE_ORDER_TARGET,
    BASE_PULL_FORWARD_TARGET,
    BASE_WINDOW_TARGET,
)
