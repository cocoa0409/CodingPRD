"""The payroll audit program: fieldwork rounds, disputes, and underpayment recovery."""

from test_helpers import (
    SECOND_AUDITOR_USER_ID,
    TEST_USERS,
    THIRD_AUDITOR_USER_ID,
    ApiErrorId,
    accrual_for,
    assert_contribution_report,
    assert_payroll_audit,
    audit_finding_payload,
    coverage_month_keys,
    create_payroll_audit_payload,
    granted_coverage_months,
    issue_findings,
    make_auditor_headers,
    make_employer_headers,
    read_audit,
    read_employer,
    read_participant,
    read_report,
    respond_to_audit,
    revoked_coverage_months,
    setup_audit_accepted_without_board_approval,
    setup_audit_in_fieldwork,
    setup_audit_ready_to_finalize,
    setup_employer_with_first_audit_window,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["fund_administrator_headers"]
AUDITOR = TEST_USERS["payroll_auditor_headers"]


def test_each_dispute_returns_the_audit_to_fieldwork_and_clears_its_findings(api):
    """PRD §3.7: "A non-empty findings issue moves the audit from `IN_FIELDWORK`
    to `FINDINGS_ISSUED`, replaces the stored `findings` wholesale with the
    payload, and prices the underpayment."
    PRD §3.7: "`DISPUTE` sends the audit backwards, from `FINDINGS_ISSUED` to
    `IN_FIELDWORK`: `round_count` increases by 1, the stored `findings` is
    cleared to empty, and `unreported_hours_found` and
    `underpayment_principal_cents` both return to 0, so the auditor must go back
    into the field and re-issue."
    PRD §3.7: "For each finding, multiply its `unreported_hours` by the
    employer's `contribution_rate_millicents_per_hour`, multiply again by 10,000
    basis points, divide by ten million, and round half up to whole cents."

    Design: Difficulty/non_linear_state_machine/payroll_audit_dispute_returns_to_fieldwork_cycle
    """
    base = setup_audit_in_fieldwork()
    audit_id = base["audit"]["id"]
    participant_id = base["participant"]["id"]
    employer_id = base["employer"]["id"]

    assert base["audit"]["round_count"] == 1
    assert base["audit"]["status"] == "IN_FIELDWORK"

    first = issue_findings(
        audit_id, [audit_finding_payload(participant_id, "2026-04", 100.00)]
    )
    assert_payroll_audit(first)
    assert first["status"] == "FINDINGS_ISSUED"
    assert first["round_count"] == 1
    assert first["underpayment_principal_cents"] == 82550
    assert first["unreported_hours_found"] == 100.00

    after_first_dispute = respond_to_audit(
        audit_id, employer_id, "DISPUTE", "hours belong to a non-covered classification"
    )
    assert after_first_dispute["status"] == "IN_FIELDWORK"
    assert after_first_dispute["round_count"] == 2
    assert after_first_dispute["findings"] == []
    assert after_first_dispute["underpayment_principal_cents"] == 0
    assert after_first_dispute["unreported_hours_found"] == 0

    second = issue_findings(
        audit_id, [audit_finding_payload(participant_id, "2026-04", 80.00)]
    )
    assert second["status"] == "FINDINGS_ISSUED"
    assert second["underpayment_principal_cents"] == 66040

    after_second_dispute = respond_to_audit(audit_id, employer_id, "DISPUTE")
    assert after_second_dispute["status"] == "IN_FIELDWORK"
    assert after_second_dispute["round_count"] == 3


def test_the_third_round_closes_the_loop_with_the_round_limit(api):
    """PRD §3.7: "The loop is bounded at three fieldwork rounds: a dispute
    submitted when `round_count` already stands at three is refused with
    `ERR_AUDIT_ROUND_LIMIT_REACHED`, leaving the audit in `FINDINGS_ISSUED` with
    the employer's only remaining option being acceptance."
    PRD §3.7: "Findings from earlier rounds are discarded, not accumulated."
    PRD §3.7: "For each finding, multiply its `unreported_hours` by the
    employer's `contribution_rate_millicents_per_hour`, multiply again by 10,000
    basis points, divide by ten million, and round half up to whole cents."

    Design: Difficulty/non_linear_state_machine/payroll_audit_dispute_returns_to_fieldwork_cycle
    """
    base = setup_audit_in_fieldwork()
    audit_id = base["audit"]["id"]
    participant_id = base["participant"]["id"]
    employer_id = base["employer"]["id"]

    issue_findings(audit_id, [audit_finding_payload(participant_id, "2026-04", 100.00)])
    respond_to_audit(audit_id, employer_id, "DISPUTE")
    issue_findings(audit_id, [audit_finding_payload(participant_id, "2026-04", 80.00)])
    respond_to_audit(audit_id, employer_id, "DISPUTE")
    third = issue_findings(
        audit_id, [audit_finding_payload(participant_id, "2026-04", 60.00)]
    )

    assert third["status"] == "FINDINGS_ISSUED"
    assert third["round_count"] == 3
    assert third["underpayment_principal_cents"] == 49530, (
        "only the latest round's 60.00 hours are priced"
    )

    validate_error(
        api.respond_to_audit(
            audit_id, {"response": "DISPUTE"}, make_employer_headers(employer_id)
        ),
        ApiErrorId.ERR_AUDIT_ROUND_LIMIT_REACHED.value,
    )

    unchanged = read_audit(audit_id)
    assert unchanged["status"] == "FINDINGS_ISSUED"
    assert unchanged["round_count"] == 3
    assert unchanged["underpayment_principal_cents"] == 49530


def test_finalizing_mints_a_posted_audit_origin_recovery_report(api):
    """PRD §3.7: "Finalizing moves the audit to the terminal `CLOSED` status and
    runs a four-hop cascade. The first hop mints a recovery report: a
    contribution report with `origin` `AUDIT`, the audited employer, a
    `work_period` equal to the audit's `period_end_month`, `amends_report_id`
    null, `filing_status` already `POSTED` and `payment_status` `UNPAID`, and its
    `due_date` derived as the twentieth of the month following that work period
    exactly as for any other report."
    PRD §3.7: "It carries one contribution line per finding, each with the
    finding's `participant_id`, `hours` equal to the finding's
    `unreported_hours`, `gross_wages_cents` of 0, and `work_classification`
    `JOURNEYMAN`; the audit's `resulting_report_id` is set to that report."
    PRD §3.7: "Alongside those hops, the pension accrual rows for the touched
    plan year are recomputed, and the employer's `cumulative_delinquent_cents` is
    recomputed to include the newly minted, entirely unpaid audit report."

    Design: Difficulty/transitive_cascade/audit_finalize_four_hop_eligibility_cascade
    """
    base = setup_audit_ready_to_finalize()
    assert base["motion"]["status"] == "CARRIED"
    assert read_participant(base["participant"]["id"])["eligibility_status"] == "NOT_ELIGIBLE"

    closed = validate_success(api.finalize_payroll_audit(base["audit"]["id"], ADMIN))

    assert closed["status"] == "CLOSED"
    assert closed["resulting_report_id"] is not None

    recovery = read_report(closed["resulting_report_id"])
    assert_contribution_report(recovery)
    assert recovery["origin"] == "AUDIT"
    assert recovery["work_period"] == "2026-06"
    assert recovery["filing_status"] == "POSTED"
    assert recovery["payment_status"] == "UNPAID"
    assert recovery["amends_report_id"] is None
    assert recovery["due_date"] == "2026-07-20"
    assert recovery["total_contributions_due_cents"] == 82550

    lines, line_meta = validate_paginated(
        api.list_report_lines(recovery["id"], ADMIN)
    )
    assert line_meta["total_count"] == 1
    assert lines[0]["participant_id"] == base["participant"]["id"]
    assert lines[0]["hours"] == 100.00
    assert lines[0]["gross_wages_cents"] == 0
    assert lines[0]["work_classification"] == "JOURNEYMAN"

    employer = read_employer(base["employer"]["id"])
    assert employer["cumulative_delinquent_cents"] == 207448, (
        "124898 from the original filing plus 82550 from the recovery report"
    )


def test_the_recovered_hours_buy_a_coverage_month_and_restore_eligibility(api):
    """PRD §3.7: "The second hop follows from the report being posted: its lines
    enter the eligibility replay for every participant named in the findings,
    rewriting `credited_hours_total` and `hour_bank_hours`. The third hop follows
    from the second: where the replay produced additional whole coverage months,
    new `GRANTED` coverage months are minted and `coverage_through_month`
    advances. The fourth hop follows from the third: because
    `coverage_through_month` has moved past the logical clock's month, a
    participant's `eligibility_status` now reads `ELIGIBLE` where it previously
    read `NOT_ELIGIBLE` — recovered hours restore coverage the worker should have
    had all along."
    PRD §3.4: "The `source` of each minted row is `RECIPROCAL` when the event
    came from a reciprocity transfer; otherwise it is `CURRENT_HOURS` when the
    event's own hours were at least `hours_per_coverage_month`, and `BANK_DRAW`
    when they were not, because in that case the purchase was only possible by
    drawing on hours banked earlier."
    PRD §3.4: "**Step zero wipes.** Every coverage month of this participant
    whose `status` is `GRANTED` is set to `REVOKED`; `hour_bank_hours` is reset
    to 0, `forfeited_hours_total` is reset to 0, and `coverage_through_month` is
    set to null. Revoked rows are never deleted — they remain readable as the
    historical record of grants the fund has withdrawn."

    Design: Difficulty/transitive_cascade/audit_finalize_four_hop_eligibility_cascade
    """
    base = setup_audit_ready_to_finalize()
    participant_id = base["participant"]["id"]

    closed = validate_success(api.finalize_payroll_audit(base["audit"]["id"], ADMIN))
    recovery_report_id = closed["resulting_report_id"]

    participant = read_participant(participant_id)
    assert participant["credited_hours_total"] == 251.30
    assert participant["hour_bank_hours"] == 11.30
    assert participant["coverage_through_month"] == "2026-08"
    assert participant["eligibility_status"] == "ELIGIBLE"

    granted = granted_coverage_months(participant_id)
    assert coverage_month_keys(granted) == ["2026-05", "2026-08"]
    recovered = [row for row in granted if row["coverage_month"] == "2026-08"][0]
    assert recovered["granting_report_id"] == recovery_report_id
    assert recovered["source"] == "BANK_DRAW"
    assert recovered["hours_applied"] == 120

    assert len(revoked_coverage_months(participant_id)) == 1

    accrual = accrual_for(participant_id, 2026)
    assert accrual["hours_credited"] == 251.30
    assert accrual["pension_credit"] == 0.25


def test_an_abutting_audit_window_is_permitted_on_the_same_employer(api):
    """PRD §3.7: "An employer may not be audited twice over the same ground: the
    new window may not intersect the window of any existing audit on that
    employer whose status is anything other than `ABANDONED`, and an intersection
    is refused with `ERR_AUDIT_PERIOD_OVERLAP`. Abutting windows are explicitly
    permitted — an audit that starts the month after another one ends does not
    overlap it."
    PRD §3.7: "The auditor's own opaque identity is captured into
    `auditor_user_id`, and the audit opens with `status` `IN_FIELDWORK`,
    `round_count` at 1, an empty `findings` array, `unreported_hours_found` at 0,
    `underpayment_principal_cents` at 0, and `resulting_report_id` null."

    Design: Difficulty/resource_temporal_overlap/audit_period_closed_interval_intersection_on_employer
    """
    base = setup_employer_with_first_audit_window()

    adjacent = validate_success(
        api.create_payroll_audit(
            create_payroll_audit_payload(base["employer"]["id"], "2026-07", "2026-12"),
            make_auditor_headers(SECOND_AUDITOR_USER_ID),
        ),
        201,
    )

    assert_payroll_audit(adjacent)
    assert adjacent["status"] == "IN_FIELDWORK"
    assert adjacent["round_count"] == 1
    assert adjacent["auditor_user_id"] == SECOND_AUDITOR_USER_ID
    assert adjacent["resulting_report_id"] is None


def test_a_window_sharing_a_single_month_is_refused_as_an_overlap(api):
    """PRD §3.7: "An employer may not be audited twice over the same ground: the
    new window may not intersect the window of any existing audit on that
    employer whose status is anything other than `ABANDONED`, and an intersection
    is refused with `ERR_AUDIT_PERIOD_OVERLAP`. Abutting windows are explicitly
    permitted — an audit that starts the month after another one ends does not
    overlap it."
    PRD §3.7: "Audits may be listed and filtered by `employer_id`, by `status`,
    and by `resulting_report_id`."

    Design: Difficulty/resource_temporal_overlap/audit_period_closed_interval_intersection_on_employer
    """
    base = setup_employer_with_first_audit_window()
    adjacent = validate_success(
        api.create_payroll_audit(
            create_payroll_audit_payload(base["employer"]["id"], "2026-07", "2026-12"),
            make_auditor_headers(SECOND_AUDITOR_USER_ID),
        ),
        201,
    )

    validate_error(
        api.create_payroll_audit(
            create_payroll_audit_payload(base["employer"]["id"], "2026-06", "2026-09"),
            make_auditor_headers(SECOND_AUDITOR_USER_ID),
        ),
        ApiErrorId.ERR_AUDIT_PERIOD_OVERLAP.value,
    )

    rows, meta = validate_paginated(
        api.list_payroll_audits(ADMIN, params={"employer_id": base["employer"]["id"]})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {base["audit"]["id"], adjacent["id"]}


def test_an_empty_findings_array_abandons_the_audit_and_frees_its_months(api):
    """PRD §3.7: "An issue that supplies an **empty** findings array means the
    opposite conclusion: the stored `findings` is set to empty,
    `unreported_hours_found` and `underpayment_principal_cents` both drop to 0,
    and the audit moves from `IN_FIELDWORK` straight to `ABANDONED`, which is
    terminal and produces no recovery report at all."
    PRD §3.7: "Because abandoned audits are excluded from the test, an audit that
    found nothing frees its period for a later look."

    Design: Corner/state_machines/audit_empty_findings_abandons_audit_and_frees_its_period
    """
    base = setup_audit_in_fieldwork()

    abandoned = validate_success(
        api.issue_audit_findings(base["audit"]["id"], {"findings": []}, AUDITOR)
    )

    assert abandoned["status"] == "ABANDONED"
    assert abandoned["unreported_hours_found"] == 0
    assert abandoned["underpayment_principal_cents"] == 0
    assert abandoned["resulting_report_id"] is None

    reopened = validate_success(
        api.create_payroll_audit(
            create_payroll_audit_payload(base["employer"]["id"], "2026-01", "2026-06"),
            make_auditor_headers(THIRD_AUDITOR_USER_ID),
        ),
        201,
    )
    assert reopened["status"] == "IN_FIELDWORK"

    _rows, meta = validate_paginated(
        api.list_payroll_audits(
            ADMIN,
            params={"employer_id": base["employer"]["id"], "status": "ABANDONED"},
        )
    )
    assert meta["total_count"] == 1


def test_finalizing_without_a_carried_settlement_motion_is_refused(api):
    """PRD §3.7: "The joint board must have blessed the settlement: a motion of
    this fund whose `subject_type` is `AUDIT_SETTLEMENT` and whose
    `subject_ref_id` names this very audit must stand in either `CARRIED` or
    `ARBITRATION_CARRIED`, and finalizing without one is refused with
    `ERR_BOARD_APPROVAL_REQUIRED`."
    PRD §3.7: "Finalizing moves the audit to the terminal `CLOSED` status and
    runs a four-hop cascade. The first hop mints a recovery report: a
    contribution report with `origin` `AUDIT`, the audited employer, a
    `work_period` equal to the audit's `period_end_month`, `amends_report_id`
    null, `filing_status` already `POSTED` and `payment_status` `UNPAID`, and its
    `due_date` derived as the twentieth of the month following that work period
    exactly as for any other report."

    Design: Corner/state_machines/audit_finalize_before_board_approval_returns_board_approval_required
    """
    base = setup_audit_accepted_without_board_approval()

    validate_error(
        api.finalize_payroll_audit(base["audit"]["id"], ADMIN),
        ApiErrorId.ERR_BOARD_APPROVAL_REQUIRED.value,
    )

    unchanged = read_audit(base["audit"]["id"])
    assert unchanged["status"] == "EMPLOYER_ACCEPTED"
    assert unchanged["resulting_report_id"] is None

    _rows, meta = validate_paginated(
        api.list_contribution_reports(
            ADMIN, params={"employer_id": base["employer"]["id"], "origin": "AUDIT"}
        )
    )
    assert meta["total_count"] == 0

    assert read_participant(base["participant"]["id"])["credited_hours_total"] == 0


def test_an_employer_response_before_any_findings_is_out_of_state(api):
    """PRD §3.7: "Only the audited employer may respond — an employer acting
    against another employer's audit is turned away with
    `ERR_NOT_RESOURCE_OWNER` — and only while the audit sits in
    `FINDINGS_ISSUED`, any other status yielding `ERR_AUDIT_INVALID_STATE`."
    PRD §3.7: "the audit opens with `status` `IN_FIELDWORK`, `round_count` at 1,
    an empty `findings` array, `unreported_hours_found` at 0,
    `underpayment_principal_cents` at 0, and `resulting_report_id` null."

    Design: Corner/rbac/audit_respond_before_findings_is_rejected_as_audit_invalid_state
    """
    base = setup_audit_in_fieldwork()

    validate_error(
        api.respond_to_audit(
            base["audit"]["id"],
            {"response": "ACCEPT"},
            make_employer_headers(base["employer"]["id"]),
        ),
        ApiErrorId.ERR_AUDIT_INVALID_STATE.value,
    )

    unchanged = read_audit(base["audit"]["id"])
    assert unchanged["status"] == "IN_FIELDWORK"
    assert unchanged["round_count"] == 1
    assert unchanged["findings"] == []
