"""Composite state builders.

Every builder drives the public endpoints declared by the PRD only — there is no
back-door seeding. Each builder returns the parsed resource payload (or a small
dict of related payloads) and accepts ``**overrides`` so a caller can change any
input field without copying the chain.

The recurring baseline used across the suite (referred to below as the *standard
project*) is a PREMIUM project requiring 1250 cartons per hour on a
240,000,000-cent base, with a two-segment line ``IB-01`` (BELT, 1500 cph, 96%
availability, full source share) feeding ``TR-02`` (ROLLER, 1400 cph, 95%
availability).
"""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .constants import TEST_DEFAULTS, TEST_INSTANTS
from .factories import (
    abort_window_payload,
    create_acceptance_certificate_payload,
    create_change_order_payload,
    create_commissioning_ramp_payload,
    create_cutover_window_payload,
    create_fabrication_lot_payload,
    create_fat_test_payload,
    create_flow_link_payload,
    create_project_payload,
    create_segment_payload,
    create_simulation_payload,
    create_site_zone_payload,
    create_spare_part_line_payload,
    create_staging_bay_payload,
    review_decision_payload,
    spares_provisioning_payload,
)
from .test_users import TEST_USERS

PROJECT_DIRECTOR = TEST_USERS["project_director_headers"]
DESIGN_ENGINEER = TEST_USERS["design_engineer_headers"]
SHOP_SUPERVISOR = TEST_USERS["shop_supervisor_headers"]
SITE_MANAGER = TEST_USERS["site_manager_headers"]
CUSTOMER_REP = TEST_USERS["customer_rep_headers"]


# ---------------------------------------------------------------------------
# Tier 1 — single independent creates
# ---------------------------------------------------------------------------
def make_project(api, headers: Optional[dict] = None, **overrides) -> dict:
    """Create one Project. Defaults to the standard project."""
    response = api.create_project(
        create_project_payload(**overrides), headers or PROJECT_DIRECTOR
    )
    return get_success_data(response)


def make_staging_bay(api, headers: Optional[dict] = None, **overrides) -> dict:
    """Create one StagingBay (a shop-floor resource, not owned by a project)."""
    response = api.create_staging_bay(
        create_staging_bay_payload(**overrides), headers or SHOP_SUPERVISOR
    )
    return get_success_data(response)


def set_clock(api, to_iso8601: str, headers: Optional[dict] = None) -> dict:
    """Move the logical clock to an explicit instant."""
    response = api.set_clock(to_iso8601, headers or PROJECT_DIRECTOR)
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Tier 2 — one dependency deep
# ---------------------------------------------------------------------------
def make_segment(api, project_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    """Create one ConveyorSegment on a project still in DESIGN."""
    response = api.create_segment(
        create_segment_payload(project_id, **overrides), headers or DESIGN_ENGINEER
    )
    return get_success_data(response)


def make_flow_link(
    api,
    project_id: str,
    from_segment_id: str,
    to_segment_id: str,
    split_share_bps: int = 10000,
    headers: Optional[dict] = None,
) -> dict:
    """Create one FlowLink between two segments of the same project."""
    response = api.create_flow_link(
        create_flow_link_payload(project_id, from_segment_id, to_segment_id, split_share_bps),
        headers or DESIGN_ENGINEER,
    )
    return get_success_data(response)


def make_site_zone(api, project_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    """Create one SiteZone. Defaults to Z-INBOUND holding the whole facility share."""
    response = api.create_site_zone(
        create_site_zone_payload(project_id, **overrides), headers or SITE_MANAGER
    )
    return get_success_data(response)


def make_spare_part_line(
    api, project_id: str, headers: Optional[dict] = None, **overrides
) -> dict:
    """Create one SparePartLine in DRAFT."""
    response = api.create_spare_part_line(
        create_spare_part_line_payload(project_id, **overrides), headers or PROJECT_DIRECTOR
    )
    return get_success_data(response)


def make_change_order(api, project_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    """Create one ChangeOrder in DRAFT at round_no 1."""
    response = api.create_change_order(
        create_change_order_payload(project_id, **overrides), headers or PROJECT_DIRECTOR
    )
    return get_success_data(response)


def run_simulation(
    api, project_id: str, method: str = "DEGRADED_AVAILABILITY", headers: Optional[dict] = None
) -> dict:
    """Run one throughput simulation and return the SimulationRun."""
    response = api.run_simulation(
        project_id, create_simulation_payload(method), headers or DESIGN_ENGINEER
    )
    return get_success_data(response)


def read_project(api, project_id: str, headers: Optional[dict] = None) -> dict:
    """Re-read a Project (used to pick up its current version before an OCC call)."""
    return get_success_data(api.get_project(project_id, headers or PROJECT_DIRECTOR))


def read_lot(api, lot_id: str, headers: Optional[dict] = None) -> dict:
    """Re-read a FabricationLot (used to pick up its current version)."""
    return get_success_data(api.get_fabrication_lot(lot_id, headers or SHOP_SUPERVISOR))


def read_segment(api, segment_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_segment(segment_id, headers or DESIGN_ENGINEER))


def read_window(api, window_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_cutover_window(window_id, headers or SITE_MANAGER))


def read_change_order(api, change_order_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_change_order(change_order_id, headers or PROJECT_DIRECTOR))


def read_certificate(api, certificate_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api.get_acceptance_certificate(certificate_id, headers or PROJECT_DIRECTOR)
    )


# ---------------------------------------------------------------------------
# Tier 3 — design-stage topologies
# ---------------------------------------------------------------------------
def make_linear_design(api, project: Optional[dict] = None, **project_overrides) -> dict:
    """Standard two-segment line: IB-01 (BELT) -> TR-02 (ROLLER) at full share.

    Returns ``{"project", "ib01", "tr02", "link"}``.
    """
    project = project or make_project(api, **project_overrides)
    ib01 = make_segment(
        api,
        project["id"],
        segment_code="IB-01",
        equipment_class="BELT",
        rated_capacity_cph=1500,
        availability_pct=96,
        source_share_bps=10000,
    )
    tr02 = make_segment(
        api,
        project["id"],
        segment_code="TR-02",
        equipment_class="ROLLER",
        rated_capacity_cph=1400,
        availability_pct=95,
        source_share_bps=None,
    )
    link = make_flow_link(api, project["id"], ib01["id"], tr02["id"], 10000)
    return {"project": project, "ib01": ib01, "tr02": tr02, "link": link}


def make_simulated_design(
    api, method: str = "DEGRADED_AVAILABILITY", project: Optional[dict] = None, **project_overrides
) -> dict:
    """Standard two-segment line with one completed simulation of ``method``."""
    design = make_linear_design(api, project=project, **project_overrides)
    design["simulation"] = run_simulation(api, design["project"]["id"], method)
    return design


def make_frozen_project(
    api, method: str = "DEGRADED_AVAILABILITY", project: Optional[dict] = None, **project_overrides
) -> dict:
    """Standard line, simulated, then design-frozen.

    Returns ``{"project", "ib01", "tr02", "link", "simulation"}`` where
    ``project`` is the post-freeze payload (delivery_status DESIGN_FROZEN).
    """
    design = make_simulated_design(api, method=method, project=project, **project_overrides)
    frozen = get_success_data(
        api.design_freeze(design["project"]["id"], PROJECT_DIRECTOR)
    )
    design["project"] = frozen
    return design


def make_merge_sortation_design(api, **project_overrides) -> dict:
    """Three feeders -> one MERGE -> one SORTATION -> two takeaways.

    Exercises the merge derate (three inbound links) together with the sortation
    divert loss (two outbound links is below the three-way threshold, so the
    loss does not apply). Returns the project plus every segment keyed by code.
    """
    overrides = {
        "customer_name": "Harborline Parcel",
        "facility_code": "DC-SEA-02",
        "required_throughput_cph": 1200,
        "contract_base_cents": 200_000_000,
        "authorized_ceiling_cents": 260_000_000,
        "spares_budget_cents": 4_000_000,
        "service_tier": "BASIC",
    }
    overrides.update(project_overrides)
    project = make_project(api, **overrides)
    segments: Dict[str, dict] = {}
    for code, klass, capacity, availability, source in (
        ("SR-1", "BELT", 900, 99, 4000),
        ("SR-2", "BELT", 900, 99, 3000),
        ("SR-3", "ROLLER", 900, 99, 3000),
    ):
        segments[code] = make_segment(
            api,
            project["id"],
            segment_code=code,
            equipment_class=klass,
            rated_capacity_cph=capacity,
            availability_pct=availability,
            source_share_bps=source,
        )
    for code, klass, capacity, availability in (
        ("MG-X", "MERGE", 1751, 89),
        ("SX-Y", "SORTATION", 1600, 95),
        ("OT-1", "BELT", 1000, 99),
        ("OT-2", "BELT", 1000, 99),
    ):
        segments[code] = make_segment(
            api,
            project["id"],
            segment_code=code,
            equipment_class=klass,
            rated_capacity_cph=capacity,
            availability_pct=availability,
            source_share_bps=None,
        )
    for from_code, to_code, share in (
        ("SR-1", "MG-X", 10000),
        ("SR-2", "MG-X", 10000),
        ("SR-3", "MG-X", 10000),
        ("MG-X", "SX-Y", 10000),
        ("SX-Y", "OT-1", 6000),
        ("SX-Y", "OT-2", 4000),
    ):
        make_flow_link(
            api, project["id"], segments[from_code]["id"], segments[to_code]["id"], share
        )
    return {"project": project, "segments": segments}


def make_branching_design(api, **project_overrides) -> dict:
    """Two feeders -> MERGE -> SORTATION -> three takeaways.

    The sortation has three outbound links, so the divert loss applies on top of
    the two-input merge derate. Returns the project plus segments keyed by code.
    """
    overrides = {
        "customer_name": "Meridian Fulfilment",
        "facility_code": "DC-DFW-11",
        "customer_rep_user_id": "cust-rep-21",
        "required_throughput_cph": 1300,
    }
    overrides.update(project_overrides)
    project = make_project(api, **overrides)
    segments: Dict[str, dict] = {}
    for code, klass, capacity, availability, source in (
        ("IB-A", "BELT", 1600, 95, 8000),
        ("IB-B", "ROLLER", 280, 90, 2000),
    ):
        segments[code] = make_segment(
            api,
            project["id"],
            segment_code=code,
            equipment_class=klass,
            rated_capacity_cph=capacity,
            availability_pct=availability,
            source_share_bps=source,
        )
    for code, klass, capacity, availability in (
        ("MG-C", "MERGE", 2000, 96),
        ("SX-D", "SORTATION", 1800, 92),
        ("OT-E", "BELT", 1800, 97),
        ("OT-F", "ROLLER", 2000, 98),
        ("OT-G", "BELT", 1200, 99),
    ):
        segments[code] = make_segment(
            api,
            project["id"],
            segment_code=code,
            equipment_class=klass,
            rated_capacity_cph=capacity,
            availability_pct=availability,
            source_share_bps=None,
        )
    for from_code, to_code, share in (
        ("IB-A", "MG-C", 10000),
        ("IB-B", "MG-C", 10000),
        ("MG-C", "SX-D", 10000),
        ("SX-D", "OT-E", 5000),
        ("SX-D", "OT-F", 3000),
        ("SX-D", "OT-G", 2000),
    ):
        make_flow_link(
            api, project["id"], segments[from_code]["id"], segments[to_code]["id"], share
        )
    return {"project": project, "segments": segments}


# ---------------------------------------------------------------------------
# Tier 4 — fabrication chain
# ---------------------------------------------------------------------------
def make_planned_lot(
    api,
    frozen: Optional[dict] = None,
    bay: Optional[dict] = None,
    segment_codes: Optional[List[str]] = None,
    **lot_overrides,
) -> dict:
    """Frozen standard project plus one PLANNED FabricationLot.

    Returns ``{"project", "ib01", "tr02", "link", "simulation", "bay", "lot"}``.
    """
    frozen = frozen or make_frozen_project(api)
    bay = bay or make_staging_bay(api)
    lot = get_success_data(
        api.create_fabrication_lot(
            create_fabrication_lot_payload(
                frozen["project"]["id"], bay["id"], segment_codes, **lot_overrides
            ),
            SHOP_SUPERVISOR,
        )
    )
    state = dict(frozen)
    state["bay"] = bay
    state["lot"] = lot
    return state


def make_staged_lot(api, planned: Optional[dict] = None, **kwargs) -> dict:
    """As :func:`make_planned_lot`, advanced through fabrication into STAGED."""
    state = planned or make_planned_lot(api, **kwargs)
    lot_id = state["lot"]["id"]
    get_success_data(api.start_fabrication(lot_id, SHOP_SUPERVISOR))
    state["lot"] = get_success_data(api.stage_fabrication_lot(lot_id, SHOP_SUPERVISOR))
    return state


def record_fat_test(
    api, lot: dict, measured_cph: int = 1320, defect_count: int = 1, headers: Optional[dict] = None
) -> dict:
    """Record one FatTest against a STAGED lot using its current version."""
    response = api.create_fat_test(
        create_fat_test_payload(lot["id"], lot["version"], measured_cph, defect_count),
        headers or SHOP_SUPERVISOR,
    )
    return get_success_data(response)


def make_fat_passed_lot(
    api,
    staged: Optional[dict] = None,
    measured_cph: int = 1320,
    defect_count: int = 1,
    **kwargs,
) -> dict:
    """As :func:`make_staged_lot`, with one passing FatTest recorded.

    Adds ``"fat_test"`` and refreshes ``"lot"`` to the FAT_PASSED payload.
    """
    state = staged or make_staged_lot(api, **kwargs)
    state["fat_test"] = record_fat_test(api, state["lot"], measured_cph, defect_count)
    state["lot"] = read_lot(api, state["lot"]["id"])
    return state


def fail_fat_attempt(api, state: dict, measured_cph: int, defect_count: int = 1) -> dict:
    """Drive one full rework cycle: start-fabrication, stage, then a failing test.

    Refreshes ``state["lot"]`` and returns the FatTest that was recorded.
    """
    lot_id = state["lot"]["id"]
    get_success_data(api.start_fabrication(lot_id, SHOP_SUPERVISOR))
    state["lot"] = get_success_data(api.stage_fabrication_lot(lot_id, SHOP_SUPERVISOR))
    fat_test = record_fat_test(api, state["lot"], measured_cph, defect_count)
    state["lot"] = read_lot(api, lot_id)
    return fat_test


# ---------------------------------------------------------------------------
# Tier 5 — cutover, commissioning, acceptance, dispute
# ---------------------------------------------------------------------------
def make_scheduled_window(
    api, state: Optional[dict] = None, zone_overrides: Optional[dict] = None, **window_overrides
) -> dict:
    """FAT_PASSED lot plus a SiteZone holding the whole share and a SCHEDULED window.

    Adds ``"zone"`` and ``"window"`` to the returned state dict.
    """
    state = state or make_fat_passed_lot(api)
    zone = make_site_zone(api, state["project"]["id"], **(zone_overrides or {}))
    window = get_success_data(
        api.create_cutover_window(
            create_cutover_window_payload(
                state["project"]["id"], zone["id"], state["lot"]["id"], **window_overrides
            ),
            SITE_MANAGER,
        )
    )
    state["zone"] = zone
    state["window"] = window
    return state


def make_completed_cutover(api, state: Optional[dict] = None, **kwargs) -> dict:
    """Scheduled window advanced to COMPLETED with the clock inside the window.

    Leaves the project in COMMISSIONING, the zone CUTOVER_COMPLETE and the lot
    INSTALLED. Refreshes ``"window"``, ``"zone"``, ``"lot"`` and ``"project"``.
    """
    state = state or make_scheduled_window(api, **kwargs)
    set_clock(api, TEST_INSTANTS["WINDOW_DUE_UTC"])
    get_success_data(api.start_cutover_window(state["window"]["id"], SITE_MANAGER))
    state["window"] = get_success_data(
        api.complete_cutover_window(state["window"]["id"], SITE_MANAGER)
    )
    state["project"] = read_project(api, state["project"]["id"])
    state["lot"] = read_lot(api, state["lot"]["id"])
    return state


def abort_cutover(api, state: dict, abort_reason: Optional[str] = None) -> dict:
    """Abort an IN_PROGRESS window and refresh the window and project payloads."""
    payload = abort_window_payload() if abort_reason is None else abort_window_payload(abort_reason)
    state["window"] = get_success_data(
        api.abort_cutover_window(state["window"]["id"], payload, SITE_MANAGER)
    )
    state["project"] = read_project(api, state["project"]["id"])
    return state


def record_ramp(
    api,
    project_id: str,
    step_pct: int,
    measured_cph: int,
    sustained_minutes: int,
    headers: Optional[dict] = None,
) -> dict:
    """Record one CommissioningRamp step."""
    response = api.create_commissioning_ramp(
        create_commissioning_ramp_payload(project_id, step_pct, measured_cph, sustained_minutes),
        headers or SITE_MANAGER,
    )
    return get_success_data(response)


def make_commissioned_project(api, state: Optional[dict] = None, **kwargs) -> dict:
    """Completed cutover plus passing ramp steps at 50, 75 and 100 per cent.

    Adds ``"ramps"`` (a list in step order) and refreshes ``"project"``, which
    then reports ``acceptance_ready`` true.
    """
    state = state or make_completed_cutover(api, **kwargs)
    project_id = state["project"]["id"]
    ramps = [
        record_ramp(api, project_id, 50, 700, 30),
        record_ramp(api, project_id, 75, 940, 60),
        record_ramp(api, project_id, 100, 1300, 120),
    ]
    state["ramps"] = ramps
    state["project"] = read_project(api, project_id)
    return state


def make_accepted_project(
    api, state: Optional[dict] = None, headers: Optional[dict] = None, **kwargs
) -> dict:
    """Commissioned project with an AcceptanceCertificate issued.

    Adds ``"certificate"`` and refreshes ``"project"`` (delivery ACCEPTED).
    """
    state = state or make_commissioned_project(api, **kwargs)
    certificate = get_success_data(
        api.create_acceptance_certificate(
            create_acceptance_certificate_payload(state["project"]["id"]),
            headers or PROJECT_DIRECTOR,
        )
    )
    state["certificate"] = certificate
    state["project"] = read_project(api, state["project"]["id"])
    return state


def make_disputed_certificate(
    api,
    state: Optional[dict] = None,
    claimed_cph: int = 1150,
    damages_basis: str = "NAMEPLATE",
    headers: Optional[dict] = None,
    **kwargs,
) -> dict:
    """Accepted project whose certificate carries one OPEN PerformanceDispute.

    Adds ``"dispute"`` and refreshes ``"certificate"`` and ``"project"``.
    """
    from .factories import create_performance_dispute_payload

    state = state or make_accepted_project(api, **kwargs)
    dispute = get_success_data(
        api.create_performance_dispute(
            create_performance_dispute_payload(
                state["certificate"]["id"], claimed_cph, damages_basis
            ),
            headers or CUSTOMER_REP,
        )
    )
    state["dispute"] = dispute
    state["certificate"] = read_certificate(api, state["certificate"]["id"])
    state["project"] = read_project(api, state["project"]["id"])
    return state


# ---------------------------------------------------------------------------
# Change-order and spares helpers
# ---------------------------------------------------------------------------
def make_submitted_change_order(
    api, project_id: str, headers: Optional[dict] = None, **overrides
) -> dict:
    """Create a ChangeOrder and submit it, returning the SUBMITTED payload."""
    change_order = make_change_order(api, project_id, headers=headers, **overrides)
    return get_success_data(
        api.submit_change_order(change_order["id"], headers or PROJECT_DIRECTOR)
    )


def decide_change_order(
    api, project_id: str, change_order_id: str, decision: str, headers: Optional[dict] = None, **extra
) -> dict:
    """Read the project's current version, then post a review decision."""
    project = read_project(api, project_id, headers)
    response = api.review_change_order(
        change_order_id,
        review_decision_payload(decision, project["version"], **extra),
        headers or PROJECT_DIRECTOR,
    )
    return get_success_data(response)


def spare_lines_by_part_no(api, project_id: str, headers: Optional[dict] = None) -> Dict[str, dict]:
    """Index a project's spare part lines by ``part_no`` (they have no single read)."""
    response = api.list_spare_part_lines(
        project_id, headers or PROJECT_DIRECTOR, params={"limit": 100}
    )
    return {line["part_no"]: line for line in get_success_data(response)}


def provision_spares(api, project_id: str, headers: Optional[dict] = None) -> dict:
    """Read the project's current version, then run the spares waterfall."""
    project = read_project(api, project_id, headers)
    response = api.run_spares_provisioning(
        project_id, spares_provisioning_payload(project["version"]), headers or PROJECT_DIRECTOR
    )
    return get_success_data(response)


STANDARD_PROJECT_NUMBERS = TEST_DEFAULTS
