"""Cyclic lifecycles: the claim suspend/resubmit loop and the audit appeal re-entry."""
import pytest

from test_helpers import (
    analyze_part,
    approve_claim,
    assert_date_equals,
    assert_instant_equals,
    assert_ratio_four_decimals,
    decide_appeal,
    file_appeal,
    get_audit,
    get_appeal,
    get_claim,
    get_dealer,
    get_finding,
    list_claim_edits,
    list_ledger_entries,
    parts_return_for_claim,
    pay_claim,
    receive_part,
    resubmit_claim,
    set_clock,
    setup_audit_with_findings,
    setup_claim,
)

CA_PROFILE = {
    "state_code": "CA",
    "markup_cap_pct": 0.30,
    "labor_rate_method": "RETAIL_SAMPLE",
    "min_sample_repair_orders": 5,
    "max_labor_rate_cents": 19500,
    "deemed_approved_days": 30,
    "appeal_window_days": 30,
}

BRAKE_OPERATION = {
    "op_code": "A1234-56",
    "description": "Front brake pad replacement",
    "standard_time_hours": 1.5,
    "max_time_hours": 2.5,
    "category": "BASIC",
    "requires_causal_part": True,
    "causal_failure_group": "BRAKE_FRONT",
    "overlap_group": "BRAKE_FRONT",
}

BRAKE_PART = {
    "part_number": "BRK-PAD-9931",
    "description": "Front brake pad set",
    "dealer_net_cents": 24799,
    "failure_group": "BRAKE_FRONT",
    "return_required": True,
    "retention_days": 30,
}

COVERED_TERMS = {
    "model_year": 2024,
    "warranty_start_date": "2024-01-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
}

ELEC_OPERATION = {
    "op_code": "AUD-100",
    "description": "Electrical harness repair",
    "standard_time_hours": 2.0,
    "max_time_hours": 3.0,
    "category": "BASIC",
    "requires_causal_part": True,
    "causal_failure_group": "ELEC",
    "overlap_group": "ELEC",
}

ELEC_PART = {
    "part_number": "AUD-P1",
    "description": "Electrical harness",
    "dealer_net_cents": 24000,
    "failure_group": "ELEC",
    "return_required": False,
    "retention_days": 0,
}

ELEC_NARRATIVE = {
    "complaint_text": "Customer reports intermittent electrical fault.",
    "cause_text": "Harness chafed through insulation layer.",
    "correction_text": "Replaced the electrical harness assembly.",
}

RESUBMISSION = {
    "claimed_labor_hours": 1.5,
    "claimed_parts_qty": 3,
    "complaint_text": "Customer reports brake squeal at low speed.",
    "cause_text": "Front brake pads worn beyond specification.",
    "correction_text": "Replaced front brake pads, corrected the claimed time.",
}


def build_excessive_time_claim():
    """A claim submitted at 2.2 hours, above the 1.5-hour flat rate but under the 2.5 max."""
    set_clock("2026-05-01T00:00:00Z")
    world = setup_claim(
        profile_overrides=CA_PROFILE,
        dealer_overrides={
            "dealer_code": "D1",
            "name": "Dealer One",
            "vehicles_in_operation": 100,
            "initial_labor_rate_cents": 13750,
            "initial_parts_markup_pct": 0.40,
        },
        vehicle_overrides=COVERED_TERMS,
        operation_overrides=BRAKE_OPERATION,
        part_overrides=BRAKE_PART,
        claim_overrides={
            "repair_order_number": "RO-NL-1",
            "repair_date": "2026-04-10",
            "odometer_at_repair": 20000,
            "claimed_labor_hours": 2.2,
            "claimed_parts_qty": 3,
            "complaint_text": "Customer reports brake squeal at low speed.",
            "cause_text": "Front brake pads worn beyond specification.",
            "correction_text": "Replaced front brake pads and verified normal braking.",
        },
    )
    return world


def build_appealed_extrapolation_audit():
    """An issued audit of 60,000 cents, appealed on both findings inside the window."""
    set_clock("2026-05-01T00:00:00Z")
    specs = []
    for order, (ro, date, odo) in enumerate(
        [
            ("RO-A1", "2026-01-05", 11000),
            ("RO-A2", "2026-02-10", 13000),
            ("RO-A3", "2026-03-20", 15000),
        ]
    ):
        specs.append(
            {
                "claim": dict(
                    ELEC_NARRATIVE,
                    repair_order_number=ro,
                    repair_date=date,
                    odometer_at_repair=odo,
                    claimed_labor_hours=2.0,
                    claimed_parts_qty=1,
                ),
                "approve": {"approved_labor_hours": 2.0, "approved_parts_qty": 1},
                "pay": True,
            }
        )
    world = setup_audit_with_findings(
        specs,
        [
            {
                "claim_index": 0,
                "unsupported_amount_cents": 30000,
                "finding_code": "NO_REPAIR_ORDER",
                "evidence_note": "No repair order on file for this claim.",
            },
            {
                "claim_index": 1,
                "unsupported_amount_cents": 10000,
                "finding_code": "TIME_NOT_DOCUMENTED",
                "evidence_note": "Technician time is not documented on the order.",
            },
        ],
        audit_overrides={
            "period_start": "2026-01-01",
            "period_end": "2026-07-01",
            "sample_size": 2,
            "lead_auditor_user_id": "auditor-lead-1",
        },
        issue=True,
        profile_overrides=CA_PROFILE,
        dealer_overrides={
            "dealer_code": "D-AUD",
            "name": "Audit Dealer",
            "vehicles_in_operation": 100,
            "initial_labor_rate_cents": 10000,
            "initial_parts_markup_pct": 0.25,
        },
        operation_overrides=ELEC_OPERATION,
        part_overrides=ELEC_PART,
        vehicle_overrides=COVERED_TERMS,
    )
    assert world["audit"]["total_chargeback_cents"] == 60000
    assert world["audit"]["status"] == "FINDINGS_ISSUED"

    set_clock("2026-05-10T00:00:00Z")
    world["appeal"] = file_appeal(
        world["audit"],
        [world["findings"][0]["id"], world["findings"][1]["id"]],
        world["dealer"]["id"],
        grounds="Repair orders and technician time records are on file for both claims.",
    )
    return world


class TestClaimSuspendResubmitCycle:
    def test_07_the_claim_cycles_back_to_submitted_and_reaches_paid_on_a_second_axis(self):
        """PRD §3.4: "An `EXCESSIVE_TIME` edit fires when `claimed_labor_hours` is strictly greater than the operation's `standard_time_hours`."
        PRD §3.4: "A correction then stamps `resolved_at` on every edit of this claim that is still open, re-runs coverage determination and the provisional pricing pass, and appends a freshly computed edit set."
        PRD §3.4: "Only when the fresh set contains no suspending edit does the claim complete the cycle `SUSPENDED → SUBMITTED`."
        PRD §3.6: "A claim's `payment_status` walks `UNPAID → PAID → DEBITED → CREDIT_REINSTATED` without its `status` ever leaving `APPROVED`: a debited claim is still an approved claim, and the two dimensions must be reported and reasoned about separately."
        PRD §3.6: "A successful payment moves `payment_status` from `UNPAID` to `PAID`, leaves `status` untouched at `APPROVED`, and advances the claim's `version` by 1."

        Design: Difficulty/non_linear_state_machine/claim_suspend_resubmit_cycle_with_independent_payment_dimension
        """
        world = build_excessive_time_claim()
        claim = world["claim"]

        assert claim["status"] == "SUSPENDED"
        assert claim["provisional_labor_amount_cents"] == 30250
        assert claim["provisional_parts_amount_cents"] == 104157
        assert claim["provisional_total_cents"] == 134407
        assert claim["suspend_edit_count"] == 1
        assert claim["payment_status"] == "UNPAID"

        edits = list_claim_edits(claim["id"])
        suspending = [edit for edit in edits if edit["severity"] == "SUSPEND"]
        assert [edit["edit_code"] for edit in suspending] == ["EXCESSIVE_TIME"]
        assert suspending[0]["resolved_at"] is None

        corrected = resubmit_claim(world, **RESUBMISSION)
        assert corrected["status"] == "SUBMITTED", "the SUSPENDED -> SUBMITTED cycle edge"
        assert corrected["provisional_total_cents"] == 124782
        assert corrected["suspend_edit_count"] == 0
        assert corrected["version"] == claim["version"] + 1
        resolved = [
            edit
            for edit in list_claim_edits(claim["id"])
            if edit["edit_code"] == "EXCESSIVE_TIME"
        ]
        assert resolved and all(edit["resolved_at"] is not None for edit in resolved)

        approved = approve_claim(
            claim["id"], approved_labor_hours=1.5, approved_parts_qty=3
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_total_cents"] == 117342
        assert approved["payment_status"] == "UNPAID", (
            "approval never touches the payment dimension"
        )

        paid = pay_claim(claim["id"])
        assert paid["payment_status"] == "PAID"
        assert paid["status"] == "APPROVED"

    def test_08_a_no_defect_analysis_debits_the_paid_claim_without_moving_its_status(self):
        """PRD §3.7: "A timely receipt moves `REQUESTED → RECEIVED`, stamps `received_date`, decrements the dealer's `open_parts_return_count` by 1, advances the dealer's `version` by 1, and advances the obligation's `version` by 1."
        PRD §3.7: "`NO_DEFECT_FOUND` means the dealer replaced a part that was not actually faulty, and `debit_amount_cents` becomes the claim's entire `approved_parts_amount_cents` — the parts side of the claim is clawed back, the labor is not."
        PRD §3.7: "Whenever the resulting debit is greater than zero, the claim's `debited_amount_cents` is increased by it, the claim's `payment_status` moves to `DEBITED` from either `PAID` or `UNPAID`, the claim's `version` advances by 1, and a ledger row with `source_type` `PARTS_NO_DEFECT` is appended for that amount against the dealer, which recomputes the dealer's balance and posture and advances the dealer's `version` by 1."
        PRD §2.8: "Otherwise, a balance of at least 90,000 cents — 900 dollars — puts the dealer in `PROBATION`."

        Design: Difficulty/non_linear_state_machine/claim_suspend_resubmit_cycle_with_independent_payment_dimension
        """
        world = build_excessive_time_claim()
        claim_id = world["claim"]["id"]
        obligation = parts_return_for_claim(claim_id)
        assert obligation["status"] == "REQUESTED"

        resubmit_claim(world, **RESUBMISSION)
        approve_claim(claim_id, approved_labor_hours=1.5, approved_parts_qty=3)
        pay_claim(claim_id)

        received = receive_part(obligation["id"], "2026-05-05")
        assert received["status"] == "RECEIVED"
        assert get_dealer(world["dealer"]["id"])["open_parts_return_count"] == 0

        analyzed = analyze_part(
            obligation["id"],
            analysis_result="NO_DEFECT_FOUND",
            analysis_note="Bench test found the pads within specification.",
        )
        assert analyzed["status"] == "ANALYZED"
        assert analyzed["debit_amount_cents"] == 96717, (
            "the debit is the approved parts amount only, not the 117342 approved total"
        )

        debited = get_claim(claim_id)
        assert debited["payment_status"] == "DEBITED"
        assert debited["status"] == "APPROVED", (
            "a debited claim is still an approved claim"
        )
        assert debited["debited_amount_cents"] == 96717

        dealer = get_dealer(world["dealer"]["id"])
        assert dealer["chargeback_balance_cents"] == 96717
        assert dealer["status"] == "PROBATION"
        rows = list_ledger_entries(dealer["id"])
        assert [row["source_type"] for row in rows] == ["PARTS_NO_DEFECT"]
        assert rows[0]["amount_cents"] == 96717


class TestAuditAppealLoopReentry:
    def test_09_a_partial_decision_returns_the_audit_to_findings_issued_with_a_fresh_deadline(self):
        """PRD §3.8: "On acceptance the appeal opens in `FILED` with `filed_by_dealer_id` taken from `X-User-ID`, `overturned_finding_ids` an empty array, `reviewer_user_id` and `decision_note` null and `reinstated_amount_cents` at 0; each contested finding has its `appeal_id` stamped with the new appeal; and the audit moves `FINDINGS_ISSUED → APPEALED` with its `version` advanced by 1."
        PRD §3.8: "`PARTIAL` requires `overturned_finding_ids` to be a non-empty strict subset of `contested_finding_ids`, moves the appeal `FILED → PARTIALLY_GRANTED`, moves the listed findings `CHARGED_BACK → OVERTURNED` and every remaining contested finding `CHARGED_BACK → UPHELD`."
        PRD §3.8: "A partially granted or a denied appeal instead drives the audit `APPEALED → FINDINGS_ISSUED`, stamping a fresh `findings_issued_at` at the current clock instant and a fresh `appeal_deadline` derived from it, so the dealer may appeal the re-issued findings again inside the new window."

        Design: Difficulty/non_linear_state_machine/audit_findings_issued_appealed_findings_issued_loop_reentry
        """
        world = build_appealed_extrapolation_audit()
        upheld_finding, overturned_finding = world["findings"]

        assert world["appeal"]["status"] == "FILED"
        assert world["appeal"]["overturned_finding_ids"] == []
        assert world["appeal"]["reinstated_amount_cents"] == 0
        appealed_audit = get_audit(world["audit"]["id"])
        assert appealed_audit["status"] == "APPEALED"
        assert_date_equals(
            appealed_audit["appeal_deadline"], "2026-05-31", "appeal_deadline"
        )

        set_clock("2026-05-12T00:00:00Z")
        decision = decide_appeal(
            world["appeal"]["id"],
            action="PARTIAL",
            overturned_finding_ids=[overturned_finding["id"]],
            decision_note="Technician time record produced for the second claim only.",
        )

        assert decision["status"] == "PARTIALLY_GRANTED"
        assert decision["overturned_finding_ids"] == [overturned_finding["id"]]
        assert get_finding(overturned_finding["id"])["status"] == "OVERTURNED"
        assert get_finding(upheld_finding["id"])["status"] == "UPHELD"

        reissued = get_audit(world["audit"]["id"])
        assert reissued["status"] == "FINDINGS_ISSUED", (
            "a partial grant re-enters FINDINGS_ISSUED rather than closing the audit"
        )
        assert_instant_equals(
            reissued["findings_issued_at"], "2026-05-12T00:00:00Z", "findings_issued_at"
        )
        assert_date_equals(
            reissued["appeal_deadline"], "2026-06-11", "refreshed appeal_deadline"
        )

    def test_10_the_second_visit_recomputes_the_chargeback_against_the_pinned_snapshots(self):
        """PRD §3.8: "Every decision then re-runs the third through sixth computational steps described above, against the audit's *persisted* snapshots rather than against live data: `sample_chargeback_cents` is re-totalled over the findings that are still `OPEN`, `CHARGED_BACK` or `UPHELD`, `error_rate` is recomputed against the unchanged `sample_paid_snapshot_cents`, the tier is re-selected, `extrapolated_chargeback_cents` is recomputed against the unchanged `population_paid_snapshot_cents`, and `total_chargeback_cents` is rewritten."
        PRD §3.8: "A row with `source_type` `APPEAL_REVERSAL_SAMPLE` carries the sampled delta — the previous `sample_chargeback_cents` less the new one — as a negative amount, and a row with `source_type` `APPEAL_REVERSAL_EXTRAPOLATION` carries the extrapolation delta — the previous `extrapolated_chargeback_cents` less the new one — likewise as a negative amount, each with `claim_id` null."
        PRD §3.8: "Each claim named by a finding that has just become `OVERTURNED` has its `debited_amount_cents` reduced by that finding's `unsupported_amount_cents`, has its `reinstated_amount_cents` increased by the same figure, moves `DEBITED → CREDIT_REINSTATED`, and advances its `version` by 1."

        Design: Difficulty/non_linear_state_machine/audit_findings_issued_appealed_findings_issued_loop_reentry
        """
        world = build_appealed_extrapolation_audit()
        overturned_finding = world["findings"][1]

        set_clock("2026-05-12T00:00:00Z")
        decide_appeal(
            world["appeal"]["id"],
            action="PARTIAL",
            overturned_finding_ids=[overturned_finding["id"]],
            decision_note="Technician time record produced for the second claim only.",
        )

        audit = get_audit(world["audit"]["id"])
        assert audit["sample_paid_snapshot_cents"] == 100000
        assert audit["population_paid_snapshot_cents"] == 50000
        assert audit["sample_chargeback_cents"] == 30000
        assert_ratio_four_decimals(audit["error_rate"], "error_rate")
        assert audit["error_rate"] == 0.3000
        assert audit["extrapolation_factor"] == 1.00
        assert audit["extrapolated_chargeback_cents"] == 15000
        assert audit["total_chargeback_cents"] == 45000

        rows = list_ledger_entries(world["dealer"]["id"])
        reversals = [
            row
            for row in rows
            if row["source_type"]
            in ("APPEAL_REVERSAL_SAMPLE", "APPEAL_REVERSAL_EXTRAPOLATION")
        ]
        assert len(reversals) == 2
        by_type = {row["source_type"]: row for row in reversals}
        assert by_type["APPEAL_REVERSAL_SAMPLE"]["amount_cents"] == -10000
        assert by_type["APPEAL_REVERSAL_EXTRAPOLATION"]["amount_cents"] == -5000
        assert all(row["claim_id"] is None for row in reversals)

        dealer = get_dealer(world["dealer"]["id"])
        assert dealer["chargeback_balance_cents"] == 45000
        assert dealer["status"] == "ACTIVE"

        reinstated = get_claim(world["claims"][1]["id"])
        still_debited = get_claim(world["claims"][0]["id"])
        assert reinstated["payment_status"] == "CREDIT_REINSTATED"
        assert reinstated["reinstated_amount_cents"] == 10000
        assert reinstated["debited_amount_cents"] == 0
        assert still_debited["payment_status"] == "DEBITED"
        assert get_appeal(world["appeal"]["id"])["reinstated_amount_cents"] == 15000
