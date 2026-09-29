"""Reserving, pressurizing, recording and reviewing a leakage measurement."""

from test_helpers import (
    ADMIN_HEADERS,
    DECISION_ACCEPT,
    DECISION_REJECT,
    ERR_LEAKAGE_TEST_INVALID_STATE,
    ERR_TEST_WINDOW_CONFLICT,
    GRADE_A,
    METHOD_PRESSURE_PAN,
    PHASE_PRE,
    QA_HEADERS,
    RING_3,
    TEST_ACCEPTED,
    TEST_DRAFT,
    TEST_PRESSURIZED,
    TEST_RECORDED,
    TEST_REJECTED,
    factories as f,
    fixtures as fx,
    leakage_per_100_sqft,
    normalize_to_cfm25,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_reservation_is_created_in_draft_with_every_measurement_null(api):
    """Booking a window records intent only; no measurement exists yet.

    PRD 3.3: "The reservation is created in status `DRAFT` with
    `test_pressure_pa`, `fan_ring_config`, `masked_register_count`,
    `measured_leakage_cfm`, `ambient_temp_f`, `normalized_leakage_cfm25` and
    `leakage_per_100_sqft` all null and `version` at 1."

    Design: Corner/state_machines/leakage_test_is_created_in_draft_with_null_measurements
    """
    sc = fx.scenario_eligible_system(api)
    test = validate_success(
        api.create_leakage_test(f.leakage_test_payload(sc.duct_system_id), sc.tech_headers),
        201,
    )

    assert test["status"] == TEST_DRAFT
    assert test["duct_system_id"] == sc.duct_system_id
    assert test["phase"] == PHASE_PRE
    for field in (
        "test_pressure_pa",
        "fan_ring_config",
        "masked_register_count",
        "measured_leakage_cfm",
        "ambient_temp_f",
        "normalized_leakage_cfm25",
        "leakage_per_100_sqft",
        "performed_by_user_id",
        "reviewed_by_user_id",
    ):
        assert test[field] is None, f"{field} must be null on a fresh reservation"
    assert test["version"] == 1


def test_pressurizing_a_recorded_measurement_reports_the_state_error(api):
    """Pressurization is legal from `DRAFT` alone and leaves the row untouched otherwise.

    PRD 3.3: "Attempting to pressurize from anything other than `DRAFT`, to record
    from anything other than `PRESSURIZED`, or to review from anything other than
    `RECORDED` is rejected with `ERR_LEAKAGE_TEST_INVALID_STATE`."

    Design: Corner/state_machines/pressurize_a_recorded_test_returns_leakage_test_invalid_state
    """
    sc = fx.scenario_eligible_system(api)
    test = validate_success(
        api.create_leakage_test(f.leakage_test_payload(sc.duct_system_id), sc.tech_headers),
        201,
    )
    pressurized = validate_success(
        api.pressurize_leakage_test(test["id"], f.pressurize_payload(), sc.tech_headers)
    )
    assert pressurized["status"] == TEST_PRESSURIZED
    recorded = validate_success(
        api.record_leakage_test(test["id"], f.record_payload(), sc.tech_headers)
    )
    assert recorded["status"] == TEST_RECORDED

    validate_error(
        api.pressurize_leakage_test(
            test["id"], f.pressurize_payload(test_pressure_pa=50.0), sc.tech_headers
        ),
        ERR_LEAKAGE_TEST_INVALID_STATE,
        409,
    )

    after = validate_success(api.get_leakage_test(test["id"], ADMIN_HEADERS))
    assert after["status"] == TEST_RECORDED
    assert after["test_pressure_pa"] == 25.0
    assert after["fan_ring_config"] == "RING_2"
    assert after["normalized_leakage_cfm25"] == 300.00
    assert after["version"] == recorded["version"]


def test_reviewing_an_already_accepted_measurement_a_second_time_is_refused(api):
    """`ACCEPTED` is terminal, so a second review cannot re-stamp the reviewer.

    PRD 3.3: "`ACCEPT` moves the measurement from `RECORDED` to `ACCEPTED`;
    `REJECT` moves it from `RECORDED` to `REJECTED`. Both are terminal".

    Design: Corner/state_machines/reviewing_an_already_accepted_test_a_second_time_is_rejected
    """
    sc = fx.scenario_with_baseline(api)
    accepted = sc.pre_test
    assert accepted["status"] == TEST_ACCEPTED

    validate_error(
        api.review_leakage_test(
            accepted["id"], f.review_payload(decision=DECISION_REJECT), QA_HEADERS
        ),
        ERR_LEAKAGE_TEST_INVALID_STATE,
        409,
    )

    after = validate_success(api.get_leakage_test(accepted["id"], ADMIN_HEADERS))
    assert after["status"] == TEST_ACCEPTED
    assert after["version"] == accepted["version"], "a rejected review must not bump version"


def test_an_accepted_measurement_refuses_every_further_action(api):
    """All three transitions report the same state error once the row is terminal.

    PRD 3.3: "Attempting to pressurize from anything other than `DRAFT`, to record
    from anything other than `PRESSURIZED`, or to review from anything other than
    `RECORDED` is rejected with `ERR_LEAKAGE_TEST_INVALID_STATE`."

    Design: Corner/state_machines/accepted_leakage_test_is_terminal_for_every_action
    """
    sc = fx.scenario_with_baseline(api)
    test_id = sc.pre_test["id"]

    validate_error(
        api.pressurize_leakage_test(test_id, f.pressurize_payload(), sc.tech_headers),
        ERR_LEAKAGE_TEST_INVALID_STATE,
        409,
    )
    validate_error(
        api.record_leakage_test(test_id, f.record_payload(), sc.tech_headers),
        ERR_LEAKAGE_TEST_INVALID_STATE,
        409,
    )
    validate_error(
        api.review_leakage_test(
            test_id, f.review_payload(decision=DECISION_ACCEPT), QA_HEADERS
        ),
        ERR_LEAKAGE_TEST_INVALID_STATE,
        409,
    )

    after = validate_success(api.get_leakage_test(test_id, ADMIN_HEADERS))
    assert after["status"] == TEST_ACCEPTED
    assert after["leakage_per_100_sqft"] == 15.00


def test_per_area_leakage_is_derived_from_the_already_rounded_normalized_value(api):
    """Round, then divide, then round again — the pinned order changes the answer.

    A raw 130.0 CFM held at 50 pascals normalizes to 85.77 CFM25, and 85.77
    divided by eighteen hundreds of square feet is 4.765, which rounds half-up to
    4.77. Dividing the unrounded intermediate instead yields 4.7649, which rounds
    to 4.76.

    PRD 2.6: "The per-area leakage figure is computed **from the already-rounded**
    normalized leakage value, not from the unrounded intermediate — round, then
    divide, then round again."

    Design: Difficulty/combinatorial_formula/normalized_leakage_rounding_order_pinned
    """
    sc = fx.scenario_eligible_system(
        api,
        with_program=False,
        project={"conditioned_floor_area_sqft": 1800},
        duct_system={
            "total_register_count": 7,
            "design_cfm": 900.0,
            "condition_grade": GRADE_A,
        },
    )
    test = validate_success(
        api.create_leakage_test(
            f.leakage_test_payload(sc.duct_system_id, method=METHOD_PRESSURE_PAN),
            sc.tech_headers,
        ),
        201,
    )
    validate_success(
        api.pressurize_leakage_test(
            test["id"],
            f.pressurize_payload(
                test_pressure_pa=50.0, fan_ring_config=RING_3, masked_register_count=7
            ),
            sc.tech_headers,
        )
    )
    recorded = validate_success(
        api.record_leakage_test(
            test["id"],
            f.record_payload(measured_leakage_cfm=130.0, ambient_temp_f=81.0),
            sc.tech_headers,
        )
    )

    assert recorded["normalized_leakage_cfm25"] == normalize_to_cfm25(130.0, 50.0) == 85.77
    assert recorded["leakage_per_100_sqft"] == leakage_per_100_sqft(85.77, 1800) == 4.77
    assert recorded["leakage_per_100_sqft"] != 4.76, (
        "4.76 is what dividing the unrounded intermediate produces"
    )
    assert recorded["status"] == TEST_RECORDED
    assert recorded["performed_by_user_id"] == sc.technician_id


def test_the_pinned_rounding_order_still_binds_at_the_top_of_the_pressure_range(api):
    """A second pinned pair: 87.06 over twelve hundreds of square feet is 7.26.

    A raw 200.0 CFM held at the top of the permitted range, 100 pascals,
    normalizes to 87.0550... which rounds to 87.06; 87.06 divided by twelve is
    7.255, which rounds half-up to 7.26. Dividing the unrounded 87.0550... by
    twelve gives 7.2545..., which would round to 7.25.

    PRD 3.3: "Computing step two from the unrounded step-one intermediate is
    wrong and differs from the pinned answer for readings sitting near a
    half-cent boundary."

    Design: Difficulty/combinatorial_formula/normalized_leakage_rounding_order_pinned
    """
    sc = fx.scenario_eligible_system(
        api,
        with_program=False,
        project={"conditioned_floor_area_sqft": 1200},
        duct_system={"total_register_count": 7, "design_cfm": 900.0},
    )
    test = validate_success(
        api.create_leakage_test(f.leakage_test_payload(sc.duct_system_id), sc.tech_headers),
        201,
    )
    validate_success(
        api.pressurize_leakage_test(
            test["id"],
            f.pressurize_payload(test_pressure_pa=100.0, masked_register_count=7),
            sc.tech_headers,
        )
    )
    recorded = validate_success(
        api.record_leakage_test(
            test["id"],
            f.record_payload(measured_leakage_cfm=200.0, ambient_temp_f=79.0),
            sc.tech_headers,
        )
    )

    assert recorded["normalized_leakage_cfm25"] == normalize_to_cfm25(200.0, 100.0) == 87.06
    assert recorded["leakage_per_100_sqft"] == leakage_per_100_sqft(87.06, 1200) == 7.26
    assert recorded["leakage_per_100_sqft"] != 7.25


def test_buffered_measurement_windows_conflict_when_they_merely_touch(api):
    """A half-hour buffer closed at both ends makes touching intervals conflict.

    A reservation running 13:00 to 15:00 projects the buffered interval 12:30 to
    15:30. A second reservation beginning at 16:00 projects 15:30 to 17:30, so the
    two share the 15:30 boundary instant and the second is refused; moving it one
    minute later clears the boundary and it is accepted.

    PRD 3.3: "Because the buffered interval is closed at both ends, two
    measurements whose buffered endpoints merely touch **do** conflict".

    Design: Difficulty/resource_temporal_overlap/leakage_test_window_buffered_closed_interval_conflict
    """
    sc = fx.scenario_eligible_system(api)
    first = validate_success(
        api.create_leakage_test(
            f.leakage_test_payload(
                sc.duct_system_id,
                window_start_at=f.utc(2026, 8, 1, 13, 0),
                window_end_at=f.utc(2026, 8, 1, 15, 0),
            ),
            sc.tech_headers,
        ),
        201,
    )

    validate_error(
        api.create_leakage_test(
            f.leakage_test_payload(
                sc.duct_system_id,
                window_start_at=f.utc(2026, 8, 1, 16, 0),
                window_end_at=f.utc(2026, 8, 1, 17, 0),
            ),
            sc.tech_headers,
        ),
        ERR_TEST_WINDOW_CONFLICT,
        409,
    )

    third = validate_success(
        api.create_leakage_test(
            f.leakage_test_payload(
                sc.duct_system_id,
                window_start_at=f.utc(2026, 8, 1, 16, 1),
                window_end_at=f.utc(2026, 8, 1, 17, 0),
            ),
            sc.tech_headers,
        ),
        201,
    )
    assert third["status"] == TEST_DRAFT

    rows, meta = validate_paginated(
        api.list_leakage_tests(sc.duct_system_id, ADMIN_HEADERS)
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [first["id"], third["id"]]
    assert sc.read_duct_system()["baseline_leakage_cfm25"] is None


def test_the_window_guard_ignores_rejected_measurements_and_sibling_systems(api):
    """The buffered-overlap check is scoped to non-rejected rows on the same system.

    PRD 3.3: "If that buffered interval intersects the buffered interval of any
    other non-`REJECTED` measurement on the same duct system, the reservation is
    rejected with `ERR_TEST_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/leakage_test_window_buffered_closed_interval_conflict
    """
    sc = fx.scenario_eligible_system(api)
    sibling = fx.add_duct_system(sc, system_label="AHU-2", lab_reference="LAB-1002")

    rejected = fx.add_accepted_leakage_test(sc, decision=DECISION_REJECT)
    assert rejected["status"] == TEST_REJECTED

    # The identical window is free again now that the earlier row is REJECTED.
    replacement = validate_success(
        api.create_leakage_test(f.leakage_test_payload(sc.duct_system_id), sc.tech_headers),
        201,
    )
    assert replacement["status"] == TEST_DRAFT

    # A conflict is scoped to one duct system, so the sibling may hold it too.
    on_sibling = validate_success(
        api.create_leakage_test(f.leakage_test_payload(sibling["id"]), sc.tech_headers),
        201,
    )
    assert on_sibling["duct_system_id"] == sibling["id"]

    # And the guard still bites for the replacement's own buffered interval.
    validate_error(
        api.create_leakage_test(
            f.leakage_test_payload(
                sc.duct_system_id,
                window_start_at=f.utc(2026, 8, 1, 15, 30),
                window_end_at=f.utc(2026, 8, 1, 16, 0),
            ),
            sc.tech_headers,
        ),
        ERR_TEST_WINDOW_CONFLICT,
        409,
    )
