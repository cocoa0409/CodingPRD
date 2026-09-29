"""Exact undo: a money balance reversed to zero and a count restored to its pre-submission value."""
import pytest

from test_helpers import (
    approve_claim,
    create_dealer,
    create_labor_operation,
    create_part,
    create_state_law_profile,
    create_vehicle,
    get_claim,
    get_dealer,
    get_parts_return,
    list_claim_edits,
    list_ledger_entries,
    list_parts_returns,
    make_dealer_warranty_admin_headers,
    parts_return_for_claim,
    pay_claim,
    receive_part,
    run_non_return_sweep,
    set_clock,
    setup_claim,
    submit_claim,
    void_claim,
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

BRAKE_CLAIM = {
    "repair_order_number": "RO-CNT-1",
    "repair_date": "2026-04-10",
    "odometer_at_repair": 20000,
    "claimed_labor_hours": 1.5,
    "claimed_parts_qty": 3,
    "complaint_text": "Customer reports brake squeal at low speed.",
    "cause_text": "Front brake pads worn beyond specification.",
    "correction_text": "Replaced front brake pads and verified normal braking.",
}


def build_swept_non_return_world():
    """A 275,250-cent non-return debit already swept: dealer SUSPENDED, sibling on posture hold."""
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

    claim = submit_claim(
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
    approved = approve_claim(claim["id"], approved_labor_hours=3.0, approved_parts_qty=1)
    assert approved["approved_total_cents"] == 275250
    pay_claim(claim["id"])

    sibling = submit_claim(
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
    obligation = parts_return_for_claim(claim["id"])

    set_clock("2026-06-16T00:00:00Z")
    run_non_return_sweep()

    swept_dealer = get_dealer(dealer["id"])
    assert swept_dealer["chargeback_balance_cents"] == 275250
    assert swept_dealer["status"] == "SUSPENDED"
    assert swept_dealer["open_parts_return_count"] == 0
    assert get_parts_return(obligation["id"])["status"] == "NOT_RETURNED"
    assert get_claim(sibling["id"])["status"] == "SUSPENDED"
    return {
        "dealer": dealer,
        "claim": claim,
        "sibling": sibling,
        "obligation": obligation,
    }


def build_returnable_claim_awaiting_void():
    """A live claim whose return-required causal part has pushed open_parts_return_count to 1."""
    set_clock("2026-05-01T00:00:00Z")
    world = setup_claim(
        profile_overrides=CA_PROFILE,
        dealer_overrides={
            "dealer_code": "D-CNT",
            "name": "Count Dealer",
            "vehicles_in_operation": 100,
            "initial_labor_rate_cents": 13750,
            "initial_parts_markup_pct": 0.40,
        },
        vehicle_overrides=COVERED_TERMS,
        operation_overrides=BRAKE_OPERATION,
        part_overrides=BRAKE_PART,
        claim_overrides=BRAKE_CLAIM,
    )
    world["obligation"] = parts_return_for_claim(world["claim"]["id"])
    return world


class TestLateReturnReversesToExactZero:
    def test_37_the_reversal_row_is_appended_and_the_balance_returns_to_exactly_zero(self):
        """PRD §3.7: "Receipt on an obligation already in `NOT_RETURNED` moves `NOT_RETURNED → RECEIVED`, stamps `received_date`, and sets `reversed_amount_cents` equal to the obligation's `debit_amount_cents`."
        PRD §3.7: "A ledger row with `source_type` `LATE_RETURN_REVERSAL` is appended carrying the negative of the debit amount, so the dealer's `chargeback_balance_cents` falls by exactly what it rose by."
        PRD §2.8: "A dealer's `chargeback_balance_cents` is *defined* as the signed sum of `amount_cents` over every ledger row naming that dealer, and this equality is an invariant that must hold at every observable instant."
        PRD §2.8: "No rounding occurs anywhere in this calculation, so a forward debit of some amount followed by a reversal of exactly that amount returns the balance to its precise pre-debit value."

        Design: Difficulty/compensating_invariant/late_part_return_reverses_non_return_debit_to_exact_zero
        """
        world = build_swept_non_return_world()

        set_clock("2026-06-20T00:00:00Z")
        obligation = receive_part(world["obligation"]["id"], "2026-06-20")

        assert obligation["status"] == "RECEIVED"
        assert obligation["reversed_amount_cents"] == 275250
        assert obligation["debit_amount_cents"] == 275250, (
            "the original debit is compensated, never erased"
        )

        rows = list_ledger_entries(world["dealer"]["id"])
        assert len(rows) == 2, "the ledger is append-only: both rows survive"
        reversals = [
            row for row in rows if row["source_type"] == "LATE_RETURN_REVERSAL"
        ]
        assert len(reversals) == 1
        assert reversals[0]["amount_cents"] == -275250
        assert reversals[0]["balance_after_cents"] == 0
        assert reversals[0]["claim_id"] == world["claim"]["id"]

        dealer = get_dealer(world["dealer"]["id"])
        assert dealer["chargeback_balance_cents"] == 0
        assert dealer["chargeback_balance_cents"] == sum(
            row["amount_cents"] for row in rows
        )

    def test_38_every_downstream_consequence_of_the_debit_unwinds_as_well(self):
        """PRD §3.7: "The dealer's `open_parts_return_count` is deliberately **not** decremented again here: the row already left `REQUESTED` when the sweep moved it to `NOT_RETURNED`, and decrementing twice would break the count invariant."
        PRD §3.7: "The linked claim moves `DEBITED → CREDIT_REINSTATED` with its `reinstated_amount_cents` increased by the reversed amount and its `version` advanced by 1."
        PRD §3.7: "The dealer's `status` is recomputed from the reduced balance and may fall `SUSPENDED → ACTIVE`, `PROBATION → ACTIVE`, or `SUSPENDED → PROBATION`, with the dealer's `version` advancing by 1."
        PRD §3.7: "And if the dealer has returned all the way to `ACTIVE`, every claim of that dealer in `SUSPENDED` whose only open suspending edit is a `DEALER_POSTURE_HOLD` is released `SUSPENDED → SUBMITTED`: those hold edits are stamped `resolved_at`, `suspend_edit_count` is set to 0, and the claim's `version` advances by 1."

        Design: Difficulty/compensating_invariant/late_part_return_reverses_non_return_debit_to_exact_zero
        """
        world = build_swept_non_return_world()

        set_clock("2026-06-20T00:00:00Z")
        receive_part(world["obligation"]["id"], "2026-06-20")

        dealer = get_dealer(world["dealer"]["id"])
        assert dealer["status"] == "ACTIVE"
        assert dealer["open_parts_return_count"] == 0, (
            "the sweep already decremented the count; the late receipt must not do it twice"
        )

        claim = get_claim(world["claim"]["id"])
        assert claim["payment_status"] == "CREDIT_REINSTATED"
        assert claim["reinstated_amount_cents"] == 275250
        assert claim["status"] == "APPROVED"

        sibling = get_claim(world["sibling"]["id"])
        assert sibling["status"] == "SUBMITTED"
        assert sibling["suspend_edit_count"] == 0
        holds = list_claim_edits(
            sibling["id"], params={"edit_code": "DEALER_POSTURE_HOLD"}
        )
        assert len(holds) == 1
        assert holds[0]["resolved_at"] is not None


class TestVoidRestoresOpenReturnCount:
    def test_39_voiding_the_claim_waives_the_obligation_and_restores_the_count(self):
        """PRD §3.4: "When the submission's causal part has `return_required` true, the same request also raises a parts-return obligation in `REQUESTED`, whose `due_date` is its own `created_at` advanced by the part's `retention_days` days, and increments the dealer's `open_parts_return_count` by 1 — re-establishing the invariant that the count always equals the number of parts-return rows in `REQUESTED` whose claim belongs to that dealer."
        PRD §3.6: "Voiding stamps `resolved_at` on every open edit, sets `suspend_edit_count` to 0, advances the claim's `version` by 1, and runs the same parts-return waiver as denial — every `REQUESTED` obligation becomes `WAIVED`, the dealer's `open_parts_return_count` drops by one per waived row, and the dealer's `version` advances by 1."
        PRD §3.6: "That compensating pair is deliberate: submitting a claim whose causal part must be returned and then voiding that claim leaves the dealer's open-return count at exactly its pre-submission value."

        Design: Difficulty/compensating_invariant/claim_void_restores_open_parts_return_count_to_pre_submission_value
        """
        world = build_returnable_claim_awaiting_void()
        assert get_dealer(world["dealer"]["id"])["open_parts_return_count"] == 1
        assert world["obligation"]["status"] == "REQUESTED"
        assert str(world["obligation"]["due_date"])[:10] == "2026-05-31"

        voided = void_claim(
            world["claim"]["id"],
            void_reason="Claim was entered against the wrong repair order.",
        )

        assert voided["status"] == "VOID"
        obligation = get_parts_return(world["obligation"]["id"])
        assert obligation["status"] == "WAIVED"
        assert obligation["debit_amount_cents"] == 0
        assert obligation["reversed_amount_cents"] == 0
        assert get_dealer(world["dealer"]["id"])["open_parts_return_count"] == 0

    def test_40_the_waiver_moves_no_money_and_restates_the_count_invariant(self):
        """PRD §3.7: "Taken together, the four movements that touch the count — creation into `REQUESTED` adding one, and departure from `REQUESTED` to any of `RECEIVED`, `NOT_RETURNED` or `WAIVED` subtracting one, with the late `NOT_RETURNED → RECEIVED` step changing nothing — keep `open_parts_return_count` exactly equal to the number of that dealer's obligations sitting in `REQUESTED` at every observable instant."
        PRD §3.7: "Rows in `RECEIVED`, `ANALYZED`, `NOT_RETURNED` and `WAIVED` are all excluded from that count."
        PRD §3.7: "What happens to the money depends entirely on which of the three outcomes was recorded, and the debit is always computed against the linked claim, which must be in `APPROVED` — a claim that reached `DENIED` or `VOID` had its obligation waived and is never debited."

        Design: Difficulty/compensating_invariant/claim_void_restores_open_parts_return_count_to_pre_submission_value
        """
        world = build_returnable_claim_awaiting_void()

        void_claim(
            world["claim"]["id"],
            void_reason="Claim was entered against the wrong repair order.",
        )

        assert list_ledger_entries(world["dealer"]["id"]) == [], "a void never debits"
        dealer = get_dealer(world["dealer"]["id"])
        assert dealer["chargeback_balance_cents"] == 0
        assert dealer["status"] == "ACTIVE"

        still_requested = list_parts_returns(
            {"claim_id": world["claim"]["id"], "status": "REQUESTED"}
        )
        assert still_requested == []
        assert dealer["open_parts_return_count"] == len(still_requested)
