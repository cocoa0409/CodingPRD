"""Non-linear state machines: genuine cycles and independent parallel axes.

A diet order can loop back into the verification queue a bounded number of times,
and a production batch carries two axes where the quality axis may travel
backwards while the production axis stands still.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiClient, ApiErrorId, assertions, factories, fixtures
from test_helpers import test_users as users


# ---------------------------------------------------------------------------
# Diet order: PENDING_VERIFICATION -> ACTIVE -> SUSPENDED -> PENDING_VERIFICATION
# ---------------------------------------------------------------------------


def _active_medical_order(api: ApiClient) -> dict:
    """A verified therapeutic diet order on a general-population inmate."""
    ctx = fixtures.active_contract_with_facility(
        api,
        contract_overrides={"contract_code": "CFS-2515-NL1"},
        facility_overrides={
            "facility_code": "FAC-NL1",
            "sharps_authorized_count": 12,
        },
    )
    inmate = fixtures.create_inmate(api, ctx["facility"]["id"])
    order = validate_success(
        api.create_diet_order(
            factories.medical_diet_order_payload(inmate["id"], inmate["version"]),
            users.DIETITIAN,
        ),
        201,
    )
    verified = validate_success(api.verify_diet_order(order["id"], users.MEDICAL))
    ctx["inmate"] = inmate
    ctx["order"] = verified
    return ctx


def _suspend(api: ApiClient, order_id: str, reason: str) -> dict:
    return validate_success(
        api.suspend_diet_order(
            order_id, {"suspension_reason": reason}, users.FOOD_SUPERVISOR
        )
    )


def test_each_reverification_lap_clears_the_verification_stamps_and_recounts(
    api: ApiClient,
) -> None:
    """Reverification returns a suspended order to the queue with its attestation
    wiped, and re-verification restamps it from the logical clock.

    The PRD states: "Reverification, a `RegisteredDietitian` action taking no
    payload, moves a `SUSPENDED` order back to `PENDING_VERIFICATION`:
    `reverification_count` is incremented by 1, `verified_by_user_id`,
    `verified_at`, `verification_expires_at` and `suspension_reason` are all cleared
    to null, `requested_by_user_id` is overwritten with the requesting operator's
    `X-User-ID`, and `version` is incremented by 1." On re-verification
    "`verification_expires_at` is `verified_at` plus a validity window that depends
    on the family: a religious accommodation is good for 180 days, a therapeutic
    diet for only 30", so a therapeutic diet verified at the default clock instant
    expires on the thirty-first of August.

    Design: Difficulty/non_linear_state_machine/diet_order_suspend_reverify_cycle_caps_at_two_reverifications
    """
    ctx = _active_medical_order(api)
    order_id = ctx["order"]["id"]

    _suspend(api, order_id, "First refusal streak")
    requeued = validate_success(api.request_reverification(order_id, users.DIETITIAN))

    assert requeued["status"] == "PENDING_VERIFICATION"
    assert requeued["reverification_count"] == 1
    assert requeued["verified_by_user_id"] is None
    assert requeued["verified_at"] is None
    assert requeued["verification_expires_at"] is None
    assert requeued["suspension_reason"] is None
    assert requeued["requested_by_user_id"] == users.user_id_of(users.DIETITIAN)

    reverified = validate_success(api.verify_diet_order(order_id, users.MEDICAL))

    assert reverified["status"] == "ACTIVE"
    assert reverified["verified_by_user_id"] == users.user_id_of(users.MEDICAL)
    assertions.assert_instant(reverified["verified_at"], "2026-08-01T00:00:00Z")
    assertions.assert_instant(
        reverified["verification_expires_at"], "2026-08-31T00:00:00Z"
    )
    assert reverified["reverification_count"] == 1

    _suspend(api, order_id, "Second refusal streak")
    second_lap = validate_success(api.request_reverification(order_id, users.DIETITIAN))
    assert second_lap["reverification_count"] == 2
    assert second_lap["status"] == "PENDING_VERIFICATION"


def test_a_third_reverification_is_refused_at_the_ceiling_of_two(
    api: ApiClient,
) -> None:
    """The cycle is bounded: after two laps the order is stuck in SUSPENDED and the
    census counters have already been released.

    The PRD states: "This edge closes a genuine cycle — `PENDING_VERIFICATION` →
    `ACTIVE` → `SUSPENDED` → `PENDING_VERIFICATION` — but it is bounded: an order
    whose `reverification_count` has already reached 2 cannot go round again, and
    the attempt reports `ERR_REVERIFICATION_LIMIT_REACHED`." Suspension itself
    "decrements both census counters by 1", so the inmate and facility tallies read
    zero while the order waits.

    Design: Difficulty/non_linear_state_machine/diet_order_suspend_reverify_cycle_caps_at_two_reverifications
    """
    ctx = _active_medical_order(api)
    order_id = ctx["order"]["id"]

    for lap, reason in enumerate(
        ("First refusal streak", "Second refusal streak"), start=1
    ):
        _suspend(api, order_id, reason)
        requeued = validate_success(
            api.request_reverification(order_id, users.DIETITIAN)
        )
        assert requeued["reverification_count"] == lap
        validate_success(api.verify_diet_order(order_id, users.MEDICAL))

    _suspend(api, order_id, "Third refusal streak")

    validate_error(
        api.request_reverification(order_id, users.DIETITIAN),
        ApiErrorId.ERR_REVERIFICATION_LIMIT_REACHED.value,
        409,
    )

    final = fixtures.read_diet_order(api, order_id)
    assert final["status"] == "SUSPENDED"
    assert final["reverification_count"] == 2
    assert final["suspension_reason"] == "Third refusal streak"

    inmate = validate_success(api.get_inmate(ctx["inmate"]["id"], users.OFFICER))
    assert inmate["active_diet_order_count"] == 0
    facility = fixtures.read_facility(api, ctx["facility"]["id"])
    assert facility["active_special_diet_count"] == 0


# ---------------------------------------------------------------------------
# Production batch: two independent axes
# ---------------------------------------------------------------------------


def _batch_chilled_on_qa_hold(api: ApiClient) -> dict:
    """A batch driven to CHILLED whose QA axis has been pulled back to QA_HELD by
    an out-of-range final chill reading."""
    ctx = fixtures.locked_forecast(
        api,
        contract_overrides={"contract_code": "CFS-2515-NL2"},
        facility_overrides={
            "facility_code": "FAC-NL2",
            "sharps_authorized_count": 12,
        },
    )
    assert ctx["forecast"]["total_forecast_trays"] == 22
    ctx = fixtures.planned_batch(
        api,
        ctx,
        planned_trays=10,
        scheduled_cook_start_at="2026-08-01T06:00:00Z",
        service_site="MAIN_KITCHEN",
    )
    batch_id = ctx["batch"]["id"]

    fixtures.set_clock(api, "2026-08-01T10:00:00Z")
    validate_success(
        api.post_temperature_log(
            batch_id,
            factories.temperature_log_payload("COOK_END", 170.0),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    validate_success(
        api.advance_stage(
            batch_id,
            factories.advance_stage_payload("COOKED", produced_trays=10),
            users.FOOD_SUPERVISOR,
        )
    )

    fixtures.set_clock(api, "2026-08-01T11:00:00Z")
    validate_success(
        api.post_temperature_log(
            batch_id,
            factories.temperature_log_payload("CHILL_INTERMEDIATE", 78.0),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )

    fixtures.set_clock(api, "2026-08-01T12:00:00Z")
    validate_success(
        api.post_temperature_log(
            batch_id,
            factories.temperature_log_payload("CHILL_FINAL", 45.0),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    chilled = validate_success(
        api.advance_stage(
            batch_id, factories.advance_stage_payload("CHILLED"), users.FOOD_SUPERVISOR
        )
    )
    ctx["batch"] = chilled
    return ctx


def test_out_of_range_chill_final_holds_the_qa_axis_while_the_stage_axis_advances(
    api: ApiClient,
) -> None:
    """The production axis reaches CHILLED on the strength of a reading that is out
    of range, and then cannot pass STAGED because the QA axis is held.

    The PRD states: "Moving `COOKED` → `CHILLED` requires an existing `CHILL_FINAL`
    reading — in range or not — otherwise `ERR_CHILL_LOG_MISSING`." It also states
    that "an out-of-range `CHILL_INTERMEDIATE` or `CHILL_FINAL` reading moves
    `qa_status` to `QA_HELD` with `qa_reason` set to the literal string
    `CHILL_GATE_FAILED`", and that "Moving `CHILLED` → `STAGED` requires `qa_status`
    to read exactly `QA_PASSED`, otherwise `ERR_QA_NOT_PASSED`."

    Design: Difficulty/non_linear_state_machine/production_batch_qa_axis_loops_back_while_stage_axis_holds_at_chilled
    """
    ctx = _batch_chilled_on_qa_hold(api)
    batch_id = ctx["batch"]["id"]

    assert ctx["batch"]["production_stage"] == "CHILLED"
    assert ctx["batch"]["qa_status"] == "QA_HELD"
    assert ctx["batch"]["qa_reason"] == "CHILL_GATE_FAILED"
    assert ctx["batch"]["produced_trays"] == 10
    assert ctx["batch"]["cook_chill_compliant"] is False

    validate_error(
        api.advance_stage(
            batch_id, factories.advance_stage_payload("STAGED"), users.FOOD_SUPERVISOR
        ),
        ApiErrorId.ERR_QA_NOT_PASSED.value,
        409,
    )

    unchanged = fixtures.read_batch(api, batch_id)
    assert unchanged["production_stage"] == "CHILLED"
    assert unchanged["qa_status"] == "QA_HELD"


def test_a_later_in_range_reading_rehabilitates_the_batch_and_frees_the_stage_axis(
    api: ApiClient,
) -> None:
    """A second final chill reading that is in range re-anchors `chill_final_at`,
    turns the compliance flag true and lets an explicit verdict release the hold.

    The PRD states: "This is an existence test rather than a universal one, so a
    later in-range reading at the same control point rehabilitates an earlier
    out-of-range one for the purposes of the flag — but the out-of-range reading has
    already pushed `qa_status` to `QA_HELD`, and only an explicit QA verdict can
    leave `QA_HELD`." It adds that "`chill_final_at` is the `logged_at` of the
    earliest in-range `CHILL_FINAL` reading", and that "A `QA_PASSED` verdict may be
    recorded from `QA_PENDING` or from `QA_HELD`, and only when
    `cook_chill_compliant` is true".

    Design: Difficulty/non_linear_state_machine/production_batch_qa_axis_loops_back_while_stage_axis_holds_at_chilled
    """
    ctx = _batch_chilled_on_qa_hold(api)
    batch_id = ctx["batch"]["id"]

    fixtures.set_clock(api, "2026-08-01T13:00:00Z")
    reading = validate_success(
        api.post_temperature_log(
            batch_id,
            factories.temperature_log_payload("CHILL_FINAL", 38.0),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    assertions.assert_temperature_log(reading)
    assert reading["in_range"] is True
    assert reading["minutes_since_cook_end"] == 180

    rehabilitated = fixtures.read_batch(api, batch_id)
    assertions.assert_instant(rehabilitated["chill_final_at"], "2026-08-01T13:00:00Z")
    assert rehabilitated["chill_minutes"] == 180
    assert rehabilitated["cook_chill_compliant"] is True
    assert rehabilitated["qa_status"] == "QA_HELD"
    assert rehabilitated["production_stage"] == "CHILLED"

    passed = validate_success(
        api.qa_decision(
            batch_id,
            factories.qa_decision_payload(
                "QA_PASSED", "Rehabilitated by in-range CHILL_FINAL at 13:00Z"
            ),
            users.DIETITIAN,
        )
    )
    assert passed["qa_status"] == "QA_PASSED"
    assert passed["production_stage"] == "CHILLED"

    staged = validate_success(
        api.advance_stage(
            batch_id, factories.advance_stage_payload("STAGED"), users.FOOD_SUPERVISOR
        )
    )
    assert staged["production_stage"] == "STAGED"
    assert staged["qa_status"] == "QA_PASSED"
    assert staged["produced_trays"] == 10
