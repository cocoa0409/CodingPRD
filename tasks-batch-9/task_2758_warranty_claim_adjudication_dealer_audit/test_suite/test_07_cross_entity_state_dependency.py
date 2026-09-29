"""Gates that live on a third entity: the dealer's audit hold and an audit's child appeal."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    close_audit,
    decide_appeal,
    file_appeal,
    get_appeal,
    get_audit,
    get_claim,
    get_dealer,
    get_finding,
    get_success_data,
    issue_findings,
    list_ledger_entries,
    set_clock,
    setup_audit_with_findings,
    setup_dealer_under_audit_hold,
    validate_error,
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

AUDIT_DEALER = {
    "dealer_code": "D-AUD",
    "name": "Audit Dealer",
    "vehicles_in_operation": 100,
    "initial_labor_rate_cents": 10000,
    "initial_parts_markup_pct": 0.25,
}

WORLD_KWARGS = {
    "profile_overrides": CA_PROFILE,
    "dealer_overrides": AUDIT_DEALER,
    "operation_overrides": ELEC_OPERATION,
    "part_overrides": ELEC_PART,
    "vehicle_overrides": COVERED_TERMS,
}


def _claim_spec(repair_order_number, repair_date, odometer_at_repair, pay):
    return {
        "claim": dict(
            ELEC_NARRATIVE,
            repair_order_number=repair_order_number,
            repair_date=repair_date,
            odometer_at_repair=odometer_at_repair,
            claimed_labor_hours=2.0,
            claimed_parts_qty=1,
        ),
        "approve": {"approved_labor_hours": 2.0, "approved_parts_qty": 1},
        "pay": pay,
    }


def build_unpaid_claim_under_audit_hold():
    """An APPROVED, still-UNPAID 50,000-cent claim whose dealer has a findings-free audit IN_FIELD."""
    set_clock("2026-05-01T00:00:00Z")
    world = setup_dealer_under_audit_hold(
        [_claim_spec("RO-H1", "2026-02-15", 12000, False)],
        audit_overrides={
            "period_start": "2026-01-01",
            "period_end": "2026-07-01",
            "sample_size": 1,
            "lead_auditor_user_id": "auditor-lead-1",
        },
        **WORLD_KWARGS,
    )
    claim = world["claims"][0]
    assert claim["status"] == "APPROVED"
    assert claim["payment_status"] == "UNPAID"
    assert claim["approved_total_cents"] == 50000
    assert claim["suspend_edit_count"] == 0
    world["claim"] = claim
    return world


def build_appealed_audit_pending_one_appeal():
    """The 60,000-cent extrapolation audit with a FILED appeal contesting only the first finding."""
    set_clock("2026-05-01T00:00:00Z")
    world = setup_audit_with_findings(
        [
            _claim_spec("RO-A1", "2026-01-05", 11000, True),
            _claim_spec("RO-A2", "2026-02-10", 13000, True),
            _claim_spec("RO-A3", "2026-03-20", 15000, True),
        ],
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
        **WORLD_KWARGS,
    )
    assert world["audit"]["total_chargeback_cents"] == 60000
    assert get_dealer(world["dealer"]["id"])["chargeback_balance_cents"] == 60000
    set_clock("2026-05-10T00:00:00Z")
    world["appeal"] = file_appeal(
        world["audit"],
        [world["findings"][0]["id"]],
        world["dealer"]["id"],
        grounds="The repair order for the first claim is on file and was produced on request.",
    )
    world["audit"] = get_audit(world["audit"]["id"])
    assert world["audit"]["status"] == "APPEALED"
    return world


class TestPaymentBlockedByDealerAuditHold:
    def test_29_payment_is_frozen_by_an_audit_the_claim_never_references(self):
        """PRD §3.6: "The dealer's `audit_hold` must be false, or `ERR_DEALER_UNDER_AUDIT_HOLD` — payment of a claim is frozen for the duration of an audit, which is what stops the manufacturer from paying out money it is about to try to claw back."
        PRD §3.8: "Going on site sets the dealer's `audit_hold` to true and advances the dealer's `version` by 1, alongside the audit's own."
        PRD §3.8: "`audit_hold` is true exactly while at least one audit of that dealer sits in `IN_FIELD`, `FINDINGS_ISSUED` or `APPEALED`, and as §3.6 explained it freezes payment of that dealer's claims for the duration."

        Design: Difficulty/cross_entity_state_dependency/claim_payment_blocked_by_dealer_audit_hold_from_a_third_entity
        """
        world = build_unpaid_claim_under_audit_hold()
        claim = world["claim"]
        assert world["audit"]["status"] == "IN_FIELD"
        assert get_dealer(world["dealer"]["id"])["audit_hold"] is True

        blocked = api_client.pay_claim(claim["id"], TEST_USERS["warranty_admin_headers"])
        validate_error(blocked, ApiErrorId.ERR_DEALER_UNDER_AUDIT_HOLD.value)

        held = get_claim(claim["id"])
        assert held["payment_status"] == "UNPAID"
        assert held["version"] == claim["version"]

        # Issuing findings moves the audit on but keeps it in a hold-bearing state.
        issued = issue_findings(world["audit"]["id"])
        assert issued["status"] == "FINDINGS_ISSUED"
        assert get_dealer(world["dealer"]["id"])["audit_hold"] is True

        still_blocked = api_client.pay_claim(
            claim["id"], TEST_USERS["warranty_admin_headers"]
        )
        validate_error(still_blocked, ApiErrorId.ERR_DEALER_UNDER_AUDIT_HOLD.value)
        assert get_claim(claim["id"])["payment_status"] == "UNPAID"

    def test_30_closing_the_unrelated_audit_releases_the_hold_and_the_same_payment_succeeds(self):
        """PRD §3.8: "A successful close moves the audit `FINDINGS_ISSUED → CLOSED`, moves every finding still in `CHARGED_BACK` to `UPHELD` with each such finding's `version` advancing by 1, recomputes the dealer's `audit_hold` and advances the dealer's `version` by 1, and advances the audit's own `version` by 1."
        PRD §3.6: "A successful payment moves `payment_status` from `UNPAID` to `PAID`, leaves `status` untouched at `APPROVED`, and advances the claim's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/claim_payment_blocked_by_dealer_audit_hold_from_a_third_entity
        """
        world = build_unpaid_claim_under_audit_hold()
        claim = world["claim"]
        issue_findings(world["audit"]["id"])

        closed = close_audit(world["audit"]["id"])
        assert closed["status"] == "CLOSED"
        assert get_dealer(world["dealer"]["id"])["audit_hold"] is False

        paid = get_success_data(
            api_client.pay_claim(claim["id"], TEST_USERS["warranty_admin_headers"])
        )
        assert paid["payment_status"] == "PAID"
        assert paid["status"] == "APPROVED", "payment never touches the adjudication status"
        assert paid["version"] == claim["version"] + 1


class TestAuditCloseBlockedByPendingChildAppeal:
    def test_31_a_filed_appeal_blocks_the_close_with_its_own_error_not_a_state_error(self):
        """PRD §3.8: "The close accepts an audit in `FINDINGS_ISSUED` or in `APPEALED` — the latter deliberately, so that the pending-appeal rule rather than a generic state error is what speaks — and no appeal of that audit may still be in `FILED`, or the close is refused with `ERR_APPEAL_PENDING`."
        PRD §3.8: "Since an audit in `APPEALED` always has an appeal in `FILED`, a manual close attempted from `APPEALED` always reports `ERR_APPEAL_PENDING`."

        Design: Difficulty/cross_entity_state_dependency/audit_close_blocked_by_pending_appeal_of_a_child_entity
        """
        world = build_appealed_audit_pending_one_appeal()
        audit = world["audit"]

        response = api_client.close_audit(
            audit["id"], TEST_USERS["audit_manager_headers"]
        )
        validate_error(response, ApiErrorId.ERR_APPEAL_PENDING.value)

        assert get_audit(audit["id"])["status"] == "APPEALED"
        assert get_appeal(world["appeal"]["id"])["status"] == "FILED"
        assert get_dealer(world["dealer"]["id"])["audit_hold"] is True

    def test_32_denying_the_appeal_unblocks_the_close_without_moving_any_money(self):
        """PRD §3.8: "`DENY` moves the appeal `FILED → DENIED`, moves every contested finding `CHARGED_BACK → UPHELD`, and leaves the appeal's `reinstated_amount_cents` at 0."
        PRD §3.8: "Each row is omitted entirely when its own delta is zero, which is why a denied appeal typically appends nothing at all."
        PRD §3.8: "A partially granted or a denied appeal instead drives the audit `APPEALED → FINDINGS_ISSUED`, stamping a fresh `findings_issued_at` at the current clock instant and a fresh `appeal_deadline` derived from it, so the dealer may appeal the re-issued findings again inside the new window."

        Design: Difficulty/cross_entity_state_dependency/audit_close_blocked_by_pending_appeal_of_a_child_entity
        """
        world = build_appealed_audit_pending_one_appeal()
        rows_before = list_ledger_entries(world["dealer"]["id"])

        set_clock("2026-05-12T00:00:00Z")
        decided = decide_appeal(
            world["appeal"]["id"],
            action="DENY",
            decision_note="No repair order was produced for the audited claim.",
        )
        assert decided["status"] == "DENIED"
        assert decided["reinstated_amount_cents"] == 0
        assert get_finding(world["findings"][0]["id"])["status"] == "UPHELD"

        reissued = get_audit(world["audit"]["id"])
        assert reissued["status"] == "FINDINGS_ISSUED"
        assert str(reissued["findings_issued_at"])[:10] == "2026-05-12"
        assert str(reissued["appeal_deadline"])[:10] == "2026-06-11"
        assert reissued["total_chargeback_cents"] == 60000, "a denial reverses nothing"
        assert reissued["error_rate"] == 0.4000
        assert len(list_ledger_entries(world["dealer"]["id"])) == len(rows_before)
        assert get_dealer(world["dealer"]["id"])["chargeback_balance_cents"] == 60000

        closed = close_audit(world["audit"]["id"])
        assert closed["status"] == "CLOSED"
        assert get_finding(world["findings"][1]["id"])["status"] == "UPHELD", (
            "the uncontested finding was still CHARGED_BACK and the close upholds it"
        )
        assert get_dealer(world["dealer"]["id"])["audit_hold"] is False
