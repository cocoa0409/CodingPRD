"""Composite setup helpers.

Every helper drives the public API only, uses `get_success_data()` so a broken
precondition surfaces as a setup failure, and starts from an empty database (the
harness restarts the server before each test, so nothing is carried over).

Reference geometry shared by all premise helpers
------------------------------------------------
Tower: `ground_elevation_m` 1200.0, `antenna_agl_m` 45.0 -> antenna 1245.0 m AMSL.
Premise: `premise_ground_elevation_m` 1210.0, `roof_height_m` 4.0,
`declared_tree_line_height_m` 3.0, `obstruction_class` CLEAR,
`path_distance_km` 5.0 -> desktop mast requirement 2.5 m, NON_PEN_ROOF_TRIPOD.
`SURVEY_PRESETS` below pairs measured heights with that same premise so a survey
lands in a chosen mounting band.
"""

from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START_UTC
from .factories import (
    close_outage_payload,
    completion_payload,
    create_backhaul_circuit_payload,
    create_coordination_payload,
    create_outage_credit_payload,
    create_outage_event_payload,
    create_sector_payload,
    create_service_plan_payload,
    create_serviceability_request_payload,
    create_spectrum_license_payload,
    create_subscriber_payload,
    create_tower_payload,
    create_work_order_payload,
    next_seq,
    survey_payload,
    usage_record_payload,
)
from .test_users import (
    BILLING_ADMIN,
    CAPACITY_PLANNER,
    FIELD_TECH,
    FINANCE_APPROVER,
    NETWORK_ENGINEER,
    SALES_AGENT,
    make_billing_admin_headers,
    make_field_tech_headers,
    make_finance_approver_headers,
    make_network_engineer_headers,
)

# Named operator identities. The two-person controls of PRD 2.11 compare
# `X-User-ID` values, so fixtures keep the surveyor, the deciding engineer, the
# credit preparer and the credit approver on four distinct identifiers.
SURVEYOR_USER_ID = "tech-surveyor-1"
DECIDING_ENGINEER_USER_ID = "eng-decider-1"
CREDIT_PREPARER_USER_ID = "billing-preparer-1"
CREDIT_APPROVER_USER_ID = "finance-approver-1"

SURVEYOR_HEADERS = make_field_tech_headers(SURVEYOR_USER_ID)
DECIDING_ENGINEER_HEADERS = make_network_engineer_headers(DECIDING_ENGINEER_USER_ID)
CREDIT_PREPARER_HEADERS = make_billing_admin_headers(CREDIT_PREPARER_USER_ID)
CREDIT_APPROVER_HEADERS = make_finance_approver_headers(CREDIT_APPROVER_USER_ID)


# --------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# --------------------------------------------------------------------------


def set_clock(to_iso8601: str, headers=None) -> dict:
    """Move the logical clock. Returns the response data (carries `current_utc`)."""
    return get_success_data(
        api_client.set_clock(to_iso8601, headers or NETWORK_ENGINEER)
    )


def reset_clock(headers=None) -> dict:
    """Return the logical clock to its startup reading of 2026-08-01T00:00:00Z."""
    return set_clock(CLOCK_START_UTC, headers)


# --------------------------------------------------------------------------
# Tier 0: single-call creators and readers
# --------------------------------------------------------------------------


def create_tower(headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_tower(create_tower_payload(**overrides), headers or NETWORK_ENGINEER)
    )


def get_tower(tower_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_tower(tower_id, headers or NETWORK_ENGINEER))


def change_tower_status(tower_id: str, to_status: str, reason=None, headers=None) -> dict:
    payload = {"to_status": to_status}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(
        api_client.change_tower_status(tower_id, payload, headers or NETWORK_ENGINEER)
    )


def create_backhaul_circuit(tower_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_backhaul_circuit(
            create_backhaul_circuit_payload(tower_id, **overrides), headers or NETWORK_ENGINEER
        )
    )


def change_circuit_state(circuit_id: str, to_state: str, headers=None, **extra) -> dict:
    payload = {"to_state": to_state}
    payload.update(extra)
    return get_success_data(
        api_client.change_circuit_state(circuit_id, payload, headers or NETWORK_ENGINEER)
    )


def create_accepted_circuit(tower_id: str, measured_mbps: float = 505.0, headers=None, **overrides) -> dict:
    """Order a circuit and walk it ORDERED -> INSTALLED -> ACCEPTED."""
    circuit = create_backhaul_circuit(tower_id, headers=headers, **overrides)
    change_circuit_state(circuit["id"], "INSTALLED", headers=headers)
    return change_circuit_state(
        circuit["id"], "ACCEPTED", headers=headers, measured_mbps=measured_mbps
    )


def create_spectrum_license(headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_spectrum_license(
            create_spectrum_license_payload(**overrides), headers or NETWORK_ENGINEER
        )
    )


def get_spectrum_license(license_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_spectrum_license(license_id, headers or NETWORK_ENGINEER)
    )


def create_sector(tower_id: str, spectrum_license_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_sector(
            create_sector_payload(tower_id, spectrum_license_id, **overrides),
            headers or NETWORK_ENGINEER,
        )
    )


def activate_sector(sector_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.activate_sector(sector_id, headers or NETWORK_ENGINEER)
    )


def get_sector(sector_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_sector(sector_id, headers or NETWORK_ENGINEER))


def change_capacity_policy(
    sector_id: str, max_oversubscription_ratio: float, justification: str = "Retuned by planning", headers=None
) -> dict:
    return get_success_data(
        api_client.change_capacity_policy(
            sector_id,
            {
                "max_oversubscription_ratio": max_oversubscription_ratio,
                "justification": justification,
            },
            headers or CAPACITY_PLANNER,
        )
    )


def create_service_plan(headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_service_plan(
            create_service_plan_payload(**overrides), headers or CAPACITY_PLANNER
        )
    )


def create_serviceability_request(tower_id: str, plan_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_serviceability_request(
            create_serviceability_request_payload(tower_id, plan_id, **overrides),
            headers or SALES_AGENT,
        )
    )


def get_serviceability_request(request_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_serviceability_request(request_id, headers or SALES_AGENT)
    )


def create_capacity_hold(
    request_id: str, expected_sector_version: int, hold_days=None, headers=None
) -> dict:
    payload = {
        "serviceability_request_id": request_id,
        "expected_sector_version": expected_sector_version,
    }
    if hold_days is not None:
        payload["hold_days"] = hold_days
    return get_success_data(
        api_client.create_capacity_hold(payload, headers or SALES_AGENT)
    )


def hold_for_request(request_id: str, hold_days=None, headers=None) -> dict:
    """Reserve for a QUALIFIED enquiry, reading the sector's current `version` first."""
    request = get_serviceability_request(request_id)
    sector = get_sector(request["qualified_sector_id"])
    return create_capacity_hold(
        request_id, sector["version"], hold_days=hold_days, headers=headers
    )


def get_capacity_hold(hold_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_capacity_hold(hold_id, headers or SALES_AGENT))


def release_capacity_hold(hold_id: str, note=None, headers=None) -> dict:
    payload = {"note": note} if note is not None else {}
    return get_success_data(
        api_client.release_capacity_hold(hold_id, payload, headers or CAPACITY_PLANNER)
    )


def create_subscriber(request_id: str, plan_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_subscriber(
            create_subscriber_payload(request_id, plan_id, **overrides), headers or SALES_AGENT
        )
    )


def get_subscriber(subscriber_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_subscriber(subscriber_id, headers or SALES_AGENT)
    )


def change_subscriber_status(subscriber_id: str, to_status: str, reason: str = "Ops request", headers=None) -> dict:
    return get_success_data(
        api_client.change_subscriber_status(
            subscriber_id, {"to_status": to_status, "reason": reason}, headers or BILLING_ADMIN
        )
    )


def change_subscriber_plan(
    subscriber_id: str, service_plan_id: str, expected_subscriber_version: int, headers=None
) -> dict:
    return get_success_data(
        api_client.change_subscriber_plan(
            subscriber_id,
            {
                "service_plan_id": service_plan_id,
                "expected_subscriber_version": expected_subscriber_version,
            },
            headers or SALES_AGENT,
        )
    )


def list_equipment_assignments(subscriber_id: str, headers=None, params=None) -> list:
    response = api_client.list_subscriber_equipment(
        subscriber_id, headers or BILLING_ADMIN, params=params
    )
    return get_success_data(response)


def get_assignment_for_subscriber(subscriber_id: str, headers=None) -> dict:
    """The per-account listing is the only discovery channel for the minted radio."""
    rows = list_equipment_assignments(subscriber_id, headers=headers)
    assert rows, f"Setup failed: no equipment assignment listed for account {subscriber_id}"
    return rows[0]


def get_equipment_assignment(assignment_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_equipment_assignment(assignment_id, headers or BILLING_ADMIN)
    )


def create_work_order(subscriber_id: str, scheduled_at=None, headers=None, **overrides) -> dict:
    payload = create_work_order_payload(subscriber_id, **overrides)
    if scheduled_at is not None:
        payload["scheduled_at"] = scheduled_at
    return get_success_data(
        api_client.create_work_order(payload, headers or FIELD_TECH)
    )


def get_work_order(work_order_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_work_order(work_order_id, headers or FIELD_TECH))


def survey_work_order(work_order_id: str, headers=None, **measurements) -> dict:
    """File the on-site survey. Defaults to the reference premise measurements
    (tree line 3.0 m, roof 4.0 m, penetration allowed) and is filed by
    SURVEYOR_HEADERS so a later exception decision by DECIDING_ENGINEER_HEADERS
    satisfies the two-person control."""
    return get_success_data(
        api_client.survey_work_order(
            work_order_id, survey_payload(**measurements), headers or SURVEYOR_HEADERS
        )
    )


def decide_exception(
    work_order_id: str,
    decision: str,
    note: str = "Engineering review complete",
    approved_mounting_type=None,
    headers=None,
) -> dict:
    payload = {"decision": decision, "note": note}
    if approved_mounting_type is not None:
        payload["approved_mounting_type"] = approved_mounting_type
    return get_success_data(
        api_client.decide_exception(work_order_id, payload, headers or DECIDING_ENGINEER_HEADERS)
    )


def reschedule_work_order(work_order_id: str, scheduled_at: str = "2026-08-09T15:00:00Z", headers=None) -> dict:
    return get_success_data(
        api_client.reschedule_work_order(
            work_order_id, {"scheduled_at": scheduled_at}, headers or FIELD_TECH
        )
    )


def complete_work_order(
    work_order_id: str, installed_mast_height_m: float = 2.5, radio_serial=None, headers=None
) -> dict:
    payload = completion_payload(installed_mast_height_m=installed_mast_height_m)
    if radio_serial is not None:
        payload["radio_serial"] = radio_serial
    return get_success_data(
        api_client.complete_work_order(work_order_id, payload, headers or FIELD_TECH)
    )


def ingest_usage(
    subscriber_id: str, usage_date: str, downstream_gb: float, upstream_gb: float = 0.0, headers=None
) -> dict:
    return get_success_data(
        api_client.create_usage_record(
            subscriber_id,
            usage_record_payload(usage_date, downstream_gb, upstream_gb),
            headers or BILLING_ADMIN,
        )
    )


def close_cycle(subscriber_id: str, headers=None) -> dict:
    return get_success_data(api_client.close_cycle(subscriber_id, headers or BILLING_ADMIN))


def create_outage(tower_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_outage_event(
            create_outage_event_payload(tower_id, **overrides), headers or NETWORK_ENGINEER
        )
    )


def close_outage(outage_id: str, ended_at=None, peak_wind_mph=None, headers=None) -> dict:
    payload = close_outage_payload()
    if ended_at is not None:
        payload["ended_at"] = ended_at
    if peak_wind_mph is not None:
        payload["peak_wind_mph"] = peak_wind_mph
    return get_success_data(
        api_client.close_outage_event(outage_id, payload, headers or NETWORK_ENGINEER)
    )


def get_outage(outage_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_outage_event(outage_id, headers or NETWORK_ENGINEER))


def prepare_credit(outage_id: str, subscriber_id: str, headers=None) -> dict:
    """Prepare a service-level credit as CREDIT_PREPARER_USER_ID."""
    return get_success_data(
        api_client.create_outage_credit(
            create_outage_credit_payload(outage_id, subscriber_id),
            headers or CREDIT_PREPARER_HEADERS,
        )
    )


def apply_credit(credit_id: str, note=None, headers=None) -> dict:
    """Apply a prepared credit as CREDIT_APPROVER_USER_ID (a different person
    from the preparer, per the two-person money control)."""
    payload = {"note": note} if note is not None else {}
    return get_success_data(
        api_client.apply_outage_credit(credit_id, payload, headers or CREDIT_APPROVER_HEADERS)
    )


def reverse_credit(credit_id: str, reversal_reason: str = "Posted in error", headers=None) -> dict:
    return get_success_data(
        api_client.reverse_outage_credit(
            credit_id, {"reversal_reason": reversal_reason}, headers or CREDIT_APPROVER_HEADERS
        )
    )


def get_credit(credit_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_outage_credit(credit_id, headers or BILLING_ADMIN))


def create_coordination(requesting_sector_id: str, neighbor_sector_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_coordination(
            create_coordination_payload(requesting_sector_id, neighbor_sector_id, **overrides),
            headers or NETWORK_ENGINEER,
        )
    )


def respond_to_coordination(coordination_id: str, decision: str, headers=None, **extra) -> dict:
    payload = {"decision": decision}
    payload.update(extra)
    return get_success_data(
        api_client.respond_to_coordination(coordination_id, payload, headers or NETWORK_ENGINEER)
    )


def revise_coordination(coordination_id: str, headers=None, **overrides) -> dict:
    from .factories import revision_payload

    return get_success_data(
        api_client.revise_coordination(
            coordination_id, revision_payload(**overrides), headers or NETWORK_ENGINEER
        )
    )


# --------------------------------------------------------------------------
# Survey measurement presets, all paired with the reference premise above.
#
# WALL_BRACKET            -> mast 1.0 m  -> SCHEDULED to MOUNT_APPROVED
# NON_PEN_ROOF_TRIPOD     -> mast 2.5 m  -> SCHEDULED to MOUNT_APPROVED
# ROOF_MAST_GUYED         -> mast 5.0 m  -> SCHEDULED to EXCEPTION_PENDING
# ROOF_MAST_GUYED_NO_PEN  -> mast 5.0 m, penetration refused -> RESURVEY_REQUIRED
# GROUND_POLE_MAST        -> mast 11.5 m -> SCHEDULED to EXCEPTION_PENDING
# MAST_LIMIT_EXCEEDED     -> mast 13.5 m -> SCHEDULED to SURVEY_FAILED
# NO_LINE_OF_SIGHT        -> margin -3.5 m -> SCHEDULED to SURVEY_FAILED
# --------------------------------------------------------------------------

SURVEY_PRESETS = {
    "WALL_BRACKET": {
        "measured_tree_line_height_m": 3.0,
        "measured_roof_height_m": 5.5,
        "structure_penetration_allowed": True,
    },
    "NON_PEN_ROOF_TRIPOD": {
        "measured_tree_line_height_m": 3.0,
        "measured_roof_height_m": 4.0,
        "structure_penetration_allowed": True,
    },
    "ROOF_MAST_GUYED": {
        "measured_tree_line_height_m": 5.5,
        "measured_roof_height_m": 4.0,
        "structure_penetration_allowed": True,
    },
    "ROOF_MAST_GUYED_NO_PEN": {
        "measured_tree_line_height_m": 5.5,
        "measured_roof_height_m": 4.0,
        "structure_penetration_allowed": False,
    },
    "GROUND_POLE_MAST": {
        "measured_tree_line_height_m": 12.0,
        "measured_roof_height_m": 4.0,
        "structure_penetration_allowed": True,
    },
    "MAST_LIMIT_EXCEEDED": {
        "measured_tree_line_height_m": 14.0,
        "measured_roof_height_m": 4.0,
        "structure_penetration_allowed": True,
    },
    "NO_LINE_OF_SIGHT": {
        "measured_tree_line_height_m": 35.0,
        "measured_roof_height_m": 4.0,
        "structure_penetration_allowed": True,
    },
}


# --------------------------------------------------------------------------
# Tier 1/2: plant with transport, licence, sector and a published plan
# --------------------------------------------------------------------------


def setup_active_plant(
    tower_overrides=None,
    circuit_overrides=None,
    license_overrides=None,
    sector_overrides=None,
    plan_overrides=None,
    activate_tower: bool = True,
    activate_the_sector: bool = True,
    measured_mbps: float = 505.0,
) -> dict:
    """Tower with an ACCEPTED circuit, an ACTIVE tower status, a licence, a sector
    (ACTIVE by default) and one published plan.

    Returns {"tower", "circuit", "license", "sector", "plan"}; every value is the
    freshest representation the setup calls returned.
    """
    tower = create_tower(**(tower_overrides or {}))
    circuit = create_accepted_circuit(
        tower["id"], measured_mbps=measured_mbps, **(circuit_overrides or {})
    )
    if activate_tower:
        tower = change_tower_status(tower["id"], "ACTIVE")
    license_ = create_spectrum_license(**(license_overrides or {}))
    sector = create_sector(tower["id"], license_["id"], **(sector_overrides or {}))
    if activate_the_sector:
        sector = activate_sector(sector["id"])
        tower = get_tower(tower["id"])
    plan = create_service_plan(**(plan_overrides or {}))
    return {
        "tower": tower,
        "circuit": circuit,
        "license": license_,
        "sector": sector,
        "plan": plan,
    }


def setup_planned_plant(**kwargs) -> dict:
    """Same plant, but the tower stays PLANNED and the sector stays PLANNED."""
    kwargs.setdefault("activate_tower", False)
    kwargs.setdefault("activate_the_sector", False)
    return setup_active_plant(**kwargs)


def setup_qualified_request(scenario=None, request_overrides=None, **plant_kwargs) -> dict:
    """Active plant + one enquiry qualified against its sector.

    Returns the scenario dict with a "request" key added.
    """
    scenario = scenario or setup_active_plant(**plant_kwargs)
    request = create_serviceability_request(
        scenario["tower"]["id"], scenario["plan"]["id"], **(request_overrides or {})
    )
    scenario["request"] = request
    return scenario


def setup_held_reservation(scenario=None, hold_days=None, **kwargs) -> dict:
    """Active plant + QUALIFIED enquiry + a HELD reservation for it.

    Returns the scenario dict with "request", "hold" and a refreshed "sector".
    """
    scenario = scenario or setup_qualified_request(**kwargs)
    if "request" not in scenario:
        scenario = setup_qualified_request(scenario, **kwargs)
    hold = hold_for_request(scenario["request"]["id"], hold_days=hold_days)
    scenario["hold"] = hold
    scenario["sector"] = get_sector(scenario["sector"]["id"])
    return scenario


def setup_pending_install_subscriber(scenario=None, equipment_mode: str = "RENTAL", **kwargs) -> dict:
    """Active plant + consumed reservation + a PENDING_INSTALL account and the
    equipment record minted alongside it.

    Returns the scenario dict with "subscriber", "assignment" and refreshed
    "sector", "request" and "hold".
    """
    scenario = scenario or setup_held_reservation(**kwargs)
    if "hold" not in scenario:
        scenario = setup_held_reservation(scenario, **kwargs)
    subscriber = create_subscriber(
        scenario["request"]["id"], scenario["plan"]["id"], equipment_mode=equipment_mode
    )
    scenario["subscriber"] = subscriber
    scenario["assignment"] = get_assignment_for_subscriber(subscriber["id"])
    scenario["sector"] = get_sector(scenario["sector"]["id"])
    scenario["request"] = get_serviceability_request(scenario["request"]["id"])
    scenario["hold"] = get_capacity_hold(scenario["hold"]["id"])
    return scenario


def setup_scheduled_work_order(scenario=None, scheduled_at="2026-08-02T15:00:00Z", **kwargs) -> dict:
    """PENDING_INSTALL account + one SCHEDULED truck roll."""
    scenario = scenario or setup_pending_install_subscriber(**kwargs)
    if "subscriber" not in scenario:
        scenario = setup_pending_install_subscriber(scenario, **kwargs)
    scenario["work_order"] = create_work_order(
        scenario["subscriber"]["id"], scheduled_at=scheduled_at
    )
    return scenario


def setup_work_order_in_state(target_status: str, scenario=None, **kwargs) -> dict:
    """Drive one truck roll to `target_status` using the survey presets.

    Supported targets: SCHEDULED, MOUNT_APPROVED, EXCEPTION_PENDING,
    RESURVEY_REQUIRED, SURVEY_FAILED, INSTALLED.
    """
    scenario = scenario or setup_scheduled_work_order(**kwargs)
    if "work_order" not in scenario:
        scenario = setup_scheduled_work_order(scenario, **kwargs)
    work_order_id = scenario["work_order"]["id"]

    if target_status == "SCHEDULED":
        return scenario
    if target_status == "MOUNT_APPROVED":
        scenario["work_order"] = survey_work_order(
            work_order_id, **SURVEY_PRESETS["NON_PEN_ROOF_TRIPOD"]
        )
        return scenario
    if target_status == "EXCEPTION_PENDING":
        scenario["work_order"] = survey_work_order(
            work_order_id, **SURVEY_PRESETS["ROOF_MAST_GUYED"]
        )
        return scenario
    if target_status == "RESURVEY_REQUIRED":
        scenario["work_order"] = survey_work_order(
            work_order_id, **SURVEY_PRESETS["ROOF_MAST_GUYED_NO_PEN"]
        )
        return scenario
    if target_status == "SURVEY_FAILED":
        scenario["work_order"] = survey_work_order(
            work_order_id, **SURVEY_PRESETS["MAST_LIMIT_EXCEEDED"]
        )
        return scenario
    if target_status == "INSTALLED":
        scenario["work_order"] = survey_work_order(
            work_order_id, **SURVEY_PRESETS["NON_PEN_ROOF_TRIPOD"]
        )
        scenario["work_order"] = complete_work_order(work_order_id, installed_mast_height_m=2.5)
        scenario["subscriber"] = get_subscriber(scenario["subscriber"]["id"])
        scenario["assignment"] = get_assignment_for_subscriber(scenario["subscriber"]["id"])
        return scenario
    raise AssertionError(f"Setup failed: unsupported work order target status {target_status!r}")


def setup_active_subscriber(scenario=None, equipment_mode: str = "RENTAL", **kwargs) -> dict:
    """Full activation chain: install completed, account ACTIVE, radio DEPLOYED.

    Returns the scenario dict with "work_order" (INSTALLED), a refreshed
    "subscriber" (ACTIVE) and "assignment" (DEPLOYED).
    """
    if scenario is None:
        scenario = setup_scheduled_work_order(equipment_mode=equipment_mode, **kwargs)
    return setup_work_order_in_state("INSTALLED", scenario)


# --------------------------------------------------------------------------
# Clock arithmetic helpers (the logical clock is the only "now" there is)
# --------------------------------------------------------------------------


def iso_shift(instant: str, days: int = 0, hours: int = 0, minutes: int = 0) -> str:
    """Return `instant` moved by the given offset, in the same Z-suffixed form."""
    base = datetime.strptime(instant, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    moved = base + timedelta(days=days, hours=hours, minutes=minutes)
    return moved.strftime("%Y-%m-%dT%H:%M:%SZ")


def advance_clock(days: int = 0, hours: int = 0, minutes: int = 0, headers=None) -> str:
    """Move the clock forward from its startup reading and return the new instant."""
    target = iso_shift(CLOCK_START_UTC, days=days, hours=hours, minutes=minutes)
    set_clock(target, headers)
    return target


# --------------------------------------------------------------------------
# Tier 0 (continued): equipment close-out
# --------------------------------------------------------------------------


def return_equipment(assignment_id: str, return_condition: str = "GOOD", headers=None) -> dict:
    return get_success_data(
        api_client.return_equipment(
            assignment_id, {"return_condition": return_condition}, headers or FIELD_TECH
        )
    )


def settle_unreturned_equipment(assignment_id: str, note=None, headers=None) -> dict:
    payload = {"note": note} if note is not None else {}
    return get_success_data(
        api_client.settle_unreturned_equipment(assignment_id, payload, headers or BILLING_ADMIN)
    )


# --------------------------------------------------------------------------
# Tier 4: driving a sector's ledger to a chosen posture
#
# The reference sector is `capacity_mbps` 25 with `max_oversubscription_ratio`
# 8.0, so its ceiling is floor(25 * 8.0) = 200 Mbps and the watch, withhold and
# freeze lines sit at ratios 4.0, 6.0 and 8.0 -- that is, at 100, 150 and 200
# committed Mbps.
# --------------------------------------------------------------------------


def reserve_bandwidth(scenario: dict, mbps: int, hold_days=None) -> dict:
    """Take `mbps` of the sector's allowance through the front door: publish a plan
    of that size, qualify a fresh enquiry against the tower, and reserve.

    Appends {"plan", "request", "hold"} to `scenario["reservations"]` and returns
    that entry. `scenario["sector"]` is refreshed.
    """
    plan = create_service_plan(downstream_mbps=mbps, upstream_mbps=max(1, mbps // 5))
    request = create_serviceability_request(scenario["tower"]["id"], plan["id"])
    hold = hold_for_request(request["id"], hold_days=hold_days)
    entry = {"plan": plan, "request": request, "hold": hold}
    scenario.setdefault("reservations", []).append(entry)
    scenario["sector"] = get_sector(scenario["sector"]["id"])
    return entry


def setup_sector_at_watch(scenario=None, **kwargs) -> dict:
    """Reference sector carrying 100 committed Mbps: ratio exactly 4.0, which is
    exactly half of the 8.0 ceiling, so the posture sits on the watch line."""
    scenario = scenario or setup_active_plant(**kwargs)
    reserve_bandwidth(scenario, 100)
    return scenario


def setup_sector_at_hold(scenario=None, **kwargs) -> dict:
    """Reference sector carrying 150 committed Mbps: ratio exactly 6.0, which is
    exactly three-quarters of the 8.0 ceiling, so the posture is HOLD."""
    scenario = scenario or setup_active_plant(**kwargs)
    reserve_bandwidth(scenario, 150)
    return scenario


def setup_sector_frozen_by_ceiling(scenario=None, **kwargs) -> dict:
    """Reference sector carrying 100 committed Mbps, then retuned to a ceiling of
    4.0 so the ratio lands exactly on the freeze line."""
    scenario = scenario or setup_active_plant(**kwargs)
    reserve_bandwidth(scenario, 100)
    scenario["sector"] = change_capacity_policy(
        scenario["sector"]["id"], 4.0, justification="Tightened to the current commitments"
    )
    return scenario


def setup_sector_frozen_by_backhaul(scenario=None, **kwargs) -> dict:
    """Degrade the tower's only accepted circuit, which drops
    `backhaul_accepted_mbps` to zero and freezes every sector on the tower."""
    scenario = scenario or setup_active_plant(**kwargs)
    scenario["circuit"] = change_circuit_state(scenario["circuit"]["id"], "DEGRADED")
    scenario["sector"] = get_sector(scenario["sector"]["id"])
    scenario["tower"] = get_tower(scenario["tower"]["id"])
    return scenario


def setup_transport_limited_sector(scenario=None) -> dict:
    """A sector below its own watch line but pushed into HOLD by transport: a
    10 Mbps circuit with 120 committed Mbps gives an air ratio of 4.8 (provisional
    WATCH) and a transport ratio of exactly 12.0."""
    scenario = scenario or setup_active_plant(
        circuit_overrides={"committed_mbps": 10}, measured_mbps=10.0
    )
    reserve_bandwidth(scenario, 120)
    return scenario


def setup_deferred_request(scenario=None, plan_mbps: int = 50, **kwargs) -> dict:
    """A sector in HOLD plus one enquiry that was excluded only by that posture, so
    it lands in CAPACITY_DEFERRED and waits in the promotion queue.

    Adds "deferred_plan" and "deferred_request" to the scenario.
    """
    scenario = scenario or setup_sector_at_hold(**kwargs)
    plan = create_service_plan(downstream_mbps=plan_mbps, upstream_mbps=max(1, plan_mbps // 5))
    request = create_serviceability_request(scenario["tower"]["id"], plan["id"])
    scenario["deferred_plan"] = plan
    scenario["deferred_request"] = request
    return scenario


def setup_lapsed_hold(scenario=None, hold_days: int = 1, **kwargs) -> dict:
    """A reservation whose `expires_at` the clock has passed. Lapse is lazy, so the
    scenario also re-reads the sector, which is what settles it.
    """
    scenario = scenario or setup_qualified_request(**kwargs)
    if "request" not in scenario:
        scenario = setup_qualified_request(scenario, **kwargs)
    hold = hold_for_request(scenario["request"]["id"], hold_days=hold_days)
    advance_clock(days=hold_days + 1)
    scenario["hold"] = get_capacity_hold(hold["id"])
    scenario["sector"] = get_sector(scenario["sector"]["id"])
    scenario["request"] = get_serviceability_request(scenario["request"]["id"])
    return scenario


# --------------------------------------------------------------------------
# Tier 5: cancellation and hardware close-out
# --------------------------------------------------------------------------


def cancel_subscriber(subscriber_id: str, reason: str = "Customer moved away", headers=None) -> dict:
    return change_subscriber_status(subscriber_id, "CANCELLED", reason=reason, headers=headers)


def setup_return_pending_assignment(
    equipment_mode: str = "RENTAL", months_in_service: int = 0, scenario=None, **kwargs
) -> dict:
    """An ACTIVE account cancelled with the radio still on the wall, so its
    equipment record sits in RETURN_PENDING with a 21-day `return_due_at`.

    `months_in_service` advances the clock by that many 30-day settlement months
    between deployment and cancellation, which is what the settlement tenure reads.
    """
    scenario = scenario or setup_active_subscriber(equipment_mode=equipment_mode, **kwargs)
    if months_in_service:
        advance_clock(days=30 * months_in_service)
    scenario["subscriber"] = cancel_subscriber(scenario["subscriber"]["id"])
    scenario["assignment"] = get_assignment_for_subscriber(scenario["subscriber"]["id"])
    scenario["sector"] = get_sector(scenario["sector"]["id"])
    return scenario


def setup_voided_assignment(scenario=None, **kwargs) -> dict:
    """A PENDING_INSTALL account cancelled before any radio was deployed, so its
    equipment record is VOIDED rather than awaiting a return."""
    scenario = scenario or setup_pending_install_subscriber(**kwargs)
    scenario["subscriber"] = cancel_subscriber(scenario["subscriber"]["id"])
    scenario["assignment"] = get_assignment_for_subscriber(scenario["subscriber"]["id"])
    return scenario


def setup_write_off_ready_assignment(
    equipment_mode: str = "RENTAL", months_in_service: int = 0, scenario=None, **kwargs
) -> dict:
    """A RETURN_PENDING record whose 21-day return window has closed, so the
    unreturned write-off is admissible."""
    scenario = setup_return_pending_assignment(
        equipment_mode=equipment_mode, months_in_service=months_in_service, scenario=scenario, **kwargs
    )
    assignment = scenario["assignment"]
    set_clock(assignment["return_due_at"])
    scenario["assignment"] = get_equipment_assignment(assignment["id"])
    return scenario


# --------------------------------------------------------------------------
# Tier 5: outages and service-level credits
# --------------------------------------------------------------------------


def setup_closed_outage(
    scenario=None,
    minutes: int = 240,
    cause: str = "POWER",
    started_at: str = "2026-08-05T02:00:00Z",
    peak_wind_mph=None,
    planned_notice_days=None,
    **kwargs,
) -> dict:
    """An ACTIVE account on a tower with one CLOSED outage of `minutes` minutes.

    The clock is moved to the outage's `ended_at` before closure so the window is
    entirely in the past. Adds "outage" to the scenario.
    """
    scenario = scenario or setup_active_subscriber(**kwargs)
    if "subscriber" not in scenario:
        scenario = setup_active_subscriber(scenario)
    overrides = {"cause": cause, "started_at": started_at}
    if planned_notice_days is not None:
        overrides["planned_notice_days"] = planned_notice_days
    outage = create_outage(scenario["tower"]["id"], **overrides)
    ended_at = iso_shift(started_at, minutes=minutes)
    set_clock(ended_at)
    scenario["outage"] = close_outage(outage["id"], ended_at=ended_at, peak_wind_mph=peak_wind_mph)
    return scenario


def setup_prepared_credit(scenario=None, **kwargs) -> dict:
    """CLOSED outage + one PENDING credit prepared by CREDIT_PREPARER_USER_ID."""
    scenario = scenario or setup_closed_outage(**kwargs)
    if "outage" not in scenario:
        scenario = setup_closed_outage(scenario, **kwargs)
    scenario["credit"] = prepare_credit(
        scenario["outage"]["id"], scenario["subscriber"]["id"]
    )
    return scenario


def setup_applied_credit(scenario=None, **kwargs) -> dict:
    """A credit carried through to APPLIED by CREDIT_APPROVER_USER_ID, a different
    person from the preparer. Refreshes "subscriber" and "outage"."""
    scenario = scenario or setup_prepared_credit(**kwargs)
    if "credit" not in scenario:
        scenario = setup_prepared_credit(scenario, **kwargs)
    scenario["credit"] = apply_credit(scenario["credit"]["id"])
    scenario["subscriber"] = get_subscriber(scenario["subscriber"]["id"])
    scenario["outage"] = get_outage(scenario["outage"]["id"])
    return scenario


# --------------------------------------------------------------------------
# Tier 5: two-tower interference coordination
# --------------------------------------------------------------------------


def setup_neighbor_sectors(sector_overrides=None, neighbor_overrides=None) -> dict:
    """Two independent towers, each with its own accepted transport, licence and
    ACTIVE sector, so a coordination between them crosses tower boundaries.

    Returns {"local": <plant>, "neighbor": <plant>}.
    """
    local = setup_active_plant(sector_overrides=sector_overrides)
    neighbor = setup_active_plant(
        tower_overrides={"latitude": 41.31, "longitude": -104.71},
        sector_overrides=neighbor_overrides or {"azimuth_deg": 270.0},
    )
    return {"local": local, "neighbor": neighbor}


def setup_coordination(pair=None, **overrides) -> dict:
    """Neighbouring sectors plus one coordination in REQUESTED at round 1.

    Returns {"local", "neighbor", "coordination"}.
    """
    pair = pair or setup_neighbor_sectors()
    pair["coordination"] = create_coordination(
        pair["local"]["sector"]["id"], pair["neighbor"]["sector"]["id"], **overrides
    )
    return pair


def setup_coordination_in_revision_requested(pair=None, **overrides) -> dict:
    """A coordination the neighbour has countered, so it sits in
    REVISION_REQUESTED at round 1 and the requester may revise."""
    pair = pair or setup_coordination(**overrides)
    if "coordination" not in pair:
        pair = setup_coordination(pair, **overrides)
    pair["coordination"] = respond_to_coordination(
        pair["coordination"]["id"], "REQUEST_REVISION", note="Please shift the centre down"
    )
    return pair


def setup_coordination_at_round(target_round: int, pair=None, **overrides) -> dict:
    """Walk a coordination up to `target_round` (1, 2 or 3) in REQUESTED status by
    alternating a neighbour revision request with a requester revision."""
    assert 1 <= target_round <= 3, f"Setup failed: unsupported coordination round {target_round}"
    pair = pair or setup_coordination(**overrides)
    if "coordination" not in pair:
        pair = setup_coordination(pair, **overrides)
    center = 3570.0
    while pair["coordination"]["round_number"] < target_round:
        pair["coordination"] = respond_to_coordination(
            pair["coordination"]["id"], "REQUEST_REVISION", note="Counter-offer"
        )
        center += 5.0
        pair["coordination"] = revise_coordination(
            pair["coordination"]["id"], proposed_channel_center_mhz=center
        )
    return pair
