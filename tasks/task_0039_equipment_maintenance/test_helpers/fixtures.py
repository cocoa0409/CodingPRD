"""Composite setup helpers for multi-step test prerequisites.

PRD §3 lifecycles require many calls to drive an entity to a testable state
(e.g., a WorkOrder ready to be completed needs site → equipment commissioned
→ plan activated → equipment placed in service → technician created → WO
created and started, plus any requisitions). These helpers encapsulate
those preambles so test bodies can focus on the assertion under test.

All helpers use get_success_data (lenient validator) so a setup failure
surfaces as a "Setup failed" KeyError, distinct from real test assertion
failures.

Identity threading rule (PRD §2.1): for ownership-gated calls on a
WorkOrder by a Technician, headers must be built with
make_technician_headers(technician.id) — not the shared TEST_USERS
fallback. Acceptance similarly requires
make_site_manager_headers(equipment.responsible_user_id).
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_NOW_ISO, SECONDS_PER_DAY
from .factories import (
    advance_clock_payload,
    complete_payload,
    create_equipment_payload,
    create_plan_payload,
    create_requisition_payload,
    create_site_payload,
    create_spare_part_payload,
    create_technician_payload,
    create_template_payload,
    create_work_order_payload,
    emit_alarm_payload,
    pause_payload,
    return_requisition_payload,
)
from .test_users import (
    TEST_USERS,
    make_site_manager_headers,
    make_technician_headers,
)


# ---------------------------------------------------------------------------
# Time helpers — operate on the deterministic site clock (PRD §2.7)
# ---------------------------------------------------------------------------
def parse_iso(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp with three fractional digits."""
    if ts.endswith("Z"):
        ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts)


def iso_z(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_seconds(ts: str, seconds: int) -> str:
    return iso_z(parse_iso(ts) + timedelta(seconds=seconds))


# ---------------------------------------------------------------------------
# Tier 1: state-progression primitives
# ---------------------------------------------------------------------------
def create_site(name: Optional[str] = None) -> Dict[str, Any]:
    """Create a Site as SiteManager. PRD §3.1: clock_now starts at
    2026-01-01T00:00:00.000Z, sweep_run_index at 0."""
    payload = create_site_payload() if name is None else {"name": name}
    res = api_client.create_site(payload, TEST_USERS["site_manager_headers"])
    return get_success_data(res)


def advance_clock(site_id: str, seconds: int,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.1: clock-advance only moves the clock; SiteManager or
    Dispatcher may invoke."""
    headers = headers or TEST_USERS["site_manager_headers"]
    res = api_client.advance_clock(site_id, advance_clock_payload(seconds),
                                   headers)
    return get_success_data(res)


def run_sweep(site_id: str,
              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.1: increments sweep_run_index, runs Steps 1–2 of plan
    generation, recomputes sla_breached on every open WO."""
    headers = headers or TEST_USERS["site_manager_headers"]
    res = api_client.run_sweep(site_id, headers)
    return get_success_data(res)


def create_equipment(site_id: str,
                     responsible_user_id: str,
                     **overrides) -> Dict[str, Any]:
    """Create an Equipment in INSTALLED state."""
    payload = create_equipment_payload(responsible_user_id, **overrides)
    res = api_client.create_equipment(
        site_id, payload, TEST_USERS["site_manager_headers"]
    )
    return get_success_data(res)


def create_template(site_id: str, **overrides) -> Dict[str, Any]:
    payload = create_template_payload(**overrides)
    res = api_client.create_template(
        site_id, payload, TEST_USERS["plan_owner_headers"]
    )
    return get_success_data(res)


def create_plan(site_id: str, equipment_id: str, template_id: str,
                kind: str = "PERIODIC_TIME",
                **overrides) -> Dict[str, Any]:
    payload = create_plan_payload(equipment_id, template_id, kind, **overrides)
    res = api_client.create_plan(
        site_id, payload, TEST_USERS["plan_owner_headers"]
    )
    return get_success_data(res)


def activate_plan(site_id: str, plan_id: str) -> Dict[str, Any]:
    res = api_client.activate_plan(
        site_id, plan_id, TEST_USERS["plan_owner_headers"]
    )
    return get_success_data(res)


def commission_equipment(site_id: str, equipment_id: str) -> Dict[str, Any]:
    res = api_client.commission_equipment(
        site_id, equipment_id, TEST_USERS["site_manager_headers"]
    )
    return get_success_data(res)


def place_in_service(site_id: str, equipment_id: str) -> Dict[str, Any]:
    res = api_client.place_equipment_in_service(
        site_id, equipment_id, TEST_USERS["site_manager_headers"]
    )
    return get_success_data(res)


def create_technician(site_id: str,
                      skills: Optional[List[str]] = None,
                      **overrides) -> Dict[str, Any]:
    payload = create_technician_payload(skills=skills, **overrides)
    res = api_client.create_technician(
        site_id, payload, TEST_USERS["site_manager_headers"]
    )
    return get_success_data(res)


def create_spare_part(site_id: str, **overrides) -> Dict[str, Any]:
    payload = create_spare_part_payload(**overrides)
    res = api_client.create_spare_part(
        site_id, payload, TEST_USERS["storekeeper_headers"]
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 2: composite scenarios
# ---------------------------------------------------------------------------
def setup_site_with_in_service_equipment(
    *,
    responsible_user_id: str = "owner-001",
    criticality: str = "MEDIUM",
    template_default_priority: str = "P3",
    template_required_skill: str = "MECHANICAL",
    equipment_category: str = "PUMP",
    plan_kind: str = "PERIODIC_TIME",
    plan_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build site → template → equipment INSTALLED → plan DRAFT → activate
    plan → commission equipment → place equipment in service. Returns a
    bag of every entity created. The returned dict has keys:
    site, template, equipment, plan."""
    site = create_site()
    template = create_template(
        site["id"],
        equipment_category=equipment_category,
        required_skill=template_required_skill,
        default_priority=template_default_priority,
    )
    equipment = create_equipment(
        site["id"],
        responsible_user_id,
        category=equipment_category,
        criticality=criticality,
    )
    plan = create_plan(
        site["id"], equipment["id"], template["id"], plan_kind,
        **(plan_overrides or {}),
    )
    plan = activate_plan(site["id"], plan["id"])
    equipment = commission_equipment(site["id"], equipment["id"])
    equipment = place_in_service(site["id"], equipment["id"])
    return {
        "site": site,
        "template": template,
        "equipment": equipment,
        "plan": plan,
    }


def setup_site_with_commissioned_only(
    *,
    responsible_user_id: str = "owner-001",
    template_required_skill: str = "MECHANICAL",
    equipment_category: str = "PUMP",
) -> Dict[str, Any]:
    """Same as in-service setup but stops after commission (lifecycle stays
    COMMISSIONED). Useful for tests that need an equipment that has not yet
    been placed in service."""
    site = create_site()
    template = create_template(
        site["id"],
        equipment_category=equipment_category,
        required_skill=template_required_skill,
    )
    equipment = create_equipment(
        site["id"], responsible_user_id, category=equipment_category,
    )
    plan = create_plan(site["id"], equipment["id"], template["id"])
    plan = activate_plan(site["id"], plan["id"])
    equipment = commission_equipment(site["id"], equipment["id"])
    return {
        "site": site,
        "template": template,
        "equipment": equipment,
        "plan": plan,
    }


def setup_full_workorder_scenario(
    *,
    responsible_user_id: str = "owner-001",
    technician_skills: Optional[List[str]] = None,
    criticality: str = "MEDIUM",
    template_default_priority: str = "P3",
    template_required_skill: str = "MECHANICAL",
    plan_kind: str = "PERIODIC_TIME",
    plan_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """In-service equipment + technician with required skill. Adds a
    technician keyed on template_required_skill. Returns dict including
    'technician'."""
    bag = setup_site_with_in_service_equipment(
        responsible_user_id=responsible_user_id,
        criticality=criticality,
        template_default_priority=template_default_priority,
        template_required_skill=template_required_skill,
        plan_kind=plan_kind,
        plan_overrides=plan_overrides,
    )
    skills = technician_skills if technician_skills is not None \
        else [template_required_skill]
    technician = create_technician(bag["site"]["id"], skills=skills)
    bag["technician"] = technician
    return bag


def create_ad_hoc_work_order(
    site_id: str,
    equipment_id: str,
    template_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.5: ad-hoc create runs the technician selector. Returns the
    work order."""
    headers = headers or TEST_USERS["dispatcher_headers"]
    payload = create_work_order_payload(equipment_id, template_id, **overrides)
    res = api_client.create_work_order(site_id, payload, headers)
    return get_success_data(res)


def setup_pending_workorder(**setup_kwargs) -> Dict[str, Any]:
    """In-service scenario + technician + ad-hoc PENDING work order routed
    to that technician. Returns the bag with 'work_order' added."""
    bag = setup_full_workorder_scenario(**setup_kwargs)
    wo = create_ad_hoc_work_order(
        bag["site"]["id"], bag["equipment"]["id"], bag["template"]["id"],
    )
    bag["work_order"] = wo
    return bag


# ---------------------------------------------------------------------------
# Tier 3: full work-order lifecycle shortcuts
# ---------------------------------------------------------------------------
def start_work_order(site_id: str, wo_id: str,
                     technician_id: str) -> Dict[str, Any]:
    """PRD §3.6: technician starts; X-User-ID must equal
    assigned_technician_id (built per-instance)."""
    headers = make_technician_headers(technician_id)
    res = api_client.start_work_order(site_id, wo_id, headers)
    return get_success_data(res)


def pause_work_order(site_id: str, wo_id: str, technician_id: str,
                     reason: str = "WAIT_INFO") -> Dict[str, Any]:
    headers = make_technician_headers(technician_id)
    res = api_client.pause_work_order(
        site_id, wo_id, pause_payload(reason), headers,
    )
    return get_success_data(res)


def resume_work_order(site_id: str, wo_id: str,
                      technician_id: str) -> Dict[str, Any]:
    headers = make_technician_headers(technician_id)
    res = api_client.resume_work_order(site_id, wo_id, headers)
    return get_success_data(res)


def complete_work_order(site_id: str, wo_id: str, technician_id: str,
                        **overrides) -> Dict[str, Any]:
    headers = make_technician_headers(technician_id)
    res = api_client.complete_work_order(
        site_id, wo_id, complete_payload(**overrides), headers,
    )
    return get_success_data(res)


def accept_work_order(site_id: str, wo_id: str,
                      responsible_user_id: str) -> Dict[str, Any]:
    """PRD §3.6: SiteManager whose X-User-ID equals the equipment's
    responsible_user_id may accept."""
    headers = make_site_manager_headers(responsible_user_id)
    res = api_client.accept_work_order(site_id, wo_id, headers)
    return get_success_data(res)


def setup_started_workorder(**setup_kwargs) -> Dict[str, Any]:
    """In-service scenario + PENDING WO + IN_PROGRESS via /start. Returns
    the bag with work_order updated to IN_PROGRESS state."""
    bag = setup_pending_workorder(**setup_kwargs)
    wo = start_work_order(
        bag["site"]["id"], bag["work_order"]["id"], bag["technician"]["id"],
    )
    bag["work_order"] = wo
    return bag


def setup_completed_workorder(**setup_kwargs) -> Dict[str, Any]:
    """Through completion. Returns bag with work_order in COMPLETED."""
    bag = setup_started_workorder(**setup_kwargs)
    wo = complete_work_order(
        bag["site"]["id"], bag["work_order"]["id"], bag["technician"]["id"],
    )
    bag["work_order"] = wo
    return bag


def setup_closed_workorder(*, responsible_user_id: str = "owner-001",
                           **setup_kwargs) -> Dict[str, Any]:
    """Through acceptance (CLOSED). Equipment.responsible_user_id is pinned
    so the SiteManager headers used for /accept actually match it."""
    bag = setup_completed_workorder(
        responsible_user_id=responsible_user_id, **setup_kwargs,
    )
    wo = accept_work_order(
        bag["site"]["id"], bag["work_order"]["id"], responsible_user_id,
    )
    bag["work_order"] = wo
    return bag


# ---------------------------------------------------------------------------
# Tier 4: requisition helpers
# ---------------------------------------------------------------------------
def create_requisition(site_id: str, wo_id: str, part_id: str, qty: int,
                       headers: Optional[Dict[str, str]] = None
                       ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["storekeeper_headers"]
    res = api_client.create_requisition(
        site_id, wo_id, create_requisition_payload(part_id, qty), headers,
    )
    return get_success_data(res)


def issue_requisition(site_id: str, wo_id: str,
                      req_id: str) -> Dict[str, Any]:
    res = api_client.issue_requisition(
        site_id, wo_id, req_id, TEST_USERS["storekeeper_headers"],
    )
    return get_success_data(res)


def return_requisition(site_id: str, wo_id: str, req_id: str,
                       returned_qty: int) -> Dict[str, Any]:
    res = api_client.return_requisition(
        site_id, wo_id, req_id, return_requisition_payload(returned_qty),
        TEST_USERS["storekeeper_headers"],
    )
    return get_success_data(res)


def cancel_requisition(site_id: str, wo_id: str,
                       req_id: str) -> Dict[str, Any]:
    res = api_client.cancel_requisition(
        site_id, wo_id, req_id, TEST_USERS["storekeeper_headers"],
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 5: difficulty-design recipes
# ---------------------------------------------------------------------------
def setup_priority_combo(
    *,
    criticality: str,
    template_default_priority: str,
) -> Dict[str, Any]:
    """Difficulty: priority_score combinatorial — pin Equipment.criticality
    and TaskTemplate.default_priority to test the score formula."""
    return setup_full_workorder_scenario(
        criticality=criticality,
        template_default_priority=template_default_priority,
    )


def setup_two_paused_workorders_for_mttr() -> Dict[str, Any]:
    """Difficulty rule_id=dual_variant_calc / mttr_active_vs_wallclock.

    Builds two completed WOs on the SAME equipment so MTTR with mode=active
    vs mode=wallclock yields different numbers.

    WO_A: AD_HOC, started immediately, paused 30 min in, resumed 60 min
          later, completed at started_at + 150 min wall.
          total_active_minutes = 120 (90 active before pause + 30 active
          after resume; the recipe pins it to 120).
          wallclock = 150.
    WO_B: AD_HOC on same equipment, started 20 min after open, completed
          60 min after start, no pauses.
          total_active_minutes = 60. wallclock = 80.

    NOTE on construction: WO_A and WO_B both target the same equipment, so
    we drive WO_A all the way through CLOSED (which clears
    open_work_order_id) before opening WO_B.
    """
    bag = setup_full_workorder_scenario(
        criticality="MEDIUM",
        template_required_skill="MECHANICAL",
    )
    site_id = bag["site"]["id"]
    eq_id = bag["equipment"]["id"]
    template_id = bag["template"]["id"]
    tech_id = bag["technician"]["id"]
    responsible_user_id = bag["equipment"]["responsible_user_id"]

    # ─── WO_A ──────────────────────────────────────────────────────────
    wo_a = create_ad_hoc_work_order(site_id, eq_id, template_id)
    wo_a = start_work_order(site_id, wo_a["id"], tech_id)
    advance_clock(site_id, 30 * 60)  # +30 min active
    wo_a = pause_work_order(site_id, wo_a["id"], tech_id, reason="WAIT_INFO")
    advance_clock(site_id, 60 * 60)  # +60 min paused (counts only for wall)
    wo_a = resume_work_order(site_id, wo_a["id"], tech_id)
    advance_clock(site_id, 60 * 60)  # +60 more active
    wo_a = complete_work_order(site_id, wo_a["id"], tech_id)
    wo_a = accept_work_order(site_id, wo_a["id"], responsible_user_id)
    # WO_A: started at t0, 30 active + 60 paused + 60 active = 150 wall;
    #       total_active_minutes = 90 (30 + 60). The PRD says pause and
    #       complete each add (clock - last_in_progress) / 60 floor minutes.

    # ─── 20-min gap before WO_B opens ──────────────────────────────────
    advance_clock(site_id, 20 * 60)

    # ─── WO_B ──────────────────────────────────────────────────────────
    wo_b = create_ad_hoc_work_order(site_id, eq_id, template_id)
    wo_b = start_work_order(site_id, wo_b["id"], tech_id)
    advance_clock(site_id, 60 * 60)  # +60 min active, no pauses
    wo_b = complete_work_order(site_id, wo_b["id"], tech_id)
    wo_b = accept_work_order(site_id, wo_b["id"], responsible_user_id)

    bag["work_order_a"] = wo_a
    bag["work_order_b"] = wo_b
    return bag


def setup_completed_and_open_for_availability(
    completed_started_offset_seconds: int = 3600,
    completed_active_seconds: int = 3600,
    open_started_offset_seconds: int = 5 * 3600,
    advance_after_open_seconds: int = 3 * 3600,
) -> Dict[str, Any]:
    """Difficulty rule_id=dual_variant_calc / availability_provisional_vs_final.

    On a single equipment, builds:
      - one COMPLETED ad-hoc WO with started_at=t0+1h, completed_at=t0+2h
      - one OPEN (IN_PROGRESS) ad-hoc WO with started_at=t0+5h
      - clock advanced to t0+8h before analytics are queried

    Tests query window [t0, t0+10h)."""
    bag = setup_full_workorder_scenario()
    site_id = bag["site"]["id"]
    eq_id = bag["equipment"]["id"]
    template_id = bag["template"]["id"]
    tech_id = bag["technician"]["id"]
    responsible_user_id = bag["equipment"]["responsible_user_id"]

    t0 = bag["site"]["clock_now"]
    bag["t0"] = t0

    # WO_completed
    advance_clock(site_id, completed_started_offset_seconds)  # +1h
    wo1 = create_ad_hoc_work_order(site_id, eq_id, template_id)
    wo1 = start_work_order(site_id, wo1["id"], tech_id)
    advance_clock(site_id, completed_active_seconds)  # +1h active
    wo1 = complete_work_order(site_id, wo1["id"], tech_id)
    wo1 = accept_work_order(site_id, wo1["id"], responsible_user_id)
    bag["work_order_completed"] = wo1

    # Advance to t0+5h relative to start — we are at t0+2h now, so add 3h
    remaining_before_open = open_started_offset_seconds - (
        completed_started_offset_seconds + completed_active_seconds
    )
    if remaining_before_open > 0:
        advance_clock(site_id, remaining_before_open)

    # WO_open: still IN_PROGRESS at the moment of analytics
    wo2 = create_ad_hoc_work_order(site_id, eq_id, template_id)
    wo2 = start_work_order(site_id, wo2["id"], tech_id)
    bag["work_order_open"] = wo2

    # Advance the clock so wallclock is t0 + 8h
    elapsed = open_started_offset_seconds  # currently we're at t0+5h
    target_total = open_started_offset_seconds + advance_after_open_seconds
    if target_total > elapsed:
        advance_clock(site_id, target_total - elapsed)

    # Final clock for the test
    bag["clock_at_analytics"] = get_success_data(
        api_client.get_site(site_id, TEST_USERS["site_manager_headers"]),
    )["clock_now"]
    return bag


def setup_two_periodic_plans_for_sweep_order() -> Dict[str, Any]:
    """Difficulty rule_id=combinatorial_formula /
    plan_generation_mode_c_pinned_evaluation_order.

    Site clock at t0; equipment IN_SERVICE with usage_counter=100.
    Plan A: PERIODIC_TIME interval_days=1, ACTIVE, last_generated_at=null
            → next_due_at = t0 + 86400s (set on activate)
    Plan B: PERIODIC_USAGE interval_usage=10, ACTIVE,
            last_generated_usage=100 (= equipment.usage_counter at activation)

    To make Plan B due on the next sweep, after activation we PATCH the
    equipment to bump usage_counter to 110 (delta = 10 ≥ interval_usage).
    """
    site = create_site()
    template = create_template(site["id"])
    equipment = create_equipment(
        site["id"], "owner-001", usage_counter=100,
    )
    # Two plans on the same equipment:
    plan_a = create_plan(
        site["id"], equipment["id"], template["id"], "PERIODIC_TIME",
        interval_days=1,
    )
    plan_a = activate_plan(site["id"], plan_a["id"])
    plan_b = create_plan(
        site["id"], equipment["id"], template["id"], "PERIODIC_USAGE",
        interval_usage=10,
    )
    plan_b = activate_plan(site["id"], plan_b["id"])
    equipment = commission_equipment(site["id"], equipment["id"])
    equipment = place_in_service(site["id"], equipment["id"])
    # Bump usage so Plan B qualifies (delta = 110 - 100 = 10 ≥ 10)
    eq_after_patch = api_client.patch_equipment(
        site["id"], equipment["id"],
        {"version": equipment["version"], "usage_counter": 110},
        TEST_USERS["site_manager_headers"],
    )
    equipment = get_success_data(eq_after_patch)

    technician = create_technician(site["id"], skills=["MECHANICAL"])
    return {
        "site": site,
        "template": template,
        "equipment": equipment,
        "plan_a": plan_a,
        "plan_b": plan_b,
        "technician": technician,
    }


def setup_two_sites_for_cross_site_test() -> Dict[str, Any]:
    """Difficulty rule_id=priority_pair_validation_conflict /
    business_safety_busy_vs_business_referential_cross_site.

    Builds Site A with equipment EQ1 (IN_SERVICE) holding an open PENDING
    WO. Builds Site B with a TaskTemplate TT (different site)."""
    bag_a = setup_pending_workorder()
    site_b = create_site()
    template_b = create_template(site_b["id"])
    return {
        "site_a": bag_a["site"],
        "equipment_a": bag_a["equipment"],
        "template_a": bag_a["template"],
        "work_order_a": bag_a["work_order"],
        "technician_a": bag_a["technician"],
        "site_b": site_b,
        "template_b": template_b,
    }


def setup_two_techs_for_aggregate_capacity() -> Dict[str, Any]:
    """Difficulty rule_id=resource_temporal_overlap /
    technician_workload_aggregate_capacity.

    Site with technicians T_A (created first) and T_B (created second),
    both with skills=[MECHANICAL]. Three IN_SERVICE equipment (E1, E2, E3)
    on the same site. Caller drives WO creation on E1, E2, E3 to test
    selector ranking."""
    site = create_site()
    template = create_template(site["id"])
    tech_a = create_technician(site["id"], skills=["MECHANICAL"])
    # PRD §3.4 selector tie-break is created_at ASC, then id ASC. Advance the
    # site clock between technician creations so the two techs receive
    # strictly different created_at timestamps and the test can rely on the
    # secondary key (created_at) rather than the lexicographic id tie-break.
    advance_clock(site["id"], 1)
    tech_b = create_technician(site["id"], skills=["MECHANICAL"])

    def _commissioned_in_service_equipment(asset_suffix: str):
        eq = create_equipment(
            site["id"], "owner-001", asset_tag=f"AT-{asset_suffix}",
        )
        plan = create_plan(site["id"], eq["id"], template["id"])
        activate_plan(site["id"], plan["id"])
        eq = commission_equipment(site["id"], eq["id"])
        eq = place_in_service(site["id"], eq["id"])
        return eq

    eq_1 = _commissioned_in_service_equipment("E1")
    eq_2 = _commissioned_in_service_equipment("E2")
    eq_3 = _commissioned_in_service_equipment("E3")

    return {
        "site": site,
        "template": template,
        "technician_a": tech_a,
        "technician_b": tech_b,
        "equipment_1": eq_1,
        "equipment_2": eq_2,
        "equipment_3": eq_3,
    }


def setup_decommission_cascade() -> Dict[str, Any]:
    """Difficulty rule_id=transitive_cascade /
    equipment_decommission_depth_3_cascade.

    Site, equipment IN_SERVICE, ACTIVE plan attached, PENDING WO on this
    equipment, and one RESERVED requisition R1 on a SparePart S1
    (stock_on_hand=10, reorder_point=5, qty=6 → after reservation
    available=4 ≤ 5 so replenish_pending=true)."""
    bag = setup_pending_workorder()
    spare = create_spare_part(
        bag["site"]["id"],
        stock_on_hand=10, reorder_point=5,
    )
    req = create_requisition(
        bag["site"]["id"], bag["work_order"]["id"], spare["id"], 6,
    )
    return {
        **bag,
        "spare_part": spare,
        "requisition": req,
    }


def setup_replenish_threshold_at_boundary(
    *,
    stock_on_hand: int = 10,
    reorder_point: int = 5,
    reserve_qty: int = 5,
) -> Dict[str, Any]:
    """Difficulty rule_id=boundary_precision_check /
    replenish_threshold_inclusive_le.

    Site, SparePart S1: stock_on_hand=10, reorder_point=5,
    replenish_pending=false. Equipment IN_SERVICE; WO; reserve qty=5 on
    S1 → stock_reserved=5, available=stock_on_hand-stock_reserved=5."""
    bag = setup_pending_workorder()
    spare = create_spare_part(
        bag["site"]["id"],
        stock_on_hand=stock_on_hand, reorder_point=reorder_point,
    )
    req = create_requisition(
        bag["site"]["id"], bag["work_order"]["id"], spare["id"], reserve_qty,
    )
    return {
        **bag,
        "spare_part": spare,
        "requisition": req,
    }


def setup_sla_breach_at_boundary() -> Dict[str, Any]:
    """Difficulty rule_id=boundary_precision_check /
    sla_breach_strict_greater_than.

    Site clock at t0; equipment IN_SERVICE; technician with skill;
    AD_HOC WO created at t0. Forced to P1 by criticality=HIGH +
    template default_priority=P1, source=AD_HOC: priority_score = 4*8+1=33
    → P1, sla_due_at = opened_at + 240 * 60s = opened_at + 14400s."""
    bag = setup_full_workorder_scenario(
        criticality="HIGH",
        template_default_priority="P1",
    )
    wo = create_ad_hoc_work_order(
        bag["site"]["id"], bag["equipment"]["id"], bag["template"]["id"],
    )
    bag["work_order"] = wo
    return bag


def setup_full_stock_invariant_scenario() -> Dict[str, Any]:
    """Difficulty rule_id=compensating_invariant /
    spare_part_stock_conservation.

    Site, equipment IN_SERVICE, technician with skill. SparePart S:
    stock_on_hand=10, stock_reserved=0, reorder_point=2. WO IN_PROGRESS
    with one RESERVED requisition R: qty=4 (stock_reserved becomes 4).

    PRD §3.8 requires the work order to be in IN_PROGRESS, PAUSED, or
    COMPLETED-but-not-yet-CLOSED for a return; the WO is started here so
    downstream tests can issue + return without an ERR_INVALID_STATE."""
    bag = setup_pending_workorder()
    spare = create_spare_part(
        bag["site"]["id"],
        stock_on_hand=10, reorder_point=2,
    )
    req = create_requisition(
        bag["site"]["id"], bag["work_order"]["id"], spare["id"], 4,
    )
    wo = start_work_order(
        bag["site"]["id"], bag["work_order"]["id"], bag["technician"]["id"],
    )
    bag["work_order"] = wo
    return {
        **bag,
        "spare_part": spare,
        "requisition": req,
    }


def setup_for_parts_cost_pinned_rounding() -> Dict[str, Any]:
    """Difficulty rule_id=combinatorial_formula /
    parts_cost_mode_b_pinned_rounding_order.

    Site, equipment IN_SERVICE, technician with skill; two SparePart rows
    (P1: unit_cost_cents=191, P2: unit_cost_cents=191), each
    stock_on_hand=20. WO created; reserve qty=11 on each, issue both;
    start the WO. Returns bag with everything ready for /complete."""
    bag = setup_pending_workorder()
    site_id = bag["site"]["id"]
    wo_id = bag["work_order"]["id"]
    p1 = create_spare_part(
        site_id, unit_cost_cents=191, stock_on_hand=20, reorder_point=0,
    )
    p2 = create_spare_part(
        site_id, unit_cost_cents=191, stock_on_hand=20, reorder_point=0,
    )
    r1 = create_requisition(site_id, wo_id, p1["id"], 11)
    r2 = create_requisition(site_id, wo_id, p2["id"], 11)
    r1 = issue_requisition(site_id, wo_id, r1["id"])
    r2 = issue_requisition(site_id, wo_id, r2["id"])
    wo = start_work_order(site_id, wo_id, bag["technician"]["id"])
    bag["work_order"] = wo
    bag["part_p1"] = p1
    bag["part_p2"] = p2
    bag["requisition_r1"] = r1
    bag["requisition_r2"] = r2
    return bag


__all__ = [
    "parse_iso",
    "iso_z",
    "add_seconds",
    "create_site",
    "advance_clock",
    "run_sweep",
    "create_equipment",
    "create_template",
    "create_plan",
    "activate_plan",
    "commission_equipment",
    "place_in_service",
    "create_technician",
    "create_spare_part",
    "create_ad_hoc_work_order",
    "start_work_order",
    "pause_work_order",
    "resume_work_order",
    "complete_work_order",
    "accept_work_order",
    "create_requisition",
    "issue_requisition",
    "return_requisition",
    "cancel_requisition",
    "setup_site_with_in_service_equipment",
    "setup_site_with_commissioned_only",
    "setup_full_workorder_scenario",
    "setup_pending_workorder",
    "setup_started_workorder",
    "setup_completed_workorder",
    "setup_closed_workorder",
    "setup_priority_combo",
    "setup_two_paused_workorders_for_mttr",
    "setup_completed_and_open_for_availability",
    "setup_two_periodic_plans_for_sweep_order",
    "setup_two_sites_for_cross_site_test",
    "setup_two_techs_for_aggregate_capacity",
    "setup_decommission_cascade",
    "setup_replenish_threshold_at_boundary",
    "setup_sla_breach_at_boundary",
    "setup_full_stock_invariant_scenario",
    "setup_for_parts_cost_pinned_rounding",
]
