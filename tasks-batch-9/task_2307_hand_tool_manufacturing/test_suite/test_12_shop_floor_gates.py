"""The gates that stand between a request and a booked furnace, a scheduled test
run or a recorded reading."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_lot,
    api_client,
    assert_specimen_ledger,
    create_chamber,
    create_furnace,
    create_lot,
    create_sku,
    furnace_campaign_payload,
    furnace_status_payload,
    campaign_complete_payload,
    read_campaign,
    read_lot,
    read_test_run,
    schedule_campaign,
    schedule_test_run,
    setup_lot_at_stage,
    setup_lot_with_completed_campaign,
    make_test_results_payload,
    make_test_run_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

PP = TEST_USERS["production_planner_headers"]
QE = TEST_USERS["quality_engineer_headers"]

CAMPAIGN_WINDOW = ("2026-08-02T06:00:00Z", "2026-08-02T10:00:00Z")
HARDNESS_SLOT = ("2026-08-03T08:00:00Z", "2026-08-03T09:00:00Z")
CORROSION_SLOT = ("2026-08-04T00:00:00Z", "2026-08-08T00:00:00Z")


# ---------------------------------------------------------------------------
# The reading array is measured against the run's own specimen count
# ---------------------------------------------------------------------------


def _scheduled_hardness_run():
    ctx = setup_lot_with_completed_campaign(lot_overrides={"specimen_pool_total": 20})
    advance_lot(ctx["lot"]["id"], "HEAT_TREATED")
    ctx["run"] = schedule_test_run(ctx["lot"]["id"], "HARDNESS", 2, HARDNESS_SLOT)
    return ctx


def test_three_readings_on_a_two_specimen_run_are_refused_and_nothing_is_recorded():
    """The arity is checked against the run's own `specimen_count`, and the refusal
    leaves the run scheduled with no derived statistics.

    PRD §3.4: "Its length must equal the run's `specimen_count`, and a mismatch is
    `ERR_READING_COUNT_MISMATCH` — evaluated as a request-shape fault, and
    therefore reported ahead of the run's own state."

    Design: Corner/validations/reading_count_must_equal_specimen_count
    """
    ctx = _scheduled_hardness_run()

    validate_error(
        api_client.submit_test_run_results(
            ctx["run"]["id"], make_test_results_payload((52.0, 53.0, 51.0)), QE
        ),
        ApiErrorId.ERR_READING_COUNT_MISMATCH,
        422,
    )

    unchanged = read_test_run(ctx["run"]["id"])
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["mean_reading"] is None
    assert unchanged["readings"] is None


def test_the_matching_reading_count_is_then_accepted_on_the_same_run():
    """Two readings on a two-specimen run resolve it, so the earlier refusal was
    about arity alone.

    PRD §3.4: "Adjudication first computes `mean_reading`, the arithmetic mean of
    the supplied readings rounded half up to one decimal place."

    Design: Corner/validations/reading_count_must_equal_specimen_count
    """
    ctx = _scheduled_hardness_run()
    validate_error(
        api_client.submit_test_run_results(
            ctx["run"]["id"], make_test_results_payload((52.0, 53.0, 51.0)), QE
        ),
        ApiErrorId.ERR_READING_COUNT_MISMATCH,
    )

    resolved = validate_success(
        api_client.submit_test_run_results(ctx["run"]["id"], make_test_results_payload((52.0, 53.0)), QE)
    )

    assert resolved["status"] == "PASSED"
    assert resolved["mean_reading"] == pytest.approx(52.5, abs=0.01)


# ---------------------------------------------------------------------------
# The chamber field is a two-sided conditional on test_type
# ---------------------------------------------------------------------------


def _heat_treated_lot_and_a_cabinet():
    ctx = setup_lot_with_completed_campaign(lot_overrides={"specimen_pool_total": 20})
    advance_lot(ctx["lot"]["id"], "HEAT_TREATED")
    ctx["chamber"] = create_chamber(coupon_capacity=24)
    return ctx


def test_a_corrosion_run_without_a_cabinet_is_refused_for_the_missing_cabinet():
    """The lot has not even reached PLATED, yet the missing `chamber_id` is a
    request-shape fault and outranks the stage gate.

    PRD §3.3: "Corrosion testing additionally names a `chamber_id`: for a
    `SALT_SPRAY` run the field is required and its absence is
    `ERR_CHAMBER_REQUIRED`, while for every other test type it must be absent or
    null and supplying it is `ERR_CHAMBER_NOT_APPLICABLE`."

    Design: Corner/validations/chamber_presence_is_conditional_on_test_type
    """
    ctx = _heat_treated_lot_and_a_cabinet()

    body = validate_error(
        api_client.create_test_run(
            make_test_run_payload(
                ctx["lot"]["id"],
                test_type="SALT_SPRAY",
                specimen_count=2,
                window_start=CORROSION_SLOT[0],
                window_end=CORROSION_SLOT[1],
            ),
            QE,
        ),
        ApiErrorId.ERR_CHAMBER_REQUIRED,
        422,
    )
    assert body["error_id"] != ApiErrorId.ERR_TEST_STAGE_TOO_EARLY
    assert read_lot(ctx["lot"]["id"])["process_status"] == "HEAT_TREATED"


def test_a_hardness_run_carrying_a_cabinet_is_refused_for_the_surplus_cabinet():
    """The same field that is mandatory for corrosion is forbidden everywhere else,
    and the chamberless request then succeeds with a null cabinet.

    PRD §3.3: "for every other test type it must be absent or null and supplying it
    is `ERR_CHAMBER_NOT_APPLICABLE`."

    Design: Corner/validations/chamber_presence_is_conditional_on_test_type
    """
    ctx = _heat_treated_lot_and_a_cabinet()
    payload = make_test_run_payload(
        ctx["lot"]["id"],
        test_type="HARDNESS",
        specimen_count=2,
        window_start=HARDNESS_SLOT[0],
        window_end=HARDNESS_SLOT[1],
    )

    validate_error(
        api_client.create_test_run(dict(payload, chamber_id=ctx["chamber"]["id"]), QE),
        ApiErrorId.ERR_CHAMBER_NOT_APPLICABLE,
        422,
    )

    accepted = validate_success(api_client.create_test_run(payload, QE), 201)
    assert accepted["chamber_id"] is None

    lot = read_lot(ctx["lot"]["id"])
    assert lot["specimens_committed"] == 2
    assert_specimen_ledger(lot)


# ---------------------------------------------------------------------------
# The furnace basket and the soak floor
# ---------------------------------------------------------------------------


def _lot_and_a_nine_hundred_kilogram_furnace():
    sku = create_sku()
    furnace = create_furnace(max_charge_kg=900, alloy_grades_supported=["CR_MO"])
    lot = create_lot(sku["id"], specimen_pool_total=20)
    return sku, furnace, lot


def test_a_basket_one_kilogram_over_the_limit_is_refused_while_the_exact_limit_books():
    """900 kg against a 900 kg basket is accepted because the comparison is
    inclusive, and 901 creates nothing.

    PRD §3.2: "**The charge comes third**: `charge_kg` may not exceed the furnace's
    `max_charge_kg`, and exceeding it is `ERR_FURNACE_CHARGE_EXCEEDED`."

    Design: Corner/validations/campaign_charge_and_soak_limits_with_inclusive_soak_boundary
    """
    _, furnace, lot = _lot_and_a_nine_hundred_kilogram_furnace()
    overweight = furnace_campaign_payload(
        lot["id"],
        furnace["id"],
        window_start=CAMPAIGN_WINDOW[0],
        window_end=CAMPAIGN_WINDOW[1],
        charge_kg=901,
    )

    validate_error(
        api_client.create_furnace_campaign(overweight, PP),
        ApiErrorId.ERR_FURNACE_CHARGE_EXCEEDED,
        422,
    )
    _, empty = validate_paginated(api_client.list_furnace_campaigns(PP))
    assert empty["total_count"] == 0

    accepted = validate_success(
        api_client.create_furnace_campaign(dict(overweight, charge_kg=900), PP), 201
    )
    assert accepted["status"] == "SCHEDULED"
    assert accepted["charge_kg"] == 900

    _, meta = validate_paginated(api_client.list_furnace_campaigns(PP))
    assert meta["total_count"] == 1


def test_a_fifty_nine_minute_soak_is_refused_while_exactly_one_hour_completes():
    """The soak floor is a full hour and the comparison is inclusive, so 59 leaves
    the campaign scheduled with no soak recorded and 60 completes it.

    PRD §3.2: "the reported soak must be at least a full hour — 60 minutes —
    otherwise `ERR_SOAK_TIME_TOO_SHORT`."

    Design: Corner/validations/campaign_charge_and_soak_limits_with_inclusive_soak_boundary
    """
    _, furnace, lot = _lot_and_a_nine_hundred_kilogram_furnace()
    campaign = schedule_campaign(
        lot["id"],
        furnace["id"],
        window_start=CAMPAIGN_WINDOW[0],
        window_end=CAMPAIGN_WINDOW[1],
        charge_kg=900,
    )

    validate_error(
        api_client.complete_furnace_campaign(
            campaign["id"], campaign_complete_payload(soak_minutes=59), PP
        ),
        ApiErrorId.ERR_SOAK_TIME_TOO_SHORT,
        422,
    )
    still_scheduled = read_campaign(campaign["id"])
    assert still_scheduled["status"] == "SCHEDULED"
    assert still_scheduled["soak_minutes"] is None

    completed = validate_success(
        api_client.complete_furnace_campaign(
            campaign["id"], campaign_complete_payload(soak_minutes=60), PP
        )
    )
    assert completed["status"] == "COMPLETED"
    assert completed["soak_minutes"] == 60


def test_a_furnace_in_maintenance_takes_no_booking_until_it_is_returned_to_service():
    """Availability is read at scheduling time, so the identical request fails and
    then succeeds with nothing changed but the furnace's own status.

    PRD §3.2: "The furnace must be `AVAILABLE`, otherwise
    `ERR_FURNACE_UNAVAILABLE`."

    Design: Corner/validations/campaign_requires_available_furnace_at_scheduling_time
    """
    _, furnace, lot = _lot_and_a_nine_hundred_kilogram_furnace()
    validate_success(
        api_client.set_furnace_status(
            furnace["id"], furnace_status_payload(status="MAINTENANCE"), PP
        )
    )
    booking = furnace_campaign_payload(
        lot["id"],
        furnace["id"],
        window_start=CAMPAIGN_WINDOW[0],
        window_end=CAMPAIGN_WINDOW[1],
        charge_kg=800,
    )

    validate_error(
        api_client.create_furnace_campaign(booking, PP),
        ApiErrorId.ERR_FURNACE_UNAVAILABLE,
        409,
    )
    _, empty = validate_paginated(api_client.list_furnace_campaigns(PP))
    assert empty["total_count"] == 0

    restored = validate_success(
        api_client.set_furnace_status(
            furnace["id"], furnace_status_payload(status="AVAILABLE"), PP
        )
    )
    assert restored["status"] == "AVAILABLE"
    assert restored["version"] == 3

    accepted = validate_success(api_client.create_furnace_campaign(booking, PP), 201)
    assert accepted["status"] == "SCHEDULED"

    _, meta = validate_paginated(api_client.list_furnace_campaigns(PP))
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# The stage gate and the temporal gate
# ---------------------------------------------------------------------------


def test_a_post_heat_treatment_window_may_start_exactly_when_the_soak_ended():
    """The floor is the earliest completed campaign's `window_end`, and one minute
    earlier is refused while the instant itself is inside the allowed region.

    PRD §3.3: "the run's `window_start` may not fall before the earliest
    `window_end` among the lot's `COMPLETED` campaigns, and a window that starts
    earlier is `ERR_TEST_WINDOW_BEFORE_HEAT_TREAT`."

    Design: Corner/validations/test_window_must_not_precede_completed_heat_treatment
    """
    ctx = setup_lot_at_stage("MACHINED", lot_overrides={"specimen_pool_total": 20})
    lot_id = ctx["lot"]["id"]
    early = make_test_run_payload(
        lot_id,
        test_type="DIMENSIONAL",
        specimen_count=2,
        window_start="2026-08-02T09:59:00Z",
        window_end="2026-08-02T11:00:00Z",
    )

    validate_error(
        api_client.create_test_run(early, QE),
        ApiErrorId.ERR_TEST_WINDOW_BEFORE_HEAT_TREAT,
        422,
    )

    accepted = validate_success(
        api_client.create_test_run(dict(early, window_start="2026-08-02T10:00:00Z"), QE), 201
    )
    assert accepted["status"] == "SCHEDULED"

    lot = read_lot(lot_id)
    assert lot["specimens_committed"] == 2
    assert_specimen_ledger(lot)


def test_each_test_type_carries_its_own_stage_requirement():
    """At HEAT_TREATED both machining tests are premature; after the advance the
    dimensional run books while corrosion still waits for plating.

    PRD §3.3: "`DIMENSIONAL` and `PROOF_TORQUE` runs require the lot to have
    reached at least `MACHINED`, `SALT_SPRAY` runs require at least `PLATED`, and
    `MECHANISM_CYCLE` runs require `ASSEMBLED`."

    Design: Corner/validations/post_machining_test_types_rejected_before_machining
    """
    ctx = _heat_treated_lot_and_a_cabinet()
    lot_id = ctx["lot"]["id"]

    for test_type in ("DIMENSIONAL", "PROOF_TORQUE"):
        validate_error(
            api_client.create_test_run(
                make_test_run_payload(
                    lot_id,
                    test_type=test_type,
                    specimen_count=2,
                    window_start="2026-08-03T08:00:00Z",
                    window_end="2026-08-03T09:00:00Z",
                ),
                QE,
            ),
            ApiErrorId.ERR_TEST_STAGE_TOO_EARLY,
            409,
        )

    assert advance_lot(lot_id, "MACHINED")["process_status"] == "MACHINED"

    accepted = validate_success(
        api_client.create_test_run(
            make_test_run_payload(
                lot_id,
                test_type="DIMENSIONAL",
                specimen_count=2,
                window_start="2026-08-03T08:00:00Z",
                window_end="2026-08-03T09:00:00Z",
            ),
            QE,
        ),
        201,
    )
    assert accepted["status"] == "SCHEDULED"
    assert read_lot(lot_id)["cert_status"] == "IN_TEST"

    validate_error(
        api_client.create_test_run(
            make_test_run_payload(
                lot_id,
                test_type="SALT_SPRAY",
                specimen_count=2,
                window_start=CORROSION_SLOT[0],
                window_end=CORROSION_SLOT[1],
                chamber_id=ctx["chamber"]["id"],
            ),
            QE,
        ),
        ApiErrorId.ERR_TEST_STAGE_TOO_EARLY,
        409,
    )


def test_a_corrosion_booking_that_clears_every_gate_moves_all_three_entities_correctly():
    """Cabinet supplied, lot plated, window after the soak, specimens inside the
    pool and coupons inside capacity: the run books, the pool moves and the dossier
    opens, while the cabinet row itself is untouched.

    PRD §3.3: "A successfully scheduled run is created with `status` `SCHEDULED`,
    and its `specimen_count` moves from the lot's `specimens_available` into
    `specimens_committed`, which increments the lot's `version` as well as creating
    the run."

    Design: Corner/validations/test_scheduling_with_every_gate_satisfied_succeeds
    """
    ctx = setup_lot_at_stage("PLATED", lot_overrides={"specimen_pool_total": 20})
    chamber = create_chamber(coupon_capacity=24)

    run = validate_success(
        api_client.create_test_run(
            make_test_run_payload(
                ctx["lot"]["id"],
                test_type="SALT_SPRAY",
                specimen_count=4,
                window_start=CORROSION_SLOT[0],
                window_end=CORROSION_SLOT[1],
                chamber_id=chamber["id"],
            ),
            QE,
        ),
        201,
    )

    assert run["status"] == "SCHEDULED"
    assert run["mandatory"] is True
    assert run["requirement_value"] == pytest.approx(96, abs=0.01)

    lot = read_lot(ctx["lot"]["id"])
    assert lot["specimens_committed"] == 4
    assert lot["specimens_consumed"] == 0
    assert lot["specimens_available"] == 16
    assert lot["cert_status"] == "IN_TEST"
    assert_specimen_ledger(lot)

    cabinet = validate_success(api_client.get_salt_spray_chamber(chamber["id"], QE))
    assert cabinet["coupon_capacity"] == 24
    assert cabinet["version"] == 1
