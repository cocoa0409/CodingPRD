"""Guards whose unsatisfied condition lives on a different entity entirely."""

from test_helpers import (
    ADMIN_HEADERS,
    ERR_CYCLE_STAGE_INVALID,
    ERR_OBLIGATIONS_OUTSTANDING,
    ERR_VISA_NOT_APPROVED,
    FINANCE_PAYER_HEADERS,
    get_success_data,
    approve_visa_case,
    assert_money_equals,
    assert_score_equals,
    assign_and_score,
    assign_panelist,
    check_in,
    complete_all_trainings,
    complete_residency,
    create_applicant,
    create_chair,
    create_international_applicant,
    create_panelist,
    create_residency,
    disbursements_for,
    file_visa_case,
    generate_stipend_schedule,
    lock_slate,
    make_conflict_payload,
    make_lifecycle_payload,
    make_score_payload,
    obligations_for,
    pay_disbursement,
    read_application,
    read_cycle,
    read_panel_assignment,
    visa_case_for,
    refresh_application,
    refresh_residency,
    request_visa_docs,
    schedule_residency,
    score_assignment,
    set_clock,
    setup_open_cycle,
    setup_panel_review_cycle,
    submit_visa_docs,
    validate_error,
)

SESSION_START = "2026-11-02"
SESSION_END = "2026-12-27"
EARLY_CLOCK = "2026-06-01T00:00:00Z"
EARLY_CYCLE = {"open_at": "2026-05-01T00:00:00Z"}
CONSULATE_DATE = "2026-09-15"
DOC_LIST = ["PASSPORT", "INVITATION_LETTER", "FUNDING_PROOF"]


def _sponsored_residency_at_filed(api):
    """Every check-in condition met except the sponsorship, which stops at FILED."""
    cycle = setup_open_cycle(api, clock=EARLY_CLOCK, **EARLY_CYCLE)
    residency = create_residency(api, cycle, create_international_applicant(api))
    schedule_residency(api, residency, SESSION_START, 8)

    case = visa_case_for(api, residency.residency_id)
    assert case["status"] == "INITIATED"
    assert case["backlog_days"] == 21
    assert case["filing_deadline_date"] == "2026-07-14"
    assert case["earliest_entry_date"] == "2026-10-03"
    assert case["case_type"] == "B1_SHORT_TERM"
    assert case["days_to_filing_deadline"] == 43

    request_visa_docs(api, case["id"], DOC_LIST)
    submit_visa_docs(api, case["id"], DOC_LIST)
    filed = file_visa_case(api, case["id"], CONSULATE_DATE)
    assert filed["status"] == "FILED"

    complete_all_trainings(api, residency)
    set_clock(api, f"{SESSION_START}T09:00:00Z")
    return residency, filed


def test_a_filed_but_unapproved_sponsorship_blocks_the_check_in(api):
    """Everything on the residency is in order; the visa case alone is not.

    PRD: "And when `visa_required` is true, the residency's visa case must be in
    status `APPROVED`, or the answer is `ERR_VISA_NOT_APPROVED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/residency_checkin_gated_on_visa_case_approval
    """
    residency, filed = _sponsored_residency_at_filed(api)
    ready = refresh_residency(api, residency)
    assert ready["status"] == "SCHEDULED"
    assert ready["session_start_date"] == SESSION_START
    assert ready["compliance_status"] == "CLEARED"
    assert ready["visa_required"] is True
    assert filed["status"] != "APPROVED"

    validate_error(
        api.residency_lifecycle(
            residency.residency_id, make_lifecycle_payload("CHECK_IN"), ADMIN_HEADERS
        ),
        ERR_VISA_NOT_APPROVED,
    )

    unmoved = refresh_residency(api, residency)
    assert unmoved["status"] == "SCHEDULED"
    assert unmoved["version"] == ready["version"]


def test_approving_the_case_unblocks_the_identical_check_in(api):
    """The gate is re-read live, so the second attempt needs no other change.

    PRD: "`APPROVE` drives `FILED → APPROVED` with no further precondition, and
    is what unblocks the residency's check-in described in §3.6."

    Design: Difficulty/cross_entity_state_dependency/residency_checkin_gated_on_visa_case_approval
    """
    residency, filed = _sponsored_residency_at_filed(api)
    validate_error(
        api.residency_lifecycle(
            residency.residency_id, make_lifecycle_payload("CHECK_IN"), ADMIN_HEADERS
        ),
        ERR_VISA_NOT_APPROVED,
    )
    before = refresh_residency(api, residency)

    approved = approve_visa_case(api, filed["id"])
    assert approved["status"] == "APPROVED"
    assert approved["version"] == filed["version"] + 1
    # Approving the sponsorship writes nothing on the residency itself.
    assert refresh_residency(api, residency)["version"] == before["version"]

    entered = check_in(api, residency)
    assert entered["status"] == "IN_RESIDENCE"
    assert entered["version"] == before["version"] + 1


def test_a_domestic_residency_carries_no_sponsorship_gate_at_all(api):
    """With no visa case in play the same calendar admits check-in first time.

    PRD: "Every residency whose `visa_required` is true carries exactly one visa
    case."

    Design: Difficulty/cross_entity_state_dependency/residency_checkin_gated_on_visa_case_approval
    """
    cycle = setup_open_cycle(api, clock=EARLY_CLOCK, **EARLY_CYCLE)
    residency = create_residency(api, cycle, create_applicant(api))
    schedule_residency(api, residency, SESSION_START, 8)
    assert residency.residency["visa_required"] is False
    complete_all_trainings(api, residency)
    set_clock(api, f"{SESSION_START}T09:00:00Z")

    entered = check_in(api, residency)

    assert entered["status"] == "IN_RESIDENCE"


def _third_reviewer_seated(api, lock=True):
    """Two reviewers scored, a third legally seated, and the slate optionally locked."""
    cycle, apps = setup_panel_review_cycle(api, applicant_count=1)
    app = apps[0]
    for _ in range(2):
        assign_and_score(api, app, create_panelist(api), 8, 8, 8, 8)
    latecomer = create_panelist(api)
    seat = assign_panelist(api, app, latecomer)
    assert seat["status"] == "ASSIGNED"
    assert seat["panelist_total_100"] is None

    scored = refresh_application(api, app)
    assert scored["status"] == "SCORED"
    assert scored["scored_panelist_count"] == 2
    assert_score_equals(scored["final_panel_score"], 80.00, "final score")

    if lock:
        lock_slate(api, cycle, create_chair(api))
        assert read_cycle(api, cycle.cycle_id)["status"] == "SLATE_LOCKED"
        assert read_application(api, app.application_id)["status"] == "OFFERED"
    return cycle, app, latecomer, seat


def test_a_locked_slate_freezes_a_reviewer_who_was_legally_seated(api):
    """The seat is sound and the reviewer active; the parent cycle has moved on.

    PRD: "The cycle must be in `PANEL_REVIEW`, the application must be in
    `PANEL_REVIEW` or `SCORED`, the reviewer's `status` must be `ACTIVE`
    (`ERR_PANELIST_RECUSED`), and the assignment must still be in `ASSIGNED`".

    Design: Difficulty/cross_entity_state_dependency/panel_scoring_gated_on_cycle_stage_after_slate_lock
    """
    _cycle, app, latecomer, seat = _third_reviewer_seated(api)

    validate_error(
        api.submit_scores(seat["id"], make_score_payload(9, 9, 9, 9), latecomer.headers),
        ERR_CYCLE_STAGE_INVALID,
    )

    frozen = read_panel_assignment(api, seat["id"])
    assert frozen["status"] == "ASSIGNED"
    assert frozen["panelist_total_100"] is None
    for field in (
        "score_artistic_merit",
        "score_feasibility",
        "score_community_fit",
        "score_technical_readiness",
    ):
        assert frozen[field] is None
    aggregate = read_application(api, app.application_id)
    assert aggregate["scored_panelist_count"] == 2
    assert_score_equals(aggregate["final_panel_score"], 80.00, "final score")


def test_the_freeze_is_stage_wide_and_covers_conflict_declaration_too(api):
    """The reviewer's own escape hatch is shut by the same parent-cycle stage.

    PRD: "The cycle must be in `PANEL_REVIEW` and the assignment must be in
    `ASSIGNED` or `SCORED`; from `CONFLICT_DECLARED` or `VACATED` the answer is
    `ERR_ASSIGNMENT_STATE_INVALID` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/panel_scoring_gated_on_cycle_stage_after_slate_lock
    """
    _cycle, _app, latecomer, seat = _third_reviewer_seated(api)

    validate_error(
        api.declare_conflict(
            seat["id"],
            make_conflict_payload("PRIOR_MENTORSHIP", "taught the applicant in 2019"),
            latecomer.headers,
        ),
        ERR_CYCLE_STAGE_INVALID,
    )

    still_seated = read_panel_assignment(api, seat["id"])
    assert still_seated["status"] == "ASSIGNED"
    assert still_seated["conflict_type"] is None


def test_the_same_scores_are_accepted_before_the_lock(api):
    """The rejected payload was always valid; only the cycle stage changed.

    PRD: "Every review recorded, quorum edge or not, recomputes
    `scored_panelist_count` and `provisional_screening_score` and advances both
    the assignment's and the application's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/panel_scoring_gated_on_cycle_stage_after_slate_lock
    """
    _cycle, app, latecomer, seat = _third_reviewer_seated(api, lock=False)

    recorded = score_assignment(api, seat["id"], latecomer, 9, 9, 9, 9)

    assert recorded["status"] == "SCORED"
    assert_score_equals(recorded["panelist_total_100"], 90.00, "third leg")
    widened = refresh_application(api, app)
    assert widened["scored_panelist_count"] == 3
    assert_score_equals(
        widened["provisional_screening_score"], 83.33, "untrimmed mean of three"
    )


def _residency_with_full_calendar(api):
    """An eight-week residency mid-session with four periods and four obligations."""
    cycle = setup_open_cycle(api)
    residency = create_residency(api, cycle, create_applicant(api))
    schedule_residency(api, residency, SESSION_START, 8)
    generate_stipend_schedule(api, residency)
    complete_all_trainings(api, residency)
    set_clock(api, f"{SESSION_START}T09:00:00Z")
    check_in(api, residency)

    rows = disbursements_for(api, residency.residency_id)
    assert len(rows) == 4
    duties = obligations_for(api, residency.residency_id)
    assert len(duties) == 4
    assert all(duty["status"] == "PENDING" for duty in duties)
    assert all(duty["due_date"] == SESSION_END for duty in duties)
    assert sum(duty["required_count"] for duty in duties) == 5
    return residency, rows, duties


def _pay_the_first_three(api, rows):
    return [
        pay_disbursement(api, rows[index]["id"], date)
        for index, date in enumerate(["2026-11-16", "2026-11-30", "2026-12-14"])
    ]


def test_breached_obligations_block_the_final_payment(api):
    """The last period waits on the engagement ledger, not on its own state.

    PRD: "And when the row being paid carries the highest `period_index` among
    the residency's non-voided schedule, the residency's
    `obligations_breached_count` must be 0: the final payment is withheld until
    the public-engagement commitments are settled, and an outstanding breach is
    `ERR_OBLIGATIONS_OUTSTANDING` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/final_disbursement_payment_gated_on_breached_obligations
    """
    residency, rows, _duties = _residency_with_full_calendar(api)
    _pay_the_first_three(api, rows)

    set_clock(api, f"{SESSION_END}T18:00:00Z")
    finished = complete_residency(api, residency)
    assert finished["status"] == "COMPLETED"
    assert finished["obligations_breached_count"] == 4

    validate_error(
        api.settle_disbursement(
            rows[3]["id"],
            {"action": "PAY", "paid_on_date": "2026-12-28"},
            FINANCE_PAYER_HEADERS,
        ),
        ERR_OBLIGATIONS_OUTSTANDING,
    )

    unpaid = get_success_data(
        api.get_disbursement(rows[3]["id"], FINANCE_PAYER_HEADERS)
    )
    assert unpaid["status"] == "SCHEDULED"
    assert_money_equals(unpaid["withholding_cents"], 0, "unpaid withholding")
    ledger = refresh_residency(api, residency)
    assert_money_equals(ledger["stipend_paid_gross_cents"], 420000, "paid gross")
    assert_money_equals(ledger["withholding_to_date_cents"], 0, "withholding to date")


def test_the_engagement_guard_is_positional_and_spares_earlier_periods(api):
    """Three periods settle while every obligation is still outstanding.

    PRD: "Every disbursement of the same residency with a lower `period_index`
    must already have left `SCHEDULED` — that is, must be `PAID`, `VOIDED` or
    `REVERSED` — so payment runs strictly in order, and a gap is
    `ERR_DISBURSEMENT_OUT_OF_ORDER` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/final_disbursement_payment_gated_on_breached_obligations
    """
    residency, rows, _duties = _residency_with_full_calendar(api)

    paid = _pay_the_first_three(api, rows)

    assert [row["status"] for row in paid] == ["PAID"] * 3
    assert [row["period_index"] for row in paid] == [1, 2, 3]
    outstanding = obligations_for(api, residency.residency_id)
    assert all(duty["status"] == "PENDING" for duty in outstanding)
    assert refresh_residency(api, residency)["obligations_breached_count"] == 0
    assert_money_equals(
        residency.residency["stipend_paid_gross_cents"], 420000, "paid gross"
    )


def test_pending_obligations_never_block_the_final_payment(api):
    """It is the breach, not the existence of the commitments, that gates the money.

    PRD: "`obligations_completed_total` is the sum of `completed_count` over the
    same set; and `obligations_breached_count` counts only the rows in
    `BREACHED`."

    Design: Difficulty/cross_entity_state_dependency/final_disbursement_payment_gated_on_breached_obligations
    """
    residency, rows, _duties = _residency_with_full_calendar(api)
    _pay_the_first_three(api, rows)
    assert refresh_residency(api, residency)["obligations_breached_count"] == 0

    final = pay_disbursement(api, rows[3]["id"], "2026-12-28")

    assert final["status"] == "PAID"
    assert final["period_index"] == 4
    assert_money_equals(final["net_cents"], 140000, "final net")
    assert_money_equals(
        refresh_residency(api, residency)["stipend_paid_gross_cents"],
        560000,
        "paid gross",
    )


