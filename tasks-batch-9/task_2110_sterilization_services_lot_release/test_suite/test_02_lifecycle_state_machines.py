"""Initial states, declared transitions, terminal-state lockdown and the two
loops of the cycle machine."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_load_position,
    api_client,
    assert_instant_equals,
    build_cycle_scenario,
    close_dosimetry,
    complete_cycle,
    create_cycle,
    create_cycle_payload,
    create_lot,
    create_lot_payload,
    create_product,
    create_qualified_qualification,
    disposition_adverse_event,
    fetch_adverse_event,
    fetch_aeration_record,
    fetch_indicator,
    get_customer,
    get_cycle,
    get_lot,
    get_recipe,
    get_chamber,
    get_permit,
    make_customer_rep_headers,
    officer,
    open_aeration_record,
    operator,
    place_indicator,
    record_reading,
    record_residual_test,
    report_adverse_event,
    set_chamber_status,
    set_clock,
    set_permit_status,
    setup_reference_data,
    setup_released_lot,
    sign_ready,
    start_cycle,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["regulatory_admin_headers"]


def test_new_cycle_starts_in_planned_with_a_computed_occupancy_end():
    """PRD 3.4: "The cycle opens in `status` `PLANNED` with
    `loaded_pallet_count` 0, `load_density_g_per_cm3` 0, `abated_eto_kg` 0,
    `emission_fee_usd` 0, `deviation_code` `NONE`, and `delivered_dose_kgy`,
    `max_observed_dose_kgy`, `operator_user_id` and
    `dosimetry_closed_by_user_id` all null."
    PRD 3.4: "At creation the server derives `occupancy_end_at` as
    `scheduled_end_at` advanced by the chamber's `turnaround_minutes`, which is
    the outer edge of the chamber's occupancy."

    Design: Corner/state_machines/corner_new_cycle_starts_in_planned_with_computed_occupancy
    """
    env = setup_reference_data(qualify=False)

    data = validate_success(
        api_client.create_cycle(
            create_cycle_payload(env["chamber"]["id"], env["recipe"]["id"]), operator()
        ),
        201,
    )

    assert data["status"] == "PLANNED"
    assert_instant_equals(
        data["occupancy_end_at"], "2026-08-11T06:30:00Z", "occupancy_end_at"
    )
    assert data["loaded_pallet_count"] == 0
    assert data["load_density_g_per_cm3"] == pytest.approx(0.0, abs=1e-9)
    assert data["delivered_dose_kgy"] is None
    assert data["max_observed_dose_kgy"] is None
    assert data["deviation_code"] == "NONE"
    assert data["operator_user_id"] is None
    assert data["dosimetry_closed_by_user_id"] is None
    assert data["abated_eto_kg"] == pytest.approx(0.0, abs=1e-9)
    assert data["emission_fee_usd"] == pytest.approx(0.0, abs=1e-9)


def test_new_lot_starts_received_on_both_state_axes():
    """PRD 3.4: "The lot is born in `status` `RECEIVED` with `residual_status`
    `NOT_APPLICABLE`, `quarantine_reason` `NONE`, `staged_pallet_count` 0,
    `available_pallet_count` equal to `total_pallet_count`,
    `cumulative_dose_kgy` 0, `resterilization_count` 0, `schedulable` true,
    `release_mode` `NONE`, and `parent_lot_id`, `released_at`,
    `released_by_user_id` and `release_dose_kgy` all null"
    PRD 3.4: "The owning customer's `open_lot_count` rises by one."

    Design: Corner/state_machines/corner_new_lot_starts_received_on_both_state_axes
    """
    env = setup_reference_data(qualify=False)

    data = validate_success(
        api_client.create_lot(
            create_lot_payload(
                env["customer"]["id"], env["product"]["id"], total_pallet_count=4
            ),
            make_customer_rep_headers(env["customer"]["id"]),
        ),
        201,
    )

    assert data["status"] == "RECEIVED"
    assert data["residual_status"] == "NOT_APPLICABLE"
    assert data["staged_pallet_count"] == 0
    assert data["available_pallet_count"] == 4
    assert data["quarantine_reason"] == "NONE"
    assert data["release_mode"] == "NONE"
    assert data["schedulable"] is True
    assert data["cumulative_dose_kgy"] == pytest.approx(0.0, abs=1e-9)
    assert data["resterilization_count"] == 0
    assert data["parent_lot_id"] is None
    assert get_customer(env["customer"]["id"])["open_lot_count"] == 1


def test_complete_from_planned_is_rejected():
    """PRD 3.6: "Completing the dwell is deliberately unconditional beyond the
    state gate: a `RUNNING` cycle moves `RUNNING → COMPLETED`, every lot on its
    load map moves `IN_PROCESS → PROCESSED`"
    PRD 2.7: "Everything else yields `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/corner_complete_from_planned_rejected
    """
    env = build_cycle_scenario(stage="planned", qualify=False)

    response = api_client.complete_cycle(env["cycle"]["id"], operator())

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert get_cycle(env["cycle"]["id"])["status"] == "PLANNED"


def test_start_from_planned_returns_the_specific_cycle_not_ready_error():
    """PRD 3.6: "The cycle must be `READY`, and a start attempted from any
    other state is refused specifically with `ERR_CYCLE_NOT_READY`."

    Design: Corner/state_machines/corner_start_from_planned_returns_cycle_not_ready
    """
    env = build_cycle_scenario(
        stage="planned",
        modality="ETO",
        qualify=False,
        cycle_overrides={"raw_eto_charge_kg": 100.0},
    )

    response = api_client.start_cycle(env["cycle"]["id"], operator())

    validate_error(response, ApiErrorId.ERR_CYCLE_NOT_READY)
    cycle = get_cycle(env["cycle"]["id"])
    assert cycle["status"] == "PLANNED"
    assert cycle["abated_eto_kg"] == pytest.approx(0.0, abs=1e-9)
    assert get_permit(env["permit"]["id"])["consumed_kg_ytd"] == pytest.approx(0.0, abs=1e-9)


def test_second_readiness_sign_off_is_rejected():
    """PRD 3.6: "The sign-off is accepted while the cycle is in `LOADING`, and
    its state gate deliberately also admits a cycle still in `PLANNED` so that
    the emptiness check below stays reachable rather than being masked by a
    generic state rejection."
    PRD 2.7: "Everything else yields `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/corner_ready_twice_second_call_rejected
    """
    env = build_cycle_scenario(stage="ready")

    response = api_client.ready_cycle(env["cycle"]["id"], operator())

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert get_cycle(env["cycle"]["id"])["status"] == "READY"


def test_second_abort_of_a_cancelled_cycle_is_rejected():
    """PRD 3.6: "Aborting a cycle is available from `PLANNED`, `LOADING`,
    `READY` and `RUNNING`, and always requires a `reason` in the payload."
    PRD 3.4: "`DOSE_CONFORMING` and `CANCELLED` are terminal."

    Design: Corner/state_machines/corner_abort_of_a_cancelled_cycle_rejected
    """
    env = build_cycle_scenario(stage="planned", qualify=False)
    validate_success(
        api_client.abort_cycle(
            env["cycle"]["id"], {"reason": "customer cancelled the booking"}, operator()
        )
    )

    response = api_client.abort_cycle(
        env["cycle"]["id"], {"reason": "second abort attempt"}, operator()
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert get_cycle(env["cycle"]["id"])["status"] == "CANCELLED"


def test_releasing_an_already_released_lot_is_rejected():
    """PRD 3.9: "The chain begins with the lot's own posture: the lot must be
    in `QUARANTINE`, must not carry a `residual_status` of `RESIDUAL_FAIL`, and
    must have a governing cycle at all, with any of those three failures
    reported as `ERR_LOT_NOT_RELEASABLE`."
    PRD 3.9: "`quarantine_reason` returns to `NONE`, and the owning customer's
    `open_lot_count` falls by one."

    Design: Corner/state_machines/corner_release_of_an_already_released_lot_rejected
    """
    env = setup_released_lot()
    assert get_customer(env["customer"]["id"])["open_lot_count"] == 0

    response = api_client.release_lot(
        env["lot"]["id"], {"release_mode": "PARAMETRIC"}, officer()
    )

    validate_error(response, ApiErrorId.ERR_LOT_NOT_RELEASABLE)
    lot = get_lot(env["lot"]["id"])
    assert lot["status"] == "RELEASED"
    assert lot["release_dose_kgy"] == pytest.approx(30.00, abs=0.001)
    assert get_customer(env["customer"]["id"])["open_lot_count"] == 0


def test_approving_an_approved_recipe_is_rejected():
    """PRD 3.3: "Recipes open in `status` `DRAFT`; only a `RegulatoryAdmin` may
    advance one `DRAFT → APPROVED`, and only an `APPROVED` recipe may back a
    cycle — scheduling against a draft is refused with
    `ERR_RECIPE_NOT_APPROVED`."
    PRD 2.7: "Everything else yields `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/corner_approve_of_an_approved_recipe_rejected
    """
    env = setup_reference_data(qualify=False)

    response = api_client.approve_recipe(env["recipe"]["id"], ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert get_recipe(env["recipe"]["id"])["status"] == "APPROVED"


def test_completion_opens_the_residual_axis_only_for_aeration_products():
    """PRD 3.6: "Completing the dwell is deliberately unconditional beyond the
    state gate: a `RUNNING` cycle moves `RUNNING → COMPLETED`, every lot on its
    load map moves `IN_PROCESS → PROCESSED`, and — for each such lot, only when
    the chamber's `modality` is `ETO` and the lot's product has
    `requires_aeration` set to true — the lot's second dimension opens with
    `NOT_APPLICABLE → PENDING_AERATION`, creating the degassing obligation of
    §3.8."

    Design: Corner/state_machines/corner_complete_opens_residual_axis_only_for_aeration_products
    """
    env = setup_reference_data(
        modality="ETO", product_overrides={"requires_aeration": True}
    )
    product_b = create_product(
        env["customer"]["id"], product_code="P1B", requires_aeration=False
    )
    create_qualified_qualification(product_b["id"], env["recipe"]["id"])
    lot_a = create_lot(env["customer"]["id"], env["product"]["id"], lot_code="L-A")
    lot_b = create_lot(env["customer"]["id"], product_b["id"], lot_code="L-B")
    cycle = create_cycle(
        env["chamber"]["id"], env["recipe"]["id"], raw_eto_charge_kg=100.0
    )
    position_a = add_load_position(
        cycle["id"], lot_a["id"], position_index=1, zone="MIN_DOSE", pallet_count=2
    )
    position_b = add_load_position(
        cycle["id"], lot_b["id"], expected_cycle_version=position_a["cycle_version_after"],
        position_index=2, zone="INTERIOR", pallet_count=2,
    )
    place_indicator(
        position_a["id"], indicator_type="DOSIMETER", placement_zone="MIN_DOSE",
        serial_code="D-MIN",
    )
    place_indicator(
        position_b["id"], indicator_type="DOSIMETER", placement_zone="ROUTINE",
        serial_code="D-RT",
    )
    sign_ready(cycle["id"])
    start_cycle(cycle["id"])

    completed = complete_cycle(cycle["id"])

    assert completed["status"] == "COMPLETED"
    assert completed["load_density_g_per_cm3"] == pytest.approx(0.1000, abs=1e-9)
    stored_a = get_lot(lot_a["id"])
    assert stored_a["status"] == "PROCESSED"
    assert stored_a["residual_status"] == "PENDING_AERATION"
    stored_b = get_lot(lot_b["id"])
    assert stored_b["status"] == "PROCESSED"
    assert stored_b["residual_status"] == "NOT_APPLICABLE"


def test_first_reading_advances_a_completed_cycle_to_dosimetry_review():
    """PRD 3.7: "The very first reading recorded against a `COMPLETED` cycle
    carries that cycle `COMPLETED → DOSIMETRY_REVIEW`, which is a
    server-driven transition rather than a separate operator action."
    PRD 3.7: "A successful reading sets the indicator's `reading_status` to
    `READ` and stamps `read_at` with the logical clock and `read_by_user_id`
    with the analyst's `X-User-ID`."
    PRD 3.5: "Every indicator is born with `reading_status` `UNREAD`,
    `bi_result` `PENDING`, and `measured_dose_kgy`, `read_at` and
    `read_by_user_id` all null."

    Design: Corner/state_machines/corner_first_indicator_reading_auto_advances_completed_to_dosimetry_review
    """
    env = build_cycle_scenario(stage="completed")
    set_clock("2026-08-11T09:00:00Z")

    data = record_reading(
        env["indicators"]["min_zone"][0]["id"], measured_dose_kgy=28.50
    )

    assert data["reading_status"] == "READ"
    assert_instant_equals(data["read_at"], "2026-08-11T09:00:00Z", "read_at")
    assert data["read_by_user_id"] == "ana-1"
    assert get_cycle(env["cycle"]["id"])["status"] == "DOSIMETRY_REVIEW"

    untouched = fetch_indicator(
        env["position"]["id"], env["indicators"]["routine"][0]["id"]
    )
    assert untouched["reading_status"] == "UNREAD"
    assert untouched["measured_dose_kgy"] is None


def test_reread_on_a_deviated_cycle_reopens_dosimetry_review():
    """PRD 3.7: "When the indicator's cycle is sitting in `DOSE_DEVIATION`, a
    re-read is the documented mechanism for correcting a mis-read instrument:
    the indicator's `measured_dose_kgy` or `bi_result` is overwritten,
    `read_at` and `read_by_user_id` are refreshed, the cycle's `deviation_code`
    returns to `NONE`, its `delivered_dose_kgy` and `max_observed_dose_kgy` are
    cleared back to null, and the cycle walks `DOSE_DEVIATION →
    DOSIMETRY_REVIEW` so that the close may be attempted again on corrected
    data."
    PRD 3.7: "Any lot on this cycle that is already in `QUARANTINE` carrying
    `quarantine_reason` of `DOSE_DEVIATION` or `BI_POSITIVE` — the residue of a
    previous deviated close on this same cycle that has since been corrected by
    re-reads — has its `quarantine_reason` reset to `ROUTINE` and its
    `schedulable` flag restored to true, compensating the earlier cascade."

    Design: Corner/state_machines/corner_reread_on_deviated_cycle_reopens_dosimetry_review
    """
    env = build_cycle_scenario(
        stage="review", min_zone_dose=19.00, routine_dose=20.00
    )
    deviated = close_dosimetry(env["cycle"]["id"])
    assert deviated["status"] == "DOSE_DEVIATION"
    assert deviated["deviation_code"] == "UNDERDOSE"
    assert deviated["delivered_dose_kgy"] == pytest.approx(20.00, abs=0.001)

    reread = record_reading(
        env["indicators"]["routine"][0]["id"], measured_dose_kgy=30.00
    )

    assert reread["measured_dose_kgy"] == pytest.approx(30.00, abs=0.001)
    reopened = get_cycle(env["cycle"]["id"])
    assert reopened["status"] == "DOSIMETRY_REVIEW"
    assert reopened["deviation_code"] == "NONE"
    assert reopened["delivered_dose_kgy"] is None
    assert reopened["max_observed_dose_kgy"] is None

    closed = close_dosimetry(env["cycle"]["id"])
    assert closed["status"] == "DOSE_CONFORMING"
    assert closed["delivered_dose_kgy"] == pytest.approx(30.00, abs=0.001)

    lot = get_lot(env["lot"]["id"])
    assert lot["status"] == "QUARANTINE"
    assert lot["quarantine_reason"] == "ROUTINE"
    assert lot["schedulable"] is True
    assert lot["cumulative_dose_kgy"] == pytest.approx(30.00, abs=0.001)


def test_residual_retest_loop_exhausts_after_a_third_failure():
    """PRD 3.8: "A failure is tolerated at most twice: the facility grants a
    retest budget of two failed samples per record."
    PRD 3.8: "When a failure arrives that would push `retest_count` past two,
    the budget is exhausted. `retest_count` still rises by one, the record
    moves `RETEST_REQUIRED → EXHAUSTED`, and the failure propagates: the lot
    moves `AERATING → RESIDUAL_FAIL` on the residual dimension and
    simultaneously `QUARANTINE → REJECTED` on the primary dimension with
    `quarantine_reason` set to `RESIDUAL_FAIL`, and the owning customer's
    `open_lot_count` falls by one because the lot has left the open set for
    good."
    PRD 3.8: "Every accepted test records `last_eto_ppm` and `last_ech_ppm` on
    the record regardless of its verdict."

    Design: Corner/state_machines/corner_residual_retest_self_loop_exhausts_and_rejects_lot
    """
    env = build_cycle_scenario(
        stage="closed", modality="ETO", product_overrides={"requires_aeration": True}
    )
    set_clock("2026-08-12T08:00:00Z")
    record = open_aeration_record(env["lot"]["id"])
    assert record["required_hours"] == 15

    set_clock("2026-08-12T23:00:00Z")
    first = record_residual_test(record["id"], eto_residual_ppm=8.0, ech_residual_ppm=1.0)
    assert first["status"] == "RETEST_REQUIRED"
    assert first["retest_count"] == 1
    assert first["required_hours"] == 23
    assert_instant_equals(first["target_end_at"], "2026-08-13T22:00:00Z", "target_end_at")

    set_clock("2026-08-13T22:00:00Z")
    second = record_residual_test(record["id"], eto_residual_ppm=7.0, ech_residual_ppm=1.0)
    assert second["status"] == "RETEST_REQUIRED"
    assert second["retest_count"] == 2
    assert second["required_hours"] == 30
    assert_instant_equals(second["target_end_at"], "2026-08-15T04:00:00Z", "target_end_at")

    set_clock("2026-08-15T04:00:00Z")
    third = record_residual_test(record["id"], eto_residual_ppm=6.0, ech_residual_ppm=1.0)

    assert third["status"] == "EXHAUSTED"
    assert third["retest_count"] == 3
    stored = fetch_aeration_record(env["lot"]["id"], record["id"])
    assert stored["last_eto_ppm"] == pytest.approx(6.0, abs=0.001)
    assert stored["last_ech_ppm"] == pytest.approx(1.0, abs=0.001)

    lot = get_lot(env["lot"]["id"])
    assert lot["residual_status"] == "RESIDUAL_FAIL"
    assert lot["status"] == "REJECTED"
    assert lot["quarantine_reason"] == "RESIDUAL_FAIL"
    assert get_customer(env["customer"]["id"])["open_lot_count"] == 0


def test_dismiss_branch_rolls_the_quarantine_reason_back_to_routine():
    """PRD 3.9: "The event is created in `status` `REPORTED` with
    `reported_by_user_id` set from the caller's `X-User-ID`, `lot_version_after`
    snapshotting the lot's `version` immediately after the write, and
    `disposition` null. If the subject lot is in `QUARANTINE`, its
    `quarantine_reason` is set to `ADVERSE_EVENT`."
    PRD 3.9: "`DISMISS` is the gentlest: the event moves `REPORTED →
    DISMISSED`, and if the lot is sitting in `QUARANTINE` its
    `quarantine_reason` walks back from `ADVERSE_EVENT` to `ROUTINE`. The lot's
    `status` is untouched, so a dismissed complaint leaves a quarantined lot
    releasable on its original merits."

    Design: Corner/state_machines/corner_adverse_event_dismiss_branch_restores_routine_quarantine_reason
    """
    env = build_cycle_scenario(stage="closed")
    event = report_adverse_event(
        env["lot"]["id"],
        reporter_headers=officer(),
        event_type="FIELD_DOSE_DEVIATION",
        severity="MEDIUM",
        description="Field dose deviation reported by the customer",
    )
    before = get_lot(env["lot"]["id"])
    assert before["quarantine_reason"] == "ADVERSE_EVENT"
    assert event["lot_version_after"] == before["version"]
    assert event["reported_by_user_id"] == "qro-1"

    dispositioned = disposition_adverse_event(event["id"], "DISMISS")

    assert dispositioned["status"] == "DISMISSED"
    assert dispositioned["disposition"] == "DISMISS"
    lot = get_lot(env["lot"]["id"])
    assert lot["status"] == "QUARANTINE"
    assert lot["quarantine_reason"] == "ROUTINE"


def test_decommissioned_chamber_is_terminal():
    """PRD 3.2: "The administrator may also retire it, `AVAILABLE →
    DECOMMISSIONED` or `MAINTENANCE → DECOMMISSIONED`; `DECOMMISSIONED` is
    terminal and additionally blocks scheduling any new cycle into that
    chamber, again with `ERR_CHAMBER_UNAVAILABLE`."
    PRD 2.7: "Everything else yields `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/corner_decommissioned_chamber_is_terminal
    """
    env = setup_reference_data(qualify=False)
    set_chamber_status(env["chamber"]["id"], "DECOMMISSIONED")

    reinstate = api_client.set_chamber_status(
        env["chamber"]["id"], {"status": "AVAILABLE"}, ADMIN
    )
    schedule = api_client.create_cycle(
        create_cycle_payload(env["chamber"]["id"], env["recipe"]["id"]), operator()
    )

    validate_error(reinstate, ApiErrorId.ERR_INVALID_STATE)
    validate_error(schedule, ApiErrorId.ERR_CHAMBER_UNAVAILABLE)
    assert get_chamber(env["chamber"]["id"])["status"] == "DECOMMISSIONED"


def test_expired_permit_is_terminal():
    """PRD 3.2: "`ACTIVE → EXPIRED` and `SUSPENDED → EXPIRED` are both
    commanded by a `RegulatoryAdmin` and are permanent — there is no transition
    out of `EXPIRED`, and an `EXPIRED` permit blocks cycle starts with the same
    `ERR_PERMIT_NOT_ACTIVE`."
    PRD 2.7: "Everything else yields `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/corner_expired_permit_is_terminal
    """
    set_clock("2026-08-10T00:00:00Z")
    permit = validate_success(
        api_client.create_permit(
            {
                "permit_code": "AP-2026",
                "permit_year": 2026,
                "annual_allowance_kg": 1000.0,
                "max_concurrent_eto_cycles": 2,
            },
            ADMIN,
        ),
        201,
    )
    set_permit_status(permit["id"], "EXPIRED")

    response = api_client.set_permit_status(permit["id"], {"status": "ACTIVE"}, ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert get_permit(permit["id"])["status"] == "EXPIRED"


def test_dispositioning_an_already_dispositioned_event_is_rejected():
    """PRD 3.9: "Dispositioning a reported event is reserved to a
    `QualityReleaseOfficer` and takes one field, `disposition`, whose three
    values are `RESTERILIZE`, `SCRAP` and `DISMISS`. All three outcomes are
    terminal for the event, and all three require the event to still be in
    `REPORTED`."
    PRD 2.7: "Everything else yields `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/corner_dispositioning_a_dispositioned_event_rejected
    """
    env = setup_released_lot()
    event = report_adverse_event(
        env["lot"]["id"],
        reporter_headers=officer(),
        event_type="PACKAGING_BREACH",
        severity="LOW",
        description="Outer carton seal breached in transit",
    )
    disposition_adverse_event(event["id"], "SCRAP")

    response = api_client.disposition_adverse_event(
        event["id"], {"disposition": "DISMISS"}, officer()
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    stored = fetch_adverse_event(env["lot"]["id"], event["id"])
    assert stored["status"] == "SCRAP_APPROVED"
    assert stored["disposition"] == "SCRAP"
    lot = get_lot(env["lot"]["id"])
    assert lot["status"] == "SCRAPPED"
    assert lot["schedulable"] is False
