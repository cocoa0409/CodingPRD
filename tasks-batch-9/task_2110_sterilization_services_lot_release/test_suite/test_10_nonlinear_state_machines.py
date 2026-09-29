"""Non-linear state machines: a cycle that re-enters LOADING, a lot that
carries two independent dimensions, and a qualification loop bounded by a
counter rather than by a state.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    add_load_position,
    api_client,
    assert_instant_equals,
    build_cycle_scenario,
    get_cycle,
    get_lot,
    get_qualification,
    officer,
    open_aeration_record,
    record_dose_audit,
    setup_reference_data,
    sign_ready,
    validate_error,
    validate_paginated,
)

ROUND_TRIP_RECIPE = {
    "required_min_zone_dosimeters": 1,
    "required_routine_dosimeters": 1,
    "required_biological_indicators": 0,
}


def test_new_load_position_unwinds_a_signed_off_cycle_to_loading():
    """PRD 3.5: "The cycle's own state follows the map: the first position on
    a fresh cycle drives `PLANNED → LOADING`, every subsequent position holds
    it at `LOADING → LOADING`, and a position added to a cycle that had already
    been signed off drives `READY → LOADING`, deliberately unwinding the
    sign-off so that every readiness check must be re-run against the revised
    map."

    Design: Difficulty/non_linear_state_machine/cycle_ready_reverts_to_loading_then_forward_again
    """
    env = build_cycle_scenario(
        stage="ready",
        recipe_overrides=ROUND_TRIP_RECIPE,
        lot_overrides={"total_pallet_count": 4},
        pallet_count=2,
    )
    ready_version = get_cycle(env["cycle"]["id"])["version"]

    second = add_load_position(
        env["cycle"]["id"],
        env["lot"]["id"],
        expected_cycle_version=ready_version,
        position_index=2,
        zone="INTERIOR",
        pallet_count=2,
    )

    cycle = get_cycle(env["cycle"]["id"])
    assert cycle["status"] == "LOADING", "the signed-off cycle fell back to LOADING"
    assert cycle["loaded_pallet_count"] == 4
    assert second["cycle_version_after"] == cycle["version"]


def test_second_sign_off_returns_the_cycle_to_ready():
    """PRD 3.5: "That `READY → LOADING → READY` round trip is a supported
    working pattern, not an error."
    PRD 3.5: "the lot's `staged_pallet_count` grows by the same `pallet_count`
    and its `available_pallet_count` is refreshed to `total_pallet_count` less
    `staged_pallet_count`; the lot moves `RECEIVED → STAGED`, or simply stays
    `STAGED` if it was already staged by an earlier slot; and the cycle's
    `version` increases by one."

    Design: Difficulty/non_linear_state_machine/cycle_ready_reverts_to_loading_then_forward_again
    """
    env = build_cycle_scenario(
        stage="ready",
        recipe_overrides=ROUND_TRIP_RECIPE,
        lot_overrides={"total_pallet_count": 4},
        pallet_count=2,
    )
    ready_version = get_cycle(env["cycle"]["id"])["version"]
    add_load_position(
        env["cycle"]["id"],
        env["lot"]["id"],
        expected_cycle_version=ready_version,
        position_index=2,
        zone="INTERIOR",
        pallet_count=2,
    )
    assert get_cycle(env["cycle"]["id"])["status"] == "LOADING"

    signed = sign_ready(env["cycle"]["id"])

    assert signed["status"] == "READY", "the same state is occupied twice"
    assert signed["loaded_pallet_count"] == 4
    assert signed["load_density_g_per_cm3"] == pytest.approx(0.1000, abs=1e-9)

    lot = get_lot(env["lot"]["id"])
    assert lot["staged_pallet_count"] == 4
    assert lot["available_pallet_count"] == 0
    assert lot["status"] == "STAGED"


def test_opening_an_aeration_record_moves_only_the_residual_axis():
    """PRD 3.8: "Opening the record moves the lot `PENDING_AERATION →
    AERATING` on the residual dimension and creates the record in `status`
    `IN_PROGRESS` with `retest_count` 0, `variant_applied` `STANDARD`,
    `aeration_start_at` set to the current logical-clock instant, and
    `last_failed_sample_at`, `last_eto_ppm` and `last_ech_ppm` all null."
    PRD 3.4: "The residual dimension advances only on the degassing workflow of
    §3.8 and never on a cycle or release operation, so the two dimensions
    genuinely evolve independently."

    Design: Difficulty/non_linear_state_machine/lot_status_and_residual_status_are_independent_axes
    """
    env = build_cycle_scenario(
        stage="closed",
        modality="ETO",
        product_overrides={"requires_aeration": True},
    )
    before = get_lot(env["lot"]["id"])
    assert before["status"] == "QUARANTINE"
    assert before["residual_status"] == "PENDING_AERATION"

    record = open_aeration_record(env["lot"]["id"])

    assert record["status"] == "IN_PROGRESS"
    assert record["retest_count"] == 0
    assert record["variant_applied"] == "STANDARD"
    assert record["last_failed_sample_at"] is None
    assert record["last_eto_ppm"] is None
    assert record["last_ech_ppm"] is None

    lot = get_lot(env["lot"]["id"])
    assert lot["residual_status"] == "AERATING"
    assert lot["status"] == "QUARANTINE", "the status axis is untouched by the aeration write"
    assert lot["quarantine_reason"] == "ROUTINE"


def test_release_reads_the_residual_axis_even_when_the_status_axis_is_satisfied():
    """PRD 3.9: "Next, the residual axis must be settled: a lot whose
    `residual_status` is still `PENDING_AERATION` or `AERATING` is refused with
    `ERR_AERATION_INCOMPLETE`, while `NOT_APPLICABLE` and `RESIDUAL_PASS` both
    satisfy this gate."

    Design: Difficulty/non_linear_state_machine/lot_status_and_residual_status_are_independent_axes
    """
    env = build_cycle_scenario(
        stage="closed",
        modality="ETO",
        product_overrides={"requires_aeration": True},
    )
    open_aeration_record(env["lot"]["id"])

    response = api_client.release_lot(
        env["lot"]["id"], {"release_mode": "PARAMETRIC"}, officer()
    )

    validate_error(response, ApiErrorId.ERR_AERATION_INCOMPLETE)
    lot = get_lot(env["lot"]["id"])
    assert lot["status"] == "QUARANTINE"
    assert lot["residual_status"] == "AERATING"
    assert lot["release_mode"] == "NONE"
    assert lot["released_at"] is None


def test_first_conditional_pass_re_enters_the_conditional_state():
    """PRD 3.3: "Exactly one positive is a `CONDITIONAL_PASS` and buys only 30
    days."
    PRD 3.3: "A `CONDITIONAL_PASS` increases `consecutive_conditional_count` by
    one and then looks at the new count: below 2 the qualification becomes
    `CONDITIONAL`; at 2 or above it becomes `REVOKED`, with `next_audit_due_at`
    forced to null."

    Design: Difficulty/non_linear_state_machine/qualification_conditional_loop_revokes_on_second_consecutive_conditional
    """
    env = setup_reference_data(qualify=False, clock="2026-08-20T00:00:00Z")

    audit = record_dose_audit(
        env["qualification"]["id"],
        performed_at="2026-08-20T00:00:00Z",
        positives=1,
    )

    assert audit["outcome"] == "CONDITIONAL_PASS"
    assert_instant_equals(
        audit["next_audit_due_at"], "2026-09-19T00:00:00Z", "next_audit_due_at"
    )
    assert audit["qualification_status_after"] == "CONDITIONAL"

    qualification = get_qualification(env["qualification"]["id"])
    assert qualification["status"] == "CONDITIONAL"
    assert qualification["consecutive_conditional_count"] == 1
    assert qualification["audit_interval_days"] == 30


def test_second_consecutive_conditional_pass_leaves_the_loop_into_revoked():
    """PRD 3.3: "A `CONDITIONAL_PASS` increases `consecutive_conditional_count`
    by one and then looks at the new count: below 2 the qualification becomes
    `CONDITIONAL`; at 2 or above it becomes `REVOKED`, with `next_audit_due_at`
    forced to null."
    PRD 3.3: "`CONDITIONAL → REVOKED` fires when a `CONDITIONAL_PASS` pushes
    `consecutive_conditional_count` to 2 or more — reachable from `CONDITIONAL`
    and from `AUDIT_DUE` alike — nulling `next_audit_due_at`"

    Design: Difficulty/non_linear_state_machine/qualification_conditional_loop_revokes_on_second_consecutive_conditional
    """
    env = setup_reference_data(qualify=False, clock="2026-08-20T00:00:00Z")
    record_dose_audit(
        env["qualification"]["id"], performed_at="2026-08-20T00:00:00Z", positives=1
    )

    audit = record_dose_audit(
        env["qualification"]["id"], performed_at="2026-09-19T00:00:00Z", positives=1
    )

    assert audit["outcome"] == "CONDITIONAL_PASS"
    assert audit["qualification_status_after"] == "REVOKED"

    qualification = get_qualification(env["qualification"]["id"])
    assert qualification["status"] == "REVOKED"
    assert qualification["consecutive_conditional_count"] == 2
    assert qualification["next_audit_due_at"] is None

    audits, meta = validate_paginated(
        api_client.list_dose_audits(
            env["qualification"]["id"], officer()
        )
    )
    assert meta["total_count"] == 2, "both audits are permanent laboratory records"
