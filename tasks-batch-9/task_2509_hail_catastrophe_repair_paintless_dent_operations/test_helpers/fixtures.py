"""Composite setup helpers.

Every test runs against an empty database, so each scenario is built end to end
through the PRD's own endpoints.  The helpers here are layered:

* **Tier 1 — primitives.**  One thin wrapper per write endpoint, each returning
  the created row.  They use ``get_success_data`` so that a broken setup step
  fails loudly with the server's own error identifier rather than a
  ``KeyError`` three calls later.
* **Tier 2 — the site.**  ``setup_operational_facility`` walks the whole
  stand-up chain: score a storm, target it, stand up a lot, get both required
  permits approved, hire and deploy crew, commission the site, open the event
  and put an active rate sheet behind a carrier.
* **Tier 3 — the vehicle.**  ``bring_vehicle_to`` drives one car from intake to
  any later stage of the repair and billing dimensions, so a test that needs a
  car in ``IN_REPAIR`` states that in one line.
* **Tier 4 — targeted shortcuts.**  Named helpers for the accumulation and
  terminal scenarios (the rework loop, the negotiation cycle, the pay cascade,
  demobilization) that would otherwise be repeated verbatim.

Identity threading matters here.  ``PdrTechnician``, ``QualityInspector`` and
``InsurerAdjuster`` are entity-backed roles, so every ownership-gated call made
by these helpers builds its headers from the row it just created.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import (
    CLOCK_T0,
    DEFAULT_FACILITY,
    DEPLOYMENT_END,
    DEPLOYMENT_START,
    PERMIT_WINDOW_FROM,
    PERMIT_WINDOW_TO,
    SECOND_INSURER,
)
from .test_users import (
    TEST_USERS,
    make_insurer_adjuster_headers,
    make_pdr_technician_headers,
    make_quality_inspector_headers,
)
from .types import REQUIRED_PERMIT_TYPES

DIRECTOR = TEST_USERS["director_headers"]
PERMIT_OFFICER = TEST_USERS["permit_officer_headers"]
CREW_COORDINATOR = TEST_USERS["crew_coordinator_headers"]
INTAKE_ADVISOR = TEST_USERS["intake_advisor_headers"]
SHOP_ESTIMATOR = TEST_USERS["shop_estimator_headers"]
BILLING_COORDINATOR = TEST_USERS["billing_coordinator_headers"]


# ══ Named technician roster ═══════════════════════════════════════════════════
#
# Keys are short handles used throughout the suite; every spec is a valid
# creation payload.  `TX` holds a licence that has already lapsed relative to
# the default clock, and `TO` is licensed in a different state from the default
# lot, so both are deliberately unusable at the Kansas site.

TECHNICIAN_SPECS: Dict[str, Dict[str, Any]] = {
    "TA": {
        "full_name": "Tara Alvarez",
        "home_state_code": "TX",
        "license_state_code": "KS",
        "license_expires_at": "2027-01-31",
        "skill_tier": "MASTER",
        "flat_split_pct": 0.45,
    },
    "TB": {
        "full_name": "Bo Nakamura",
        "home_state_code": "OK",
        "license_state_code": "KS",
        "license_expires_at": "2027-03-31",
        "skill_tier": "JOURNEYMAN",
        "flat_split_pct": 0.4,
    },
    "TC": {
        "full_name": "Cal Ruiz",
        "home_state_code": "KS",
        "license_state_code": "KS",
        "license_expires_at": "2027-05-31",
        "skill_tier": "JOURNEYMAN",
        "flat_split_pct": 0.4,
    },
    "TD": {
        "full_name": "Dee Whitmore",
        "home_state_code": "KS",
        "license_state_code": "KS",
        "license_expires_at": "2027-06-30",
        "skill_tier": "APPRENTICE",
        "flat_split_pct": 0.3,
    },
    "TI": {
        "full_name": "Iris Tran",
        "home_state_code": "KS",
        "license_state_code": "KS",
        "license_expires_at": "2027-12-31",
        "skill_tier": "JOURNEYMAN",
        "flat_split_pct": 0.35,
    },
    "TO": {
        "full_name": "Rae Okonkwo",
        "home_state_code": "OK",
        "license_state_code": "OK",
        "license_expires_at": "2027-09-30",
        "skill_tier": "JOURNEYMAN",
        "flat_split_pct": 0.35,
    },
    "TX": {
        "full_name": "Xan Pierce",
        "home_state_code": "KS",
        "license_state_code": "KS",
        "license_expires_at": "2026-07-31",
        "skill_tier": "JOURNEYMAN",
        "flat_split_pct": 0.4,
    },
}


# ══ Named damage-matrix profiles ══════════════════════════════════════════════
#
# Each profile is a list of damage-line payload fragments (the `vehicle_id` is
# filled in by the helper).  The comments record what the default rate sheet
# prices them at, so a test can reason about a profile without re-deriving it.

DAMAGE_PROFILES: Dict[str, List[Dict[str, Any]]] = {
    # Three panels that price differently under the two philosophies: paintless
    # 202,886 against conventional 257,750, so paintless wins.
    "three_panel": [
        {
            "panel_code": "HOOD",
            "dent_count": 42,
            "dent_size_class": "NICKEL",
            "aluminum": False,
            "r_and_i_hours": 0.5,
            "conventional_labor_hours": 8.0,
            "conventional_paint_materials_cents": 25000,
        },
        {
            "panel_code": "ROOF",
            "dent_count": 15,
            "dent_size_class": "DIME",
            "aluminum": False,
            "r_and_i_hours": 1.5,
            "conventional_labor_hours": 12.0,
            "conventional_paint_materials_cents": 26000,
        },
        {
            "panel_code": "LEFT_QUARTER",
            "dent_count": 9,
            "dent_size_class": "QUARTER",
            "aluminum": True,
            "r_and_i_hours": 0,
            "conventional_labor_hours": 7.0,
            "conventional_paint_materials_cents": 31250,
        },
    ],
    # One panel where conventional is the cheaper philosophy: paintless 107,528
    # against conventional 77,000.
    "single_panel_conventional": [
        {
            "panel_code": "HOOD",
            "dent_count": 42,
            "dent_size_class": "NICKEL",
            "aluminum": False,
            "r_and_i_hours": 0,
            "conventional_labor_hours": 8.0,
            "conventional_paint_materials_cents": 25000,
        },
    ],
    # A cheap single panel: paintless 51,204 against conventional 56,000.
    "single_panel_pdr": [
        {
            "panel_code": "HOOD",
            "dent_count": 20,
            "dent_size_class": "NICKEL",
            "aluminum": False,
            "r_and_i_hours": 0,
            "conventional_labor_hours": 8.0,
            "conventional_paint_materials_cents": 4000,
        },
    ],
    # Sits exactly on the 15-dent tier boundary: paintless 42,945.
    "tier_boundary_15": [
        {
            "panel_code": "ROOF",
            "dent_count": 15,
            "dent_size_class": "DIME",
            "aluminum": False,
            "r_and_i_hours": 1.5,
            "conventional_labor_hours": 12.0,
            "conventional_paint_materials_cents": 26000,
        },
    ],
    # One dent past the boundary, which is cheaper: paintless 39,847.
    "tier_boundary_16": [
        {
            "panel_code": "ROOF",
            "dent_count": 16,
            "dent_size_class": "DIME",
            "aluminum": False,
            "r_and_i_hours": 1.5,
            "conventional_labor_hours": 12.0,
            "conventional_paint_materials_cents": 26000,
        },
    ],
    # A panel whose raw paintless charge blows through the 140,000 panel cap,
    # so the panel is capped and the whole car leaves the paintless path.
    "capped_panel": [
        {
            "panel_code": "DECK_LID",
            "dent_count": 60,
            "dent_size_class": "HALF_DOLLAR",
            "aluminum": False,
            "r_and_i_hours": 0,
            "conventional_labor_hours": 14.0,
            "conventional_paint_materials_cents": 27500,
        },
    ],
}


# ══ Tier 1: primitives ════════════════════════════════════════════════════════


def set_clock(client: ApiClient, to_iso8601: str) -> None:
    get_success_data(client.set_clock(to_iso8601, DIRECTOR))


def create_storm_event(client: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        client.create_storm_event(f.storm_event_payload(**overrides), DIRECTOR)
    )


def target_storm_event(client: ApiClient, event_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.decide_storm_event(
            event_id, f.storm_event_decision_payload("TARGET"), DIRECTOR
        )
    )


def create_facility(client: ApiClient, event_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        client.create_facility(f.facility_payload(event_id, **overrides), DIRECTOR)
    )


def file_permit(
    client: ApiClient, facility_id: str, permit_type: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        client.create_permit(
            f.permit_payload(facility_id, permit_type, **overrides), DIRECTOR
        )
    )


def decide_permit(
    client: ApiClient,
    permit_id: str,
    decision: str = "APPROVE",
    valid_from: Optional[str] = PERMIT_WINDOW_FROM,
    valid_to: Optional[str] = PERMIT_WINDOW_TO,
) -> Dict[str, Any]:
    return get_success_data(
        client.decide_permit(
            permit_id,
            f.permit_decision_payload(decision, valid_from, valid_to),
            PERMIT_OFFICER,
        )
    )


def approve_required_permits(
    client: ApiClient,
    facility_id: str,
    valid_from: str = PERMIT_WINDOW_FROM,
    valid_to: str = PERMIT_WINDOW_TO,
    **overrides,
) -> Dict[str, Dict[str, Any]]:
    """File and approve one `TEMP_BUSINESS_LICENSE` and one `ZONING_USE`."""
    permits: Dict[str, Dict[str, Any]] = {}
    for permit_type in REQUIRED_PERMIT_TYPES:
        permit = file_permit(client, facility_id, permit_type, **overrides)
        decide_permit(client, permit["id"], "APPROVE", valid_from, valid_to)
        permits[permit_type] = permit
    return permits


def create_technician(client: ApiClient, handle_or_spec: Any, **overrides) -> Dict[str, Any]:
    """Create a roster technician from a named spec handle or a raw spec dict."""
    spec = (
        dict(TECHNICIAN_SPECS[handle_or_spec])
        if isinstance(handle_or_spec, str)
        else dict(handle_or_spec)
    )
    spec.update(overrides)
    return get_success_data(
        client.create_technician(f.technician_payload(**spec), CREW_COORDINATOR)
    )


def create_housing_unit(client: ApiClient, facility_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        client.create_housing_unit(
            f.housing_unit_payload(facility_id, **overrides), CREW_COORDINATOR
        )
    )


def create_deployment(
    client: ApiClient,
    technician_id: str,
    facility_id: str,
    start_date: str = DEPLOYMENT_START,
    end_date: str = DEPLOYMENT_END,
    housing_unit_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_crew_deployment(
            f.crew_deployment_payload(
                technician_id,
                facility_id,
                start_date,
                end_date,
                housing_unit_id,
                **overrides,
            ),
            CREW_COORDINATOR,
        )
    )


def set_deployment_status(
    client: ApiClient, deployment_id: str, to_status: str
) -> Dict[str, Any]:
    return get_success_data(
        client.set_crew_deployment_status(
            deployment_id, f.crew_deployment_status_payload(to_status), CREW_COORDINATOR
        )
    )


def commission_facility(client: ApiClient, facility_id: str) -> Dict[str, Any]:
    return get_success_data(client.commission_facility(facility_id, DIRECTOR))


def activate_storm_event(client: ApiClient, event_id: str) -> Dict[str, Any]:
    return get_success_data(client.activate_storm_event(event_id, DIRECTOR))


def create_insurer(client: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        client.create_insurer(f.insurer_payload(**overrides), DIRECTOR)
    )


def draft_rate_agreement(
    client: ApiClient, insurer_id: str, event_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        client.create_rate_agreement(
            f.rate_agreement_payload(insurer_id, event_id, **overrides), DIRECTOR
        )
    )


def read_insurer_version(client: ApiClient, insurer_id: str) -> int:
    """Re-read the carrier so an activation can carry a fresh expected version."""
    return get_success_data(client.get_insurer(insurer_id, DIRECTOR))["version"]


def activate_rate_agreement(
    client: ApiClient,
    rate_agreement_id: str,
    insurer_id: str,
    expected_insurer_version: Optional[int] = None,
) -> Dict[str, Any]:
    if expected_insurer_version is None:
        expected_insurer_version = read_insurer_version(client, insurer_id)
    return get_success_data(
        client.activate_rate_agreement(
            rate_agreement_id,
            f.rate_agreement_activate_payload(expected_insurer_version),
            DIRECTOR,
        )
    )


def intake_vehicle(
    client: ApiClient, facility_id: str, insurer_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        client.create_vehicle(
            f.vehicle_payload(facility_id, insurer_id, **overrides), INTAKE_ADVISOR
        )
    )


def add_damage_line(client: ApiClient, vehicle_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        client.create_damage_line(
            f.damage_line_payload(vehicle_id, **overrides), INTAKE_ADVISOR
        )
    )


def add_damage_profile(
    client: ApiClient, vehicle_id: str, profile: Any = "three_panel"
) -> List[Dict[str, Any]]:
    """Record a named (or literal) matrix, one panel at a time, in order."""
    rows = DAMAGE_PROFILES[profile] if isinstance(profile, str) else profile
    return [add_damage_line(client, vehicle_id, **row) for row in rows]


def estimate_vehicle(client: ApiClient, vehicle_id: str) -> Dict[str, Any]:
    return get_success_data(client.estimate_vehicle(vehicle_id, SHOP_ESTIMATOR))


def triage_vehicle(client: ApiClient, vehicle_id: str) -> Dict[str, Any]:
    return get_success_data(client.triage_vehicle(vehicle_id, SHOP_ESTIMATOR))


def billing_action(
    client: ApiClient, vehicle_id: str, action: str, insurer_id: str
) -> Dict[str, Any]:
    """Route a billing action to the role the PRD assigns it."""
    headers = (
        BILLING_COORDINATOR
        if action == "SUBMIT_BILL"
        else make_insurer_adjuster_headers(insurer_id)
    )
    return get_success_data(
        client.vehicle_billing(vehicle_id, f.billing_payload(action), headers)
    )


def authorize_vehicle(client: ApiClient, vehicle_id: str, insurer_id: str) -> Dict[str, Any]:
    return billing_action(client, vehicle_id, "AUTHORIZE", insurer_id)


def start_repair(client: ApiClient, vehicle_id: str) -> Dict[str, Any]:
    return get_success_data(client.start_vehicle_repair(vehicle_id, SHOP_ESTIMATOR))


def open_work_ticket(
    client: ApiClient, vehicle_id: str, technician_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        client.create_work_ticket(
            f.work_ticket_payload(vehicle_id, technician_id, **overrides),
            make_pdr_technician_headers(technician_id),
        )
    )


def submit_work_ticket(
    client: ApiClient, ticket_id: str, technician_id: str
) -> Dict[str, Any]:
    return get_success_data(
        client.submit_work_ticket(ticket_id, make_pdr_technician_headers(technician_id))
    )


def record_inspection(
    client: ApiClient,
    vehicle_id: str,
    inspector_technician_id: str,
    result: str = "PASS",
    defect_panel_codes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_quality_inspection(
            f.quality_inspection_payload(
                vehicle_id, inspector_technician_id, result, defect_panel_codes
            ),
            make_quality_inspector_headers(inspector_technician_id),
        )
    )


def release_vehicle(client: ApiClient, vehicle_id: str) -> Dict[str, Any]:
    return get_success_data(client.release_vehicle(vehicle_id, INTAKE_ADVISOR))


def file_supplement(
    client: ApiClient,
    vehicle_id: str,
    requested_amount_cents: int,
    expected_vehicle_version: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    if expected_vehicle_version is None:
        expected_vehicle_version = read_vehicle_version(client, vehicle_id)
    return get_success_data(
        client.create_supplement(
            f.supplement_payload(
                vehicle_id, requested_amount_cents, expected_vehicle_version, **overrides
            ),
            SHOP_ESTIMATOR,
        )
    )


def review_supplement(
    client: ApiClient,
    supplement_id: str,
    insurer_id: str,
    decision: str,
    counter_amount_cents: Optional[int] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.review_supplement(
            supplement_id,
            f.supplement_review_payload(decision, counter_amount_cents),
            make_insurer_adjuster_headers(insurer_id),
        )
    )


def revise_supplement(
    client: ApiClient,
    supplement_id: str,
    action: str = "REVISE",
    revised_amount_cents: Optional[int] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.revise_supplement(
            supplement_id,
            f.supplement_revise_payload(action, revised_amount_cents),
            SHOP_ESTIMATOR,
        )
    )


def demobilize_event(client: ApiClient, event_id: str) -> Dict[str, Any]:
    return get_success_data(client.demobilize_storm_event(event_id, DIRECTOR))


def close_event(client: ApiClient, event_id: str) -> Dict[str, Any]:
    return get_success_data(client.close_storm_event(event_id, DIRECTOR))


# ── Read-back helpers ─────────────────────────────────────────────────────────


def read_vehicle(client: ApiClient, vehicle_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_vehicle(vehicle_id, SHOP_ESTIMATOR))


def read_vehicle_version(client: ApiClient, vehicle_id: str) -> int:
    return read_vehicle(client, vehicle_id)["version"]


def read_facility(client: ApiClient, facility_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_facility(facility_id, DIRECTOR))


def read_event(client: ApiClient, event_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_storm_event(event_id, DIRECTOR))


def read_insurer(client: ApiClient, insurer_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_insurer(insurer_id, DIRECTOR))


def read_technician(client: ApiClient, technician_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_technician(technician_id, CREW_COORDINATOR))


def read_deployment(client: ApiClient, deployment_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_crew_deployment(deployment_id, CREW_COORDINATOR))


def read_rate_agreement(client: ApiClient, rate_agreement_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_rate_agreement(rate_agreement_id, DIRECTOR))


def read_supplement(client: ApiClient, supplement_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_supplement(supplement_id, SHOP_ESTIMATOR))


def read_work_ticket(client: ApiClient, ticket_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_work_ticket(ticket_id, SHOP_ESTIMATOR))


def read_damage_lines(client: ApiClient, vehicle_id: str) -> List[Dict[str, Any]]:
    return get_success_data(client.list_vehicle_damage_lines(vehicle_id, SHOP_ESTIMATOR))


def read_housing_units(client: ApiClient, facility_id: str) -> List[Dict[str, Any]]:
    return get_success_data(client.list_facility_housing_units(facility_id, CREW_COORDINATOR))


def read_throughput_summary(client: ApiClient, facility_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_throughput_summary(facility_id, DIRECTOR))


# ══ Tier 2: a standing, working site ══════════════════════════════════════════


def setup_operational_facility(
    client: ApiClient,
    clock: str = CLOCK_T0,
    event_overrides: Optional[Dict[str, Any]] = None,
    facility_overrides: Optional[Dict[str, Any]] = None,
    pay_model: str = "FLAT",
    staging_slot_count: int = DEFAULT_FACILITY["staging_slot_count"],
    permit_valid_from: str = PERMIT_WINDOW_FROM,
    permit_valid_to: str = PERMIT_WINDOW_TO,
    technicians: Sequence[str] = ("TA",),
    on_site: Optional[Sequence[str]] = None,
    deployment_start: str = DEPLOYMENT_START,
    deployment_end: str = DEPLOYMENT_END,
    commission: bool = True,
    activate_event: bool = True,
    insurer_overrides: Optional[Dict[str, Any]] = None,
    rate_agreement_overrides: Optional[Dict[str, Any]] = None,
    activate_rate_sheet: bool = True,
) -> Dict[str, Any]:
    """Stand up one commissioned Kansas lot on an open event with a live sheet.

    Returns a scenario dictionary whose keys the rest of the suite relies on::

        event, event_id, facility, facility_id, permits,
        technicians (handle -> row), deployments (handle -> row),
        insurer, insurer_id, rate_agreement, rate_agreement_id
    """
    set_clock(client, clock)

    event = create_storm_event(client, **(event_overrides or {}))
    target_storm_event(client, event["id"])

    facility = create_facility(
        client,
        event["id"],
        pay_model=pay_model,
        staging_slot_count=staging_slot_count,
        **(facility_overrides or {}),
    )
    permits = approve_required_permits(
        client, facility["id"], permit_valid_from, permit_valid_to
    )

    on_site = tuple(technicians) if on_site is None else tuple(on_site)
    technician_rows: Dict[str, Dict[str, Any]] = {}
    deployment_rows: Dict[str, Dict[str, Any]] = {}
    for handle in technicians:
        technician = create_technician(client, handle)
        technician_rows[handle] = technician
        deployment = create_deployment(
            client,
            technician["id"],
            facility["id"],
            deployment_start,
            deployment_end,
        )
        if handle in on_site:
            deployment = set_deployment_status(client, deployment["id"], "ON_SITE")
        deployment_rows[handle] = deployment

    if commission:
        facility = commission_facility(client, facility["id"])
    if activate_event:
        event = activate_storm_event(client, event["id"])

    insurer = create_insurer(client, **(insurer_overrides or {}))
    rate_agreement = draft_rate_agreement(
        client, insurer["id"], event["id"], **(rate_agreement_overrides or {})
    )
    if activate_rate_sheet:
        rate_agreement = activate_rate_agreement(
            client, rate_agreement["id"], insurer["id"]
        )

    return {
        "event": event,
        "event_id": event["id"],
        "facility": facility,
        "facility_id": facility["id"],
        "permits": permits,
        "technicians": technician_rows,
        "deployments": deployment_rows,
        "insurer": insurer,
        "insurer_id": insurer["id"],
        "rate_agreement": rate_agreement,
        "rate_agreement_id": rate_agreement["id"],
        "clock": clock,
    }


def setup_repair_floor(client: ApiClient, **overrides) -> Dict[str, Any]:
    """A site staffed with one worker (`TA`) and one separate inspector (`TI`).

    The PRD's separation of duties means the inspector may hold no ticket on the
    car, so a full-lifecycle scenario always needs two deployed technicians.
    """
    overrides.setdefault("technicians", ("TA", "TI"))
    return setup_operational_facility(client, **overrides)


def tech_id(scenario: Dict[str, Any], handle: str) -> str:
    return scenario["technicians"][handle]["id"]


def tech_headers(scenario: Dict[str, Any], handle: str) -> Dict[str, str]:
    return make_pdr_technician_headers(tech_id(scenario, handle))


def inspector_headers(scenario: Dict[str, Any], handle: str) -> Dict[str, str]:
    return make_quality_inspector_headers(tech_id(scenario, handle))


def adjuster_headers(scenario: Dict[str, Any]) -> Dict[str, str]:
    return make_insurer_adjuster_headers(scenario["insurer_id"])


def add_technician_to_site(
    client: ApiClient,
    scenario: Dict[str, Any],
    handle: str,
    on_site: bool = True,
    start_date: str = DEPLOYMENT_START,
    end_date: str = DEPLOYMENT_END,
    housing_unit_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Hire and deploy one more named technician onto the scenario's lot."""
    technician = create_technician(client, handle)
    deployment = create_deployment(
        client,
        technician["id"],
        scenario["facility_id"],
        start_date,
        end_date,
        housing_unit_id,
    )
    if on_site:
        deployment = set_deployment_status(client, deployment["id"], "ON_SITE")
    scenario["technicians"][handle] = technician
    scenario["deployments"][handle] = deployment
    return technician


def add_second_facility(
    client: ApiClient,
    scenario: Dict[str, Any],
    name: str = "Enid Overflow Lot",
    state_code: str = "OK",
    address: str = "44 Owen K Garriott Rd",
    staging_slot_count: int = 4,
    pay_model: str = "POOLED",
    technicians: Sequence[str] = ("TO",),
    commission: bool = True,
) -> Dict[str, Any]:
    """Stand up a second lot on the same event, in its own licensing state."""
    facility = create_facility(
        client,
        scenario["event_id"],
        name=name,
        state_code=state_code,
        address=address,
        staging_slot_count=staging_slot_count,
        pay_model=pay_model,
    )
    permits = approve_required_permits(client, facility["id"])
    technician_rows: Dict[str, Dict[str, Any]] = {}
    deployment_rows: Dict[str, Dict[str, Any]] = {}
    for handle in technicians:
        technician = create_technician(client, handle)
        deployment = create_deployment(client, technician["id"], facility["id"])
        deployment = set_deployment_status(client, deployment["id"], "ON_SITE")
        technician_rows[handle] = technician
        deployment_rows[handle] = deployment
    if commission:
        facility = commission_facility(client, facility["id"])
    return {
        "facility": facility,
        "facility_id": facility["id"],
        "permits": permits,
        "technicians": technician_rows,
        "deployments": deployment_rows,
    }


def add_second_insurer(
    client: ApiClient, scenario: Dict[str, Any], **overrides
) -> Dict[str, Any]:
    """Register a second carrier with its own active sheet on the same event."""
    payload = dict(SECOND_INSURER)
    payload.update(overrides)
    insurer = create_insurer(client, **payload)
    agreement = draft_rate_agreement(client, insurer["id"], scenario["event_id"])
    agreement = activate_rate_agreement(client, agreement["id"], insurer["id"])
    return {
        "insurer": insurer,
        "insurer_id": insurer["id"],
        "rate_agreement": agreement,
        "rate_agreement_id": agreement["id"],
    }


# ══ Tier 3: one vehicle driven to a chosen stage ═══════════════════════════════

VEHICLE_STAGES = (
    "INTAKE",
    "MATRIX",
    "ESTIMATED",
    "TRIAGED",
    "AUTHORIZED",
    "IN_REPAIR",
    "QC_PENDING",
    "READY",
    "RELEASED",
)

DEFAULT_TICKET_SPECS: List[Dict[str, Any]] = [
    {"tech": "TA", "labor_units": 3.0, "dents_repaired": 42, "panels_worked": 1}
]


def bring_vehicle_to(
    client: ApiClient,
    scenario: Dict[str, Any],
    stage: str,
    damage_profile: Any = "three_panel",
    ticket_specs: Optional[Sequence[Dict[str, Any]]] = None,
    inspector: str = "TI",
    inspection_result: str = "PASS",
    defect_panel_codes: Optional[List[str]] = None,
    facility_id: Optional[str] = None,
    insurer_id: Optional[str] = None,
    **vehicle_overrides,
) -> Dict[str, Any]:
    """Drive one car from intake up to ``stage`` and return everything created.

    The returned dictionary carries ``vehicle`` (the row as of the last write),
    ``vehicle_id``, ``damage_lines``, ``work_tickets`` and ``inspection``.
    """
    assert stage in VEHICLE_STAGES, f"unknown stage {stage!r}"
    reached = VEHICLE_STAGES.index(stage)
    facility_id = facility_id or scenario["facility_id"]
    insurer_id = insurer_id or scenario["insurer_id"]

    vehicle = intake_vehicle(client, facility_id, insurer_id, **vehicle_overrides)
    result: Dict[str, Any] = {
        "vehicle": vehicle,
        "vehicle_id": vehicle["id"],
        "damage_lines": [],
        "work_tickets": [],
        "inspection": None,
    }
    if reached == 0:
        return result

    result["damage_lines"] = add_damage_profile(client, vehicle["id"], damage_profile)
    if reached == 1:
        return result

    result["vehicle"] = estimate_vehicle(client, vehicle["id"])
    if reached == 2:
        return result

    result["vehicle"] = triage_vehicle(client, vehicle["id"])
    if reached == 3:
        return result

    result["vehicle"] = authorize_vehicle(client, vehicle["id"], insurer_id)
    if reached == 4:
        return result

    result["vehicle"] = start_repair(client, vehicle["id"])
    if reached == 5:
        return result

    specs = DEFAULT_TICKET_SPECS if ticket_specs is None else ticket_specs
    tickets: List[Dict[str, Any]] = []
    for spec in specs:
        spec = dict(spec)
        handle = spec.pop("tech")
        technician_id = tech_id(scenario, handle)
        ticket = open_work_ticket(client, vehicle["id"], technician_id, **spec)
        ticket["_tech_handle"] = handle
        tickets.append(ticket)
    for ticket in tickets:
        submit_work_ticket(
            client, ticket["id"], tech_id(scenario, ticket["_tech_handle"])
        )
    result["work_tickets"] = tickets
    result["vehicle"] = read_vehicle(client, vehicle["id"])
    if reached == 6:
        return result

    result["inspection"] = record_inspection(
        client,
        vehicle["id"],
        tech_id(scenario, inspector),
        inspection_result,
        defect_panel_codes,
    )
    result["vehicle"] = read_vehicle(client, vehicle["id"])
    if reached == 7:
        return result

    result["vehicle"] = release_vehicle(client, vehicle["id"])
    return result


# ══ Tier 4: targeted scenario shortcuts ═══════════════════════════════════════


def setup_vehicle_in_repair(
    client: ApiClient,
    damage_profile: Any = "three_panel",
    technicians: Sequence[str] = ("TA", "TI"),
    pay_model: str = "FLAT",
    **scenario_overrides,
) -> Dict[str, Any]:
    """One authorized car on the floor, with a worker and a spare inspector."""
    scenario = setup_operational_facility(
        client, technicians=technicians, pay_model=pay_model, **scenario_overrides
    )
    car = bring_vehicle_to(client, scenario, "IN_REPAIR", damage_profile=damage_profile)
    scenario["car"] = car
    return scenario


def setup_vehicle_at_qc(
    client: ApiClient,
    damage_profile: Any = "three_panel",
    ticket_specs: Optional[Sequence[Dict[str, Any]]] = None,
    technicians: Sequence[str] = ("TA", "TI"),
    pay_model: str = "FLAT",
    **scenario_overrides,
) -> Dict[str, Any]:
    """One car whose tickets are all submitted, waiting on an inspection."""
    scenario = setup_operational_facility(
        client, technicians=technicians, pay_model=pay_model, **scenario_overrides
    )
    car = bring_vehicle_to(
        client,
        scenario,
        "QC_PENDING",
        damage_profile=damage_profile,
        ticket_specs=ticket_specs,
    )
    scenario["car"] = car
    return scenario


def fail_inspection_and_restart(
    client: ApiClient,
    scenario: Dict[str, Any],
    vehicle_id: str,
    inspector: str = "TI",
    defect_panel_codes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """One turn of the rework loop: fail the car, then put it back on the floor."""
    inspection = record_inspection(
        client,
        vehicle_id,
        tech_id(scenario, inspector),
        "FAIL",
        defect_panel_codes or ["HOOD"],
    )
    vehicle = start_repair(client, vehicle_id)
    return {"inspection": inspection, "vehicle": vehicle}


def drive_rework_count_to(
    client: ApiClient,
    scenario: Dict[str, Any],
    vehicle_id: str,
    target: int,
    inspector: str = "TI",
) -> List[Dict[str, Any]]:
    """Cycle QC_PENDING → QC_FAILED → IN_REPAIR until `rework_count` is `target`.

    The car is left in ``QC_PENDING`` after each restart by re-opening and
    submitting a ticket, because an inspection may only be recorded there.
    """
    inspections: List[Dict[str, Any]] = []
    for _ in range(target):
        inspection = record_inspection(
            client, vehicle_id, tech_id(scenario, inspector), "FAIL", ["HOOD"]
        )
        inspections.append(inspection)
        start_repair(client, vehicle_id)
        worker_id = tech_id(scenario, "TA")
        ticket = open_work_ticket(
            client, vehicle_id, worker_id, labor_units=1.0, dents_repaired=1
        )
        submit_work_ticket(client, ticket["id"], worker_id)
    return inspections


def setup_negotiated_supplement(
    client: ApiClient,
    requested_amount_cents: int,
    damage_profile: Any = "three_panel",
    **scenario_overrides,
) -> Dict[str, Any]:
    """A triaged, authorized car carrying one supplement under review."""
    scenario = setup_operational_facility(client, **scenario_overrides)
    car = bring_vehicle_to(
        client, scenario, "AUTHORIZED", damage_profile=damage_profile
    )
    supplement = file_supplement(client, car["vehicle_id"], requested_amount_cents)
    scenario["car"] = car
    scenario["supplement"] = supplement
    return scenario


def setup_housed_crew(
    client: ApiClient,
    bed_count: int = 2,
    nightly_rate_cents: int = 8900,
    **scenario_overrides,
) -> Dict[str, Any]:
    """A site with one shared housing unit and nobody in it yet."""
    scenario_overrides.setdefault("technicians", ())
    scenario = setup_operational_facility(client, commission=False, activate_event=False, **scenario_overrides)
    unit = create_housing_unit(
        client,
        scenario["facility_id"],
        bed_count=bed_count,
        nightly_rate_cents=nightly_rate_cents,
    )
    scenario["housing_unit"] = unit
    scenario["housing_unit_id"] = unit["id"]
    return scenario


def clear_the_lot_and_demobilize(
    client: ApiClient, scenario: Dict[str, Any], at_clock: Optional[str] = None
) -> Dict[str, Any]:
    """Move the clock (optionally) and wind the event down."""
    if at_clock is not None:
        set_clock(client, at_clock)
    return demobilize_event(client, scenario["event_id"])


def settle_vehicle(client: ApiClient, vehicle_id: str, insurer_id: str) -> Dict[str, Any]:
    """Walk a released car all the way to `PAID`."""
    billing_action(client, vehicle_id, "SUBMIT_BILL", insurer_id)
    return billing_action(client, vehicle_id, "SETTLE", insurer_id)


def each(values: Iterable[Any]) -> List[Any]:
    """Small readability shim for turning a generator into a list inline."""
    return list(values)
