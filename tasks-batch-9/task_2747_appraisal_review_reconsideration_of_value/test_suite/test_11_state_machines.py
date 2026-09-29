"""
State machines: seeded states, sanctioned edges, refused edges and the side effects.

A report carries two independent status dimensions and a desk review carries a third,
so these cases separate what an edge is allowed to move from what it must leave alone.
They walk the seeded pair on intake, the draft-to-submitted handoff and its score, the
two preconditions that gate opening a review, the grid lock that opening installs, the
refusals from draft and from an already-resolved dispute, the guarded flip that waits
for the last open bias flag, the ledger write that assignment performs, and the appeal
that restores a quarantined report from its snapshot.
"""

from test_helpers import (
    CHIEF_APPRAISER_HEADERS,
    COMPLIANCE_HEADERS,
    DESK_REVIEWER_HEADERS,
    DESK_REVIEWER_HEADERS_2,
    DESK_USER_1,
    assert_instant,
    factories as f,
    fixtures as fx,
    make_amc_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# A narrative carrying prohibited terms at positions 1, 2 and 8, so the index is
# three twelve-point contributions and three narrative flags are emitted.
BIASED_NARRATIVE = (
    "Subject sits in a desirable neighborhood with strong pride of ownership "
    "and a family-oriented character."
)


def _author(license_number):
    return {
        "full_name": "Alice Author",
        "license_number": license_number,
        "license_state": "CA",
    }


def _reviewer(license_number):
    return {
        "full_name": "Bob Reviewer",
        "license_number": license_number,
        "license_state": "CA",
    }


def _grid(street):
    """Three closed sales that clear every receipt check."""
    return [
        {
            "street_address": f"1 {street}",
            "sale_price_cents": 39000000,
            "gross_adjustment_cents": 390000,
            "net_adjustment_cents": 390000,
            "distance_miles": 1.0,
            "sale_date": "2026-05-01T00:00:00Z",
        },
        {
            "street_address": f"2 {street}",
            "sale_price_cents": 40000000,
            "gross_adjustment_cents": 400000,
            "net_adjustment_cents": 0,
            "distance_miles": 1.5,
            "sale_date": "2026-06-01T00:00:00Z",
        },
        {
            "street_address": f"3 {street}",
            "sale_price_cents": 41000000,
            "gross_adjustment_cents": 410000,
            "net_adjustment_cents": -410000,
            "distance_miles": 2.0,
            "sale_date": "2026-06-15T00:00:00Z",
        },
    ]


def test_a_delivered_report_is_seeded_in_received_and_not_screened(api):
    """Intake seeds both status dimensions and bumps the loan file's version.

    The report opens on the review dimension in RECEIVED and on the compliance
    dimension in NOT_SCREENED, with the quarantine snapshot, the supersede pointer and
    the current value all absent. The loan file it landed against is still waiting on
    an appraisal, but its optimistic-concurrency version has moved because the delivery
    wrote to it.

    PRD: "A successful delivery is created with `version` 1, with `review_status`
    `RECEIVED` and `bias_screen_status` `NOT_SCREENED`, and with every derived field
    empty: `completeness_score_bps`, `indicated_value_cents`,
    `variance_vs_reported_bps`, `bias_risk_index`, `current_value_cents`, and
    `quarantine_return_status` are all null, while `eligible_comp_count`,
    `closed_comp_count`, `max_gross_adjustment_bps`, `max_net_adjustment_bps`,
    `rule_check_fail_count`, and `rule_check_warn_count` all start at 0."

    PRD: "The delivery increments the loan file's `version` by 1, increments the
    authoring appraiser's `total_appraisal_count`, and recomputes both of that
    appraiser's performance-score variants — because a new report changes the
    denominator of the revision rate, a delivery can move an appraiser's standing all
    on its own."

    Design: Corner/state_machines/initial_state_appraisal_starts_received_and_not_screened
    """
    env = fx.panel_and_loan(
        api,
        amc={"name": "Initial State AMC"},
        appraiser=_author("CA-AL-C101"),
        loan={"loan_number": "LN-2747-C101", "borrower_display_name": "Ida Borrower"},
    )
    loan_version = env["loan"]["version"]

    data = validate_success(
        api.create_appraisal(
            f.appraisal_payload(
                env["loan"]["id"], env["appraiser"]["id"], env["amc"]["id"],
                loan_version,
            ),
            make_amc_headers(env["amc"]["id"]),
        ),
        201,
    )

    assert data["review_status"] == "RECEIVED"
    assert data["bias_screen_status"] == "NOT_SCREENED"
    assert data["quarantine_return_status"] is None
    assert data["supersedes_appraisal_id"] is None
    assert data["current_value_cents"] is None
    assert data["version"] == 1

    loan = fx.read_loan_file(api, env["loan"]["id"])
    assert loan["collateral_status"] == "PENDING_APPRAISAL"
    assert loan["version"] == loan_version + 1


def test_submitting_a_draft_review_writes_the_final_score_and_the_submitter(api):
    """The handoff moves the review, scores it and stamps who did it.

    The review was created in DRAFT with a perfect preliminary score on a clean report.
    Submission moves it to SUBMITTED, writes the final variant, resolves the escalation
    requirement to NONE, and takes the submitter from the request headers rather than
    from the body. The preliminary variant is untouched, and the report's own review
    dimension does not move either, because it already moved when the review opened.

    PRD: "Submission moves `DRAFT → SUBMITTED`, records `submitted_by_user_id` from
    `X-User-ID`, writes `final_quality_score_bps`, and resolves `required_escalation`."

    Design: Corner/state_machines/valid_transition_desk_review_draft_to_submitted_writes_final_score
    """
    env = fx.screened_report(
        api,
        amc={"name": "Clean Baseline AMC"},
        appraiser=_author("CA-AL-C102"),
        loan={"loan_number": "LN-2747-C102", "borrower_display_name": "Jon Borrower"},
        comparables=_grid("Alder Street"),
    )
    draft = fx.open_desk_review(api, env["appraisal"]["id"], reviewer_note="Clean delivery.")
    assert draft["status"] == "DRAFT"
    assert draft["preliminary_quality_score_bps"] == 10000
    assert draft["final_quality_score_bps"] is None

    data = validate_success(
        api.submit_desk_review(
            draft["id"],
            f.desk_review_submit_payload(findings_note="Grid and narrative both clean."),
            DESK_REVIEWER_HEADERS,
        )
    )

    assert data["status"] == "SUBMITTED"
    assert data["final_quality_score_bps"] == 10000
    assert data["required_escalation"] == "NONE"
    assert data["submitted_by_user_id"] == DESK_USER_1
    assert data["preliminary_quality_score_bps"] == 10000
    assert fx.read_appraisal(api, env["appraisal"]["id"])["review_status"] == (
        "IN_DESK_REVIEW"
    )


def test_opening_a_review_before_the_receipt_checks_have_run_is_refused(api):
    """A report still in RECEIVED cannot be taken into review, even once screened.

    The bias screen has run, so the compliance precondition is satisfied, but the
    receipt checks have not, so the earlier rung fires and names the rule checks rather
    than the screen. Nothing is created and nothing moves: no review exists against the
    report, the report stays in RECEIVED at the version the screen left it, and the loan
    file never reaches UNDER_REVIEW.

    PRD: "The receipt checks must already have run, which is to say the appraisal's
    `review_status` must be `RULES_CLEARED` or `RULES_FLAGGED` and its
    `completeness_score_bps` therefore non-null; an appraisal still in `RECEIVED` is
    refused with `ERR_RULE_CHECKS_NOT_RUN` (HTTP 409)."

    Design: Corner/state_machines/precondition_enforcement_desk_review_before_rule_checks_rejected
    """
    env = fx.delivered_report(
        api,
        amc={"name": "Precondition AMC"},
        appraiser=_author("CA-AL-C103"),
        loan={"loan_number": "LN-2747-C103", "borrower_display_name": "Kim Borrower"},
        comparables=[],
    )
    screened = fx.run_bias_screen(api, env["appraisal"]["id"])
    version_after_screen = screened["version"]

    validate_error(
        api.create_desk_review(
            f.desk_review_payload(
                env["appraisal"]["id"], version_after_screen,
                reviewer_note="Premature intake.",
            ),
            DESK_REVIEWER_HEADERS,
        ),
        "ERR_RULE_CHECKS_NOT_RUN", 409,
    )

    _, meta = validate_paginated(
        api.list_desk_reviews(
            DESK_REVIEWER_HEADERS, {"appraisal_id": env["appraisal"]["id"]},
        )
    )
    assert meta["total_count"] == 0

    appraisal = fx.read_appraisal(api, env["appraisal"]["id"])
    assert appraisal["review_status"] == "RECEIVED"
    assert appraisal["version"] == version_after_screen
    assert fx.read_loan_file(api, env["loan"]["id"])["collateral_status"] == (
        "PENDING_APPRAISAL"
    )


def test_opening_a_review_before_the_bias_screen_has_run_is_refused(api):
    """With the checks run but the screen skipped, the later rung fires instead.

    This is the mirror of the previous case and isolates the second precondition: the
    report has been graded, so it sits in RULES_CLEARED, but its compliance dimension is
    still NOT_SCREENED, so the open is refused for the screen and with the screen's own
    status code.

    PRD: "The bias screen must already have run, which is to say `bias_screen_status`
    must be anything other than `NOT_SCREENED`; an unscreened appraisal is refused with
    `ERR_BIAS_SCREEN_REQUIRED` (HTTP 422)."

    Design: Corner/state_machines/precondition_enforcement_desk_review_before_rule_checks_rejected
    """
    env = fx.graded_report(
        api,
        amc={"name": "Precondition Mirror AMC"},
        appraiser=_author("CA-AL-C103B"),
        loan={"loan_number": "LN-2747-C103B", "borrower_display_name": "Kim Borrower"},
        comparables=_grid("Alder Street"),
    )
    appraisal = env["appraisal"]
    assert appraisal["review_status"] == "RULES_CLEARED"
    assert appraisal["bias_screen_status"] == "NOT_SCREENED"

    validate_error(
        api.create_desk_review(
            f.desk_review_payload(
                appraisal["id"], appraisal["version"],
                reviewer_note="Unscreened intake.",
            ),
            DESK_REVIEWER_HEADERS,
        ),
        "ERR_BIAS_SCREEN_REQUIRED", 422,
    )

    _, meta = validate_paginated(
        api.list_desk_reviews(DESK_REVIEWER_HEADERS, {"appraisal_id": appraisal["id"]})
    )
    assert meta["total_count"] == 0
    assert fx.read_appraisal(api, appraisal["id"])["review_status"] == "RULES_CLEARED"


def test_opening_a_review_locks_the_comparable_grid_against_further_rows(api):
    """The open moves three records and shuts the grid.

    The review is created in DRAFT with the preliminary score and the risk tier
    snapshotted off the loan file, the report moves into IN_DESK_REVIEW with its version
    bumped, and the loan file moves to UNDER_REVIEW. A fourth comparable filed after
    that is refused, and the grid still holds exactly the three rows it had.

    PRD: "And it moves the loan file's `collateral_status` to `UNDER_REVIEW`
    (`PENDING_APPRAISAL → UNDER_REVIEW`) while locking the appraisal's comparable grid
    against further additions."

    PRD: "The grid must be unlocked: a comparable may be added only while no desk review
    on this appraisal sits in `DRAFT`, `SUBMITTED`, or `ACCEPTED`, and only while the
    appraisal's `review_status` is none of `VALUE_ACCEPTED`, `VALUE_REVISED`,
    `QUARANTINED`, or `SUPERSEDED`. A locked grid rejects the addition with
    `ERR_APPRAISAL_GRID_LOCKED` (HTTP 409)."

    Design: Corner/state_machines/side_effect_execution_desk_review_create_locks_comparable_grid
    """
    env = fx.screened_report(
        api,
        amc={"name": "Grid Lock AMC"},
        appraiser=_author("CA-AL-C104"),
        loan={"loan_number": "LN-2747-C104", "borrower_display_name": "Lena Borrower"},
        comparables=_grid("Birch Street"),
    )
    version_before_open = env["appraisal"]["version"]

    review = validate_success(
        api.create_desk_review(
            f.desk_review_payload(
                env["appraisal"]["id"], version_before_open,
                reviewer_note="Opening the desk review.",
            ),
            DESK_REVIEWER_HEADERS,
        ),
        201,
    )
    assert review["status"] == "DRAFT"
    assert review["preliminary_quality_score_bps"] == 10000
    assert review["risk_tier_at_review"] == "STANDARD"

    appraisal = fx.read_appraisal(api, env["appraisal"]["id"])
    assert appraisal["review_status"] == "IN_DESK_REVIEW"
    assert appraisal["version"] == version_before_open + 1
    assert fx.read_loan_file(api, env["loan"]["id"])["collateral_status"] == "UNDER_REVIEW"

    validate_error(
        api.create_comparable(
            env["appraisal"]["id"],
            f.comparable_payload(
                "4 Birch Street", sale_price_cents=40500000,
                gross_adjustment_cents=405000, net_adjustment_cents=0,
                distance_miles=1.75, sale_date="2026-06-20T00:00:00Z",
            ),
            make_amc_headers(env["amc"]["id"]),
        ),
        "ERR_APPRAISAL_GRID_LOCKED", 409,
    )

    _, meta = validate_paginated(
        api.list_comparables(env["appraisal"]["id"], DESK_REVIEWER_HEADERS)
    )
    assert meta["total_count"] == 3
    assert fx.read_appraisal(api, env["appraisal"]["id"])["eligible_comp_count"] == 3


def test_deciding_a_review_that_is_still_in_draft_is_refused(api):
    """The decision edge starts at SUBMITTED, so a draft cannot be accepted.

    The acceptance would have been the value-of-record event, so the refusal is checked
    on both sides: the review is still in DRAFT with no final score and no decider, and
    the loan file has no value of record and is still merely under review.

    PRD: "The review must be in `SUBMITTED` or the request is refused with
    `ERR_DESK_REVIEW_NOT_SUBMITTED` (HTTP 409), and the acting `X-User-ID` must differ
    from `submitted_by_user_id` or the request is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/state_machines/invalid_transition_desk_review_decide_from_draft_rejected
    """
    env = fx.open_review(
        api,
        amc={"name": "Invalid Transition AMC"},
        appraiser=_author("CA-AL-C105"),
        loan={"loan_number": "LN-2747-C105", "borrower_display_name": "Mona Borrower"},
        comparables=_grid("Cedar Street"),
    )

    validate_error(
        api.decide_desk_review(
            env["desk_review"]["id"],
            f.desk_review_decide_payload(
                "ACCEPT", decision_note="Deciding before submission.",
            ),
            CHIEF_APPRAISER_HEADERS,
        ),
        "ERR_DESK_REVIEW_NOT_SUBMITTED", 409,
    )

    review = fx.read_desk_review(api, env["desk_review"]["id"])
    assert review["status"] == "DRAFT"
    assert review["final_quality_score_bps"] is None
    assert review["decided_by_user_id"] is None

    assert fx.read_appraisal(api, env["appraisal"]["id"])["review_status"] == (
        "IN_DESK_REVIEW"
    )
    loan = fx.read_loan_file(api, env["loan"]["id"])
    assert loan["collateral_status"] == "UNDER_REVIEW"
    assert loan["value_of_record_appraisal_id"] is None


def test_a_resolved_dispute_refuses_both_a_late_response_and_a_second_resolution(api):
    """Every resolved state is terminal, so neither further call is accepted.

    The dispute was upheld straight from OPEN, which decrements the company's open count
    and leaves the value of record alone. A relay arriving afterwards and a second
    resolution attempting to overturn are both refused with the same code, and the
    dispute keeps the resolution it already has: no position was recorded, no response
    instant was stamped, and the rejected overturn wrote no revision.

    PRD: "Its `response_deadline_at` is snapshotted at creation as the dispute's
    `created_at` plus the company's `sla_response_hours` — a snapshot, so a later change
    to the company's SLA parameter does not move an existing dispute's deadline."

    PRD: "A dispute already in one of the three resolved states cannot be resolved again
    — `ERR_DISPUTE_ALREADY_RESOLVED`."

    Design: Corner/state_machines/terminal_state_lockdown_resolved_dispute_rejects_further_action
    """
    env = fx.delivered_report(
        api,
        amc={"name": "Terminal Dispute AMC"},
        appraiser=_author("CA-AL-C106"),
        loan={"loan_number": "LN-2747-C106", "borrower_display_name": "Nils Borrower"},
        comparables=[],
    )
    dispute = fx.file_dispute(
        api, env["appraisal"]["id"], env["amc"]["id"], env["appraiser"]["id"],
        dispute_basis="ADJUSTMENT_SUPPORT",
        slot_start="2026-08-06T10:00:00Z", slot_end="2026-08-06T11:00:00Z",
    )
    assert_instant(
        dispute["response_deadline_at"], "2026-08-04T00:00:00Z", "response_deadline_at",
    )

    fx.resolve_dispute(
        api, dispute["id"], "UPHELD",
        resolution_note="Adjustment support accepted as delivered.",
    )

    validate_error(
        api.dispute_amc_response(
            dispute["id"],
            f.amc_response_payload(
                "VALUE_SUPPORTED",
                response_summary="Late position filed after resolution.",
            ),
            make_amc_headers(env["amc"]["id"]),
        ),
        "ERR_DISPUTE_ALREADY_RESOLVED", 409,
    )
    validate_error(
        api.resolve_dispute_case(
            dispute["id"],
            f.resolve_dispute_payload(
                "OVERTURNED", resolved_value_cents=40500000,
                resolution_note="Second resolution attempt.",
            ),
            CHIEF_APPRAISER_HEADERS,
        ),
        "ERR_DISPUTE_ALREADY_RESOLVED", 409,
    )

    final = fx.read_dispute_case(api, dispute["id"])
    assert final["status"] == "RESOLVED_UPHELD"
    assert final["resolution"] == "UPHELD"
    assert final["appraiser_position"] is None
    assert final["appraiser_responded_at"] is None

    assert fx.read_appraisal(api, env["appraisal"]["id"])["current_value_cents"] is None
    assert fx.list_value_revisions(api, env["appraisal"]["id"]) == []
    assert fx.read_amc(api, env["amc"]["id"])["open_dispute_count"] == 0


def test_a_second_submission_of_the_same_review_is_refused_and_changes_nothing(api):
    """Resubmission is not a no-op that succeeds; it is a refused transition.

    The review is already in SUBMITTED, and no edge leaves that state on submission, so
    the retry falls to the catch-all state rung. A different reviewer makes the second
    attempt, which is what proves the refusal did not re-stamp the submitter, and the
    findings note and both scores are the first submission's.

    PRD: "The target resource is in a state from which the requested transition exists at
    all — otherwise `ERR_INVALID_STATE` (409). This is the catch-all rung: an operation
    that has its own more specific state error uses that code instead, at the rung listed
    below."

    Design: Corner/state_machines/idempotency_second_desk_review_submit_rejected
    """
    env = fx.open_review(
        api,
        amc={"name": "Idempotency AMC"},
        appraiser=_author("CA-AL-C107"),
        loan={"loan_number": "LN-2747-C107", "borrower_display_name": "Olga Borrower"},
        comparables=_grid("Dogwood Street"),
    )
    fx.submit_desk_review(
        api, env["desk_review"]["id"], findings_note="First submission.",
    )

    validate_error(
        api.submit_desk_review(
            env["desk_review"]["id"],
            f.desk_review_submit_payload(findings_note="Second submission."),
            DESK_REVIEWER_HEADERS_2,
        ),
        "ERR_INVALID_STATE", 409,
    )

    review = fx.read_desk_review(api, env["desk_review"]["id"])
    assert review["status"] == "SUBMITTED"
    assert review["submitted_by_user_id"] == DESK_USER_1
    assert review["findings_note"] == "First submission."
    assert review["final_quality_score_bps"] == 10000
    assert review["required_escalation"] == "NONE"


def test_the_compliance_dimension_flips_only_when_the_last_open_flag_clears(api):
    """Two of three clearances change nothing; the third moves the whole dimension.

    Three prohibited terms produce three narrative flags, each weighted twelve, and an
    index of 36 that lands the dimension in INDICATED. The flags are cleared one at a
    time: the first two leave the report INDICATED, and only the clearance of the last
    open flag moves it to CLEAR. Adjudication never recomputes the index and never
    touches the review dimension, so both stay where the screen left them.

    PRD: "Flags are emitted in a fixed order, and a `CLEAR` outcome does not mean no
    flags — a single matched term scores only 12 and still writes a flag."

    PRD: "Clearing an open flag is the edge `OPEN → CLEARED`, and `CLEARED` is terminal
    for the flag; if it was the *last* flag on the appraisal still in `OPEN`, the
    appraisal's `bias_screen_status` moves `INDICATED → CLEAR`, which is what unblocks
    desk-review acceptance."

    Design: Corner/state_machines/guarded_transition_bias_status_flips_only_on_the_last_open_flag
    """
    env = fx.delivered_report(
        api,
        amc={"name": "Guarded Flag AMC"},
        appraiser=_author("CA-AL-C108"),
        loan={"loan_number": "LN-2747-C108", "borrower_display_name": "Pia Borrower"},
        appraisal={"narrative_text": BIASED_NARRATIVE},
        comparables=[],
    )
    appraisal_id = env["appraisal"]["id"]
    screened = fx.run_bias_screen(api, appraisal_id)
    assert screened["bias_risk_index"] == 36
    assert screened["bias_screen_status"] == "INDICATED"

    flags, meta = validate_paginated(
        api.list_bias_flags(appraisal_id, COMPLIANCE_HEADERS, {"status": "OPEN"})
    )
    assert meta["total_count"] == 3
    assert [row["indicator_code"] for row in flags] == ["TERM_1", "TERM_2", "TERM_8"]
    for row in flags:
        assert row["source"] == "NARRATIVE"
        assert row["severity_weight"] == 12
        assert row["status"] == "OPEN"

    first = fx.adjudicate_flag(
        api, flags[0]["id"], "CLEAR",
        rationale="Term one is quoted from the borrower's own listing.",
    )
    assert first["status"] == "CLEARED"
    assert first["adjudicated_by_user_id"] == "compliance_user_1"
    assert fx.read_appraisal(api, appraisal_id)["bias_screen_status"] == "INDICATED"

    fx.adjudicate_flag(
        api, flags[1]["id"], "CLEAR",
        rationale="Term two describes upkeep, not occupants.",
    )
    assert fx.read_appraisal(api, appraisal_id)["bias_screen_status"] == "INDICATED"

    fx.adjudicate_flag(
        api, flags[2]["id"], "CLEAR",
        rationale="Term three refers to the floor plan.",
    )
    final = fx.read_appraisal(api, appraisal_id)
    assert final["bias_screen_status"] == "CLEAR"
    assert final["bias_risk_index"] == 36
    assert final["review_status"] == "RECEIVED"


def test_staffing_an_order_charges_the_company_and_reserves_the_window(api):
    """Assignment is the moment the money and the counters move.

    The order was created in PENDING_ASSIGNMENT with a due date seventy-two hours after
    the escalation, and at assignment exactly that whole allowance is still left, so no
    rush applies and the bare base fee is below the first discount tier. The company's
    ledger moves from nothing to precisely the order's total, the assignee picks up one
    open assignment, the authoring appraiser's counters are untouched, and the requested
    window is reserved on the assignee.

    PRD: "A successful assignment writes all four cost fields, adds `total_cost_cents`
    to the management company's `ytd_escalation_spend_cents`, increments the assignee's
    `open_assignment_count`, and reserves the inspection window on that appraiser so it
    participates in future conflict checks."

    Design: Corner/state_machines/side_effect_ledger_sync_assignment_adds_cost_to_amc_ytd_spend
    """
    env = fx.escalated_report(
        api,
        with_reviewer=True,
        amc={"name": "Ledger Sync AMC"},
        appraiser=_author("CA-AL-C109"),
        reviewer=_reviewer("CA-BR-C109"),
        loan={
            "loan_number": "LN-2747-C109",
            "risk_tier": "HIGH",
            "borrower_display_name": "Quinn Borrower",
        },
        appraisal={"exhibit_count": 1},
        comparables=_grid("Fir Street"),
    )
    assert env["order"]["status"] == "PENDING_ASSIGNMENT"
    assert_instant(env["order"]["due_at"], "2026-08-04T00:00:00Z", "due_at")
    assert env["desk_review"]["final_quality_score_bps"] == 8086
    assert env["desk_review"]["required_escalation"] == "FIELD_REVIEW"
    assert env["desk_review"]["risk_tier_at_review"] == "HIGH"
    assert fx.read_amc(api, env["amc"]["id"])["ytd_escalation_spend_cents"] == 0

    order = validate_success(
        api.assign_escalation_order(
            env["order"]["id"],
            f.assign_payload(
                env["reviewer"]["id"], "2026-08-02T09:00:00Z", "2026-08-02T12:00:00Z",
            ),
            CHIEF_APPRAISER_HEADERS,
        )
    )

    assert order["status"] == "ASSIGNED"
    assert order["assigned_appraiser_id"] == env["reviewer"]["id"]
    assert order["base_fee_cents"] == 45000
    assert order["rush_surcharge_cents"] == 0
    assert order["discount_pct_bps"] == 0
    assert order["total_cost_cents"] == 45000
    assert_instant(
        order["inspection_window_start"], "2026-08-02T09:00:00Z", "window start",
    )
    assert_instant(
        order["inspection_window_end"], "2026-08-02T12:00:00Z", "window end",
    )

    assert fx.read_amc(api, env["amc"]["id"])["ytd_escalation_spend_cents"] == 45000
    assignee = fx.read_appraiser(api, env["reviewer"]["id"])
    assert assignee["open_assignment_count"] == 1
    assert assignee["completed_assignment_count"] == 0
    assert fx.read_appraiser(api, env["appraiser"]["id"])["open_assignment_count"] == 0


def _revised_then_flagged(api):
    """A report whose value was revised by a completed second appraisal and which still
    carries three open narrative flags, so a substantiation can quarantine it."""
    env = fx.escalation_completed(
        api,
        40600000,
        amc={"name": "Quarantine Lift AMC"},
        appraiser=_author("CA-AL-C110"),
        reviewer=_reviewer("CA-BR-C110"),
        loan={
            "loan_number": "LN-2747-C110",
            "borrower_display_name": "Rosa Borrower",
        },
        appraisal={"narrative_text": BIASED_NARRATIVE},
        comparables=_grid("Gum Street"),
    )
    flags, _ = validate_paginated(
        api.list_bias_flags(
            env["appraisal"]["id"], COMPLIANCE_HEADERS, {"status": "OPEN"}
        )
    )
    env["flags"] = flags
    return env


def test_substantiating_a_flag_snapshots_the_status_before_quarantining(api):
    """The revised status is captured first, then overwritten by the quarantine.

    The report is sitting in VALUE_REVISED after a completed second appraisal. A
    substantiation stores that status in the snapshot field before setting the review
    status to QUARANTINED, moves the compliance dimension to SUBSTANTIATED, drags the
    loan file into quarantine, and charges the authoring appraiser rather than the
    reviewer who produced the new figure.

    PRD: "The appraisal's current `review_status` is first snapshotted into
    `quarantine_return_status`, and only then is `review_status` set to `QUARANTINED`;
    `bias_screen_status` moves `INDICATED → SUBSTANTIATED`; the loan file's
    `collateral_status` is set to `QUARANTINED`; the authoring appraiser's
    `substantiated_bias_count` is incremented and both performance-score variants are
    recomputed; the appraiser's panel standing is re-evaluated against the performance
    cascade of §3.9; and if that cascade lands the appraiser in `PROBATION`,
    `SUSPENDED`, or `REMOVED`, every escalation order currently `ASSIGNED` to that
    appraiser whose escalation type is `SECOND_APPRAISAL` is forced to
    `REASSIGNMENT_REQUIRED`."

    Design: Corner/state_machines/side_effect_conditional_cascade_quarantine_lift_restores_snapshot
    """
    env = _revised_then_flagged(api)
    appraisal_id = env["appraisal"]["id"]

    before = fx.read_appraisal(api, appraisal_id)
    assert before["review_status"] == "VALUE_REVISED"
    assert before["quarantine_return_status"] is None
    assert before["current_value_cents"] == 40600000
    assert fx.read_loan_file(api, env["loan"]["id"])["collateral_status"] == "VALUE_REVISED"

    flag = fx.adjudicate_flag(
        api, env["flags"][0]["id"], "SUBSTANTIATE",
        rationale="The narrative term describes the occupants, not the dwelling.",
    )
    assert flag["status"] == "SUBSTANTIATED"

    after = fx.read_appraisal(api, appraisal_id)
    assert after["review_status"] == "QUARANTINED"
    assert after["quarantine_return_status"] == "VALUE_REVISED"
    assert after["bias_screen_status"] == "SUBSTANTIATED"
    assert fx.read_loan_file(api, env["loan"]["id"])["collateral_status"] == "QUARANTINED"
    assert fx.read_appraiser(api, env["appraiser"]["id"])["substantiated_bias_count"] == 1
    assert fx.read_appraiser(api, env["reviewer"]["id"])["substantiated_bias_count"] == 0


def test_appealing_that_flag_restores_the_snapshot_and_clears_it(api):
    """The appeal walks every side effect of the substantiation back.

    Clearing the substantiated flag is permitted because no other flag on the report is
    substantiated. The review status returns to the snapshotted VALUE_REVISED and the
    snapshot field goes back to null, the compliance dimension lands on the distinct
    CLEARED_ON_REVIEW outcome rather than on a plain clear, the loan file follows the
    restored status out of quarantine, and the authoring appraiser's substantiated count
    is decremented back to nothing.

    PRD: "Clearing a substantiated flag — the edge `SUBSTANTIATED → CLEARED`, which also
    lands the flag in its terminal `CLEARED` state — is the bias **appeal**, permitted
    only when no other flag on that appraisal is still `SUBSTANTIATED`, and it reverses
    the quarantine: `review_status` is restored from `quarantine_return_status` and that
    snapshot field is cleared back to null, `bias_screen_status` moves `SUBSTANTIATED →
    CLEARED_ON_REVIEW`, the loan file's `collateral_status` is restored to the value
    implied by the restored review status — so an appraisal whose snapshot was
    `VALUE_ACCEPTED` returns the loan to `QUARANTINED → VALUE_ACCEPTED` and one whose
    snapshot was `VALUE_REVISED` returns it to `QUARANTINED → VALUE_REVISED` — and the
    authoring appraiser's `substantiated_bias_count` is decremented with both
    performance-score variants recomputed afterwards."

    Design: Corner/state_machines/side_effect_conditional_cascade_quarantine_lift_restores_snapshot
    """
    env = _revised_then_flagged(api)
    appraisal_id = env["appraisal"]["id"]
    flag_id = env["flags"][0]["id"]

    fx.adjudicate_flag(
        api, flag_id, "SUBSTANTIATE",
        rationale="The narrative term describes the occupants, not the dwelling.",
    )
    appealed = fx.adjudicate_flag(
        api, flag_id, "CLEAR",
        rationale="On appeal the term is quoted from the recorded plat description.",
    )

    assert appealed["status"] == "CLEARED"

    restored = fx.read_appraisal(api, appraisal_id)
    assert restored["review_status"] == "VALUE_REVISED"
    assert restored["quarantine_return_status"] is None
    assert restored["bias_screen_status"] == "CLEARED_ON_REVIEW"
    assert fx.read_loan_file(api, env["loan"]["id"])["collateral_status"] == "VALUE_REVISED"
    assert fx.read_appraiser(api, env["appraiser"]["id"])["substantiated_bias_count"] == 0


def test_the_quarantine_cycle_leaves_the_value_ledger_untouched(api):
    """Two adjudications move statuses only; the money and the other flags stay put.

    Across the substantiation and the appeal the value of record never moves and the
    single immutable revision row the completed second appraisal wrote is neither
    rewritten nor joined by another, because adjudicating a flag is not a movement of a
    value of record. The two flags nobody adjudicated are left exactly as the screen
    emitted them.

    PRD: "Every movement of a value of record, whichever channel produced it, writes one
    row to an append-only revision ledger hanging off the appraisal. A ledger row carries
    only `id` and `created_at` as common fields — it is an immutable event, so it has no
    `updated_at` and no `version` — plus the `appraisal_id` whose value moved, a
    `source_type` of `ROV`, `FIELD_REVIEW`, `SECOND_APPRAISAL`, or `DISPUTE`, and a
    `source_ref_id`."

    Design: Corner/state_machines/side_effect_conditional_cascade_quarantine_lift_restores_snapshot
    """
    env = _revised_then_flagged(api)
    appraisal_id = env["appraisal"]["id"]
    flag_id = env["flags"][0]["id"]

    fx.adjudicate_flag(
        api, flag_id, "SUBSTANTIATE",
        rationale="The narrative term describes the occupants, not the dwelling.",
    )
    assert fx.read_appraisal(api, appraisal_id)["current_value_cents"] == 40600000

    fx.adjudicate_flag(
        api, flag_id, "CLEAR",
        rationale="On appeal the term is quoted from the recorded plat description.",
    )
    assert fx.read_appraisal(api, appraisal_id)["current_value_cents"] == 40600000

    revisions = fx.list_value_revisions(api, appraisal_id)
    assert len(revisions) == 1
    assert revisions[0]["new_value_cents"] == 40600000
    assert revisions[0]["source_type"] == "SECOND_APPRAISAL"

    still_open, meta = validate_paginated(
        api.list_bias_flags(appraisal_id, COMPLIANCE_HEADERS, {"status": "OPEN"})
    )
    assert meta["total_count"] == 2
    assert [row["indicator_code"] for row in still_open] == ["TERM_2", "TERM_8"]
