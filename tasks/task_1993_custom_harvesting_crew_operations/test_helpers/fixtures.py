"""Composite setup helpers.

Every test runs against an empty database, so each helper builds its
preconditions from scratch using only endpoints the PRD declares. Setup calls
use the lenient `get_success_data` validator so a broken precondition surfaces
as a clear "Setup step failed" rather than a confusing assertion later.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_contract_payload,
    create_crew_member_payload,
    create_delivery_ticket_payload,
    create_lodging_reservation_payload,
    create_lodging_site_payload,
    create_machine_assignment_payload,
    create_machine_payload,
    create_route_stop_payload,
    create_season_payload,
    issue_settlement_payload,
)
from .test_users import TEST_USERS

OPERATOR = TEST_USERS["harvest_operator_headers"]
LIAISON = TEST_USERS["grower_liaison_headers"]
BOSS = TEST_USERS["crew_boss_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------------------
# Tier 0 — primitive steps
# ---------------------------------------------------------------------------


def set_logical_clock(to_iso8601: str) -> Dict[str, Any]:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, OPERATOR))


def create_season(**overrides) -> Dict[str, Any]:
    """Create a HarvestSeason (starts in DRAFT)."""
    return get_success_data(api_client.create_season(create_season_payload(**overrides), OPERATOR))


def add_machine(season_id: str, **overrides) -> Dict[str, Any]:
    """Register a machine under a season (born AVAILABLE)."""
    return get_success_data(api_client.create_machine(season_id, create_machine_payload(**overrides), OPERATOR))


def activate_season(season_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.activate_season(season_id, OPERATOR))


def open_settlement_window(season_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.open_settlement(season_id, OPERATOR))


def create_contract(season_id: str, **overrides) -> Dict[str, Any]:
    """Create a CustomerContract (starts in DRAFT)."""
    return get_success_data(api_client.create_contract(season_id, create_contract_payload(**overrides), LIAISON))


def commit_contract(contract_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.commit_contract(contract_id, LIAISON))


def create_committed_contract(season_id: str, **overrides) -> Dict[str, Any]:
    contract = create_contract(season_id, **overrides)
    commit_contract(contract["id"])
    return get_contract(contract["id"])


def create_route_stop(contract_id: str, **overrides) -> Dict[str, Any]:
    """Create a RouteStop (starts SCHEDULED)."""
    return get_success_data(api_client.create_route_stop(contract_id, create_route_stop_payload(**overrides), LIAISON))


def reserve_machine(stop_id: str, machine_id: str, **overrides) -> Dict[str, Any]:
    """Create a MachineAssignment (starts RESERVED)."""
    payload = create_machine_assignment_payload(stop_id, machine_id, **overrides)
    return get_success_data(api_client.create_machine_assignment(payload, BOSS))


def cancel_assignment(assignment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.cancel_machine_assignment(assignment_id, BOSS))


def depart_stop(stop_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.depart_route_stop(stop_id, BOSS))


def start_cutting(stop_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.start_cutting(stop_id, BOSS))


def pause_stop(stop_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.pause_weather(stop_id, BOSS))


def resume_stop(stop_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.resume_route_stop(stop_id, BOSS))


def set_actual_acres(stop_id: str, actual_acres: float) -> Dict[str, Any]:
    return get_success_data(api_client.update_route_stop(stop_id, {"actual_acres": actual_acres}, BOSS))


def complete_stop(stop_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.complete_route_stop(stop_id, BOSS))


def skip_stop(stop_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.skip_route_stop(stop_id, OPERATOR))


def report_breakdown(machine_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.report_breakdown(machine_id, BOSS))


def dispatch_repair(machine_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.dispatch_repair(machine_id, OPERATOR))


def return_to_service(machine_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.return_to_service(machine_id, OPERATOR))


def post_delivery_ticket(stop_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_delivery_ticket(stop_id, create_delivery_ticket_payload(**overrides), BOSS))


def onboard_crew_member(season_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_crew_member(season_id, create_crew_member_payload(**overrides), OPERATOR))


def activate_crew(crew_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.activate_crew_member(crew_id, OPERATOR))


def onboard_active_crew(season_id: str, **overrides) -> Dict[str, Any]:
    member = onboard_crew_member(season_id, **overrides)
    activate_crew(member["id"])
    return get_crew_member(member["id"])


def add_lodging_site(season_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_lodging_site(season_id, create_lodging_site_payload(**overrides), OPERATOR))


def book_lodging(stop_id: str, crew_member_id: str, lodging_site_id: str, **overrides) -> Dict[str, Any]:
    payload = create_lodging_reservation_payload(crew_member_id, lodging_site_id, **overrides)
    return get_success_data(api_client.create_lodging_reservation(stop_id, payload, BOSS))


def create_draft_settlement(contract_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.create_settlement(contract_id, CLERK))


# ---------------------------------------------------------------------------
# Re-read helpers
# ---------------------------------------------------------------------------


def get_season(season_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_season(season_id, OPERATOR))


def get_contract(contract_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_contract(contract_id, CLERK))


def get_stop(stop_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_route_stop(stop_id, BOSS))


def get_machine(machine_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_machine(machine_id, OPERATOR))


def get_assignment(assignment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_machine_assignment(assignment_id, BOSS))


def get_crew_member(crew_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_crew_member(crew_id, OPERATOR))


def get_reservation(res_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_lodging_reservation(res_id, BOSS))


def get_ticket(ticket_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_delivery_ticket(ticket_id, BOSS))


def get_settlement(settlement_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_settlement(settlement_id, CLERK))


# ---------------------------------------------------------------------------
# Tier 1 — season setup
# ---------------------------------------------------------------------------


def create_active_season(num_combines: int = 1, **season_overrides) -> Dict[str, Any]:
    """DRAFT season + COMBINE machine(s) + activation. Returns a context dict."""
    season = create_season(**season_overrides)
    machines = [
        add_machine(season["id"], label=f"Combine-{i + 1:02d}")
        for i in range(num_combines)
    ]
    activated = activate_season(season["id"])
    return {"season": activated, "machines": machines, "machine": machines[0]}


# ---------------------------------------------------------------------------
# Tier 2 — route-stop progression
# ---------------------------------------------------------------------------


def drive_stop_to_en_route(stop_id: str, machine_id: str, **assignment_overrides) -> Dict[str, Any]:
    """Reserve the machine against the stop, then depart. Returns the EN_ROUTE stop."""
    reserve_machine(stop_id, machine_id, **assignment_overrides)
    return depart_stop(stop_id)


def drive_stop_to_cutting(stop_id: str, machine_id: str, **assignment_overrides) -> Dict[str, Any]:
    """Reserve + depart + start-cutting. Returns the CUTTING stop."""
    drive_stop_to_en_route(stop_id, machine_id, **assignment_overrides)
    return start_cutting(stop_id)


def setup_cutting_stop(
    planned_acres: float = 100,
    contract_overrides: Optional[Dict[str, Any]] = None,
    stop_overrides: Optional[Dict[str, Any]] = None,
    assignment_overrides: Optional[Dict[str, Any]] = None,
    season_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Active season + committed contract + one stop driven to CUTTING.

    Returns {"season", "machine", "contract", "stop"}.
    """
    ctx = create_active_season(**(season_overrides or {}))
    contract = create_committed_contract(ctx["season"]["id"], **(contract_overrides or {}))
    stop_kwargs: Dict[str, Any] = {"planned_acres": planned_acres}
    stop_kwargs.update(stop_overrides or {})
    stop = create_route_stop(contract["id"], **stop_kwargs)
    stop = drive_stop_to_cutting(stop["id"], ctx["machine"]["id"], **(assignment_overrides or {}))
    return {
        "season": ctx["season"],
        "machine": ctx["machine"],
        "machines": ctx["machines"],
        "contract": contract,
        "stop": stop,
    }


# ---------------------------------------------------------------------------
# Tier 3 — full harvest lifecycle shortcuts
# ---------------------------------------------------------------------------


def harvest_contract(
    season_id: str,
    machine_id: str,
    sequence_index: int = 1,
    actual_acres: float = 100,
    tickets: Optional[List[Dict[str, Any]]] = None,
    contract_overrides: Optional[Dict[str, Any]] = None,
    stop_overrides: Optional[Dict[str, Any]] = None,
    assignment_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Committed contract + one stop driven CUTTING -> COMPLETED.

    Posts each ticket spec in `tickets` while the stop is CUTTING. On return
    the parent contract is HARVESTED (its only stop is COMPLETED).
    Returns {"contract", "stop", "tickets"}.
    """
    contract = create_committed_contract(season_id, **(contract_overrides or {}))
    stop_kwargs: Dict[str, Any] = {"sequence_index": sequence_index}
    stop_kwargs.update(stop_overrides or {})
    stop = create_route_stop(contract["id"], **stop_kwargs)
    drive_stop_to_cutting(stop["id"], machine_id, **(assignment_overrides or {}))
    set_actual_acres(stop["id"], actual_acres)
    posted = [post_delivery_ticket(stop["id"], **spec) for spec in (tickets or [])]
    completed = complete_stop(stop["id"])
    return {"contract": contract, "stop": completed, "tickets": posted}


def setup_harvested_contract(
    season_overrides: Optional[Dict[str, Any]] = None,
    contract_overrides: Optional[Dict[str, Any]] = None,
    stop_overrides: Optional[Dict[str, Any]] = None,
    assignment_overrides: Optional[Dict[str, Any]] = None,
    actual_acres: float = 100,
    tickets: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Active season, one contract fully harvested (status HARVESTED).

    Returns {"season", "machine", "contract", "stop", "tickets"}.
    """
    ctx = create_active_season(**(season_overrides or {}))
    harvested = harvest_contract(
        ctx["season"]["id"],
        ctx["machine"]["id"],
        actual_acres=actual_acres,
        tickets=tickets,
        contract_overrides=contract_overrides,
        stop_overrides=stop_overrides,
        assignment_overrides=assignment_overrides,
    )
    return {
        "season": ctx["season"],
        "machine": ctx["machine"],
        "machines": ctx["machines"],
        "contract": harvested["contract"],
        "stop": harvested["stop"],
        "tickets": harvested["tickets"],
    }


# ---------------------------------------------------------------------------
# Tier 4 — settlement window and issuance
# ---------------------------------------------------------------------------


def issue_settlement_and_get(contract_id: str, settlement_id: str) -> Dict[str, Any]:
    """Read the contract's current version, then issue with that OCC value."""
    version = get_contract(contract_id)["version"]
    return get_success_data(
        api_client.issue_settlement(
            settlement_id, issue_settlement_payload(version), CLERK
        )
    )


def setup_settling_season_with_draft_settlement(**kwargs) -> Dict[str, Any]:
    """Harvested contract + season in SETTLING + a DRAFT settlement."""
    ctx = setup_harvested_contract(**kwargs)
    open_settlement_window(ctx["season"]["id"])
    settlement = create_draft_settlement(ctx["contract"]["id"])
    ctx["settlement"] = settlement
    ctx["season"] = get_season(ctx["season"]["id"])
    return ctx


def setup_issued_settlement(**kwargs) -> Dict[str, Any]:
    """Full pipeline through an ISSUED settlement. Returns ctx with 'settlement'."""
    ctx = setup_settling_season_with_draft_settlement(**kwargs)
    issued = issue_settlement_and_get(ctx["contract"]["id"], ctx["settlement"]["id"])
    ctx["settlement"] = issued
    return ctx
