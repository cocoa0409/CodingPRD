"""Non-linear lifecycles and transitive cascades.

The project request-for-information cycle, the four-way appeal decision with its
cyclic remand edge, the applicant's three orthogonal status dimensions, and the
two four-hop causal chains the PRD spells out — obligation and the reporting
sweep.
"""
from test_helpers import (
    ADJUDICATOR_USER_ID,
    GRANTS_OFFICER_USER_ID,
    SECOND_GRANTS_OFFICER_USER_ID,
    SPECIALIST_USER_ID,
    ApiErrorId,
    get_applicant,
    get_disaster,
    get_deobligation,
    get_project,
    issue_rfi,
    make_admin_headers,
    make_adjudicator_headers,
    make_applicant_agent_headers,
    make_grants_officer_headers,
    make_specialist_headers,
    reporting_sweep,
    respond_to_rfi,
    set_clock,
    setup_appeal_under_review,
    setup_obligated_project,
    setup_submitted_project,
    setup_validated_project,
    validate_error,
    validate_paginated,
    validate_success,
)

# The category F wastewater project used by the audit-threshold cascades: a
# reviewed repair basis of exactly 100000000 cents at a 0.75 federal share
# obligates exactly the single-audit threshold of 75000000 cents.
_PLANT_FACILITY = {"name": "Harborview Wastewater Plant", "facility_type": "UTILITY"}
_PLANT_PROJECT = {
    "category": "F",
    "title": "Wastewater plant rebuild",
    "scope_of_work": "Rebuild headworks and clarifiers",
    "estimated_repair_cost_cents": 100000000,
    "mitigation_requested_cents": 0,
}
_PLANT_LINE = {
    "cost_type": "MATERIALS",
    "claimed_cents": 100000000,
    "work_start_at": "2026-06-12T08:00:00Z",
    "work_end_at": "2026-06-20T17:00:00Z",
}


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/project_rfi_cycle_bounded_at_two_rounds
# ---------------------------------------------------------------------------
def _setup_two_completed_rfi_rounds():
    """A project back in UNDER_REVIEW after two full RFI rounds, the second of
    which revised the estimate down to 4800000 cents."""
    scenario = setup_submitted_project(
        disaster_overrides={"declaration_number": "DR-4906", "population": 900000},
        project_overrides={
            "estimated_repair_cost_cents": 5000000,
            "mitigation_requested_cents": 0,
        },
    )
    project_id = scenario["project"]["id"]
    applicant_id = scenario["applicant"]["id"]
    issue_rfi(project_id, "Provide the bid tabulation for the intake contract")
    respond_to_rfi(project_id, applicant_id, "Bid tabulation attached")
    issue_rfi(project_id, "Provide the insurance declarations page")
    scenario["project"] = respond_to_rfi(
        project_id,
        applicant_id,
        "Declarations page attached",
        revised_estimate_cents=4800000,
    )
    return scenario


def test_third_request_for_information_is_refused_once_two_rounds_are_spent(api):
    """PRD §3.3: "The round counter is hard-capped: a project may carry at most two rounds,
    so a request issued while `rfi_round_count` is already 2 is refused with
    `ERR_RFI_ROUNDS_EXHAUSTED`."

    Design: Difficulty/non_linear_state_machine/project_rfi_cycle_bounded_at_two_rounds
    """
    scenario = _setup_two_completed_rfi_rounds()

    response = api.issue_rfi(
        scenario["project"]["id"],
        {"question": "Provide a third clarification"},
        make_specialist_headers(SPECIALIST_USER_ID),
    )

    validate_error(response, ApiErrorId.ERR_RFI_ROUNDS_EXHAUSTED)


def test_refused_third_request_for_information_leaves_the_cycle_where_it_was(api):
    """PRD §3.3: "A `ProgramSpecialist` may issue a request for information, supplying the
    `question` text; this drives `UNDER_REVIEW → RFI_ISSUED`, records the text in
    `last_rfi_question`, raises `rfi_round_count` by 1, and increments the project's
    `version` by 1."
    PRD §3.3: "The applicant closes the loop by answering, supplying the `response`
    narrative and optionally a `revised_estimate_cents`; this drives `RFI_ISSUED →
    UNDER_REVIEW`, and when `revised_estimate_cents` is supplied it **replaces**
    `estimated_repair_cost_cents` outright."
    PRD §3.3: "A project can therefore travel `UNDER_REVIEW → RFI_ISSUED → UNDER_REVIEW`
    twice, and a revision that crosses `small_project_threshold_cents` flips `size_class`
    mid-review, which in turn flips the mitigation cap percentage from 20 percent to 15
    percent or back."

    Design: Difficulty/non_linear_state_machine/project_rfi_cycle_bounded_at_two_rounds
    """
    scenario = _setup_two_completed_rfi_rounds()
    project_id = scenario["project"]["id"]

    api.issue_rfi(
        project_id,
        {"question": "Provide a third clarification"},
        make_specialist_headers(SPECIALIST_USER_ID),
    )

    project = get_project(project_id)
    assert project["rfi_round_count"] == 2, (
        f"Expected 2, got {project['rfi_round_count']} after a refused third request"
    )
    assert project["status"] == "UNDER_REVIEW", (
        f"Expected UNDER_REVIEW, got {project['status']} after the second rfi-response "
        "returned the project through the cycle"
    )


def test_second_rfi_response_revision_reran_the_provisional_cost_variant(api):
    """PRD §3.3: "The applicant closes the loop by answering, supplying the `response`
    narrative and optionally a `revised_estimate_cents`; this drives `RFI_ISSUED →
    UNDER_REVIEW`, and when `revised_estimate_cents` is supplied it **replaces**
    `estimated_repair_cost_cents` outright."
    PRD §3.3: "Because the estimate may have changed, answering re-runs the whole
    `PROVISIONAL` variant — `size_class`, `anticipated_insurance_cents`,
    `mitigation_approved_cents` and `eligible_cost_provisional_cents` are all recomputed
    from the new basis — and increments the project's `version` by 1."

    Design: Difficulty/non_linear_state_machine/project_rfi_cycle_bounded_at_two_rounds
    """
    scenario = _setup_two_completed_rfi_rounds()
    project_id = scenario["project"]["id"]

    api.issue_rfi(
        project_id,
        {"question": "Provide a third clarification"},
        make_specialist_headers(SPECIALIST_USER_ID),
    )

    project = get_project(project_id)
    assert project["estimated_repair_cost_cents"] == 4800000, (
        f"Expected 4800000, got {project['estimated_repair_cost_cents']} after the "
        "second rfi-response replaced the estimate"
    )
    assert project["eligible_cost_provisional_cents"] == 4800000, (
        f"Expected 4800000, got {project['eligible_cost_provisional_cents']} after the "
        "PROVISIONAL variant was re-run on the revised estimate"
    )


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/
#     appeal_four_way_branch_remand_returns_determination_to_proposed
# ---------------------------------------------------------------------------
def _setup_first_level_appeal_on_finalized_deobligation():
    """A project obligated at 3420000 cents by officer-1, reduced by 500000 cents
    on a determination made and finalized by officer-2, with one SUBMITTED
    first-level appeal asking for the whole 500000 cents back."""
    return setup_appeal_under_review(
        500000,
        relief_requested_cents=500000,
        reason="DISALLOWED_COST",
        headers=make_grants_officer_headers(SECOND_GRANTS_OFFICER_USER_ID),
        officer_user_id=SECOND_GRANTS_OFFICER_USER_ID,
        disaster_overrides={"declaration_number": "DR-4907", "population": 900000},
        project_overrides={
            "estimated_repair_cost_cents": 5000000,
            "mitigation_requested_cents": 900000,
        },
        line_items=[{"cost_type": "MATERIALS", "claimed_cents": 3800000}],
    )


def _remand(api, appeal_id):
    return api.decide_appeal(
        appeal_id,
        {
            "decision": "REMAND",
            "decision_rationale": (
                "Record incomplete; return to the grants officer for re-determination"
            ),
        },
        make_adjudicator_headers(ADJUDICATOR_USER_ID),
    )


def test_remand_branch_grants_no_relief_and_stamps_the_adjudicator(api):
    """PRD §3.9: "**`SUBMITTED → REMANDED`** sets `relief_granted_cents` to 0 and sends the
    determination back for re-work."
    PRD §3.9: "All four decisions stamp `decided_at` from the clock, record
    `decided_by_user_id`, and increment the appeal's `version` by 1; beyond that they
    diverge completely."
    PRD §3.9: "The `level` is derived, not supplied: it is `FIRST` when `prior_appeal_id` is
    null and `SECOND` otherwise."

    Design: Difficulty/non_linear_state_machine/appeal_four_way_branch_remand_returns_determination_to_proposed
    """
    scenario = _setup_first_level_appeal_on_finalized_deobligation()

    appeal = validate_success(_remand(api, scenario["appeal"]["id"]))

    assert appeal["status"] == "REMANDED", (
        f"Expected REMANDED, got {appeal['status']} after the REMAND branch"
    )
    assert appeal["relief_granted_cents"] == 0, (
        f"Expected 0, got {appeal['relief_granted_cents']} after a remand"
    )
    assert appeal["level"] == "FIRST", (
        f"Expected FIRST, got {appeal['level']} for an appeal filed without a prior appeal"
    )
    assert appeal["decided_by_user_id"] == ADJUDICATOR_USER_ID, (
        f"Expected {ADJUDICATOR_USER_ID}, got {appeal['decided_by_user_id']} after the decision"
    )


def test_remand_returns_the_determination_from_final_to_proposed(api):
    """PRD §3.9: "A remand runs the determination's `FINAL → PROPOSED` path instead, and it
    is the cyclic edge of this state machine."
    PRD §3.9: "The determination's `status` returns to `PROPOSED`, `finalized_at` is cleared
    to null, `appeal_deadline_at` is cleared to null, and `reversed_cents` stays at 0 —
    nothing was granted."

    Design: Difficulty/non_linear_state_machine/appeal_four_way_branch_remand_returns_determination_to_proposed
    """
    scenario = _setup_first_level_appeal_on_finalized_deobligation()

    _remand(api, scenario["appeal"]["id"])

    deobligation = get_deobligation(scenario["deobligation"]["id"])
    assert deobligation["status"] == "PROPOSED", (
        f"Expected PROPOSED, got {deobligation['status']} after the remand"
    )
    assert deobligation["finalized_at"] is None, (
        f"Expected null, got {deobligation['finalized_at']} after the remand cleared finalization"
    )
    assert deobligation["appeal_deadline_at"] is None, (
        f"Expected null, got {deobligation['appeal_deadline_at']} after the remand cleared "
        "the appeal window"
    )
    assert deobligation["reversed_cents"] == 0, (
        f"Expected 0, got {deobligation['reversed_cents']} — a remand is not a reversal"
    )


def test_remand_restores_the_obligation_ledger_and_re_suspends_the_applicant(api):
    """PRD §3.9: "Because the determination is no longer final, the project's
    `deobligated_cents` falls by the full `amount_cents` and its
    `pending_deobligation_cents` rises by the same amount, so the money returns to the
    obligation ledger while remaining proposed for withdrawal."
    PRD §3.9: "Because `deobligated_cents` moved, the applicant's `total_obligated_cents`,
    `pending_deobligation_cents` and `available_drawdown_cents` are recomputed; because the
    applicant's pending figure is above 0 again, `drawdown_status` becomes `SUSPENDED` and
    the declaration's `suspended_applicant_count` is recomputed; the declaration's
    `total_obligated_cents` is recomputed too."

    Design: Difficulty/non_linear_state_machine/appeal_four_way_branch_remand_returns_determination_to_proposed
    """
    scenario = _setup_first_level_appeal_on_finalized_deobligation()

    _remand(api, scenario["appeal"]["id"])

    project = get_project(scenario["project"]["id"])
    assert project["deobligated_cents"] == 0, (
        f"Expected 0, got {project['deobligated_cents']} after the remand un-finalized "
        "the determination"
    )
    assert project["pending_deobligation_cents"] == 500000, (
        f"Expected 500000, got {project['pending_deobligation_cents']} after the remand"
    )
    assert project["federal_share_obligated_cents"] == 3420000, (
        f"Expected 3420000, got {project['federal_share_obligated_cents']} — the remand "
        "branch does not touch the obligated share"
    )

    applicant = get_applicant(scenario["applicant"]["id"])
    assert applicant["total_obligated_cents"] == 3420000, (
        f"Expected 3420000, got {applicant['total_obligated_cents']} after the remand"
    )
    assert applicant["pending_deobligation_cents"] == 500000, (
        f"Expected 500000, got {applicant['pending_deobligation_cents']} after the remand"
    )
    assert applicant["drawdown_status"] == "SUSPENDED", (
        f"Expected SUSPENDED, got {applicant['drawdown_status']} once the pending "
        "determination came back"
    )


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/
#     applicant_orthogonal_status_dimensions_evolve_independently
# ---------------------------------------------------------------------------
def _setup_delinquent_report_on_enhanced_applicant(api):
    """An applicant obligated at 75000000 cents — hence ENHANCED with a
    SINGLE_AUDIT requirement — whose auto-created 2026-Q3 report has been swept
    DELINQUENT after the clock moved past its due date."""
    scenario = setup_obligated_project(
        disaster_overrides={"declaration_number": "DR-4908"},
        facility_overrides=dict(_PLANT_FACILITY),
        project_overrides=dict(_PLANT_PROJECT),
        line_items=[dict(_PLANT_LINE)],
    )
    set_clock("2026-11-15T00:00:00Z")
    reporting_sweep(scenario["applicant"]["id"])

    reports, _meta = validate_paginated(
        api.list_progress_reports(
            make_admin_headers(), params={"applicant_id": scenario["applicant"]["id"]}
        )
    )
    assert len(reports) == 1, f"Expected exactly one progress report, got {len(reports)}"
    assert reports[0]["status"] == "DELINQUENT", (
        f"Expected DELINQUENT, got {reports[0]['status']} after the sweep"
    )
    scenario["report"] = reports[0]
    return scenario


def _submit_report(api, report_id, applicant_id):
    return api.submit_progress_report(
        report_id,
        {"expenditures_to_date_cents": 41000000, "pct_complete": 55},
        make_applicant_agent_headers(applicant_id),
    )


def test_curing_a_delinquent_report_moves_only_the_drawdown_dimension(api):
    """PRD §3.8: "The submission writes `expenditures_to_date_cents` and `pct_complete`,
    stamps `submitted_at` from the clock, and drives `DUE → SUBMITTED` when the clock is at
    or before `due_at` or `DUE → LATE` when it is past."
    PRD §3.8: "A `DELINQUENT → LATE` filing is the interesting one, because delinquency by
    definition means the deadline has already passed: it writes the same fields, and then,
    because the report left `DELINQUENT`, the applicant's `delinquent_report_count` is
    recomputed; because that count returned to 0 and `pending_deobligation_cents` is also 0,
    `drawdown_status` returns to `ACTIVE`; and because `drawdown_status` became `ACTIVE`, the
    declaration's `suspended_applicant_count` is recomputed."

    Design: Difficulty/non_linear_state_machine/applicant_orthogonal_status_dimensions_evolve_independently
    """
    scenario = _setup_delinquent_report_on_enhanced_applicant(api)
    applicant_id = scenario["applicant"]["id"]

    report = validate_success(_submit_report(api, scenario["report"]["id"], applicant_id))

    assert report["status"] == "LATE", (
        f"Expected LATE, got {report['status']} for a filing past due_at 2026-10-31T00:00:00Z"
    )
    assert report["submitted_at"] is not None and report["submitted_at"].startswith(
        "2026-11-15T00:00:00"
    ), f"Expected submitted_at stamped at 2026-11-15T00:00:00Z, got {report['submitted_at']}"

    applicant = get_applicant(applicant_id)
    assert applicant["delinquent_report_count"] == 0, (
        f"Expected 0, got {applicant['delinquent_report_count']} after the report left DELINQUENT"
    )
    assert applicant["drawdown_status"] == "ACTIVE", (
        f"Expected ACTIVE, got {applicant['drawdown_status']} once the delinquency was cured"
    )


def test_eligibility_and_monitoring_dimensions_do_not_follow_the_drawdown_dimension(api):
    """PRD §3.1: "`eligibility_status` records the statutory determination and, once made, is
    permanent."
    PRD §2.9: "`audit_requirement` becomes `SINGLE_AUDIT` once the applicant's
    `total_obligated_cents` reaches the single-audit threshold and never returns to `NONE`,
    even if a later deobligation drops the ledger below the threshold."
    PRD §2.9: "`monitoring_status` escalates from `STANDARD` to `ENHANCED` on the same event
    and never returns to `STANDARD`."

    Design: Difficulty/non_linear_state_machine/applicant_orthogonal_status_dimensions_evolve_independently
    """
    scenario = _setup_delinquent_report_on_enhanced_applicant(api)
    applicant_id = scenario["applicant"]["id"]

    _submit_report(api, scenario["report"]["id"], applicant_id)

    applicant = get_applicant(applicant_id)
    assert applicant["eligibility_status"] == "ELIGIBLE", (
        f"Expected ELIGIBLE, got {applicant['eligibility_status']} — the ELIGIBILITY "
        "dimension is untouched by a reporting cure"
    )
    assert applicant["monitoring_status"] == "ENHANCED", (
        f"Expected ENHANCED, got {applicant['monitoring_status']} — monitoring never "
        "returns to STANDARD"
    )
    assert applicant["audit_requirement"] == "SINGLE_AUDIT", (
        f"Expected SINGLE_AUDIT, got {applicant['audit_requirement']} — the audit "
        "requirement is a high-water mark"
    )


def test_declaration_counters_track_the_two_dimensions_separately(api):
    """PRD §3.8: "A `DELINQUENT → LATE` filing is the interesting one, because delinquency by
    definition means the deadline has already passed: it writes the same fields, and then,
    because the report left `DELINQUENT`, the applicant's `delinquent_report_count` is
    recomputed; because that count returned to 0 and `pending_deobligation_cents` is also 0,
    `drawdown_status` returns to `ACTIVE`; and because `drawdown_status` became `ACTIVE`, the
    declaration's `suspended_applicant_count` is recomputed."
    PRD §2.9: "`monitoring_status` escalates from `STANDARD` to `ENHANCED` on the same event
    and never returns to `STANDARD`."

    Design: Difficulty/non_linear_state_machine/applicant_orthogonal_status_dimensions_evolve_independently
    """
    scenario = _setup_delinquent_report_on_enhanced_applicant(api)

    _submit_report(api, scenario["report"]["id"], scenario["applicant"]["id"])

    disaster = get_disaster(scenario["disaster"]["id"])
    assert disaster["suspended_applicant_count"] == 0, (
        f"Expected 0, got {disaster['suspended_applicant_count']} once the applicant's "
        "drawdowns went back to ACTIVE"
    )
    assert disaster["enhanced_monitoring_applicant_count"] == 1, (
        f"Expected 1, got {disaster['enhanced_monitoring_applicant_count']} — the "
        "MONITORING dimension did not revert"
    )


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/
#     obligate_cascade_project_to_applicant_to_audit_to_report_to_disaster
# ---------------------------------------------------------------------------
def _setup_validated_plant_project_at_the_audit_threshold():
    """A VALIDATED category F project whose reviewed repair basis of 100000000
    cents obligates to exactly the single-audit threshold."""
    return setup_validated_project(
        disaster_overrides={"declaration_number": "DR-4909"},
        facility_overrides=dict(_PLANT_FACILITY),
        project_overrides=dict(_PLANT_PROJECT),
        line_items=[dict(_PLANT_LINE)],
    )


def test_obligation_moves_the_project_share_and_then_the_applicant_ledger(api):
    """PRD §3.7: "`federal_share_obligated_cents` is the exact integer sum of those two
    independently rounded values; adding the two products first and rounding once is not the
    rule and can differ by a cent."
    PRD §3.7: "Obligation then sets off the system's deepest cascade, and each hop happens
    **because** the previous hop happened."
    PRD §3.7: "Because `federal_share_obligated_cents` moved, the applicant's grant ledger is
    recomputed, refreshing `total_obligated_cents` and `available_drawdown_cents`."

    Design: Difficulty/transitive_cascade/obligate_cascade_project_to_applicant_to_audit_to_report_to_disaster
    """
    scenario = _setup_validated_plant_project_at_the_audit_threshold()

    project = validate_success(
        api.obligate_project(
            scenario["project"]["id"], make_grants_officer_headers(GRANTS_OFFICER_USER_ID)
        )
    )

    assert project["federal_share_obligated_cents"] == 75000000, (
        f"Expected 75000000, got {project['federal_share_obligated_cents']} after obligate"
    )
    assert project["status"] == "OBLIGATED", (
        f"Expected OBLIGATED, got {project['status']} after obligate"
    )

    applicant = get_applicant(scenario["applicant"]["id"])
    assert applicant["total_obligated_cents"] == 75000000, (
        f"Expected 75000000, got {applicant['total_obligated_cents']} after obligate"
    )
    assert applicant["available_drawdown_cents"] == 75000000, (
        f"Expected 75000000, got {applicant['available_drawdown_cents']} after obligate"
    )


def test_ledger_movement_across_the_audit_threshold_escalates_monitoring(api):
    """PRD §3.7: "Because `total_obligated_cents` moved, the single-audit test runs: when it
    now stands at or above 75,000,000 cents — seven hundred fifty thousand dollars of federal
    award — and the applicant's `monitoring_status` is still `STANDARD`, `audit_requirement`
    becomes `SINGLE_AUDIT` and `monitoring_status` escalates `MONITORING:STANDARD →
    MONITORING:ENHANCED`."

    Design: Difficulty/transitive_cascade/obligate_cascade_project_to_applicant_to_audit_to_report_to_disaster
    """
    scenario = _setup_validated_plant_project_at_the_audit_threshold()

    api.obligate_project(
        scenario["project"]["id"], make_grants_officer_headers(GRANTS_OFFICER_USER_ID)
    )

    applicant = get_applicant(scenario["applicant"]["id"])
    assert applicant["audit_requirement"] == "SINGLE_AUDIT", (
        f"Expected SINGLE_AUDIT, got {applicant['audit_requirement']} at a ledger of "
        f"{applicant['total_obligated_cents']} cents"
    )
    assert applicant["monitoring_status"] == "ENHANCED", (
        f"Expected ENHANCED, got {applicant['monitoring_status']} at a ledger of "
        f"{applicant['total_obligated_cents']} cents"
    )
    assert applicant["drawdown_status"] == "ACTIVE", (
        f"Expected ACTIVE, got {applicant['drawdown_status']} — nothing in this cascade "
        "suspends drawdowns"
    )


def test_monitoring_escalation_creates_the_quarterly_report_row(api):
    """PRD §3.7: "Because `monitoring_status` became `ENHANCED`, the system creates one
    progress report row for this applicant in status `DUE`, for the quarter containing the
    current logical clock, with `quarter_label`, `period_start_at`, `period_end_at` and
    `due_at` all derived by the quarter rules of §3.8."
    PRD §3.8: "`period_start_at` is the first instant of that quarter of that year in UTC;
    `period_end_at` is the first instant of the following quarter, and because the period is
    half-open that end instant belongs to the next quarter rather than this one; and `due_at`
    is `period_end_at` plus the reporting grace period of thirty days."
    PRD §3.8: "A report row can be **created by the system** as part of the monitoring
    escalation of §3.7, in which case it is born in status `DUE` with `submitted_at` null and
    no reported data."

    Design: Difficulty/transitive_cascade/obligate_cascade_project_to_applicant_to_audit_to_report_to_disaster
    """
    scenario = _setup_validated_plant_project_at_the_audit_threshold()

    api.obligate_project(
        scenario["project"]["id"], make_grants_officer_headers(GRANTS_OFFICER_USER_ID)
    )

    reports, _meta = validate_paginated(
        api.list_progress_reports(
            make_admin_headers(), params={"applicant_id": scenario["applicant"]["id"]}
        )
    )
    assert len(reports) == 1, (
        f"Expected exactly one progress report created by the escalation, got {len(reports)}"
    )
    report = reports[0]
    assert report["quarter_label"] == "2026-Q3", (
        f"Expected 2026-Q3 for a logical clock at 2026-07-01T00:00:00Z, got "
        f"{report['quarter_label']}"
    )
    assert report["status"] == "DUE", (
        f"Expected DUE, got {report['status']} for a system-created report row"
    )
    assert report["period_start_at"].startswith("2026-07-01T00:00:00"), (
        f"Expected period_start_at 2026-07-01T00:00:00Z, got {report['period_start_at']}"
    )
    assert report["period_end_at"].startswith("2026-10-01T00:00:00"), (
        f"Expected period_end_at 2026-10-01T00:00:00Z, got {report['period_end_at']}"
    )
    assert report["due_at"].startswith("2026-10-31T00:00:00"), (
        f"Expected due_at 2026-10-31T00:00:00Z, got {report['due_at']}"
    )
    assert report["submitted_at"] is None, (
        f"Expected null, got {report['submitted_at']} on a system-created report row"
    )


def test_report_row_existence_refreshes_the_declaration_counters(api):
    """PRD §3.7: "Because that report row now exists, the declaration's
    `enhanced_monitoring_applicant_count` is recomputed; the declaration's
    `total_obligated_cents` is likewise recomputed from its applicants' ledgers."

    Design: Difficulty/transitive_cascade/obligate_cascade_project_to_applicant_to_audit_to_report_to_disaster
    """
    scenario = _setup_validated_plant_project_at_the_audit_threshold()

    api.obligate_project(
        scenario["project"]["id"], make_grants_officer_headers(GRANTS_OFFICER_USER_ID)
    )

    disaster = get_disaster(scenario["disaster"]["id"])
    assert disaster["enhanced_monitoring_applicant_count"] == 1, (
        f"Expected 1, got {disaster['enhanced_monitoring_applicant_count']} after the "
        "escalation created the report row"
    )
    assert disaster["total_obligated_cents"] == 75000000, (
        f"Expected 75000000, got {disaster['total_obligated_cents']} after obligate"
    )


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/
#     reporting_sweep_cascade_report_to_ledger_to_suspension_to_disaster
# ---------------------------------------------------------------------------
def _setup_overdue_report_ready_for_sweep():
    """The end state of the obligation cascade, with the clock moved past the
    2026-Q3 report's due date but before any sweep has run."""
    scenario = setup_obligated_project(
        disaster_overrides={"declaration_number": "DR-4910"},
        facility_overrides=dict(_PLANT_FACILITY),
        project_overrides=dict(_PLANT_PROJECT),
        line_items=[dict(_PLANT_LINE)],
    )
    set_clock("2026-11-15T00:00:00Z")
    return scenario


def _sweep(api, applicant_id):
    return api.reporting_sweep(applicant_id, make_admin_headers())


def _find_q3_report(api, applicant_id):
    reports, _meta = validate_paginated(
        api.list_progress_reports(make_admin_headers(), params={"applicant_id": applicant_id})
    )
    matches = [row for row in reports if row["quarter_label"] == "2026-Q3"]
    assert len(matches) == 1, f"Expected one 2026-Q3 report, got {len(matches)}"
    return matches[0]


def test_reporting_sweep_drives_the_overdue_report_delinquent(api):
    """PRD §3.8: "Every progress report of that applicant whose `status` is `DUE` and whose
    `due_at` is now behind the logical clock is driven `DUE → DELINQUENT`."

    Design: Difficulty/transitive_cascade/reporting_sweep_cascade_report_to_ledger_to_suspension_to_disaster
    """
    scenario = _setup_overdue_report_ready_for_sweep()

    _sweep(api, scenario["applicant"]["id"])

    report = _find_q3_report(api, scenario["applicant"]["id"])
    assert report["status"] == "DELINQUENT", (
        f"Expected DELINQUENT, got {report['status']} for a DUE report past "
        "due_at 2026-10-31T00:00:00Z"
    )
    assert report["submitted_at"] is None, (
        f"Expected null, got {report['submitted_at']} — the sweep files no data"
    )


def test_delinquency_count_suspends_drawdowns_and_then_the_declaration_counter(api):
    """PRD §3.8: "Because a report became `DELINQUENT`, `delinquent_report_count` is
    recomputed; because that count is now above 0, `drawdown_status` becomes `SUSPENDED`;
    because it became `SUSPENDED`, the declaration's `suspended_applicant_count` is
    recomputed."
    PRD §3.8: "`total_obligated_cents` is the sum, over the applicant's projects in status
    `OBLIGATED`, `CLOSEOUT_REQUESTED` or `CLOSED`, of `federal_share_obligated_cents` less
    `deobligated_cents`; projects in `DRAFT`, `UNDER_REVIEW`, `RFI_ISSUED`, `VALIDATED` or
    `DENIED` contribute nothing."

    Design: Difficulty/transitive_cascade/reporting_sweep_cascade_report_to_ledger_to_suspension_to_disaster
    """
    scenario = _setup_overdue_report_ready_for_sweep()
    applicant_id = scenario["applicant"]["id"]

    _sweep(api, applicant_id)

    applicant = get_applicant(applicant_id)
    assert applicant["delinquent_report_count"] == 1, (
        f"Expected 1, got {applicant['delinquent_report_count']} after the sweep"
    )
    assert applicant["drawdown_status"] == "SUSPENDED", (
        f"Expected SUSPENDED, got {applicant['drawdown_status']} with a delinquent report "
        "outstanding"
    )
    assert applicant["total_obligated_cents"] == 75000000, (
        f"Expected 75000000, got {applicant['total_obligated_cents']} — the sweep moves "
        "no money"
    )

    disaster = get_disaster(scenario["disaster"]["id"])
    assert disaster["suspended_applicant_count"] == 1, (
        f"Expected 1, got {disaster['suspended_applicant_count']} after the suspension"
    )


def test_reporting_sweep_rescores_the_monitoring_risk_variant(api):
    """PRD §3.8: "The sweep also re-scores the applicant on the `MONITORING` variant, whatever
    it found: `risk_score_monitoring` is rewritten, `monitoring_scored_at` is stamped from the
    clock, and `risk_tier` is refreshed — and because `monitoring_scored_at` is now non-null,
    `risk_tier` follows the monitoring score from here on rather than the screening score."
    PRD §3.8: "The second component awards 25 points for each of the applicant's `DELINQUENT`
    reports, capped at 100 points, so four delinquent reports max it out."
    PRD §3.8: "The third component measures how much cash the applicant is sitting on relative
    to what it has been awarded: when `total_obligated_cents` is exactly 0 while
    `cash_on_hand_cents` is above 0 — cash held against no live obligation at all, the worst
    possible signal — the component is a flat 100 points; otherwise it is one hundred
    multiplied by `cash_on_hand_cents`, divided by `total_obligated_cents` (treating a zero
    denominator as 1), truncated downward, and then capped at 100."
    PRD §3.1: "The applicant-type component is a fixed point value read from the
    `applicant_type`: 20 points for `LOCAL_GOVERNMENT`, 30 for `TRIBE`, 10 for
    `STATE_AGENCY` and 60 for `PRIVATE_NONPROFIT`."

    Design: Difficulty/transitive_cascade/reporting_sweep_cascade_report_to_ledger_to_suspension_to_disaster
    """
    scenario = _setup_overdue_report_ready_for_sweep()
    applicant_id = scenario["applicant"]["id"]

    _sweep(api, applicant_id)

    applicant = get_applicant(applicant_id)
    assert applicant["risk_score_monitoring"] == 13.50, (
        f"Expected 13.50, got {applicant['risk_score_monitoring']} for one delinquent "
        "report and no cash on hand against a 75000000 cent obligation"
    )
    assert applicant["risk_tier"] == "LOW", (
        f"Expected LOW, got {applicant['risk_tier']} for a monitoring score of "
        f"{applicant['risk_score_monitoring']}"
    )
    assert applicant["monitoring_scored_at"] is not None and applicant[
        "monitoring_scored_at"
    ].startswith("2026-11-15T00:00:00"), (
        "Expected monitoring_scored_at stamped at 2026-11-15T00:00:00Z, got "
        f"{applicant['monitoring_scored_at']}"
    )
