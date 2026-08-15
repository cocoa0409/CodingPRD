"""Transitive cascades, compensating invariants, consistency model.

Covers queue-A `transitive_cascade/*` and `compensating_invariant/*` plus
queue-B `consistency_model/immediate_visibility_of_cascade_in_same_response_chain`
and `cross_cutting_complexity_layers/scheduled_overdue_flip_by_clock`.
"""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    ApiErrorId,
    assert_instant_equal,
    create_and_approve_case,
    create_revocation_task,
    create_asset_item,
    create_benefits_notice,
    create_covenant_ack,
    set_clock,
    make_task_ready,
    execute_task,
    verify_task,
    calculate_statement,
    approve_statement,
    disburse_statement,
    drive_case_to_payroll_pending,
    HR_INTAKE,
    HR_APPROVER,
    HR_REVIEWER,
    HR_DIRECTOR,
    IT_OP,
    IT_VER,
    CLERK,
    PAYROLL_CALC,
    PAYROLL_APPROVER,
    BEN_ADMIN,
    MGR,
)


class TestAssetDefaultCascade:
    def test_asset_default_cascades_to_statement(self):
        """PRD §3.4: "The item's `deduction_status` becomes `APPLIED`, and the
        default cascades: the case's `deduction_total_cents` is recomputed, and
        if the statement is `CALCULATED` or `APPROVED` its deduction total and
        `net_pay_cents` are recomputed in place under the §3.3 waterfall."

        TOOLING, cost=100000, issued=2026-08-01, return_due=2026-08-13 ->
        age=12d, dep=12*10=120bps, value=100000*0.988=98800.

        Design: Difficulty/transitive_cascade/asset_default_cascades_to_statement_and_close_gate
        """
        case = create_and_approve_case(employee_ref="E-CASC")
        item = create_asset_item(
            case["id"], asset_tag="T1", asset_kind="TOOLING",
            replacement_cost_cents=100000, issued_date="2026-08-01T00:00:00Z",
        )
        stmts = get_success_data(api_client.list_case_statements(case["id"], PAYROLL_CALC))
        stmt = stmts[0]
        calc = calculate_statement(stmt, regular_wages_cents=200000)
        assert calc["net_pay_cents"] == 200000
        # Drive case to PAYROLL_PENDING so mark-defaulted is legal, then advance
        # the clock past return_due_at + 7 days.
        task = create_revocation_task(case["id"], system_name="EMAIL", sequence_rank=1)
        set_clock("2026-08-10T17:00:00Z")
        execute_task(task["id"], outcome="SUCCESS")
        verify_task(task["id"], outcome="VERIFIED")
        set_clock("2026-08-21T00:00:00Z")

        defaulted = validate_success(api_client.mark_asset_defaulted(item["id"], PAYROLL_CALC))
        assert defaulted["status"] == "DEFAULTED"
        assert defaulted["deduction_status"] == "APPLIED"
        assert defaulted["deduction_amount_cents"] == 98800

        case_after = get_success_data(api_client.get_case(case["id"], HR_INTAKE))
        assert case_after["deduction_total_cents"] == 98800
        assert case_after["asset_posture"] == "DEFAULTED"

        stmt_after = get_success_data(api_client.get_statement(stmt["id"], PAYROLL_CALC))
        assert stmt_after["deduction_total_cents"] == 98800
        assert stmt_after["net_pay_cents"] == 200000 - 98800

    def test_asset_default_updates_case_deduction_total_exactly(self):
        """PRD §3.4: "The case's `deduction_total_cents` is the sum of
        `deduction_amount_cents` across exactly those items whose
        `deduction_status` is `APPLIED`."

        Design: Difficulty/transitive_cascade/asset_default_cascades_to_statement_and_close_gate
        """
        case = create_and_approve_case(employee_ref="E-CASC2")
        item_a = create_asset_item(
            case["id"], asset_tag="T1", asset_kind="TOOLING",
            replacement_cost_cents=100000, issued_date="2026-08-01T00:00:00Z",
        )
        # Drive case to PAYROLL_PENDING
        task = create_revocation_task(case["id"], system_name="EMAIL", sequence_rank=1)
        set_clock("2026-08-10T17:00:00Z")
        execute_task(task["id"], outcome="SUCCESS")
        verify_task(task["id"], outcome="VERIFIED")
        set_clock("2026-08-21T00:00:00Z")
        validate_success(api_client.mark_asset_defaulted(item_a["id"], PAYROLL_CALC))

        case_after = get_success_data(api_client.get_case(case["id"], HR_INTAKE))
        item_after = get_success_data(api_client.get_asset_item(item_a["id"], CLERK))
        assert case_after["deduction_total_cents"] == item_after["deduction_amount_cents"]


class TestRevocationVerifyCascade:
    def test_revocation_verify_cascades_case_to_payroll_pending(self):
        """PRD §3.2: "the posture turning `COMPLETE` advances the case again,
        notifying the manager with `REVOCATION_COMPLETE`. That second advancement
        has two orders. In the revocation-first order the case moves to
        `PAYROLL_PENDING`, where it waits for payroll."

        Design: Difficulty/transitive_cascade/revocation_verify_cascades_to_notice_queue_and_covenant_reminder
        """
        case = create_and_approve_case(employee_ref="E-CAS2")
        task = create_revocation_task(case["id"], system_name="EMAIL", sequence_rank=1)
        set_clock("2026-08-10T17:00:00Z")
        execute_task(task["id"], outcome="SUCCESS")
        verified = verify_task(task["id"], outcome="VERIFIED")
        assert verified["status"] == "VERIFIED"

        case_after = get_success_data(api_client.get_case(case["id"], HR_INTAKE))
        assert case_after["revocation_posture"] == "COMPLETE"
        assert case_after["status"] == "PAYROLL_PENDING"

    def test_revocation_verify_cascades_benefits_notice_queue_and_covenant_reminder(self):
        """PRD §3.2: "Both advancements queue the case's benefits notices and
        arm its covenant reminders, as §3.6 details." PRD §3.6: "every `DRAFT`
        notice of the case is queued automatically and stamped with a `send_by`
        deadline measured in calendar days from the determined last day, landing
        at 17:00 UTC on the target date: forty-four days for a `COBRA_ELECTION`"
        and "every pending acknowledgment is armed with a `remind_at` set to
        three days after the determined last day at 09:00 UTC."

        DL=2026-08-10 -> COBRA send_by = 2026-09-23T17:00:00Z; remind_at =
        2026-08-13T09:00:00Z.

        Design: Difficulty/transitive_cascade/revocation_verify_cascades_to_notice_queue_and_covenant_reminder
        """
        case = create_and_approve_case(employee_ref="E-CAS2B")
        notice = create_benefits_notice(case["id"], notice_kind="COBRA_ELECTION")
        ack = create_covenant_ack(case["id"], covenant_kind="NON_COMPETE")
        task = create_revocation_task(case["id"], system_name="EMAIL", sequence_rank=1)
        set_clock("2026-08-10T17:00:00Z")
        execute_task(task["id"], outcome="SUCCESS")
        verify_task(task["id"], outcome="VERIFIED")

        notice_after = get_success_data(api_client.get_benefits_notice(notice["id"], BEN_ADMIN))
        assert notice_after["status"] == "QUEUED"
        assert_instant_equal(notice_after["send_by"], "2026-09-23T17:00:00Z")

        ack_after_list = get_success_data(
            api_client.list_case_covenant_acks(case["id"], HR_INTAKE)
        )
        ack_after = [a for a in ack_after_list if a["id"] == ack["id"]][0]
        assert_instant_equal(ack_after["remind_at"], "2026-08-13T09:00:00Z")


class TestAssetWaiveCompensatingInvariant:
    def test_asset_waive_from_tracked_zeroes_nothing(self):
        """PRD §3.4: "waiving an item whose deduction was `COMPUTED` or
        `APPLIED` moves the deduction to `WAIVED`, zeroes its amount, and
        recomputes the case total." Waiving a TRACKED item with no deduction
        leaves the case total unchanged (no drift).

        Design: Difficulty/compensating_invariant/asset_waive_restores_deduction_total
        """
        case = create_and_approve_case(employee_ref="E-INV1B")
        item = create_asset_item(
            case["id"], asset_tag="T1", asset_kind="TOOLING",
            replacement_cost_cents=100000, issued_date="2026-08-01T00:00:00Z",
        )
        case_before = get_success_data(api_client.get_case(case["id"], HR_INTAKE))
        assert case_before["deduction_total_cents"] == 0

        waived = validate_success(api_client.waive_asset_item(
            item["id"], {"waive_reason": "waived at intake"}, CLERK
        ))
        assert waived["status"] == "WAIVED"

        case_after = get_success_data(api_client.get_case(case["id"], HR_INTAKE))
        assert case_after["deduction_total_cents"] == 0


class TestRehireReturnLoopInvariant:
    def test_rehire_return_resubmit_loop_conserves_review_identity(self):
        """PRD §3.7: "A director may instead return a `SUBMITTED` review with a
        `return_reason`, moving it to `RETURNED`, and the reviewer resubmits from
        `RETURNED` back to `SUBMITTED` with a fresh `rationale`; the
        return–submit loop may repeat." PRD §2.10: "A case admits exactly one
        FinalPayStatement, exactly one KnowledgeTransferPlan, and exactly one
        RehireEligibilityReview."

        Design: Difficulty/compensating_invariant/rehire_return_resubmit_loop_conserves_review_identity
        """
        case, stmt, _task = _drive_to_clearance(employee_ref="E-INV2")
        reviews = get_success_data(api_client.list_case_rehire_reviews(case["id"], HR_REVIEWER))
        review = reviews[0]
        validate_success(api_client.submit_rehire_review(
            review["id"], {"recommended_code": "ELIGIBLE", "rationale": "v1"}, HR_REVIEWER
        ))
        validate_success(api_client.return_rehire_review(
            review["id"], {"return_reason": "needs exit-interview context"}, HR_DIRECTOR
        ))
        resubmitted = validate_success(api_client.submit_rehire_review(
            review["id"],
            {"recommended_code": "ELIGIBLE_WITH_CONDITIONS", "rationale": "v2 revised"},
            HR_REVIEWER,
        ))
        assert resubmitted["id"] == review["id"]
        assert resubmitted["recommended_code"] == "ELIGIBLE_WITH_CONDITIONS"
        assert resubmitted["finalized_at"] is None

        reviews_after = get_success_data(
            api_client.list_case_rehire_reviews(case["id"], HR_REVIEWER)
        )
        assert len(reviews_after) == 1
        assert reviews_after[0]["id"] == review["id"]

        case_after = get_success_data(api_client.get_case(case["id"], HR_INTAKE))
        assert case_after["rehire_code"] is None

    def test_rehire_return_resubmit_loop_does_not_mark_finalized(self):
        """PRD §3.7: "An `HRDirector` then finalizes a `SUBMITTED` review,
        stamping `finalized_at` and landing it in `FINALIZED`" — only finalize
        stamps; the return+resubmit loop leaves `finalized_at` null.

        Design: Difficulty/compensating_invariant/rehire_return_resubmit_loop_conserves_review_identity
        """
        case, stmt, _task = _drive_to_clearance(employee_ref="E-INV2B")
        reviews = get_success_data(api_client.list_case_rehire_reviews(case["id"], HR_REVIEWER))
        review = reviews[0]
        validate_success(api_client.submit_rehire_review(
            review["id"], {"recommended_code": "ELIGIBLE", "rationale": "v1"}, HR_REVIEWER
        ))
        validate_success(api_client.return_rehire_review(
            review["id"], {"return_reason": "rework"}, HR_DIRECTOR
        ))
        resub = validate_success(api_client.submit_rehire_review(
            review["id"], {"recommended_code": "ELIGIBLE", "rationale": "v2"}, HR_REVIEWER
        ))
        assert resub["finalized_at"] is None
        assert resub["status"] == "SUBMITTED"


class TestConsistencyModelImmediateVisibility:
    def test_immediate_visibility_of_cascade_in_same_response_chain(self):
        """PRD §2.11: "An OffboardingCase is reconciled against its children
        continuously, not at checkpoints... Each such reconciliation is a real
        mutation of the case: `updated_at` is refreshed and `version` increments
        by one on every transition, automatic or client-driven."

        After mark-defaulted returns 200, the very next GET of case and
        statement must already reflect the recomputed totals — no lag.

        OTHER asset, cost=10000, issued=2026-08-01, return_due=2026-08-13 ->
        age=12d, dep=120bps, deduction=10000*0.988=9880.

        Design: Corner/consistency_model/immediate_visibility_of_cascade_in_same_response_chain
        """
        case = create_and_approve_case(employee_ref="E-CONS1")
        item = create_asset_item(
            case["id"], asset_tag="U1", asset_kind="OTHER",
            replacement_cost_cents=10000, issued_date="2026-08-01T00:00:00Z",
        )
        stmts = get_success_data(api_client.list_case_statements(case["id"], PAYROLL_CALC))
        stmt = stmts[0]
        calculate_statement(stmt, regular_wages_cents=50000)
        # PAYROLL_PENDING + clock past return_due + 7
        task = create_revocation_task(case["id"], system_name="EMAIL", sequence_rank=1)
        set_clock("2026-08-10T17:00:00Z")
        execute_task(task["id"], outcome="SUCCESS")
        verify_task(task["id"], outcome="VERIFIED")
        set_clock("2026-08-21T00:00:00Z")
        validate_success(api_client.mark_asset_defaulted(item["id"], PAYROLL_CALC))

        case_after = get_success_data(api_client.get_case(case["id"], PAYROLL_CALC))
        stmt_after = get_success_data(api_client.get_statement(stmt["id"], PAYROLL_CALC))
        assert case_after["deduction_total_cents"] == 9880
        assert stmt_after["deduction_total_cents"] == 9880
        assert stmt_after["net_pay_cents"] == 50000 - 9880


class TestScheduledOverdueFlip:
    def test_scheduled_overdue_flip_by_clock(self):
        """PRD §3.4: "Once the logical clock passes `return_due_at`, the
        scheduler moves a still-`TRACKED` item to `OVERDUE`." PRD §2.4: "Each
        set call fires every system-scheduler transition whose time predicate
        now holds, in one sweep: ... tracked assets past their return deadline
        become overdue..."

        DL=2026-08-10 -> return_due_at = 2026-08-13 (DL + 3 days). Clock to
        2026-08-14 flips the item.

        Design: Corner/cross_cutting_complexity_layers/scheduled_overdue_flip_by_clock
        """
        case = create_and_approve_case(employee_ref="E-SCH1")
        item = create_asset_item(
            case["id"], asset_tag="M1", asset_kind="MONITOR",
            replacement_cost_cents=30000, issued_date="2026-01-01T00:00:00Z",
        )
        assert item["status"] == "TRACKED"
        set_clock("2026-08-14T00:00:00Z")
        item_after = get_success_data(api_client.get_asset_item(item["id"], CLERK))
        assert item_after["status"] == "OVERDUE"
        case_after = get_success_data(api_client.get_case(case["id"], HR_INTAKE))
        assert case_after["asset_posture"] == "DEFAULTED"


# ---------------------------------------------------------------------------
# Local helper: drive a case all the way to CLEARANCE_IN_PROGRESS.
# ---------------------------------------------------------------------------

def _drive_to_clearance(**case_overrides):
    """case -> approve -> task verified -> statement calculate + approve.
    Returns (refreshed_case, approved_statement, task)."""
    case, stmt, task = _drive_through_payroll_pending(**case_overrides)
    approved = approve_statement(stmt["id"])
    refreshed_case = get_success_data(api_client.get_case(case["id"], HR_INTAKE))
    return refreshed_case, approved, task


def _drive_through_payroll_pending(**case_overrides):
    case = create_and_approve_case(**case_overrides)
    task = create_revocation_task(case["id"], system_name="EMAIL", sequence_rank=1)
    set_clock("2026-08-10T17:00:00Z")
    execute_task(task["id"], outcome="SUCCESS")
    verify_task(task["id"], outcome="VERIFIED")
    stmts = get_success_data(api_client.list_case_statements(case["id"], PAYROLL_CALC))
    stmt = stmts[0]
    calculate_statement(stmt)
    refreshed = get_success_data(api_client.get_case(case["id"], HR_INTAKE))
    return refreshed, stmt, task
