"""State machines that revisit states, count laps and run on two axes at once."""

from test_helpers import (
    ERR_REVISION_LIMIT_REACHED,
    ERR_VISA_DOCS_INCOMPLETE,
    MAX_REVISION_ROUNDS,
    ADMIN_HEADERS,
    VISA_HEADERS,
    advance_to_screening,
    approve_visa_case,
    check_in,
    create_applicant,
    create_international_applicant,
    create_residency,
    decide_screening,
    file_visa_case,
    make_screening_decision_payload,
    make_visa_docs_payload,
    read_residency,
    read_visa_case,
    record_training,
    refresh_application,
    reinstate_compliance,
    request_visa_docs,
    schedule_residency,
    setup_open_cycle,
    setup_submitted_application,
    set_clock,
    submit_application,
    submit_visa_docs,
    suspend_compliance,
    validate_error,
    visa_case_for,
)

HAZMAT_SCULPT = {"requires_hazmat_review": True}


def _application_in_screening(api):
    """One submitted application sitting in a cycle that has reached screening."""
    cycle = setup_open_cycle(api)
    applicant = create_applicant(api)
    app = setup_submitted_application(api, cycle, applicant)
    advance_to_screening(api, cycle)
    return cycle, app


def test_the_revision_counter_advances_on_the_request_edge_only(api):
    """Handing an application back counts a round; the return trip does not.

    PRD: "It increments `revision_round` by 1 and advances `version` by 1. The
    loop is bounded at two rounds".

    Design: Difficulty/non_linear_state_machine/application_revision_cycle_bounded_at_max_revision_rounds
    """
    _cycle, app = _application_in_screening(api)
    assert refresh_application(api, app)["revision_round"] == 0

    first = decide_screening(api, app, "REQUEST_REVISION")
    assert first["status"] == "REVISION_REQUESTED"
    assert first["revision_round"] == 1

    back = submit_application(api, app)
    assert back["status"] == "SUBMITTED"
    assert back["revision_round"] == 1

    second = decide_screening(api, app, "REQUEST_REVISION")
    assert second["status"] == "REVISION_REQUESTED"
    assert second["revision_round"] == 2

    again = submit_application(api, app)
    assert again["status"] == "SUBMITTED"
    assert again["revision_round"] == MAX_REVISION_ROUNDS


def test_the_third_revision_request_is_refused_without_side_effects(api):
    """The same edge that ran twice is closed on the third attempt.

    PRD: "Because the revision loop is bounded at two rounds, the longest
    possible path through intake is `DRAFT → SUBMITTED → REVISION_REQUESTED →
    SUBMITTED → REVISION_REQUESTED → SUBMITTED` before the application must be
    advanced or rejected."

    Design: Difficulty/non_linear_state_machine/application_revision_cycle_bounded_at_max_revision_rounds
    """
    _cycle, app = _application_in_screening(api)
    for _ in range(2):
        decide_screening(api, app, "REQUEST_REVISION")
        submit_application(api, app)

    validate_error(
        api.decide_screening(
            app.application_id,
            make_screening_decision_payload("REQUEST_REVISION", note="third pass"),
            ADMIN_HEADERS,
        ),
        ERR_REVISION_LIMIT_REACHED,
    )

    unchanged = refresh_application(api, app)
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["revision_round"] == 2


def test_the_cap_closes_one_edge_and_not_the_whole_state(api):
    """From the very state that refused a revision, advancing still works.

    PRD: "`ADVANCE` drives `SUBMITTED → PANEL_REVIEW`, putting the application
    in front of the selection panel, and advances the application's `version`
    by 1."

    Design: Difficulty/non_linear_state_machine/application_revision_cycle_bounded_at_max_revision_rounds
    """
    _cycle, app = _application_in_screening(api)
    for _ in range(2):
        decide_screening(api, app, "REQUEST_REVISION")
        submit_application(api, app)

    validate_error(
        api.decide_screening(
            app.application_id,
            make_screening_decision_payload("REQUEST_REVISION"),
            ADMIN_HEADERS,
        ),
        ERR_REVISION_LIMIT_REACHED,
    )

    advanced = decide_screening(api, app, "ADVANCE")
    assert advanced["status"] == "PANEL_REVIEW"
    assert advanced["revision_round"] == 2


def test_the_safety_axis_clears_while_the_lifecycle_axis_stands_still(api):
    """Two required trainings move compliance without moving the lifecycle.

    PRD: "When, after the append, every member of `required_training_types`
    appears in `completed_training_types`, the compliance axis moves
    `TRAINING_PENDING → CLEARED` in the same request."

    Design: Difficulty/non_linear_state_machine/residency_status_and_compliance_dimensions_advance_independently
    """
    cycle = setup_open_cycle(api, discipline_overrides=HAZMAT_SCULPT)
    applicant = create_applicant(api)
    residency = create_residency(api, cycle, applicant)
    schedule_residency(api, residency, "2026-11-02", 8)
    assert residency.residency["required_training_types"] == [
        "EQUIPMENT_WELDING",
        "SAFETY_ORIENTATION",
    ]

    partial = record_training(api, residency, "SAFETY_ORIENTATION")
    assert partial["compliance_status"] == "TRAINING_PENDING"
    assert partial["status"] == "SCHEDULED"

    cleared = record_training(api, residency, "EQUIPMENT_WELDING")
    assert cleared["compliance_status"] == "CLEARED"
    assert cleared["status"] == "SCHEDULED"
    assert cleared["completed_training_types"] == [
        "EQUIPMENT_WELDING",
        "SAFETY_ORIENTATION",
    ]


def test_suspension_and_reinstatement_oscillate_under_a_fixed_lifecycle(api):
    """The compliance axis has no terminal state and may swing back and forth.

    PRD: "`REINSTATE` drives `SUSPENDED → CLEARED` and requires that every
    member of `required_training_types` still appears in
    `completed_training_types`, or the answer is `ERR_TRAINING_NOT_COMPLETE`
    (HTTP 422)."

    Design: Difficulty/non_linear_state_machine/residency_status_and_compliance_dimensions_advance_independently
    """
    cycle = setup_open_cycle(api, discipline_overrides=HAZMAT_SCULPT)
    applicant = create_applicant(api)
    residency = create_residency(api, cycle, applicant)
    schedule_residency(api, residency, "2026-11-02", 8)
    record_training(api, residency, "SAFETY_ORIENTATION")
    record_training(api, residency, "EQUIPMENT_WELDING")
    set_clock(api, "2026-11-02T09:00:00Z")
    entered = check_in(api, residency)
    assert entered["status"] == "IN_RESIDENCE"
    assert entered["compliance_status"] == "CLEARED"

    suspended = suspend_compliance(
        api, residency, "unattended hot work observed in the shop"
    )
    assert suspended["compliance_status"] == "SUSPENDED"
    assert suspended["status"] == "IN_RESIDENCE"

    restored = reinstate_compliance(api, residency)
    assert restored["compliance_status"] == "CLEARED"
    assert restored["status"] == "IN_RESIDENCE"

    again = suspend_compliance(api, residency, "second lapse in the same week")
    assert again["compliance_status"] == "SUSPENDED"
    assert again["status"] == "IN_RESIDENCE"


def test_reinstatement_never_returns_to_the_pending_clearance_state(api):
    """A resident suspended before clearance cannot be reinstated at all.

    PRD: "a residency suspended out of `TRAINING_PENDING` before its trainings
    were complete cannot be reinstated until they are, and reinstatement always
    lands in `CLEARED`, never back in `TRAINING_PENDING`."

    Design: Difficulty/non_linear_state_machine/residency_status_and_compliance_dimensions_advance_independently
    """
    cycle = setup_open_cycle(api, discipline_overrides=HAZMAT_SCULPT)
    applicant = create_applicant(api)
    residency = create_residency(api, cycle, applicant)
    schedule_residency(api, residency, "2026-11-02", 8)

    early = suspend_compliance(api, residency, "shop access revoked pending induction")
    assert early["compliance_status"] == "SUSPENDED"
    assert early["status"] == "SCHEDULED"

    record_training(api, residency, "SAFETY_ORIENTATION")
    record_training(api, residency, "EQUIPMENT_WELDING")
    reinstated = reinstate_compliance(api, residency)

    assert reinstated["compliance_status"] == "CLEARED"
    assert reinstated["status"] == "SCHEDULED"
    assert read_residency(api, residency.residency_id)["compliance_status"] == "CLEARED"


TWO_DOCS = ["PASSPORT", "INVITATION_LETTER"]
THREE_DOCS = ["PASSPORT", "INVITATION_LETTER", "FUNDING_PROOF"]
FOUR_DOCS = ["PASSPORT", "INVITATION_LETTER", "FUNDING_PROOF", "POLICE_CERTIFICATE"]


def _sponsored_case(api):
    """A French artist's automatically opened case, with a confirmed calendar."""
    cycle = setup_open_cycle(
        api, clock="2026-06-01T00:00:00Z", open_at="2026-05-01T00:00:00Z"
    )
    applicant = create_international_applicant(api)
    residency = create_residency(api, cycle, applicant)
    opened = visa_case_for(api, residency.residency_id)
    schedule_residency(api, residency, "2026-11-02", 8)
    return residency, opened, visa_case_for(api, residency.residency_id)


def test_the_first_document_round_trip_leaves_the_lap_counter_at_zero(api):
    """An opening request is not a re-request, so no round is recorded.

    PRD: "`REQUEST` requires a non-empty `doc_list` and drives `INITIATED →
    DOCS_REQUESTED`, replacing `requested_doc_list` with the supplied list."

    Design: Difficulty/non_linear_state_machine/visa_case_rfe_cycle_increments_round_on_every_pass
    """
    _residency, opened, scheduled = _sponsored_case(api)
    assert opened["status"] == "INITIATED"
    assert opened["rfe_round"] == 0
    assert scheduled["case_type"] == "B1_SHORT_TERM"
    assert scheduled["filing_deadline_date"] == "2026-07-14"
    assert scheduled["earliest_entry_date"] == "2026-10-03"
    assert scheduled["days_to_filing_deadline"] == 43

    requested = request_visa_docs(api, scheduled["id"], TWO_DOCS)
    assert requested["status"] == "DOCS_REQUESTED"
    assert requested["rfe_round"] == 0
    assert requested["requested_doc_list"] == TWO_DOCS

    submitted = submit_visa_docs(api, scheduled["id"], TWO_DOCS)
    assert submitted["status"] == "DOCS_SUBMITTED"
    assert submitted["rfe_round"] == 0
    assert submitted["submitted_doc_list"] == TWO_DOCS


def test_every_re_request_after_a_submission_counts_another_lap(api):
    """The reverse edge out of a submission is what advances the lap counter.

    PRD: "`REQUEST` is also an edge **out of** `DOCS_SUBMITTED`, closing a
    cycle: re-requesting after a submission drives `DOCS_SUBMITTED →
    DOCS_REQUESTED`, replaces `requested_doc_list` with the new list and
    increases `rfe_round` by 1."

    Design: Difficulty/non_linear_state_machine/visa_case_rfe_cycle_increments_round_on_every_pass
    """
    _residency, _opened, case = _sponsored_case(api)
    case_id = case["id"]
    request_visa_docs(api, case_id, TWO_DOCS)
    submit_visa_docs(api, case_id, TWO_DOCS)

    second_request = request_visa_docs(api, case_id, THREE_DOCS)
    assert second_request["status"] == "DOCS_REQUESTED"
    assert second_request["rfe_round"] == 1
    assert second_request["requested_doc_list"] == THREE_DOCS

    second_submit = submit_visa_docs(api, case_id, THREE_DOCS)
    assert second_submit["status"] == "DOCS_SUBMITTED"
    assert second_submit["rfe_round"] == 1

    third_request = request_visa_docs(api, case_id, FOUR_DOCS)
    assert third_request["status"] == "DOCS_REQUESTED"
    assert third_request["rfe_round"] == 2


def test_the_lap_counter_has_no_ceiling(api):
    """A fourth and fifth pass are accepted where a revision loop would stop.

    PRD: "Those request-for-evidence rounds are unbounded — unlike the
    application revision loop of §3.3, which stops at two — so `rfe_round`
    simply counts how many times the coordinator has gone back to the
    resident."

    Design: Difficulty/non_linear_state_machine/visa_case_rfe_cycle_increments_round_on_every_pass
    """
    _residency, _opened, case = _sponsored_case(api)
    case_id = case["id"]
    request_visa_docs(api, case_id, TWO_DOCS)
    submit_visa_docs(api, case_id, TWO_DOCS)
    for lap in range(1, 5):
        laps_request = request_visa_docs(api, case_id, TWO_DOCS)
        assert laps_request["rfe_round"] == lap
        assert laps_request["status"] == "DOCS_REQUESTED"
        submit_visa_docs(api, case_id, TWO_DOCS)

    final = read_visa_case(api, case_id)
    assert final["rfe_round"] == 4
    assert final["status"] == "DOCS_SUBMITTED"


def test_the_submission_guard_strengthens_with_the_lap(api):
    """A payload that satisfied an earlier lap is short on the later one.

    PRD: "`SUBMIT` drives `DOCS_REQUESTED → DOCS_SUBMITTED` and requires the
    supplied `doc_list` to cover every member of `requested_doc_list`; a short
    submission is `ERR_VISA_DOCS_INCOMPLETE` (HTTP 422), while extra documents
    beyond those requested are harmless."

    Design: Difficulty/non_linear_state_machine/visa_case_rfe_cycle_increments_round_on_every_pass
    """
    _residency, _opened, case = _sponsored_case(api)
    case_id = case["id"]
    request_visa_docs(api, case_id, TWO_DOCS)
    submit_visa_docs(api, case_id, TWO_DOCS)
    request_visa_docs(api, case_id, THREE_DOCS)
    submit_visa_docs(api, case_id, THREE_DOCS)
    request_visa_docs(api, case_id, FOUR_DOCS)

    validate_error(
        api.visa_docs(
            case_id, make_visa_docs_payload("SUBMIT", THREE_DOCS), VISA_HEADERS
        ),
        ERR_VISA_DOCS_INCOMPLETE,
    )

    stalled = read_visa_case(api, case_id)
    assert stalled["status"] == "DOCS_REQUESTED"
    assert stalled["rfe_round"] == 2


def test_the_loop_is_left_rather_than_exhausted(api):
    """Filing stays reachable from a submission no matter how many laps ran.

    PRD: "`APPROVE` drives `FILED → APPROVED` with no further precondition, and
    is what unblocks the residency's check-in described in §3.6."

    Design: Difficulty/non_linear_state_machine/visa_case_rfe_cycle_increments_round_on_every_pass
    """
    _residency, _opened, case = _sponsored_case(api)
    case_id = case["id"]
    request_visa_docs(api, case_id, TWO_DOCS)
    submit_visa_docs(api, case_id, TWO_DOCS)
    request_visa_docs(api, case_id, THREE_DOCS)
    submit_visa_docs(api, case_id, THREE_DOCS)

    filed = file_visa_case(api, case_id, "2026-09-01")
    assert filed["status"] == "FILED"
    assert filed["rfe_round"] == 1
    assert filed["consulate_appointment_date"] == "2026-09-01"

    approved = approve_visa_case(api, case_id)
    assert approved["status"] == "APPROVED"
    assert approved["rfe_round"] == 1
