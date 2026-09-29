"""Optimistic concurrency on contested parents, derived rollups and immediacy.

Two writes prove they are working from a current view of a parent resource
(PRD 2.8); every counter and readiness flag is recomputed from its source rows
on each write; and nothing lags — a write response and the next read agree.
"""

from test_helpers import (
    assert_delivery_receipt,
    assert_pile_disposition,
    assert_same_entity,
    assert_zone_occupancy,
    factories as f,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_STALE_PROJECT_VERSION,
    ERR_STALE_YARD_ZONE_VERSION,
)
from test_helpers.fixtures import (
    LAYDOWN_END,
    LAYDOWN_START,
    accepted_area,
    accepted_module_delivery,
    add_change_order,
    create_block,
    create_circuit,
    create_pile,
    create_yard_zone,
    declare_mechanical_completion,
    project_version,
    record_drive_result,
    record_string_test,
    reserve_delivery,
    read_yard_zone,
    wire_circuit,
)


def _tracker_payload(project_id, yard_zone_id, expected_version):
    """A second shipment into the same zone, overlapping the first's window."""
    return f.delivery_payload(
        project_id,
        yard_zone_id,
        expected_version,
        component_type="TRACKER",
        unit_qty=40,
        pallets=40,
        planned_arrival_at="2026-08-04T09:00:00Z",
        laydown_window_start=LAYDOWN_START,
        laydown_window_end=LAYDOWN_END,
    )


def test_reservation_on_a_superseded_yard_zone_version_is_refused(
    api, project, procurement_headers
):
    """A zone version that was current one call ago is stale, and re-reading clears it.

    PRD 2.8: "If that value does not equal the yard zone's current `version` — because another writer has reserved, cancelled or rejected a shipment in that zone since the client read it — the reservation is rejected with `ERR_STALE_YARD_ZONE_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/stale_parent_versions_are_rejected_on_both_occ_write_endpoints
    """
    zone = create_yard_zone(api, project["id"], pallet_capacity=200)
    stale_version = zone["version"]
    reserve_delivery(
        api, project["id"], zone["id"], expected_version=stale_version, pallets=60
    )

    refused = api.create_delivery(
        _tracker_payload(project["id"], zone["id"], stale_version), procurement_headers
    )
    validate_error(refused, ERR_STALE_YARD_ZONE_VERSION)

    zone_now = read_yard_zone(api, zone["id"])
    assert zone_now["version"] == stale_version + 1, (
        "only the admitted reservation may advance the zone's version"
    )
    assert_zone_occupancy(zone_now, reserved_pallets=60, available_pallets=140)

    admitted = validate_success(
        api.create_delivery(
            _tracker_payload(project["id"], zone["id"], zone_now["version"]),
            procurement_headers,
        ),
        expected_status=201,
    )
    assert admitted["status"] == "RESERVED"
    assert_zone_occupancy(
        read_yard_zone(api, zone["id"]), reserved_pallets=100, available_pallets=100
    )


def test_scheduling_on_a_superseded_project_version_is_refused(
    api, project, commissioning_headers
):
    """Commissioning-test scheduling reports its own 412 code, not the yard-zone one.

    PRD 2.8: "A mismatch with the project's current `version` is rejected with `ERR_STALE_PROJECT_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/stale_parent_versions_are_rejected_on_both_occ_write_endpoints
    """
    stale_version = project["version"]
    add_change_order(api, project["id"], 100000, reason="extra combiner pad")

    refused = api.create_commissioning_test(
        f.commissioning_test_payload(project["id"], stale_version),
        commissioning_headers,
    )
    validate_error(refused, ERR_STALE_PROJECT_VERSION)

    current = project_version(api, project["id"])
    assert current == stale_version + 1, (
        "the change order advanced the project once and the refused write not at all"
    )

    scheduled = validate_success(
        api.create_commissioning_test(
            f.commissioning_test_payload(project["id"], current), commissioning_headers
        ),
        expected_status=201,
    )
    assert scheduled["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# The block and project rollups are recomputed from their source rows
# ---------------------------------------------------------------------------
def _take_block_to_ready(api, block, circuit_code):
    """Drive the block's one pile, declare it mechanically complete, then wire and
    test its one string circuit, which is what makes the block `mc_ready`."""
    pile = create_pile(api, block["id"])
    record_drive_result(api, pile["id"])
    declare_mechanical_completion(
        api, block["id"], modules_installed_qty=20, max_torque_tube_deviation_mm=18.0
    )
    circuit = create_circuit(api, block["id"], circuit_code=circuit_code)
    wire_circuit(api, circuit["id"])
    record_string_test(api, circuit["id"])
    return circuit


def test_block_and_project_rollups_climb_and_fall_with_their_source_rows(
    api, project, epc_headers, foreman_headers
):
    """Readiness flips to READY only on the second block, and a later failure walks it back.

    PRD 3.5: "`mc_readiness` is `READY` when the project has at least one block, when `blocks_mc_ready_count` equals `blocks_total`, and when every grading area of the project has `status` `ACCEPTED`; in every other case it is `BLOCKED`."

    Design: Corner/cross_cutting_complexity_layers/block_and_project_derived_counters_track_every_source_write
    """
    area = accepted_area(api, project["id"])
    zone = create_yard_zone(api, project["id"])
    accepted_module_delivery(api, project["id"], zone["id"])
    b1 = create_block(api, project["id"], area["id"], block_code="B1")
    b2 = create_block(api, project["id"], area["id"], block_code="B2")

    opening = validate_success(api.get_project(project["id"], epc_headers))
    assert opening["blocks_total"] == 2
    assert opening["blocks_mc_ready_count"] == 0
    assert opening["mc_readiness"] == "BLOCKED"

    pile = create_pile(api, b1["id"])
    record_drive_result(api, pile["id"])
    after_pile = validate_success(api.get_block(b1["id"], foreman_headers))
    assert after_pile["piles_accepted_count"] == 1
    assert after_pile["piles_refused_count"] == 0
    assert after_pile["mechanical_status"] == "PILES_COMPLETE"

    declare_mechanical_completion(
        api, b1["id"], modules_installed_qty=20, max_torque_tube_deviation_mm=18.0
    )
    circuit_one = create_circuit(api, b1["id"], circuit_code="C1")
    wire_circuit(api, circuit_one["id"])
    record_string_test(api, circuit_one["id"])

    first_ready = validate_success(api.get_block(b1["id"], foreman_headers))
    assert first_ready["mechanical_status"] == "MECH_COMPLETE"
    assert first_ready["circuits_wired_count"] == 1
    assert first_ready["circuits_tested_count"] == 1
    assert first_ready["circuits_failed_count"] == 0
    assert first_ready["electrical_status"] == "TESTED"
    assert first_ready["mc_ready"] is True

    halfway = validate_success(api.get_project(project["id"], epc_headers))
    assert halfway["blocks_mc_ready_count"] == 1
    assert halfway["mc_readiness"] == "BLOCKED", "one of two ready blocks is not enough"

    circuit_two = _take_block_to_ready(api, b2, "C2")
    both = validate_success(api.get_project(project["id"], epc_headers))
    assert both["blocks_mc_ready_count"] == 2
    assert both["mc_readiness"] == "READY"

    failed = validate_success(
        api.create_string_test_result(
            circuit_two["id"],
            f.string_test_payload(insulation_resistance_mohm=30.0),
            foreman_headers,
        )
    )
    assert failed["status"] == "FAILED"
    assert failed["test_failure_reason"] == "INSULATION"

    reworked = validate_success(api.get_block(b2["id"], foreman_headers))
    assert reworked["circuits_wired_count"] == 1
    assert reworked["circuits_failed_count"] == 1
    assert reworked["electrical_status"] == "REWORK"
    assert reworked["mc_ready"] is False

    walked_back = validate_success(api.get_project(project["id"], epc_headers))
    assert walked_back["blocks_mc_ready_count"] == 1, (
        "the rollup decrements rather than latching at its high-water mark"
    )
    assert walked_back["mc_readiness"] == "BLOCKED"


# ---------------------------------------------------------------------------
# Nothing lags: the write response and the next read already agree
# ---------------------------------------------------------------------------
def test_receipt_response_already_carries_the_resolved_acceptance_fork(
    api, project, procurement_headers
):
    """The receipt itself reports ACCEPTED with its damage ratio, and the zone read follows.

    PRD 3.3: "It then immediately resolves the `ARRIVED` fork in the same request, and the two branches diverge sharply."

    Design: Corner/consistency_model/every_derived_change_is_visible_in_the_same_response_and_the_next_read
    """
    zone = create_yard_zone(api, project["id"])
    delivery = reserve_delivery(api, project["id"], zone["id"])
    assert delivery["status"] == "RESERVED"

    receipt = validate_success(
        api.receive_delivery(
            delivery["id"], f.receipt_payload(60, 3), procurement_headers
        )
    )
    assert_delivery_receipt(
        receipt, status="ACCEPTED", accepted_unit_qty=57, damage_ratio=0.05
    )

    assert_zone_occupancy(
        read_yard_zone(api, zone["id"]), reserved_pallets=60, available_pallets=40
    )

    reread = validate_success(api.get_delivery(delivery["id"], procurement_headers))
    assert_same_entity(
        receipt,
        reread,
        "status",
        "damage_ratio",
        "received_unit_qty",
        "damaged_unit_qty",
        "accepted_unit_qty",
        "version",
    )


def test_drive_response_and_the_next_block_read_show_the_same_new_reality(
    api, project, foreman_headers
):
    """The drive response carries the disposition and the parent counter is already reconciled.

    PRD 2.12: "Counters, ledgers, readiness flags and settlement figures are recomputed from their inputs whenever those inputs change, and the recomputation is **immediate**: by the time a write returns, every derived field it affects — on the written resource, on its parent, and on the project — already reflects the new reality."

    Design: Corner/consistency_model/every_derived_change_is_visible_in_the_same_response_and_the_next_read
    """
    area = accepted_area(api, project["id"])
    block = create_block(api, project["id"], area["id"])
    pile = create_pile(api, block["id"])

    driven = validate_success(
        api.create_drive_result(
            pile["id"], f.drive_result_payload(), foreman_headers
        )
    )
    assert_pile_disposition(driven, "ACCEPTED")
    assert driven["remediated"] is False

    block_now = validate_success(api.get_block(block["id"], foreman_headers))
    assert block_now["piles_accepted_count"] == 1
    assert block_now["mechanical_status"] == "PILES_COMPLETE"

    reread = validate_success(api.get_pile(pile["id"], foreman_headers))
    assert_same_entity(driven, reread, "status", "remediated", "version")
