"""State machines: self-loops, once-only reversals, bounded cycles and terminal lockdown."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS, make_subrecipient_coordinator_headers


ADMIN = TEST_USERS["program_administrator_headers"]


# ─── The two-state contractor machine has no self-loop ────────────────────────

def test_setting_the_contractor_status_to_the_value_it_already_holds_is_refused(api):
    """The guard is "different from the current value", so both directions can refuse.

    "A `ProgramAdministrator` may set the contractor's `status` to `ACTIVE` or
    `SUSPENDED`, optionally with a `status_reason`. Setting it to the value it
    already holds is `ERR_INVALID_CONTRACTOR_STATE`, so the toggle is strictly a
    change."

    "Either direction advances the contractor's `version` by 1."

    Design: Corner/state_machines/contractor_status_change_to_the_current_status_is_refused
    """
    api.set_clock("2026-08-01T00:00:00Z")
    contractor = fixtures.create_contractor(
        api, name="Riverbend Wrecking", license_no="DEM-1",
        asbestos_certified=True, max_concurrent_work_orders=2,
    )
    assert contractor["status"] == "ACTIVE"
    assert contractor["version"] == 1

    validate_error(
        api.set_contractor_status(
            contractor["id"],
            factories.contractor_status_payload(
                contractor["id"], "ACTIVE", status_reason="no change"
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_CONTRACTOR_STATE.value,
        409,
    )
    unmoved = validate_success(api.get_demolition_contractor(contractor["id"], ADMIN))
    assert unmoved["status"] == "ACTIVE"
    assert unmoved["version"] == 1

    suspended = validate_success(
        api.set_contractor_status(
            contractor["id"],
            factories.contractor_status_payload(
                contractor["id"], "SUSPENDED", status_reason="license lapse"
            ),
            ADMIN,
        )
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["version"] == 2

    validate_error(
        api.set_contractor_status(
            contractor["id"],
            factories.contractor_status_payload(
                contractor["id"], "SUSPENDED", status_reason="still lapsed"
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_CONTRACTOR_STATE.value,
        409,
    )
    final = validate_success(api.get_demolition_contractor(contractor["id"], ADMIN))
    assert final["status"] == "SUSPENDED"
    assert final["version"] == 2


# ─── Reversal is once-only on both ledger-like entities ───────────────────────

def test_a_dob_record_may_be_reversed_once_and_the_parcel_total_drops_once(api):
    """The second reverse is refused, so the rollup cannot double-subtract.

    "The record must be `ACTIVE`; reversing one already at `REVERSED` is
    `ERR_ALREADY_REVERSED`."

    "The record's `version` advances by 1, the parcel's `dob_deduction_total_cents`
    is recomputed without it, and the parcel's `version` advances by 1."

    Design: Corner/state_machines/reversing_an_already_reversed_dob_record_or_ledger_entry_is_refused
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = fixtures.create_approved_project(api)
    record = fixtures.record_dob(
        api, state["project"], state["parcel"]["id"],
        benefit_source="NFIP_CLAIM", amount_cents=900_000, received_on="2026-03-01",
    )
    assert record["deductible_cents"] == 900_000

    parcel = validate_success(api.get_parcel(state["parcel"]["id"], ADMIN))
    assert parcel["dob_deduction_total_cents"] == 900_000

    reversed_record = validate_success(
        api.reverse_dob_record(
            record["id"],
            factories.reverse_dob_record_payload(
                record["id"], reversal_reason="insurer clawback"
            ),
            ADMIN,
        )
    )
    assert reversed_record["status"] == "REVERSED"

    parcel = validate_success(api.get_parcel(state["parcel"]["id"], ADMIN))
    assert parcel["dob_deduction_total_cents"] == 0

    validate_error(
        api.reverse_dob_record(
            record["id"],
            factories.reverse_dob_record_payload(
                record["id"], reversal_reason="insurer clawback again"
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_ALREADY_REVERSED.value,
        409,
    )

    unchanged = validate_success(api.get_parcel(state["parcel"]["id"], ADMIN))
    assert unchanged["dob_deduction_total_cents"] == 0


def test_a_ledger_entry_may_be_reversed_once_and_the_balance_drops_once(api):
    """A repeat reversal of the same entry is refused with the same identifier.

    "The target must exist, otherwise `ERR_LEDGER_ENTRY_NOT_FOUND`, and must have
    `status` `ACTIVE`; a target already at `REVERSED` is `ERR_ALREADY_REVERSED`, so
    reversal is strictly once-only."

    "Because the mirror is never `ACTIVE`, reversing an entry can never itself
    trigger `ERR_PROGRAM_INCOME_OVERDRAWN`, even when the reversed entry was a large
    credit that expenditures had already drawn against."

    Design: Corner/state_machines/reversing_an_already_reversed_dob_record_or_ledger_entry_is_refused
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = fixtures.create_approved_project(api)
    entry = fixtures.post_program_income(
        api, state["project"]["id"], entry_type="LEASE_REVENUE",
        amount_cents=100_000, posted_on="2026-08-01",
    )
    assert entry["federal_share_cents"] == 75_000

    project = validate_success(
        api.get_mitigation_project(state["project"]["id"], ADMIN)
    )
    assert project["program_income_balance_cents"] == 75_000

    mirror = validate_success(
        api.reverse_program_income_entry(
            entry["id"],
            factories.reverse_program_income_entry_payload(
                entry["id"], reversal_note="posted in error"
            ),
            ADMIN,
        ),
        201,
    )
    assert mirror["status"] == "REVERSED"

    target = validate_success(api.get_program_income_entry(entry["id"], ADMIN))
    assert target["status"] == "REVERSED"

    project = validate_success(
        api.get_mitigation_project(state["project"]["id"], ADMIN)
    )
    assert project["program_income_balance_cents"] == 0

    validate_error(
        api.reverse_program_income_entry(
            entry["id"],
            factories.reverse_program_income_entry_payload(
                entry["id"], reversal_note="posted in error again"
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_ALREADY_REVERSED.value,
        409,
    )

    unchanged = validate_success(
        api.get_mitigation_project(state["project"]["id"], ADMIN)
    )
    assert unchanged["program_income_balance_cents"] == 0


# ─── The bounded appraisal revision cycle ─────────────────────────────────────

def _appraisal_returned_three_times(api):
    """Traverse SUBMITTED -> RETURNED_FOR_REVISION three times on one appraisal."""
    state = fixtures.create_approved_project(api)
    author = TEST_USERS["staff_appraiser_headers"]
    reviewer = TEST_USERS["review_appraiser_headers"]
    appraisal = validate_success(
        api.create_appraisal(
            state["parcel"]["id"],
            factories.create_appraisal_payload(
                state["parcel"]["id"], appraiser_license_no="LIC-SA-1",
                effective_date="2026-07-01", indicated_value_cents=20_000_000,
            ),
            author,
        ),
        201,
    )

    revised_values = (None, 20_100_000, 20_200_000)
    notes = ("comparables thin", "adjustments unsupported", "still unsupported")
    for revised, note in zip(revised_values, notes):
        payload = factories.submit_appraisal_payload(appraisal["id"])
        if revised is not None:
            payload["indicated_value_cents"] = revised
        submitted = validate_success(
            api.submit_appraisal(appraisal["id"], author, payload)
        )
        assert submitted["status"] == "SUBMITTED"
        returned = validate_success(
            api.review_appraisal(
                appraisal["id"],
                factories.review_decision_payload(
                    appraisal["id"], "RETURN", review_note=note
                ),
                reviewer,
            )
        )
        assert returned["status"] == "RETURNED_FOR_REVISION"

    state["appraisal"] = validate_success(api.get_appraisal(appraisal["id"], ADMIN))
    return state


def test_the_third_resubmission_still_succeeds_at_a_revision_count_of_two(api):
    """Equality with the limit is permitted, so the cycle survives three returns.

    "A submission from `RETURNED_FOR_REVISION` requires `revision_count` to be at
    most 2; a `revision_count` of exactly 2 still submits, and a `revision_count` of
    3 is refused with `ERR_APPRAISAL_REVISION_LIMIT`."

    "`RETURN` is admitted only from `SUBMITTED`; a return attempted against an
    appraisal already in `RETURNED_FOR_REVISION` is `ERR_INVALID_APPRAISAL_STATE`.
    It moves `status` to `RETURNED_FOR_REVISION`, increments `revision_count` by 1,
    and advances `version` by 1."

    "The submission may optionally carry a revised `effective_date` and a revised
    `indicated_value_cents`, which overwrite the stored values before the validity
    window is computed."

    Design: Corner/state_machines/a_third_return_pushes_the_appraisal_past_the_revision_limit_on_resubmission
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = _appraisal_returned_three_times(api)

    assert state["appraisal"]["status"] == "RETURNED_FOR_REVISION"
    assert state["appraisal"]["revision_count"] == 3
    assert state["appraisal"]["indicated_value_cents"] == 20_200_000


def test_the_fourth_submission_at_a_revision_count_of_three_hits_the_limit(api):
    """The refusal parks the appraisal in RETURNED_FOR_REVISION with its stored value.

    "Because each return increments `revision_count` by 1, an appraisal survives
    being returned three times and dies on the fourth resubmission attempt."

    "The submission may optionally carry a revised `effective_date` and a revised
    `indicated_value_cents`, which overwrite the stored values before the validity
    window is computed."

    Design: Corner/state_machines/a_third_return_pushes_the_appraisal_past_the_revision_limit_on_resubmission
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = _appraisal_returned_three_times(api)

    validate_error(
        api.submit_appraisal(
            state["appraisal"]["id"],
            TEST_USERS["staff_appraiser_headers"],
            factories.submit_appraisal_payload(
                state["appraisal"]["id"], indicated_value_cents=20_300_000
            ),
        ),
        ApiErrorId.ERR_APPRAISAL_REVISION_LIMIT.value,
        409,
    )

    appraisal = validate_success(
        api.get_appraisal(state["appraisal"]["id"], ADMIN)
    )
    assert appraisal["status"] == "RETURNED_FOR_REVISION"
    assert appraisal["revision_count"] == 3
    assert appraisal["indicated_value_cents"] == 20_200_000


# ─── The bounded demolition rework cycle ──────────────────────────────────────

def _work_order_ready_on_a_draft_project(api):
    project = fixtures.create_draft_project(api, grant_program="FMA")
    parcel = fixtures.create_parcel(
        api, project, apn="APN-SM-REWORK", site_address="2701 River Rd",
        occupancy_type="VACANT",
    )
    contractor = fixtures.create_contractor(
        api, name="Riverbend Wrecking", license_no="DEM-1",
        asbestos_certified=True, max_concurrent_work_orders=2,
    )
    work_order = fixtures.issue_work_order(
        api, project, parcel["id"], contractor["id"],
        asbestos_survey_status="CLEARED",
        scheduled_start="2026-09-01T08:00:00Z",
        scheduled_end="2026-09-03T17:00:00Z",
    )
    disconnections = fixtures.order_all_utility_disconnections(
        api, project, work_order["id"]
    )
    fixtures.confirm_all_utility_disconnections(api, project, disconnections)
    work_order = validate_success(
        api.get_demolition_work_order(work_order["id"], ADMIN)
    )
    assert work_order["status"] == "READY"
    return {
        "project": project,
        "parcel": parcel,
        "contractor": contractor,
        "work_order": work_order,
    }


def _fail_three_inspections(api, state):
    """Traverse IN_PROGRESS -> FAILED_INSPECTION three times on one work order."""
    coordinator = make_subrecipient_coordinator_headers(state["project"]["id"])
    monitor = TEST_USERS["compliance_monitor_headers"]
    work_order_id = state["work_order"]["id"]
    notes = ("debris left on grade", "foundation not removed", "grade not restored")
    for index, note in enumerate(notes, start=1):
        started = validate_success(
            api.start_demolition_work_order(work_order_id, coordinator)
        )
        assert started["status"] == "IN_PROGRESS"
        failed = validate_success(
            api.fail_demolition_inspection(
                work_order_id,
                factories.fail_inspection_payload(work_order_id, inspection_note=note),
                monitor,
            )
        )
        assert failed["status"] == "FAILED_INSPECTION"
        assert failed["failed_inspection_count"] == index
    return validate_success(api.get_demolition_work_order(work_order_id, ADMIN))


def test_the_third_restart_succeeds_while_the_failed_inspection_count_is_two(api):
    """The count is bumped by the monitor's call, and equality with the cap still starts.

    "Third, when starting from `FAILED_INSPECTION`, `failed_inspection_count` must
    be at most 2; a count strictly greater than 2 is `ERR_DEMOLITION_REWORK_LIMIT`,
    so a work order survives three failed inspections and dies on the fourth restart
    attempt."

    "It moves to `FAILED_INSPECTION`, `failed_inspection_count` increments by 1, and
    the work order's `version` advances by 1. No parcel or contractor field moves,
    and because `FAILED_INSPECTION` is one of the statuses counted by
    `active_work_order_count`, the contractor's capacity is not released."

    Design: Corner/state_machines/a_fourth_demolition_restart_after_three_failed_inspections_hits_the_rework_limit
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = _work_order_ready_on_a_draft_project(api)

    work_order = _fail_three_inspections(api, state)
    assert work_order["status"] == "FAILED_INSPECTION"
    assert work_order["failed_inspection_count"] == 3

    contractor = validate_success(
        api.get_demolition_contractor(state["contractor"]["id"], ADMIN)
    )
    assert contractor["active_work_order_count"] == 1


def test_the_fourth_restart_at_a_failed_inspection_count_of_three_hits_the_limit(api):
    """The cycle dies on the restart, leaving the work order in FAILED_INSPECTION.

    "Fourth, the work order must not still be in `UTILITY_HOLD` - if some
    `utility_type` in `required_utility_types` has no `CONFIRMED` child, the start is
    `ERR_UTILITY_DISCONNECT_INCOMPLETE`."

    "Third, when starting from `FAILED_INSPECTION`, `failed_inspection_count` must
    be at most 2; a count strictly greater than 2 is `ERR_DEMOLITION_REWORK_LIMIT`,
    so a work order survives three failed inspections and dies on the fourth restart
    attempt."

    Design: Corner/state_machines/a_fourth_demolition_restart_after_three_failed_inspections_hits_the_rework_limit
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = _work_order_ready_on_a_draft_project(api)
    _fail_three_inspections(api, state)

    validate_error(
        api.start_demolition_work_order(
            state["work_order"]["id"],
            make_subrecipient_coordinator_headers(state["project"]["id"]),
        ),
        ApiErrorId.ERR_DEMOLITION_REWORK_LIMIT.value,
        409,
    )

    work_order = validate_success(
        api.get_demolition_work_order(state["work_order"]["id"], ADMIN)
    )
    assert work_order["status"] == "FAILED_INSPECTION"
    assert work_order["failed_inspection_count"] == 3


# ─── The perpetual restriction: one cycle, four refusals, then lockdown ───────

MONITOR_ONE = TEST_USERS["compliance_monitor_headers"]
MONITOR_TWO = TEST_USERS["compliance_monitor_2_headers"]


def _inspect(api, restriction_id, headers=None, **overrides):
    return api.create_monitoring_inspection(
        restriction_id,
        factories.create_monitoring_inspection_payload(restriction_id, **overrides),
        headers or MONITOR_ONE,
    )


def _restriction_in_violation_open(api):
    """RECORDED -> IN_COMPLIANCE -> VIOLATION_OPEN on one 0.34-acre parcel."""
    state = fixtures.parcel_open_space_recorded(
        api,
        record_overrides={
            "recording_reference": "BK-1-PG-1",
            "maintenance_responsible_party": "City of Riverbend Parks",
        },
    )
    restriction = state["restriction"]
    assert restriction["status"] == "RECORDED"
    assert restriction["recorded_on"] == "2026-08-01"
    assert restriction["next_monitoring_due_date"] == "2029-08-01"

    validate_success(
        _inspect(
            api, restriction["id"], inspection_date="2026-08-01", finding="COMPLIANT",
            narrative="open field, no structures",
        ),
        201,
    )
    compliant = validate_success(api.get_deed_restriction(restriction["id"], ADMIN))
    assert compliant["status"] == "IN_COMPLIANCE"
    assert compliant["next_monitoring_due_date"] == "2029-08-01"

    validate_success(
        _inspect(
            api, restriction["id"], inspection_date="2026-08-01",
            finding="PROHIBITED_USE_OBSERVED", prohibited_use_code="FILL_PLACEMENT",
            narrative="imported fill dumped on the pad",
        ),
        201,
    )
    state["restriction"] = validate_success(
        api.get_deed_restriction(restriction["id"], ADMIN)
    )
    assert state["restriction"]["status"] == "VIOLATION_OPEN"
    return state


def test_a_second_different_prohibited_use_and_a_future_visit_are_both_refused(api):
    """The open code is protected, and tomorrow's site visit cannot be recorded today.

    "A `PROHIBITED_USE_OBSERVED` finding recorded against a restriction in
    `RECORDED`, in `IN_COMPLIANCE` or in `CURED` moves it to `VIOLATION_OPEN`, sets
    `open_violation_code` to the inspection's `prohibited_use_code`, sets
    `violation_reported_by_user_id` to the inspection's `inspector_user_id`, and sets
    `corrective_deadline_date` to `inspection_date` plus 90 days while leaving
    `next_monitoring_due_date` untouched."

    "While the restriction is already `VIOLATION_OPEN`, a `PROHIBITED_USE_OBSERVED`
    inspection whose `prohibited_use_code` differs from the restriction's
    `open_violation_code` is `ERR_PROHIBITED_USE_UNRESOLVED`: a second, different
    prohibited use may not be opened while the first is still uncured."

    "The `inspection_date` may not be later than the date part of the logical clock;
    a future-dated site visit is `ERR_FUTURE_DATED_FINDING`, and an
    `inspection_date` falling exactly on the current logical date is accepted."

    Design: Corner/state_machines/deed_restriction_compliance_cycle_ends_in_a_terminated_state_that_locks_out_actions
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = _restriction_in_violation_open(api)
    restriction = state["restriction"]

    assert restriction["open_violation_code"] == "FILL_PLACEMENT"
    assert restriction["violation_reported_by_user_id"] == "cm-1"
    assert restriction["corrective_deadline_date"] == "2026-10-30"
    assert restriction["next_monitoring_due_date"] == "2029-08-01"

    validate_error(
        _inspect(
            api, restriction["id"], inspection_date="2026-08-01",
            finding="PROHIBITED_USE_OBSERVED",
            prohibited_use_code="PERMANENT_STORAGE",
            narrative="containers parked on the lot",
        ),
        ApiErrorId.ERR_PROHIBITED_USE_UNRESOLVED.value,
        409,
    )

    validate_error(
        _inspect(
            api, restriction["id"], inspection_date="2026-08-02",
            finding="PROHIBITED_USE_OBSERVED",
            prohibited_use_code="FILL_PLACEMENT",
            narrative="tomorrow's visit",
        ),
        ApiErrorId.ERR_FUTURE_DATED_FINDING.value,
        422,
    )

    unmoved = validate_success(api.get_deed_restriction(restriction["id"], ADMIN))
    assert unmoved["status"] == "VIOLATION_OPEN"
    assert unmoved["open_violation_code"] == "FILL_PLACEMENT"

    inspections, meta = validate_paginated(
        api.list_monitoring_inspections(
            ADMIN, params={"deed_restriction_id": restriction["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert len(inspections) == 2


def _restriction_cured(api):
    """The same restriction cured by a second monitor after a self-cure is refused."""
    state = _restriction_in_violation_open(api)
    restriction = state["restriction"]

    validate_error(
        api.cure_deed_restriction(
            restriction["id"],
            factories.cure_payload(
                restriction["id"], cure_date="2026-08-01",
                cure_narrative="fill removed",
            ),
            MONITOR_ONE,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )

    state["restriction"] = validate_success(
        api.cure_deed_restriction(
            restriction["id"],
            factories.cure_payload(
                restriction["id"], cure_date="2026-08-01",
                cure_narrative="fill removed and grade restored",
            ),
            MONITOR_TWO,
        )
    )
    return state


def test_the_monitor_who_reported_the_violation_may_not_certify_the_cure(api):
    """A different monitor closes the same violation and the clock re-anchors on the cure.

    "Segregation of duties SoD-3 applies as described in §2.10: the acting
    `X-User-ID` may not equal the restriction's `violation_reported_by_user_id`, so
    the monitor who reported the prohibited use may not be the monitor who signs off
    that it was fixed. A self-cure is `ERR_SEGREGATION_OF_DUTIES`."

    "The cure moves `status` to `CURED`, sets `cured_on` from the request's
    `cure_date`, clears `open_violation_code` and `corrective_deadline_date` to null,
    re-anchors `next_monitoring_due_date` to `cure_date` plus 36 months, and advances
    the restriction's `version` by 1."

    Design: Corner/state_machines/deed_restriction_compliance_cycle_ends_in_a_terminated_state_that_locks_out_actions
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = _restriction_cured(api)

    restriction = state["restriction"]
    assert restriction["status"] == "CURED"
    assert restriction["cured_on"] == "2026-08-01"
    assert restriction["open_violation_code"] is None
    assert restriction["corrective_deadline_date"] is None
    assert restriction["next_monitoring_due_date"] == "2029-08-01"
    assert restriction["violation_reported_by_user_id"] == "cm-1"


def test_termination_needs_the_federal_prefix_and_then_locks_the_restriction(api):
    """A local authorization is refused; the federal one terminates and closes every door.

    "A `ProgramAdministrator` terminates it with a
    `termination_authorization_reference` that must begin with the literal prefix
    `FEMA-OSR-`; a reference that does not begin with that prefix is
    `ERR_TERMINATION_NOT_AUTHORIZED`, and an absent or empty reference is
    `ERR_INVALID_REQUEST`."

    "Termination sets `status` to `TERMINATED`, stores the
    `termination_authorization_reference`, recomputes the project's
    `protected_open_space_acres` so that the parcel's acreage leaves the protected
    total, and advances the restriction's and the project's `version` each by 1."

    "A restriction in `VIOLATION_OPEN` may **not** be terminated - the violation
    must be cured first - and a restriction already `TERMINATED` may not be
    terminated again; both are `ERR_INVALID_RESTRICTION_STATE`."

    Design: Corner/state_machines/deed_restriction_compliance_cycle_ends_in_a_terminated_state_that_locks_out_actions
    """
    api.set_clock("2026-08-01T00:00:00Z")
    state = _restriction_cured(api)
    restriction_id = state["restriction"]["id"]

    validate_error(
        api.terminate_deed_restriction(
            restriction_id,
            factories.terminate_restriction_payload(
                restriction_id,
                termination_authorization_reference="LOCAL-COUNCIL-2026-11",
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_TERMINATION_NOT_AUTHORIZED.value,
        422,
    )

    terminated = validate_success(
        api.terminate_deed_restriction(
            restriction_id,
            factories.terminate_restriction_payload(
                restriction_id,
                termination_authorization_reference="FEMA-OSR-2026-11",
            ),
            ADMIN,
        )
    )
    assert terminated["status"] == "TERMINATED"
    assert terminated["termination_authorization_reference"] == "FEMA-OSR-2026-11"

    project = validate_success(
        api.get_mitigation_project(state["project"]["id"], ADMIN)
    )
    assert float(project["protected_open_space_acres"]) == 0.00

    validate_error(
        api.cure_deed_restriction(
            restriction_id,
            factories.cure_payload(
                restriction_id, cure_date="2026-08-01",
                cure_narrative="after termination",
            ),
            MONITOR_TWO,
        ),
        ApiErrorId.ERR_INVALID_RESTRICTION_STATE.value,
        409,
    )

    validate_error(
        _inspect(
            api, restriction_id, inspection_date="2026-08-01", finding="COMPLIANT",
            narrative="after termination",
        ),
        ApiErrorId.ERR_INVALID_RESTRICTION_STATE.value,
        409,
    )

    validate_error(
        api.terminate_deed_restriction(
            restriction_id,
            factories.terminate_restriction_payload(
                restriction_id,
                termination_authorization_reference="FEMA-OSR-2026-12",
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_RESTRICTION_STATE.value,
        409,
    )

    final = validate_success(api.get_deed_restriction(restriction_id, ADMIN))
    assert final["status"] == "TERMINATED"
