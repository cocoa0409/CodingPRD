"""Composite state builders.

The harness restarts the API server before every individual test, so every test
begins against an empty database. Nothing here assumes a pre-existing row: each
builder constructs its state from scratch through the endpoints of PRD section 4
only, under the role each of those endpoints requires, and returns the rows the
API minted so a test can thread real identifiers and real versions into the call
it is exercising.

The chains below follow the physical order the plant is built in — permit and
earthwork, then owner acceptance, then laydown and receipt, then piles, then
mechanical completion, then wiring and string tests — because every later gate
in the PRD refuses to run until the earlier one has been satisfied.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import DEFAULT_CLOCK
from .test_users import (
    CIVIL_SUPERINTENDENT,
    COMMISSIONING_ENGINEER,
    EPC_PROJECT_MANAGER,
    INSTALLATION_FOREMAN,
    LABOR_COMPLIANCE_OFFICER,
    LABOR_COMPLIANCE_OFFICER_ALT,
    OWNER_ENGINEER,
    PROCUREMENT_COORDINATOR,
    UTILITY_COORDINATOR,
)

Json = Dict[str, Any]

# ---------------------------------------------------------------------------
# Reference instants shared by the chains
# ---------------------------------------------------------------------------
CLEARING_START = "2026-08-01T12:00:00Z"
CLEARING_END = "2026-08-01T20:00:00Z"
GRADING_START = "2026-08-02T12:00:00Z"
GRADING_END = "2026-08-02T20:00:00Z"
LAYDOWN_START = "2026-08-03T00:00:00Z"
LAYDOWN_END = "2026-08-07T00:00:00Z"
OUTAGE_START = "2026-08-10T00:00:00Z"
OUTAGE_END = "2026-08-10T04:00:00Z"
INSIDE_OUTAGE = "2026-08-10T02:00:00Z"
TEST_SCHEDULED_AT = "2026-08-10T02:30:00Z"


# ===========================================================================
# Tier 1: one call each
# ===========================================================================
def set_clock(api, now: str) -> Json:
    """Move the logical site clock of PRD 2.5, which every gate reads."""
    return get_success_data(api.set_clock(f.clock_payload(now), EPC_PROJECT_MANAGER))


def reset_clock(api) -> Json:
    """Pin the clock at the instant the PRD declares as its default reading."""
    return set_clock(api, DEFAULT_CLOCK)


def create_project(api, **overrides: Any) -> Json:
    return get_success_data(
        api.create_project(f.project_payload(**overrides), EPC_PROJECT_MANAGER)
    )


def read_project(api, project_id: str) -> Json:
    return get_success_data(api.get_project(project_id, EPC_PROJECT_MANAGER))


def project_version(api, project_id: str) -> int:
    """The project's current `version`, for the concurrency guard on scheduling."""
    return read_project(api, project_id)["version"]


def create_grading_area(api, project_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_grading_area(
            project_id, f.grading_area_payload(**overrides), CIVIL_SUPERINTENDENT
        )
    )


def read_grading_area(api, grading_area_id: str) -> Json:
    return get_success_data(api.get_grading_area(grading_area_id, CIVIL_SUPERINTENDENT))


def create_yard_zone(api, project_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_yard_zone(
            project_id, f.yard_zone_payload(**overrides), PROCUREMENT_COORDINATOR
        )
    )


def read_yard_zone(api, yard_zone_id: str) -> Json:
    return get_success_data(api.get_yard_zone(yard_zone_id, PROCUREMENT_COORDINATOR))


def yard_zone_version(api, yard_zone_id: str) -> int:
    """The zone's current `version`, for the reservation concurrency guard."""
    return read_yard_zone(api, yard_zone_id)["version"]


def create_substation(api, project_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_substation(
            project_id, f.substation_payload(**overrides), UTILITY_COORDINATOR
        )
    )


def read_substation(api, substation_id: str) -> Json:
    return get_success_data(api.get_substation(substation_id, UTILITY_COORDINATOR))


def create_punch_item(api, project_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_punch_list_item(
            project_id, f.punch_list_item_payload(**overrides), OWNER_ENGINEER
        )
    )


def read_punch_item(api, item_id: str) -> Json:
    return get_success_data(api.get_punch_list_item(item_id, OWNER_ENGINEER))


def create_payroll_week(api, project_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_payroll_week(
            project_id, f.payroll_week_payload(**overrides), LABOR_COMPLIANCE_OFFICER
        )
    )


def read_payroll_week(api, week_id: str) -> Json:
    return get_success_data(api.get_payroll_week(week_id, LABOR_COMPLIANCE_OFFICER))


def read_settlement_summary(api, project_id: str) -> Json:
    return get_success_data(api.get_settlement_summary(project_id, EPC_PROJECT_MANAGER))


# ===========================================================================
# Tier 2: the civil chain — permit, earthwork, owner acceptance
# ===========================================================================
def log_clearing(
    api,
    grading_area_id: str,
    *,
    start_at: str = CLEARING_START,
    end_at: str = CLEARING_END,
    acreage: float = 10.00,
) -> Json:
    """A clearing window, the first earthwork activity an area records."""
    return get_success_data(
        api.create_earthwork_log(
            grading_area_id,
            f.earthwork_log_payload("CLEARING", start_at, end_at, acreage),
            CIVIL_SUPERINTENDENT,
        )
    )


def log_grading(
    api,
    grading_area_id: str,
    *,
    start_at: str = GRADING_START,
    end_at: str = GRADING_END,
    acreage: float = 8.00,
) -> Json:
    """A grading window, which is what takes the area to `GRADED`."""
    return get_success_data(
        api.create_earthwork_log(
            grading_area_id,
            f.earthwork_log_payload("GRADING", start_at, end_at, acreage),
            CIVIL_SUPERINTENDENT,
        )
    )


def record_bmp_inspection(
    api, grading_area_id: str, occurred_at: str, deficiencies_found: bool = False
) -> Json:
    return get_success_data(
        api.create_site_event(
            grading_area_id,
            f.bmp_inspection_payload(occurred_at, deficiencies_found),
            CIVIL_SUPERINTENDENT,
        )
    )


def record_rain_event(
    api, grading_area_id: str, occurred_at: str, rainfall_inches: float
) -> Json:
    return get_success_data(
        api.create_site_event(
            grading_area_id,
            f.rain_event_payload(occurred_at, rainfall_inches),
            CIVIL_SUPERINTENDENT,
        )
    )


def suspend_permit(api, grading_area_id: str, occurred_at: str) -> Json:
    return get_success_data(
        api.create_site_event(
            grading_area_id,
            f.permit_suspension_payload(occurred_at),
            CIVIL_SUPERINTENDENT,
        )
    )


def reinstate_permit(api, grading_area_id: str, occurred_at: str) -> Json:
    return get_success_data(
        api.create_site_event(
            grading_area_id,
            f.permit_reinstatement_payload(occurred_at),
            CIVIL_SUPERINTENDENT,
        )
    )


def accept_grading_area(
    api,
    grading_area_id: str,
    *,
    compaction_test_pct: float = 96.5,
    drainage_inspection_passed: bool = True,
) -> Json:
    """Owner acceptance, which is what unlocks block creation on the area."""
    return get_success_data(
        api.accept_grading_area(
            grading_area_id,
            f.acceptance_payload(compaction_test_pct, drainage_inspection_passed),
            OWNER_ENGINEER,
        )
    )


def graded_area(api, project_id: str, **overrides: Any) -> Json:
    """A grading area that has been cleared and graded but not yet accepted."""
    area = create_grading_area(api, project_id, **overrides)
    log_clearing(api, area["id"])
    log_grading(api, area["id"])
    return read_grading_area(api, area["id"])


def accepted_area(api, project_id: str, **overrides: Any) -> Json:
    """A grading area at `ACCEPTED`, ready to carry blocks."""
    area = graded_area(api, project_id, **overrides)
    accept_grading_area(api, area["id"])
    return read_grading_area(api, area["id"])


# ===========================================================================
# Tier 2: the laydown chain — zone, reservation, receipt
# ===========================================================================
def reserve_delivery(
    api,
    project_id: str,
    yard_zone_id: str,
    *,
    expected_version: Optional[int] = None,
    **overrides: Any,
) -> Json:
    """Reserve pallet positions, reading the zone's live version when not given."""
    version = (
        expected_version
        if expected_version is not None
        else yard_zone_version(api, yard_zone_id)
    )
    fields = dict(overrides)
    fields.setdefault("laydown_window_start", LAYDOWN_START)
    fields.setdefault("laydown_window_end", LAYDOWN_END)
    payload = f.delivery_payload(project_id, yard_zone_id, version, **fields)
    return get_success_data(api.create_delivery(payload, PROCUREMENT_COORDINATOR))


def receive_delivery(
    api, delivery_id: str, received_unit_qty: int, damaged_unit_qty: int
) -> Json:
    """Receive and inspect; the acceptance fork resolves inside this one call."""
    return get_success_data(
        api.receive_delivery(
            delivery_id,
            f.receipt_payload(received_unit_qty, damaged_unit_qty),
            PROCUREMENT_COORDINATOR,
        )
    )


def cancel_delivery(api, delivery_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.cancel_delivery(
            delivery_id, f.cancellation_payload(**overrides), PROCUREMENT_COORDINATOR
        )
    )


def accepted_module_delivery(
    api,
    project_id: str,
    yard_zone_id: str,
    *,
    unit_qty: int = 60,
    pallets: int = 60,
    received: int = 60,
    damaged: int = 3,
    **overrides: Any,
) -> Json:
    """A module shipment accepted into the yard, which is what makes modules
    available to a block's mechanical completion."""
    delivery = reserve_delivery(
        api,
        project_id,
        yard_zone_id,
        unit_qty=unit_qty,
        pallets=pallets,
        **overrides,
    )
    return receive_delivery(api, delivery["id"], received, damaged)


# ===========================================================================
# Tier 2: the mechanical chain — block, piles, mechanical completion
# ===========================================================================
def create_block(api, project_id: str, grading_area_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_block(
            project_id, f.block_payload(grading_area_id, **overrides), EPC_PROJECT_MANAGER
        )
    )


def read_block(api, block_id: str) -> Json:
    return get_success_data(api.get_block(block_id, EPC_PROJECT_MANAGER))


def create_pile(api, block_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_pile(block_id, f.pile_payload(**overrides), INSTALLATION_FOREMAN)
    )


def read_pile(api, pile_id: str) -> Json:
    return get_success_data(api.get_pile(pile_id, INSTALLATION_FOREMAN))


def record_drive_result(api, pile_id: str, **overrides: Any) -> Json:
    """Record a driving result; the disposition resolves inside the same call."""
    return get_success_data(
        api.create_drive_result(
            pile_id, f.drive_result_payload(**overrides), INSTALLATION_FOREMAN
        )
    )


def record_remediation(
    api,
    pile_id: str,
    remediation_method: str,
    actual_embedment_mm: int,
    plumb_deviation_mm: float,
) -> Json:
    return get_success_data(
        api.create_remediation(
            pile_id,
            f.remediation_payload(
                remediation_method, actual_embedment_mm, plumb_deviation_mm
            ),
            INSTALLATION_FOREMAN,
        )
    )


def driven_pile(api, block_id: str, **overrides: Any) -> Json:
    """A single pile driven to design and accepted, which completes a one-pile block."""
    pile = create_pile(api, block_id, **overrides)
    record_drive_result(api, pile["id"])
    return read_pile(api, pile["id"])


def piles_complete_block(
    api, project_id: str, grading_area_id: str, **overrides: Any
) -> Json:
    """A block whose planned piles are all accepted, so it sits at `PILES_COMPLETE`."""
    block = create_block(api, project_id, grading_area_id, **overrides)
    planned = block["planned_pile_count"]
    for index in range(1, planned + 1):
        driven_pile(api, block["id"], row_index=1, position_index=index)
    return read_block(api, block["id"])


def declare_mechanical_completion(api, block_id: str, **overrides: Any) -> Json:
    """Declare tracker and module installation complete for the block."""
    return get_success_data(
        api.declare_mechanical_completion(
            block_id, f.mechanical_completion_payload(**overrides), INSTALLATION_FOREMAN
        )
    )


def mech_complete_block(
    api,
    project_id: str,
    grading_area_id: str,
    *,
    modules_installed_qty: int = 50,
    max_torque_tube_deviation_mm: float = 18.0,
    **overrides: Any,
) -> Json:
    """A block at `MECH_COMPLETE`, which is what allows its strings to be wired."""
    block = piles_complete_block(api, project_id, grading_area_id, **overrides)
    declare_mechanical_completion(
        api,
        block["id"],
        modules_installed_qty=modules_installed_qty,
        max_torque_tube_deviation_mm=max_torque_tube_deviation_mm,
    )
    return read_block(api, block["id"])


# ===========================================================================
# Tier 2: the electrical chain — circuit, wiring, string test
# ===========================================================================
def create_circuit(api, block_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_string_circuit(
            block_id, f.string_circuit_payload(**overrides), INSTALLATION_FOREMAN
        )
    )


def read_circuit(api, circuit_id: str) -> Json:
    return get_success_data(api.get_string_circuit(circuit_id, INSTALLATION_FOREMAN))


def wire_circuit(api, circuit_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_wiring(circuit_id, f.wiring_payload(**overrides), INSTALLATION_FOREMAN)
    )


def record_string_test(api, circuit_id: str, **overrides: Any) -> Json:
    """Record insulation resistance, open-circuit voltage and polarity in one call."""
    return get_success_data(
        api.create_string_test_result(
            circuit_id, f.string_test_payload(**overrides), INSTALLATION_FOREMAN
        )
    )


def wired_circuit(api, block_id: str, **overrides: Any) -> Json:
    """A circuit terminated into its combiner, so its test can be recorded."""
    circuit = create_circuit(api, block_id, **overrides)
    wire_circuit(api, circuit["id"])
    return read_circuit(api, circuit["id"])


def tested_circuit(api, block_id: str, **overrides: Any) -> Json:
    """A circuit whose string test passed, taking the block's electrical side to
    `TESTED`."""
    circuit = wired_circuit(api, block_id, **overrides)
    record_string_test(api, circuit["id"])
    return read_circuit(api, circuit["id"])


# ===========================================================================
# Tier 3: lifecycle shortcuts — a project that is ready for commissioning
# ===========================================================================
def ready_project(api, **project_overrides: Any) -> Json:
    """The whole plant, built in physical order, to the point where the project
    reports itself ready for mechanical completion.

    Returns the rows the chain minted, each re-read at its final state:
    ``project``, ``area``, ``zone``, ``delivery``, ``block`` and ``circuit``.
    """
    project = create_project(api, **project_overrides)
    area = accepted_area(api, project["id"])
    zone = create_yard_zone(api, project["id"])
    delivery = accepted_module_delivery(api, project["id"], zone["id"])
    block = mech_complete_block(api, project["id"], area["id"])
    circuit = tested_circuit(api, block["id"])
    return {
        "project": read_project(api, project["id"]),
        "area": area,
        "zone": read_yard_zone(api, zone["id"]),
        "delivery": delivery,
        "block": read_block(api, block["id"]),
        "circuit": circuit,
    }


# ===========================================================================
# Tier 3: the interconnection chain — substation, outage window, energization
# ===========================================================================
def request_outage_window(api, substation_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_outage_window(
            substation_id, f.outage_window_payload(**overrides), UTILITY_COORDINATOR
        )
    )


def answer_outage_window(api, window_id: str, decision: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_utility_response(
            window_id, f.utility_response_payload(decision, **overrides), UTILITY_COORDINATOR
        )
    )


def read_outage_window(api, window_id: str) -> Json:
    return get_success_data(api.get_outage_window(window_id, UTILITY_COORDINATOR))


def advance_substation(
    api, substation_id: str, to_status: str, witness_ref: str
) -> Json:
    return get_success_data(
        api.create_status_advance(
            substation_id,
            f.status_advance_payload(to_status, witness_ref),
            UTILITY_COORDINATOR,
        )
    )


def approved_outage_window(api, substation_id: str, **overrides: Any) -> Json:
    """A backfeed outage the utility has approved, which is the permission
    energization is checked against."""
    window = request_outage_window(api, substation_id, **overrides)
    answer_outage_window(api, window["id"], "APPROVE")
    return read_outage_window(api, window["id"])


def substation_at_backfeed_requested(api, project_id: str, **overrides: Any) -> Json:
    """A substation walked one step at a time up to `BACKFEED_REQUESTED`, with an
    approved backfeed window already on file."""
    substation = create_substation(api, project_id, **overrides)
    approved_outage_window(api, substation["id"])
    advance_substation(api, substation["id"], "STEEL_ERECTED", "W-1")
    advance_substation(api, substation["id"], "EQUIPMENT_SET", "W-2")
    advance_substation(api, substation["id"], "BACKFEED_REQUESTED", "W-3")
    return read_substation(api, substation["id"])


def energize_substation(api, project_id: str, **overrides: Any) -> Json:
    """Take a substation all the way to `ENERGIZED`, with the clock moved inside
    the approved window so energization is admissible."""
    substation = substation_at_backfeed_requested(api, project_id, **overrides)
    set_clock(api, INSIDE_OUTAGE)
    advance_substation(api, substation["id"], "ENERGIZED", "W-4")
    return read_substation(api, substation["id"])


def energized_project(api, **project_overrides: Any) -> Json:
    """A ready project whose substation is energized, i.e. everything a
    commissioning test needs before it can be finalized.

    Adds ``substation`` to the rows :func:`ready_project` returns.
    """
    rows = ready_project(api, **project_overrides)
    substation = energize_substation(api, rows["project"]["id"])
    rows["substation"] = substation
    rows["project"] = read_project(api, rows["project"]["id"])
    return rows


# ===========================================================================
# Tier 4: commissioning — scheduling, intervals, finalization
# ===========================================================================
def schedule_commissioning_test(
    api,
    project_id: str,
    *,
    test_type: str = "CAPACITY",
    expected_version: Optional[int] = None,
    **overrides: Any,
) -> Json:
    """Schedule a test, reading the project's live version when it is not given."""
    version = (
        expected_version
        if expected_version is not None
        else project_version(api, project_id)
    )
    payload = f.commissioning_test_payload(
        project_id, version, test_type=test_type, **overrides
    )
    return get_success_data(api.create_commissioning_test(payload, COMMISSIONING_ENGINEER))


def read_commissioning_test(api, test_id: str) -> Json:
    return get_success_data(api.get_commissioning_test(test_id, COMMISSIONING_ENGINEER))


def append_interval(
    api,
    test_id: str,
    sampled_at: str,
    irradiance_w_m2: float,
    measured_kw_ac: float,
    **overrides: Any,
) -> Json:
    return get_success_data(
        api.create_test_interval(
            test_id,
            f.interval_payload(
                sampled_at, irradiance_w_m2, measured_kw_ac, **overrides
            ),
            COMMISSIONING_ENGINEER,
        )
    )


def finalize_test(api, test_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.finalize_commissioning_test(
            test_id, f.finalization_payload(**overrides), COMMISSIONING_ENGINEER
        )
    )


def append_intervals(api, test_id: str, samples: List[Json]) -> List[Json]:
    """Append a list of interval payload keyword sets in the order given."""
    return [
        append_interval(
            api,
            test_id,
            sample["sampled_at"],
            sample["irradiance_w_m2"],
            sample["measured_kw_ac"],
            **{
                key: value
                for key, value in sample.items()
                if key
                not in {"sampled_at", "irradiance_w_m2", "measured_kw_ac"}
            },
        )
        for sample in samples
    ]


# ===========================================================================
# Tier 4: punch list — submission, decision, closure
# ===========================================================================
def submit_closure(api, item_id: str, **overrides: Any) -> Json:
    """Closure evidence, submitted by the foreman whose identity is recorded."""
    return get_success_data(
        api.create_closure_submission(
            item_id, f.closure_submission_payload(**overrides), INSTALLATION_FOREMAN
        )
    )


def decide_closure(api, item_id: str, decision: str, **overrides: Any) -> Json:
    """The owner's verdict on a submitted closure, taken by a different operator."""
    return get_success_data(
        api.create_closure_decision(
            item_id, f.closure_decision_payload(decision, **overrides), OWNER_ENGINEER
        )
    )


def submitted_punch_item(api, project_id: str, **overrides: Any) -> Json:
    """A punch item awaiting the owner's verdict."""
    item = create_punch_item(api, project_id, **overrides)
    submit_closure(api, item["id"])
    return read_punch_item(api, item["id"])


def closed_punch_item(api, project_id: str, **overrides: Any) -> Json:
    """A punch item the owner approved, so it no longer counts as open."""
    item = submitted_punch_item(api, project_id, **overrides)
    decide_closure(api, item["id"], "APPROVE")
    return read_punch_item(api, item["id"])


def waived_punch_item(api, project_id: str, **overrides: Any) -> Json:
    """A punch item the owner waived, the other way an item stops being open."""
    item = submitted_punch_item(api, project_id, **overrides)
    decide_closure(api, item["id"], "WAIVE")
    return read_punch_item(api, item["id"])


# ===========================================================================
# Tier 4: certified payroll — entries, voids, certification, compliance runs
# ===========================================================================
def post_labor_entry(api, week_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_labor_entry(
            week_id, f.labor_entry_payload(**overrides), LABOR_COMPLIANCE_OFFICER
        )
    )


def read_labor_entry(api, entry_id: str) -> Json:
    return get_success_data(api.get_labor_entry(entry_id, LABOR_COMPLIANCE_OFFICER))


def void_labor_entry(api, entry_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.void_labor_entry(
            entry_id, f.void_payload(**overrides), LABOR_COMPLIANCE_OFFICER
        )
    )


def certify_week(api, week_id: str, **overrides: Any) -> Json:
    """Certify the week under a second operator, since the officer who posted a
    still-posted line may not certify it."""
    return get_success_data(
        api.certify_payroll_week(
            week_id, f.certification_payload(**overrides), LABOR_COMPLIANCE_OFFICER_ALT
        )
    )


def week_with_entries(
    api, project_id: str, entries: List[Json], *, week_start_date: str = "2026-08-03"
) -> Json:
    """An open week carrying the given lines, then re-read with its hour ledger."""
    week = create_payroll_week(api, project_id, week_start_date=week_start_date)
    for entry in entries:
        post_labor_entry(api, week["id"], **entry)
    return read_payroll_week(api, week["id"])


def certified_week(
    api, project_id: str, entries: List[Json], *, week_start_date: str = "2026-08-03"
) -> Json:
    """A week whose lines are posted and which is then locked by certification."""
    week = week_with_entries(
        api, project_id, entries, week_start_date=week_start_date
    )
    certify_week(api, week["id"])
    return read_payroll_week(api, week["id"])


def run_labor_compliance(api, project_id: str, **overrides: Any) -> Json:
    """Recompute apprenticeship compliance, wage restitution and tax-credit status."""
    return get_success_data(
        api.create_labor_compliance_run(
            project_id,
            f.labor_compliance_run_payload(**overrides),
            LABOR_COMPLIANCE_OFFICER,
        )
    )


# ===========================================================================
# Tier 5: scope and milestones — the terminal ladder
# ===========================================================================
def add_change_order(api, project_id: str, amount_cents: int, **overrides: Any) -> Json:
    return get_success_data(
        api.create_change_order(
            project_id,
            f.change_order_payload(amount_cents, **overrides),
            EPC_PROJECT_MANAGER,
        )
    )


def claim_milestone(api, project_id: str, milestone_kind: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_milestone_claim(
            project_id,
            f.milestone_claim_payload(milestone_kind, **overrides),
            EPC_PROJECT_MANAGER,
        )
    )


def decide_milestone(
    api, project_id: str, milestone_kind: str, decision: str, **overrides: Any
) -> Json:
    """The owner's verdict on the outstanding claim, taken by a different operator
    from the one who filed it."""
    return get_success_data(
        api.create_milestone_decision(
            project_id,
            f.milestone_decision_payload(milestone_kind, decision, **overrides),
            OWNER_ENGINEER,
        )
    )


def certify_milestone(api, project_id: str, milestone_kind: str) -> Json:
    """File a claim and certify it, i.e. one full rung of the milestone ladder."""
    claim_milestone(api, project_id, milestone_kind)
    decide_milestone(api, project_id, milestone_kind, "CERTIFY")
    return read_project(api, project_id)
