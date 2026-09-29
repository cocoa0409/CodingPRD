"""Optimistic concurrency on the two version-guarded endpoints: the lot's
sampling-plan draw and the unit's warranty claim."""

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers.assertions import assert_close, assert_sampling_plan
from test_helpers.factories import (
    cycle_report_payload,
    sampling_plan_payload,
    warranty_claim_payload,
    watering_log_payload,
)
from test_helpers.fixtures import World

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_lot_version_token_is_row_scoped_equality_and_outranks_the_hold_gate(
    world: World,
):
    """A stale token on a held lot answers 412; the same write with a fresh token answers 409.

    "If that value does not equal the lot's current `version`, the request is rejected with
    `ERR_STALE_LOT_VERSION` (HTTP 412)", and the increment scope is normative: "a `ProductionLot`'s
    `version` advances only on writes addressed to the lot itself (stage advancement, sampling-plan
    draws, dispositions and environmental holds) ... Creating a child `BatteryAssembly`, recording a
    verification on one, reworking one, or scheduling a `CapacityTest` do **not** advance the lot's
    `version`". The ordering is fixed by the tier list -- "**Tier 10 -- optimistic concurrency.**
    `ERR_STALE_LOT_VERSION` on `POST /production-lots/{id}/sampling-plans`" above tier 12, where
    "`ERR_LOT_ENV_HELD` guards ten operations". A redraw is legitimate but not idempotent: it
    "requires the lot to already be in `LOT_TESTING` and leaves `process_state` untouched".

    Design: Corner/cross_cutting_layers/lot_occ_is_row_scoped_equality_and_outranks_the_environmental_hold_gate
    """
    lot = world.lot_in_state(C.LOT_ASSEMBLY, "LOT-S", 9)
    assert lot["version"] == 4, "create plus three advances is four accepted lot writes"
    other = world.open_lot("LOT-T", 12)
    assert other["version"] == 1

    world.certify_assembly(lot["id"], "ASM-S1")
    assert world.read_lot(lot["id"])["version"] == 4, "assembly writes are not lot writes"

    first = validate_success(
        world.api.draw_sampling_plan(
            lot["id"], sampling_plan_payload(4), world.qa_a
        ),
        201,
    )
    assert first["process_state"] == C.LOT_TESTING
    assert_sampling_plan(first, sample_size=3, acceptance_number=0, revision=1)
    assert first["version"] == 5

    held = world.hold_lot(lot["id"])
    assert held["env_hold_status"] == C.ENV_HOLD_HELD
    assert held["hold_reason"] == C.HOLD_REASON_OPERATOR
    assert held["version"] == 6

    validate_error(
        world.api.draw_sampling_plan(
            lot["id"],
            sampling_plan_payload(5, plan_reason="stale token on a held lot"),
            world.qa_a,
        ),
        E.ERR_STALE_LOT_VERSION,
    )
    assert world.read_lot(lot["id"])["version"] == 6, "a 412 must not bump the counter"

    validate_error(
        world.api.draw_sampling_plan(
            lot["id"],
            sampling_plan_payload(6, plan_reason="fresh token on a held lot"),
            world.qa_a,
        ),
        E.ERR_LOT_ENV_HELD,
    )
    assert world.read_lot(lot["id"])["version"] == 6, "a 409 must not bump the counter"

    cleared = world.release_hold(lot["id"])
    assert cleared["env_hold_status"] == C.ENV_HOLD_CLEAR
    assert cleared["hold_reason"] is None
    assert cleared["version"] == 7

    validate_error(
        world.api.draw_sampling_plan(
            lot["id"],
            sampling_plan_payload(6, plan_reason="token invalidated by the hold release"),
            world.qa_a,
        ),
        E.ERR_STALE_LOT_VERSION,
    )

    redrawn = validate_success(
        world.api.draw_sampling_plan(
            lot["id"], sampling_plan_payload(7, plan_reason="legitimate redraw"), world.qa_a
        ),
        201,
    )
    assert redrawn["process_state"] == C.LOT_TESTING
    assert_sampling_plan(redrawn, sample_size=3, acceptance_number=0, revision=2)
    assert redrawn["version"] == 8

    validate_error(
        world.api.draw_sampling_plan(
            lot["id"],
            sampling_plan_payload(7, plan_reason="replay of the request that just succeeded"),
            world.qa_a,
        ),
        E.ERR_STALE_LOT_VERSION,
    )
    validate_error(
        world.api.draw_sampling_plan(
            lot["id"],
            sampling_plan_payload(
                other["version"], plan_reason="another lot's version token"
            ),
            world.qa_a,
        ),
        E.ERR_STALE_LOT_VERSION,
    )

    after = world.read_lot(lot["id"])
    assert_sampling_plan(after, sample_size=3, acceptance_number=0, revision=2)
    assert after["version"] == 8

    untouched = world.read_lot(other["id"])
    assert untouched["process_state"] == C.LOT_PLANNED
    assert untouched["version"] == 1
    assert untouched["sample_size"] is None


def test_a_watering_log_invalidates_a_claimants_token_and_occ_precedes_the_state_gate(
    world: World,
):
    """The replayed duplicate claim answers 412; the refreshed duplicate answers 409.

    "A mismatch against the unit's current `version` is rejected with
    `ERR_STALE_BATTERY_UNIT_VERSION` (HTTP 412). Here the hazard is that a re-claim on a denied unit
    supersedes the previous adjudication by clearing `warranty_decision` and `warranty_credit_cents`,
    while field maintenance and cycle reports also advance the unit's `version`". Opening a claim
    "increments the unit's `version` by 1 -- so a second claim replaying the same
    `expected_battery_unit_version` is refused with `ERR_STALE_BATTERY_UNIT_VERSION`", while "A unit
    already `CLAIM_OPEN` cannot open a second claim, which is `ERR_WARRANTY_STATE_INVALID`" -- and
    tier 10 sits above tier 11. The service window is closed on both ends: "`performed_at` must fall
    within the closed interval from the unit's `shipped_at` to the logical clock -- a service event
    cannot predate the shipment or be filed in the future".

    Design: Corner/cross_cutting_layers/battery_unit_occ_outranks_the_warranty_state_gate_and_the_event_time_gate
    """
    lot = world.released_lot("LOT-U", 9)
    unit = world.ship_unit(lot["id"], "BU-U-001")
    assert unit["shipped_at"].startswith("2026-09-03T14:00:00")
    assert unit["version"] == 1
    assert unit["warranty_status"] == C.WARRANTY_IN_SERVICE
    assert unit["cycle_count"] == 0
    assert unit["watering_events_ok"] == 0
    assert_close(unit["watering_compliance_ratio"], 1.0000, "watering_compliance_ratio", 4)

    world.set_clock("2026-12-01T00:00:00Z")

    log = validate_success(
        world.api.create_maintenance_log(
            unit["id"], watering_log_payload("2026-10-01T00:00:00Z"), world.warranty
        ),
        201,
    )
    assert log["resulting_cycle_count"] == 0
    assert_close(log["resulting_compliance_ratio"], 0.5000, "resulting_compliance_ratio", 4)

    watered = world.read_unit(unit["id"])
    assert watered["version"] == 2, "a service event the claimant never filed moves the token"
    assert watered["watering_events_ok"] == 1
    assert watered["watering_events_expected"] == 2
    assert watered["months_in_service"] == 2
    assert_close(watered["watering_compliance_ratio"], 0.5000, "watering_compliance_ratio", 4)

    validate_error(
        world.api.open_warranty_claim(
            unit["id"],
            warranty_claim_payload(1, reported_at="2026-12-01T00:00:00Z"),
            world.warranty,
        ),
        E.ERR_STALE_BATTERY_UNIT_VERSION,
    )
    stale_refused = world.read_unit(unit["id"])
    assert stale_refused["claim_count"] == 0
    assert stale_refused["warranty_status"] == C.WARRANTY_IN_SERVICE
    assert stale_refused["version"] == 2

    claimed = validate_success(
        world.api.open_warranty_claim(
            unit["id"],
            warranty_claim_payload(2, reported_at="2026-12-01T00:00:00Z"),
            world.warranty,
        ),
        201,
    )
    assert claimed["warranty_status"] == C.WARRANTY_CLAIM_OPEN
    assert claimed["claim_count"] == 1
    assert claimed["version"] == 3
    assert claimed["warranty_decision"] is None
    assert claimed["warranty_credit_cents"] == 0
    assert claimed["last_claim_at"].startswith("2026-12-01T00:00:00")

    validate_error(
        world.api.open_warranty_claim(
            unit["id"],
            warranty_claim_payload(2, reported_at="2026-12-01T00:00:00Z"),
            world.warranty,
        ),
        E.ERR_STALE_BATTERY_UNIT_VERSION,
    )
    validate_error(
        world.api.open_warranty_claim(
            unit["id"],
            warranty_claim_payload(3, reported_at="2026-12-01T00:00:00Z"),
            world.warranty,
        ),
        E.ERR_WARRANTY_STATE_INVALID,
    )

    validate_error(
        world.api.create_maintenance_log(
            unit["id"],
            cycle_report_payload("2026-08-01T00:00:00Z", 120),
            world.warranty,
        ),
        E.ERR_EVENT_TIME_OUT_OF_RANGE,
    )
    validate_error(
        world.api.create_maintenance_log(
            unit["id"],
            cycle_report_payload("2027-06-01T00:00:00Z", 120),
            world.warranty,
        ),
        E.ERR_EVENT_TIME_OUT_OF_RANGE,
    )

    after = world.read_unit(unit["id"])
    assert after["version"] == 3
    assert after["claim_count"] == 1
    assert after["warranty_status"] == C.WARRANTY_CLAIM_OPEN
    assert after["cycle_count"] == 0
    assert after["watering_events_ok"] == 1

    rows, meta = validate_paginated(
        world.api.list_maintenance_logs(unit["id"], world.warranty)
    )
    assert meta["total_count"] == 1, rows
    assert rows[0]["event_type"] == C.MAINT_WATERING
