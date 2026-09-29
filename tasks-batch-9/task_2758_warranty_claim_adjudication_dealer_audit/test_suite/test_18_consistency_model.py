"""Cascades are final the moment the triggering request returns: the response body itself
carries every recomputed figure and an immediate re-read agrees with it."""
from test_helpers import (
    analyze_part,
    api_client,
    approve_claim,
    get_claim,
    get_dealer,
    parts_return_for_claim,
    pay_claim,
    receive_part,
    set_clock,
    setup_claim,
    TEST_USERS,
    validate_paginated,
)

ADMIN = TEST_USERS["warranty_admin_headers"]

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


def ledger_rows(dealer_id):
    """Read the dealer's append-only ledger with its meta block."""
    return validate_paginated(
        api_client.list_dealer_ledger_entries(
            dealer_id, ADMIN, params={"limit": 10, "offset": 0}
        )
    )


def build_paid_brake_claim_awaiting_analysis():
    """A paid brake claim whose approved parts side is 96717 cents, with the returned part
    already received and awaiting its verdict."""
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
        vehicle_overrides={
            "vin": "VIN00000000000001",
            "model_year": 2024,
            "warranty_start_date": "2024-01-15",
            "in_service_odometer": 0,
            "basic_months": 36,
            "basic_miles": 36000,
            "powertrain_months": 60,
            "powertrain_miles": 60000,
        },
        operation_overrides=BRAKE_OPERATION,
        part_overrides=BRAKE_PART,
        claim_overrides={
            "repair_order_number": "RO-1001",
            "repair_date": "2026-04-10",
            "odometer_at_repair": 20000,
            "claimed_labor_hours": 2.0,
            "claimed_parts_qty": 3,
            "complaint_text": "Customer reports brake squeal at low speed.",
            "cause_text": "Front brake pads worn beyond specification.",
            "correction_text": "Replaced front brake pads and verified normal braking.",
        },
    )
    claim = approve_claim(
        world["claim"]["id"], approved_labor_hours=2.0, approved_parts_qty=3
    )
    assert claim["approved_parts_amount_cents"] == 96717
    assert claim["approved_total_cents"] == 117342
    world["claim"] = pay_claim(claim["id"])
    parts_return = parts_return_for_claim(claim["id"])
    world["parts_return"] = receive_part(parts_return["id"], "2026-05-01")
    assert world["parts_return"]["status"] == "RECEIVED"
    return world


class TestCascadeVisibleInTheSameResponse:
    def test_01_the_analysis_response_already_carries_the_debit_the_claim_reports(self):
        """PRD §3.7: "A `WarrantyAdmin` supplies an `analysis_result` — one of `DEFECT_CONFIRMED`, `NO_DEFECT_FOUND` or `NOT_AVAILABLE` — together with a free-text `analysis_note`, and both are recorded as the obligation moves `RECEIVED → ANALYZED`."
        PRD §3.7: "`NO_DEFECT_FOUND` means the dealer replaced a part that was not actually faulty, and `debit_amount_cents` becomes the claim's entire `approved_parts_amount_cents` — the parts side of the claim is clawed back, the labor is not."
        PRD §3.7: "Whenever the resulting debit is greater than zero, the claim's `debited_amount_cents` is increased by it, the claim's `payment_status` moves to `DEBITED` from either `PAID` or `UNPAID`, the claim's `version` advances by 1, and a ledger row with `source_type` `PARTS_NO_DEFECT` is appended for that amount against the dealer, which recomputes the dealer's balance and posture and advances the dealer's `version` by 1."
        PRD §2.4: "When one operation mutates several records, each mutated record's own `version` advances by 1 and its own `updated_at` is refreshed."

        Design: Corner/consistency_model/cascade_is_visible_in_the_same_response_immediate
        """
        world = build_paid_brake_claim_awaiting_analysis()

        analyzed = analyze_part(
            world["parts_return"]["id"],
            analysis_result="NO_DEFECT_FOUND",
            analysis_note="Bench test found the component within specification.",
        )

        # The triggering response is already the final word on the obligation.
        assert analyzed["status"] == "ANALYZED"
        assert analyzed["analysis_result"] == "NO_DEFECT_FOUND"
        assert analyzed["debit_amount_cents"] == 96717

        # A re-read taken immediately afterwards adds nothing and contradicts nothing.
        claim = get_claim(world["claim"]["id"])
        assert claim["payment_status"] == "DEBITED"
        assert claim["debited_amount_cents"] == 96717
        assert claim["approved_parts_amount_cents"] == 96717
        assert claim["approved_total_cents"] == 117342
        assert claim["version"] == world["claim"]["version"] + 1

    def test_02_the_dealer_balance_and_posture_are_already_recomputed_on_return(self):
        """PRD §2.8: "A dealer's `chargeback_balance_cents` is *defined* as the signed sum of `amount_cents` over every ledger row naming that dealer, and this equality is an invariant that must hold at every observable instant."
        PRD §2.8: "In practice the server maintains it incrementally: each append adds that row's `amount_cents` to the dealer's current balance, writes the result into the row's `balance_after_cents`, and stores it as the dealer's new `chargeback_balance_cents`."
        PRD §2.8: "Immediately after each append, and only there, the dealer's `status` is recomputed from the new balance."
        PRD §2.8: "Otherwise, a balance of at least 90,000 cents — 900 dollars — puts the dealer in `PROBATION`."

        Design: Corner/consistency_model/cascade_is_visible_in_the_same_response_immediate
        """
        world = build_paid_brake_claim_awaiting_analysis()
        assert get_dealer(world["dealer"]["id"])["chargeback_balance_cents"] == 0

        analyze_part(
            world["parts_return"]["id"],
            analysis_result="NO_DEFECT_FOUND",
            analysis_note="Bench test found the component within specification.",
        )

        dealer = get_dealer(world["dealer"]["id"])
        assert dealer["chargeback_balance_cents"] == 96717
        # 96717 cents is past the 90,000-cent probation band, and the posture already says so.
        assert dealer["status"] == "PROBATION"

        rows, meta = ledger_rows(world["dealer"]["id"])
        assert meta["total_count"] == 1
        assert rows[0]["source_type"] == "PARTS_NO_DEFECT"
        assert rows[0]["amount_cents"] == 96717
        assert rows[0]["balance_after_cents"] == dealer["chargeback_balance_cents"]
