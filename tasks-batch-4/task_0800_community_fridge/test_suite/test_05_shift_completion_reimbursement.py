"""Shift completion: reimbursement math, cleaning cyclic revert, reliability,
posture reconciliation, and the steward-active gate."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_fridge_and_steward, new_shift, set_clock, record_temperature,
    make_admin_headers, make_steward_headers,
    complete_shift_payload,
)


def _complete(api, shift_id, steward_id, miles=0, cold_chain=False, as_admin=False):
    headers = make_admin_headers() if as_admin else make_steward_headers(steward_id)
    return api.complete_shift(
        shift_id,
        complete_shift_payload(miles_traveled=miles, handled_cold_chain=cold_chain),
        headers,
    )


def _fridge(api, fridge_id):
    return validate_success(api.get_fridge(fridge_id, make_admin_headers()), 200)


def _restricted_cleaning_scenario(api):
    """RESTRICTED fridge + a SCHEDULED CLEANING shift, clock past its start."""
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=5)
    record_temperature(api, fridge["id"], 10.0, steward_id=steward["id"])
    shift = new_shift(api, fridge["id"], steward["id"], kind="CLEANING",
                      start_at="2026-03-01T09:00:00Z", end_at="2026-03-01T11:00:00Z")
    set_clock(api, "2026-03-01T09:30:00Z")
    return fridge, steward, shift


def test_reimbursement_combines_base_mileage_bonus_and_hazard_multiplier(api):
    """PRD §3.3: "for more than 5 and up to 20 miles it is 250 cents plus 30 cents for
    each mile above 5 ... a cold-chain bonus of 500 cents is added when
    `handled_cold_chain` is true ... the sum is multiplied by a hazard factor: 1.25
    when the fridge's `safety_posture` is `RESTRICTED` at the moment of completion."

    Design: Difficulty/combinatorial_formula/shift_reimbursement_tiered_mileage_posture
    """
    fridge, steward, shift = _restricted_cleaning_scenario(api)
    data = validate_success(
        _complete(api, shift["id"], steward["id"], miles=12, cold_chain=True), 200
    )
    # base 2000 + mileage(5*50 + 7*30 = 460) + bonus 500 = 2960, *1.25 = 3700
    assert data["reimbursement_amount_cents"] == 3700


def test_reimbursement_committed_to_fridge_budget(api):
    """PRD §3.3: "the reimbursement is calculated and committed to the fridge's
    `budget_committed_cents`."

    Design: Difficulty/combinatorial_formula/shift_reimbursement_tiered_mileage_posture
    """
    fridge, steward, shift = _restricted_cleaning_scenario(api)
    validate_success(
        _complete(api, shift["id"], steward["id"], miles=12, cold_chain=True), 200
    )
    assert _fridge(api, fridge["id"])["budget_committed_cents"] == 3700


def _completed_cleaning_shift(api):
    """A CLEANING shift COMPLETED (OPERATIONAL fridge, 0 miles -> reimb 2000)."""
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=5)
    shift = new_shift(api, fridge["id"], steward["id"], kind="CLEANING",
                      start_at="2026-03-01T09:00:00Z", end_at="2026-03-01T11:00:00Z")
    set_clock(api, "2026-03-01T09:30:00Z")
    completed = validate_success(_complete(api, shift["id"], steward["id"]), 200)
    return fridge, steward, completed


def test_fail_inspection_reverts_shift_and_zeroes_reimbursement(api):
    """PRD §3.3: "it moves the shift from `COMPLETED` back to `SCHEDULED`. The reversal
    subtracts the shift's `reimbursement_amount_cents` from the fridge's
    `budget_committed_cents` and then zeroes `reimbursement_amount_cents`."

    Design: Difficulty/non_linear_state_machine/shift_completed_failinspection_reopen_cycle
    """
    fridge, steward, completed = _completed_cleaning_shift(api)
    assert completed["reimbursement_amount_cents"] == 2000
    reverted = validate_success(
        api.fail_inspection(completed["id"], make_admin_headers()), 200
    )
    assert reverted["status"] == "SCHEDULED"
    assert reverted["reimbursement_amount_cents"] == 0


def test_fail_inspection_reverses_committed_budget(api):
    """PRD §3.3: "The reversal subtracts the shift's `reimbursement_amount_cents` from
    the fridge's `budget_committed_cents` and then zeroes `reimbursement_amount_cents`."

    Design: Difficulty/non_linear_state_machine/shift_completed_failinspection_reopen_cycle
    """
    fridge, steward, completed = _completed_cleaning_shift(api)
    validate_success(api.fail_inspection(completed["id"], make_admin_headers()), 200)
    assert _fridge(api, fridge["id"])["budget_committed_cents"] == 0


def _reliability_scenario(api):
    """Steward with 1 COMPLETED, 1 MISSED, and 2 future SCHEDULED shifts."""
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=6)
    sid = steward["id"]
    completed_shift = new_shift(api, fridge["id"], sid, kind="COVERAGE",
                               start_at="2026-03-01T09:00:00Z", end_at="2026-03-01T10:00:00Z")
    new_shift(api, fridge["id"], sid, kind="COVERAGE",
              start_at="2026-03-02T09:00:00Z", end_at="2026-03-02T10:00:00Z")
    new_shift(api, fridge["id"], sid, kind="COVERAGE",
              start_at="2026-03-20T09:00:00Z", end_at="2026-03-20T10:00:00Z")
    new_shift(api, fridge["id"], sid, kind="COVERAGE",
              start_at="2026-03-21T09:00:00Z", end_at="2026-03-21T10:00:00Z")
    set_clock(api, "2026-03-01T09:30:00Z")
    validate_success(_complete(api, completed_shift["id"], sid), 200)
    set_clock(api, "2026-03-02T10:30:00Z")  # second shift now past end -> MISSED via run-ops
    validate_success(api.run_ops(fridge["id"], make_admin_headers()), 200)
    return fridge, steward


def test_reliability_actual_counts_only_resolved_shifts(api):
    """PRD §3.3: "The `reliability_actual` score is the completed tally divided by the
    sum of the completed and missed tallies, rounded half-up to two decimals; if that
    sum is zero, `reliability_actual` is 1.00."

    Design: Difficulty/dual_variant_calc/steward_reliability_actual_vs_projected
    """
    fridge, steward = _reliability_scenario(api)
    fetched = validate_success(api.get_steward(steward["id"], make_admin_headers()), 200)
    assert fetched["reliability_actual"] == 0.5


def test_reliability_projected_counts_upcoming_shifts_as_completions(api):
    """PRD §3.3: "it is the completed tally plus the upcoming tally, divided by the sum
    of the completed, missed, and upcoming tallies, rounded half-up to two decimals; if
    that sum is zero, `reliability_projected` is 1.00."

    Design: Difficulty/dual_variant_calc/steward_reliability_actual_vs_projected
    """
    fridge, steward = _reliability_scenario(api)
    fetched = validate_success(api.get_steward(steward["id"], make_admin_headers()), 200)
    assert fetched["reliability_projected"] == 0.75


def _overdue_cleaning_scenario(api):
    """Fridge created at 2026-03-01, clock advanced 14 days (cleaning overdue ->
    RESTRICTED), with a CLEANING shift scheduled for that time."""
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=5)
    shift = new_shift(api, fridge["id"], steward["id"], kind="CLEANING",
                      start_at="2026-03-15T09:00:00Z", end_at="2026-03-15T11:00:00Z")
    set_clock(api, "2026-03-15T09:30:00Z")
    return fridge, steward, shift


def test_cleaning_completion_restores_operational_posture(api):
    """PRD §3.3: "When the completed shift is a `CLEANING` shift, completion also sets
    the fridge's `last_cleaned_at` to the current logical time and recomputes the
    fridge's `safety_posture`, which can lift a fridge out of `RESTRICTED` if a
    stale-cleaning condition was the only thing holding it there."

    Design: Difficulty/transitive_cascade/cleaning_complete_lastcleaned_posture_chain
    """
    fridge, steward, shift = _overdue_cleaning_scenario(api)
    assert _fridge(api, fridge["id"])["safety_posture"] == "RESTRICTED"
    validate_success(_complete(api, shift["id"], steward["id"]), 200)
    assert _fridge(api, fridge["id"])["safety_posture"] == "OPERATIONAL"


def test_cleaning_completion_sets_last_cleaned_at_to_now(api):
    """PRD §3.3: "When the completed shift is a `CLEANING` shift, completion also sets
    the fridge's `last_cleaned_at` to the current logical time and recomputes the
    fridge's `safety_posture`."

    Design: Difficulty/transitive_cascade/cleaning_complete_lastcleaned_posture_chain
    """
    fridge, steward, shift = _overdue_cleaning_scenario(api)
    validate_success(_complete(api, shift["id"], steward["id"]), 200)
    assert _fridge(api, fridge["id"])["last_cleaned_at"] == "2026-03-15T09:30:00.000Z"


def test_complete_shift_with_suspended_steward_rejected(api):
    """PRD §3.3: "the steward must be `ACTIVE`, or the request fails with
    `ERR_STEWARD_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/complete_requires_steward_active
    """
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=5)
    shift = new_shift(api, fridge["id"], steward["id"], kind="COVERAGE",
                      start_at="2026-03-01T09:00:00Z", end_at="2026-03-01T10:00:00Z")
    validate_success(api.suspend_steward(steward["id"], make_admin_headers()), 200)
    set_clock(api, "2026-03-01T09:30:00Z")
    resp = _complete(api, shift["id"], steward["id"], as_admin=True)
    validate_error(resp, ApiErrorId.ERR_STEWARD_SUSPENDED.value)


def test_complete_shift_with_active_steward_succeeds(api):
    """PRD §3.3: "On success the shift moves from `SCHEDULED` to `COMPLETED`, its
    `completed_at` is stamped with the current logical time, the steward's
    `completed_count` is recomputed, and the reimbursement is calculated and committed
    to the fridge's `budget_committed_cents`."

    Design: Difficulty/cross_entity_state_dependency/complete_requires_steward_active
    """
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=5)
    shift = new_shift(api, fridge["id"], steward["id"], kind="COVERAGE",
                      start_at="2026-03-01T09:00:00Z", end_at="2026-03-01T10:00:00Z")
    set_clock(api, "2026-03-01T09:30:00Z")
    data = validate_success(_complete(api, shift["id"], steward["id"]), 200)
    assert data["status"] == "COMPLETED"


def test_fail_inspection_on_coverage_shift_rejected_invalid_state(api):
    """PRD §3.3: "This is a deliberate cyclic revert: it is permitted only when the
    shift's `kind` is `CLEANING` (otherwise `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/fail_inspection_on_coverage_shift_returns_invalid_state
    """
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=5)
    shift = new_shift(api, fridge["id"], steward["id"], kind="COVERAGE",
                      start_at="2026-03-01T09:00:00Z", end_at="2026-03-01T10:00:00Z")
    set_clock(api, "2026-03-01T09:30:00Z")
    validate_success(_complete(api, shift["id"], steward["id"]), 200)
    resp = api.fail_inspection(shift["id"], make_admin_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
