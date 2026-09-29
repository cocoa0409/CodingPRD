"""Comfort complaints: signed deviations, the per-room roll-up and the balancing cycle."""

from test_helpers import (
    ADMIN_HEADERS,
    COMPLAINT_BALANCING,
    COMPLAINT_DIAGNOSED,
    COMPLAINT_NOISE,
    COMPLAINT_OPEN,
    COMPLAINT_RESOLVED,
    DIAG_DAMPER_MISADJUSTED,
    DIAG_UNDERSIZED_BRANCH,
    ERR_COMPLAINT_INVALID_STATE,
    ERR_DUPLICATE_READING_SEQ,
    ERR_NO_AIRFLOW_READINGS,
    INSPECTOR_HEADERS,
    QA_HEADERS,
    assert_append_only_fields,
    deviation_pct,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_deviation_keeps_its_sign_while_tolerance_reads_the_magnitude(api):
    """A starved room is negative; tolerance compares the absolute value inclusively.

    PRD 3.9: "`deviation_pct` is computed by subtracting `design_cfm` from
    `measured_cfm`, dividing by `design_cfm`, multiplying by 100 and rounding half-up to
    two decimals — so a room delivering less than its design flow carries a negative
    deviation. `within_tolerance` is true exactly when the absolute value of
    `deviation_pct` is less than or equal to the complaint's `tolerance_pct`; the
    comparison is inclusive".

    Design: Corner/calculations/airflow_deviation_signs_and_zero_case_round_to_two_decimals
    """
    sc = fx.scenario_base(api)
    fx.add_complaint(sc)
    fx.diagnose_complaint(sc, tolerance_pct=10.00)

    minus_ten = fx.add_airflow_reading(sc, "Den", 1, 108.0, 120.0, damper_position_pct=40.0)
    assert minus_ten["deviation_pct"] == deviation_pct(108.0, 120.0)
    assert minus_ten["deviation_pct"] == -10.00
    assert minus_ten["within_tolerance"] is True
    assert_append_only_fields(minus_ten)

    exact = fx.add_airflow_reading(sc, "Hall", 2, 120.0, 120.0, damper_position_pct=50.0)
    assert exact["deviation_pct"] == 0.00
    assert exact["within_tolerance"] is True

    outside = fx.add_airflow_reading(sc, "Study", 3, 105.0, 120.0, damper_position_pct=35.0)
    assert outside["deviation_pct"] == deviation_pct(105.0, 120.0)
    assert outside["deviation_pct"] == -12.50
    assert outside["within_tolerance"] is False

    complaint = sc.read_complaint()
    assert complaint["balanced_room_count"] == 2
    assert complaint["status"] == COMPLAINT_DIAGNOSED


def test_a_complaint_resolves_only_once_every_distinct_room_governs_within_tolerance(api):
    """The roll-up reads the greatest `reading_seq` per room, and 2 of 2 resolves it.

    PRD 3.9: "For every distinct `room_label` under the complaint, the **governing**
    reading is the one with the greatest `reading_seq` for that room ... If instead
    every distinct room under the complaint now has a governing reading within
    tolerance, and at least one room exists, the complaint auto-resolves from
    `BALANCING` to the terminal `RESOLVED` status: `balanced_room_count` is set to the
    number of distinct rooms and `resolved_at` is stamped with the logical clock."

    Design: Corner/calculations/complaint_resolves_only_when_every_distinct_room_is_within_tolerance
    """
    sc = fx.scenario_base(api)
    fx.add_complaint(sc)
    fx.diagnose_complaint(sc, tolerance_pct=10.00)
    bedroom = fx.add_airflow_reading(sc, "Bedroom", 1, 126.0, 120.0)
    assert bedroom["deviation_pct"] == 5.00
    assert bedroom["within_tolerance"] is True
    living = fx.add_airflow_reading(sc, "Living Room", 2, 105.0, 120.0)
    assert living["deviation_pct"] == -12.50
    assert living["within_tolerance"] is False

    balancing = fx.enter_balancing(sc)
    assert balancing["status"] == COMPLAINT_BALANCING
    assert balancing["balanced_room_count"] == 1

    fixed = fx.add_airflow_reading(
        sc, "Living Room", 3, 120.0, 120.0, damper_position_pct=70.0
    )
    assert fixed["deviation_pct"] == 0.00
    assert fixed["within_tolerance"] is True

    complaint = sc.read_complaint()
    assert complaint["status"] == COMPLAINT_RESOLVED
    assert complaint["balanced_room_count"] == 2
    assert complaint["rebalance_count"] == 0
    assert complaint["resolved_at"] == f.stamp(2026, 8, 1)

    rows, meta = validate_paginated(
        api.list_airflow_readings(sc.complaint_id, ADMIN_HEADERS)
    )
    assert meta["total_count"] == 3
    assert len(rows) == 3


def test_an_out_of_tolerance_reading_throws_the_complaint_back_to_diagnosed(api):
    """The `DIAGNOSED`/`BALANCING` pair is a cycle a stubborn room can drive.

    PRD 3.9: "If the reading just stored has `within_tolerance` false, the complaint is
    thrown back from `BALANCING` to `DIAGNOSED` and `rebalance_count` rises by 1, so the
    technician must re-diagnose and re-enter balancing; this is why the `DIAGNOSED` and
    `BALANCING` pair forms a cycle a stubborn room can drive several times."

    Design: Corner/state_machines/complaint_reverts_from_balancing_to_diagnosed_on_out_of_tolerance_reading
    """
    sc = fx.scenario_base(api)
    fx.add_complaint(sc)
    fx.diagnose_complaint(sc, tolerance_pct=10.00)
    first = fx.add_airflow_reading(sc, "Living Room", 1, 132.0, 120.0)
    assert first["deviation_pct"] == 10.00
    assert first["within_tolerance"] is True
    assert fx.enter_balancing(sc)["status"] == COMPLAINT_BALANCING

    second = validate_success(
        api.create_airflow_reading(
            sc.complaint_id,
            f.airflow_reading_payload(
                "Living Room", 2, 138.0, 120.0, damper_position_pct=75.0
            ),
            sc.tech_headers,
        ),
        201,
    )
    assert second["deviation_pct"] == 15.00
    assert second["within_tolerance"] is False

    complaint = sc.read_complaint()
    assert complaint["status"] == COMPLAINT_DIAGNOSED
    assert complaint["rebalance_count"] == 1
    assert complaint["balanced_room_count"] == 0
    assert complaint["resolved_at"] is None

    _rows, meta = validate_paginated(
        api.list_airflow_readings(sc.complaint_id, ADMIN_HEADERS)
    )
    assert meta["total_count"] == 2


def test_the_reading_sequence_is_unique_per_room_not_per_complaint(api):
    """The same sequence number is free again under a different room label.

    PRD 3.9: "`reading_seq` must be unique for a given combination of
    `comfort_complaint_id` and `room_label`; a repeat is rejected with
    `ERR_DUPLICATE_READING_SEQ`." And: "`balanced_room_count` is recomputed after every
    reading as the number of distinct rooms whose governing reading has
    `within_tolerance` true."

    Design: Corner/validations/reading_seq_is_unique_per_room_not_per_complaint
    """
    sc = fx.scenario_base(api)
    fx.add_complaint(sc)
    fx.diagnose_complaint(sc, tolerance_pct=10.00)

    living_one = fx.add_airflow_reading(
        sc, "Living Room", 1, 110.0, 100.0, damper_position_pct=60.0
    )
    assert living_one["deviation_pct"] == 10.00
    assert living_one["within_tolerance"] is True

    validate_error(
        api.create_airflow_reading(
            sc.complaint_id,
            f.airflow_reading_payload(
                "Living Room", 1, 105.0, 100.0, damper_position_pct=55.0
            ),
            sc.tech_headers,
        ),
        ERR_DUPLICATE_READING_SEQ,
        422,
    )

    den = fx.add_airflow_reading(sc, "Den", 1, 95.0, 100.0, damper_position_pct=80.0)
    assert den["deviation_pct"] == -5.00

    living_two = fx.add_airflow_reading(
        sc, "Living Room", 2, 92.0, 100.0, damper_position_pct=45.0
    )
    assert living_two["deviation_pct"] == -8.00

    complaint = sc.read_complaint()
    assert complaint["balanced_room_count"] == 2
    assert complaint["status"] == COMPLAINT_DIAGNOSED
    assert complaint["rebalance_count"] == 0

    rows, meta = validate_paginated(
        api.list_airflow_readings(sc.complaint_id, ADMIN_HEADERS)
    )
    assert meta["total_count"] == 3
    assert len(rows) == 3


def test_balancing_needs_one_reading_and_then_does_not_resolve_by_itself(api):
    """Both legs of the evidence rule, and the auto-resolve belongs to the reading.

    PRD 3.9: "the transition from `DIAGNOSED` to `BALANCING` is refused with
    `ERR_NO_AIRFLOW_READINGS` unless at least one airflow reading already exists under
    the complaint. It carries a `damper_adjustment_note` describing what was adjusted,
    which is null before that point". PRD 3.9 places the resolution on the reading:
    "While a complaint is `BALANCING`, each new reading can move the complaint by
    itself."

    Design: Corner/validations/balance_requires_at_least_one_reading_and_then_does_not_auto_resolve
    """
    sc = fx.scenario_base(api)
    fx.add_complaint(sc)
    diagnosed = fx.diagnose_complaint(sc, tolerance_pct=10.00)
    assert diagnosed["status"] == COMPLAINT_DIAGNOSED
    assert diagnosed["tolerance_pct"] == 10.00
    assert diagnosed["balanced_room_count"] == 0
    assert diagnosed["damper_adjustment_note"] is None

    validate_error(
        api.balance_comfort_complaint(
            sc.complaint_id,
            f.balance_payload(damper_adjustment_note="premature balance attempt"),
            sc.tech_headers,
        ),
        ERR_NO_AIRFLOW_READINGS,
        422,
    )
    still_diagnosed = sc.read_complaint()
    assert still_diagnosed["status"] == COMPLAINT_DIAGNOSED
    assert still_diagnosed["damper_adjustment_note"] is None

    reading = fx.add_airflow_reading(
        sc, "Nursery", 1, 105.0, 100.0, damper_position_pct=70.0
    )
    assert reading["deviation_pct"] == 5.00
    assert reading["within_tolerance"] is True
    assert sc.read_complaint()["balanced_room_count"] == 1
    assert sc.read_complaint()["status"] == COMPLAINT_DIAGNOSED

    balanced = fx.enter_balancing(
        sc, damper_adjustment_note="nursery branch damper opened to 70%"
    )
    assert balanced["status"] == COMPLAINT_BALANCING
    assert balanced["status"] != COMPLAINT_RESOLVED
    assert balanced["damper_adjustment_note"] == "nursery branch damper opened to 70%"
    assert balanced["resolved_at"] is None
    assert balanced["rebalance_count"] == 0


def test_complaint_actions_fired_from_the_wrong_phase_report_the_state_error(api):
    """The state rung answers first, and the rejected action overwrites nothing.

    PRD 3.9: "Attempting it from any status other than `DIAGNOSED` is
    `ERR_COMPLAINT_INVALID_STATE`" and "Diagnosing a complaint that is not `OPEN` is
    `ERR_COMPLAINT_INVALID_STATE`". PRD 2.8 orders the rungs: state conflicts (6) are
    evaluated before structural and completeness rules (10).

    Design: Corner/errors/complaint_actions_fired_from_the_wrong_phase_report_the_complaint_state_error
    """
    sc = fx.scenario_base(api)
    complaint = fx.add_complaint(sc, room_label="Den")
    assert complaint["status"] == COMPLAINT_OPEN
    assert complaint["diagnosis_code"] is None
    assert complaint["tolerance_pct"] is None
    assert complaint["rebalance_count"] == 0
    assert complaint["version"] == 1

    # Balancing from OPEN violates the state rule and the evidence rule at once.
    validate_error(
        api.balance_comfort_complaint(
            sc.complaint_id,
            f.balance_payload(
                damper_adjustment_note="balancing before diagnosis and before any reading"
            ),
            sc.tech_headers,
        ),
        ERR_COMPLAINT_INVALID_STATE,
        409,
    )

    diagnosed = fx.diagnose_complaint(
        sc, diagnosis_code=DIAG_DAMPER_MISADJUSTED, tolerance_pct=10.00
    )
    assert diagnosed["status"] == COMPLAINT_DIAGNOSED

    validate_error(
        api.diagnose_comfort_complaint(
            sc.complaint_id,
            f.diagnose_payload(
                diagnosis_code=DIAG_UNDERSIZED_BRANCH, tolerance_pct=25.00
            ),
            sc.tech_headers,
        ),
        ERR_COMPLAINT_INVALID_STATE,
        409,
    )

    final = sc.read_complaint()
    assert final["status"] == COMPLAINT_DIAGNOSED
    assert final["diagnosis_code"] == DIAG_DAMPER_MISADJUSTED
    assert final["tolerance_pct"] == 10.00
    assert final["version"] == 2

    # With the state rule satisfied the same missing readings answer differently.
    validate_error(
        api.balance_comfort_complaint(
            sc.complaint_id,
            f.balance_payload(
                damper_adjustment_note="now diagnosed, but still no readings"
            ),
            sc.tech_headers,
        ),
        ERR_NO_AIRFLOW_READINGS,
        422,
    )


def test_complaint_and_reading_collections_filter_by_status_and_room(api):
    """Two complaints on one project cut independently, and an empty page is a 200.

    PRD 4 declares `GET /duct-sealing/projects/{id}/comfort-complaints` with a `status`
    filter and `GET /duct-sealing/comfort-complaints/{id}/airflow-readings` with a
    `room_label` filter. PRD 2.3: "`total_count` is the size of the filtered
    population, not the size of the returned page, so applying a filter shrinks
    `total_count`", and "the airflow readings of a comfort complaint are returned in
    ascending `reading_seq` order".

    Design: Corner/endpoints/complaint_and_reading_collections_filter_by_status_and_room
    """
    sc = fx.scenario_base(api)
    first = fx.add_complaint(sc, room_label="Den")
    second = fx.add_complaint(
        sc, room_label="Attic", complaint_type=COMPLAINT_NOISE, reported_by="Sam Kerr"
    )
    assert second["status"] == COMPLAINT_OPEN

    fx.diagnose_complaint(sc, complaint=first, tolerance_pct=10.00)
    fx.add_airflow_reading(sc, "Den", 1, 110.0, 100.0, complaint=first)
    fx.add_airflow_reading(sc, "Den", 2, 105.0, 100.0, complaint=first)
    attic = fx.add_airflow_reading(sc, "Attic", 1, 80.0, 100.0, complaint=first)
    assert attic["deviation_pct"] == -20.00
    assert attic["within_tolerance"] is False

    _all_rows, all_meta = validate_paginated(
        api.list_comfort_complaints(sc.project_id, ADMIN_HEADERS)
    )
    assert all_meta["total_count"] == 2

    open_rows, open_meta = validate_paginated(
        api.list_comfort_complaints(sc.project_id, ADMIN_HEADERS, status=COMPLAINT_OPEN)
    )
    assert open_meta["total_count"] == 1
    assert open_rows[0]["id"] == second["id"]

    diagnosed_rows, diagnosed_meta = validate_paginated(
        api.list_comfort_complaints(
            sc.project_id, QA_HEADERS, status=COMPLAINT_DIAGNOSED
        )
    )
    assert diagnosed_meta["total_count"] == 1
    assert diagnosed_rows[0]["id"] == first["id"]
    assert diagnosed_rows[0]["balanced_room_count"] == 1

    resolved_rows, resolved_meta = validate_paginated(
        api.list_comfort_complaints(
            sc.project_id, ADMIN_HEADERS, status=COMPLAINT_RESOLVED
        )
    )
    assert resolved_rows == []
    assert resolved_meta["total_count"] == 0

    first_rows, first_meta = validate_paginated(
        api.list_airflow_readings(first["id"], INSPECTOR_HEADERS)
    )
    assert first_meta["total_count"] == 3

    den_rows, den_meta = validate_paginated(
        api.list_airflow_readings(first["id"], INSPECTOR_HEADERS, room_label="Den")
    )
    assert den_meta["total_count"] == 2
    assert [row["room_label"] for row in den_rows] == ["Den", "Den"]
    assert [row["reading_seq"] for row in den_rows] == [1, 2]

    sibling_rows, sibling_meta = validate_paginated(
        api.list_airflow_readings(second["id"], INSPECTOR_HEADERS)
    )
    assert sibling_rows == []
    assert sibling_meta["total_count"] == 0
