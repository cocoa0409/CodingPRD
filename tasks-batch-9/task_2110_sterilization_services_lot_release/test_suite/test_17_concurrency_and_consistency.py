"""Optimistic concurrency on the load map and the lot file, and the immediate
visibility of every derived field."""

import pytest

from test_helpers import (
    ApiErrorId,
    add_load_position,
    api_client,
    build_cycle_scenario,
    close_dosimetry,
    create_adverse_event_payload,
    create_cycle,
    create_load_position_payload,
    create_lot,
    create_product,
    create_qualified_qualification,
    get_cycle,
    get_lot,
    officer,
    operator,
    place_indicator,
    report_adverse_event,
    setup_reference_data,
    setup_released_lot,
    sign_ready,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_stale_cycle_version_is_rejected_and_the_fresh_handle_succeeds():
    """PRD 2.6: "Creating a load position on a cycle — the write served by
    `POST /sterilization/cycles/{id}/load-positions` — requires
    `expected_cycle_version` in the request body. The field is not optional; it
    carries the `version` of the parent `Cycle` as the client last observed it.
    If that value does not equal the cycle's current `version`, the request is
    rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412), because a client
    working from an earlier read is reasoning about a load map and a
    `load_density_g_per_cm3` that no longer exist."
    PRD 2.6: "Each `LoadPosition` records `cycle_version_after`, a snapshot of
    the parent cycle's `version` immediately after that position was persisted;
    it is the handle a client uses for the next load-map write."

    Design: Corner/cross_cutting/corner_occ_stale_cycle_version_rejected_on_load_position
    """
    env = setup_reference_data()
    lot = create_lot(env["customer"]["id"], env["product"]["id"], total_pallet_count=4)
    cycle = create_cycle(env["chamber"]["id"], env["recipe"]["id"])
    stale_version = cycle["version"]
    first = add_load_position(
        cycle["id"], lot["id"], expected_cycle_version=stale_version,
        position_index=1, zone="MIN_DOSE", pallet_count=2,
    )

    rejected = api_client.create_load_position(
        cycle["id"],
        create_load_position_payload(
            lot["id"], stale_version, position_index=2, zone="INTERIOR", pallet_count=2
        ),
        operator(),
    )

    validate_error(rejected, ApiErrorId.ERR_STALE_CYCLE_VERSION)
    assert get_cycle(cycle["id"])["loaded_pallet_count"] == 2
    assert get_lot(lot["id"])["staged_pallet_count"] == 2

    second = validate_success(
        api_client.create_load_position(
            cycle["id"],
            create_load_position_payload(
                lot["id"], first["cycle_version_after"], position_index=2,
                zone="INTERIOR", pallet_count=2,
            ),
            operator(),
        ),
        201,
    )

    assert second["cycle_version_after"] == first["cycle_version_after"] + 1
    stored_cycle = get_cycle(cycle["id"])
    assert stored_cycle["loaded_pallet_count"] == 4
    assert stored_cycle["load_density_g_per_cm3"] == pytest.approx(0.1000, abs=1e-9)
    stored_lot = get_lot(lot["id"])
    assert stored_lot["staged_pallet_count"] == 4
    assert stored_lot["available_pallet_count"] == 0


def test_cycle_version_advances_on_load_map_writes_and_the_sign_off():
    """PRD 2.6: "The cycle's `version` advances on every load-map write, on the
    readiness sign-off, and on every cascade-driven position removal, so any of
    those events invalidates a client's cached handle."
    PRD 2.4: "All resources except one also carry `updated_at`, an ISO 8601 UTC
    timestamp refreshed on every persisted change to the row, and `version`, an
    integer that begins at 1 when the row is created and increases by exactly
    one on every persisted mutation of that row."

    Design: Corner/cross_cutting/corner_occ_version_increments_on_every_cycle_mutation
    """
    env = setup_reference_data()
    lot = create_lot(env["customer"]["id"], env["product"]["id"])
    cycle = create_cycle(env["chamber"]["id"], env["recipe"]["id"])
    assert cycle["version"] == 1

    position = add_load_position(
        cycle["id"], lot["id"], expected_cycle_version=cycle["version"],
        position_index=1, zone="MIN_DOSE", pallet_count=2,
    )
    assert position["cycle_version_after"] == 2

    place_indicator(
        position["id"], indicator_type="DOSIMETER", placement_zone="MIN_DOSE",
        serial_code="D-MIN",
    )
    place_indicator(
        position["id"], indicator_type="DOSIMETER", placement_zone="ROUTINE",
        serial_code="D-RT",
    )
    ready = sign_ready(cycle["id"])

    assert ready["version"] == 3, "indicator placement does not advance the cycle"
    assert ready["status"] == "READY"


def test_a_stale_lot_version_is_rejected_on_a_second_adverse_event():
    """PRD 2.6: "Reporting an adverse event against a lot — the write served by
    `POST /sterilization/lots/{id}/adverse-events` — requires
    `expected_lot_version` in the request body, again not optional, carrying
    the `version` of the parent `Lot` as the client last observed it. A
    mismatch with the lot's current `version` is rejected with
    `ERR_STALE_LOT_VERSION` (HTTP 412), which tells the reporter that the lot's
    disposition, `quarantine_reason` or residual posture moved underneath their
    read."
    PRD 2.6: "Each `AdverseEvent` records `lot_version_after`, a snapshot of
    the subject lot's `version` immediately after the event was persisted, and
    creating the event itself increments the lot's `version` by one."

    Design: Corner/cross_cutting/corner_occ_stale_lot_version_rejected_on_adverse_event
    """
    env = setup_released_lot()
    stale_version = get_lot(env["lot"]["id"])["version"]
    first = report_adverse_event(
        env["lot"]["id"],
        expected_lot_version=stale_version,
        reporter_headers=officer(),
        event_type="STERILITY_COMPLAINT",
        severity="HIGH",
        description="Field sterility complaint on implanted device",
    )

    rejected = api_client.create_adverse_event(
        env["lot"]["id"],
        create_adverse_event_payload(
            stale_version,
            event_type="PACKAGING_BREACH",
            severity="LOW",
            description="Outer carton seal breached in transit",
        ),
        officer(),
    )

    validate_error(rejected, ApiErrorId.ERR_STALE_LOT_VERSION)
    _, meta = validate_paginated(
        api_client.list_adverse_events(env["lot"]["id"], officer())
    )
    assert meta["total_count"] == 1

    second = validate_success(
        api_client.create_adverse_event(
            env["lot"]["id"],
            create_adverse_event_payload(
                first["lot_version_after"],
                event_type="PACKAGING_BREACH",
                severity="LOW",
                description="Outer carton seal breached in transit",
            ),
            officer(),
        ),
        201,
    )

    assert second["lot_version_after"] == first["lot_version_after"] + 1
    _, meta_after = validate_paginated(
        api_client.list_adverse_events(env["lot"]["id"], officer())
    )
    assert meta_after["total_count"] == 2
    assert get_lot(env["lot"]["id"])["status"] == "RELEASED"


def test_the_dosimetry_close_response_already_carries_its_cascade():
    """PRD 2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD 3.7: "On the conforming branch the cycle walks `DOSIMETRY_REVIEW →
    DOSE_CONFORMING`. The analyst's `X-User-ID` is stamped as
    `dosimetry_closed_by_user_id`, the second half of the segregation-of-duties
    pair. Every lot on the load map at `status` `PROCESSED` moves `PROCESSED →
    QUARANTINE` with `quarantine_reason` set to `ROUTINE`."

    Design: Corner/consistency_model/corner_cascade_is_visible_in_the_same_response
    """
    env = build_cycle_scenario(stage="review")

    closed = close_dosimetry(env["cycle"]["id"])

    assert closed["delivered_dose_kgy"] == pytest.approx(30.00, abs=0.001)
    assert closed["status"] == "DOSE_CONFORMING"
    assert closed["dosimetry_closed_by_user_id"] == "ana-1"

    lot = get_lot(env["lot"]["id"])
    assert lot["status"] == "QUARANTINE"
    assert lot["cumulative_dose_kgy"] == pytest.approx(30.00, abs=0.001)
    assert lot["quarantine_reason"] == "ROUTINE"


def test_derived_fields_are_reconciled_inside_the_causing_write():
    """PRD 3.5: "When the write succeeds, the slot is persisted with
    `cycle_version_after` set to the cycle's `version` as of that write; the
    cycle's `loaded_pallet_count` grows by the placed `pallet_count`; the
    cycle's `load_density_g_per_cm3` is recomputed from scratch; the lot's
    `staged_pallet_count` grows by the same `pallet_count` and its
    `available_pallet_count` is refreshed to `total_pallet_count` less
    `staged_pallet_count`; the lot moves `RECEIVED → STAGED`, or simply stays
    `STAGED` if it was already staged by an earlier slot; and the cycle's
    `version` increases by one."
    PRD 2.8: "The batch record is hierarchical — a permit owns chambers, a
    chamber owns cycles, a cycle owns load positions, a load position owns
    indicators, a lot owns aeration records and adverse events — and
    consistency across that hierarchy is maintained by the server, not by the
    client."

    Design: Corner/consistency_model/corner_derived_fields_are_refreshed_within_the_write_that_causes_them
    """
    env = setup_reference_data(
        recipe_overrides={
            "density_min_g_per_cm3": 0.0900,
            "density_max_g_per_cm3": 0.1100,
        }
    )
    product_b = create_product(
        env["customer"]["id"], product_code="P2", pallet_mass_kg=90.0, pallet_volume_m3=0.8
    )
    create_qualified_qualification(product_b["id"], env["recipe"]["id"])
    lot_a = create_lot(
        env["customer"]["id"], env["product"]["id"], lot_code="L-P1", total_pallet_count=4
    )
    lot_b = create_lot(
        env["customer"]["id"], product_b["id"], lot_code="L-P2", total_pallet_count=2
    )
    cycle = create_cycle(env["chamber"]["id"], env["recipe"]["id"])
    first = add_load_position(
        cycle["id"], lot_a["id"], expected_cycle_version=cycle["version"],
        position_index=1, zone="MIN_DOSE", pallet_count=2,
    )

    second = add_load_position(
        cycle["id"], lot_b["id"], expected_cycle_version=first["cycle_version_after"],
        position_index=2, zone="INTERIOR", pallet_count=1,
    )

    assert second["cycle_version_after"] == first["cycle_version_after"] + 1
    stored_cycle = get_cycle(cycle["id"])
    assert stored_cycle["loaded_pallet_count"] == 3
    assert stored_cycle["load_density_g_per_cm3"] == pytest.approx(0.1031, abs=1e-9)
    assert stored_cycle["status"] == "LOADING"
    stored_b = get_lot(lot_b["id"])
    assert stored_b["staged_pallet_count"] == 1
    assert stored_b["available_pallet_count"] == 1
    assert stored_b["status"] == "STAGED"
    stored_a = get_lot(lot_a["id"])
    assert stored_a["staged_pallet_count"] == 2
    assert stored_a["available_pallet_count"] == 2
