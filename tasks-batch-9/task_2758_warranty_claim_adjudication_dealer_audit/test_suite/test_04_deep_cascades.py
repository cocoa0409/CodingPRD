"""Five-level cascades: the non-return sweep forwards and an appeal grant backwards."""
import pytest

from test_helpers import (
    approve_claim,
    create_dealer,
    create_labor_operation,
    create_part,
    create_state_law_profile,
    create_vehicle,
    decide_appeal,
    file_appeal,
    get_audit,
    get_claim,
    get_dealer,
    get_finding,
    get_parts_return,
    list_claim_edits,
    list_ledger_entries,
    make_dealer_warranty_admin_headers,
    parts_return_for_claim,
    pay_claim,
    run_non_return_sweep,
    set_clock,
    setup_audit_with_findings,
    submit_claim,
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

COVERED_TERMS = {
    "model_year": 2024,
    "warranty_start_date": "2024-01-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
}

POWERTRAIN_OPERATION = {
    "op_code": "P7788-90",
    "description": "Transmission assembly replacement",
    "standard_time_hours": 3.0,
    "max_time_hours": 4.0,
    "category": "POWERTRAIN",
    "requires_causal_part": True,
    "causal_failure_group": "PWRTRN",
    "overlap_group": "PWRTRN",
}

DIAGNOSTIC_OPERATION = {
    "op_code": "D0001-00",
    "description": "Diagnostic time only",
    "standard_time_hours": 2.0,
    "max_time_hours": 2.5,
    "category": "BASIC",
    "requires_causal_part": False,
    "overlap_group": "DIAG",
}

TRANSMISSION_PART = {
    "part_number": "PWR-TRN-4410",
    "description": "Transmission assembly",
    "dealer_net_cents": 180000,
    "failure_group": "PWRTRN",
    "return_required": True,
    "retention_days": 45,
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


def build_overdue_powertrain_world():
    """A paid 275,250-cent powertrain claim whose return is overdue, plus an idle sibling."""
    set_clock("2026-05-01T00:00:00Z")
    profile = create_state_law_profile(**CA_PROFILE)
    dealer = create_dealer(
        profile["id"],
        dealer_code="D-PWR",
        name="Powertrain Dealer",
        vehicles_in_operation=100,
        initial_labor_rate_cents=13750,
        initial_parts_markup_pct=0.40,
    )
    headers = make_dealer_warranty_admin_headers(dealer["id"])
    powertrain_vehicle = create_vehicle(**COVERED_TERMS)
    sibling_vehicle = create_vehicle(**COVERED_TERMS)
    powertrain_operation = create_labor_operation(**POWERTRAIN_OPERATION)
    diagnostic_operation = create_labor_operation(**DIAGNOSTIC_OPERATION)
    part = create_part(**TRANSMISSION_PART)

    powertrain_claim = submit_claim(
        {
            "dealer": dealer,
            "vehicle": powertrain_vehicle,
            "operation": powertrain_operation,
            "part": part,
            "dealer_headers": headers,
        },
        repair_order_number="RO-P-1",
        repair_date="2026-04-10",
        odometer_at_repair=45000,
        claimed_labor_hours=3.0,
        claimed_parts_qty=1,
        complaint_text="Customer reports harsh shifting under load.",
        cause_text="Internal transmission clutch pack failure confirmed.",
        correction_text="Replaced the transmission assembly and road tested.",
    )
    assert powertrain_claim["coverage_type"] == "POWERTRAIN"
    assert powertrain_claim["provisional_total_cents"] == 293250
    assert powertrain_claim["status"] == "SUSPENDED"

    approved = approve_claim(
        powertrain_claim["id"], approved_labor_hours=3.0, approved_parts_qty=1
    )
    assert approved["approved_total_cents"] == 275250
    pay_claim(powertrain_claim["id"])

    sibling_claim = submit_claim(
        {
            "dealer": dealer,
            "vehicle": sibling_vehicle,
            "operation": diagnostic_operation,
            "part": None,
            "dealer_headers": headers,
        },
        repair_order_number="RO-S-1",
        repair_date="2026-04-20",
        odometer_at_repair=20000,
        claimed_labor_hours=2.0,
        claimed_parts_qty=0,
        complaint_text="Customer reports a dash warning lamp on.",
        cause_text="Diagnostic scan traced a transient sensor code.",
        correction_text="Cleared the code and verified no recurrence.",
    )
    assert sibling_claim["status"] == "SUBMITTED"

    obligation = parts_return_for_claim(powertrain_claim["id"])
    return {
        "dealer": dealer,
        "claim": powertrain_claim,
        "sibling": sibling_claim,
        "obligation": obligation,
    }


def build_probation_audit_appeal_world():
    """An issued audit worth exactly 90,000 cents, on probation, appealed on its one finding."""
    set_clock("2026-05-01T00:00:00Z")
    specs = []
    for ro, date, odo in [
        ("RO-A1", "2026-01-05", 11000),
        ("RO-A2", "2026-02-10", 13000),
        ("RO-A3", "2026-03-20", 15000),
    ]:
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
    specs.append(
        {
            "claim": dict(
                ELEC_NARRATIVE,
                repair_order_number="RO-A4",
                repair_date="2026-04-25",
                odometer_at_repair=17000,
                claimed_labor_hours=2.0,
                claimed_parts_qty=1,
            )
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
            }
        ],
        audit_overrides={
            "period_start": "2026-01-01",
            "period_end": "2026-07-01",
            "sample_size": 1,
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
    set_clock("2026-05-10T00:00:00Z")
    world["appeal"] = file_appeal(
        world["audit"],
        [world["findings"][0]["id"]],
        world["dealer"]["id"],
        grounds="The signed repair order for this claim is on file at the store.",
    )
    return world


class TestNonReturnSweepCascade:
    def test_11_the_sweep_debits_the_whole_claim_and_appends_one_ledger_row(self):
        """PRD §3.7: "The sweep considers every obligation still in `REQUESTED` whose `due_date` the logical clock has reached or passed, and whose linked claim is in `APPROVED`; it processes them in ascending order of their own `created_at`, so that the sequence of `balance_after_cents` values it writes onto the ledger is deterministic."
        PRD §3.7: "Each swept obligation moves `REQUESTED → NOT_RETURNED`, has `debit_amount_cents` set to the linked claim's entire `approved_total_cents` — a non-return costs the dealer the whole claim, labor included, not merely the parts — decrements the dealer's `open_parts_return_count` by 1, and advances its own `version` by 1."
        PRD §3.7: "Second, a ledger row with `source_type` `PARTS_NON_RETURN` is appended for the positive debit amount against the dealer, raising `chargeback_balance_cents`."

        Design: Difficulty/transitive_cascade/non_return_sweep_depth_five_return_claim_ledger_posture_sibling
        """
        world = build_overdue_powertrain_world()
        assert world["obligation"]["status"] == "REQUESTED"
        assert str(world["obligation"]["due_date"])[:10] == "2026-06-15"

        set_clock("2026-06-16T00:00:00Z")
        result = run_non_return_sweep()

        assert result["swept_count"] == 1
        assert result["debited_claim_ids"] == [world["claim"]["id"]]
        assert result["total_debit_cents"] == 275250

        obligation = get_parts_return(world["obligation"]["id"])
        assert obligation["status"] == "NOT_RETURNED"
        assert obligation["debit_amount_cents"] == 275250

        claim = get_claim(world["claim"]["id"])
        assert claim["payment_status"] == "DEBITED"
        assert claim["debited_amount_cents"] == 275250, (
            "a non-return debits the whole approved total, not the 234000 parts amount"
        )
        assert claim["status"] == "APPROVED"

        rows = list_ledger_entries(world["dealer"]["id"])
        assert len(rows) == 1
        assert rows[0]["source_type"] == "PARTS_NON_RETURN"
        assert rows[0]["claim_id"] == world["claim"]["id"]
        assert rows[0]["amount_cents"] == 275250
        assert rows[0]["balance_after_cents"] == 275250

    def test_12_the_posture_jump_suspends_a_sibling_claim_the_request_never_named(self):
        """PRD §2.8: "Because the test is on the balance and not on the size of the movement, a single large debit may take a dealer from `ACTIVE` straight to `SUSPENDED` without ever passing through `PROBATION`, and a recomputation that lands the dealer in the band it was already in is not a transition at all and changes nothing."
        PRD §3.7: "Fourth, if that recomputation put the dealer into `PROBATION` or `SUSPENDED`, every claim of that dealer currently in `SUBMITTED` is driven `SUBMITTED → SUSPENDED`: each such claim receives an appended edit whose `edit_code` is `DEALER_POSTURE_HOLD` and whose `severity` is `SUSPEND`, has its `suspend_edit_count` incremented by 1, and has its `version` advanced by 1."
        PRD §3.7: "Fifth and last, those newly suspended sibling claims are now unpayable and unapprovable — the fifth hop is what makes one dealer's unreturned part visible on every other claim that dealer has in flight."

        Design: Difficulty/transitive_cascade/non_return_sweep_depth_five_return_claim_ledger_posture_sibling
        """
        world = build_overdue_powertrain_world()
        assert get_dealer(world["dealer"]["id"])["status"] == "ACTIVE"

        set_clock("2026-06-16T00:00:00Z")
        run_non_return_sweep()

        dealer = get_dealer(world["dealer"]["id"])
        assert dealer["chargeback_balance_cents"] == 275250
        assert dealer["status"] == "SUSPENDED", (
            "275250 is at or above 200000, so PROBATION is skipped entirely"
        )
        assert dealer["open_parts_return_count"] == 0

        sibling = get_claim(world["sibling"]["id"])
        assert sibling["status"] == "SUSPENDED"
        assert sibling["suspend_edit_count"] == 1
        assert sibling["payment_status"] == "UNPAID"
        assert sibling["approved_total_cents"] is None

        edits = list_claim_edits(sibling["id"])
        assert [edit["edit_code"] for edit in edits] == ["DEALER_POSTURE_HOLD"]
        assert edits[0]["severity"] == "SUSPEND"
        assert edits[0]["resolved_at"] is None


class TestAppealGrantCascade:
    def test_13_a_grant_zeroes_the_extrapolation_and_closes_the_audit(self):
        """PRD §3.8: "`GRANT` moves the appeal `FILED → GRANTED`, sets `overturned_finding_ids` equal to `contested_finding_ids`, and moves every contested finding `CHARGED_BACK → OVERTURNED`."
        PRD §3.8: "The fifth step selects the extrapolation tier from that rate, with both boundaries inclusive on their lower edge: a rate of at least 0.10 gives an `extrapolation_factor` of 1.00, a rate of at least 0.05 but below 0.10 gives 0.50, and anything below 0.05 gives 0.00 — a dealer whose sampled error rate is under five percent is not extrapolated against at all."
        PRD §3.8: "The appeal's own `reinstated_amount_cents` records the audit's `total_chargeback_cents` before the decision less its value after."
        PRD §3.8: "A granted appeal — one whose reinstated set equals its contested set — drives the audit `APPEALED → CLOSED`, at which point the dealer's `audit_hold` is recomputed and becomes false when no other audit of that dealer remains open."

        Design: Difficulty/transitive_cascade/appeal_grant_depth_five_finding_recompute_ledger_posture_release
        """
        world = build_probation_audit_appeal_world()
        finding = world["findings"][0]
        held_claim_id = world["claims"][3]["id"]

        before = get_dealer(world["dealer"]["id"])
        assert before["chargeback_balance_cents"] == 90000
        assert before["status"] == "PROBATION"
        assert get_claim(held_claim_id)["status"] == "SUSPENDED"
        issued = get_audit(world["audit"]["id"])
        assert issued["sample_paid_snapshot_cents"] == 50000
        assert issued["population_paid_snapshot_cents"] == 100000
        assert issued["error_rate"] == 0.6000
        assert issued["extrapolated_chargeback_cents"] == 60000

        set_clock("2026-05-12T00:00:00Z")
        decision = decide_appeal(
            world["appeal"]["id"],
            action="GRANT",
            decision_note="The signed repair order was produced during the review.",
        )

        assert decision["status"] == "GRANTED"
        assert decision["overturned_finding_ids"] == [finding["id"]]
        assert decision["reinstated_amount_cents"] == 90000
        assert get_finding(finding["id"])["status"] == "OVERTURNED"

        audit = get_audit(world["audit"]["id"])
        assert audit["sample_chargeback_cents"] == 0
        assert audit["error_rate"] == 0.0
        assert audit["extrapolation_factor"] == 0.00
        assert audit["extrapolated_chargeback_cents"] == 0
        assert audit["total_chargeback_cents"] == 0
        assert audit["sample_paid_snapshot_cents"] == 50000, "the snapshots stay pinned"
        assert audit["population_paid_snapshot_cents"] == 100000
        assert audit["status"] == "CLOSED"
        assert get_dealer(world["dealer"]["id"])["audit_hold"] is False

    def test_14_the_two_reversal_rows_release_a_claim_the_appeal_never_mentioned(self):
        """PRD §3.8: "The dealer's balance and posture are recomputed from the appended rows, and a dealer whose balance drops back below the probation threshold returns to `ACTIVE` and releases its posture-suspended claims back to `SUBMITTED` under exactly the conditions §3.7 states; the dealer's `version` advances by 1."
        PRD §3.7: "And if the dealer has returned all the way to `ACTIVE`, every claim of that dealer in `SUSPENDED` whose only open suspending edit is a `DEALER_POSTURE_HOLD` is released `SUSPENDED → SUBMITTED`: those hold edits are stamped `resolved_at`, `suspend_edit_count` is set to 0, and the claim's `version` advances by 1."
        PRD §2.8: "In practice the server maintains it incrementally: each append adds that row's `amount_cents` to the dealer's current balance, writes the result into the row's `balance_after_cents`, and stores it as the dealer's new `chargeback_balance_cents`."

        Design: Difficulty/transitive_cascade/appeal_grant_depth_five_finding_recompute_ledger_posture_release
        """
        world = build_probation_audit_appeal_world()
        held_claim_id = world["claims"][3]["id"]
        held_edits = list_claim_edits(held_claim_id)
        assert [edit["edit_code"] for edit in held_edits] == ["DEALER_POSTURE_HOLD"]

        set_clock("2026-05-12T00:00:00Z")
        decide_appeal(
            world["appeal"]["id"],
            action="GRANT",
            decision_note="The signed repair order was produced during the review.",
        )

        rows = list_ledger_entries(world["dealer"]["id"])
        reversals = [row for row in rows if row["amount_cents"] < 0]
        assert len(reversals) == 2
        by_type = {row["source_type"]: row for row in reversals}
        assert by_type["APPEAL_REVERSAL_SAMPLE"]["amount_cents"] == -30000
        assert by_type["APPEAL_REVERSAL_SAMPLE"]["balance_after_cents"] == 60000
        assert by_type["APPEAL_REVERSAL_EXTRAPOLATION"]["amount_cents"] == -60000
        assert by_type["APPEAL_REVERSAL_EXTRAPOLATION"]["balance_after_cents"] == 0

        dealer = get_dealer(world["dealer"]["id"])
        assert dealer["chargeback_balance_cents"] == 0
        assert dealer["status"] == "ACTIVE"

        released = get_claim(held_claim_id)
        assert released["status"] == "SUBMITTED"
        assert released["suspend_edit_count"] == 0
        hold_edits = [
            edit
            for edit in list_claim_edits(held_claim_id)
            if edit["edit_code"] == "DEALER_POSTURE_HOLD"
        ]
        assert hold_edits and all(
            edit["resolved_at"] is not None for edit in hold_edits
        )

        reinstated = get_claim(world["claims"][0]["id"])
        assert reinstated["payment_status"] == "CREDIT_REINSTATED"
        assert reinstated["reinstated_amount_cents"] == 30000
        assert reinstated["debited_amount_cents"] == 0
        for index in (1, 2):
            assert get_claim(world["claims"][index]["id"])["payment_status"] == "PAID"
