"""The two agreement dimensions, the execution gates and the committed ledger."""
from test_helpers import (
    CANON_ESTIMATE_STATE_SHARE_CENTS,
    CANON_STATE_LIABILITY_CENTS,
    OFFICER_USER_ID,
    RELEASE_NOTE,
    VOID_REASON,
    add_second_relocate_chain,
    assert_settlement_figures,
    assert_version_unchanged,
    circulate_agreement,
    commit_window,
    draft_agreement,
    make_agreement_officer_headers,
    make_program_admin_headers,
    raise_audit_finding,
    read_agreement,
    read_audit_finding,
    read_owner,
    read_project,
    release_owner_hold,
    report_complete,
    resolve_audit_finding,
    revise_project,
    set_clock,
    settle_agreement,
    validate_error,
    validate_paginated,
    validate_success,
    void_agreement,
    world_agreement_circulated,
    world_agreement_drafted,
    world_agreement_executed,
    world_cost_documents,
    world_plan_approved,
)

ONE_LABOR_LINE = [
    {
        "doc_type": "LABOR",
        "amount_cents": 12_345_678,
        "incurred_on": "2027-04-02T00:00:00Z",
        "support_reference": "PR-2027-04-A",
        "review": "ACCEPT",
    }
]

SECOND_EASEMENT_FACILITY = {
    "facility_type": "BURIED_ELECTRIC",
    "station_begin": 300.0,
    "station_end": 340.0,
    "offset_ft": 11.0,
    "depth_in": 44,
    "material": "PVC duct bank",
    "installed_year": 1968,
    "occupancy_basis": "PRIVATE_EASEMENT",
    "record_source": "AS_BUILT",
}


def test_two_audit_cycles_move_the_settlement_dimension_off_and_back(api):
    """PRD 3.8: "Raising a finding suspends settlement: an agreement in
    `PENDING_FINAL_INVOICE` moves to `AUDIT_IN_PROGRESS`, and its `version`
    increments."

    Design: Difficulty/non_linear_state_machine/settlement_dimension_reenters_pending_after_two_audit_cycles_then_locks
    """
    world = world_cost_documents(api, documents=ONE_LABOR_LINE)
    agreement_id = world["agreement_id"]
    assert world["agreement"]["settlement_status"] == "PENDING_FINAL_INVOICE"
    assert world["agreement"]["execution_status"] == "EXECUTED"

    first = raise_audit_finding(
        api, agreement_id, finding_type="UNSUPPORTED_COST", questioned_cost_cents=500_000
    )
    in_audit = read_agreement(api, agreement_id)
    assert in_audit["settlement_status"] == "AUDIT_IN_PROGRESS"
    assert in_audit["execution_status"] == "EXECUTED"

    resolve_audit_finding(api, first["id"], "WITHDRAWN")
    back = read_agreement(api, agreement_id)
    assert back["settlement_status"] == "PENDING_FINAL_INVOICE"
    assert back["execution_status"] == "EXECUTED"

    second = raise_audit_finding(
        api,
        agreement_id,
        finding_type="INDIRECT_RATE_ERROR",
        questioned_cost_cents=250_000,
    )
    in_audit_again = read_agreement(api, agreement_id)
    assert in_audit_again["settlement_status"] == "AUDIT_IN_PROGRESS"
    assert in_audit_again["execution_status"] == "EXECUTED"

    resolve_audit_finding(api, second["id"], "SUSTAINED")
    back_again = read_agreement(api, agreement_id)
    assert back_again["settlement_status"] == "PENDING_FINAL_INVOICE"
    assert back_again["execution_status"] == "EXECUTED"

    assert read_audit_finding(api, first["id"])["disposition"] == "WITHDRAWN"
    assert read_audit_finding(api, second["id"])["disposition"] == "SUSTAINED"
    assert read_audit_finding(api, first["id"])["status"] == "RESOLVED"
    assert read_audit_finding(api, second["id"])["status"] == "RESOLVED"


def test_the_settled_dimension_refuses_an_identical_second_settlement(api):
    """PRD 3.8: "Settling moves `settlement_status` `PENDING_FINAL_INVOICE →
    SETTLED`, requires an `as_built_reference` in the request body, and is refused
    unless three conditions hold: the agreement is in `PENDING_FINAL_INVOICE`
    (otherwise `ERR_SETTLEMENT_STATE_INVALID`), no audit finding of the agreement
    is `OPEN` (otherwise `ERR_OPEN_AUDIT_FINDING`), and at least one cost document
    of the agreement is `ACCEPTED` with a `doc_type` other than `CREDIT_SALVAGE`
    and `INDIRECT` (otherwise `ERR_NO_ELIGIBLE_COST_DOCUMENTATION`)."

    Design: Difficulty/non_linear_state_machine/settlement_dimension_reenters_pending_after_two_audit_cycles_then_locks
    """
    world = world_cost_documents(api, documents=ONE_LABOR_LINE)
    agreement_id = world["agreement_id"]
    finding = raise_audit_finding(
        api, agreement_id, finding_type="UNSUPPORTED_COST", questioned_cost_cents=500_000
    )
    resolve_audit_finding(api, finding["id"], "WITHDRAWN")

    settled = settle_agreement(api, agreement_id, "ASB-2258-0021")
    assert settled["settlement_status"] == "SETTLED"
    assert settled["execution_status"] == "EXECUTED"
    assert_settlement_figures(
        settled,
        cost_basis="ACTUAL_BASIS",
        eligible_cost_cents=12_345_678,
        indirect_cost_cents=1_543_210,
        betterment_credit_cents=4_444_444,
        net_allowable_cents=9_444_444,
        participation_tier_pct=95,
        state_share_cents=8_972_222,
        owner_share_cents=472_222,
    )
    assert read_project(api, world["project_id"])[
        "total_committed_reimbursement_cents"
    ] == 8_972_222

    validate_error(
        api.final_settlement(
            agreement_id,
            {"as_built_reference": "ASB-2258-0021"},
            make_agreement_officer_headers(OFFICER_USER_ID),
        ),
        "ERR_SETTLEMENT_STATE_INVALID",
    )

    after = read_agreement(api, agreement_id)
    assert after["settlement_status"] == "SETTLED"
    assert_version_unchanged(settled, after)


def test_the_execution_state_rung_answers_before_the_authority_rung(api):
    """PRD 2.9: "Validation is a strictly ordered ladder, not a set of independent
    checks. Rungs are evaluated in the order below, and **the first violated rung
    decides the response; no later rung is evaluated.**"

    Design: Difficulty/priority_pair_validation_conflict/state_priority_nine_beats_fiscal_priority_twentynine_on_agreement_execute
    """
    world = world_agreement_drafted(
        api, project_overrides={"reimbursement_authority_cents": 26_000_000}
    )
    officer = make_agreement_officer_headers(OFFICER_USER_ID)
    assert world["agreement"]["execution_status"] == "DRAFT"
    assert world["agreement"]["state_share_cents"] == CANON_ESTIMATE_STATE_SHARE_CENTS

    validate_error(
        api.execute_agreement(world["agreement_id"], officer),
        "ERR_AGREEMENT_NOT_EXECUTABLE",
    )

    circulated = circulate_agreement(api, world["agreement_id"])
    assert circulated["execution_status"] == "PENDING_OWNER_SIGNATURE"

    validate_error(
        api.execute_agreement(world["agreement_id"], officer), "ERR_AUTHORITY_EXCEEDED"
    )

    after = read_agreement(api, world["agreement_id"])
    assert after["execution_status"] == "PENDING_OWNER_SIGNATURE"
    assert after["executed_by_user_id"] is None
    assert read_project(api, world["project_id"])[
        "total_committed_reimbursement_cents"
    ] == 0


def test_the_authority_rung_admits_a_ledger_that_lands_exactly_on_the_ceiling(api):
    """PRD 3.8: "the project's `total_committed_reimbursement_cents` plus this
    agreement's `state_share_cents` must be no greater than the project's
    `reimbursement_authority_cents` (otherwise `ERR_AUTHORITY_EXCEEDED`)."

    Design: Difficulty/priority_pair_validation_conflict/state_priority_nine_beats_fiscal_priority_twentynine_on_agreement_execute
    """
    world = world_agreement_circulated(
        api, project_overrides={"reimbursement_authority_cents": 26_000_000}
    )
    officer = make_agreement_officer_headers(OFFICER_USER_ID)

    validate_error(
        api.execute_agreement(world["agreement_id"], officer), "ERR_AUTHORITY_EXCEEDED"
    )
    assert read_agreement(api, world["agreement_id"])["execution_status"] == (
        "PENDING_OWNER_SIGNATURE"
    )

    raised = revise_project(
        api,
        world["project_id"],
        reimbursement_authority_cents=CANON_ESTIMATE_STATE_SHARE_CENTS,
    )
    assert raised["reimbursement_authority_cents"] == CANON_ESTIMATE_STATE_SHARE_CENTS
    assert raised["clearance_posture"] == "CLEARANCE_PENDING"

    executed = validate_success(api.execute_agreement(world["agreement_id"], officer))
    assert executed["execution_status"] == "EXECUTED"
    assert executed["executed_by_user_id"] == OFFICER_USER_ID

    project = read_project(api, world["project_id"])
    assert project["total_committed_reimbursement_cents"] == (
        CANON_ESTIMATE_STATE_SHARE_CENTS
    )
    assert project["clearance_posture"] == "CLEARANCE_PENDING"


def _owner_driven_onto_hold(api):
    """A circulated agreement whose owner then breaches two commitments."""
    world = world_agreement_circulated(
        api, project_overrides={"name": "SR-14 Widening Section 5"}
    )
    add_second_relocate_chain(
        api,
        world,
        facility_overrides={
            **SECOND_EASEMENT_FACILITY,
            "station_begin": 200.0,
            "station_end": 240.0,
            "offset_ft": 12.5,
            "depth_in": 48,
        },
        conflict_overrides={"conflict_station": 220.0, "clearance_deficiency_in": 14},
        plan_overrides={
            "estimated_cost_cents": 20_000_000,
            "replacement_in_kind_cost_cents": 20_000_000,
            "proposed_capacity_ratio": 1.00,
            "work_days": 9,
        },
    )
    commitment_a = commit_window(api, world["plan_id"], world["owner_id"])
    commitment_b = commit_window(
        api,
        world["plan_b_id"],
        world["owner_id"],
        window_start="2027-05-05T00:00:00Z",
        window_end="2027-05-20T00:00:00Z",
        committed_work_days=9,
    )

    set_clock(api, "2027-04-28T00:00:00Z")
    report_complete(api, commitment_a["id"], world["owner_id"])
    set_clock(api, "2027-05-28T00:00:00Z")
    breached = report_complete(api, commitment_b["id"], world["owner_id"])
    assert breached["status"] == "BREACHED"

    world["commitment_id"] = commitment_a["id"]
    world["commitment_b_id"] = commitment_b["id"]
    world["owner"] = read_owner(api, world["owner_id"])
    return world


def test_a_hold_earned_on_another_entity_stops_the_agreement_from_executing(api):
    """PRD 2.9: "The counterparty owner's `reimbursement_hold` is false — otherwise
    `ERR_OWNER_ON_REIMBURSEMENT_HOLD`. Applies to agreement execution and final
    settlement."

    Design: Difficulty/cross_entity_state_dependency/agreement_execute_depends_on_utility_owner_reimbursement_hold
    """
    world = _owner_driven_onto_hold(api)
    officer = make_agreement_officer_headers(OFFICER_USER_ID)
    assert world["owner"]["reimbursement_hold"] is True
    assert world["owner"]["delinquency_strikes"] == 2

    before = read_agreement(api, world["agreement_id"])
    assert before["execution_status"] == "PENDING_OWNER_SIGNATURE"
    assert before["state_share_cents"] == CANON_ESTIMATE_STATE_SHARE_CENTS

    validate_error(
        api.execute_agreement(world["agreement_id"], officer),
        "ERR_OWNER_ON_REIMBURSEMENT_HOLD",
    )

    after = read_agreement(api, world["agreement_id"])
    assert after["execution_status"] == "PENDING_OWNER_SIGNATURE"
    assert after["executed_by_user_id"] is None
    assert_version_unchanged(before, after)
    assert read_project(api, world["project_id"])[
        "total_committed_reimbursement_cents"
    ] == 0


def test_releasing_the_hold_lets_the_unchanged_agreement_execute(api):
    """PRD 3.1: "Releasing the hold requires a `release_note` and performs four
    things in one transaction: `reimbursement_hold` returns to false,
    `delinquency_strikes` resets to 0, every reimbursement agreement of this owner
    sitting in `settlement_status` `HELD` returns to `PENDING_FINAL_INVOICE`, and
    every cost document of those agreements sitting in `review_status` `HELD`
    returns to `SUBMITTED`."

    Design: Difficulty/cross_entity_state_dependency/agreement_execute_depends_on_utility_owner_reimbursement_hold
    """
    world = _owner_driven_onto_hold(api)
    officer = make_agreement_officer_headers(OFFICER_USER_ID)
    validate_error(
        api.execute_agreement(world["agreement_id"], officer),
        "ERR_OWNER_ON_REIMBURSEMENT_HOLD",
    )
    blocked = read_agreement(api, world["agreement_id"])

    released = release_owner_hold(api, world["owner_id"], RELEASE_NOTE)
    assert released["reimbursement_hold"] is False
    assert released["delinquency_strikes"] == 0

    executed = validate_success(api.execute_agreement(world["agreement_id"], officer))
    assert executed["execution_status"] == "EXECUTED"
    assert executed["executed_by_user_id"] == OFFICER_USER_ID
    assert executed["state_share_cents"] == blocked["state_share_cents"]
    assert executed["settlement_status"] == "NOT_STARTED"

    assert read_project(api, world["project_id"])[
        "total_committed_reimbursement_cents"
    ] == CANON_ESTIMATE_STATE_SHARE_CENTS


def test_voiding_an_executed_agreement_returns_the_ledger_to_exactly_zero(api):
    """PRD 3.8: "Voiding an agreement that had reached `EXECUTED` additionally
    reverses its ledger effect: the project's
    `total_committed_reimbursement_cents` drops by exactly this agreement's
    `state_share_cents` and returns to its pre-execution value, and the posture is
    recomputed from the restored ledger."

    Design: Difficulty/compensating_invariant/void_after_execute_restores_the_committed_reimbursement_ledger_to_the_cent
    """
    world = world_agreement_circulated(
        api, project_overrides={"name": "SR-14 Widening Section 7"}
    )
    before = read_project(api, world["project_id"])
    assert before["total_committed_reimbursement_cents"] == 0
    assert before["clearance_posture"] == "CLEARANCE_PENDING"

    executed = validate_success(
        api.execute_agreement(
            world["agreement_id"], make_agreement_officer_headers(OFFICER_USER_ID)
        )
    )
    assert executed["execution_status"] == "EXECUTED"
    committed = read_project(api, world["project_id"])
    assert committed["total_committed_reimbursement_cents"] == (
        CANON_ESTIMATE_STATE_SHARE_CENTS
    )

    voided = void_agreement(api, world["agreement_id"], VOID_REASON)
    assert voided["execution_status"] == "VOIDED"
    assert voided["settlement_status"] == "VOIDED_OUT"

    after = read_project(api, world["project_id"])
    assert after["total_committed_reimbursement_cents"] == 0
    assert after["clearance_posture"] == "CLEARANCE_PENDING"


def test_the_voided_agreement_keeps_its_figures_and_the_forward_estimate(api):
    """PRD 3.8: "That ledger, `total_committed_reimbursement_cents`, is the sum of
    `state_share_cents` over every agreement of the project whose
    `execution_status` is `EXECUTED`."

    Design: Difficulty/compensating_invariant/void_after_execute_restores_the_committed_reimbursement_ledger_to_the_cent
    """
    world = world_agreement_executed(
        api, project_overrides={"name": "SR-14 Widening Section 7"}
    )
    assert read_project(api, world["project_id"])[
        "total_committed_reimbursement_cents"
    ] == CANON_ESTIMATE_STATE_SHARE_CENTS

    void_agreement(api, world["agreement_id"], VOID_REASON)

    agreement = read_agreement(api, world["agreement_id"])
    assert_settlement_figures(
        agreement,
        cost_basis="ESTIMATE_BASIS",
        eligible_cost_cents=40_000_000,
        indirect_cost_cents=5_000_000,
        betterment_credit_cents=14_400_000,
        net_allowable_cents=30_600_000,
        participation_tier_pct=95,
        state_share_cents=CANON_ESTIMATE_STATE_SHARE_CENTS,
        owner_share_cents=1_530_000,
    )

    project = read_project(api, world["project_id"])
    assert project["total_committed_reimbursement_cents"] == 0
    assert project["estimated_state_liability_cents"] == CANON_STATE_LIABILITY_CENTS


def test_final_billing_cannot_open_before_the_execution_dimension_allows_it(api):
    """PRD 3.8: "Opening final billing moves `settlement_status` `NOT_STARTED →
    PENDING_FINAL_INVOICE` and requires `execution_status` to be `EXECUTED`;
    attempted on an unexecuted agreement it returns
    `ERR_AGREEMENT_NOT_EXECUTABLE`, and attempted on an agreement whose settlement
    has already started it returns `ERR_SETTLEMENT_STATE_INVALID`."

    Design: Corner/state_machines/open_final_billing_before_execution_is_blocked_by_the_execution_dimension
    """
    world = world_agreement_drafted(api)
    officer = make_agreement_officer_headers(OFFICER_USER_ID)
    assert world["agreement"]["execution_status"] == "DRAFT"
    assert world["agreement"]["settlement_status"] == "NOT_STARTED"

    validate_error(
        api.open_final_billing(world["agreement_id"], officer),
        "ERR_AGREEMENT_NOT_EXECUTABLE",
    )

    after = read_agreement(api, world["agreement_id"])
    assert after["execution_status"] == "DRAFT"
    assert after["settlement_status"] == "NOT_STARTED"
    assert_version_unchanged(world["agreement"], after)


def test_the_two_dimensions_of_one_agreement_row_advance_independently(api):
    """PRD 3.8: "`execution_status` tracks the contract — `DRAFT`,
    `PENDING_OWNER_SIGNATURE`, `EXECUTED`, `VOIDED` — while `settlement_status`
    tracks the money — `NOT_STARTED`, `PENDING_FINAL_INVOICE`, `HELD`,
    `AUDIT_IN_PROGRESS`, `SETTLED`, `VOIDED_OUT`."

    Design: Corner/state_machines/agreement_execution_and_settlement_dimensions_advance_independently
    """
    world = world_agreement_executed(api)
    officer = make_agreement_officer_headers(OFFICER_USER_ID)
    assert world["agreement"]["execution_status"] == "EXECUTED"
    assert world["agreement"]["settlement_status"] == "NOT_STARTED"
    assert world["agreement"]["state_share_cents"] == CANON_ESTIMATE_STATE_SHARE_CENTS

    billing = validate_success(api.open_final_billing(world["agreement_id"], officer))
    assert billing["execution_status"] == "EXECUTED"
    assert billing["settlement_status"] == "PENDING_FINAL_INVOICE"

    finding = raise_audit_finding(
        api,
        world["agreement_id"],
        finding_type="UNSUPPORTED_COST",
        questioned_cost_cents=100_000,
    )
    in_audit = read_agreement(api, world["agreement_id"])
    assert in_audit["execution_status"] == "EXECUTED"
    assert in_audit["settlement_status"] == "AUDIT_IN_PROGRESS"
    assert read_project(api, world["project_id"])[
        "total_committed_reimbursement_cents"
    ] == CANON_ESTIMATE_STATE_SHARE_CENTS

    voided = void_agreement(
        api, world["agreement_id"], "Scope withdrawn from the letting."
    )
    assert voided["execution_status"] == "VOIDED"
    assert voided["settlement_status"] == "VOIDED_OUT"
    assert read_project(api, world["project_id"])[
        "total_committed_reimbursement_cents"
    ] == 0
    assert read_audit_finding(api, finding["id"])["status"] == "OPEN"


def test_only_executed_agreements_enter_the_committed_ledger(api):
    """PRD 3.8: "Agreements in `DRAFT`, `PENDING_OWNER_SIGNATURE` or `VOIDED`
    contribute nothing."

    Design: Corner/calculations/committed_reimbursement_ledger_counts_executed_agreements_only
    """
    world = world_plan_approved(api)
    add_second_relocate_chain(
        api,
        world,
        facility_overrides=SECOND_EASEMENT_FACILITY,
        conflict_overrides={"conflict_station": 320.0, "clearance_deficiency_in": 14},
        plan_overrides={
            "estimated_cost_cents": 5_000_000,
            "replacement_in_kind_cost_cents": 5_000_000,
            "proposed_capacity_ratio": 1.00,
            "work_days": 4,
        },
    )
    first = draft_agreement(api, world["plan_id"], 45_000_000)
    second = draft_agreement(api, world["plan_b_id"], 5_625_000)
    assert first["state_share_cents"] == CANON_ESTIMATE_STATE_SHARE_CENTS
    assert second["state_share_cents"] == 5_343_750
    assert second["participation_tier_pct"] == 95
    assert second["owner_share_cents"] == 281_250

    officer = make_agreement_officer_headers(OFFICER_USER_ID)
    assert circulate_agreement(api, first["id"])["execution_status"] == (
        "PENDING_OWNER_SIGNATURE"
    )
    assert circulate_agreement(api, second["id"])["execution_status"] == (
        "PENDING_OWNER_SIGNATURE"
    )
    assert read_project(api, world["project_id"])[
        "total_committed_reimbursement_cents"
    ] == 0

    validate_success(api.execute_agreement(first["id"], officer))
    assert read_project(api, world["project_id"])[
        "total_committed_reimbursement_cents"
    ] == CANON_ESTIMATE_STATE_SHARE_CENTS

    validate_success(api.execute_agreement(second["id"], officer))
    assert read_project(api, world["project_id"])[
        "total_committed_reimbursement_cents"
    ] == 34_413_750

    rows, meta = validate_paginated(
        api.list_agreements(
            make_program_admin_headers(), {"execution_status": "EXECUTED"}
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}
