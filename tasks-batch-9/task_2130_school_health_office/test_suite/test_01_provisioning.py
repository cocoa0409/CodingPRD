"""Buildings, nurses and recurring coverage blocks: staffing conservation,
the two coverage-ratio variants and the posture they feed."""

import pytest

from test_helpers import *  # noqa: F401,F403


def _three_student_building():
    """One building, an RN and a delegated aide on ACTIVE blocks, an LPN block still
    SCHEDULED, and three enrolled students."""
    school = create_school(name="Lincoln Elementary", building_code="LNC01", cot_capacity=2)
    rn = create_nurse(full_name="Rita Nolan", credential="RN", weekly_contracted_minutes=2400)
    aide = create_nurse(full_name="Ada Pike", credential="HEALTH_AIDE",
                        weekly_contracted_minutes=1200, delegation_authorized=True)
    lpn = create_nurse(full_name="Lena Ruiz", credential="LPN",
                       weekly_contracted_minutes=1200, delegation_authorized=True)
    cov_rn = create_coverage(rn["id"], school["id"], weekday="MON", start_minute=480, end_minute=960)
    create_coverage(aide["id"], school["id"], weekday="TUE", start_minute=480, end_minute=780)
    cov_lpn = create_coverage(lpn["id"], school["id"], weekday="WED", start_minute=480,
                              end_minute=840, effective_from="2026-12-01T00:00:00Z")
    for name, grade, dob in [("Ann Reed", 3, "2017-04-11T00:00:00Z"),
                             ("Ben Ortiz", 4, "2016-09-02T00:00:00Z"),
                             ("Cara Diaz", 5, "2015-12-19T00:00:00Z")]:
        create_student(school["id"], full_name=name, grade_level=grade, date_of_birth=dob)
    return school, cov_rn, cov_lpn


def test_contracted_and_delivered_weekly_minutes_count_different_blocks(api, admin_headers):
    """PRD §3.1: "The **CONTRACTED** variant sums `duration_minutes` across every block at the
    building whose `status` is `SCHEDULED` or `ACTIVE`, at full weight, ignoring both the nurse's
    credential and the nurse's employment status; that sum is reported as
    `contracted_weekly_minutes`, and the resulting ratio as `contracted_students_per_nurse_fte`."
    PRD §3.1: "The **DELIVERED** variant admits only blocks whose `status` is `ACTIVE` and whose
    nurse has `employment_status` of `ACTIVE`, and multiplies each block's duration by a credential
    weight before summing: an `RN` counts at 1.00, an `LPN` at 0.60, a `HEALTH_AIDE` with
    `delegation_authorized` true at 0.30, and a `HEALTH_AIDE` without that delegation at 0.00."

    Design: Difficulty/dual_variant_calc/coverage_ratio_contracted_vs_delivered_diverge
    """
    school, cov_rn, cov_lpn = _three_student_building()

    lpn_block = validate_success(api.get_coverage_assignment(cov_lpn["id"], admin_headers))
    rn_block = validate_success(api.get_coverage_assignment(cov_rn["id"], admin_headers))
    assert lpn_block["status"] == "SCHEDULED", "a block whose effective_from is in the future is SCHEDULED"
    assert rn_block["status"] == "ACTIVE"

    data = validate_success(api.get_school(school["id"], admin_headers))
    assert data["enrolled_student_count"] == 3
    assert data["contracted_weekly_minutes"] == 1140, "480 + 300 + 360 at full weight"
    assert data["delivered_weekly_minutes"] == pytest.approx(570.0, abs=0.01), \
        "480 x 1.00 for the RN plus 300 x 0.30 for the delegated aide; the SCHEDULED block contributes nothing"


def test_contracted_and_delivered_ratios_diverge_on_identical_rows(api, admin_headers):
    """PRD §3.1: "Both variants divide a building's enrolled student count by a nurse-FTE figure,
    where one full-time equivalent is 2100 minutes per week; both round half up to two decimal
    places, dividing the unrounded minutes and rounding exactly once at the end."
    PRD §3.1: "One adjustment then applies: if the base posture is `FULL` but the building's
    `stock_protocol_status` is `DEPLETED`, the recorded `coverage_posture` is downgraded to
    `LIMITED`; an `UNCOVERED` base posture stays `UNCOVERED`, and a `LIMITED` base posture is
    unchanged."

    Design: Difficulty/dual_variant_calc/coverage_ratio_contracted_vs_delivered_diverge
    """
    school, _, _ = _three_student_building()

    data = validate_success(api.get_school(school["id"], admin_headers))
    assert data["contracted_students_per_nurse_fte"] == pytest.approx(5.53, abs=0.001)
    assert data["delivered_students_per_nurse_fte"] == pytest.approx(11.05, abs=0.001)
    assert data["contracted_students_per_nurse_fte"] != data["delivered_students_per_nurse_fte"]
    assert data["stock_protocol_status"] == "DEPLETED", "no stock lot has been received"
    assert data["coverage_posture"] == "LIMITED", "a FULL base posture is downgraded by DEPLETED stock"


def test_creating_a_coverage_block_moves_minutes_from_uncommitted_to_committed(api, admin_headers):
    """PRD §2.10: "For every `Nurse`, `weekly_contracted_minutes` always equals
    `committed_weekly_minutes` plus `uncommitted_weekly_minutes`."
    PRD §2.10: "Creating a coverage block adds that block's duration to
    `committed_weekly_minutes` and subtracts the same duration from `uncommitted_weekly_minutes`;
    ending a block reverses both moves exactly, so a create followed by an end leaves the nurse's
    week as it was found and no minutes leak."

    Design: Difficulty/compensating_invariant/nurse_minute_conservation_create_then_end_block
    """
    school = create_school(name="Pierce Elementary", building_code="PIE17")
    nurse = create_nurse(full_name="Otto Vane", credential="RN", weekly_contracted_minutes=1000)
    assert nurse["committed_weekly_minutes"] == 0
    assert nurse["uncommitted_weekly_minutes"] == 1000

    block = create_coverage(nurse["id"], school["id"], weekday="THU", start_minute=480, end_minute=900)
    assert block["duration_minutes"] == 420
    assert block["status"] == "ACTIVE"

    data = validate_success(api.get_nurse(nurse["id"], admin_headers))
    assert data["committed_weekly_minutes"] == 420
    assert data["uncommitted_weekly_minutes"] == 580
    assert_nurse_minute_conservation(data)


def test_ending_a_coverage_block_returns_every_minute_with_zero_drift(api, admin_headers):
    """PRD §2.10: "Creating a coverage block adds that block's duration to
    `committed_weekly_minutes` and subtracts the same duration from `uncommitted_weekly_minutes`;
    ending a block reverses both moves exactly, so a create followed by an end leaves the nurse's
    week as it was found and no minutes leak."
    PRD §3.1: "Ending a block is the compensating half: the administrator supplies an
    `effective_to`, the block's minutes return to the nurse's uncommitted balance,
    `assigned_school_count` is refreshed, and the ratios and posture are recomputed."

    Design: Difficulty/compensating_invariant/nurse_minute_conservation_create_then_end_block
    """
    school = create_school(name="Pierce Elementary", building_code="PIE17")
    nurse = create_nurse(full_name="Otto Vane", credential="RN", weekly_contracted_minutes=1000)
    block = create_coverage(nurse["id"], school["id"], weekday="THU", start_minute=480, end_minute=900)

    ended = validate_success(api.end_coverage_assignment(
        block["id"], {"effective_to": "2026-07-15T00:00:00Z"}, admin_headers))
    assert ended["status"] == "ENDED"

    data = validate_success(api.get_nurse(nurse["id"], admin_headers))
    assert data["weekly_contracted_minutes"] == 1000, "the contracted total never moves"
    assert data["committed_weekly_minutes"] == 0
    assert data["uncommitted_weekly_minutes"] == 1000
    assert data["assigned_school_count"] == 0
    assert_nurse_minute_conservation(data)

    building = validate_success(api.get_school(school["id"], admin_headers))
    assert building["contracted_weekly_minutes"] == 0
    assert building["delivered_weekly_minutes"] == pytest.approx(0.0, abs=0.01)
    assert building["coverage_posture"] == "UNCOVERED"


def _two_building_nurse():
    school_a = create_school(name="Lowell Elementary", building_code="LOW13")
    school_b = create_school(name="Monroe Elementary", building_code="MON14")
    nurse = create_nurse(full_name="Ivy Cole", credential="RN", weekly_contracted_minutes=2400)
    create_coverage(nurse["id"], school_a["id"], weekday="TUE", start_minute=480, end_minute=720)
    return school_a, school_b, nurse


def test_same_building_blocks_may_touch_exactly_on_the_minute(api, admin_headers):
    """PRD §3.1: "Two such blocks at the **same** building may touch exactly — an existing block
    ending on the very minute the new one starts is accepted — but may not overlap, because the
    minute interval is half-open."

    Design: Difficulty/resource_temporal_overlap/nurse_block_half_open_touch_ok_but_cross_school_needs_20_minute_buffer
    """
    school_a, _, nurse = _two_building_nurse()

    resp = api.create_coverage_assignment(
        {"nurse_id": nurse["id"], "school_id": school_a["id"], "weekday": "TUE",
         "start_minute": 720, "end_minute": 900, "effective_from": "2026-07-01T00:00:00Z"},
        admin_headers)
    data = validate_success(resp, 201)
    assert data["duration_minutes"] == 180
    assert_coverage_assignment(data)


def test_cross_building_blocks_need_twenty_minutes_of_clear_travel_time(api, admin_headers):
    """PRD §3.1: "Two such blocks at **different** buildings must additionally be separated by at
    least 20 minutes of clear time on both sides, so that the nurse can physically travel."
    PRD §3.1: "A violation of either arm is `ERR_COVERAGE_OVERLAP` at ladder position 33."

    Design: Difficulty/resource_temporal_overlap/nurse_block_half_open_touch_ok_but_cross_school_needs_20_minute_buffer
    """
    school_a, school_b, nurse = _two_building_nurse()
    create_coverage(nurse["id"], school_a["id"], weekday="TUE", start_minute=720, end_minute=900)

    no_gap = api.create_coverage_assignment(
        {"nurse_id": nurse["id"], "school_id": school_b["id"], "weekday": "TUE",
         "start_minute": 900, "end_minute": 1020, "effective_from": "2026-07-01T00:00:00Z"},
        admin_headers)
    validate_error(no_gap, ApiErrorId.ERR_COVERAGE_OVERLAP.value, 409)

    with_gap = api.create_coverage_assignment(
        {"nurse_id": nurse["id"], "school_id": school_b["id"], "weekday": "TUE",
         "start_minute": 920, "end_minute": 1040, "effective_from": "2026-07-01T00:00:00Z"},
        admin_headers)
    accepted = validate_success(with_gap, 201)
    assert accepted["duration_minutes"] == 120

    nurse_row = validate_success(api.get_nurse(nurse["id"], admin_headers))
    assert nurse_row["committed_weekly_minutes"] == 540, "240 + 180 + 120 minutes are committed"
    assert nurse_row["uncommitted_weekly_minutes"] == 1860
    assert nurse_row["assigned_school_count"] == 2

    _, meta = validate_paginated(api.list_coverage_assignments(admin_headers, {"nurse_id": nurse["id"]}))
    assert meta["total_count"] == 3


def _overdrawn_nurse():
    school = create_school(name="Hoover Elementary", building_code="HOO09")
    nurse = create_nurse(full_name="Nils Bray", credential="RN", weekly_contracted_minutes=600)
    create_coverage(nurse["id"], school["id"], weekday="MON", start_minute=480, end_minute=960)
    return school, nurse


def test_overlapping_block_that_also_overdraws_the_week_reports_the_overlap(api, admin_headers):
    """PRD §2.7: "A block that both collides with an existing block and would overdraw the nurse's
    week returns `ERR_COVERAGE_OVERLAP`, not `ERR_NURSE_HOURS_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/conflict_d_coverage_overlap_outranks_nurse_hours_exceeded
    """
    school, nurse = _overdrawn_nurse()

    resp = api.create_coverage_assignment(
        {"nurse_id": nurse["id"], "school_id": school["id"], "weekday": "MON",
         "start_minute": 900, "end_minute": 1200, "effective_from": "2026-07-01T00:00:00Z"},
        admin_headers)
    validate_error(resp, ApiErrorId.ERR_COVERAGE_OVERLAP.value, 409)


def test_block_rejected_for_overlap_moves_neither_staffing_counter(api, admin_headers):
    """PRD §3.1: "Only once that check passes does the contracted-hours guard at position 47 apply,
    moving the nurse's two conservation counters and refusing the block with
    `ERR_NURSE_HOURS_EXCEEDED` if the post-move `uncommitted_weekly_minutes` would fall below zero."

    Design: Difficulty/priority_pair_validation_conflict/conflict_d_coverage_overlap_outranks_nurse_hours_exceeded
    """
    school, nurse = _overdrawn_nurse()

    api.create_coverage_assignment(
        {"nurse_id": nurse["id"], "school_id": school["id"], "weekday": "MON",
         "start_minute": 900, "end_minute": 1200, "effective_from": "2026-07-01T00:00:00Z"},
        admin_headers)

    data = validate_success(api.get_nurse(nurse["id"], admin_headers))
    assert data["committed_weekly_minutes"] == 480
    assert data["uncommitted_weekly_minutes"] == 120
    assert data["weekly_contracted_minutes"] == 600
    _, meta = validate_paginated(api.list_coverage_assignments(admin_headers, {"nurse_id": nurse["id"]}))
    assert meta["total_count"] == 1, "the refused block was not persisted"


def test_registering_a_building_seeds_its_counters_and_defaults_the_protocol_flag(api, admin_headers):
    """PRD §3.1: "The flag `emergency_protocol_enabled` defaults to true and governs whether
    undesignated stock epinephrine or albuterol may be given at that building at all."
    PRD §3.1: "A freshly registered building starts with `enrolled_student_count` at 0,
    `occupied_cot_count` at 0 and `required_stock_units` at 0; the days-of-supply, protocol-status
    and posture calculations run immediately, which for an empty building yields a
    `stock_protocol_status` of `DEPLETED` and a `coverage_posture` of `UNCOVERED`."

    Design: Corner/entities/school_creation_seeds_derived_fields_and_default_protocol_flag
    """
    resp = api.create_school(
        {"name": "Quincy Elementary", "building_code": "QCY20", "cot_capacity": 4}, admin_headers)
    data = validate_success(resp, 201)
    assert_school(data)

    assert data["emergency_protocol_enabled"] is True
    assert data["cot_capacity"] == 4
    assert data["enrolled_student_count"] == 0
    assert data["eligible_stock_student_count"] == 0
    assert data["required_stock_units"] == 0
    assert data["occupied_cot_count"] == 0
    assert data["epinephrine_days_of_supply"] == pytest.approx(0.0, abs=0.01)
    assert data["albuterol_days_of_supply"] == pytest.approx(0.0, abs=0.01)
    assert data["stock_protocol_status"] == "DEPLETED"
    assert data["contracted_students_per_nurse_fte"] is None, "a zero minute total yields a null ratio"
    assert data["coverage_posture"] == "UNCOVERED"
    assert data["version"] == 1


def test_registering_a_nurse_defaults_delegation_and_seeds_the_conservation_counters(api, admin_headers):
    """PRD §3.1: "The optional `delegation_authorized` flag defaults to false and records whether
    an LPN or aide holds a signed delegation of nursing task."
    PRD §3.1: "On registration, `employment_status` is `ACTIVE`, `committed_weekly_minutes` is 0,
    `uncommitted_weekly_minutes` equals `weekly_contracted_minutes`, and `assigned_school_count`
    is 0."

    Design: Corner/entities/nurse_creation_defaults_delegation_and_seeds_conservation_counters
    """
    create_school(name="Upton Elementary", building_code="UPT24")

    resp = api.create_nurse(
        {"full_name": "Uma Blaine", "credential": "LPN", "weekly_contracted_minutes": 1500},
        admin_headers)
    data = validate_success(resp, 201)
    assert_nurse(data)

    assert data["delegation_authorized"] is False
    assert data["employment_status"] == "ACTIVE"
    assert data["weekly_contracted_minutes"] == 1500
    assert data["committed_weekly_minutes"] == 0
    assert data["uncommitted_weekly_minutes"] == 1500
    assert data["assigned_school_count"] == 0
    assert data["version"] == 1


def test_block_duration_is_fixed_while_its_status_tracks_the_logical_clock(api, admin_headers):
    """PRD §3.1: "The block's `duration_minutes` is simply its end minute less its start minute."
    PRD §3.1: "A block's `status` is not stored by the client but derived from the logical clock:
    it is `SCHEDULED` while the clock is before `effective_from`, `ACTIVE` while the clock is at or
    after `effective_from` and either `effective_to` is null or the clock is before `effective_to`,
    and `ENDED` once `effective_to` is set and the clock has reached it."

    Design: Corner/entities/coverage_assignment_duration_and_status_are_computed_from_clock
    """
    school = create_school(name="Vance Elementary", building_code="VAN25")
    nurse = create_nurse(full_name="Vic Ramos", credential="RN", weekly_contracted_minutes=2400)
    block = create_coverage(nurse["id"], school["id"], weekday="WED", start_minute=540,
                            end_minute=870, effective_from="2026-09-01T00:00:00Z",
                            effective_to="2026-10-01T00:00:00Z")
    assert block["duration_minutes"] == 330
    assert block["status"] == "SCHEDULED", "the default clock is before effective_from"

    set_clock("2026-09-15T00:00:00Z")
    mid = validate_success(api.get_coverage_assignment(block["id"], admin_headers))
    assert mid["status"] == "ACTIVE"
    assert mid["duration_minutes"] == 330

    set_clock("2026-10-01T00:00:00Z")
    ended = validate_success(api.get_coverage_assignment(block["id"], admin_headers))
    assert ended["status"] == "ENDED", "effective_to is reached, so the block has ended"


def test_a_block_on_a_free_weekday_can_still_overdraw_the_contracted_week(api, admin_headers):
    """PRD §2.10: "The guard is applied to the post-move balance and permits equality with zero,
    so a block that consumes the nurse's last remaining minute exactly is accepted while one that
    would drive `uncommitted_weekly_minutes` below zero is refused with `ERR_NURSE_HOURS_EXCEEDED`
    (HTTP 409, ladder position 47) and moves neither counter."

    Design: Corner/validations/nurse_hours_exceeded_fires_when_no_interval_overlap_exists
    """
    school = create_school(name="Xenia Elementary", building_code="XEN52")
    nurse = create_nurse(full_name="Xan Petrov", credential="RN", weekly_contracted_minutes=600)
    create_coverage(nurse["id"], school["id"], weekday="MON", start_minute=480, end_minute=960)

    resp = api.create_coverage_assignment(
        {"nurse_id": nurse["id"], "school_id": school["id"], "weekday": "TUE",
         "start_minute": 480, "end_minute": 780, "effective_from": "2026-07-01T00:00:00Z"},
        admin_headers)
    validate_error(resp, ApiErrorId.ERR_NURSE_HOURS_EXCEEDED.value, 409)

    data = validate_success(api.get_nurse(nurse["id"], admin_headers))
    assert data["committed_weekly_minutes"] == 480
    assert data["uncommitted_weekly_minutes"] == 120
    assert data["assigned_school_count"] == 1
    _, meta = validate_paginated(api.list_coverage_assignments(admin_headers, {"nurse_id": nurse["id"]}))
    assert meta["total_count"] == 1


def test_an_undelegated_aide_delivers_no_weighted_minutes_until_delegation_is_granted(api, admin_headers):
    """PRD §3.1: "The **DELIVERED** variant admits only blocks whose `status` is `ACTIVE` and whose
    nurse has `employment_status` of `ACTIVE`, and multiplies each block's duration by a credential
    weight before summing: an `RN` counts at 1.00, an `LPN` at 0.60, a `HEALTH_AIDE` with
    `delegation_authorized` true at 0.30, and a `HEALTH_AIDE` without that delegation at 0.00."
    PRD §3.1: "When the relevant minute total is zero, the corresponding ratio is null rather than
    any numeric value."

    Design: Corner/calculations/coverage_posture_uncovered_when_only_an_undelegated_aide_covers
    """
    school = create_school(name="Rowan Elementary", building_code="ROW46")
    aide = create_nurse(full_name="Rae Osei", credential="HEALTH_AIDE",
                        weekly_contracted_minutes=1200, delegation_authorized=False)
    create_coverage(aide["id"], school["id"], weekday="MON", start_minute=480, end_minute=960)
    create_student(school["id"], full_name="Rory Ives", grade_level=1,
                   date_of_birth="2019-09-09T00:00:00Z")

    before = validate_success(api.get_school(school["id"], admin_headers))
    assert before["contracted_weekly_minutes"] == 480
    assert before["contracted_students_per_nurse_fte"] == pytest.approx(4.38, abs=0.001)
    assert before["delivered_weekly_minutes"] == pytest.approx(0.0, abs=0.01)
    assert before["delivered_students_per_nurse_fte"] is None
    assert before["coverage_posture"] == "UNCOVERED"

    validate_success(api.patch_nurse(aide["id"], {"delegation_authorized": True}, admin_headers))

    after = validate_success(api.get_school(school["id"], admin_headers))
    assert after["delivered_weekly_minutes"] == pytest.approx(144.0, abs=0.01), "480 x 0.30"
    assert after["delivered_students_per_nurse_fte"] == pytest.approx(14.58, abs=0.001)
    assert after["coverage_posture"] == "LIMITED", "a FULL base posture downgraded by DEPLETED stock"
    assert after["contracted_students_per_nurse_fte"] == pytest.approx(4.38, abs=0.001), \
        "the contracted variant never reads credential"


def test_marking_a_nurse_inactive_recomputes_the_delivered_ratio_and_posture(api, admin_headers):
    """PRD §3.1: "Later, an administrator may amend a nurse's `employment_status` — the only other
    value is `INACTIVE` — or the `delegation_authorized` flag; either amendment increments the
    nurse's `version` and forces both coverage-ratio variants and the posture to be recomputed at
    every building where that nurse holds a block in `SCHEDULED` or `ACTIVE` status."

    Design: Corner/endpoints/nurse_patch_flips_employment_status_and_recomputes_every_school
    """
    school = create_school(name="Bracewell Elementary", building_code="BRC56")
    nurse = create_nurse(full_name="Bea Ortega", credential="RN", weekly_contracted_minutes=2400)
    block = create_coverage(nurse["id"], school["id"], weekday="MON", start_minute=480, end_minute=960)
    create_student(school["id"], full_name="Bram Kell", grade_level=2,
                   date_of_birth="2018-05-05T00:00:00Z")

    before = validate_success(api.get_school(school["id"], admin_headers))
    assert before["delivered_weekly_minutes"] == pytest.approx(480.0, abs=0.01)
    assert before["coverage_posture"] == "LIMITED"

    before_nurse = validate_success(api.get_nurse(nurse["id"], admin_headers))
    patched = validate_success(api.patch_nurse(nurse["id"], {"employment_status": "INACTIVE"}, admin_headers))
    assert patched["employment_status"] == "INACTIVE"
    assert patched["version"] == before_nurse["version"] + 1

    after = validate_success(api.get_school(school["id"], admin_headers))
    assert after["contracted_weekly_minutes"] == 480
    assert after["contracted_students_per_nurse_fte"] == pytest.approx(4.38, abs=0.001)
    assert after["delivered_weekly_minutes"] == pytest.approx(0.0, abs=0.01)
    assert after["delivered_students_per_nurse_fte"] is None
    assert after["coverage_posture"] == "UNCOVERED"

    still_active = validate_success(api.get_coverage_assignment(block["id"], admin_headers))
    assert still_active["status"] == "ACTIVE", "the block itself is untouched"


def test_reusing_a_building_code_is_refused(api, admin_headers):
    """PRD §3.1: "The building code is a two- to eight-character uppercase alphanumeric string and
    must be unique across every building on record; a collision is refused with
    `ERR_DUPLICATE_BUILDING_CODE` at ladder position 40."

    Design: Corner/errors/error_duplicate_building_code_on_school_create
    """
    first = create_school(name="Dupont Elementary", building_code="DUP75", cot_capacity=2)

    resp = api.create_school(
        {"name": "Dupont Annex", "building_code": "DUP75", "cot_capacity": 3,
         "emergency_protocol_enabled": False}, admin_headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_BUILDING_CODE.value, 409)

    unchanged = validate_success(api.get_school(first["id"], admin_headers))
    assert unchanged["cot_capacity"] == 2
    assert unchanged["emergency_protocol_enabled"] is True
