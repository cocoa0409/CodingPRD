"""State-transition behaviour: branch asymmetry, cycles, locks and terminality."""
from test_helpers import (
    ADJUDICATOR_USER_ID,
    ApiErrorId,
    GRANTS_OFFICER_USER_ID,
    SECOND_GRANTS_OFFICER_USER_ID,
    SPECIALIST_USER_ID,
    certify_closeout,
    close_obligations,
    create_applicant,
    create_contract,
    create_cost_line_item,
    create_damage_site,
    create_drawdown,
    create_facility,
    create_progress_report,
    decide_appeal,
    get_applicant,
    get_appeal,
    get_contract,
    get_cost_line_item,
    get_deobligation,
    get_disaster,
    get_drawdown,
    get_facility,
    get_progress_report,
    get_project,
    get_success_data,
    is_iso8601_timestamp,
    make_admin_headers,
    make_adjudicator_headers,
    make_applicant_agent_headers,
    make_grants_officer_headers,
    make_specialist_headers,
    review_cost_line_item,
    review_procurement,
    screen_facility,
    setup_appeal_under_review,
    setup_closeout_requested_project,
    setup_declaration,
    setup_drafted_project,
    setup_obligated_project,
    setup_submitted_project,
    setup_validated_project,
    validate_error,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Damage assessment site: the two adjudication branches
# ---------------------------------------------------------------------------


def test_damage_site_validate_transition_writes_validated_loss(api):
    """PRD §3.2: "`REPORTED → VALIDATED` requires a supplied `validated_loss_cents` of
    at least 0, writes it onto the site, sets `validation_status` to `VALIDATED`, and
    then refreshes the declaration-level indicator, incrementing both the site's
    `version` and the declaration's `version` by 1."

    PRD §3.2: "`per_capita_impact_cents` becomes `total_validated_loss_cents` divided by
    the declaration's `population`, truncated downward to a whole number of cents."

    PRD §3.2: "`indicator_met` becomes true when `per_capita_impact_cents` is at least
    the statewide per-capita indicator of 189 cents — one dollar and eighty-nine cents
    of validated loss per resident — and false otherwise."

    Design: Corner/state_machines/damage_site_validate_transition_writes_validated_loss
    """
    scenario = setup_declaration(declaration_number="DR-4942")
    disaster_id = scenario["disaster"]["id"]
    applicant = create_applicant(disaster_id)
    facility = create_facility(applicant["id"])
    site = create_damage_site(
        facility["id"], applicant["id"], reported_loss_cents=1_200_000
    )

    disaster_before = get_disaster(disaster_id)

    data = validate_success(
        api.validate_damage_site(
            site["id"],
            {"decision": "VALIDATE", "validated_loss_cents": 1_000_000},
            make_specialist_headers(SPECIALIST_USER_ID),
        )
    )

    assert data["validation_status"] == "VALIDATED", (
        f"Expected VALIDATED, got {data['validation_status']} after the validate branch"
    )
    assert data["validated_loss_cents"] == 1_000_000, (
        f"Expected validated_loss_cents 1000000, got {data['validated_loss_cents']}"
    )
    assert data["rejection_reason"] is None, (
        f"Expected rejection_reason null on the validate branch, got {data['rejection_reason']}"
    )
    assert data["version"] == 2, (
        f"Expected damage site version 2, got {data['version']} after validate"
    )

    disaster = get_disaster(disaster_id)
    assert disaster["total_validated_loss_cents"] == 1_000_000, (
        "Expected total_validated_loss_cents 1000000, got "
        f"{disaster['total_validated_loss_cents']} after validate"
    )
    assert disaster["per_capita_impact_cents"] == 0, (
        "Expected per_capita_impact_cents 0 (floor of 1000000 / 2000000), got "
        f"{disaster['per_capita_impact_cents']}"
    )
    assert disaster["indicator_met"] is False, (
        f"Expected indicator_met false (0 below 189), got {disaster['indicator_met']}"
    )
    assert disaster["version"] == disaster_before["version"] + 1, (
        f"Expected declaration version {disaster_before['version'] + 1}, got "
        f"{disaster['version']} after the indicator refresh"
    )


def test_damage_site_reject_branch_leaves_indicator_untouched(api):
    """PRD §3.2: "`REPORTED → REJECTED` requires a supplied `rejection_reason`, records
    it, forces `validated_loss_cents` to 0 — where it stays forever — sets
    `validation_status` to `REJECTED`, and increments only the site's `version` by 1:
    the declaration's aggregates are **not** recomputed and the declaration's `version`
    does not move."

    Design: Corner/state_machines/damage_site_reject_branch_leaves_indicator_untouched
    """
    scenario = setup_declaration(declaration_number="DR-4943")
    disaster_id = scenario["disaster"]["id"]
    applicant = create_applicant(disaster_id)
    facility = create_facility(applicant["id"])
    site = create_damage_site(
        facility["id"], applicant["id"], reported_loss_cents=1_200_000
    )

    disaster_before = get_disaster(disaster_id)

    data = validate_success(
        api.validate_damage_site(
            site["id"],
            {
                "decision": "REJECT",
                "rejection_reason": "Reported damage predates the incident period",
            },
            make_specialist_headers(SPECIALIST_USER_ID),
        )
    )

    assert data["validation_status"] == "REJECTED", (
        f"Expected REJECTED, got {data['validation_status']} after the reject branch"
    )
    assert data["validated_loss_cents"] == 0, (
        f"Expected validated_loss_cents forced to 0, got {data['validated_loss_cents']}"
    )
    assert data["rejection_reason"] == "Reported damage predates the incident period", (
        f"Expected the supplied rejection_reason, got {data['rejection_reason']}"
    )

    disaster = get_disaster(disaster_id)
    assert disaster["total_validated_loss_cents"] == 0, (
        "Expected total_validated_loss_cents 0 after a reject, got "
        f"{disaster['total_validated_loss_cents']}"
    )
    assert disaster["per_capita_impact_cents"] == 0, (
        f"Expected per_capita_impact_cents 0, got {disaster['per_capita_impact_cents']}"
    )
    assert disaster["indicator_met"] is False, (
        f"Expected indicator_met false, got {disaster['indicator_met']}"
    )
    assert disaster["version"] == disaster_before["version"], (
        "The reject branch must not move the declaration's version: expected "
        f"{disaster_before['version']}, got {disaster['version']}"
    )


# ---------------------------------------------------------------------------
# Once-only actions
# ---------------------------------------------------------------------------


class TestOnceOnlyActions:
    """Each of these transitions may be taken exactly once."""

    def test_second_damage_site_adjudication_rejected(self, api):
        """PRD §3.2: "A site whose `validation_status` is already `VALIDATED` or
        `REJECTED` cannot be adjudicated again and yields
        `ERR_DAMAGE_SITE_ALREADY_ADJUDICATED` — both of those states are terminal."

        Design: Corner/state_machines/once_only_actions_reject_their_second_invocation
        """
        scenario = setup_declaration(
            clock="2026-07-15T00:00:00Z", declaration_number="DR-4944"
        )
        applicant = create_applicant(scenario["disaster"]["id"])
        facility = create_facility(applicant["id"])
        site = create_damage_site(
            facility["id"], applicant["id"], reported_loss_cents=600_000
        )
        validate_success(
            api.validate_damage_site(
                site["id"],
                {"decision": "VALIDATE", "validated_loss_cents": 500_000},
                make_specialist_headers(SPECIALIST_USER_ID),
            )
        )

        validate_error(
            api.validate_damage_site(
                site["id"],
                {"decision": "REJECT", "rejection_reason": "Second look"},
                make_specialist_headers(SPECIALIST_USER_ID),
            ),
            ApiErrorId.ERR_DAMAGE_SITE_ALREADY_ADJUDICATED,
        )

        after = get_success_data(api.get_damage_site(site["id"], make_admin_headers()))
        assert after["validation_status"] == "VALIDATED", (
            "Expected the site to stay VALIDATED, got "
            f"{after['validation_status']} after the refused second adjudication"
        )
        assert after["validated_loss_cents"] == 500_000, (
            f"Expected validated_loss_cents 500000, got {after['validated_loss_cents']}"
        )

    def test_second_procurement_review_rejected(self, api):
        """PRD §3.4: "Procurement compliance review is a `ProgramSpecialist` capability
        that drives the contract out of `PENDING_REVIEW` exactly once — a second attempt
        on a contract already `COMPLIANT` or `NONCOMPLIANT` is refused with
        `ERR_CONTRACT_ALREADY_REVIEWED`."

        Design: Corner/state_machines/once_only_actions_reject_their_second_invocation
        """
        scenario = setup_declaration(
            clock="2026-07-15T00:00:00Z", declaration_number="DR-4944"
        )
        applicant = create_applicant(scenario["disaster"]["id"])
        contract = create_contract(
            applicant["id"],
            vendor_name="Bayline Contractors",
            contract_type="SMALL_PURCHASE",
            award_amount_cents=1_000_000,
            awarded_at="2026-06-15T00:00:00Z",
            debarment_check_completed=True,
        )
        reviewed = review_procurement(contract["id"])
        assert reviewed["procurement_status"] == "COMPLIANT", (
            f"Setup expected COMPLIANT, got {reviewed['procurement_status']}"
        )

        validate_error(
            api.review_procurement(
                contract["id"], make_specialist_headers(SPECIALIST_USER_ID)
            ),
            ApiErrorId.ERR_CONTRACT_ALREADY_REVIEWED,
        )

        after = get_contract(contract["id"])
        assert after["procurement_status"] == "COMPLIANT", (
            "Expected procurement_status to stay COMPLIANT, got "
            f"{after['procurement_status']}"
        )
        assert after["version"] == 2, (
            f"Expected contract version to stay 2, got {after['version']}"
        )

    def test_second_progress_report_submission_rejected(self, api):
        """PRD §3.8: "Submission is admissible only against a row in `DUE` or
        `DELINQUENT`; a row already `SUBMITTED` or `LATE` yields
        `ERR_REPORT_ALREADY_SUBMITTED`."

        Design: Corner/state_machines/once_only_actions_reject_their_second_invocation
        """
        scenario = setup_declaration(
            clock="2026-07-15T00:00:00Z", declaration_number="DR-4944"
        )
        applicant = create_applicant(scenario["disaster"]["id"])
        report = create_progress_report(
            applicant["id"],
            "2026-Q2",
            expenditures_to_date_cents=250_000,
            pct_complete=40,
        )
        assert report["status"] == "SUBMITTED", (
            f"Setup expected a SUBMITTED report, got {report['status']}"
        )

        validate_error(
            api.submit_progress_report(
                report["id"],
                {"expenditures_to_date_cents": 300_000, "pct_complete": 55},
                make_applicant_agent_headers(applicant["id"]),
            ),
            ApiErrorId.ERR_REPORT_ALREADY_SUBMITTED,
        )

        after = get_progress_report(report["id"])
        assert after["expenditures_to_date_cents"] == 250_000, (
            "Expected expenditures_to_date_cents to stay 250000, got "
            f"{after['expenditures_to_date_cents']}"
        )
        assert after["pct_complete"] == 40, (
            f"Expected pct_complete to stay 40, got {after['pct_complete']}"
        )

    def test_second_close_obligations_rejected(self, api):
        """PRD §3.1: "Closing sets `status` to `OBLIGATION_CLOSED` and increments the
        declaration's `version` by 1; a second attempt on an already-closed declaration
        yields `ERR_DISASTER_INVALID_STATE`."

        Design: Corner/state_machines/once_only_actions_reject_their_second_invocation
        """
        scenario = setup_declaration(
            clock="2026-07-15T00:00:00Z", declaration_number="DR-4944"
        )
        disaster_id = scenario["disaster"]["id"]
        closed = close_obligations(disaster_id)
        assert closed["status"] == "OBLIGATION_CLOSED", (
            f"Setup expected OBLIGATION_CLOSED, got {closed['status']}"
        )

        validate_error(
            api.close_obligations(disaster_id, make_admin_headers()),
            ApiErrorId.ERR_DISASTER_INVALID_STATE,
        )

        after = get_disaster(disaster_id)
        assert after["status"] == "OBLIGATION_CLOSED", (
            f"Expected the declaration to stay OBLIGATION_CLOSED, got {after['status']}"
        )


# ---------------------------------------------------------------------------
# Drawdown: refund reachability and the reject branch
# ---------------------------------------------------------------------------


def test_drawdown_refund_before_disbursement_rejected(api):
    """PRD §3.8: "It carries a single `refund_cents` amount, which may not exceed the
    drawdown's `approved_cents` (`ERR_REFUND_EXCEEDS_DRAWDOWN`), and it is admissible
    only on a drawdown in `PAID`; a refund attempted against a `REQUESTED`, `REJECTED`
    or already-`REFUNDED` row yields `ERR_DRAWDOWN_INVALID_STATE`."

    PRD §3.8: "`REQUESTED` and `REJECTED` drawdowns contribute nothing anywhere."

    Design: Corner/state_machines/drawdown_refund_before_disbursement_rejected
    """
    scenario = setup_obligated_project(
        disaster_overrides={"declaration_number": "DR-4945"},
        project_overrides={"estimated_repair_cost_cents": 4_000_000},
        line_items=[{"claimed_cents": 4_000_000}],
        officer_user_id=GRANTS_OFFICER_USER_ID,
    )
    applicant_id = scenario["applicant"]["id"]
    drawdown = create_drawdown(applicant_id, scenario["project"]["id"], 1_000_000)

    validate_error(
        api.refund_drawdown(
            drawdown["id"],
            {"refund_cents": 1_000_000},
            make_applicant_agent_headers(applicant_id),
        ),
        ApiErrorId.ERR_DRAWDOWN_INVALID_STATE,
    )

    after = get_drawdown(drawdown["id"])
    assert after["status"] == "REQUESTED", (
        f"Expected the drawdown to stay REQUESTED, got {after['status']}"
    )
    assert after["approved_cents"] == 0, (
        f"Expected approved_cents 0, got {after['approved_cents']}"
    )
    assert after["refunded_cents"] == 0, (
        f"Expected refunded_cents 0, got {after['refunded_cents']}"
    )

    applicant = get_applicant(applicant_id)
    assert applicant["total_drawn_cents"] == 0, (
        f"Expected total_drawn_cents 0, got {applicant['total_drawn_cents']}"
    )
    assert applicant["total_refunded_cents"] == 0, (
        f"Expected total_refunded_cents 0, got {applicant['total_refunded_cents']}"
    )
    assert applicant["cash_on_hand_cents"] == 0, (
        f"Expected cash_on_hand_cents 0, got {applicant['cash_on_hand_cents']}"
    )
    assert applicant["available_drawdown_cents"] == 3_000_000, (
        "Expected available_drawdown_cents 3000000, got "
        f"{applicant['available_drawdown_cents']}"
    )

    disaster = get_disaster(scenario["disaster"]["id"])
    assert disaster["total_drawn_cents"] == 0, (
        f"Expected declaration total_drawn_cents 0, got {disaster['total_drawn_cents']}"
    )


def test_drawdown_reject_branch_moves_no_cash(api):
    """PRD §3.8: "The `REQUESTED → REJECTED` branch is the mirror image in inertness: it
    records the `rejection_reason`, sets `status` to `REJECTED`, leaves `approved_cents`
    at 0, moves **no** ledger field on either the applicant or the declaration, and
    increments neither of their versions — only the drawdown's own `version` rises by 1."

    Design: Corner/state_machines/drawdown_reject_branch_moves_no_cash
    """
    scenario = setup_obligated_project(
        disaster_overrides={"declaration_number": "DR-4955"},
        project_overrides={"estimated_repair_cost_cents": 4_000_000},
        line_items=[{"claimed_cents": 4_000_000}],
        officer_user_id=GRANTS_OFFICER_USER_ID,
    )
    applicant_id = scenario["applicant"]["id"]
    drawdown = create_drawdown(applicant_id, scenario["project"]["id"], 1_000_000)

    data = validate_success(
        api.disburse_drawdown(
            drawdown["id"],
            {
                "decision": "REJECT",
                "rejection_reason": "Supporting expenditure detail missing",
            },
            make_grants_officer_headers(SECOND_GRANTS_OFFICER_USER_ID),
        )
    )

    assert data["status"] == "REJECTED", (
        f"Expected REJECTED, got {data['status']} after the reject disbursement branch"
    )
    assert data["approved_cents"] == 0, (
        f"Expected approved_cents to stay 0, got {data['approved_cents']}"
    )
    assert data["refunded_cents"] == 0, (
        f"Expected refunded_cents 0, got {data['refunded_cents']}"
    )
    assert data["rejection_reason"] == "Supporting expenditure detail missing", (
        f"Expected the supplied rejection_reason, got {data['rejection_reason']}"
    )

    applicant = get_applicant(applicant_id)
    assert applicant["total_drawn_cents"] == 0, (
        f"Expected total_drawn_cents 0, got {applicant['total_drawn_cents']}"
    )
    assert applicant["cash_on_hand_cents"] == 0, (
        f"Expected cash_on_hand_cents 0, got {applicant['cash_on_hand_cents']}"
    )
    assert applicant["available_drawdown_cents"] == 3_000_000, (
        "Expected available_drawdown_cents 3000000, got "
        f"{applicant['available_drawdown_cents']}"
    )

    disaster = get_disaster(scenario["disaster"]["id"])
    assert disaster["total_drawn_cents"] == 0, (
        f"Expected declaration total_drawn_cents 0, got {disaster['total_drawn_cents']}"
    )


# ---------------------------------------------------------------------------
# Project: initial state and terminal state
# ---------------------------------------------------------------------------


def test_project_starts_in_draft_and_rfi_from_draft_is_rejected(api):
    """PRD §3.3: "The project is created in `DRAFT` with `size_class` null,
    `rfi_round_count` 0, `last_rfi_question` null, `work_type` not yet derived, and every
    basis and ledger field at its opening value: `repair_eligible_cents`,
    `anticipated_insurance_cents`, `settlement_allocated_cents`,
    `insurance_reduction_cents`, `mitigation_approved_cents`,
    `eligible_cost_provisional_cents`, `federal_share_obligated_cents`,
    `deobligated_cents` and `pending_deobligation_cents` at 0, and
    `eligible_cost_final_cents`, `federal_share_final_cents`, `closeout_variance_cents`,
    `cost_reviewed_by_user_id`, `obligated_by_user_id` and `denial_reason` all null."

    PRD §3.3: "A `ProgramSpecialist` may issue a request for information, supplying the
    `question` text; this drives `UNDER_REVIEW → RFI_ISSUED`, records the text in
    `last_rfi_question`, raises `rfi_round_count` by 1, and increments the project's
    `version` by 1."

    PRD §3.7: "The project must be in `UNDER_REVIEW`."

    PRD §2.7: "State admissibility of the target row, and — for drawdown creation and
    deobligation creation — of the referenced project: `ERR_PROJECT_INVALID_STATE`,
    `ERR_DISASTER_INVALID_STATE`, `ERR_DAMAGE_SITE_ALREADY_ADJUDICATED`,
    `ERR_CONTRACT_ALREADY_REVIEWED`, `ERR_COST_LINE_ITEM_LOCKED`,
    `ERR_FACILITY_AMENDMENT_LOCKED`, `ERR_DRAWDOWN_INVALID_STATE`,
    `ERR_DEOBLIGATION_NOT_FINAL`, `ERR_APPEAL_ALREADY_DECIDED` or
    `ERR_REPORT_ALREADY_SUBMITTED` (all 409)."

    Design: Corner/state_machines/project_starts_in_draft_and_rfi_from_draft_is_rejected
    """
    scenario = setup_drafted_project(
        disaster_overrides={"declaration_number": "DR-4947"},
        project_overrides={"estimated_repair_cost_cents": 5_000_000},
    )
    project_id = scenario["project"]["id"]
    assert scenario["project"]["status"] == "DRAFT", (
        f"A created project must start in DRAFT, got {scenario['project']['status']}"
    )

    validate_error(
        api.issue_rfi(
            project_id,
            {"question": "Provide the damage inventory"},
            make_specialist_headers(SPECIALIST_USER_ID),
        ),
        ApiErrorId.ERR_PROJECT_INVALID_STATE,
    )
    validate_error(
        api.cost_review(
            project_id,
            {"decision": "VALIDATE"},
            make_specialist_headers(SPECIALIST_USER_ID),
        ),
        ApiErrorId.ERR_PROJECT_INVALID_STATE,
    )

    after = get_project(project_id)
    assert after["status"] == "DRAFT", (
        f"Expected the project to stay DRAFT, got {after['status']}"
    )
    assert after["rfi_round_count"] == 0, (
        f"Expected rfi_round_count 0, got {after['rfi_round_count']}"
    )
    assert after["last_rfi_question"] is None, (
        f"Expected last_rfi_question null, got {after['last_rfi_question']}"
    )
    assert after["repair_eligible_cents"] == 0, (
        f"Expected repair_eligible_cents 0, got {after['repair_eligible_cents']}"
    )
    assert after["size_class"] is None, (
        f"Expected size_class null in DRAFT, got {after['size_class']}"
    )
    assert after["version"] == 1, (
        f"Expected project version to stay 1, got {after['version']}"
    )


def test_project_closed_is_terminal_and_rejects_further_actions(api):
    """PRD §3.9: "When the work is done and the receipts are in, the `ApplicantAgent`
    requests closeout, driving the project `OBLIGATED → CLOSEOUT_REQUESTED`."

    PRD §3.7: "Obligation is a `GrantsOfficer` capability driving `VALIDATED →
    OBLIGATED`, and it is where the federal government's money is committed."

    PRD §3.3: "A `ProgramSpecialist` may issue a request for information, supplying the
    `question` text; this drives `UNDER_REVIEW → RFI_ISSUED`, records the text in
    `last_rfi_question`, raises `rfi_round_count` by 1, and increments the project's
    `version` by 1."

    PRD §2.7: "State admissibility of the target row, and — for drawdown creation and
    deobligation creation — of the referenced project: `ERR_PROJECT_INVALID_STATE`,
    `ERR_DISASTER_INVALID_STATE`, `ERR_DAMAGE_SITE_ALREADY_ADJUDICATED`,
    `ERR_CONTRACT_ALREADY_REVIEWED`, `ERR_COST_LINE_ITEM_LOCKED`,
    `ERR_FACILITY_AMENDMENT_LOCKED`, `ERR_DRAWDOWN_INVALID_STATE`,
    `ERR_DEOBLIGATION_NOT_FINAL`, `ERR_APPEAL_ALREADY_DECIDED` or
    `ERR_REPORT_ALREADY_SUBMITTED` (all 409)."

    PRD §3.4: "The project must be open to cost accumulation, meaning its `status` is
    `DRAFT`, `UNDER_REVIEW`, `RFI_ISSUED` or `OBLIGATED`; a project sitting in
    `VALIDATED`, `CLOSEOUT_REQUESTED`, `CLOSED` or `DENIED` has its cost record frozen
    and the claim is refused with `ERR_COST_LINE_ITEM_LOCKED`."

    PRD §3.9: "A **`SMALL`** project is funded on its estimate and is never reconciled
    against actuals: `federal_share_final_cents` is set equal to
    `federal_share_obligated_cents`, `closeout_variance_cents` is set to 0, and **no**
    determination is created no matter how far the documented actuals fell below the
    estimate."

    Design: Corner/state_machines/project_closed_is_terminal_and_rejects_further_actions
    """
    scenario = setup_closeout_requested_project(
        disaster_overrides={"declaration_number": "DR-4946"},
        project_overrides={
            "estimated_repair_cost_cents": 1_500_000,
            "title": "Culvert replacement",
            "scope_of_work": "Replace two collapsed culverts",
        },
        line_items=[{"claimed_cents": 1_500_000}],
        officer_user_id=GRANTS_OFFICER_USER_ID,
    )
    project_id = scenario["project"]["id"]
    applicant_id = scenario["applicant"]["id"]
    agent = make_applicant_agent_headers(applicant_id)
    closed = certify_closeout(
        project_id, "No exceptions noted in the documented cost package"
    )
    assert closed["status"] == "CLOSED", (
        f"Setup expected a CLOSED project, got {closed['status']}"
    )

    validate_error(
        api.request_closeout(project_id, agent), ApiErrorId.ERR_PROJECT_INVALID_STATE
    )
    validate_error(
        api.obligate_project(
            project_id, make_grants_officer_headers(GRANTS_OFFICER_USER_ID)
        ),
        ApiErrorId.ERR_PROJECT_INVALID_STATE,
    )
    validate_error(
        api.issue_rfi(
            project_id,
            {"question": "Please resubmit the invoice package"},
            make_specialist_headers(SPECIALIST_USER_ID),
        ),
        ApiErrorId.ERR_PROJECT_INVALID_STATE,
    )
    validate_error(
        api.create_cost_line_item(
            {
                "project_id": project_id,
                "cost_type": "MATERIALS",
                "claimed_cents": 100_000,
                "work_start_at": "2026-06-13T08:00:00Z",
                "work_end_at": "2026-06-13T17:00:00Z",
            },
            agent,
        ),
        ApiErrorId.ERR_COST_LINE_ITEM_LOCKED,
    )

    after = get_project(project_id)
    assert after["status"] == "CLOSED", (
        f"Expected the project to stay CLOSED, got {after['status']}"
    )
    assert after["federal_share_obligated_cents"] == 1_125_000, (
        "Expected federal_share_obligated_cents 1125000, got "
        f"{after['federal_share_obligated_cents']}"
    )
    assert after["federal_share_final_cents"] == 1_125_000, (
        "Expected federal_share_final_cents 1125000 for a SMALL project, got "
        f"{after['federal_share_final_cents']}"
    )
    assert after["closeout_variance_cents"] == 0, (
        "Expected closeout_variance_cents 0 for a SMALL project, got "
        f"{after['closeout_variance_cents']}"
    )
    assert after["rfi_round_count"] == 0, (
        f"Expected rfi_round_count 0, got {after['rfi_round_count']}"
    )

    rows, _meta = validate_paginated(api.list_cost_line_items(make_admin_headers()))
    assert len(rows) == 1, (
        f"Expected the refused claim to be absent, got {len(rows)} cost line items"
    )


# ---------------------------------------------------------------------------
# Facility: the screening cycle and the amendment lock
# ---------------------------------------------------------------------------


def test_facility_rescreen_after_amendment_flips_ineligible_to_eligible(api):
    """PRD §3.2: "If `legal_responsibility_documented` is false, the facility is
    `INELIGIBLE` with reason `LEGAL_RESPONSIBILITY_NOT_DOCUMENTED`."

    PRD §3.2: "Whichever branch fires, `screened_at` is stamped with the logical clock
    and the facility's `version` increments by 1; the `PENDING → ELIGIBLE` branch
    additionally clears `screening_failure_reason` to null, and the `PENDING →
    INELIGIBLE` branch sets it to the first failed rule's code."

    PRD §3.2: "An `ApplicantAgent` may amend its own facility's `in_active_use`,
    `legal_responsibility_documented`, `ownership`, `flood_zone` and
    `prior_disaster_flood_damage`, and any such amendment — from `ELIGIBLE` or from
    `INELIGIBLE` alike — writes the supplied attributes, forces `eligibility_status`
    back to `PENDING`, clears `screening_failure_reason` to null and `screened_at` to
    null, and increments `version` by 1."

    PRD §3.2: "The facility may then be re-screened, giving the `INELIGIBLE → PENDING →
    ELIGIBLE` path that cures a missing tax-exempt letter or a mis-recorded ownership
    form."

    PRD §3.2: "Otherwise the facility is `ELIGIBLE` and `screening_failure_reason` is
    null."

    Design: Corner/state_machines/facility_rescreen_after_amendment_flips_ineligible_to_eligible
    """
    scenario = setup_declaration(declaration_number="DR-4948")
    applicant = create_applicant(scenario["disaster"]["id"])
    facility = create_facility(
        applicant["id"], legal_responsibility_documented=False
    )
    screened = screen_facility(facility["id"])

    assert screened["eligibility_status"] == "INELIGIBLE", (
        f"Expected INELIGIBLE, got {screened['eligibility_status']} on first screening"
    )
    assert screened["screening_failure_reason"] == "LEGAL_RESPONSIBILITY_NOT_DOCUMENTED", (
        "Expected LEGAL_RESPONSIBILITY_NOT_DOCUMENTED, got "
        f"{screened['screening_failure_reason']}"
    )
    assert is_iso8601_timestamp(screened["screened_at"]), (
        f"Expected screened_at stamped from the clock, got {screened['screened_at']}"
    )
    assert screened["version"] == 2, (
        f"Expected facility version 2 after screening, got {screened['version']}"
    )

    amended = validate_success(
        api.amend_facility(
            facility["id"],
            {"legal_responsibility_documented": True},
            make_applicant_agent_headers(applicant["id"]),
        )
    )
    assert amended["eligibility_status"] == "PENDING", (
        "An amendment must force eligibility_status back to PENDING, got "
        f"{amended['eligibility_status']}"
    )
    assert amended["screening_failure_reason"] is None, (
        "Expected screening_failure_reason cleared to null, got "
        f"{amended['screening_failure_reason']}"
    )
    assert amended["screened_at"] is None, (
        f"Expected screened_at cleared to null, got {amended['screened_at']}"
    )
    assert amended["legal_responsibility_documented"] is True, (
        "Expected the supplied legal_responsibility_documented true, got "
        f"{amended['legal_responsibility_documented']}"
    )
    assert amended["version"] == 3, (
        f"Expected facility version 3 after the amendment, got {amended['version']}"
    )

    rescreened = validate_success(
        api.screen_facility(
            facility["id"], make_specialist_headers(SPECIALIST_USER_ID)
        )
    )
    assert rescreened["eligibility_status"] == "ELIGIBLE", (
        "Expected the cure to make the facility ELIGIBLE, got "
        f"{rescreened['eligibility_status']}"
    )
    assert rescreened["screening_failure_reason"] is None, (
        "Expected screening_failure_reason null on the eligible branch, got "
        f"{rescreened['screening_failure_reason']}"
    )
    assert is_iso8601_timestamp(rescreened["screened_at"]), (
        f"Expected screened_at re-stamped, got {rescreened['screened_at']}"
    )
    assert rescreened["version"] == 4, (
        f"Expected facility version 4 after the re-screen, got {rescreened['version']}"
    )


def test_facility_amendment_locked_by_validated_project(api):
    """PRD §3.2: "If any project on that facility is in `VALIDATED`, `OBLIGATED` or
    `CLOSEOUT_REQUESTED`, the amendment is refused with
    `ERR_FACILITY_AMENDMENT_LOCKED`."

    Design: Corner/state_machines/facility_amendment_locked_by_validated_project
    """
    scenario = setup_validated_project(
        disaster_overrides={"declaration_number": "DR-4949"},
        project_overrides={"estimated_repair_cost_cents": 4_000_000},
        line_items=[{"claimed_cents": 4_000_000}],
    )
    facility_id = scenario["facility"]["id"]
    assert scenario["project"]["status"] == "VALIDATED", (
        f"Setup expected a VALIDATED project, got {scenario['project']['status']}"
    )

    validate_error(
        api.amend_facility(
            facility_id,
            {"in_active_use": False},
            make_applicant_agent_headers(scenario["applicant"]["id"]),
        ),
        ApiErrorId.ERR_FACILITY_AMENDMENT_LOCKED,
    )

    after = get_facility(facility_id)
    assert after["in_active_use"] is True, (
        f"Expected in_active_use unchanged at true, got {after['in_active_use']}"
    )
    assert after["eligibility_status"] == "ELIGIBLE", (
        f"Expected eligibility_status to stay ELIGIBLE, got {after['eligibility_status']}"
    )
    assert is_iso8601_timestamp(after["screened_at"]), (
        f"Expected screened_at untouched, got {after['screened_at']}"
    )
    assert after["version"] == 2, (
        f"Expected facility version to stay 2, got {after['version']}"
    )


# ---------------------------------------------------------------------------
# Cost line items and project cost review
# ---------------------------------------------------------------------------


def test_cost_line_item_creation_and_review_locked_after_project_validation(api):
    """PRD §3.4: "The project must be open to cost accumulation, meaning its `status` is
    `DRAFT`, `UNDER_REVIEW`, `RFI_ISSUED` or `OBLIGATED`; a project sitting in
    `VALIDATED`, `CLOSEOUT_REQUESTED`, `CLOSED` or `DENIED` has its cost record frozen
    and the claim is refused with `ERR_COST_LINE_ITEM_LOCKED`."

    PRD §3.5: "The line's project must still be open to cost accumulation — `DRAFT`,
    `UNDER_REVIEW`, `RFI_ISSUED` or `OBLIGATED` — or the review is refused with
    `ERR_COST_LINE_ITEM_LOCKED`."

    PRD §3.7: "The system totals the `eligible_cents` of every cost line item on the
    project whose `review_status` is `ALLOWED` or `PARTIALLY_ALLOWED`, and
    `repair_eligible_cents` becomes that total."

    Design: Corner/state_machines/cost_line_item_creation_and_review_locked_after_project_validation
    """
    scenario = setup_validated_project(
        disaster_overrides={"declaration_number": "DR-4950"},
        project_overrides={"estimated_repair_cost_cents": 4_000_000},
        line_items=[{"claimed_cents": 4_000_000}],
    )
    project_id = scenario["project"]["id"]
    applicant_id = scenario["applicant"]["id"]
    line_id = scenario["lines"][0]["id"]

    validate_error(
        api.create_cost_line_item(
            {
                "project_id": project_id,
                "cost_type": "MATERIALS",
                "claimed_cents": 250_000,
                "work_start_at": "2026-06-13T08:00:00Z",
                "work_end_at": "2026-06-13T17:00:00Z",
            },
            make_applicant_agent_headers(applicant_id),
        ),
        ApiErrorId.ERR_COST_LINE_ITEM_LOCKED,
    )
    validate_error(
        api.review_cost_line_item(
            line_id, make_specialist_headers(SPECIALIST_USER_ID)
        ),
        ApiErrorId.ERR_COST_LINE_ITEM_LOCKED,
    )

    rows, _meta = validate_paginated(api.list_cost_line_items(make_admin_headers()))
    assert len(rows) == 1, (
        f"Expected the refused claim to be absent, got {len(rows)} cost line items"
    )

    line = get_cost_line_item(line_id)
    assert line["review_status"] == "ALLOWED", (
        f"Expected the line to stay ALLOWED, got {line['review_status']}"
    )
    assert line["eligible_cents"] == 4_000_000, (
        f"Expected eligible_cents 4000000, got {line['eligible_cents']}"
    )
    assert line["version"] == 2, (
        f"Expected cost line item version to stay 2, got {line['version']}"
    )

    project = get_project(project_id)
    assert project["repair_eligible_cents"] == 4_000_000, (
        f"Expected repair_eligible_cents 4000000, got {project['repair_eligible_cents']}"
    )
    assert project["status"] == "VALIDATED", (
        f"Expected the project to stay VALIDATED, got {project['status']}"
    )


def test_cost_review_with_unreviewed_line_rejected(api):
    """PRD §3.7: "Two further checks guard the operation: no cost line item on the
    project may still be sitting in `review_status` `SUBMITTED`, because reviewing the
    project before its lines have been examined would fix a basis on unexamined claims
    (`ERR_UNREVIEWED_COST_LINE_ITEMS`), and the project's facility must be `ELIGIBLE` at
    this moment (`ERR_FACILITY_INELIGIBLE`) — which is precisely how a mid-review
    facility amendment blocks the review that was already in flight."

    Design: Corner/state_machines/cost_review_with_unreviewed_line_rejected
    """
    scenario = setup_submitted_project(
        disaster_overrides={"declaration_number": "DR-4951"},
        project_overrides={"estimated_repair_cost_cents": 3_000_000},
    )
    project_id = scenario["project"]["id"]
    applicant_id = scenario["applicant"]["id"]

    line_a = create_cost_line_item(project_id, applicant_id, claimed_cents=2_000_000)
    review_cost_line_item(line_a["id"])
    line_b = create_cost_line_item(
        project_id,
        applicant_id,
        claimed_cents=500_000,
        work_start_at="2026-06-13T08:00:00Z",
        work_end_at="2026-06-13T17:00:00Z",
    )

    validate_error(
        api.cost_review(
            project_id,
            {"decision": "VALIDATE"},
            make_specialist_headers(SPECIALIST_USER_ID),
        ),
        ApiErrorId.ERR_UNREVIEWED_COST_LINE_ITEMS,
    )

    unreviewed = get_cost_line_item(line_b["id"])
    assert unreviewed["review_status"] == "SUBMITTED", (
        f"Expected the second line to stay SUBMITTED, got {unreviewed['review_status']}"
    )

    project = get_project(project_id)
    assert project["status"] == "UNDER_REVIEW", (
        f"Expected the project to stay UNDER_REVIEW, got {project['status']}"
    )
    assert project["repair_eligible_cents"] == 0, (
        f"Expected repair_eligible_cents 0, got {project['repair_eligible_cents']}"
    )
    assert project["mitigation_approved_cents"] == 0, (
        f"Expected mitigation_approved_cents 0, got {project['mitigation_approved_cents']}"
    )
    assert project["cost_reviewed_by_user_id"] is None, (
        "Expected cost_reviewed_by_user_id null after a refused review, got "
        f"{project['cost_reviewed_by_user_id']}"
    )


def test_project_cost_review_deny_branch_touches_no_basis_field(api):
    """PRD §3.7: "The `UNDER_REVIEW → DENIED` branch is deliberately inert."

    PRD §3.7: "It records the supplied `denial_reason`, sets `status` to `DENIED`,
    records `cost_reviewed_by_user_id` from the acting specialist's `X-User-ID`, and
    increments the project's `version` by 1 — and that is all."

    PRD §3.7: "`repair_eligible_cents`, `mitigation_approved_cents` and
    `insurance_reduction_cents` are left exactly as they were, neither recomputed nor
    cleared, and no ledger field on the applicant or the declaration moves by a single
    cent."

    Design: Corner/state_machines/project_cost_review_deny_branch_touches_no_basis_field
    """
    scenario = setup_submitted_project(
        disaster_overrides={"declaration_number": "DR-4952"},
        project_overrides={"estimated_repair_cost_cents": 5_000_000},
    )
    project_id = scenario["project"]["id"]
    applicant_id = scenario["applicant"]["id"]
    line = create_cost_line_item(project_id, applicant_id, claimed_cents=3_000_000)
    review_cost_line_item(line["id"])

    data = validate_success(
        api.cost_review(
            project_id,
            {
                "decision": "DENY",
                "denial_reason": "Scope of work is not disaster-related damage",
            },
            make_specialist_headers(SPECIALIST_USER_ID),
        )
    )

    assert data["status"] == "DENIED", (
        f"Expected DENIED, got {data['status']} on the deny branch"
    )
    assert data["denial_reason"] == "Scope of work is not disaster-related damage", (
        f"Expected the supplied denial_reason, got {data['denial_reason']}"
    )
    assert data["cost_reviewed_by_user_id"] == SPECIALIST_USER_ID, (
        f"Expected cost_reviewed_by_user_id {SPECIALIST_USER_ID}, got "
        f"{data['cost_reviewed_by_user_id']}"
    )
    assert data["repair_eligible_cents"] == 0, (
        f"Expected repair_eligible_cents left at 0, got {data['repair_eligible_cents']}"
    )
    assert data["anticipated_insurance_cents"] == 0, (
        "Expected anticipated_insurance_cents 0, got "
        f"{data['anticipated_insurance_cents']}"
    )
    assert data["insurance_reduction_cents"] == 0, (
        f"Expected insurance_reduction_cents left at 0, got {data['insurance_reduction_cents']}"
    )
    assert data["mitigation_approved_cents"] == 0, (
        f"Expected mitigation_approved_cents left at 0, got {data['mitigation_approved_cents']}"
    )
    assert data["eligible_cost_provisional_cents"] == 5_000_000, (
        "Expected the submit-time eligible_cost_provisional_cents 5000000 untouched, got "
        f"{data['eligible_cost_provisional_cents']}"
    )
    assert data["size_class"] == "LARGE", (
        f"Expected the submit-time size_class LARGE untouched, got {data['size_class']}"
    )

    applicant = get_applicant(applicant_id)
    assert applicant["total_obligated_cents"] == 0, (
        "The deny branch must move no applicant ledger field: expected "
        f"total_obligated_cents 0, got {applicant['total_obligated_cents']}"
    )


# ---------------------------------------------------------------------------
# Deobligation and appeal
# ---------------------------------------------------------------------------


def test_deobligation_reversed_by_granted_appeal_restores_ledger(api):
    """PRD §3.9: "It stamps `finalized_at` from the logical clock and sets
    `appeal_deadline_at` to that instant plus the sixty-day appeal window."

    PRD §3.9: "Because the determination became final, the money actually leaves the
    obligation: the project's `deobligated_cents` rises by `amount_cents` and its
    `pending_deobligation_cents` falls by the same amount."

    PRD §3.9: "- **`SUBMITTED → GRANTED`** sets `relief_granted_cents` to the full
    `relief_requested_cents` and reverses the determination by that amount."

    PRD §3.9: "`reversed_cents` is set to `relief_granted_cents`; the determination's
    `status` becomes `REVERSED` when `reversed_cents` equals the full `amount_cents`, and
    **stays `FINAL`** when the reversal is partial, that is when `reversed_cents` is
    above 0 but below `amount_cents`."

    PRD §3.9: "Because `reversed_cents` moved, the project's `deobligated_cents` falls by
    `relief_granted_cents`, which puts the money back on the obligation ledger; because
    `deobligated_cents` moved, the applicant's `total_obligated_cents` and
    `available_drawdown_cents` are recomputed and the declaration's
    `total_obligated_cents` follows."

    Design: Corner/state_machines/deobligation_reversed_by_granted_appeal_restores_ledger
    """
    scenario = setup_appeal_under_review(
        500_000,
        relief_requested_cents=500_000,
        reason="DISALLOWED_COST",
        headers=make_grants_officer_headers(SECOND_GRANTS_OFFICER_USER_ID),
        officer_user_id=SECOND_GRANTS_OFFICER_USER_ID,
        disaster_overrides={"declaration_number": "DR-4953"},
        project_overrides={"estimated_repair_cost_cents": 4_000_000},
        line_items=[{"claimed_cents": 4_000_000}],
    )
    disaster_id = scenario["disaster"]["id"]
    applicant_id = scenario["applicant"]["id"]
    project_id = scenario["project"]["id"]
    deobligation_id = scenario["deobligation"]["id"]
    appeal_id = scenario["appeal"]["id"]

    deob_before = get_deobligation(deobligation_id)
    assert deob_before["status"] == "FINAL", (
        f"Setup expected a FINAL determination, got {deob_before['status']}"
    )
    assert is_iso8601_timestamp(deob_before["finalized_at"]), (
        f"Expected finalized_at stamped from the clock, got {deob_before['finalized_at']}"
    )
    assert deob_before["appeal_deadline_at"].startswith("2026-08-30T00:00:00"), (
        "Expected appeal_deadline_at sixty days after 2026-07-01T00:00:00Z, got "
        f"{deob_before['appeal_deadline_at']}"
    )
    project_before = get_project(project_id)
    assert project_before["deobligated_cents"] == 500_000, (
        f"Expected deobligated_cents 500000 after finalization, got "
        f"{project_before['deobligated_cents']}"
    )
    applicant_before = get_applicant(applicant_id)
    assert applicant_before["total_obligated_cents"] == 2_500_000, (
        "Expected total_obligated_cents 2500000 after finalization, got "
        f"{applicant_before['total_obligated_cents']}"
    )

    data = validate_success(
        api.decide_appeal(
            appeal_id,
            {
                "decision": "GRANT",
                "decision_rationale": "Documentation supports the full claimed amount",
            },
            make_adjudicator_headers(ADJUDICATOR_USER_ID),
        )
    )

    assert data["status"] == "GRANTED", (
        f"Expected GRANTED, got {data['status']} after the grant decision"
    )
    assert data["relief_granted_cents"] == 500_000, (
        f"Expected relief_granted_cents 500000, got {data['relief_granted_cents']}"
    )
    assert is_iso8601_timestamp(data["decided_at"]), (
        f"Expected decided_at stamped from the clock, got {data['decided_at']}"
    )
    assert data["decided_by_user_id"] == ADJUDICATOR_USER_ID, (
        f"Expected decided_by_user_id {ADJUDICATOR_USER_ID}, got "
        f"{data['decided_by_user_id']}"
    )

    deobligation = get_deobligation(deobligation_id)
    assert deobligation["status"] == "REVERSED", (
        f"Expected the determination REVERSED, got {deobligation['status']}"
    )
    assert deobligation["reversed_cents"] == 500_000, (
        f"Expected reversed_cents 500000, got {deobligation['reversed_cents']}"
    )

    project = get_project(project_id)
    assert project["deobligated_cents"] == 0, (
        f"Expected deobligated_cents back to 0, got {project['deobligated_cents']}"
    )
    assert project["pending_deobligation_cents"] == 0, (
        f"Expected pending_deobligation_cents 0, got {project['pending_deobligation_cents']}"
    )
    assert project["federal_share_obligated_cents"] == 3_000_000, (
        "Expected federal_share_obligated_cents never rewritten by the appeal, got "
        f"{project['federal_share_obligated_cents']}"
    )

    applicant = get_applicant(applicant_id)
    assert applicant["total_obligated_cents"] == 3_000_000, (
        f"Expected total_obligated_cents restored to 3000000, got "
        f"{applicant['total_obligated_cents']}"
    )
    assert applicant["available_drawdown_cents"] == 3_000_000, (
        f"Expected available_drawdown_cents 3000000, got "
        f"{applicant['available_drawdown_cents']}"
    )
    assert applicant["drawdown_status"] == "ACTIVE", (
        f"Expected drawdown_status ACTIVE, got {applicant['drawdown_status']}"
    )

    disaster = get_disaster(disaster_id)
    assert disaster["total_obligated_cents"] == 3_000_000, (
        "Expected the declaration total_obligated_cents restored to 3000000, got "
        f"{disaster['total_obligated_cents']}"
    )
    assert disaster["suspended_applicant_count"] == 0, (
        f"Expected suspended_applicant_count 0, got {disaster['suspended_applicant_count']}"
    )


def test_appeal_second_decision_rejected(api):
    """PRD §3.9: "The appeal must be in `SUBMITTED`, or the decision is refused with
    `ERR_APPEAL_ALREADY_DECIDED`, and the adjudicator's `X-User-ID` must differ from the
    determination's `determined_by_user_id`, or it is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    PRD §3.9: "- **`SUBMITTED → DENIED`** sets `relief_granted_cents` to 0 and moves
    **nothing** outside the appeal row — no determination, project, applicant or
    declaration field changes, and no version other than the appeal's increments."

    Design: Corner/state_machines/appeal_second_decision_rejected
    """
    scenario = setup_appeal_under_review(
        500_000,
        relief_requested_cents=500_000,
        reason="DISALLOWED_COST",
        headers=make_grants_officer_headers(SECOND_GRANTS_OFFICER_USER_ID),
        officer_user_id=SECOND_GRANTS_OFFICER_USER_ID,
        disaster_overrides={"declaration_number": "DR-4954"},
        project_overrides={"estimated_repair_cost_cents": 4_000_000},
        line_items=[{"claimed_cents": 4_000_000}],
    )
    applicant_id = scenario["applicant"]["id"]
    project_id = scenario["project"]["id"]
    deobligation_id = scenario["deobligation"]["id"]
    appeal_id = scenario["appeal"]["id"]

    denied = decide_appeal(
        appeal_id,
        "DENY",
        decision_rationale="Invoices do not tie to the approved scope of work",
    )
    assert denied["status"] == "DENIED", (
        f"Setup expected a DENIED appeal, got {denied['status']}"
    )

    validate_error(
        api.decide_appeal(
            appeal_id,
            {
                "decision": "GRANT",
                "decision_rationale": "Second look after further review",
            },
            make_adjudicator_headers(ADJUDICATOR_USER_ID),
        ),
        ApiErrorId.ERR_APPEAL_ALREADY_DECIDED,
    )

    appeal = get_appeal(appeal_id)
    assert appeal["status"] == "DENIED", (
        f"Expected the appeal to stay DENIED, got {appeal['status']}"
    )
    assert appeal["relief_granted_cents"] == 0, (
        f"Expected relief_granted_cents to stay 0, got {appeal['relief_granted_cents']}"
    )
    assert appeal["decision_rationale"] == (
        "Invoices do not tie to the approved scope of work"
    ), f"Expected the original rationale intact, got {appeal['decision_rationale']}"

    deobligation = get_deobligation(deobligation_id)
    assert deobligation["status"] == "FINAL", (
        f"Expected the determination to stay FINAL, got {deobligation['status']}"
    )
    assert deobligation["reversed_cents"] == 0, (
        f"Expected reversed_cents to stay 0, got {deobligation['reversed_cents']}"
    )

    project = get_project(project_id)
    assert project["deobligated_cents"] == 500_000, (
        f"Expected deobligated_cents to stay 500000, got {project['deobligated_cents']}"
    )

    applicant = get_applicant(applicant_id)
    assert applicant["total_obligated_cents"] == 2_500_000, (
        f"Expected total_obligated_cents to stay 2500000, got "
        f"{applicant['total_obligated_cents']}"
    )
