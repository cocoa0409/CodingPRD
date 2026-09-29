"""Transitive cascades: the four-hop chain fired by a deviating dosimetry
close and the three-hop chain fired by a RESTERILIZE disposition."""

import pytest

from test_helpers import (
    add_load_position,
    api_client,
    assert_instant_equals,
    build_cycle_scenario,
    close_dosimetry,
    create_chamber,
    create_cycle,
    create_lot,
    disposition_adverse_event,
    get_cycle,
    get_lot,
    get_qualification,
    officer,
    operator,
    report_adverse_event,
    set_clock,
    setup_released_lot,
    validate_paginated,
)

BI_RECIPE = {
    "required_min_zone_dosimeters": 1,
    "required_routine_dosimeters": 1,
    "required_biological_indicators": 1,
}


def _setup_deviating_close_with_sibling_lot():
    """Cycle C-001 sits in DOSIMETRY_REVIEW with a POSITIVE biological
    indicator; a sibling lot of the same product is staged into a second cycle
    in another chamber."""
    env = build_cycle_scenario(
        stage="review",
        recipe_overrides=BI_RECIPE,
        bi_result="POSITIVE",
        lot_overrides={"lot_code": "L-001"},
        cycle_overrides={"cycle_code": "C-001"},
    )
    chamber_b = create_chamber(
        env["permit"]["id"], "GAMMA", chamber_code="CH-G2"
    )
    sibling = create_lot(
        env["customer"]["id"], env["product"]["id"], lot_code="L-002", total_pallet_count=2
    )
    cycle_b = create_cycle(
        chamber_b["id"],
        env["recipe"]["id"],
        cycle_code="C-002",
        scheduled_start_at="2026-08-13T00:00:00Z",
        scheduled_end_at="2026-08-13T06:00:00Z",
    )
    sibling_position = add_load_position(
        cycle_b["id"], sibling["id"], position_index=1, zone="MIN_DOSE", pallet_count=2
    )
    env.update(
        {
            "chamber_b": chamber_b,
            "sibling": sibling,
            "cycle_b": cycle_b,
            "sibling_position": sibling_position,
        }
    )
    set_clock("2026-08-11T12:00:00Z")
    return env


def test_deviating_close_quarantines_its_own_lot_and_clears_schedulable():
    """PRD 3.7: "The first test asks whether any `BIOLOGICAL` indicator on the
    cycle has `bi_result` equal to `POSITIVE`; if one does, the verdict is a
    deviation with `deviation_code` `BI_POSITIVE`."
    PRD 3.7: "**Hop one** writes the dose figures, sets `deviation_code` to
    `BI_POSITIVE`, `UNDERDOSE` or `OVERDOSE` as the verdict decided, stamps
    `dosimetry_closed_by_user_id`, and lands the cycle in `DOSE_DEVIATION`."
    PRD 3.7: "**Hop two**, caused by hop one, moves every lot of this cycle at
    `status` `PROCESSED` to `QUARANTINE`, with `quarantine_reason` set to
    `BI_POSITIVE` when the deviation code is `BI_POSITIVE` and to
    `DOSE_DEVIATION` otherwise, and clears each of those lots' `schedulable`
    flag to false."

    Design: Difficulty/transitive_cascade/dose_deviation_depth4_cascade_strips_sibling_lot_from_another_load_map
    """
    env = _setup_deviating_close_with_sibling_lot()

    closed = close_dosimetry(env["cycle"]["id"])

    assert closed["status"] == "DOSE_DEVIATION"
    assert closed["deviation_code"] == "BI_POSITIVE"
    assert closed["delivered_dose_kgy"] == pytest.approx(30.00, abs=0.001)
    assert closed["max_observed_dose_kgy"] == pytest.approx(30.00, abs=0.001)

    lot = get_lot(env["lot"]["id"])
    assert lot["status"] == "QUARANTINE"
    assert lot["quarantine_reason"] == "BI_POSITIVE"
    assert lot["schedulable"] is False
    assert lot["cumulative_dose_kgy"] == pytest.approx(0, abs=0.001), (
        "a deviating close never posts to the lifetime ledger"
    )


def test_deviating_close_lapses_the_qualification_and_unstages_a_sibling_lot():
    """PRD 3.7: "**Hop three**, caused by hop two, reaches the qualification
    file: for each lot quarantined in hop two, the `ProductQualification`
    binding that lot's product to this cycle's recipe, if its `status` is
    `QUALIFIED` or `CONDITIONAL`, is moved to `AUDIT_DUE` with
    `next_audit_due_at` set to the current logical-clock instant, so that the
    pair cannot be loaded again until a fresh dose audit clears it."
    PRD 3.7: "**Hop four**, caused by hop three, reaches sideways into
    unrelated in-flight work: for every qualification pushed to `AUDIT_DUE` in
    hop three, every *other* lot of the same product whose `status` is `STAGED`
    has its `schedulable` flag cleared to false and walks `STAGED → RECEIVED`,
    and each of that lot's load positions on cycles whose `status` is
    `PLANNED`, `LOADING` or `READY` is hard-deleted in ascending `created_at`
    order — decrementing that cycle's `loaded_pallet_count`, recomputing its
    `load_density_g_per_cm3`, and reverting that cycle from `READY` to
    `LOADING`, or from `LOADING` to `PLANNED` when the removal leaves it with
    no positions at all."

    Design: Difficulty/transitive_cascade/dose_deviation_depth4_cascade_strips_sibling_lot_from_another_load_map
    """
    env = _setup_deviating_close_with_sibling_lot()

    close_dosimetry(env["cycle"]["id"])

    qualification = get_qualification(env["qualification"]["id"])
    assert qualification["status"] == "AUDIT_DUE"
    assert_instant_equals(
        qualification["next_audit_due_at"], "2026-08-11T12:00:00Z", "next_audit_due_at"
    )

    sibling = get_lot(env["sibling"]["id"])
    assert sibling["status"] == "RECEIVED"
    assert sibling["schedulable"] is False
    assert sibling["staged_pallet_count"] == 0
    assert sibling["available_pallet_count"] == 2

    cycle_b = get_cycle(env["cycle_b"]["id"])
    assert cycle_b["status"] == "PLANNED"
    assert cycle_b["loaded_pallet_count"] == 0
    assert cycle_b["load_density_g_per_cm3"] == pytest.approx(0.0, abs=1e-9)

    _, meta_b = validate_paginated(
        api_client.list_load_positions(operator(), params={"cycle_id": env["cycle_b"]["id"]})
    )
    assert meta_b["total_count"] == 0

    _, meta_a = validate_paginated(
        api_client.list_load_positions(operator(), params={"cycle_id": env["cycle"]["id"]})
    )
    assert meta_a["total_count"] == 1, "the deviated cycle keeps its own load map"


def _setup_released_lot_with_reported_event():
    env = setup_released_lot(
        product_overrides={"product_code": "P5", "max_cumulative_dose_kgy": 45.0},
        lot_overrides={"lot_code": "L-001"},
    )
    env["event"] = report_adverse_event(
        env["lot"]["id"],
        reporter_headers=officer(),
        event_type="STERILITY_COMPLAINT",
        severity="HIGH",
        description="Field sterility complaint on implanted device",
    )
    return env


def test_resterilize_recalls_the_lot_and_mints_a_successor():
    """PRD 3.9: "**Hop one** moves the event `REPORTED → RESTERILIZE_APPROVED`
    and records `disposition` as `RESTERILIZE`."
    PRD 3.9: "**Hop two**, caused by hop one, moves the subject lot `RELEASED →
    RECALLED` with `quarantine_reason` set to `ADVERSE_EVENT`, and mints a
    successor lot in the same breath: the successor's `parent_lot_id` points at
    the subject, its `customer_id`, `product_id` and `total_pallet_count` are
    copied from the subject, its `lot_code` is the subject's `lot_code`
    followed by the literal characters `-R` and then the subject's
    `resterilization_count` increased by one, its `status` is `RECEIVED` with
    `staged_pallet_count` 0 and `available_pallet_count` equal to
    `total_pallet_count`, its `residual_status` is `NOT_APPLICABLE`, its
    `cumulative_dose_kgy` is inherited unchanged from the subject so that the
    physical goods carry their full dose history forward, its
    `resterilization_count` is the subject's increased by one, and its
    `schedulable` flag starts true."

    Design: Difficulty/transitive_cascade/resterilize_disposition_depth3_cascade_suspends_cumulative_dose_qualification
    """
    env = _setup_released_lot_with_reported_event()

    dispositioned = disposition_adverse_event(env["event"]["id"], "RESTERILIZE")

    assert dispositioned["status"] == "RESTERILIZE_APPROVED"
    assert dispositioned["disposition"] == "RESTERILIZE"

    subject = get_lot(env["lot"]["id"])
    assert subject["status"] == "RECALLED"
    assert subject["quarantine_reason"] == "ADVERSE_EVENT"

    successors, meta = validate_paginated(
        api_client.list_lots(officer(), params={"parent_lot_id": env["lot"]["id"]})
    )
    assert meta["total_count"] == 1
    successor = successors[0]
    assert successor["lot_code"] == "L-001-R1"
    assert successor["parent_lot_id"] == env["lot"]["id"]
    assert successor["resterilization_count"] == 1
    assert successor["status"] == "RECEIVED"
    assert successor["residual_status"] == "NOT_APPLICABLE"
    assert successor["total_pallet_count"] == 2
    assert successor["staged_pallet_count"] == 0
    assert successor["available_pallet_count"] == 2
    assert successor["cumulative_dose_kgy"] == pytest.approx(30.00, abs=0.001)


def test_successor_dose_burden_suspends_the_qualification_and_blocks_the_lot():
    """PRD 3.9: "**Hop three**, caused by hop two, exists because the successor
    arrives carrying a non-zero dose burden. Every `ProductQualification` for
    the successor's product whose `status` is `QUALIFIED` or `CONDITIONAL` is
    re-evaluated in ascending `created_at` order, and for each one the server
    adds the successor's `cumulative_dose_kgy` to the `target_dose_kgy` of that
    qualification's recipe and rounds the sum half up to two decimal places;
    where that figure exceeds the product's `max_cumulative_dose_kgy`, the
    qualification moves to `SUSPENDED` with `next_audit_due_at` set to null and
    the successor's `schedulable` flag is cleared to false."
    PRD 3.9: "`release_mode` records the pathway used, `released_at` records
    the current logical-clock instant, `released_by_user_id` records the
    officer's `X-User-ID`, and `release_dose_kgy` snapshots the governing
    cycle's `delivered_dose_kgy` so that the released record is immune to any
    later re-read of the cycle."

    Design: Difficulty/transitive_cascade/resterilize_disposition_depth3_cascade_suspends_cumulative_dose_qualification
    """
    env = _setup_released_lot_with_reported_event()

    disposition_adverse_event(env["event"]["id"], "RESTERILIZE")

    qualification = get_qualification(env["qualification"]["id"])
    assert qualification["status"] == "SUSPENDED", (
        "30.00 inherited plus a 30.0 target exceeds the 45.0 lifetime ceiling"
    )
    assert qualification["next_audit_due_at"] is None

    successors, _ = validate_paginated(
        api_client.list_lots(officer(), params={"parent_lot_id": env["lot"]["id"]})
    )
    assert successors[0]["schedulable"] is False

    subject = get_lot(env["lot"]["id"])
    assert subject["release_dose_kgy"] == pytest.approx(30.00, abs=0.001)
    assert subject["cumulative_dose_kgy"] == pytest.approx(30.00, abs=0.001)
