"""Money and ratio formulas: goodwill ceilings, edit thresholds, parts debits,
expense analytics and the audit extrapolation arithmetic."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_finding,
    analyze_part,
    api_client,
    approve_claim,
    assert_date_equals,
    assert_instant_equals,
    create_dealer,
    create_labor_operation,
    create_state_law_profile,
    create_vehicle,
    decide_goodwill,
    expense_analytics,
    get_claim,
    get_dealer,
    get_finding,
    issue_findings,
    make_dealer_warranty_admin_headers,
    parts_return_for_claim,
    pay_claim,
    raise_goodwill,
    receive_part,
    schedule_audit,
    set_clock,
    setup_claim,
    start_audit,
    submit_claim,
    validate_paginated,
    void_claim,
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

STANDARD_TERMS = {
    "model_year": 2025,
    "warranty_start_date": "2025-01-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
}

NARRATIVE = {
    "complaint_text": "Customer reports intermittent fault on delivery.",
    "cause_text": "Component failed internal leak test at the dealership.",
    "correction_text": "Replaced the failed component and road tested the vehicle.",
}


def ledger_rows(dealer_id):
    """Read the dealer's append-only ledger with its meta block."""
    return validate_paginated(
        api_client.list_dealer_ledger_entries(
            dealer_id, ADMIN, params={"limit": 10, "offset": 0}
        )
    )


def claim_edits(claim_id):
    """Read a claim's automated edits in append order with its meta block."""
    return validate_paginated(
        api_client.list_claim_edits(claim_id, ADMIN, params={"limit": 10, "offset": 0})
    )


GOODWILL_OPERATION = {
    "op_code": "GW-200",
    "description": "Cabin HVAC blower replacement",
    "standard_time_hours": 1.0,
    "max_time_hours": 1.5,
    "category": "BASIC",
    "requires_causal_part": True,
    "causal_failure_group": "HVAC",
    "overlap_group": "HVAC",
}

GOODWILL_PART = {
    "part_number": "GW-P1",
    "description": "HVAC blower motor",
    "dealer_net_cents": 40000,
    "failure_group": "HVAC",
    "return_required": True,
    "retention_days": 30,
}


def build_out_of_warranty_goodwill_claim():
    """A repair 3,600 miles past a 36,000-mile basic term, priced provisionally at 60,000."""
    set_clock("2026-05-20T00:00:00Z")
    world = setup_claim(
        profile_overrides=CA_PROFILE,
        dealer_overrides={
            "dealer_code": "D-GW",
            "name": "Goodwill Motors",
            "vehicles_in_operation": 100,
            "initial_labor_rate_cents": 10000,
            "initial_parts_markup_pct": 0.25,
        },
        vehicle_overrides={
            **STANDARD_TERMS,
            "vin": "VIN00000000000GW1",
            "model_year": 2023,
            "warranty_start_date": "2023-06-15",
        },
        operation_overrides=GOODWILL_OPERATION,
        part_overrides=GOODWILL_PART,
        claim_overrides={
            "repair_order_number": "RO-GW-1",
            "repair_date": "2026-05-14",
            "odometer_at_repair": 39600,
            "claimed_labor_hours": 1.0,
            "claimed_parts_qty": 1,
            **NARRATIVE,
        },
    )
    claim = world["claim"]
    assert claim["coverage_type"] == "NONE", "the repair sits past the basic mileage term"
    assert claim["status"] == "SUSPENDED", "a NO_COVERAGE edit suspends the intake"
    assert claim["provisional_total_cents"] == 60000
    return world


class TestGoodwillAuthorityCeilings:
    def test_01_decaying_authority_limits_are_pinned_from_the_out_of_warranty_margin(self):
        """PRD §3.5: "Miles overrun is the claim's `odometer_at_repair` less the vehicle's `in_service_odometer` less the vehicle's `basic_miles`, floored at zero so a repair inside the mileage limit contributes nothing."
        PRD §3.5: "Months overrun is the elapsed month count between the vehicle's `warranty_start_date` and the claim's `repair_date` — computed exactly as in §3.3 — less the vehicle's `basic_months`, likewise floored at zero."
        PRD §3.5: "Each overrun is then expressed as a fraction of its own limit: miles overrun divided by `basic_miles`, and months overrun divided by `basic_months`."
        PRD §3.5: "The larger of those two fractions, rounded half up to four decimal places, is `out_of_warranty_margin_pct`."
        PRD §3.5: "A decay multiplier is then formed by subtracting twice the margin from one and flooring the result at zero, so a repair ten percent past its warranty terms retains eighty percent of the base authority, a repair fifty percent past them retains none of it."
        PRD §3.5: "Separately, a share cap is formed by taking eighty percent of the claim's `provisional_total_cents` and rounding half up to whole cents — goodwill never covers the entire provisional value of a repair."
        PRD §3.5: "`adjudicator_limit_cents` is the lesser of the share cap and the adjudicator base authority of 50,000 cents (500 dollars) multiplied by the decay multiplier and rounded half up to whole cents."
        PRD §3.5: "`manager_limit_cents` is the lesser of the same share cap and the manager base authority of 250,000 cents (2,500 dollars) multiplied by the same decay multiplier and rounded half up to whole cents."
        PRD §3.5: "At or below `adjudicator_limit_cents` it opens `PENDING`."

        Design: Corner/calculations/goodwill_claim_final_total_capped_with_policy_adjustment_correct_result
        """
        world = build_out_of_warranty_goodwill_claim()

        authorization = raise_goodwill(
            world["claim"],
            requested_amount_cents=40000,
            policy_adjustment_pct=0.25,
            justification="Long-standing customer just outside the mileage limit.",
        )

        # 3600 miles over 36000 is 0.1000; the months overrun floors at zero.
        assert authorization["out_of_warranty_margin_pct"] == pytest.approx(
            0.1000, abs=0.00001
        )
        # The decay multiplier is 0.80, so the adjudicator base 50000 decays to 40000,
        # which is below the 48000 share cap on a provisional total of 60000.
        assert authorization["adjudicator_limit_cents"] == 40000
        # The manager base 250000 decays to 200000, so the 48000 share cap binds instead.
        assert authorization["manager_limit_cents"] == 48000
        assert authorization["status"] == "PENDING"
        assert authorization["requested_amount_cents"] == 40000

    def test_02_approved_goodwill_caps_the_final_total_and_splits_dealer_participation(self):
        """PRD §3.5: "It then cascades onto the claim: the claim's `coverage_type` flips from `NONE` to `GOODWILL`, the claim's open `NO_COVERAGE` edit is stamped `resolved_at`, `suspend_edit_count` is recomputed from the edits that remain open, and the claim's `version` advances by 1."
        PRD §3.6: "In that case `approved_total_cents` is the lesser of the unadjusted total and the approved goodwill authorization's `approved_amount_cents` — goodwill caps what the manufacturer will pay — and `dealer_participation_cents` is `approved_total_cents` multiplied by that authorization's `policy_adjustment_pct` and rounded half up to whole cents."
        PRD §3.6: "In all cases `oem_payable_cents` is `approved_total_cents` less `dealer_participation_cents`, and that is the figure the manufacturer actually pays."
        PRD §3.6: "Approval moves the claim `SUBMITTED → APPROVED` or `SUSPENDED → APPROVED`, stamps `resolved_at` on every edit of the claim that is still open, sets `suspend_edit_count` to 0, and advances the claim's `version` by 1."
        PRD §3.6: "Note that the provisional figures are left exactly as they were: after a normal approval the claim carries both stories side by side."

        Design: Corner/calculations/goodwill_claim_final_total_capped_with_policy_adjustment_correct_result
        """
        world = build_out_of_warranty_goodwill_claim()
        authorization = raise_goodwill(
            world["claim"],
            requested_amount_cents=40000,
            policy_adjustment_pct=0.25,
            justification="Long-standing customer just outside the mileage limit.",
        )
        decide_goodwill(authorization["id"], "APPROVE", approved_amount_cents=40000)

        approved = approve_claim(
            world["claim"]["id"], approved_labor_hours=1.0, approved_parts_qty=1
        )

        assert approved["status"] == "APPROVED"
        assert approved["coverage_type"] == "GOODWILL"
        assert approved["approved_labor_amount_cents"] == 10000
        assert approved["approved_parts_amount_cents"] == 50000
        # 40000 of authorized goodwill clips the 60000 unadjusted total.
        assert approved["approved_total_cents"] == 40000
        assert approved["dealer_participation_cents"] == 10000
        assert approved["oem_payable_cents"] == 30000
        assert approved["provisional_total_cents"] == 60000


DIAGNOSIS_OPERATION = {
    "op_code": "ANA-100",
    "description": "Body control module diagnosis",
    "standard_time_hours": 3.0,
    "max_time_hours": 4.0,
    "category": "BASIC",
    "requires_causal_part": False,
    "causal_failure_group": None,
    "overlap_group": "ANA_OPS",
}


def build_four_claim_analytics_world():
    """One dealer, one vehicle, four pure-labor claims: one out of window, one voided,
    one approved but unpaid, one approved and paid."""
    set_clock("2026-05-01T00:00:00Z")
    profile = create_state_law_profile(**CA_PROFILE)
    dealer = create_dealer(
        profile["id"],
        dealer_code="DZ",
        name="Analytics Motors",
        vehicles_in_operation=100,
        initial_labor_rate_cents=10000,
        initial_parts_markup_pct=0.25,
    )
    vehicle = create_vehicle(
        **{
            **STANDARD_TERMS,
            "vin": "VIN0000000000ANA1",
            "model_year": 2024,
            "warranty_start_date": "2024-01-15",
        }
    )
    operation = create_labor_operation(**DIAGNOSIS_OPERATION)
    world = {
        "dealer": dealer,
        "vehicle": vehicle,
        "operation": operation,
        "part": None,
        "dealer_headers": make_dealer_warranty_admin_headers(dealer["id"]),
    }

    def labor_claim(repair_order_number, repair_date, odometer, hours):
        return submit_claim(
            world,
            repair_order_number=repair_order_number,
            repair_date=repair_date,
            odometer_at_repair=odometer,
            claimed_labor_hours=hours,
            claimed_parts_qty=0,
            **NARRATIVE,
        )

    old_claim = labor_claim("RO-Z-OLD", "2024-04-10", 5000, 1.0)
    approve_claim(old_claim["id"], approved_labor_hours=1.0, approved_parts_qty=0)
    old_claim = pay_claim(old_claim["id"])

    voided_claim = labor_claim("RO-Z-VOID", "2026-01-10", 20000, 1.0)
    voided_claim = void_claim(
        voided_claim["id"], void_reason="Duplicate repair order raised in error."
    )

    unpaid_claim = labor_claim("RO-Z-UNPAID", "2026-02-10", 25000, 3.0)
    unpaid_claim = approve_claim(
        unpaid_claim["id"], approved_labor_hours=3.0, approved_parts_qty=0
    )

    paid_claim = labor_claim("RO-Z-PAID", "2026-04-10", 30000, 2.0)
    approve_claim(paid_claim["id"], approved_labor_hours=2.0, approved_parts_qty=0)
    paid_claim = pay_claim(paid_claim["id"])

    assert old_claim["approved_total_cents"] == 10000
    assert voided_claim["status"] == "VOID"
    assert unpaid_claim["payment_status"] == "UNPAID"
    assert unpaid_claim["approved_total_cents"] == 30000
    assert paid_claim["approved_total_cents"] == 20000
    world["dealer"] = get_dealer(dealer["id"])
    return world


class TestExpenseAnalyticsInputSet:
    def test_03_only_in_window_approved_claims_reach_the_two_numerators(self):
        """PRD §3.9: "When `window_start` is omitted it defaults to the logical clock less three hundred and sixty-five days; when `window_end` is omitted it defaults to the logical clock itself."
        PRD §3.9: "The window is applied to each claim's `repair_date` and is half-open: a claim counts when its repair date is at or after the window start and strictly before the window end."
        PRD §3.9: "The paid basis sums `approved_total_cents` over the dealer's claims that are in `APPROVED` and whose `payment_status` is exactly `PAID`, reporting the result as `paid_numerator_cents`; a claim that is approved but not yet paid is invisible on this basis, and a claim later charged back to `DEBITED` drops out of it entirely."
        PRD §3.9: "The incurred basis sums `approved_total_cents` over the dealer's claims that are in `APPROVED` whatever their `payment_status` — `UNPAID`, `PAID`, `DEBITED` and `CREDIT_REINSTATED` all count — reporting the result as `incurred_numerator_cents`."
        PRD §3.9: "Each numerator is then divided by the dealer's `vehicles_in_operation` and rounded half up to whole cents, giving `warranty_expense_per_vehicle_paid_cents` and `warranty_expense_per_vehicle_incurred_cents`."
        PRD §3.9: "Alongside them the response reports `paid_claim_count` and `incurred_claim_count`, the number of claims each basis counted."
        PRD §3.9: "With an odd number of peers, `peer_median_paid_cents` is the middle value of that sorted list."
        PRD §3.9: "The response also echoes `dealer_id`, the resolved `window_start` and `window_end`, and `vehicles_in_operation`, so a reader can see exactly which window and which denominator produced the figures."

        Design: Corner/calculations/expense_analytics_window_and_status_input_set_filtering
        """
        world = build_four_claim_analytics_world()

        report = expense_analytics(world["dealer"]["id"])

        assert_date_equals(report["window_start"], "2025-05-01", "window_start")
        assert_date_equals(report["window_end"], "2026-05-01", "window_end")
        # The 2024-04-10 paid claim predates the window and the voided claim is not
        # APPROVED, so neither basis sees them.
        assert report["paid_numerator_cents"] == 20000
        assert report["incurred_numerator_cents"] == 50000
        assert report["paid_claim_count"] == 1
        assert report["incurred_claim_count"] == 2
        assert report["warranty_expense_per_vehicle_paid_cents"] == 200
        assert report["warranty_expense_per_vehicle_incurred_cents"] == 500
        assert report["vehicles_in_operation"] == 100
        assert report["dealer_id"] == world["dealer"]["id"]
        # This dealer is the only one holding vehicles, so it is its own median peer.
        assert report["peer_median_paid_cents"] == 200
        assert report["outlier_ratio"] == pytest.approx(1.0000, abs=0.00001)
        assert report["outlier_flag"] is False


HVAC_OPERATION = {
    "op_code": "HV-300",
    "description": "HVAC compressor replacement",
    "standard_time_hours": 3.0,
    "max_time_hours": 3.0,
    "category": "BASIC",
    "requires_causal_part": True,
    "causal_failure_group": "HVAC",
    "overlap_group": "HVAC",
}

HVAC_PART = {
    "part_number": "HV-P1",
    "description": "HVAC compressor assembly",
    "dealer_net_cents": 96000,
    "failure_group": "HVAC",
    "return_required": True,
    "retention_days": 30,
}


class TestHighValueEditThreshold:
    def test_04_a_provisional_total_landing_exactly_on_the_threshold_suspends_the_claim(self):
        """PRD §3.4: "Labor is priced with exactly one rounding, applied to the product: multiply the hours by the hourly rate in cents and round the result half up to a whole cent."
        PRD §3.4: "First, take the catalog part's `dealer_net_cents`, multiply it by one plus the markup fraction, and round that *unit* price half up to a whole cent."
        PRD §3.4: "`provisional_total_cents` is then simply the labor amount plus the parts amount, with no further rounding of any kind."
        PRD §3.4: "A `HIGH_VALUE` edit fires when `provisional_total_cents` reaches 150,000 cents — 1,500 dollars — or more, the boundary being inclusive."
        PRD §3.4: "An `EXCESSIVE_TIME` edit fires when `claimed_labor_hours` is strictly greater than the operation's `standard_time_hours`."
        PRD §3.4: "A `NARRATIVE_THIN` edit fires when `correction_text` is strictly shorter than twenty characters — note that this is a separate and stricter test than the ten-character narrative floor of §3.3, applies to the correction text alone, and is merely advisory."
        PRD §3.4: "`suspend_edit_count` is then set to the number of edits just appended whose `severity` is `SUSPEND`, and the claim's `status` follows directly: `SUSPENDED` when that count is greater than zero, `SUBMITTED` when it is zero."

        Design: Corner/calculations/high_value_edit_constant_applied_at_exact_threshold
        """
        set_clock("2026-05-01T00:00:00Z")
        world = setup_claim(
            profile_overrides=CA_PROFILE,
            dealer_overrides={
                "dealer_code": "DH",
                "name": "Highvalue Motors",
                "vehicles_in_operation": 100,
                "initial_labor_rate_cents": 10000,
                "initial_parts_markup_pct": 0.25,
            },
            vehicle_overrides={
                **STANDARD_TERMS,
                "vin": "VIN0000000000HV01",
                "model_year": 2025,
                "warranty_start_date": "2025-01-15",
            },
            operation_overrides=HVAC_OPERATION,
            part_overrides=HVAC_PART,
            claim_overrides={
                "repair_order_number": "RO-HV-1",
                "repair_date": "2026-03-10",
                "odometer_at_repair": 15000,
                "claimed_labor_hours": 3.0,
                "claimed_parts_qty": 1,
                **NARRATIVE,
            },
        )
        claim = world["claim"]

        assert claim["coverage_type"] == "BASIC"
        assert claim["provisional_labor_amount_cents"] == 30000
        assert claim["provisional_parts_amount_cents"] == 120000
        # Exactly 150000 cents, and the high-value boundary is inclusive.
        assert claim["provisional_total_cents"] == 150000
        assert claim["status"] == "SUSPENDED"
        assert claim["suspend_edit_count"] == 1

        rows, meta = claim_edits(claim["id"])
        assert meta["total_count"] == 1
        assert rows[0]["edit_code"] == "HIGH_VALUE"
        assert rows[0]["severity"] == "SUSPEND"
        codes = [row["edit_code"] for row in rows]
        # 3.0 claimed hours are not strictly greater than the 3.0 standard time.
        assert "EXCESSIVE_TIME" not in codes
        assert "NARRATIVE_THIN" not in codes


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

BRAKE_DEALER = {
    "dealer_code": "D1",
    "name": "Dealer One",
    "vehicles_in_operation": 100,
    "initial_labor_rate_cents": 13750,
    "initial_parts_markup_pct": 0.40,
}

BRAKE_VEHICLE = {
    **STANDARD_TERMS,
    "vin": "VIN00000000000001",
    "model_year": 2024,
    "warranty_start_date": "2024-01-15",
}

BRAKE_NARRATIVE = {
    "complaint_text": "Customer reports brake squeal at low speed.",
    "cause_text": "Front brake pads worn beyond specification.",
    "correction_text": "Replaced front brake pads and verified normal braking.",
}


def build_received_brake_part_world():
    """A paid brake claim whose approved parts side is 96717 cents, with its returned
    part already physically received."""
    set_clock("2026-05-01T00:00:00Z")
    world = setup_claim(
        profile_overrides=CA_PROFILE,
        dealer_overrides=BRAKE_DEALER,
        vehicle_overrides=BRAKE_VEHICLE,
        operation_overrides=BRAKE_OPERATION,
        part_overrides=BRAKE_PART,
        claim_overrides={
            "repair_order_number": "RO-1001",
            "repair_date": "2026-04-10",
            "odometer_at_repair": 20000,
            "claimed_labor_hours": 1.5,
            "claimed_parts_qty": 3,
            **BRAKE_NARRATIVE,
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


class TestUnanalysablePartHalfDebit:
    def test_05_an_unanalysable_part_debits_exactly_half_the_approved_parts_amount(self):
        """PRD §3.7: "`NOT_AVAILABLE` means the part arrived but could not be analysed, and the parties split the difference: `debit_amount_cents` becomes half of the claim's `approved_parts_amount_cents`, rounded half up to a whole cent."
        PRD §3.7: "Whenever the resulting debit is greater than zero, the claim's `debited_amount_cents` is increased by it, the claim's `payment_status` moves to `DEBITED` from either `PAID` or `UNPAID`, the claim's `version` advances by 1, and a ledger row with `source_type` `PARTS_NO_DEFECT` is appended for that amount against the dealer, which recomputes the dealer's balance and posture and advances the dealer's `version` by 1."
        PRD §3.7: "Analysis follows receipt. A `WarrantyAdmin` supplies an `analysis_result` — one of `DEFECT_CONFIRMED`, `NO_DEFECT_FOUND` or `NOT_AVAILABLE` — together with a free-text `analysis_note`, and both are recorded as the obligation moves `RECEIVED → ANALYZED`."
        PRD §2.8: "In practice the server maintains it incrementally: each append adds that row's `amount_cents` to the dealer's current balance, writes the result into the row's `balance_after_cents`, and stores it as the dealer's new `chargeback_balance_cents`."
        PRD §2.8: "Below 900 dollars the dealer is `ACTIVE`."

        Design: Corner/calculations/not_available_analysis_half_parts_debit_precision
        """
        world = build_received_brake_part_world()

        analyzed = analyze_part(
            world["parts_return"]["id"],
            analysis_result="NOT_AVAILABLE",
            analysis_note="Failed component was scrapped before shipment.",
        )

        assert analyzed["status"] == "ANALYZED"
        assert analyzed["analysis_result"] == "NOT_AVAILABLE"
        # Half of 96717 is 48358.5, which rounds half up to 48359 and never down to 48358.
        assert analyzed["debit_amount_cents"] == 48359

        claim = get_claim(world["claim"]["id"])
        # The claw-back is taken on the parts side only, not on the 117342 claim total.
        assert claim["approved_parts_amount_cents"] == 96717
        assert claim["approved_total_cents"] == 117342
        assert claim["payment_status"] == "DEBITED"
        assert claim["debited_amount_cents"] == 48359

        rows, meta = ledger_rows(world["dealer"]["id"])
        assert meta["total_count"] == 1
        assert rows[0]["source_type"] == "PARTS_NO_DEFECT"
        assert rows[0]["amount_cents"] == 48359
        assert rows[0]["balance_after_cents"] == 48359

        dealer = get_dealer(world["dealer"]["id"])
        assert dealer["chargeback_balance_cents"] == 48359
        assert dealer["status"] == "ACTIVE"


REFLASH_OPERATION = {
    "op_code": "OUT-100",
    "description": "Powertrain control module reflash",
    "standard_time_hours": 3.0,
    "max_time_hours": 4.0,
    "category": "BASIC",
    "requires_causal_part": False,
    "causal_failure_group": None,
    "overlap_group": "OUT_OPS",
}


def build_two_peer_outlier_world():
    """Exactly two dealers of 100 vehicles each: one paid 30000 of labor, the other 10000."""
    set_clock("2026-05-01T00:00:00Z")
    profile = create_state_law_profile(**CA_PROFILE)
    dealer_terms = {
        "vehicles_in_operation": 100,
        "initial_labor_rate_cents": 10000,
        "initial_parts_markup_pct": 0.25,
    }
    high = create_dealer(
        profile["id"], dealer_code="DY1", name="Outlier Motors", **dealer_terms
    )
    low = create_dealer(
        profile["id"], dealer_code="DY2", name="Baseline Motors", **dealer_terms
    )
    operation = create_labor_operation(**REFLASH_OPERATION)
    vehicles = [
        create_vehicle(
            **{
                **STANDARD_TERMS,
                "vin": vin,
                "model_year": 2025,
                "warranty_start_date": "2025-01-15",
            }
        )
        for vin in ("VIN0000000000OUT1", "VIN0000000000OUT2")
    ]

    def paid_labor_claim(dealer, vehicle, repair_order_number, hours):
        claim = submit_claim(
            {
                "dealer": dealer,
                "vehicle": vehicle,
                "operation": operation,
                "part": None,
                "dealer_headers": make_dealer_warranty_admin_headers(dealer["id"]),
            },
            repair_order_number=repair_order_number,
            repair_date="2026-04-10",
            odometer_at_repair=20000,
            claimed_labor_hours=hours,
            claimed_parts_qty=0,
            **NARRATIVE,
        )
        approve_claim(claim["id"], approved_labor_hours=hours, approved_parts_qty=0)
        return pay_claim(claim["id"])

    high_claim = paid_labor_claim(high, vehicles[0], "RO-Y1-1", 3.0)
    low_claim = paid_labor_claim(low, vehicles[1], "RO-Y2-1", 1.0)
    assert high_claim["approved_total_cents"] == 30000
    assert low_claim["approved_total_cents"] == 10000
    return {"high": high, "low": low}


class TestOutlierRatioThreshold:
    def test_06_a_ratio_landing_exactly_on_the_threshold_flags_the_dealer(self):
        """PRD §3.9: "With an even number of peers, it is the mean of the two middle values, rounded half up to whole cents."
        PRD §3.9: "`outlier_ratio` is the dealer's own `warranty_expense_per_vehicle_paid_cents` divided by `peer_median_paid_cents`, rounded half up to four decimal places, and is reported as 0 when the median is 0."
        PRD §3.9: "`outlier_flag` is true exactly when that ratio reaches 1.50 or more — a dealer spending half again what the median dealer spends per vehicle in operation is flagged — with the boundary inclusive."
        PRD §3.9: "The computed flag is not merely reported: it is written back onto the dealer's persisted `outlier_flag`, and when that write actually changes the stored value the dealer's `version` advances by 1."
        PRD §3.9: "The peer set is every dealer whose `vehicles_in_operation` is greater than one — more precisely, greater than zero — regardless of posture, so dealers in `ACTIVE`, `PROBATION` and `SUSPENDED` all participate, and the dealer under examination is included in its own peer set."

        Design: Corner/calculations/outlier_flag_at_exact_ratio_threshold_constants_applied
        """
        world = build_two_peer_outlier_world()

        flagged = expense_analytics(world["high"]["id"])

        assert flagged["warranty_expense_per_vehicle_paid_cents"] == 300
        assert flagged["warranty_expense_per_vehicle_incurred_cents"] == 300
        # The two peer values are 100 and 300, so the even-count median is exactly 200.
        assert flagged["peer_median_paid_cents"] == 200
        # 300 / 200 is exactly 1.5000 and the flag boundary is inclusive.
        assert flagged["outlier_ratio"] == pytest.approx(1.5000, abs=0.00001)
        assert flagged["outlier_flag"] is True
        assert get_dealer(world["high"]["id"])["outlier_flag"] is True

        baseline = expense_analytics(world["low"]["id"])

        assert baseline["warranty_expense_per_vehicle_paid_cents"] == 100
        assert baseline["peer_median_paid_cents"] == 200
        assert baseline["outlier_ratio"] == pytest.approx(0.5000, abs=0.00001)
        assert baseline["outlier_flag"] is False
        assert get_dealer(world["low"]["id"])["outlier_flag"] is False


CLUSTER_OPERATION = {
    "op_code": "AUD-100",
    "description": "Instrument cluster diagnosis and repair",
    "standard_time_hours": 3.0,
    "max_time_hours": 4.0,
    "category": "BASIC",
    "requires_causal_part": False,
    "causal_failure_group": None,
    "overlap_group": "AUDIT_OPS",
}


def build_audit_over_a_single_paid_claim():
    """The dealer's only in-period paid claim is also the sampled one, so nothing remains
    outside the sample."""
    set_clock("2026-05-01T00:00:00Z")
    profile = create_state_law_profile(**CA_PROFILE)
    dealer = create_dealer(
        profile["id"],
        dealer_code="DA",
        name="Audit Motors",
        vehicles_in_operation=100,
        initial_labor_rate_cents=10000,
        initial_parts_markup_pct=0.25,
    )
    vehicle = create_vehicle(
        **{
            **STANDARD_TERMS,
            "vin": "VIN0000000000AUD1",
            "model_year": 2025,
            "warranty_start_date": "2025-01-15",
        }
    )
    operation = create_labor_operation(**CLUSTER_OPERATION)
    claim = submit_claim(
        {
            "dealer": dealer,
            "vehicle": vehicle,
            "operation": operation,
            "part": None,
            "dealer_headers": make_dealer_warranty_admin_headers(dealer["id"]),
        },
        repair_order_number="RO-AUD-1",
        repair_date="2026-02-15",
        odometer_at_repair=20000,
        claimed_labor_hours=2.0,
        claimed_parts_qty=0,
        **NARRATIVE,
    )
    approve_claim(claim["id"], approved_labor_hours=2.0, approved_parts_qty=0)
    claim = pay_claim(claim["id"])
    assert claim["approved_total_cents"] == 20000

    audit = schedule_audit(
        get_dealer(dealer["id"]),
        period_start="2026-01-01",
        period_end="2026-04-01",
        sample_size=1,
    )
    start_audit(audit["id"])
    finding = add_finding(
        audit["id"],
        claim["id"],
        10000,
        finding_code="TIME_NOT_DOCUMENTED",
        evidence_note="Technician time is not documented on the repair order.",
    )
    return {
        "dealer": dealer,
        "claim": claim,
        "audit": audit,
        "finding": finding,
    }


class TestAuditExtrapolationOverAnEmptyRemainder:
    def test_07_an_empty_unsampled_remainder_extrapolates_to_nothing(self):
        """PRD §3.8: "`sample_paid_snapshot_cents` is the sum of `approved_total_cents` over every claim that is named by one of this audit's findings, belongs to the audited dealer, is in `APPROVED`, has `payment_status` `PAID` at this instant — before any chargeback has touched it — and has a `repair_date` inside the half-open period."
        PRD §3.8: "The second step pins the unsampled remainder: the same sum is taken over every claim of the dealer in `APPROVED` with `payment_status` `PAID` and a `repair_date` inside the period regardless of whether a finding names it, and `population_paid_snapshot_cents` is that figure less `sample_paid_snapshot_cents`."
        PRD §3.8: "`sample_chargeback_cents` is the sum of `unsupported_amount_cents` over this audit's findings whose `status` is `OPEN`, `CHARGED_BACK` or `UPHELD`; findings in `OVERTURNED` are excluded."
        PRD §3.8: "The fourth step derives `error_rate`: when the pinned sampled denominator is zero the rate is zero, and otherwise it is `sample_chargeback_cents` divided by `sample_paid_snapshot_cents`, rounded half up to four decimal places."
        PRD §3.8: "The fifth step selects the extrapolation tier from that rate, with both boundaries inclusive on their lower edge: a rate of at least 0.10 gives an `extrapolation_factor` of 1.00, a rate of at least 0.05 but below 0.10 gives 0.50, and anything below 0.05 gives 0.00 — a dealer whose sampled error rate is under five percent is not extrapolated against at all."
        PRD §3.8: "The sixth step multiplies `population_paid_snapshot_cents` by `error_rate` and then by `extrapolation_factor`, rounds that product half up to whole cents as `extrapolated_chargeback_cents`, and sets `total_chargeback_cents` to `sample_chargeback_cents` plus `extrapolated_chargeback_cents`."
        PRD §3.8: "The audit moves `IN_FIELD → FINDINGS_ISSUED`, sets `findings_issued_at` to the current logical-clock instant, sets `appeal_deadline` to that instant advanced by the governing statute's `appeal_window_days` days, and advances its own `version` by 1."

        Design: Corner/calculations/audit_chargeback_with_empty_population_correct_result
        """
        world = build_audit_over_a_single_paid_claim()

        issued = issue_findings(world["audit"]["id"])

        assert issued["status"] == "FINDINGS_ISSUED"
        assert issued["sample_paid_snapshot_cents"] == 20000
        # The sampled claim is the dealer's only in-period paid claim, so nothing is left.
        assert issued["population_paid_snapshot_cents"] == 0
        assert issued["sample_chargeback_cents"] == 10000
        assert issued["error_rate"] == pytest.approx(0.5000, abs=0.00001)
        # A rate of 0.5000 is well above 0.10, so the full tier is still selected.
        assert issued["extrapolation_factor"] == pytest.approx(1.00, abs=0.001)
        # Yet zero times any factor is zero.
        assert issued["extrapolated_chargeback_cents"] == 0
        assert issued["total_chargeback_cents"] == 10000
        assert_instant_equals(
            issued["findings_issued_at"], "2026-05-01T00:00:00Z", "findings_issued_at"
        )
        assert_instant_equals(
            issued["appeal_deadline"], "2026-05-31T00:00:00Z", "appeal_deadline"
        )

    def test_08_no_extrapolation_ledger_row_is_appended_for_a_zero_amount(self):
        """PRD §3.8: "One ledger row with `source_type` `AUDIT_CHARGEBACK_SAMPLE` is appended per charged-back finding, each carrying that finding's `claim_id` and its positive `unsupported_amount_cents`, so the sampled rows sum to `sample_chargeback_cents`."
        PRD §3.8: "Then, and only when `extrapolated_chargeback_cents` is greater than zero, a single further row with `source_type` `AUDIT_CHARGEBACK_EXTRAPOLATION` is appended for that positive amount with its `claim_id` left null, because extrapolated money is by construction not attributable to any one claim."
        PRD §3.8: "Every finding of this audit in `OPEN` moves `OPEN → CHARGED_BACK`, each advancing its own `version` by 1."
        PRD §3.8: "Every sampled claim currently in `PAID` moves `PAID → DEBITED` with its `debited_amount_cents` increased by its own finding's `unsupported_amount_cents` and its `version` advanced by 1."
        PRD §2.8: "Below 900 dollars the dealer is `ACTIVE`."

        Design: Corner/calculations/audit_chargeback_with_empty_population_correct_result
        """
        world = build_audit_over_a_single_paid_claim()

        issue_findings(world["audit"]["id"])

        rows, meta = ledger_rows(world["dealer"]["id"])
        # Only the sampled row exists: a zero extrapolation is skipped, not booked at zero.
        assert meta["total_count"] == 1
        assert rows[0]["source_type"] == "AUDIT_CHARGEBACK_SAMPLE"
        assert rows[0]["amount_cents"] == 10000
        assert rows[0]["balance_after_cents"] == 10000
        assert rows[0]["claim_id"] == world["claim"]["id"]
        assert [row["source_type"] for row in rows].count(
            "AUDIT_CHARGEBACK_EXTRAPOLATION"
        ) == 0

        claim = get_claim(world["claim"]["id"])
        assert claim["payment_status"] == "DEBITED"
        assert claim["debited_amount_cents"] == 10000

        dealer = get_dealer(world["dealer"]["id"])
        assert dealer["chargeback_balance_cents"] == 10000
        assert dealer["status"] == "ACTIVE"

        assert get_finding(world["finding"]["id"])["status"] == "CHARGED_BACK"
