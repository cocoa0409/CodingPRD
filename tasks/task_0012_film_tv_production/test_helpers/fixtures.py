"""Composite setup helpers for the Film/TV Production API.

Fixtures encapsulate multi-step preambles so tests focus on assertions.

Design principles:
- Every fixture uses `get_success_data()` (lenient) so setup failures yield
  clear "Setup failed" errors rather than confusing assertion noise.
- All five roles are `opaque` per PRD §2.1, so shared role headers are canonical.
  Per-X-User-ID identities still matter for segregation-of-duties on
  ChangeOrder approval (PRD §3.7); the helpers thread distinct user IDs where
  the rule requires it.
- All datetimes are ISO 8601 UTC with three fractional digits (PRD §2.4).
- All monetary values are integer cents (PRD §2.8).
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client, ApiClient
from .factories import (
    create_production_payload,
    create_scene_payload,
    create_role_payload,
    create_audition_payload,
    offer_role_payload,
    substitute_role_payload,
    create_actor_payload,
    create_location_payload,
    create_location_reservation_payload,
    patch_permit_status_payload,
    patch_weather_status_payload,
    schedule_scene_payload,
    reschedule_scene_payload,
    create_budget_category_payload,
    create_change_order_payload,
    create_equipment_payload,
    create_equipment_event_payload,
    create_crew_assignment_payload,
    patch_actual_days_payload,
    create_vendor_invoice_payload,
)
from .test_users import (
    TEST_USERS,
    make_executive_producer_headers,
    make_line_producer_headers,
    make_finance_controller_headers,
    make_casting_director_headers,
    make_production_coordinator_headers,
    with_override_reason,
)


# Convenience aliases — use these in tests by default.
EXEC = TEST_USERS["executive_producer_headers"]
LP = TEST_USERS["line_producer_headers"]
FC = TEST_USERS["finance_controller_headers"]
CD = TEST_USERS["casting_director_headers"]
PC = TEST_USERS["production_coordinator_headers"]


# ─── Time helpers ─────────────────────────────────────────────────────────────

def iso(year: int = 2026, month: int = 2, day: int = 1,
         hour: int = 9, minute: int = 0, second: int = 0,
         milli: int = 0) -> str:
    """Build an ISO 8601 UTC timestamp string with .{milli:03d}Z fractional suffix."""
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}.{milli:03d}Z"


def add_minutes(iso_ts: str, minutes: int) -> str:
    """Add `minutes` to an ISO timestamp produced by `iso()`."""
    from datetime import datetime, timedelta, timezone
    # Parse, add, re-format with .000Z fractional suffix.
    parsed = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    new_dt = parsed + timedelta(minutes=minutes)
    new_dt = new_dt.astimezone(timezone.utc)
    base = new_dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = new_dt.microsecond // 1000
    return f"{base}.{millis:03d}Z"


# ─── Tier 1: Production lifecycle progression ────────────────────────────────

def create_production(api: ApiClient = api_client, **overrides) -> Dict[str, Any]:
    """Create a Production in PLANNING state. Returns the entity."""
    payload = create_production_payload(**overrides)
    resp = api.create_production(payload, EXEC)
    return get_success_data(resp)


def setup_production_with_categories(
    api: ApiClient = api_client,
    *,
    total_budget_cents: int = 200_000_000,
    reserve_fund_cents: int = 20_000_000,
    cast_planned_cents: int = 50_000_000,
    crew_planned_cents: int = 50_000_000,
    equipment_planned_cents: int = 30_000_000,
    location_planned_cents: int = 20_000_000,
    post_planned_cents: int = 20_000_000,
    misc_planned_cents: int = 10_000_000,
    **production_overrides,
) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    """Create a Production + one BudgetCategory per code (CAST, CREW, EQUIPMENT,
    LOCATION, POST, MISC). Returns (production, {category_code: category}).

    Default sums: cast 50M + crew 50M + equipment 30M + location 20M +
    post 20M + misc 10M = 180M; reserve 20M; total 200M ⇒ headroom 0M.
    Override individual category sizes to fit specific scenarios.
    """
    production = create_production(
        api,
        total_budget_cents=total_budget_cents,
        reserve_fund_cents=reserve_fund_cents,
        **production_overrides,
    )
    cats: Dict[str, Dict[str, Any]] = {}
    for code, planned in (
        ("CAST", cast_planned_cents),
        ("CREW", crew_planned_cents),
        ("EQUIPMENT", equipment_planned_cents),
        ("LOCATION", location_planned_cents),
        ("POST", post_planned_cents),
        ("MISC", misc_planned_cents),
    ):
        if planned is None:
            continue
        resp = api.create_budget_category(
            production["id"],
            create_budget_category_payload(code=code, planned_cents=planned),
            FC,
        )
        cats[code] = get_success_data(resp)
    return production, cats


def create_actor(api: ApiClient = api_client, **overrides) -> Dict[str, Any]:
    payload = create_actor_payload(**overrides)
    resp = api.create_actor(payload, CD)
    return get_success_data(resp)


# ─── Tier 2: Scene + Location + Reservation ──────────────────────────────────

def create_location(api: ApiClient = api_client, **overrides) -> Dict[str, Any]:
    payload = create_location_payload(**overrides)
    resp = api.create_location(payload, PC)
    return get_success_data(resp)


def create_scene_in_production(
    api: ApiClient = api_client,
    *,
    production_id: str,
    **overrides,
) -> Dict[str, Any]:
    payload = create_scene_payload(**overrides)
    resp = api.create_scene(production_id, payload, LP)
    return get_success_data(resp)


def create_held_reservation(
    api: ApiClient = api_client,
    *,
    location_id: str,
    production_id: str,
    scene_id: str,
    unit_label: str = "MAIN",
    start_at: Optional[str] = None,
    end_at: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """Create a LocationReservation in HELD state."""
    payload = create_location_reservation_payload(
        location_id=location_id,
        production_id=production_id,
        scene_id=scene_id,
        unit_label=unit_label,
        start_at=start_at or iso(2026, 2, 1, 9),
        end_at=end_at or iso(2026, 2, 1, 17),
        **overrides,
    )
    resp = api.create_location_reservation(payload, PC)
    return get_success_data(resp)


def confirm_reservation_with_permit_and_weather(
    api: ApiClient = api_client,
    *,
    reservation_id: str,
    needs_permit: bool = False,
    weather: str = "ACCEPTABLE",
) -> Dict[str, Any]:
    """Drive a HELD reservation to CONFIRMED by setting permit (if needed)
    and weather, then confirming."""
    if needs_permit:
        get_success_data(api.patch_permit_status(
            reservation_id, patch_permit_status_payload(permit_status="APPROVED"), PC,
        ))
    get_success_data(api.patch_weather_status(
        reservation_id, patch_weather_status_payload(weather_status=weather), PC,
    ))
    return get_success_data(api.confirm_reservation(reservation_id, PC))


# ─── Tier 3: Casting funnel walkthrough ──────────────────────────────────────

def create_role_in_production(
    api: ApiClient = api_client,
    *,
    production_id: str,
    **overrides,
) -> Dict[str, Any]:
    payload = create_role_payload(**overrides)
    resp = api.create_role(production_id, payload, CD)
    return get_success_data(resp)


def walk_role_to_offered(
    api: ApiClient = api_client,
    *,
    production_id: str,
    role_id: str,
    actor_id: str,
    audition_at: Optional[str] = None,
) -> Dict[str, Any]:
    """OPEN→AUDITIONING (record audition) →SHORTLISTED (shortlist) →OFFERED (offer).

    Records a PASS audition for the actor, shortlists the role, and offers it.
    Returns the role at OFFERED.
    """
    get_success_data(api.create_audition(
        production_id, role_id,
        create_audition_payload(
            actor_id=actor_id,
            audition_at=audition_at or iso(2026, 1, 15, 10),
            outcome="PASS",
        ),
        CD,
    ))
    get_success_data(api.shortlist_role(production_id, role_id, CD))
    return get_success_data(api.offer_role(
        production_id, role_id,
        offer_role_payload(actor_id=actor_id),
        CD,
    ))


def walk_role_to_signed(
    api: ApiClient = api_client,
    *,
    production_id: str,
    role_id: str,
    actor_id: str,
    audition_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Walk Role from OPEN through to SIGNED. Returns the SIGNED role."""
    walk_role_to_offered(
        api,
        production_id=production_id, role_id=role_id, actor_id=actor_id,
        audition_at=audition_at,
    )
    return get_success_data(api.sign_role(production_id, role_id, LP))


# ─── Tier 4: Threshold-targeting fixtures (Difficulty Design recipes) ────────

def setup_role_with_n_breakdown_scenes(
    api: ApiClient = api_client,
    *,
    n_breakdown_scenes: int = 3,
    n_shot_scenes: int = 0,
    scene_minutes: int = 480,
    role_union_tier: str = "SUPPORTING",
    role_day_rate_cents: int = 200_000,
    cast_planned_cents: int = 10_000_000,
    total_budget_cents: int = 200_000_000,
    reserve_fund_cents: int = 20_000_000,
    **production_overrides,
) -> Dict[str, Any]:
    """Setup for cast_commit_estimate testing.

    Creates Production (PLANNING), CAST budget category, one Role at OFFERED,
    and N scenes that reference the role. Optionally walks `n_shot_scenes` of
    them through to SHOT (so they are filtered out by at_sign_time variant).

    Returns dict {production, role, actor, scenes_breakdown, scenes_shot, cast_category}.
    """
    production, cats = setup_production_with_categories(
        api,
        total_budget_cents=total_budget_cents,
        reserve_fund_cents=reserve_fund_cents,
        cast_planned_cents=cast_planned_cents,
        crew_planned_cents=10_000_000,
        equipment_planned_cents=10_000_000,
        location_planned_cents=10_000_000,
        post_planned_cents=10_000_000,
        misc_planned_cents=10_000_000,
        **production_overrides,
    )

    role = create_role_in_production(
        api,
        production_id=production["id"],
        union_tier=role_union_tier,
        day_rate_cents=role_day_rate_cents,
    )
    actor = create_actor(api)

    # Create scenes_shot first (we'll walk them through SCHEDULED→SHOT below).
    scenes_shot: List[Dict[str, Any]] = []
    scenes_breakdown: List[Dict[str, Any]] = []

    for i in range(n_shot_scenes):
        scene = create_scene_in_production(
            api,
            production_id=production["id"],
            scene_number=f"S-shot-{i + 1}",
            planned_duration_minutes=scene_minutes,
            required_actor_role_ids=[role["id"]],
        )
        scenes_shot.append(scene)

    for i in range(n_breakdown_scenes):
        scene = create_scene_in_production(
            api,
            production_id=production["id"],
            scene_number=f"S-bd-{i + 1}",
            planned_duration_minutes=scene_minutes,
            required_actor_role_ids=[role["id"]],
        )
        scenes_breakdown.append(scene)

    # If any scenes_shot, walk them through SCHEDULED→SHOT via reservation+production lifecycle.
    if scenes_shot:
        location = create_location(api)
        # First, pre-walk the role to SIGNED so scene-schedule conflict checks have data,
        # but we want SHOT scenes BEFORE we sign for the test-of-interest. So instead
        # we don't sign; the conflict checks reference SIGNED actors and we have none yet.
        offset_min = 0
        for scene in scenes_shot:
            res = create_held_reservation(
                api,
                location_id=location["id"],
                production_id=production["id"],
                scene_id=scene["id"],
                unit_label=f"UNIT_{uuid.uuid4().hex[:6]}",
                start_at=iso(2026, 2, 1, 9, milli=0),
                end_at=add_minutes(iso(2026, 2, 1, 9, milli=0), scene_minutes),
            )
            confirm_reservation_with_permit_and_weather(
                api, reservation_id=res["id"], needs_permit=False,
            )
            get_success_data(api.schedule_scene(
                production["id"], scene["id"],
                schedule_scene_payload(reservation_id=res["id"]),
                LP,
            ))
            # To get to SHOT we'd need IN_PRODUCTION; do that by locking baseline.
            offset_min += scene_minutes + 60

        # Lock baseline to IN_PRODUCTION (preconditions: at least one scene SCHEDULED,
        # planned + reserve <= total budget). We have SCHEDULED scenes now.
        get_success_data(api.lock_baseline(production["id"], LP))

        # Now mark each scenes_shot as shot.
        for scene in scenes_shot:
            get_success_data(api.mark_shot(production["id"], scene["id"], PC))

    # Walk role OPEN→AUDITIONING→SHORTLISTED→OFFERED (don't sign yet).
    walk_role_to_offered(
        api,
        production_id=production["id"], role_id=role["id"], actor_id=actor["id"],
    )

    return {
        "production": production,
        "role": role,
        "actor": actor,
        "scenes_breakdown": scenes_breakdown,
        "scenes_shot": scenes_shot,
        "cast_category": cats["CAST"],
        "categories": cats,
    }


def setup_signed_role(
    api: ApiClient = api_client,
    *,
    n_breakdown_scenes: int = 2,
    role_union_tier: str = "SUPPORTING",
    role_day_rate_cents: int = 200_000,
    cast_planned_cents: int = 10_000_000,
) -> Dict[str, Any]:
    """Setup a Production with a SIGNED Role and N BREAKDOWN scenes that
    referenced it at sign time. Returns same dict shape as setup_role_with_n_breakdown_scenes
    plus the role re-fetched at SIGNED."""
    s = setup_role_with_n_breakdown_scenes(
        api,
        n_breakdown_scenes=n_breakdown_scenes,
        n_shot_scenes=0,
        scene_minutes=480,
        role_union_tier=role_union_tier,
        role_day_rate_cents=role_day_rate_cents,
        cast_planned_cents=cast_planned_cents,
    )
    signed = get_success_data(api.sign_role(s["production"]["id"], s["role"]["id"], LP))
    s["role"] = signed
    return s


# ─── Production lifecycle to WRAP_PENDING / WRAPPED ──────────────────────────

def setup_in_production(
    api: ApiClient = api_client,
    **kwargs,
) -> Dict[str, Any]:
    """Create Production + categories + Location + one Scene + one HELD/CONFIRMED
    reservation + schedule the scene + lock baseline. Returns dict with production,
    scene, reservation, location, and categories. Production ends up IN_PRODUCTION.
    """
    production, cats = setup_production_with_categories(api, **kwargs)
    location = create_location(api)
    scene = create_scene_in_production(
        api, production_id=production["id"],
        scene_number="S-baseline",
        planned_duration_minutes=120,
    )
    reservation = create_held_reservation(
        api,
        location_id=location["id"],
        production_id=production["id"],
        scene_id=scene["id"],
        start_at=iso(2026, 2, 1, 9),
        end_at=iso(2026, 2, 1, 11),
    )
    confirm_reservation_with_permit_and_weather(api, reservation_id=reservation["id"])
    get_success_data(api.schedule_scene(
        production["id"], scene["id"],
        schedule_scene_payload(reservation_id=reservation["id"]),
        LP,
    ))
    production = get_success_data(api.lock_baseline(production["id"], LP))
    return {
        "production": production,
        "scene": scene,
        "reservation": reservation,
        "location": location,
        "categories": cats,
    }


def setup_wrap_pending(
    api: ApiClient = api_client,
    *,
    crew_day_rate_cents: int = 33_333,
    crew_scheduled_days: int = 5,
    crew_actual_days: int = 11,
    total_budget_cents: int = 200_000_000,
    reserve_fund_cents: int = 20_000_000,
    cast_planned_cents: int = 10_000_000,
    crew_planned_cents: int = 10_000_000,
    equipment_planned_cents: int = 10_000_000,
    location_planned_cents: int = 10_000_000,
    post_planned_cents: int = 10_000_000,
    misc_planned_cents: int = 10_000_000,
    **production_overrides,
) -> Dict[str, Any]:
    """Walk a Production through PLANNING → IN_PRODUCTION → WRAP_PENDING.

    Order is critical: CrewAssignment is created before lock-baseline so that the
    baseline-lock cascade transitions BOOKED→ACTIVE. After IN_PRODUCTION the
    scene is marked SHOT, then begin-wrap takes the production to WRAP_PENDING.

    Returns dict {production, scene, reservation, crew_assignment, categories}.
    """
    production, cats = setup_production_with_categories(
        api,
        total_budget_cents=total_budget_cents,
        reserve_fund_cents=reserve_fund_cents,
        cast_planned_cents=cast_planned_cents,
        crew_planned_cents=crew_planned_cents,
        equipment_planned_cents=equipment_planned_cents,
        location_planned_cents=location_planned_cents,
        post_planned_cents=post_planned_cents,
        misc_planned_cents=misc_planned_cents,
        **production_overrides,
    )
    location = create_location(api)
    scene = create_scene_in_production(
        api, production_id=production["id"],
        scene_number="S-wrap",
        planned_duration_minutes=120,
    )
    reservation = create_held_reservation(
        api,
        location_id=location["id"],
        production_id=production["id"],
        scene_id=scene["id"],
        start_at=iso(2026, 2, 1, 9),
        end_at=iso(2026, 2, 1, 11),
    )
    confirm_reservation_with_permit_and_weather(api, reservation_id=reservation["id"])
    get_success_data(api.schedule_scene(
        production["id"], scene["id"],
        schedule_scene_payload(reservation_id=reservation["id"]),
        LP,
    ))

    # Create the CrewAssignment BEFORE baseline lock so it cascades BOOKED→ACTIVE.
    crew_resp = api.create_crew_assignment(
        production["id"],
        create_crew_assignment_payload(
            day_rate_cents=crew_day_rate_cents,
            scheduled_days=crew_scheduled_days,
        ),
        LP,
    )
    crew = get_success_data(crew_resp)

    # Now lock baseline → IN_PRODUCTION; cascade flips crew BOOKED→ACTIVE.
    production = get_success_data(api.lock_baseline(production["id"], LP))

    # Patch actual_days while IN_PRODUCTION (PRD §3.8).
    crew = get_success_data(api.patch_actual_days(
        production["id"], crew["id"],
        patch_actual_days_payload(actual_days=crew_actual_days),
        LP,
    ))

    # Mark scene shot to satisfy the begin-wrap precondition.
    get_success_data(api.mark_shot(production["id"], scene["id"], PC))

    # IN_PRODUCTION → WRAP_PENDING
    production = get_success_data(api.begin_wrap(production["id"], LP))

    return {
        "production": production,
        "scene": scene,
        "reservation": reservation,
        "location": location,
        "crew_assignment": crew,
        "categories": cats,
    }


# ─── Equipment lifecycle helpers ────────────────────────────────────────────

def create_equipment(api: ApiClient = api_client, **overrides) -> Dict[str, Any]:
    payload = create_equipment_payload(**overrides)
    resp = api.create_equipment(payload, PC)
    return get_success_data(resp)


def setup_equipment_checked_out(
    api: ApiClient = api_client,
    *,
    production_id: str,
    unit_cost_cents: int = 50_000,
    acquisition_mode: str = "RENTAL",
    vendor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Register an Equipment item, then CHECK_OUT it for the production.

    Production must already be in PLANNING or IN_PRODUCTION.
    Returns dict {equipment, check_out_event}.
    """
    equipment = create_equipment(
        api,
        unit_cost_cents=unit_cost_cents,
        acquisition_mode=acquisition_mode,
        vendor_id=vendor_id,
    )
    event = get_success_data(api.create_equipment_event(
        equipment["id"],
        create_equipment_event_payload(
            production_id=production_id,
            event_type="CHECK_OUT",
            occurred_at=iso(2026, 2, 1, 12),
            damage_charge_cents=0,
        ),
        PC,
    ))
    return {"equipment": equipment, "check_out_event": event}


def setup_equipment_lost(
    api: ApiClient = api_client,
    *,
    production_id: str,
    damage_charge_cents: int,
    vendor_id: Optional[str] = None,
    unit_cost_cents: int = 50_000,
) -> Dict[str, Any]:
    """Equipment in LOST state with damage_charge_cents recorded on REPORT_LOSS event.

    Path: AVAILABLE → CHECKED_OUT → LOST.
    Returns dict {equipment, check_out_event, loss_event}.
    """
    setup = setup_equipment_checked_out(
        api,
        production_id=production_id,
        unit_cost_cents=unit_cost_cents,
        vendor_id=vendor_id,
    )
    loss_event = get_success_data(api.create_equipment_event(
        setup["equipment"]["id"],
        create_equipment_event_payload(
            production_id=production_id,
            event_type="REPORT_LOSS",
            occurred_at=iso(2026, 2, 1, 13),
            damage_charge_cents=damage_charge_cents,
        ),
        PC,
    ))
    return {
        "equipment": setup["equipment"],
        "check_out_event": setup["check_out_event"],
        "loss_event": loss_event,
    }


def setup_equipment_damaged(
    api: ApiClient = api_client,
    *,
    production_id: str,
    damage_charge_cents: int,
    vendor_id: Optional[str] = None,
    unit_cost_cents: int = 50_000,
) -> Dict[str, Any]:
    setup = setup_equipment_checked_out(
        api,
        production_id=production_id,
        unit_cost_cents=unit_cost_cents,
        vendor_id=vendor_id,
    )
    damage_event = get_success_data(api.create_equipment_event(
        setup["equipment"]["id"],
        create_equipment_event_payload(
            production_id=production_id,
            event_type="REPORT_DAMAGE",
            occurred_at=iso(2026, 2, 1, 13),
            damage_charge_cents=damage_charge_cents,
        ),
        PC,
    ))
    return {
        "equipment": setup["equipment"],
        "check_out_event": setup["check_out_event"],
        "damage_event": damage_event,
    }


# ─── Re-read helpers ────────────────────────────────────────────────────────

def get_production(api: ApiClient = api_client, *, production_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_production(production_id, EXEC))


def get_categories_by_code(
    api: ApiClient = api_client, *, production_id: str,
) -> Dict[str, Dict[str, Any]]:
    """List budget categories and return dict keyed by code."""
    resp = api.list_budget_categories(production_id, FC, params={"limit": 100, "offset": 0})
    body = resp.json()
    cats = body["data"] if isinstance(body, dict) else []
    return {c["code"]: c for c in cats}
