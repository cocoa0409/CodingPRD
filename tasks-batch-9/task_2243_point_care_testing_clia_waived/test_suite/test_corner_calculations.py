"""Inclusive thresholds, input-set filtering, chronological weights and grace chains."""

from test_helpers import (
    ADMIN,
    COORDINATOR,
    SURVEYOR,
    add_finding,
    api_client,
    assert_append_only_record,
    assert_logical_instant,
    capture_result,
    create_device,
    create_site,
    create_storage_unit,
    issue_survey,
    make_operator_headers,
    open_survey,
    post_result,
    read_deficiency,
    read_device,
    read_inspection,
    read_operator,
    read_site,
    read_storage_unit,
    record_temperature_reading,
    retire_device,
    run_oversight,
    set_clock,
    setup_closed_finding,
    setup_competent_operator,
    setup_covered_site,
    setup_site_with_verified_lot,
    validate_paginated,
)

SEPTEMBER = "2026-09-01T08:00:00Z"
SEPTEMBER_STAMP = "2026-09-01T08:00:00.000Z"


def test_a_reading_on_either_storage_bound_is_in_range_and_one_tenth_past_is_not():
    """2.0 and 8.0 open nothing; 8.1 is the reading that opens the excursion.

    PRD 3.5: "The reading's `disposition` is `IN_RANGE` when `reading_c` is greater
    than or equal to the unit's `min_temp_c` and also less than or equal to its
    `max_temp_c` — both bounds inclusive, so a reading exactly on either bound is in
    range — and `OUT_OF_RANGE` otherwise." and "The unit's `last_reading_c` is the
    `reading_c` of the reading with the greatest `recorded_at`; where two readings
    share that instant, the later-created row wins."

    Design: Corner/calculations/temperature_reading_at_both_inclusive_bounds_stays_in_range
    """
    set_clock(SEPTEMBER)
    site = create_site(name="Central Lab POCT", department_code="DEPT-1800")
    unit = create_storage_unit(
        site["id"], name="Reagent Fridge 1", min_temp_c=2.0, max_temp_c=8.0
    )

    on_lower_bound = record_temperature_reading(
        unit["id"], 2.0, recorded_at="2026-09-01T08:00:00Z"
    )
    on_upper_bound = record_temperature_reading(
        unit["id"], 8.0, recorded_at="2026-09-01T09:00:00Z"
    )
    past_upper_bound = record_temperature_reading(
        unit["id"], 8.1, recorded_at="2026-09-01T10:00:00Z"
    )

    assert on_lower_bound["disposition"] == "IN_RANGE"
    assert on_lower_bound["triggered_excursion"] is False
    assert on_upper_bound["disposition"] == "IN_RANGE"
    assert on_upper_bound["triggered_excursion"] is False
    assert past_upper_bound["disposition"] == "OUT_OF_RANGE"
    assert past_upper_bound["triggered_excursion"] is True
    for reading in (on_lower_bound, on_upper_bound, past_upper_bound):
        assert_append_only_record(reading, "temperature_reading")
    read_back = read_storage_unit(unit["id"])
    assert read_back["excursion_state"] == "EXCURSION_OPEN"
    assert_logical_instant(read_back["excursion_opened_at"], SEPTEMBER_STAMP)
    assert read_back["last_reading_c"] == 8.1
    assert read_back["quarantined_lot_count"] == 0


def test_retiring_the_weak_instrument_lifts_the_site_index_to_a_perfect_score():
    """75.00 becomes 100.00 because the retired instrument leaves the input set.

    PRD 3.4: "The **site quality-control compliance index** aggregates the day-of-use
    figures over the site's non-retired instruments — those whose `status` is `ACTIVE`
    or `QC_LOCKED`; a `RETIRED` instrument is excluded entirely." and "**step one**,
    round each eligible instrument's `qc_compliance_rate_day_of_use` half up to a
    whole percent with no decimal places; **step two**, add those whole-percent
    values, divide by the number of eligible instruments, and round the quotient half
    up to 2 decimal places."

    Design: Corner/calculations/retired_device_excluded_from_site_qc_compliance_index
    """
    env = setup_site_with_verified_lot(
        clock="2026-08-01T08:00:00Z",
        certificate_overrides={"certificate_number": "45D2243020"},
        site_overrides={
            "name": "Diabetes Center POCT",
            "department_code": "DEPT-1900",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={"full_name": "Mira Vance", "hire_date": "2026-01-05"},
        device_overrides={"serial_number": "SN-GL-1902"},
        lot_overrides={"lot_number": "LOT-A1", "expiration_date": "2027-01-31"},
    )
    idle_device = create_device(env["site"]["id"], serial_number="SN-GL-1901")
    first = capture_result(env, patient_mrn="MRN-8001", measured_value=96.0)
    set_clock("2026-08-02T08:00:00Z")
    second = capture_result(env, patient_mrn="MRN-8002", measured_value=104.0)
    operator_headers = make_operator_headers(env["operator"]["id"])
    post_result(first["id"], operator_headers)
    post_result(second["id"], operator_headers)

    used = read_device(env["device"]["id"], COORDINATOR)
    assert used["use_day_count"] == 2
    assert used["qc_compliance_rate_day_of_use"] == 50.00
    assert read_device(idle_device["id"], COORDINATOR)[
        "qc_compliance_rate_day_of_use"
    ] == 100.00
    before = read_site(env["site"]["id"], COORDINATOR)
    assert before["site_qc_compliance_index"] == 75.00
    assert before["inspection_readiness_score"] == 90.00

    retired = retire_device(
        env["device"]["id"], reason="meter replaced by a connected model"
    )

    assert retired["status"] == "RETIRED"
    after = read_site(env["site"]["id"], COORDINATOR)
    assert after["site_qc_compliance_index"] == 100.00
    assert after["inspection_readiness_score"] == 100.00
    assert read_device(env["device"]["id"], COORDINATOR)[
        "qc_compliance_rate_day_of_use"
    ] == 50.00
    rows, meta = validate_paginated(
        api_client.list_test_results(
            ADMIN, params={"device_id": env["device"]["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert [row["posting_status"] for row in rows] == ["POSTED", "POSTED"]


def test_the_repeat_multiplier_is_scoped_to_the_category_not_to_the_site():
    """One issuance pins 6.00 on the recurrence and 3.00 on the first of its kind.

    PRD 3.8: "The `repeat_multiplier` is 2.0 when the site has some other finding in
    the **same** `category` whose `created_at` is strictly earlier than this
    finding's and whose `status` is `CLOSED` at the instant of issuance; otherwise it
    is 1.0."

    Design: Corner/calculations/repeat_finding_multiplier_doubles_weight_only_after_the_prior_finding_closed
    """
    _certificate, site, _coverage = setup_covered_site(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243021"},
        site_overrides={
            "name": "Ortho Clinic POCT",
            "department_code": "DEPT-2000",
            "complexity_scope": "WAIVED",
        },
        coverage_overrides={"coverage_end": "2026-12-31"},
    )
    first_survey, closed = setup_closed_finding(site["id"], "QUALITY_CONTROL")
    assert closed["status"] == "CLOSED"
    assert closed["weight"] == 3.00
    assert read_inspection(first_survey["id"])["status"] == "CLOSED"
    second_survey = open_survey(
        site["id"], SURVEYOR,
        inspection_type="BIENNIAL_SURVEY", scheduled_date="2026-09-01",
    )
    repeat = add_finding(
        second_survey["id"], SURVEYOR,
        category="QUALITY_CONTROL", severity="STANDARD_LEVEL",
        description="QC gaps recurred in August",
        correction_due_date="2026-10-31",
    )
    first_of_its_kind = add_finding(
        second_survey["id"], SURVEYOR,
        category="REAGENT_STORAGE", severity="STANDARD_LEVEL",
        description="Fridge temperature log incomplete",
        correction_due_date="2026-10-31",
    )

    issued = issue_survey(second_survey["id"], SURVEYOR, issued_on="2026-09-01")

    repeat_after = read_deficiency(repeat["id"])
    assert repeat_after["repeat_multiplier"] == 2.0
    assert repeat_after["weight"] == 6.00
    first_after = read_deficiency(first_of_its_kind["id"])
    assert first_after["repeat_multiplier"] == 1.0
    assert first_after["weight"] == 3.00
    assert issued["issued_weight_total"] == 9.00
    assert issued["readiness_score_at_issue"] == 77.50
    site_after = read_site(site["id"])
    assert site_after["open_deficiency_weight"] == 9.00
    assert site_after["oversight_posture"] == "RESTRICTED"
    assert site_after["inspection_readiness_score"] == 77.50


def test_the_lapse_deadline_is_strict_so_a_run_on_the_deadline_lapses_nobody():
    """14 grace days on a 2026-09-15 expiry survive 2026-09-29 and fall on 2026-09-30.

    PRD 3.9: "compute a base grace of 30 days when `role_title` is `PHYSICIAN` and 14
    days for every other `role_title`." and "Their `lapse_deadline` is
    `competency_expires_at` advanced by `current_grace_days` whole days, expressed as
    a `YYYY-MM-DD` date, or null when `competency_expires_at` is null." and "For every
    operator whose `competency_status` is `COMPETENT`, whose `lapse_deadline` is not
    null and whose `lapse_deadline` is strictly before the current logical date,
    competency moves `COMPETENT → LAPSED`, access moves to `LOCKED_OUT`, and
    `lockout_reason` becomes `COMPETENCY_LAPSED`."

    Design: Corner/calculations/grace_window_propagates_from_posture_snapshot_to_lapse_deadline
    """
    env = setup_competent_operator(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243022"},
        site_overrides={
            "name": "Primary Care POCT",
            "department_code": "DEPT-2100",
            "complexity_scope": "WAIVED",
        },
        coverage_overrides={"coverage_end": "2026-12-31"},
        director_overrides={"full_name": "Dr. Nadia Roy", "hire_date": "2025-11-01"},
        assessment_overrides={
            "effective_date": "2026-08-01", "expires_at": "2026-09-15"
        },
    )
    assert env["assessment"]["status"] == "APPROVED"
    set_clock("2026-09-29T06:00:00Z")

    on_deadline = run_oversight(note="run exactly on the lapse deadline")

    assert on_deadline["competencies_lapsed"] == 0
    assert on_deadline["operators_locked_out"] == 0
    subject = read_operator(env["subject"]["id"], COORDINATOR)
    assert subject["competency_status"] == "COMPETENT"
    assert subject["competency_expires_at"] == "2026-09-15"
    assert subject["current_grace_days"] == 14
    assert subject["lapse_deadline"] == "2026-09-29"
    director = read_operator(env["director"]["id"], COORDINATOR)
    assert director["current_grace_days"] == 30
    assert director["lapse_deadline"] is None

    set_clock("2026-09-30T06:00:00Z")
    past_deadline = run_oversight(note="run one day past the lapse deadline")

    assert past_deadline["competencies_lapsed"] == 1
    assert past_deadline["operators_locked_out"] == 1
    lapsed = read_operator(env["subject"]["id"], COORDINATOR)
    assert lapsed["competency_status"] == "LAPSED"
    assert lapsed["access_status"] == "LOCKED_OUT"
    assert lapsed["lockout_reason"] == "COMPETENCY_LAPSED"
    site = read_site(env["site"]["id"], COORDINATOR)
    assert site["lapsed_or_locked_operator_count"] == 1
    assert site["total_operator_count"] == 3
    assert site["oversight_posture"] == "OPEN"
    assert site["inspection_readiness_score"] == 91.67
