"""Instrument custody: booking, issue, return, drift, quarantine and calibration."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_equipment,
    assert_equipment_loan,
    build_world,
    issue_loan,
    read_equipment,
    read_loan,
    register_equipment,
    request_loan,
    return_loan,
    run_maintenance,
    set_clock,
    STAGE_CERTIFIED,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-05T09:00:00Z"


def _certified_world():
    return build_world(stage=STAGE_CERTIFIED, clock=CLOCK)


def test_damaged_return_drives_the_unit_into_the_calibration_branch(api):
    """PRD 3.4: "The base drift is the loan's `loan_hours` multiplied by 0.75 parts
    per million per hour, rounded to two decimal places. A damage penalty of 200.00
    ppm is added when the condition is `DAMAGED` and nothing is added when it is
    `GOOD`; an overdue penalty of 100.00 ppm is added when the loan was sitting in
    `OVERDUE` at the moment of return and nothing is added when it was still
    `ISSUED`."
    PRD 3.4: "When it stands at 500.00 or above but below 1000.00, the unit moves
    `QUARANTINE → IN_CALIBRATION` and is taken out of circulation for service."
    PRD 3.4: "the loan's `loan_hours` is computed as the elapsed time from
    `issued_at` to `returned_at` in exact fractional hours **rounded up** to the next
    whole hour."

    Design: Difficulty/non_linear_state_machine/equipment_three_way_fork_and_service_cycle
    """
    world = _certified_world()
    equipment = register_equipment(asset_tag="EQ-001", equipment_type="GPS_LOGGER")
    loan = request_loan(equipment["id"], world["v1"], start_at="2026-08-05T12:00:00Z",
                        due_at="2026-08-22T12:00:00Z")
    issue_loan(loan["id"])
    set_clock("2026-08-22T01:00:00Z")
    returned = return_loan(loan["id"], "DAMAGED")

    assert_equipment_loan(returned)
    assert returned["loan_hours"] == 400, (
        f"09:00 on 2026-08-05 to 01:00 on 2026-08-22 is exactly 400 hours, got "
        f"{returned['loan_hours']}")
    assert float(returned["drift_added_ppm"]) == pytest.approx(500.00, abs=1e-9), (
        f"400 * 0.75 rounded plus the 200.00 damage penalty is 500.00, got "
        f"{returned['drift_added_ppm']}")
    assert returned["status"] == "RETURNED"
    assert read_equipment(equipment["id"])["total_loan_hours"] == 400

    set_clock("2026-08-24T01:00:00Z")
    cleared = validate_success(api.clear_quarantine(equipment["id"], ADMIN))
    assert cleared["status"] == "IN_CALIBRATION", (
        f"500.00 is at or above 500.00 and below 1000.00, got {cleared['status']}")


def test_completing_calibration_closes_the_instrument_service_cycle(api):
    """PRD 3.4: "Completing calibration closes the service cycle. An instrument in
    `IN_CALIBRATION` moves `IN_CALIBRATION → AVAILABLE`, its `calibration_drift_ppm`
    resets to 0.0, and its `calibration_valid_until` is re-stamped to the logical
    clock advanced by 365 days."
    PRD 3.4: "All three branches clear `quarantine_until` back to null and
    increment the instrument's `version`."

    Design: Difficulty/non_linear_state_machine/equipment_three_way_fork_and_service_cycle
    """
    world = _certified_world()
    equipment = register_equipment(asset_tag="EQ-001", equipment_type="GPS_LOGGER")
    loan = request_loan(equipment["id"], world["v1"], start_at="2026-08-05T12:00:00Z",
                        due_at="2026-08-22T12:00:00Z")
    issue_loan(loan["id"])
    set_clock("2026-08-22T01:00:00Z")
    return_loan(loan["id"], "DAMAGED")
    set_clock("2026-08-24T01:00:00Z")
    validate_success(api.clear_quarantine(equipment["id"], ADMIN))

    calibrated = validate_success(api.complete_calibration(equipment["id"], ADMIN))

    assert_equipment(calibrated)
    assert calibrated["status"] == "AVAILABLE"
    assert float(calibrated["calibration_drift_ppm"]) == pytest.approx(0.0, abs=1e-9)
    assert calibrated["calibration_valid_until"] == "2027-08-24T01:00:00.000Z", (
        f"calibration_valid_until is the clock advanced by 365 days, got "
        f"{calibrated['calibration_valid_until']}")
    assert calibrated["quarantine_until"] is None


def test_issuing_a_loan_whose_instrument_is_already_on_loan_is_refused(api):
    """PRD 2.7: "**Priority 24 — loan and equipment state.** Guards five
    operations: `POST /citizen-science/equipment-loans`, `POST
    /citizen-science/equipment-loans/{id}/issue`, `POST
    /citizen-science/equipment-loans/{id}/return`, `POST
    /citizen-science/equipment/{id}/clear-quarantine`, and `POST
    /citizen-science/equipment/{id}/complete-calibration`."
    PRD 3.4: "Issuing hands the unit over. The loan must be in `REQUESTED`, the
    instrument must be `AVAILABLE`, its `calibration_valid_until` must be strictly
    later than the logical clock — an expired calibration is refused with
    `ERR_CALIBRATION_EXPIRED` — and the logical clock must still be before the loan's
    `due_at`, since there is no sense in issuing a unit whose booking window has
    already elapsed."

    Design: Difficulty/cross_entity_state_dependency/loan_issue_requires_equipment_available
    """
    world = _certified_world()
    equipment = register_equipment(asset_tag="EQ-005", equipment_type="SPOTTING_SCOPE")
    first = request_loan(equipment["id"], world["v1"], start_at="2026-08-05T12:00:00Z",
                         due_at="2026-08-10T00:00:00Z")
    second = request_loan(equipment["id"], world["v1"], start_at="2026-08-10T00:00:00Z",
                          due_at="2026-08-15T00:00:00Z")
    issue_loan(first["id"])

    response = api.issue_loan(second["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_EQUIPMENT_STATE_INVALID.value, 409)

    stored = read_loan(second["id"])
    assert stored["status"] == "REQUESTED"
    assert stored["issued_at"] is None


def test_the_conflict_free_second_booking_survives_the_refused_issue(api):
    """PRD 3.4: "On success, `issued_at` is stamped from the logical clock, the
    loan moves `REQUESTED → ISSUED`, and the instrument moves `AVAILABLE → ON_LOAN`;
    both rows' `version` values increment."
    PRD 2.9: "Adjacency is therefore permitted: a request whose `start_at` lands
    exactly on an occupied interval's end instant is accepted."

    Design: Difficulty/cross_entity_state_dependency/loan_issue_requires_equipment_available
    """
    world = _certified_world()
    equipment = register_equipment(asset_tag="EQ-005", equipment_type="SPOTTING_SCOPE")
    first = request_loan(equipment["id"], world["v1"], start_at="2026-08-05T12:00:00Z",
                         due_at="2026-08-10T00:00:00Z")
    second = request_loan(equipment["id"], world["v1"], start_at="2026-08-10T00:00:00Z",
                          due_at="2026-08-15T00:00:00Z")
    assert second["status"] == "REQUESTED", (
        "A window starting exactly at the previous window's end is accepted")
    issue_loan(first["id"])

    validate_error(api.issue_loan(second["id"], ADMIN),
                   ApiErrorId.ERR_EQUIPMENT_STATE_INVALID.value, 409)

    assert read_loan(first["id"])["status"] == "ISSUED"
    assert read_equipment(equipment["id"])["status"] == "ON_LOAN"


def _returned_unit_with_quarantine_tail(world):
    equipment = register_equipment(asset_tag="EQ-003", equipment_type="GPS_LOGGER")
    loan = request_loan(equipment["id"], world["v1"], start_at="2026-08-05T12:00:00Z",
                        due_at="2026-08-08T12:00:00Z")
    issue_loan(loan["id"])
    set_clock("2026-08-07T00:00:00Z")
    loan = return_loan(loan["id"], "GOOD")
    return read_equipment(equipment["id"]), loan


def test_a_booking_that_lands_inside_the_post_return_tail_is_refused(api):
    """PRD 2.9: "a loan whose `status` is `RETURNED` occupies the window from its
    `start_at` up to but not including its `returned_at` plus 48 hours, the
    post-return quarantine tail; and a loan whose `status` is `LOST` or `CANCELLED`
    occupies nothing at all."
    PRD 2.7: "**Priority 42 — instrument interval conflict.** Guards `POST
    /citizen-science/equipment-loans`. The requested window must not intersect any
    occupied interval of the unit under the half-open regime described in §2.9,
    otherwise `ERR_EQUIPMENT_INTERVAL_CONFLICT` (409)."

    Design: Difficulty/resource_temporal_overlap/equipment_half_open_window_conflicts_with_quarantine_tail
    """
    world = _certified_world()
    equipment, loan = _returned_unit_with_quarantine_tail(world)

    assert loan["loan_hours"] == 39, (
        f"09:00 on 2026-08-05 to 00:00 on 2026-08-07 is 39 hours, got "
        f"{loan['loan_hours']}")
    assert float(loan["drift_added_ppm"]) == pytest.approx(29.25, abs=1e-9)
    assert equipment["status"] == "QUARANTINE"
    assert equipment["quarantine_until"] == "2026-08-09T00:00:00.000Z"

    response = api.create_loan({
        "equipment_id": equipment["id"], "volunteer_id": world["v1"],
        "start_at": "2026-08-08T18:00:00Z", "due_at": "2026-08-12T00:00:00Z",
        "expected_equipment_version": equipment["version"]}, ADMIN)
    validate_error(response, ApiErrorId.ERR_EQUIPMENT_INTERVAL_CONFLICT.value, 409)


def test_a_booking_starting_exactly_at_the_tail_end_is_accepted(api):
    """PRD 2.9: "The requested window conflicts with an occupied window exactly
    when the requested start is strictly earlier than the occupied end **and** the
    occupied start is strictly earlier than the requested end. Adjacency is therefore
    permitted: a request whose `start_at` lands exactly on an occupied interval's end
    instant is accepted."
    PRD 3.4: "A successful request lands the loan in `REQUESTED` with `issued_at`
    and `returned_at` null, `condition_on_return` at `NONE`, `loan_hours` at 0, and
    `drift_added_ppm` at 0.0 — and, because booking changes what the instrument's
    calendar looks like to the next requester, it increments the **instrument's**
    `version` by one."

    Design: Difficulty/resource_temporal_overlap/equipment_half_open_window_conflicts_with_quarantine_tail
    """
    world = _certified_world()
    equipment, _loan = _returned_unit_with_quarantine_tail(world)

    validate_error(api.create_loan({
        "equipment_id": equipment["id"], "volunteer_id": world["v1"],
        "start_at": "2026-08-08T18:00:00Z", "due_at": "2026-08-12T00:00:00Z",
        "expected_equipment_version": equipment["version"]}, ADMIN),
        ApiErrorId.ERR_EQUIPMENT_INTERVAL_CONFLICT.value, 409)

    accepted = validate_success(api.create_loan({
        "equipment_id": equipment["id"], "volunteer_id": world["v1"],
        "start_at": "2026-08-09T00:00:00Z", "due_at": "2026-08-12T00:00:00Z",
        "expected_equipment_version": equipment["version"]}, ADMIN), 201)

    assert accepted["status"] == "REQUESTED"
    assert accepted["start_at"] == "2026-08-09T00:00:00.000Z"
    assert accepted["loan_hours"] == 0
    assert float(accepted["drift_added_ppm"]) == pytest.approx(0.0, abs=1e-9)


def test_issuing_a_unit_moves_it_out_of_the_available_pool(api):
    """PRD 3.4: "On success, `issued_at` is stamped from the logical clock, the
    loan moves `REQUESTED → ISSUED`, and the instrument moves `AVAILABLE → ON_LOAN`;
    both rows' `version` values increment."
    PRD 2.3: "Equipment may be filtered by `status` and `equipment_type`; equipment
    loans by `equipment_id`, `volunteer_id`, and `status`."

    Design: Difficulty/compensating_invariant/equipment_custody_ledger_balanced_after_issue_and_return
    """
    world = _certified_world()
    equipment = register_equipment(asset_tag="EQ-004", equipment_type="ACOUSTIC_RECORDER")
    loan = request_loan(equipment["id"], world["v1"], start_at="2026-08-05T12:00:00Z",
                        due_at="2026-08-20T00:00:00Z")

    issued = validate_success(api.issue_loan(loan["id"], ADMIN))

    assert issued["status"] == "ISSUED"
    assert read_equipment(equipment["id"])["status"] == "ON_LOAN"
    _rows, meta = validate_paginated(api.list_loans(ADMIN, {
        "equipment_id": equipment["id"], "status": "ISSUED", "limit": 10, "offset": 0}))
    assert meta["total_count"] == 1, (
        f"Exactly one loan is out against the instrument, got {meta['total_count']}")


def test_returning_a_unit_balances_the_custody_and_hour_ledgers(api):
    """PRD 3.4: "In every case, `returned_at` is stamped from the logical clock,
    the reported condition is stored, and the loan's `loan_hours` is computed as the
    elapsed time from `issued_at` to `returned_at` in exact fractional hours
    **rounded up** to the next whole hour."
    PRD 3.4: "The instrument's `calibration_drift_ppm` becomes its previous value
    plus `drift_added_ppm`, rounded to two decimal places, and its `total_loan_hours`
    grows by the loan's `loan_hours`."
    PRD 2.10: "An instrument's `total_loan_hours` accumulates the `loan_hours` of
    every loan on it that reached `RETURNED` or `LOST`."

    Design: Difficulty/compensating_invariant/equipment_custody_ledger_balanced_after_issue_and_return
    """
    world = _certified_world()
    equipment = register_equipment(asset_tag="EQ-004", equipment_type="ACOUSTIC_RECORDER")
    loan = request_loan(equipment["id"], world["v1"], start_at="2026-08-05T12:00:00Z",
                        due_at="2026-08-20T00:00:00Z")
    issue_loan(loan["id"])
    set_clock("2026-08-07T09:00:00Z")

    returned = validate_success(api.return_loan(
        loan["id"], {"condition_on_return": "GOOD"}, ADMIN))

    assert returned["status"] == "RETURNED"
    assert returned["condition_on_return"] == "GOOD"
    assert returned["loan_hours"] == 48
    assert float(returned["drift_added_ppm"]) == pytest.approx(36.00, abs=1e-9), (
        f"48 * 0.75 with no penalties is 36.00, got {returned['drift_added_ppm']}")

    stored = read_equipment(equipment["id"])
    assert stored["status"] == "QUARANTINE"
    assert stored["total_loan_hours"] == 48
    assert float(stored["calibration_drift_ppm"]) == pytest.approx(36.00, abs=1e-9)
    assert stored["quarantine_until"] == "2026-08-09T09:00:00.000Z"

    _rows, meta = validate_paginated(api.list_loans(ADMIN, {
        "equipment_id": equipment["id"], "status": "ISSUED", "limit": 10, "offset": 0}))
    assert meta["total_count"] == 0, (
        f"No loan is out once the unit is back, got {meta['total_count']}")


def test_a_lost_unit_is_retired_and_its_forward_bookings_are_cancelled(api):
    """PRD 3.4: "When the condition reported is `LOST`, the picture is different.
    The loan moves `ISSUED → LOST` or `OVERDUE → LOST`, `loan_hours` is still
    computed and still accumulates into the instrument's `total_loan_hours`, but
    `drift_added_ppm` stays at 0.00 — a unit that never came back cannot have its
    drift measured."
    PRD 3.4: "The instrument moves `ON_LOAN → RETIRED`, and every other loan on
    that instrument still sitting in `REQUESTED` transitions `REQUESTED → CANCELLED`,
    since those bookings can never be honoured."

    Design: Corner/state_machines/equipment_lost_return_retires_unit_and_cancels_requested_loans
    """
    world = _certified_world()
    equipment = register_equipment(asset_tag="EQ-006", equipment_type="GPS_LOGGER")
    first = request_loan(equipment["id"], world["v1"], start_at="2026-08-05T12:00:00Z",
                         due_at="2026-08-10T00:00:00Z")
    second = request_loan(equipment["id"], world["v1"], start_at="2026-08-10T00:00:00Z",
                          due_at="2026-08-15T00:00:00Z")
    issue_loan(first["id"])
    set_clock("2026-08-07T00:00:00Z")

    lost = validate_success(api.return_loan(
        first["id"], {"condition_on_return": "LOST"}, ADMIN))

    assert lost["status"] == "LOST"
    assert lost["loan_hours"] == 39
    assert float(lost["drift_added_ppm"]) == pytest.approx(0.00, abs=1e-9)

    stored = read_equipment(equipment["id"])
    assert stored["status"] == "RETIRED"
    assert stored["quarantine_until"] is None
    assert float(stored["calibration_drift_ppm"]) == pytest.approx(0.0, abs=1e-9)
    assert stored["total_loan_hours"] == 39
    assert read_loan(second["id"])["status"] == "CANCELLED"


def test_the_maintenance_sweep_marks_an_elapsed_loan_overdue(api):
    """PRD 3.4: "One transition is not driven by any human action: a loan sitting
    in `ISSUED` whose `due_at` the logical clock has reached or passed moves `ISSUED →
    OVERDUE` during the next maintenance sweep."
    PRD 3.9: "Second, loans fall overdue: every loan in `ISSUED` whose `due_at` the
    clock has reached or passed moves `ISSUED → OVERDUE`."

    Design: Corner/state_machines/maintenance_run_marks_issued_loan_overdue
    """
    world = _certified_world()
    equipment = register_equipment(asset_tag="EQ-007", equipment_type="GPS_LOGGER")
    loan = request_loan(equipment["id"], world["v1"], start_at="2026-08-05T12:00:00Z",
                        due_at="2026-08-10T00:00:00Z")
    issue_loan(loan["id"])
    set_clock("2026-08-11T00:00:00Z")

    sweep = validate_success(api.run_maintenance(ADMIN))

    assert sweep["overdue_loan_count"] == 1
    assert sweep["expired_certification_count"] == 0
    assert read_loan(loan["id"])["status"] == "OVERDUE"
    assert read_equipment(equipment["id"])["status"] == "ON_LOAN"


def test_returning_an_overdue_loan_adds_the_overdue_drift_surcharge(api):
    """PRD 3.4: "The base drift is the loan's `loan_hours` multiplied by 0.75 parts
    per million per hour, rounded to two decimal places. A damage penalty of 200.00
    ppm is added when the condition is `DAMAGED` and nothing is added when it is
    `GOOD`; an overdue penalty of 100.00 ppm is added when the loan was sitting in
    `OVERDUE` at the moment of return and nothing is added when it was still
    `ISSUED`."
    PRD 3.4: "The instrument itself moves `ON_LOAN → QUARANTINE` with
    `quarantine_until` set to the logical clock advanced by 48 hours, which is two
    full days in which the unit may be neither issued nor cleared."

    Design: Corner/calculations/overdue_return_adds_overdue_drift_penalty
    """
    world = _certified_world()
    equipment = register_equipment(asset_tag="EQ-008", equipment_type="ACOUSTIC_RECORDER")
    loan = request_loan(equipment["id"], world["v1"], start_at="2026-08-05T12:00:00Z",
                        due_at="2026-08-08T00:00:00Z")
    issue_loan(loan["id"])
    set_clock("2026-08-09T00:00:00Z")
    sweep = run_maintenance()
    assert sweep["overdue_loan_count"] == 1

    returned = validate_success(api.return_loan(
        loan["id"], {"condition_on_return": "GOOD"}, ADMIN))

    assert returned["status"] == "RETURNED"
    assert returned["loan_hours"] == 87
    assert float(returned["drift_added_ppm"]) == pytest.approx(165.25, abs=1e-9), (
        f"87 * 0.75 rounded to 65.25 plus the 100.00 overdue penalty is 165.25, got "
        f"{returned['drift_added_ppm']}")

    stored = read_equipment(equipment["id"])
    assert float(stored["calibration_drift_ppm"]) == pytest.approx(165.25, abs=1e-9)
    assert stored["status"] == "QUARANTINE"
    assert stored["quarantine_until"] == "2026-08-11T00:00:00.000Z"


def test_issuing_a_unit_whose_calibration_has_lapsed_is_refused(api):
    """PRD 2.7: "**Priority 44 — calibration currency.** Guards `POST
    /citizen-science/equipment-loans/{id}/issue`. The unit's
    `calibration_valid_until` must be strictly later than the logical clock,
    otherwise `ERR_CALIBRATION_EXPIRED` (409)."
    PRD 3.4: "It starts `AVAILABLE` with `calibration_drift_ppm` at 0.0,
    `quarantine_until` null, and `total_loan_hours` at 0."

    Design: Corner/errors/loan_issue_after_calibration_expiry_rejected
    """
    world = _certified_world()
    equipment = register_equipment(asset_tag="EQ-009", equipment_type="GPS_LOGGER",
                                   calibration_valid_until="2026-08-06T00:00:00Z")
    loan = request_loan(equipment["id"], world["v1"], start_at="2026-08-05T12:00:00Z",
                        due_at="2026-08-20T00:00:00Z")
    set_clock("2026-08-07T00:00:00Z")

    response = api.issue_loan(loan["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_CALIBRATION_EXPIRED.value, 409)

    assert read_loan(loan["id"])["status"] == "REQUESTED"
    assert read_equipment(equipment["id"])["status"] == "AVAILABLE"


def test_clearing_quarantine_before_the_window_elapses_is_refused(api):
    """PRD 2.7: "**Priority 45 — quarantine elapsed.** Guards `POST
    /citizen-science/equipment/{id}/clear-quarantine`. The logical clock must be at
    or after the unit's `quarantine_until`, otherwise `ERR_QUARANTINE_NOT_ELAPSED`
    (409)."
    PRD 3.4: "When `calibration_drift_ppm` is below 500.00, the unit moves
    `QUARANTINE → AVAILABLE` and returns to the pool."

    Design: Corner/errors/clear_quarantine_before_window_elapsed_rejected
    """
    world = _certified_world()
    equipment = register_equipment(asset_tag="EQ-010", equipment_type="GPS_LOGGER")
    loan = request_loan(equipment["id"], world["v1"], start_at="2026-08-05T12:00:00Z",
                        due_at="2026-08-20T00:00:00Z")
    issue_loan(loan["id"])
    set_clock("2026-08-07T00:00:00Z")
    return_loan(loan["id"], "GOOD")
    set_clock("2026-08-08T23:59:59Z")

    response = api.clear_quarantine(equipment["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_QUARANTINE_NOT_ELAPSED.value, 409)
    assert float(read_equipment(equipment["id"])["calibration_drift_ppm"]) == \
        pytest.approx(29.25, abs=1e-9)

    set_clock("2026-08-09T00:00:00Z")
    cleared = validate_success(api.clear_quarantine(equipment["id"], ADMIN))
    assert cleared["status"] == "AVAILABLE", (
        f"29.25 is below 500.00 so the unit returns to the pool, got {cleared['status']}")
    assert cleared["quarantine_until"] is None


def test_issuing_the_same_loan_twice_is_refused(api):
    """PRD 2.7: "A loan must be `REQUESTED` to be issued and must be `ISSUED` or
    `OVERDUE` to be returned, otherwise `ERR_LOAN_STATE_INVALID` (409)."
    PRD 3.4: "On success, `issued_at` is stamped from the logical clock, the loan
    moves `REQUESTED → ISSUED`, and the instrument moves `AVAILABLE → ON_LOAN`; both
    rows' `version` values increment."

    Design: Corner/errors/loan_issue_twice_returns_loan_state_invalid
    """
    world = _certified_world()
    equipment = register_equipment(asset_tag="EQ-011", equipment_type="GPS_LOGGER")
    loan = request_loan(equipment["id"], world["v1"], start_at="2026-08-05T12:00:00Z",
                        due_at="2026-08-20T00:00:00Z")
    issued = issue_loan(loan["id"])
    assert issued["issued_at"] == "2026-08-05T09:00:00.000Z"

    response = api.issue_loan(loan["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_LOAN_STATE_INVALID.value, 409)

    assert read_loan(loan["id"])["status"] == "ISSUED"
    assert read_equipment(equipment["id"])["status"] == "ON_LOAN"


def test_booking_against_a_stale_instrument_version_is_rejected(api):
    """PRD 2.5: "Requesting an equipment loan — `POST
    /citizen-science/equipment-loans` — requires `expected_equipment_version`
    carrying the client's last observed `version` of the target `Equipment`. A
    mismatch with the equipment's current `version` is rejected with
    `ERR_STALE_EQUIPMENT_VERSION` (HTTP 412)."
    PRD 3.4: "A successful request lands the loan in `REQUESTED` with `issued_at`
    and `returned_at` null, `condition_on_return` at `NONE`, `loan_hours` at 0, and
    `drift_added_ppm` at 0.0 — and, because booking changes what the instrument's
    calendar looks like to the next requester, it increments the **instrument's**
    `version` by one."

    Design: Corner/cross_cutting_layers/occ_stale_equipment_version_on_loan_create_returns_412
    """
    world = _certified_world()
    equipment = register_equipment(asset_tag="EQ-012", equipment_type="GPS_LOGGER")
    stale_version = equipment["version"]
    request_loan(equipment["id"], world["v1"], start_at="2026-08-05T12:00:00Z",
                 due_at="2026-08-10T00:00:00Z")

    response = api.create_loan({
        "equipment_id": equipment["id"], "volunteer_id": world["v1"],
        "start_at": "2026-08-10T00:00:00Z", "due_at": "2026-08-15T00:00:00Z",
        "expected_equipment_version": stale_version}, ADMIN)
    validate_error(response, ApiErrorId.ERR_STALE_EQUIPMENT_VERSION.value, 412)

    refreshed = read_equipment(equipment["id"])
    assert refreshed["version"] == stale_version + 1, (
        f"Booking increments the instrument's version by one, got {refreshed['version']}")

    accepted = validate_success(api.create_loan({
        "equipment_id": equipment["id"], "volunteer_id": world["v1"],
        "start_at": "2026-08-10T00:00:00Z", "due_at": "2026-08-15T00:00:00Z",
        "expected_equipment_version": refreshed["version"]}, ADMIN), 201)
    assert accepted["status"] == "REQUESTED"

    _rows, meta = validate_paginated(api.list_loans(
        ADMIN, {"equipment_id": equipment["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 2
