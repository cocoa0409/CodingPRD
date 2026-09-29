"""Initial states, terminal lockdowns and triggers that are not edges at all."""

from test_helpers import (
    ADMIN_HEADERS,
    ERR_COHORT_MINIMUMS_EXCEED_TARGET,
    ERR_OBLIGATION_NOT_PENDING,
    ERR_RESIDENCY_NOT_SCHEDULED,
    ERR_RESIDENCY_STATE_INVALID,
    ERR_VISA_DOCS_INCOMPLETE,
    ERR_VISA_STATE_INVALID,
    FACILITIES_HEADERS,
    VISA_HEADERS,
    add_discipline,
    advance_stage,
    assert_money_equals,
    check_in,
    complete_all_trainings,
    complete_residency,
    create_applicant,
    create_international_applicant,
    create_residency,
    create_studio,
    get_success_data,
    log_obligation_completion,
    make_compliance_payload,
    make_lifecycle_payload,
    make_obligation_progress_payload,
    make_schedule_payload,
    make_studio_assignment_payload,
    make_visa_adjudication_payload,
    make_visa_docs_payload,
    obligation_of_type,
    obligations_for,
    read_cycle,
    read_residency,
    read_visa_case,
    refresh_residency,
    request_visa_docs,
    schedule_residency,
    set_clock,
    setup_draft_cycle,
    setup_open_cycle,
    submit_visa_docs,
    tax_report,
    validate_error,
    validate_paginated,
    visa_case_for,
)

PRINT_SPEC = {
    "code": "PRINT",
    "name": "Printmaking",
    "required_capability_tags": ["PRINT_PRESS"],
    "required_ventilation_class": "NONE",
}


def test_a_cycle_with_no_disciplines_cannot_take_the_opening_edge(api):
    """The empty configuration is refused by the same code as an infeasible one.

    PRD: "A cycle with no disciplines, or whose discipline minimums together
    exceed the cohort target, is refused with
    `ERR_COHORT_MINIMUMS_EXCEED_TARGET` (HTTP 422)."

    Design: Corner/state_machines/cycle_draft_to_open_requires_a_discipline_and_a_feasible_cohort
    """
    cycle = setup_draft_cycle(api)
    assert cycle.cycle["status"] == "DRAFT"
    assert cycle.cycle["cohort_target_size"] == 10

    validate_error(
        api.advance_cycle_stage(cycle.cycle_id, "OPEN", ADMIN_HEADERS),
        ERR_COHORT_MINIMUMS_EXCEED_TARGET,
    )

    held = read_cycle(api, cycle.cycle_id)
    assert held["status"] == "DRAFT"
    assert held["version"] == cycle.cycle["version"]

    add_discipline(api, cycle, cohort_min_slots=6, cohort_max_slots=6)
    opened = advance_stage(api, cycle.cycle_id, "OPEN")

    assert opened["status"] == "OPEN"
    assert opened["version"] == held["version"] + 1


def test_the_constraint_is_the_sum_of_the_minimums_not_any_one_of_them(api):
    """Six and five are each feasible against a target of ten; together they are not.

    PRD: "`DRAFT → OPEN` requires that at least one discipline exists for the
    cycle and that the sum of `cohort_min_slots` across all of the cycle's
    disciplines is no greater than `cohort_target_size`."

    Design: Corner/state_machines/cycle_draft_to_open_requires_a_discipline_and_a_feasible_cohort
    """
    cycle = setup_draft_cycle(api)
    add_discipline(api, cycle, cohort_min_slots=6, cohort_max_slots=6)
    add_discipline(api, cycle, cohort_min_slots=5, cohort_max_slots=5, **PRINT_SPEC)

    validate_error(
        api.advance_cycle_stage(cycle.cycle_id, "OPEN", ADMIN_HEADERS),
        ERR_COHORT_MINIMUMS_EXCEED_TARGET,
    )

    refused = read_cycle(api, cycle.cycle_id)
    assert refused["status"] == "DRAFT"
    assert refused["slots_filled_count"] == 0
    assert refused["slots_open_count"] == 10


def test_the_feasibility_boundary_is_inclusive_and_moves_no_ledger(api):
    """Minimums summing to exactly the target open the cycle and nothing else.

    PRD: "A cycle with no disciplines, or whose discipline minimums together
    exceed the cohort target, is refused with
    `ERR_COHORT_MINIMUMS_EXCEED_TARGET` (HTTP 422). The edge advances the
    cycle's `version` by 1."

    Design: Corner/state_machines/cycle_draft_to_open_requires_a_discipline_and_a_feasible_cohort
    """
    cycle = setup_draft_cycle(api)
    add_discipline(api, cycle, cohort_min_slots=6, cohort_max_slots=6)
    add_discipline(api, cycle, cohort_min_slots=4, cohort_max_slots=4, **PRINT_SPEC)
    before = read_cycle(api, cycle.cycle_id)

    opened = advance_stage(api, cycle.cycle_id, "OPEN")

    assert opened["status"] == "OPEN"
    assert opened["version"] == before["version"] + 1
    assert_money_equals(opened["stipend_committed_cents"], 0, "committed")
    assert_money_equals(opened["stipend_uncommitted_cents"], 20000000, "uncommitted")
    assert opened["slots_filled_count"] == 0
    assert opened["slots_open_count"] == 10
    assert opened["created_at"] == before["created_at"]


def test_the_cohort_guard_is_not_re_evaluated_on_the_following_edge(api):
    """A cycle that opened at the boundary still advances into screening.

    PRD: "`OPEN → SCREENING` requires that no application of the cycle is still
    in status `DRAFT` — everyone has either submitted or been left out. The
    cycle's `version` advances by 1."

    Design: Corner/state_machines/cycle_draft_to_open_requires_a_discipline_and_a_feasible_cohort
    """
    cycle = setup_draft_cycle(api)
    add_discipline(api, cycle, cohort_min_slots=6, cohort_max_slots=6)
    add_discipline(api, cycle, cohort_min_slots=4, cohort_max_slots=4, **PRINT_SPEC)
    opened = advance_stage(api, cycle.cycle_id, "OPEN")

    screening = advance_stage(api, cycle.cycle_id, "SCREENING")

    assert screening["status"] == "SCREENING"
    assert screening["version"] == opened["version"] + 1
    rows, meta = validate_paginated(
        api.list_applications(ADMIN_HEADERS, {"cycle_id": cycle.cycle_id})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_a_new_residency_starts_at_the_origin_of_all_three_axes(api):
    """One response carries the status, the compliance state and the money basis.

    PRD: "A directly created residency starts in `status` `SCHEDULED` and
    `compliance_status` `TRAINING_PENDING`, with `discipline_code` copied from
    the named discipline, `stipend_basis` `PROVISIONAL` and
    `stipend_total_cents` 0."

    Design: Corner/state_machines/residency_starts_scheduled_and_training_pending_on_both_axes
    """
    cycle = setup_open_cycle(api)
    residency = create_residency(api, cycle, create_applicant(api))
    row = residency.residency

    assert row["status"] == "SCHEDULED"
    assert row["compliance_status"] == "TRAINING_PENDING"
    assert row["stipend_basis"] == "PROVISIONAL"
    assert_money_equals(row["stipend_total_cents"], 0, "award at creation")
    # The code is copied from the named discipline, not supplied by the caller.
    assert row["discipline_code"] == "SCULPT"


def test_nothing_schedule_derived_exists_before_the_calendar_is_set(api):
    """Every field the scheduling call provisions is still absent at creation.

    PRD: "**Scheduling** is the moment a residency acquires a calendar, and it
    provisions four different things at once."

    Design: Corner/state_machines/residency_starts_scheduled_and_training_pending_on_both_axes
    """
    cycle = setup_open_cycle(api)
    residency = create_residency(api, cycle, create_applicant(api))
    row = residency.residency

    for field in (
        "session_start_date",
        "session_end_date",
        "session_length_weeks",
        "actual_weeks_in_residence",
    ):
        assert row[field] is None, f"{field} should not exist before scheduling"
    _rows, meta = validate_paginated(
        api.list_obligations(ADMIN_HEADERS, {"residency_id": residency.residency_id})
    )
    assert meta["total_count"] == 0
    assert row["obligations_required_total"] == 0
    assert row["obligations_completed_total"] == 0
    assert row["obligations_breached_count"] == 0


def test_creating_the_residency_takes_the_slot_but_commits_no_money(api):
    """The slot ledger moves at creation while the money ledger waits for a length.

    PRD: "The cycle's `slots_filled_count` and `slots_open_count` are recomputed
    and the cycle's `version` advances by 1."

    Design: Corner/state_machines/residency_starts_scheduled_and_training_pending_on_both_axes
    """
    cycle = setup_open_cycle(api)
    before = read_cycle(api, cycle.cycle_id)
    residency = create_residency(api, cycle, create_applicant(api))

    after = read_cycle(api, cycle.cycle_id)

    assert after["slots_filled_count"] == 1
    assert after["slots_open_count"] == 9
    assert after["version"] == before["version"] + 1
    assert_money_equals(after["stipend_committed_cents"], 0, "committed")
    assert_money_equals(after["stipend_uncommitted_cents"], 20000000, "uncommitted")
    # The domestic artist needs no sponsorship, so no case was opened either.
    assert residency.residency["visa_required"] is False
    assert residency.residency["tax_form_type"] == "W9"
    _cases, case_meta = validate_paginated(
        api.list_visa_cases(ADMIN_HEADERS, {"residency_id": residency.residency_id})
    )
    assert case_meta["total_count"] == 0


SESSION_START = "2026-11-02"
SESSION_END = "2026-12-27"


def _completed_residency(api):
    """An eight-week residency carried all the way to its terminal status."""
    cycle = setup_open_cycle(api)
    residency = create_residency(api, cycle, create_applicant(api))
    schedule_residency(api, residency, SESSION_START, 8)
    cleared = complete_all_trainings(api, residency)
    assert cleared["compliance_status"] == "CLEARED"
    set_clock(api, f"{SESSION_START}T09:00:00Z")
    check_in(api, residency)
    set_clock(api, f"{SESSION_END}T09:00:00Z")
    return residency, complete_residency(api, residency)


def test_the_residency_reaches_its_terminal_status_cleanly(api):
    """Completion settles the calendar figure and leaves the safety axis cleared.

    PRD: "`actual_weeks_in_residence` is set to the residency's
    `session_length_weeks` — the full planned session, because the resident
    stayed to the end."

    Design: Corner/state_machines/completed_residency_refuses_every_further_action_on_both_axes
    """
    _residency, done = _completed_residency(api)

    assert done["status"] == "COMPLETED"
    assert done["actual_weeks_in_residence"] == 8
    assert done["session_length_weeks"] == 8
    assert done["compliance_status"] == "CLEARED"
    assert done["session_end_date"] == SESSION_END


def test_no_lifecycle_action_at_all_is_an_edge_from_the_terminal_status(api):
    """Repeating the arriving action and trying the others fail identically.

    PRD: "The residency's **lifecycle axis** carries five statuses —
    `SCHEDULED`, `IN_RESIDENCE`, `COMPLETED`, `TERMINATED` and `WITHDRAWN` — of
    which the last three are terminal and admit no further action of any kind. A
    lifecycle call names an `action` and may carry a `reason`. An action that is
    not an edge from the residency's current status, including any action at all
    on a terminal residency, is `ERR_RESIDENCY_STATE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/completed_residency_refuses_every_further_action_on_both_axes
    """
    residency, done = _completed_residency(api)

    for action in ("COMPLETE", "CHECK_IN", "TERMINATE"):
        validate_error(
            api.residency_lifecycle(
                residency.residency_id, make_lifecycle_payload(action), ADMIN_HEADERS
            ),
            ERR_RESIDENCY_STATE_INVALID,
        )

    frozen = read_residency(api, residency.residency_id)
    assert frozen["status"] == "COMPLETED"
    assert frozen["version"] == done["version"]


def test_the_lockdown_crosses_to_the_compliance_axis(api):
    """Neither suspension nor reinstatement is available on a finished residency.

    PRD: "A `FacilitiesManager` or `ProgramAdmin` submits an `action` of
    `SUSPEND` or `REINSTATE` with an optional `reason`; in either case the
    residency's lifecycle `status` must be `SCHEDULED` or `IN_RESIDENCE`, and a
    terminal residency is `ERR_RESIDENCY_STATE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/completed_residency_refuses_every_further_action_on_both_axes
    """
    residency, done = _completed_residency(api)

    for action in ("SUSPEND", "REINSTATE"):
        validate_error(
            api.residency_compliance(
                residency.residency_id,
                make_compliance_payload(action),
                FACILITIES_HEADERS,
            ),
            ERR_RESIDENCY_STATE_INVALID,
        )

    held = read_residency(api, residency.residency_id)
    assert held["compliance_status"] == "CLEARED"
    assert held["version"] == done["version"]


def test_facility_writes_are_shut_while_reads_stay_open(api):
    """A studio cannot be booked for a finished residency, but it can still be read.

    PRD: "The residency must not be in a terminal lifecycle status, or
    `ERR_RESIDENCY_STATE_INVALID` (HTTP 409) — a studio may be booked for a
    residency that is `SCHEDULED` or already `IN_RESIDENCE`."

    Design: Corner/state_machines/completed_residency_refuses_every_further_action_on_both_axes
    """
    residency, done = _completed_residency(api)
    studio = create_studio(api)

    validate_error(
        api.create_studio_assignment(
            make_studio_assignment_payload(
                residency.residency_id,
                SESSION_START,
                SESSION_END,
                done["version"],
                studio.studio_id,
            ),
            FACILITIES_HEADERS,
        ),
        ERR_RESIDENCY_STATE_INVALID,
    )

    still_readable = read_residency(api, residency.residency_id)
    assert still_readable["status"] == "COMPLETED"
    report = tax_report(api, residency.residency_id)
    assert report["paid_period_count"] == 0
    idle = get_success_data(api.get_studio(studio.studio_id, FACILITIES_HEADERS))
    assert idle["active_assignment_count"] == 0
    assert idle["reserved_resident_days"] == 0


def test_rescheduling_a_finished_residency_names_the_calendar_not_the_state(api):
    """The schedule endpoint has its own refusal code for the same terminal row.

    PRD: "A `ProgramAdmin` supplies a `session_start_date` and a
    `session_length_weeks`, and the residency must be in `status` `SCHEDULED` — a
    residency that has already checked in, completed, terminated or withdrawn
    cannot be rescheduled, and the answer is `ERR_RESIDENCY_NOT_SCHEDULED` (HTTP
    409)."

    Design: Corner/state_machines/completed_residency_refuses_every_further_action_on_both_axes
    """
    residency, done = _completed_residency(api)

    validate_error(
        api.schedule_residency(
            residency.residency_id, make_schedule_payload("2027-03-01", 4), ADMIN_HEADERS
        ),
        ERR_RESIDENCY_NOT_SCHEDULED,
    )

    unchanged = read_residency(api, residency.residency_id)
    assert unchanged["session_start_date"] == SESSION_START
    assert unchanged["session_length_weeks"] == 8
    assert unchanged["version"] == done["version"]


VISA_SESSION_START = "2027-02-01"
FULL_DOCS = ["PASSPORT", "CV"]


def _initiated_case(api):
    """A sponsored residency whose case has never been asked for a document."""
    cycle = setup_open_cycle(api)
    residency = create_residency(api, cycle, create_international_applicant(api))
    schedule_residency(api, residency, VISA_SESSION_START, 9)
    case = visa_case_for(api, residency.residency_id)
    assert case["status"] == "INITIATED"
    return residency, case


def test_submitting_documents_before_they_were_requested_is_not_an_edge(api):
    """The case is in its opening state, where SUBMIT simply does not exist.

    PRD: "A new case starts with `status` `INITIATED`, `case_type`
    `B1_SHORT_TERM`, `rfe_round` 0, empty `requested_doc_list` and
    `submitted_doc_list`, and `consulate_appointment_date` null."

    Design: Corner/state_machines/visa_case_docs_submit_before_a_request_is_not_an_edge
    """
    _residency, case = _initiated_case(api)
    assert case["rfe_round"] == 0
    assert case["requested_doc_list"] == []
    assert case["submitted_doc_list"] == []
    assert case["consulate_appointment_date"] is None

    validate_error(
        api.visa_docs(
            case["id"], make_visa_docs_payload("SUBMIT", FULL_DOCS), VISA_HEADERS
        ),
        ERR_VISA_STATE_INVALID,
    )

    untouched = read_visa_case(api, case["id"])
    assert untouched["status"] == "INITIATED"
    assert untouched["version"] == case["version"]
    assert untouched["requested_doc_list"] == []
    assert untouched["submitted_doc_list"] == []


def test_every_adjudication_action_is_off_the_graph_from_the_opening_state(api):
    """Filing, approval and denial all sit further down the pipeline than this.

    PRD: "The residency's `status` must be `SCHEDULED`
    (`ERR_RESIDENCY_NOT_SCHEDULED`, HTTP 409), the residency must have a
    `session_start_date` so that the timeline is defined (also
    `ERR_RESIDENCY_NOT_SCHEDULED`, HTTP 409), and the action must be an edge from
    the case's current status (`ERR_VISA_STATE_INVALID`, HTTP 409)."

    Design: Corner/state_machines/visa_case_docs_submit_before_a_request_is_not_an_edge
    """
    residency, case = _initiated_case(api)
    scheduled = refresh_residency(api, residency)
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["session_start_date"] == VISA_SESSION_START

    validate_error(
        api.visa_adjudication(
            case["id"],
            make_visa_adjudication_payload("FILE", consulate_appointment_date="2026-12-01"),
            VISA_HEADERS,
        ),
        ERR_VISA_STATE_INVALID,
    )
    for action in ("APPROVE", "DENY"):
        validate_error(
            api.visa_adjudication(
                case["id"], make_visa_adjudication_payload(action), VISA_HEADERS
            ),
            ERR_VISA_STATE_INVALID,
        )

    held = read_visa_case(api, case["id"])
    assert held["status"] == "INITIATED"
    assert held["version"] == case["version"]
    assert held["consulate_appointment_date"] is None


def test_the_request_opens_the_edge_and_a_short_submission_is_a_different_failure(api):
    """The same SUBMIT payload that was off-graph becomes legal one edge later.

    PRD: "`SUBMIT` drives `DOCS_REQUESTED → DOCS_SUBMITTED` and requires the
    supplied `doc_list` to cover every member of `requested_doc_list`; a short
    submission is `ERR_VISA_DOCS_INCOMPLETE` (HTTP 422), while extra documents
    beyond those requested are harmless."

    Design: Corner/state_machines/visa_case_docs_submit_before_a_request_is_not_an_edge
    """
    _residency, case = _initiated_case(api)

    requested = request_visa_docs(api, case["id"], FULL_DOCS)

    assert requested["status"] == "DOCS_REQUESTED"
    assert requested["requested_doc_list"] == FULL_DOCS
    assert requested["rfe_round"] == 0
    assert requested["version"] == case["version"] + 1

    validate_error(
        api.visa_docs(
            case["id"], make_visa_docs_payload("SUBMIT", ["PASSPORT"]), VISA_HEADERS
        ),
        ERR_VISA_DOCS_INCOMPLETE,
    )
    assert read_visa_case(api, case["id"])["status"] == "DOCS_REQUESTED"

    submitted = submit_visa_docs(api, case["id"], FULL_DOCS)

    assert submitted["status"] == "DOCS_SUBMITTED"
    assert submitted["submitted_doc_list"] == FULL_DOCS
    assert submitted["rfe_round"] == 0


def _scheduled_with_obligations(api):
    """An eight-week residency and its four provisioned engagement rows."""
    cycle = setup_open_cycle(api)
    residency = create_residency(api, cycle, create_applicant(api))
    schedule_residency(api, residency, SESSION_START, 8)
    duties = obligations_for(api, residency.residency_id)
    assert len(duties) == 4
    assert all(duty["status"] == "PENDING" for duty in duties)
    return residency, duties


def test_one_completion_satisfies_a_single_count_obligation(api):
    """The row reaches its required count on the first call and leaves PENDING.

    PRD: "`LOG_COMPLETION` increases `completed_count` by 1 and adds the supplied
    attendance to `total_attendance`; when `completed_count` reaches or passes
    `required_count`, the row moves `PENDING → SATISFIED`."

    Design: Corner/state_machines/logging_a_completion_twice_on_a_single_count_obligation_is_rejected
    """
    residency, _duties = _scheduled_with_obligations(api)
    row = obligation_of_type(api, residency.residency_id, "OPEN_STUDIO")
    assert row["required_count"] == 1
    assert row["completed_count"] == 0
    assert row["total_attendance"] == 0

    logged = log_obligation_completion(api, row["id"], 40)

    assert logged["status"] == "SATISFIED"
    assert logged["completed_count"] == 1
    assert logged["total_attendance"] == 40
    assert logged["version"] == row["version"] + 1
    ledger = refresh_residency(api, residency)
    assert ledger["obligations_required_total"] == 5
    assert ledger["obligations_completed_total"] == 1
    assert ledger["obligations_breached_count"] == 0


def test_a_satisfied_row_refuses_both_progress_actions(api):
    """Repeating the completion and waiving it fail for the same reason.

    PRD: "Either way the obligation must be in `PENDING`; a row already
    `SATISFIED`, `WAIVED` or `BREACHED` is `ERR_OBLIGATION_NOT_PENDING` (HTTP
    409)."

    Design: Corner/state_machines/logging_a_completion_twice_on_a_single_count_obligation_is_rejected
    """
    residency, _duties = _scheduled_with_obligations(api)
    row = obligation_of_type(api, residency.residency_id, "OPEN_STUDIO")
    satisfied = log_obligation_completion(api, row["id"], 40)

    validate_error(
        api.update_obligation_progress(
            row["id"],
            make_obligation_progress_payload("LOG_COMPLETION", attendance=40),
            ADMIN_HEADERS,
        ),
        ERR_OBLIGATION_NOT_PENDING,
    )
    validate_error(
        api.update_obligation_progress(
            row["id"],
            make_obligation_progress_payload("WAIVE", waived_reason="Venue closed"),
            ADMIN_HEADERS,
        ),
        ERR_OBLIGATION_NOT_PENDING,
    )

    frozen = get_success_data(api.get_obligation(row["id"], ADMIN_HEADERS))
    assert frozen["status"] == "SATISFIED"
    assert frozen["completed_count"] == 1
    assert frozen["total_attendance"] == 40
    assert frozen["version"] == satisfied["version"]
    ledger = refresh_residency(api, residency)
    assert ledger["obligations_required_total"] == 5
    assert ledger["obligations_completed_total"] == 1


def test_a_multi_count_row_needs_as_many_calls_as_it_requires(api):
    """The workshop row stays PENDING after one call and accumulates attendance.

    PRD: "An eight-week residency therefore owes two workshops and carries four
    obligation rows totalling five required events; a five-week and a four-week
    residency each owe one workshop and carry four rows totalling four events; a
    residency shorter than four weeks would owe no workshop at all and carry only
    three rows."

    Design: Corner/state_machines/logging_a_completion_twice_on_a_single_count_obligation_is_rejected
    """
    residency, _duties = _scheduled_with_obligations(api)
    workshop = obligation_of_type(api, residency.residency_id, "COMMUNITY_WORKSHOP")
    assert workshop["required_count"] == 2

    first = log_obligation_completion(api, workshop["id"], 40)
    assert first["status"] == "PENDING"
    assert first["completed_count"] == 1
    assert first["total_attendance"] == 40

    second = log_obligation_completion(api, workshop["id"], 15)
    assert second["status"] == "SATISFIED"
    assert second["completed_count"] == 2
    assert second["total_attendance"] == 55

    validate_error(
        api.update_obligation_progress(
            workshop["id"],
            make_obligation_progress_payload("LOG_COMPLETION", attendance=5),
            ADMIN_HEADERS,
        ),
        ERR_OBLIGATION_NOT_PENDING,
    )
    assert refresh_residency(api, residency)["obligations_completed_total"] == 2
