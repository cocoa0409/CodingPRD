"""State-machine behaviour of the Utility-Scale Solar EPC API.

Each test drives one declared transition — or one refusal of a transition the
state machine does not admit — and checks the side effects the PRD attaches to
it: the fields it stores, the sibling entities it moves, the derived rollups it
recomputes, and the state it leaves behind when it refuses.
"""

import pytest

from test_helpers import (
    assert_zone_occupancy,
    factories as f,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    INSIDE_OUTAGE,
    OUTAGE_END,
    OUTAGE_START,
    accepted_module_delivery,
    advance_substation,
    answer_outage_window,
    approved_outage_window,
    create_block,
    create_grading_area,
    create_payroll_week,
    create_punch_item,
    create_substation,
    create_yard_zone,
    declare_mechanical_completion,
    graded_area,
    log_clearing,
    log_grading,
    mech_complete_block,
    piles_complete_block,
    read_block,
    read_grading_area,
    read_outage_window,
    read_payroll_week,
    read_project,
    read_punch_item,
    read_substation,
    read_yard_zone,
    receive_delivery,
    reinstate_permit,
    request_outage_window,
    reserve_delivery,
    set_clock,
    substation_at_backfeed_requested,
    suspend_permit,
    wired_circuit,
)
from test_helpers.test_users import make_foreman_headers


# ---------------------------------------------------------------------------
# OutageWindow: REQUESTED -> APPROVED
# ---------------------------------------------------------------------------
def test_utility_approval_moves_the_window_from_requested_to_approved(
    api, project, utility_headers
):
    """The utility's approval advances a requested window to `APPROVED`.

    PRD 3.6: "`APPROVE` drives `REQUESTED → APPROVED`, making the window eligible to be consumed by energization."

    Design: Corner/state_machines/outage_window_request_is_approved_by_the_utility
    """
    substation = create_substation(api, project["id"])
    window = request_outage_window(api, substation["id"])
    assert window["status"] == "REQUESTED"

    data = validate_success(
        api.create_utility_response(
            window["id"], f.utility_response_payload("APPROVE"), utility_headers
        )
    )

    assert data["status"] == "APPROVED"


def test_utility_approval_stores_the_reference_and_bumps_the_window_version_once(
    api, project, utility_headers
):
    """The recorded response stores its reference, stamps the answer and gains one version.

    PRD 3.6: "Both decisions store `utility_reference` and stamp `responded_at`, and both increment the window's `version` by 1."

    Design: Corner/state_machines/outage_window_request_is_approved_by_the_utility
    """
    substation = create_substation(api, project["id"])
    window = request_outage_window(api, substation["id"])
    assert window["utility_reference"] is None
    assert window["responded_at"] is None
    version_before = window["version"]

    data = validate_success(
        api.create_utility_response(
            window["id"],
            f.utility_response_payload("APPROVE", utility_reference="SO-4471"),
            utility_headers,
        )
    )

    assert data["utility_reference"] == "SO-4471"
    assert data["responded_at"] is not None
    assert data["version"] == version_before + 1


def test_approving_a_window_energizes_nothing_by_itself(api, project, utility_headers):
    """An approval leaves the facility unenergized and unlinked to any window.

    PRD 3.6: "When one does, the facility's `status` becomes `ENERGIZED`, `energized_at` is stamped with the current logical-clock instant, `energizing_outage_window_id` records the `id` of the window that was consumed, and that window itself transitions `APPROVED → EXECUTED` with its own `version` incremented by 1 alongside the facility's."

    Design: Corner/state_machines/outage_window_request_is_approved_by_the_utility
    """
    substation = create_substation(api, project["id"])
    window = request_outage_window(api, substation["id"])
    answer_outage_window(api, window["id"], "APPROVE")

    after = read_substation(api, substation["id"])
    assert after["status"] == "SITE_CIVIL"
    assert after["energized_at"] is None
    assert after["energizing_outage_window_id"] is None
    assert read_outage_window(api, window["id"])["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# GradingArea: GRADED -> ACCEPTED, and its refusal from CLEARED
# ---------------------------------------------------------------------------
def test_acceptance_of_a_merely_cleared_area_is_refused(api, project, owner_headers):
    """An area that has only been cleared cannot be accepted, however good the survey.

    PRD 3.2: "Acceptance requires the area to be `GRADED` — any other status is `ERR_GRADING_AREA_NOT_OPEN_FOR_WORK` — and requires the permit to be `ACTIVE` with no open BMP deficiency, failing which it is `ERR_PERMIT_NOT_ACTIVE`."

    Design: Corner/state_machines/grading_area_acceptance_before_grading_is_rejected
    """
    area = create_grading_area(api, project["id"])
    log_clearing(api, area["id"], acreage=10.00)
    assert read_grading_area(api, area["id"])["status"] == "CLEARED"

    validate_error(
        api.accept_grading_area(area["id"], f.acceptance_payload(96.5, True), owner_headers),
        "ERR_GRADING_AREA_NOT_OPEN_FOR_WORK",
    )

    after = read_grading_area(api, area["id"])
    assert after["status"] == "CLEARED"
    assert after["compaction_test_pct"] is None
    assert after["drainage_inspection_passed"] is None
    assert after["disturbed_acreage_current"] == pytest.approx(10.00, abs=0.01)


def test_the_same_acceptance_succeeds_once_the_grading_log_lands(
    api, project, owner_headers
):
    """Once the area reaches `GRADED` the identical acceptance drives it to `ACCEPTED`.

    PRD 3.2: "Civil work ends with owner acceptance, which is the `OwnerEngineer`'s prerogative and drives `GRADED → ACCEPTED`."

    Design: Corner/state_machines/grading_area_acceptance_before_grading_is_rejected
    """
    area = create_grading_area(api, project["id"])
    log_clearing(api, area["id"], acreage=10.00)
    log_grading(api, area["id"], acreage=8.00)
    assert read_grading_area(api, area["id"])["status"] == "GRADED"

    data = validate_success(
        api.accept_grading_area(area["id"], f.acceptance_payload(96.5, True), owner_headers)
    )

    assert data["status"] == "ACCEPTED"
    assert data["compaction_test_pct"] == pytest.approx(96.5, abs=0.01)
    assert data["drainage_inspection_passed"] is True
    assert data["disturbed_acreage_current"] == pytest.approx(18.00, abs=0.01)


# ---------------------------------------------------------------------------
# Block: PILES_COMPLETE -> MECH_COMPLETE
# ---------------------------------------------------------------------------
def test_mechanical_completion_stores_the_two_measurements_and_moves_the_dimension(
    api, project, accepted_grading_area, foreman_headers
):
    """The declaration stores what the field reported and advances the mechanical side.

    PRD 3.4: "On success the two reported measurements are stored, `mechanical_status` becomes `MECH_COMPLETE`, and `mc_ready` is recomputed."

    Design: Corner/state_machines/mechanical_completion_stores_measurements_and_recomputes_readiness
    """
    zone = create_yard_zone(api, project["id"])
    accepted_module_delivery(api, project["id"], zone["id"])
    block = piles_complete_block(api, project["id"], accepted_grading_area["id"])
    assert block["mechanical_status"] == "PILES_COMPLETE"
    assert block["piles_accepted_count"] == 1
    version_before = block["version"]

    data = validate_success(
        api.declare_mechanical_completion(
            block["id"], f.mechanical_completion_payload(50, 18.0), foreman_headers
        )
    )

    assert data["mechanical_status"] == "MECH_COMPLETE"
    assert data["modules_installed_qty"] == 50
    assert data["max_torque_tube_deviation_mm"] == pytest.approx(18.0, abs=0.01)
    assert data["version"] == version_before + 1


def test_mechanical_completion_leaves_mc_ready_false_while_the_strings_are_untested(
    api, project, accepted_grading_area
):
    """`mc_ready` needs both dimensions, so the mechanical half alone does not set it.

    PRD 3.4: "They are joined at exactly one point — the derived boolean `mc_ready`, which is true if and only if `mechanical_status` is `MECH_COMPLETE` **and** `electrical_status` is `TESTED`, and false in every other combination."

    Design: Corner/state_machines/mechanical_completion_stores_measurements_and_recomputes_readiness
    """
    zone = create_yard_zone(api, project["id"])
    accepted_module_delivery(api, project["id"], zone["id"])
    block = piles_complete_block(api, project["id"], accepted_grading_area["id"])
    declare_mechanical_completion(api, block["id"])

    after = read_block(api, block["id"])
    assert after["mechanical_status"] == "MECH_COMPLETE"
    assert after["electrical_status"] == "PLANNED"
    assert after["mc_ready"] is False

    project_after = read_project(api, project["id"])
    assert project_after["blocks_total"] == 1
    assert project_after["blocks_mc_ready_count"] == 0
    assert project_after["mc_readiness"] == "BLOCKED"


# ---------------------------------------------------------------------------
# Substation: the strictly sequential ladder
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("to_status", ["ENERGIZED", "EQUIPMENT_SET"])
def test_substation_advance_that_skips_a_step_is_refused(
    api, project, utility_headers, to_status
):
    """From `SITE_CIVIL` every target but the immediate successor is refused.

    PRD 3.6: "Steps may be neither skipped nor repeated: a `to_status` that is not the immediate successor of the facility's current `status` is refused with `ERR_SUBSTATION_STEP_NOT_SEQUENTIAL`."

    Design: Corner/state_machines/substation_cannot_skip_directly_from_site_civil_to_energized
    """
    substation = create_substation(api, project["id"])
    version_before = substation["version"]

    validate_error(
        api.create_status_advance(
            substation["id"], f.status_advance_payload(to_status, "W-1"), utility_headers
        ),
        "ERR_SUBSTATION_STEP_NOT_SEQUENTIAL",
    )

    after = read_substation(api, substation["id"])
    assert after["status"] == "SITE_CIVIL"
    assert after["utility_witness_ref"] is None
    assert after["version"] == version_before


def test_the_one_legal_step_out_of_site_civil_is_accepted(api, project, utility_headers):
    """The immediate successor is admitted, recording its witness reference.

    PRD 3.6: "Every accepted advance overwrites `utility_witness_ref` with the value supplied and increments the facility's `version` by 1."

    Design: Corner/state_machines/substation_cannot_skip_directly_from_site_civil_to_energized
    """
    substation = create_substation(api, project["id"])
    version_before = substation["version"]

    data = validate_success(
        api.create_status_advance(
            substation["id"],
            f.status_advance_payload("STEEL_ERECTED", "W-1"),
            utility_headers,
        )
    )

    assert data["status"] == "STEEL_ERECTED"
    assert data["utility_witness_ref"] == "W-1"
    assert data["version"] == version_before + 1


# ---------------------------------------------------------------------------
# Declared initial states, one entity at a time
# ---------------------------------------------------------------------------
def test_new_project_starts_at_preconstruction_and_blocked(api, epc_headers):
    """A project is born before construction, unready, at version 1.

    PRD 3.1: "A newly persisted project has `version` 1 and every derived field at rest."

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
    """
    data = validate_success(
        api.create_project(f.project_payload(), epc_headers), expected_status=201
    )

    assert data["milestone_state"] == "PRECONSTRUCTION"
    assert data["mc_readiness"] == "BLOCKED"
    assert data["version"] == 1


def test_new_grading_area_starts_planned_under_an_active_permit(
    api, project, civil_headers
):
    """A fresh area is planned and covered, with nothing disturbed and no hold captured.

    PRD 3.2: "The new area begins with `status` `PLANNED` and `permit_status` `ACTIVE`."

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
    """
    data = validate_success(
        api.create_grading_area(project["id"], f.grading_area_payload(), civil_headers),
        expected_status=201,
    )

    assert data["status"] == "PLANNED"
    assert data["permit_status"] == "ACTIVE"
    assert data["disturbed_acreage_current"] == pytest.approx(0, abs=0.01)
    assert data["bmp_deficiency_open"] is False
    assert data["status_before_hold"] is None


def test_new_delivery_starts_reserved_with_every_receipt_figure_null(
    api, project, procurement_headers
):
    """A reservation is persisted at `RESERVED` before any truck has been counted.

    PRD 3.3: "When the check passes, the delivery is persisted with `status` `RESERVED`, its `received_unit_qty`, `damaged_unit_qty`, `accepted_unit_qty`, `damage_ratio` and `cancel_reason` all null, and the zone's `reserved_pallets` and `available_pallets` are recomputed with the zone's `version` incremented by 1."

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
    """
    zone = create_yard_zone(api, project["id"], pallet_capacity=100)

    data = validate_success(
        api.create_delivery(
            f.delivery_payload(project["id"], zone["id"], zone["version"]),
            procurement_headers,
        ),
        expected_status=201,
    )

    assert data["status"] == "RESERVED"
    assert data["received_unit_qty"] is None
    assert data["damaged_unit_qty"] is None
    assert data["accepted_unit_qty"] is None
    assert data["damage_ratio"] is None
    assert data["cancel_reason"] is None
    assert_zone_occupancy(
        read_yard_zone(api, zone["id"]), reserved_pallets=60, available_pallets=40
    )


def test_new_block_starts_planned_on_both_parallel_dimensions(
    api, project, accepted_grading_area, epc_headers
):
    """Both progress dimensions start at `PLANNED`, so the block is not yet ready.

    PRD 3.4: "A fresh block therefore starts with both dimensions at `PLANNED` and `mc_ready` false."

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
    """
    data = validate_success(
        api.create_block(
            project["id"], f.block_payload(accepted_grading_area["id"]), epc_headers
        ),
        expected_status=201,
    )

    assert data["mechanical_status"] == "PLANNED"
    assert data["electrical_status"] == "PLANNED"
    assert data["mc_ready"] is False


def test_new_pile_starts_planned_with_no_drive_recorded(
    api, project, accepted_grading_area, foreman_headers
):
    """A registered pile location carries no measurements until it is driven.

    PRD 3.4: "A registered pile begins at `PLANNED` with `actual_embedment_mm`, `plumb_deviation_mm`, `blow_count`, `driven_at` and `remediation_method` all null, `refusal_flag` false and `remediated` false."

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
    """
    block = create_block(api, project["id"], accepted_grading_area["id"])

    data = validate_success(
        api.create_pile(block["id"], f.pile_payload(), foreman_headers),
        expected_status=201,
    )

    assert data["status"] == "PLANNED"
    for field in (
        "actual_embedment_mm",
        "plumb_deviation_mm",
        "blow_count",
        "driven_at",
        "remediation_method",
    ):
        assert data[field] is None, f"{field} must start null, got {data[field]!r}"
    assert data["refusal_flag"] is False
    assert data["remediated"] is False


def test_new_string_circuit_starts_planned_with_no_test_recorded(
    api, project, accepted_grading_area, foreman_headers
):
    """A registered circuit carries neither a combiner position nor any test figure.

    PRD 3.5: "A registered circuit starts at `PLANNED` with `combiner_position`, `insulation_resistance_mohm`, `measured_voc_v`, `expected_voc_v`, `polarity_ok`, `test_failure_reason` and `tested_at` all null."

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
    """
    block = create_block(api, project["id"], accepted_grading_area["id"])

    data = validate_success(
        api.create_string_circuit(
            block["id"], f.string_circuit_payload(), foreman_headers
        ),
        expected_status=201,
    )

    assert data["status"] == "PLANNED"
    for field in (
        "combiner_position",
        "insulation_resistance_mohm",
        "measured_voc_v",
        "expected_voc_v",
        "polarity_ok",
        "test_failure_reason",
        "tested_at",
    ):
        assert data[field] is None, f"{field} must start null, got {data[field]!r}"


def test_new_substation_starts_at_site_civil_and_leaves_the_project_alone(
    api, project, utility_headers
):
    """The facility record begins at the first rung of the ladder, unenergized.

    PRD 3.6: "A new facility begins at `SITE_CIVIL` with `utility_witness_ref`, `energized_at` and `energizing_outage_window_id` all null, and its creation leaves the project's `version` untouched."

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
    """
    version_before = project["version"]

    data = validate_success(
        api.create_substation(project["id"], f.substation_payload(), utility_headers),
        expected_status=201,
    )

    assert data["status"] == "SITE_CIVIL"
    assert data["utility_witness_ref"] is None
    assert data["energized_at"] is None
    assert data["energizing_outage_window_id"] is None
    assert read_project(api, project["id"])["version"] == version_before


def test_new_outage_window_starts_requested_and_unanswered(
    api, project, utility_headers
):
    """A requested outage waits for the utility, touching no parent version.

    PRD 3.6: "The request is persisted at `REQUESTED` with `utility_reference` and `responded_at` null, and it bumps no parent version."

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
    """
    substation = create_substation(api, project["id"])
    version_before = substation["version"]

    data = validate_success(
        api.create_outage_window(
            substation["id"], f.outage_window_payload(), utility_headers
        ),
        expected_status=201,
    )

    assert data["status"] == "REQUESTED"
    assert data["utility_reference"] is None
    assert data["responded_at"] is None
    assert read_substation(api, substation["id"])["version"] == version_before


def test_new_punch_list_item_starts_open_and_unsubmitted(api, project, owner_headers):
    """A raised defect is open, with no evidence, no operator and no rejection yet.

    PRD 3.9: "A new item starts at `OPEN` with `closure_evidence_ref`, `submitted_by_user_id` and `decided_by_user_id` null and `rejection_count` at 0."

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
    """
    data = validate_success(
        api.create_punch_list_item(
            project["id"], f.punch_list_item_payload(), owner_headers
        ),
        expected_status=201,
    )

    assert data["status"] == "OPEN"
    assert data["closure_evidence_ref"] is None
    assert data["submitted_by_user_id"] is None
    assert data["decided_by_user_id"] is None
    assert data["rejection_count"] == 0


def test_new_payroll_week_starts_open_with_an_empty_hour_ledger(
    api, project, labor_headers
):
    """A freshly opened week carries no lines and no certification.

    PRD 3.8: "A new week starts at `OPEN` with `entry_count`, `total_hours`, `apprentice_hours`, `journeyworker_hours` and `apprentice_pct` all 0, and `certified_by_user_id` and `certified_at` null."

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
    """
    data = validate_success(
        api.create_payroll_week(project["id"], f.payroll_week_payload(), labor_headers),
        expected_status=201,
    )

    assert data["status"] == "OPEN"
    for field in (
        "entry_count",
        "total_hours",
        "apprentice_hours",
        "journeyworker_hours",
        "apprentice_pct",
    ):
        assert data[field] == 0, f"{field} must start at 0, got {data[field]!r}"
    assert data["certified_by_user_id"] is None
    assert data["certified_at"] is None


def test_new_labor_entry_is_persisted_at_posted(api, project, labor_headers):
    """An admissible payroll line lands at `POSTED`.

    PRD 3.8: "An accepted line is persisted at `POSTED` and immediately re-derives its week's hour ledger."

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
    """
    week = create_payroll_week(api, project["id"])

    data = validate_success(
        api.create_labor_entry(week["id"], f.labor_entry_payload(), labor_headers),
        expected_status=201,
    )

    assert data["status"] == "POSTED"
    assert read_payroll_week(api, week["id"])["entry_count"] == 1


def test_new_commissioning_test_starts_scheduled_with_no_results(
    api, project, commissioning_headers
):
    """A scheduled test holds no intervals and no reported figures.

    PRD 3.7: "The new test is persisted at `SCHEDULED` with `interval_count` and `valid_interval_count` at 0, `reported_kw_ac`, `reported_performance_ratio`, `pass_threshold_kw_ac`, `finalized_at`, `suspend_reason` and `void_reason` all null, and `superseded` false."

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
    """
    data = validate_success(
        api.create_commissioning_test(
            f.commissioning_test_payload(project["id"], project["version"]),
            commissioning_headers,
        ),
        expected_status=201,
    )

    assert data["status"] == "SCHEDULED"
    assert data["interval_count"] == 0
    assert data["valid_interval_count"] == 0
    for field in (
        "reported_kw_ac",
        "reported_performance_ratio",
        "pass_threshold_kw_ac",
        "finalized_at",
        "suspend_reason",
        "void_reason",
    ):
        assert data[field] is None, f"{field} must start null, got {data[field]!r}"
    assert data["superseded"] is False


def test_commissioning_test_correction_variant_defaults_to_as_measured(
    api, project, commissioning_headers
):
    """An omitted correction selector falls back to the as-measured variant.

    PRD 3.7: "It may also carry a `correction_variant`, which defaults to `AS_MEASURED` and whose only other value is `WEATHER_CORRECTED`."

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
    """
    data = validate_success(
        api.create_commissioning_test(
            f.commissioning_test_payload(project["id"], project["version"]),
            commissioning_headers,
        ),
        expected_status=201,
    )

    assert data["correction_variant"] == "AS_MEASURED"


# ---------------------------------------------------------------------------
# Delivery: ACCEPTED is terminal
# ---------------------------------------------------------------------------
def test_accepted_delivery_refuses_cancellation_and_keeps_its_pallets(
    api, project, procurement_headers
):
    """Cancellation is only for a reservation still standing, and it releases nothing here.

    PRD 3.3: "Cancellation requires the delivery to still be `RESERVED` — otherwise `ERR_DELIVERY_NOT_RESERVED` — takes a mandatory `cancel_reason`, and is the compensating action of the pallet ledger: it moves the delivery `RESERVED → CANCELLED`, stores the reason, recomputes the zone's `reserved_pallets` and `available_pallets` with this delivery excluded, increments the zone's `version` by 1, and increments the delivery's own `version` by 1."

    Design: Corner/state_machines/accepted_delivery_cannot_be_cancelled
    """
    zone = create_yard_zone(api, project["id"], pallet_capacity=100)
    delivery = reserve_delivery(api, project["id"], zone["id"], unit_qty=60, pallets=60)
    accepted = receive_delivery(api, delivery["id"], 60, 3)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["accepted_unit_qty"] == 57
    version_before = accepted["version"]

    validate_error(
        api.cancel_delivery(
            delivery["id"], f.cancellation_payload(), procurement_headers
        ),
        "ERR_DELIVERY_NOT_RESERVED",
    )

    after = validate_success(api.get_delivery(delivery["id"], procurement_headers))
    assert after["status"] == "ACCEPTED"
    assert after["cancel_reason"] is None
    assert after["version"] == version_before
    assert_zone_occupancy(
        read_yard_zone(api, zone["id"]), reserved_pallets=60, available_pallets=40
    )


def test_accepted_delivery_refuses_a_second_receipt(api, project, procurement_headers):
    """A shipment already counted off the truck cannot be received again.

    PRD 3.3: "The delivery must still be `RESERVED`; anything else is `ERR_DELIVERY_NOT_RESERVED`."

    Design: Corner/state_machines/accepted_delivery_cannot_be_cancelled
    """
    zone = create_yard_zone(api, project["id"], pallet_capacity=100)
    delivery = reserve_delivery(api, project["id"], zone["id"], unit_qty=60, pallets=60)
    receive_delivery(api, delivery["id"], 60, 3)

    validate_error(
        api.receive_delivery(
            delivery["id"], f.receipt_payload(60, 0), procurement_headers
        ),
        "ERR_DELIVERY_NOT_RESERVED",
    )

    after = validate_success(api.get_delivery(delivery["id"], procurement_headers))
    assert after["status"] == "ACCEPTED"
    assert after["damaged_unit_qty"] == 3
    assert after["accepted_unit_qty"] == 57


# ---------------------------------------------------------------------------
# PunchListItem: OPEN -> CLOSURE_SUBMITTED, and the refused replay
# ---------------------------------------------------------------------------
def test_closure_submission_records_the_evidence_and_its_submitter(api, project):
    """The first submission moves the item and records who supplied the evidence.

    PRD 3.9: "The item moves `OPEN → CLOSURE_SUBMITTED`, the reference is stored, `submitted_by_user_id` records the submitting `X-User-ID`, and the item's `version` increments by 1."

    Design: Corner/state_machines/repeat_closure_submission_on_the_same_item_is_rejected
    """
    item = create_punch_item(api, project["id"])
    headers = make_foreman_headers("IF-7")

    data = validate_success(
        api.create_closure_submission(
            item["id"], f.closure_submission_payload("PHOTO-001"), headers
        )
    )

    assert data["status"] == "CLOSURE_SUBMITTED"
    assert data["closure_evidence_ref"] == "PHOTO-001"
    assert data["submitted_by_user_id"] == "IF-7"
    assert data["version"] == item["version"] + 1


def test_replayed_closure_submission_is_refused_and_changes_nothing(api, project):
    """A second submission on the same item is refused, evidence and counters intact.

    PRD 3.9: "Submitting on an item that is not `OPEN` is refused with `ERR_PUNCH_ITEM_STATE_INVALID`, and because neither counter changes, the project's `version` is untouched."

    Design: Corner/state_machines/repeat_closure_submission_on_the_same_item_is_rejected
    """
    item = create_punch_item(api, project["id"])
    headers = make_foreman_headers("IF-7")
    first = validate_success(
        api.create_closure_submission(
            item["id"], f.closure_submission_payload("PHOTO-001"), headers
        )
    )
    project_version_before = read_project(api, project["id"])["version"]

    validate_error(
        api.create_closure_submission(
            item["id"], f.closure_submission_payload("PHOTO-002"), headers
        ),
        "ERR_PUNCH_ITEM_STATE_INVALID",
    )

    after = read_punch_item(api, item["id"])
    assert after["status"] == "CLOSURE_SUBMITTED"
    assert after["closure_evidence_ref"] == "PHOTO-001"
    assert after["version"] == first["version"]
    assert after["rejection_count"] == 0

    project_after = read_project(api, project["id"])
    assert project_after["version"] == project_version_before
    assert project_after["open_punch_item_count"] == 1


# ---------------------------------------------------------------------------
# Project readiness: a derived verdict that follows its children
# ---------------------------------------------------------------------------
def test_project_stays_blocked_while_its_only_circuit_is_merely_wired(
    api, project, accepted_grading_area
):
    """Readiness needs every block ready, and a wired-but-untested block is not.

    PRD 3.5: "`mc_readiness` is `READY` when the project has at least one block, when `blocks_mc_ready_count` equals `blocks_total`, and when every grading area of the project has `status` `ACCEPTED`; in every other case it is `BLOCKED`."

    Design: Corner/state_machines/project_readiness_bubbles_up_when_every_block_and_area_is_ready
    """
    zone = create_yard_zone(api, project["id"])
    accepted_module_delivery(api, project["id"], zone["id"])
    block = mech_complete_block(api, project["id"], accepted_grading_area["id"])
    circuit = wired_circuit(api, block["id"])
    assert circuit["status"] == "WIRED"

    after = read_project(api, project["id"])
    assert after["blocks_total"] == 1
    assert after["blocks_mc_ready_count"] == 0
    assert after["mc_readiness"] == "BLOCKED"


def test_the_last_passing_string_test_flips_project_readiness_to_ready(
    api, project, accepted_grading_area, foreman_headers
):
    """The final child event carries the block, and with it the project, into readiness.

    PRD 3.5: "The block's `circuits_tested_count` — the number of its circuits at `TESTED` — is re-derived; when it reaches `planned_string_count` with `circuits_failed_count` at 0, the block's electrical dimension advances `WIRED → TESTED`, `mc_ready` is recomputed, and if `mc_ready` flips to true the project's `blocks_mc_ready_count` is incremented and its `mc_readiness` recomputed."

    Design: Corner/state_machines/project_readiness_bubbles_up_when_every_block_and_area_is_ready
    """
    zone = create_yard_zone(api, project["id"])
    accepted_module_delivery(api, project["id"], zone["id"])
    block = mech_complete_block(api, project["id"], accepted_grading_area["id"])
    circuit = wired_circuit(api, block["id"])

    data = validate_success(
        api.create_string_test_result(
            circuit["id"], f.string_test_payload(55.0, 705.00, 40, True), foreman_headers
        )
    )
    assert data["status"] == "TESTED"

    block_after = read_block(api, block["id"])
    assert block_after["mechanical_status"] == "MECH_COMPLETE"
    assert block_after["electrical_status"] == "TESTED"
    assert block_after["mc_ready"] is True

    project_after = read_project(api, project["id"])
    assert project_after["blocks_mc_ready_count"] == 1
    assert project_after["mc_readiness"] == "READY"


# ---------------------------------------------------------------------------
# Substation: BACKFEED_REQUESTED -> ENERGIZED consumes one approved window
# ---------------------------------------------------------------------------
def test_energization_consumes_the_covering_window_and_marks_it_executed(
    api, project, utility_headers
):
    """The advance stamps the facility and drives the covering window to `EXECUTED`.

    PRD 3.6: "When one does, the facility's `status` becomes `ENERGIZED`, `energized_at` is stamped with the current logical-clock instant, `energizing_outage_window_id` records the `id` of the window that was consumed, and that window itself transitions `APPROVED → EXECUTED` with its own `version` incremented by 1 alongside the facility's."

    Design: Corner/state_machines/energization_marks_the_approved_backfeed_window_executed
    """
    substation = create_substation(api, project["id"])
    backfeed = approved_outage_window(
        api, substation["id"], start_at=OUTAGE_START, end_at=OUTAGE_END, purpose="BACKFEED"
    )
    advance_substation(api, substation["id"], "STEEL_ERECTED", "W-1")
    advance_substation(api, substation["id"], "EQUIPMENT_SET", "W-2")
    advance_substation(api, substation["id"], "BACKFEED_REQUESTED", "W-3")
    set_clock(api, INSIDE_OUTAGE)

    data = validate_success(
        api.create_status_advance(
            substation["id"],
            f.status_advance_payload("ENERGIZED", "W-4"),
            utility_headers,
        )
    )

    assert data["status"] == "ENERGIZED"
    assert data["energized_at"].startswith("2026-08-10T02:00:00")
    assert data["energizing_outage_window_id"] == backfeed["id"]

    window_after = read_outage_window(api, backfeed["id"])
    assert window_after["status"] == "EXECUTED"
    assert window_after["version"] == backfeed["version"] + 1


def test_energization_leaves_a_second_approved_window_untouched(
    api, project, utility_headers
):
    """Only the window covering the instant is consumed, and it is recoverable by filter.

    PRD 3.6: "Which window was consumed can be recovered afterwards by listing the facility's outage windows and filtering for `EXECUTED`."

    Design: Corner/state_machines/energization_marks_the_approved_backfeed_window_executed
    """
    substation = create_substation(api, project["id"])
    backfeed = approved_outage_window(
        api, substation["id"], start_at=OUTAGE_START, end_at=OUTAGE_END, purpose="BACKFEED"
    )
    tie_in = approved_outage_window(
        api,
        substation["id"],
        start_at="2026-08-11T00:00:00Z",
        end_at="2026-08-11T04:00:00Z",
        purpose="TIE_IN",
    )
    advance_substation(api, substation["id"], "STEEL_ERECTED", "W-1")
    advance_substation(api, substation["id"], "EQUIPMENT_SET", "W-2")
    advance_substation(api, substation["id"], "BACKFEED_REQUESTED", "W-3")
    set_clock(api, INSIDE_OUTAGE)
    advance_substation(api, substation["id"], "ENERGIZED", "W-4")

    rows, meta = validate_paginated(
        api.list_substation_outage_windows(
            substation["id"], utility_headers, {"status": "EXECUTED"}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [backfeed["id"]]

    tie_in_after = read_outage_window(api, tie_in["id"])
    assert tie_in_after["status"] == "APPROVED"
    assert tie_in_after["version"] == tie_in["version"]


def test_energized_substation_admits_no_further_advance(api, project, utility_headers):
    """`ENERGIZED` has no successor, so any further advance is out of sequence.

    PRD 3.6: "Steps may be neither skipped nor repeated: a `to_status` that is not the immediate successor of the facility's current `status` is refused with `ERR_SUBSTATION_STEP_NOT_SEQUENTIAL`."

    Design: Corner/state_machines/energization_marks_the_approved_backfeed_window_executed
    """
    substation = substation_at_backfeed_requested(api, project["id"])
    set_clock(api, INSIDE_OUTAGE)
    energized = advance_substation(api, substation["id"], "ENERGIZED", "W-4")
    assert energized["status"] == "ENERGIZED"

    validate_error(
        api.create_status_advance(
            substation["id"],
            f.status_advance_payload("ENERGIZED", "W-5"),
            utility_headers,
        ),
        "ERR_SUBSTATION_STEP_NOT_SEQUENTIAL",
    )

    after = read_substation(api, substation["id"])
    assert after["status"] == "ENERGIZED"
    assert after["version"] == energized["version"]


# ---------------------------------------------------------------------------
# Delivery: the REJECTED branch of the receipt fork
# ---------------------------------------------------------------------------
def test_receipt_above_the_damage_threshold_rejects_the_shipment(
    api, project, procurement_headers
):
    """Damage strictly above five percent sends the shipment to `REJECTED`.

    PRD 3.3: "When `damage_ratio` is strictly above 0.05, the delivery moves `ARRIVED → REJECTED` instead."

    Design: Corner/state_machines/rejected_delivery_receipt_releases_the_yard_reservation
    """
    zone = create_yard_zone(api, project["id"], pallet_capacity=100)
    delivery = reserve_delivery(api, project["id"], zone["id"], unit_qty=60, pallets=100)
    assert_zone_occupancy(
        read_yard_zone(api, zone["id"]), reserved_pallets=100, available_pallets=0
    )

    data = validate_success(
        api.receive_delivery(
            delivery["id"], f.receipt_payload(60, 4), procurement_headers
        )
    )

    assert data["damage_ratio"] == pytest.approx(0.0667, abs=0.0001)
    assert data["status"] == "REJECTED"


def test_rejected_receipt_releases_the_pallets_in_the_same_request(
    api, project, procurement_headers
):
    """The refused shipment accepts no units and hands its pallet positions back.

    PRD 3.3: "Its `accepted_unit_qty` is set to 0, contributing nothing to module availability, and the reservation is released: the zone's `reserved_pallets` and `available_pallets` are recomputed with this delivery excluded and the zone's `version` is incremented by 1."

    Design: Corner/state_machines/rejected_delivery_receipt_releases_the_yard_reservation
    """
    zone = create_yard_zone(api, project["id"], pallet_capacity=100)
    delivery = reserve_delivery(api, project["id"], zone["id"], unit_qty=60, pallets=100)
    zone_before = read_yard_zone(api, zone["id"])

    data = validate_success(
        api.receive_delivery(
            delivery["id"], f.receipt_payload(60, 4), procurement_headers
        )
    )

    assert data["accepted_unit_qty"] == 0

    zone_after = read_yard_zone(api, zone["id"])
    assert_zone_occupancy(zone_after, reserved_pallets=0, available_pallets=100)
    assert zone_after["version"] == zone_before["version"] + 1


# ---------------------------------------------------------------------------
# GradingArea: the hold cycle restores what it captured
# ---------------------------------------------------------------------------
def test_permit_suspension_captures_the_status_it_interrupted(api, project):
    """Suspending a cleared area records `CLEARED` before moving it to `HOLD`.

    PRD 3.2: "A `PERMIT_SUSPENSION` is admissible while the area is `PLANNED`, `CLEARED` or `GRADED` with `permit_status` `ACTIVE`; it captures the current status into `status_before_hold`, sets `status` to `HOLD` and `permit_status` to `SUSPENDED`, and — because a non-accepted area forces the project to `BLOCKED` — recomputes the project's `mc_readiness` and increments the project's `version` by 1 when that changes anything."

    Design: Corner/state_machines/permit_reinstatement_restores_the_status_captured_before_hold
    """
    area = create_grading_area(api, project["id"])
    log_clearing(api, area["id"], acreage=10.00)

    suspend_permit(api, area["id"], "2026-08-03T00:00:00Z")

    after = read_grading_area(api, area["id"])
    assert after["status"] == "HOLD"
    assert after["status_before_hold"] == "CLEARED"
    assert after["permit_status"] == "SUSPENDED"


def test_reinstatement_returns_a_cleared_area_to_cleared(api, project):
    """Reinstatement reads the captured status back and clears the capture.

    PRD 3.2: "A `PERMIT_REINSTATEMENT` runs the reverse: it requires `status` `HOLD`, `permit_status` `SUSPENDED` and `bmp_deficiency_open` false, and it restores `status` to whichever of `PLANNED`, `CLEARED` or `GRADED` was captured in `status_before_hold`, clears `status_before_hold` back to null, and returns `permit_status` to `ACTIVE`."

    Design: Corner/state_machines/permit_reinstatement_restores_the_status_captured_before_hold
    """
    area = create_grading_area(api, project["id"])
    log_clearing(api, area["id"], acreage=10.00)
    suspend_permit(api, area["id"], "2026-08-03T00:00:00Z")

    reinstate_permit(api, area["id"], "2026-08-04T00:00:00Z")

    after = read_grading_area(api, area["id"])
    assert after["status"] == "CLEARED"
    assert after["status_before_hold"] is None
    assert after["permit_status"] == "ACTIVE"


def test_reinstatement_returns_a_graded_area_to_graded(api, project):
    """The same endpoint restores `GRADED` when that is what the hold interrupted.

    PRD 3.2: "A `PERMIT_REINSTATEMENT` runs the reverse: it requires `status` `HOLD`, `permit_status` `SUSPENDED` and `bmp_deficiency_open` false, and it restores `status` to whichever of `PLANNED`, `CLEARED` or `GRADED` was captured in `status_before_hold`, clears `status_before_hold` back to null, and returns `permit_status` to `ACTIVE`."

    Design: Corner/state_machines/permit_reinstatement_restores_the_status_captured_before_hold
    """
    area = graded_area(api, project["id"])
    suspend_permit(api, area["id"], "2026-08-03T00:00:00Z")
    assert read_grading_area(api, area["id"])["status_before_hold"] == "GRADED"

    reinstate_permit(api, area["id"], "2026-08-04T00:00:00Z")

    after = read_grading_area(api, area["id"])
    assert after["status"] == "GRADED"
    assert after["status_before_hold"] is None
    assert after["permit_status"] == "ACTIVE"


def test_area_on_hold_accepts_no_earthwork_at_all(api, project, civil_headers):
    """While the area is held, even a status-neutral drainage log is refused.

    PRD 3.2: "An area on `HOLD`, and an area that has reached the terminal `ACCEPTED`, accept no earthwork logs at all, and the rejection is again `ERR_GRADING_AREA_NOT_OPEN_FOR_WORK`."

    Design: Corner/state_machines/permit_reinstatement_restores_the_status_captured_before_hold
    """
    area = create_grading_area(api, project["id"])
    log_clearing(api, area["id"], acreage=10.00)
    suspend_permit(api, area["id"], "2026-08-03T00:00:00Z")

    validate_error(
        api.create_earthwork_log(
            area["id"],
            f.earthwork_log_payload(
                "DRAINAGE", "2026-08-05T08:00:00Z", "2026-08-05T16:00:00Z", 0.00
            ),
            civil_headers,
        ),
        "ERR_GRADING_AREA_NOT_OPEN_FOR_WORK",
    )

    after = read_grading_area(api, area["id"])
    assert after["status"] == "HOLD"
    assert after["disturbed_acreage_current"] == pytest.approx(10.00, abs=0.01)
