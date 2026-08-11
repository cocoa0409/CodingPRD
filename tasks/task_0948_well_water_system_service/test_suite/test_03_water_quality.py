"""Water quality: panels, hold times, confirmation and the potability cycle."""

from test_helpers import (
    ApiErrorId,
    OFFICER_ALPHA,
    OFFICER_BETA,
    OFFICER_BRAVO,
    TEST_USERS,
    fixtures,
    make_compliance_officer_headers,
    validate_error,
    validate_paginated,
    validate_success,
    assert_instant_equals,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
OFFICER_B = TEST_USERS["compliance_officer_beta_headers"]


def _presumptive_world(
    account_name, email, address, jurisdiction="JUR_BRAVO", sample="2026-06-01T08:00:00Z",
    analyzed="2026-06-02T08:00:00Z", depth=175.0
):
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name=account_name,
        email=email,
        account_jurisdiction=jurisdiction,
        property_jurisdiction=jurisdiction,
        well_jurisdiction=jurisdiction,
        address_line=address,
        distance_miles=9.0,
        household_size=3,
        depth_feet=depth,
        drawdown=8.0,
        technician_name="Sampler",
    )
    test = fixtures.presumptive_positive_panel(
        world["well_id"], world["technician_id"], sample, analyzed, OFFICER_ALPHA
    )
    world["test_id"] = test["id"]
    return world


def test_confirmatory_regulatory_gate_beats_a_malformed_payload(api):
    """PRD 2.6: "A request that violates several gates is answered with the error of the
    lowest-numbered gate it violates, and no later gate is evaluated."
    PRD 3.3: "Three regulatory checks run before anything is written: the confirming
    sample must have been drawn within `RETEST_WINDOW_DAYS` (21 days) of the parent's
    `sample_datetime`, right-closed, or the call is refused with
    `ERR_RETEST_WINDOW_EXPIRED`; the confirming sample's own analysis must fall within
    the bacteriological hold time of 30 hours from `confirm_sample_datetime` to
    `confirm_analyzed_at`, right-closed, or the call is refused with
    `ERR_WATER_TEST_HOLD_TIME_EXCEEDED`; and the acting `X-User-ID` must differ from the
    parent's stored `recorded_by_user_id`, or the call is refused with
    `ERR_CONFIRMATORY_SAME_OFFICER`."

    Design: Difficulty/priority_pair_validation_conflict/retest_window_regulatory_gate_beats_malformed_payload_rejected
    """
    world = _presumptive_world("Ashgrove Farm", "ap@ashgrove.example", "7 Ashgrove", depth=170.0)
    fixtures.set_clock("2026-06-26T09:00:00Z")

    validate_error(
        api.record_confirmatory_result(
            world["test_id"],
            {
                "confirm_sample_datetime": "2026-06-26T08:00:00Z",
                "confirm_analyzed_at": "2026-06-26T09:00:00Z",
                "confirm_coliform_present": "MAYBE",
                "collected_by_technician_id": world["technician_id"],
            },
            OFFICER_B,
        ),
        ApiErrorId.ERR_RETEST_WINDOW_EXPIRED.value,
        422,
    )


def test_a_refused_confirmatory_result_writes_nothing(api):
    """PRD 3.3: "Three regulatory checks run before anything is written: the confirming
    sample must have been drawn within `RETEST_WINDOW_DAYS` (21 days) of the parent's
    `sample_datetime`, right-closed, or the call is refused with
    `ERR_RETEST_WINDOW_EXPIRED`; the confirming sample's own analysis must fall within
    the bacteriological hold time of 30 hours from `confirm_sample_datetime` to
    `confirm_analyzed_at`, right-closed, or the call is refused with
    `ERR_WATER_TEST_HOLD_TIME_EXCEEDED`; and the acting `X-User-ID` must differ from the
    parent's stored `recorded_by_user_id`, or the call is refused with
    `ERR_CONFIRMATORY_SAME_OFFICER`."
    PRD 3.3: "A bacteriological panel reporting `coliform_present` true lands in
    `ANALYZED_PRESUMPTIVE_POSITIVE`, sets the well to `ADVISORY` and latches
    `advisory_reason` to `PRESUMPTIVE_COLIFORM`."

    Design: Difficulty/priority_pair_validation_conflict/retest_window_regulatory_gate_beats_malformed_payload_rejected
    """
    world = _presumptive_world("Ashgrove Farm", "ap@ashgrove.example", "7 Ashgrove", depth=170.0)
    fixtures.set_clock("2026-06-26T09:00:00Z")
    api.record_confirmatory_result(
        world["test_id"],
        {
            "confirm_sample_datetime": "2026-06-26T08:00:00Z",
            "confirm_analyzed_at": "2026-06-26T09:00:00Z",
            "confirm_coliform_present": "MAYBE",
            "collected_by_technician_id": world["technician_id"],
        },
        OFFICER_B,
    )
    parent = fixtures.get_water_test(world["test_id"])
    assert parent["result_status"] == "ANALYZED_PRESUMPTIVE_POSITIVE"
    assert fixtures.get_well(world["well_id"])["potability_status"] == "ADVISORY"
    assert fixtures.child_water_tests(world["test_id"]) == []


def test_confirmatory_sample_at_exactly_twenty_one_days_clears_the_advisory(api):
    """PRD 2.10: "**The bacteriological retest window is closed on the right.** A
    confirmatory sample drawn exactly `RETEST_WINDOW_DAYS` (21 days, that is 1,814,400
    seconds) after the original sample is *in* window; one second later is out."
    PRD 3.3: "When the confirming sample reports coliform **absent**, the parent moves
    `ANALYZED_PRESUMPTIVE_POSITIVE → CLEARED_NEGATIVE`, a child `WaterTest` row is
    created with `parent_test_id` pointing at the parent, `panel_type`
    `BACTERIOLOGICAL` and `result_status` `CLEARED_NEGATIVE`, `confirmed_by_user_id` is
    stored on the parent, the well returns to `SAFE` and `advisory_reason` is cleared,
    and both `version` counters rise by 1."

    Design: Difficulty/boundary_precision_check/retest_window_exactly_twenty_one_days_is_inside_the_window
    """
    world = _presumptive_world("Twentyone Farm", "ap@twentyone.example", "21 Twentyone Rd")
    fixtures.set_clock("2026-06-22T09:00:00Z")

    updated = validate_success(
        api.record_confirmatory_result(
            world["test_id"],
            {
                "confirm_sample_datetime": "2026-06-22T08:00:00Z",
                "confirm_analyzed_at": "2026-06-22T09:00:00Z",
                "confirm_coliform_present": False,
                "collected_by_technician_id": world["technician_id"],
            },
            OFFICER_B,
        )
    )
    assert updated["result_status"] == "CLEARED_NEGATIVE"
    assert updated["confirmed_by_user_id"] == OFFICER_BETA


def test_a_clearing_retest_restores_the_well_and_materialises_the_child_row(api):
    """PRD 3.3: "When the confirming sample reports coliform **absent**, the parent moves
    `ANALYZED_PRESUMPTIVE_POSITIVE → CLEARED_NEGATIVE`, a child `WaterTest` row is
    created with `parent_test_id` pointing at the parent, `panel_type`
    `BACTERIOLOGICAL` and `result_status` `CLEARED_NEGATIVE`, `confirmed_by_user_id` is
    stored on the parent, the well returns to `SAFE` and `advisory_reason` is cleared,
    and both `version` counters rise by 1."

    Design: Difficulty/boundary_precision_check/retest_window_exactly_twenty_one_days_is_inside_the_window
    """
    world = _presumptive_world("Twentyone Farm", "ap@twentyone.example", "21 Twentyone Rd")
    fixtures.set_clock("2026-06-22T09:00:00Z")
    validate_success(
        api.record_confirmatory_result(
            world["test_id"],
            {
                "confirm_sample_datetime": "2026-06-22T08:00:00Z",
                "confirm_analyzed_at": "2026-06-22T09:00:00Z",
                "confirm_coliform_present": False,
                "collected_by_technician_id": world["technician_id"],
            },
            OFFICER_B,
        )
    )
    well = fixtures.get_well(world["well_id"])
    assert well["potability_status"] == "SAFE"
    assert well["advisory_reason"] is None

    children = fixtures.child_water_tests(world["test_id"])
    assert len(children) == 1
    assert children[0]["result_status"] == "CLEARED_NEGATIVE"


def test_a_confirming_retest_persists_every_write_and_then_errors(api):
    """PRD 2.11: "**A confirmatory retest that confirms coliform.** The child test row is
    created, the parent test latches to `CONFIRMED_POSITIVE`, `confirmed_by_user_id` is
    stored, the well moves to `UNSAFE` with an advisory reason of `CONFIRMED_COLIFORM`,
    and both `version` counters rise — and only then does the call return
    `ERR_RETEST_CONFIRMED_POSITIVE` (HTTP 422)."

    Design: Corner/state_machines/corner_mutate_then_reject_confirmatory_positive_writes_persist
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Confirm Co",
        email="cf@corner.example",
        address_line="7 Confirm",
        household_size=2,
        technician_name="Confirm Tech",
    )
    test = fixtures.presumptive_positive_panel(
        world["well_id"],
        world["technician_id"],
        "2026-06-01T08:00:00Z",
        "2026-06-02T08:00:00Z",
        OFFICER_ALPHA,
    )
    fixtures.set_clock("2026-06-10T09:00:00Z")

    validate_error(
        api.record_confirmatory_result(
            test["id"],
            {
                "confirm_sample_datetime": "2026-06-10T08:00:00Z",
                "confirm_analyzed_at": "2026-06-10T20:00:00Z",
                "confirm_coliform_present": True,
                "collected_by_technician_id": world["technician_id"],
            },
            OFFICER_B,
        ),
        ApiErrorId.ERR_RETEST_CONFIRMED_POSITIVE.value,
        422,
    )
    parent = fixtures.get_water_test(test["id"])
    assert parent["result_status"] == "CONFIRMED_POSITIVE"
    assert parent["confirmed_by_user_id"] == OFFICER_BETA

    well = fixtures.get_well(world["well_id"])
    assert well["potability_status"] == "UNSAFE"
    assert well["advisory_reason"] == "CONFIRMED_COLIFORM"
    assert len(fixtures.child_water_tests(test["id"])) == 1


def test_lapse_sweep_is_refused_while_the_window_is_still_open(api):
    """PRD 3.3: "The sweep requires that the elapsed time from the test's
    `sample_datetime` to the logical clock be **strictly greater** than 21 days; called
    while the window is still open it fails at the business gate with
    `ERR_RETEST_WINDOW_STILL_OPEN` and writes nothing. When the window has genuinely
    closed, the test latches to `CONFIRMED_POSITIVE` and the well moves to `UNSAFE` with
    `advisory_reason` `RETEST_WINDOW_LAPSED`; both `version` counters rise by 1."

    Design: Corner/state_machines/corner_lapse_retest_window_still_open_is_rejected_then_latches_after_the_window
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Lapse Co",
        email="lp@corner.example",
        address_line="8 Lapse",
        household_size=2,
        technician_name="Lapse Tech",
    )
    test = fixtures.presumptive_positive_panel(
        world["well_id"],
        world["technician_id"],
        "2026-06-01T08:00:00Z",
        "2026-06-02T08:00:00Z",
        OFFICER_ALPHA,
    )
    fixtures.set_clock("2026-06-22T08:00:00Z")
    validate_error(
        api.lapse_retest_window(test["id"], OFFICER),
        ApiErrorId.ERR_RETEST_WINDOW_STILL_OPEN.value,
        409,
    )

    fixtures.set_clock("2026-06-23T08:00:00Z")
    latched = validate_success(api.lapse_retest_window(test["id"], OFFICER))
    assert latched["result_status"] == "CONFIRMED_POSITIVE"

    well = fixtures.get_well(world["well_id"])
    assert well["potability_status"] == "UNSAFE"
    assert well["advisory_reason"] == "RETEST_WINDOW_LAPSED"


def test_a_sample_analysed_past_its_hold_time_moves_nothing(api):
    """PRD 3.3: "When the hold time is exceeded, the test lands in `INVALID_HOLD_TIME`
    with `hold_time_valid` false, `analyzed_at` and `recorded_by_user_id` stored, and —
    critically — **the well's `potability_status` does not move at all**. The result is
    discarded as evidence."
    PRD 3.3: "The limit is `HOLD_TIME_HOURS_BACTERIOLOGICAL`, 30 hours, for a
    bacteriological panel and `HOLD_TIME_HOURS_CHEMICAL`, 336 hours, for a chemical one,
    and the test is **right-closed**: exactly 30.0 hours on a bacteriological sample is
    valid, 30 hours and one second is not."

    Design: Corner/state_machines/corner_water_test_hold_time_exceeded_routes_to_invalid_and_moves_nothing
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Holdtime Co",
        email="ht@corner.example",
        address_line="9 Holdtime",
        household_size=2,
        technician_name="Hold Tech",
    )
    test = fixtures.collect_sample(
        world["well_id"],
        world["technician_id"],
        "BACTERIOLOGICAL",
        "2026-06-01T00:00:00Z",
    )
    updated = validate_success(
        api.record_lab_result(
            test["id"],
            {"analyzed_at": "2026-06-02T06:00:01Z", "coliform_present": True},
            OFFICER,
        )
    )
    assert updated["result_status"] == "INVALID_HOLD_TIME"
    assert updated["hold_time_valid"] is False
    assert updated["recorded_by_user_id"] == OFFICER_ALPHA

    well = fixtures.get_well(world["well_id"])
    assert well["potability_status"] == "UNKNOWN"
    assert well["advisory_reason"] is None


def test_lab_result_separates_a_malformed_instant_a_bad_range_and_the_exact_hold_time(api):
    """PRD 2.7: "`ERR_INVALID_TIMESTAMP` (HTTP 400) is raised when a datetime **body**
    field on a mutating endpoint does not parse as an ISO 8601 UTC instant."
    PRD 2.7: "`ERR_INVALID_DATE_RANGE` (HTTP 400) is raised on exactly two endpoints. On
    work-order scheduling it fires when `scheduled_end_at` is not strictly after
    `scheduled_start_at`. On a laboratory result it fires when `analyzed_at` precedes
    `sample_datetime`."
    PRD 3.3: "A bacteriological panel reporting `coliform_present` false lands in
    `ANALYZED_NEGATIVE`, sets the well's `potability_status` to `SAFE` and clears
    `advisory_reason`."

    Design: Corner/validations/corner_validation_lab_result_timestamp_range_and_exact_hold_time
    """
    fixtures.set_clock("2026-06-02T09:00:00Z")
    world = fixtures.base_world(
        account_name="Hold Time Co",
        email="ht@corner.example",
        address_line="30 Hold",
        technician_name="Hold Tech",
    )
    test = fixtures.collect_sample(
        world["well_id"],
        world["technician_id"],
        "BACTERIOLOGICAL",
        "2026-06-01T00:00:00Z",
        headers=OFFICER,
    )

    validate_error(
        api.record_lab_result(
            test["id"], {"analyzed_at": "2026-06-01 12:00", "coliform_present": False}, OFFICER
        ),
        ApiErrorId.ERR_INVALID_TIMESTAMP.value,
        400,
    )
    validate_error(
        api.record_lab_result(
            test["id"],
            {"analyzed_at": "2026-05-31T23:00:00Z", "coliform_present": False},
            OFFICER,
        ),
        ApiErrorId.ERR_INVALID_DATE_RANGE.value,
        400,
    )
    analysed = validate_success(
        api.record_lab_result(
            test["id"],
            {"analyzed_at": "2026-06-02T06:00:00Z", "coliform_present": False},
            OFFICER,
        )
    )
    assert analysed["result_status"] == "ANALYZED_NEGATIVE"
    assert analysed["hold_time_valid"] is True
    assert_instant_equals(
        analysed["analyzed_at"], "2026-06-02T06:00:00Z", "WaterTest.analyzed_at"
    )
    assert analysed["recorded_by_user_id"] == OFFICER_ALPHA

    well = fixtures.get_well(world["well_id"])
    assert well["potability_status"] == "SAFE"
    assert well["advisory_reason"] is None


def test_the_confirmatory_child_row_is_reachable_only_through_the_parent_filter(api):
    """PRD 3.3: "When the confirming sample reports coliform **absent**, the parent moves
    `ANALYZED_PRESUMPTIVE_POSITIVE → CLEARED_NEGATIVE`, a child `WaterTest` row is
    created with `parent_test_id` pointing at the parent, `panel_type`
    `BACTERIOLOGICAL` and `result_status` `CLEARED_NEGATIVE`, `confirmed_by_user_id` is
    stored on the parent, the well returns to `SAFE` and `advisory_reason` is cleared,
    and both `version` counters rise by 1."
    PRD 4.9: "Request: optional filters `well_profile_id`, `collected_by_technician_id`,
    `parent_test_id`, `panel_type`, `result_status`, plus `limit` and `offset`."

    Design: Corner/endpoints/corner_endpoint_water_tests_self_referential_parent_filter
    """
    fixtures.set_clock("2026-06-02T09:00:00Z")
    world = fixtures.base_world(
        account_name="Child Test Co",
        email="ct@corner.example",
        address_line="2 Retest",
        technician_name="Retest Tech",
    )
    parent = fixtures.collect_sample(
        world["well_id"],
        world["technician_id"],
        "BACTERIOLOGICAL",
        "2026-06-01T00:00:00Z",
        headers=OFFICER,
    )
    fixtures.record_lab_result(
        parent["id"], {"analyzed_at": "2026-06-02T00:00:00Z", "coliform_present": True}
    )
    fixtures.set_clock("2026-06-10T13:00:00Z")

    validate_success(
        api.record_confirmatory_result(
            parent["id"],
            {
                "confirm_sample_datetime": "2026-06-10T00:00:00Z",
                "confirm_analyzed_at": "2026-06-10T12:00:00Z",
                "confirm_coliform_present": False,
                "collected_by_technician_id": world["technician_id"],
            },
            make_compliance_officer_headers(OFFICER_BRAVO),
        )
    )

    children, _ = validate_paginated(
        api.list_water_tests(OFFICER, params={"parent_test_id": parent["id"]})
    )
    assert len(children) == 1
    child = children[0]
    assert child["parent_test_id"] == parent["id"]
    assert child["panel_type"] == "BACTERIOLOGICAL"
    assert child["result_status"] == "CLEARED_NEGATIVE"

    parent_row = fixtures.get_water_test(parent["id"])
    assert parent_row["result_status"] == "CLEARED_NEGATIVE"
    assert parent_row["recorded_by_user_id"] == OFFICER_ALPHA
    assert parent_row["confirmed_by_user_id"] == OFFICER_BRAVO

    cleared, _ = validate_paginated(
        api.list_water_tests(
            OFFICER,
            params={
                "well_profile_id": world["well_id"],
                "result_status": "CLEARED_NEGATIVE",
            },
        )
    )
    assert len(cleared) == 2

    well = fixtures.get_well(world["well_id"])
    assert well["potability_status"] == "SAFE"
    assert well["advisory_reason"] is None


def test_confirmatory_regulatory_checks_fire_in_their_declared_order(api):
    """PRD 3.3: "Three regulatory checks run before anything is written: the confirming
    sample must have been drawn within `RETEST_WINDOW_DAYS` (21 days) of the parent's
    `sample_datetime`, right-closed, or the call is refused with
    `ERR_RETEST_WINDOW_EXPIRED`; the confirming sample's own analysis must fall within
    the bacteriological hold time of 30 hours from `confirm_sample_datetime` to
    `confirm_analyzed_at`, right-closed, or the call is refused with
    `ERR_WATER_TEST_HOLD_TIME_EXCEEDED`; and the acting `X-User-ID` must differ from the
    parent's stored `recorded_by_user_id`, or the call is refused with
    `ERR_CONFIRMATORY_SAME_OFFICER`."
    PRD 2.13: "If the `X-User-ID` presenting a confirmatory result equals the test's
    stored `recorded_by_user_id`, the request is refused with
    `ERR_CONFIRMATORY_SAME_OFFICER` (HTTP 403), and nothing is written."

    Design: Corner/errors/corner_error_confirmatory_regulatory_ordering_window_officer_then_hold_time
    """
    fixtures.set_clock("2026-06-02T09:00:00Z")
    world = fixtures.base_world(
        account_name="Retest Order Co",
        email="ro@corner.example",
        address_line="21 Retest",
        technician_name="Retest Order Tech",
    )
    test = fixtures.collect_sample(
        world["well_id"],
        world["technician_id"],
        "BACTERIOLOGICAL",
        "2026-06-01T00:00:00Z",
        headers=OFFICER,
    )
    fixtures.record_lab_result(
        test["id"], {"analyzed_at": "2026-06-02T00:00:00Z", "coliform_present": True}
    )
    fixtures.set_clock("2026-06-24T00:00:00Z")

    validate_error(
        api.record_confirmatory_result(
            test["id"],
            {
                "confirm_sample_datetime": "2026-06-23T00:00:00Z",
                "confirm_analyzed_at": "2026-06-23T06:00:00Z",
                "confirm_coliform_present": False,
                "collected_by_technician_id": world["technician_id"],
            },
            OFFICER,
        ),
        ApiErrorId.ERR_RETEST_WINDOW_EXPIRED.value,
        422,
    )
    validate_error(
        api.record_confirmatory_result(
            test["id"],
            {
                "confirm_sample_datetime": "2026-06-22T00:00:00Z",
                "confirm_analyzed_at": "2026-06-22T06:00:00Z",
                "confirm_coliform_present": False,
                "collected_by_technician_id": world["technician_id"],
            },
            OFFICER,
        ),
        ApiErrorId.ERR_CONFIRMATORY_SAME_OFFICER.value,
        403,
    )
    validate_error(
        api.record_confirmatory_result(
            test["id"],
            {
                "confirm_sample_datetime": "2026-06-22T00:00:00Z",
                "confirm_analyzed_at": "2026-06-23T12:00:00Z",
                "confirm_coliform_present": False,
                "collected_by_technician_id": world["technician_id"],
            },
            make_compliance_officer_headers(OFFICER_BRAVO),
        ),
        ApiErrorId.ERR_WATER_TEST_HOLD_TIME_EXCEEDED.value,
        422,
    )

    parent = fixtures.get_water_test(test["id"])
    assert parent["result_status"] == "ANALYZED_PRESUMPTIVE_POSITIVE"
    assert parent["confirmed_by_user_id"] is None
    well = fixtures.get_well(world["well_id"])
    assert well["potability_status"] == "ADVISORY"
    assert well["advisory_reason"] == "PRESUMPTIVE_COLIFORM"
    assert fixtures.child_water_tests(test["id"]) == []
