"""Composite setup helpers — multi-step state builders used across the suite.

All helpers use get_success_data (lenient) so setup failures surface as clear
"Setup step failed" errors. Every helper builds state from scratch via
PRD-declared endpoints; the harness restarts the server before each test, so
nothing here may rely on state left behind by another test.
"""
from typing import Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    create_alarm_ticket_payload,
    create_capital_plan_payload,
    create_capital_project_payload,
    create_cleaning_payload,
    create_generator_test_payload,
    create_operator_payload,
    create_permit_payload,
    create_pump_payload,
    create_pump_rebuild_payload,
    create_runtime_reading_payload,
    create_spare_pump_payload,
    create_sso_event_payload,
    create_station_payload,
)
from .test_users import TEST_USERS, make_operator_headers

H_ADMIN = TEST_USERS["utility_admin_headers"]
H_SUPERVISOR = TEST_USERS["operations_supervisor_headers"]
H_ONCALL = TEST_USERS["on_call_operator_headers"]
H_OPERATOR = TEST_USERS["operator_headers"]
H_PLANNER = TEST_USERS["maintenance_planner_headers"]
H_COMPLIANCE = TEST_USERS["compliance_officer_headers"]
H_CPM = TEST_USERS["capital_program_manager_headers"]
H_SCADA = TEST_USERS["scada_webhook_headers"]
H_REGULATOR = TEST_USERS["regulator_portal_headers"]


# ---------------------------------------------------------------------------
# clock
# ---------------------------------------------------------------------------

def reset_clock(to_iso8601: str = DEFAULT_CLOCK_ISO) -> dict:
    """Pin the server logical clock (PRD §2.9)."""
    return get_success_data(api_client.set_clock(to_iso8601, H_ADMIN))


def tick() -> dict:
    """Advance the system tick; re-evaluates automatic transitions (PRD §2.9)."""
    return get_success_data(api_client.tick(H_ADMIN))


# ---------------------------------------------------------------------------
# stations / pumps / operators (Tier 1-2 building blocks)
# ---------------------------------------------------------------------------

def create_station(station_code: Optional[str] = None, service_zone: str = "Z1",
                   design_capacity_gpm: int = 300, pump_count: int = 2,
                   has_backup_generator: bool = False, wet_well_volume_gal: int = 2000,
                   ) -> dict:
    overrides = {}
    if station_code is not None:
        overrides["station_code"] = station_code
    payload = create_station_payload(
        service_zone=service_zone,
        design_capacity_gpm=design_capacity_gpm,
        pump_count=pump_count,
        has_backup_generator=has_backup_generator,
        wet_well_volume_gal=wet_well_volume_gal,
        **overrides,
    )
    return get_success_data(api_client.create_station(payload, H_ADMIN))


def get_station(station_id: str) -> dict:
    return get_success_data(api_client.get_station(station_id, H_ADMIN))


def add_pump(station_id: str, position_index: int, rated_gpm: int,
             status: str = "IN_SERVICE") -> dict:
    payload = create_pump_payload(
        station_id, position_index=position_index, rated_gpm=rated_gpm, status=status,
    )
    return get_success_data(api_client.create_pump(payload, H_ADMIN))


def get_pump(pump_id: str) -> dict:
    return get_success_data(api_client.get_pump(pump_id, H_ADMIN))


def setup_station_with_pumps(ratings: Sequence[int] = (150, 150),
                             design_capacity_gpm: int = 300,
                             has_backup_generator: bool = False,
                             service_zone: str = "Z1",
                             ) -> Tuple[dict, List[dict]]:
    """Station plus one IN_SERVICE pump per rating. Returns (station, pumps)."""
    station = create_station(
        service_zone=service_zone,
        design_capacity_gpm=design_capacity_gpm,
        pump_count=len(ratings),
        has_backup_generator=has_backup_generator,
    )
    pumps = [
        add_pump(station["id"], position_index=i + 1, rated_gpm=r)
        for i, r in enumerate(ratings)
    ]
    return station, pumps


def setup_normal_station(ratings: Sequence[int] = (150, 150, 150),
                         design_capacity_gpm: int = 300,
                         has_backup_generator: bool = False,
                         ) -> Tuple[dict, List[dict]]:
    """Station whose firm capacity (N-1 rule) meets design capacity, so its
    posture is NORMAL once the pumps are registered (PRD §2.7/§3.2)."""
    return setup_station_with_pumps(
        ratings=ratings,
        design_capacity_gpm=design_capacity_gpm,
        has_backup_generator=has_backup_generator,
    )


def add_operator(employee_code: Optional[str] = None, full_name: str = "Test Operator",
                 certifications: Sequence[str] = ("CSE_1", "COLLECTIONS_2"),
                 home_zone: str = "Z1") -> dict:
    overrides = {}
    if employee_code is not None:
        overrides["employee_code"] = employee_code
    payload = create_operator_payload(
        full_name=full_name, certifications=list(certifications), home_zone=home_zone,
        **overrides,
    )
    return get_success_data(api_client.create_operator(payload, H_ADMIN))


def get_operator(operator_id: str) -> dict:
    return get_success_data(api_client.get_operator(operator_id, H_ADMIN))


def add_reading(pump_id: str, recorded_at: str, run_hours_delta: float,
                starts_count: int = 1, source: str = "SCADA") -> dict:
    payload = create_runtime_reading_payload(
        recorded_at=recorded_at, run_hours_delta=run_hours_delta,
        starts_count=starts_count, source=source,
    )
    return get_success_data(
        api_client.create_runtime_reading(pump_id, payload, H_ADMIN),
    )


# ---------------------------------------------------------------------------
# alarm tickets (Tier 3 lifecycle)
# ---------------------------------------------------------------------------

def raise_ticket(station_id: str, alarm_class: str = "MINOR",
                 alarm_code: str = "HI_LEVEL", raised_at: str = DEFAULT_CLOCK_ISO,
                 is_sso_related: bool = False) -> dict:
    payload = create_alarm_ticket_payload(
        alarm_class=alarm_class, alarm_code=alarm_code, raised_at=raised_at,
        is_sso_related=is_sso_related,
    )
    return get_success_data(api_client.create_alarm_ticket(station_id, payload, H_SCADA))


def get_ticket(ticket_id: str) -> dict:
    return get_success_data(api_client.get_alarm_ticket(ticket_id, H_ONCALL))


def ack_ticket(ticket_id: str) -> dict:
    """OPEN -> ACKED; returns the refreshed ticket (with its new version)."""
    get_success_data(api_client.ack_alarm_ticket(ticket_id, H_ONCALL))
    return get_ticket(ticket_id)


def dispatch_ticket(ticket_id: str) -> dict:
    """ACKED -> DISPATCHED using the ticket's current version (OCC, PRD §2.6)."""
    current = get_ticket(ticket_id)
    return get_success_data(
        api_client.dispatch_alarm_ticket(ticket_id, current["version"], H_ONCALL),
    )


def arrive_ticket(ticket_id: str, operator_id: str) -> dict:
    return get_success_data(
        api_client.arrive_alarm_ticket(ticket_id, make_operator_headers(operator_id)),
    )


def clear_ticket(ticket_id: str, operator_id: str) -> dict:
    return get_success_data(
        api_client.clear_alarm_ticket(ticket_id, make_operator_headers(operator_id)),
    )


def setup_dispatched_ticket(alarm_class: str = "MINOR", is_sso_related: bool = False,
                            operator_home_zone: str = "Z1",
                            station: Optional[dict] = None,
                            ) -> Tuple[dict, dict, dict]:
    """Station + one callout-eligible operator + a ticket walked to DISPATCHED.

    Returns (station, winning_operator, ticket). The single created operator is
    the only eligible callout candidate, so it always wins the dispatch.
    """
    if station is None:
        station, _ = setup_station_with_pumps()
    operator = add_operator(home_zone=operator_home_zone)
    ticket = raise_ticket(station["id"], alarm_class=alarm_class,
                          is_sso_related=is_sso_related)
    ack_ticket(ticket["id"])
    dispatched = dispatch_ticket(ticket["id"])
    assert dispatched["assigned_operator_id"] == operator["id"], (
        "fixture invariant: sole eligible operator must win the callout"
    )
    return station, operator, dispatched


def setup_on_scene_ticket(**kwargs) -> Tuple[dict, dict, dict]:
    """Ticket walked to ON_SCENE. Returns (station, winning_operator, ticket)."""
    station, operator, ticket = setup_dispatched_ticket(**kwargs)
    ticket = arrive_ticket(ticket["id"], operator["id"])
    return station, operator, ticket


def setup_cleared_ticket(**kwargs) -> Tuple[dict, dict, dict]:
    """Ticket walked to CLEARED. Returns (station, winning_operator, ticket)."""
    station, operator, ticket = setup_on_scene_ticket(**kwargs)
    ticket = clear_ticket(ticket["id"], operator["id"])
    return station, operator, ticket


# ---------------------------------------------------------------------------
# pump rebuilds (Tier 3 lifecycle)
# ---------------------------------------------------------------------------

def open_rebuild(pump_id: str, work_order_ref: str = "WO-1",
                 started_at: str = DEFAULT_CLOCK_ISO, cost_usd: float = 10000.00) -> dict:
    """Open a PumpRebuild; drives the pump IN_SERVICE -> REBUILD (PRD §3.4)."""
    payload = create_pump_rebuild_payload(
        pump_id, work_order_ref=work_order_ref, started_at=started_at, cost_usd=cost_usd,
    )
    return get_success_data(api_client.create_pump_rebuild(payload, H_PLANNER))


def setup_completed_rebuild(pump_id: str) -> dict:
    """Rebuild walked OPEN -> IN_PROGRESS -> COMPLETED (pump back IN_SERVICE)."""
    rebuild = open_rebuild(pump_id)
    get_success_data(api_client.start_pump_rebuild(rebuild["id"], H_PLANNER))
    return get_success_data(api_client.complete_pump_rebuild(rebuild["id"], H_PLANNER))


# ---------------------------------------------------------------------------
# wet-well cleanings
# ---------------------------------------------------------------------------

def schedule_cleaning(station_id: str, crew_lead_operator_id: str,
                      scheduled_for: str = DEFAULT_CLOCK_ISO,
                      grease_depth_inches_pre: float = 4.0,
                      requires_confined_space_entry: bool = False) -> dict:
    payload = create_cleaning_payload(
        crew_lead_operator_id,
        scheduled_for=scheduled_for,
        grease_depth_inches_pre=grease_depth_inches_pre,
        requires_confined_space_entry=requires_confined_space_entry,
    )
    return get_success_data(
        api_client.create_wet_well_cleaning(station_id, payload, H_PLANNER),
    )


def get_cleaning(cleaning_id: str) -> dict:
    return get_success_data(api_client.get_cleaning(cleaning_id, H_ADMIN))


def complete_cleaning_now(cleaning_id: str, grease_depth_inches_post: float,
                          operator_id: Optional[str] = None) -> dict:
    """Start then complete a cleaning as an Operator (PRD §3.6)."""
    headers = make_operator_headers(operator_id) if operator_id else H_OPERATOR
    get_success_data(api_client.start_cleaning(cleaning_id, headers))
    return get_success_data(
        api_client.complete_cleaning(cleaning_id, grease_depth_inches_post, headers),
    )


def setup_completed_cleaning(station_id: str, crew_lead_operator_id: str,
                             scheduled_for: str, clock_at_work: str,
                             pre: float, post: float) -> dict:
    """A COMPLETED cleaning whose completed_at equals clock_at_work."""
    cleaning = schedule_cleaning(
        station_id, crew_lead_operator_id,
        scheduled_for=scheduled_for, grease_depth_inches_pre=pre,
    )
    reset_clock(clock_at_work)
    return complete_cleaning_now(cleaning["id"], post, operator_id=crew_lead_operator_id)


# ---------------------------------------------------------------------------
# generator tests
# ---------------------------------------------------------------------------

def schedule_generator_test(station_id: str, scheduled_for: str = DEFAULT_CLOCK_ISO,
                            test_kind: str = "NO_LOAD", load_percent: float = 0) -> dict:
    payload = create_generator_test_payload(
        scheduled_for=scheduled_for, test_kind=test_kind, load_percent=load_percent,
    )
    return get_success_data(
        api_client.create_generator_test(station_id, payload, H_PLANNER),
    )


def get_generator_test(test_id: str) -> dict:
    return get_success_data(api_client.get_generator_test(test_id, H_ADMIN))


def setup_running_generator_test(station_id: str, test_kind: str = "LOAD_BANK",
                                 scheduled_for: str = DEFAULT_CLOCK_ISO,
                                 load_percent: float = 80,
                                 operator_id: Optional[str] = None) -> dict:
    """GeneratorTest walked SCHEDULED -> RUNNING."""
    test = schedule_generator_test(
        station_id, scheduled_for=scheduled_for, test_kind=test_kind,
        load_percent=load_percent,
    )
    headers = make_operator_headers(operator_id) if operator_id else H_OPERATOR
    return get_success_data(api_client.start_generator_test(test["id"], headers))


# ---------------------------------------------------------------------------
# SSO events (Tier 3 lifecycle + Tier 5 terminal)
# ---------------------------------------------------------------------------

def create_sso(station_id: str, started_at: str = DEFAULT_CLOCK_ISO,
               cause_code: str = "GREASE_BLOCKAGE",
               reached_surface_water: bool = False) -> dict:
    """Record an SSO event; OCC version is re-read from the live station."""
    station = get_station(station_id)
    payload = create_sso_event_payload(
        station["version"], started_at=started_at, cause_code=cause_code,
        reached_surface_water=reached_surface_water,
    )
    return get_success_data(api_client.create_sso_event(station_id, payload, H_ADMIN))


def get_sso(sso_id: str) -> dict:
    return get_success_data(api_client.get_sso_event(sso_id, H_ADMIN))


def setup_sso_contained(station_id: str, started_at: str = DEFAULT_CLOCK_ISO,
                        contained_at: str = "2026-08-01T02:00:00Z",
                        cause_code: str = "GREASE_BLOCKAGE",
                        reached_surface_water: bool = False) -> dict:
    """SSO walked OPEN -> CONTAINED (provisional volume computed)."""
    sso = create_sso(station_id, started_at=started_at, cause_code=cause_code,
                     reached_surface_water=reached_surface_water)
    reset_clock(contained_at)
    return get_success_data(api_client.contain_sso_event(sso["id"], H_OPERATOR))


def setup_sso_report_draft(station_id: str, **kwargs) -> dict:
    sso = setup_sso_contained(station_id, **kwargs)
    return get_success_data(api_client.draft_sso_report(sso["id"], H_COMPLIANCE))


def setup_sso_submitted(station_id: str, submit_at: str = "2026-08-01T03:00:00Z",
                        **kwargs) -> dict:
    """SSO walked through REPORT_SUBMITTED (final volume variant computed)."""
    sso = setup_sso_report_draft(station_id, **kwargs)
    reset_clock(submit_at)
    return get_success_data(api_client.submit_sso_report(sso["id"], H_COMPLIANCE))


def setup_sso_accepted(station_id: str, **kwargs) -> dict:
    sso = setup_sso_submitted(station_id, **kwargs)
    return get_success_data(api_client.accept_sso_report(sso["id"], H_REGULATOR))


def setup_sso_closed(station_id: str, **kwargs) -> dict:
    """Full pipeline through CLOSED (terminal)."""
    sso = setup_sso_accepted(station_id, **kwargs)
    return get_success_data(api_client.close_sso_event(sso["id"], H_COMPLIANCE))


# ---------------------------------------------------------------------------
# confined-space permits (Tier 2 trio + Tier 3 lifecycle)
# ---------------------------------------------------------------------------

def create_permit_trio(home_zone: str = "Z1") -> Tuple[dict, dict, dict]:
    """Entrant (CSE_1), attendant (CSE_2), supervisor (CSE_1) — three distinct
    operators satisfying the segregation-of-duties rule (PRD §3.9)."""
    entrant = add_operator(full_name="Entrant", certifications=["CSE_1"],
                           home_zone=home_zone)
    attendant = add_operator(full_name="Attendant", certifications=["CSE_2"],
                             home_zone=home_zone)
    supervisor = add_operator(full_name="Supervisor",
                              certifications=["CSE_1", "COLLECTIONS_2"],
                              home_zone=home_zone)
    return entrant, attendant, supervisor


def create_draft_permit(station_id: str, entrant: dict, attendant: dict,
                        supervisor: dict, gas_test_passed: bool = True,
                        work_description: str = "wet well inspection") -> dict:
    payload = create_permit_payload(
        entrant["id"], attendant["id"], supervisor["id"],
        gas_test_passed=gas_test_passed, work_description=work_description,
    )
    return get_success_data(
        api_client.create_confined_space_permit(station_id, payload, H_SUPERVISOR),
    )


def get_permit(permit_id: str) -> dict:
    return get_success_data(api_client.get_permit(permit_id, H_ADMIN))


def issue_permit(permit_id: str, supervisor: dict) -> dict:
    """DRAFT -> ISSUED; only the named supervisor may issue (PRD §3.9)."""
    return get_success_data(
        api_client.issue_permit(permit_id, make_operator_headers(supervisor["id"])),
    )


def setup_issued_permit(station: Optional[dict] = None,
                        gas_test_passed: bool = True,
                        ) -> Tuple[dict, Tuple[dict, dict, dict], dict]:
    """Station + operator trio + an ISSUED permit. Returns (station, trio, permit)."""
    if station is None:
        station, _ = setup_station_with_pumps()
    trio = create_permit_trio(home_zone=station.get("service_zone", "Z1"))
    permit = create_draft_permit(station["id"], *trio, gas_test_passed=gas_test_passed)
    permit = issue_permit(permit["id"], trio[2])
    return station, trio, permit


def setup_active_permit(station: Optional[dict] = None) -> Tuple[dict, Tuple[dict, dict, dict], dict]:
    """Station + trio + an ACTIVE permit."""
    station, trio, permit = setup_issued_permit(station)
    permit = get_success_data(
        api_client.activate_permit(permit["id"], make_operator_headers(trio[2]["id"])),
    )
    return station, trio, permit


# ---------------------------------------------------------------------------
# capital plans & projects (Tier 3/5)
# ---------------------------------------------------------------------------

def create_plan(plan_year: int = 2090, budget_total_usd: float = 100000.00) -> dict:
    payload = create_capital_plan_payload(
        plan_year=plan_year, budget_total_usd=budget_total_usd,
    )
    return get_success_data(api_client.create_capital_plan(payload, H_CPM))


def get_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_capital_plan(plan_id, H_CPM))


def add_project(plan_id: str, station_id: str, project_name: str = "Project",
                estimated_cost_usd: float = 10000.00,
                consequence_of_failure: int = 5,
                likelihood_of_failure: int = 5) -> dict:
    payload = create_capital_project_payload(
        plan_id, station_id, project_name=project_name,
        estimated_cost_usd=estimated_cost_usd,
        consequence_of_failure=consequence_of_failure,
        likelihood_of_failure=likelihood_of_failure,
    )
    return get_success_data(api_client.create_capital_project(payload, H_CPM))


def get_project(project_id: str) -> dict:
    return get_success_data(api_client.get_capital_project(project_id, H_CPM))


def rank_plan(plan_id: str) -> dict:
    return get_success_data(api_client.rank_capital_plan(plan_id, H_CPM))


def approve_plan(plan_id: str) -> dict:
    """RANKED -> APPROVED using the plan's current version (OCC, PRD §2.6)."""
    current = get_plan(plan_id)
    return get_success_data(
        api_client.approve_capital_plan(plan_id, current["version"], H_ADMIN),
    )


def setup_ranked_plan(projects: Sequence[Tuple[str, float, int, int]] = (("A", 10000.00, 5, 5),),
                      plan_year: int = 2090, budget_total_usd: float = 100000.00,
                      ) -> Tuple[dict, dict, List[dict]]:
    """Plan + station + projects walked through DRAFT -> RANKED.

    `projects` is a sequence of (name, estimated_cost_usd, CoF, LoF) tuples.
    Returns (plan, station, projects).
    """
    station = create_station(has_backup_generator=True)
    plan = create_plan(plan_year=plan_year, budget_total_usd=budget_total_usd)
    rows = [
        add_project(plan["id"], station["id"], project_name=name,
                    estimated_cost_usd=cost, consequence_of_failure=c,
                    likelihood_of_failure=l)
        for name, cost, c, l in projects
    ]
    plan = rank_plan(plan["id"])
    return plan, station, rows


def setup_approved_plan(projects: Sequence[Tuple[str, float, int, int]] = (("A", 10000.00, 5, 5),),
                        plan_year: int = 2091, budget_total_usd: float = 100000.00,
                        ) -> Tuple[dict, dict, List[dict]]:
    """Plan walked DRAFT -> RANKED -> APPROVED. Returns (plan, station, projects)."""
    plan, station, rows = setup_ranked_plan(
        projects=projects, plan_year=plan_year, budget_total_usd=budget_total_usd,
    )
    plan = approve_plan(plan["id"])
    return plan, station, rows


# ---------------------------------------------------------------------------
# spare pumps
# ---------------------------------------------------------------------------

def create_spare(asset_tag: Optional[str] = None, rated_gpm: int = 200,
                 compatible_zone: str = "Z1") -> dict:
    overrides = {}
    if asset_tag is not None:
        overrides["asset_tag"] = asset_tag
    payload = create_spare_pump_payload(
        rated_gpm=rated_gpm, compatible_zone=compatible_zone, **overrides,
    )
    return get_success_data(api_client.create_spare_pump(payload, H_ADMIN))


def accumulate_runtime(pump_id: str, total_hours: float,
                       start_iso: str = DEFAULT_CLOCK_ISO) -> float:
    """Accumulate exactly `total_hours` of runtime on a pump via multiple
    readings, each within the 0..24h per-reading bound (PRD §3.2). Returns the
    total accumulated. Readings are spaced one hour apart to respect the
    chronological-order rule."""
    from datetime import datetime, timedelta

    base = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    remaining = total_hours
    i = 0
    while remaining > 0:
        delta = min(24.0, remaining)
        recorded = (base + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        add_reading(pump_id, recorded, delta)
        remaining -= delta
        i += 1
    return total_hours
