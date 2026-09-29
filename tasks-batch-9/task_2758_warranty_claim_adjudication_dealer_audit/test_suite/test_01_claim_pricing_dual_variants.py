"""Provisional versus final claim pricing, and the paid versus incurred expense bases."""
import pytest

from test_helpers import (
    approve_claim,
    create_dealer,
    create_labor_operation,
    create_part,
    create_state_law_profile,
    create_vehicle,
    expense_analytics,
    get_dealer,
    pay_claim,
    set_clock,
    setup_claim,
    submit_claim,
    make_dealer_warranty_admin_headers,
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

COVERED_VEHICLE = {
    "vin": "VIN00000000000001",
    "model_year": 2024,
    "warranty_start_date": "2024-01-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
}

BRAKE_CLAIM = {
    "repair_order_number": "RO-1001",
    "repair_date": "2026-04-10",
    "odometer_at_repair": 20000,
    "claimed_labor_hours": 1.5,
    "claimed_parts_qty": 3,
    "complaint_text": "Customer reports brake squeal at low speed.",
    "cause_text": "Front brake pads worn beyond specification.",
    "correction_text": "Replaced front brake pads and verified normal braking.",
}


def build_grandfathered_brake_claim():
    """A CA dealer whose 0.40 markup sits above the state's 0.30 cap, with one claim."""
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
        vehicle_overrides=COVERED_VEHICLE,
        operation_overrides=BRAKE_OPERATION,
        part_overrides=BRAKE_PART,
        claim_overrides=BRAKE_CLAIM,
    )
    assert world["claim"]["status"] == "SUBMITTED"
    return world


class TestProvisionalVersusFinalPricing:
    def test_01_approved_pricing_diverges_from_provisional_by_the_markup_cap(self):
        """PRD §3.4: "Four inputs are selected for this provisional pass: the hourly rate is the dealer's `approved_labor_rate_cents` as of this instant; the markup is the dealer's `approved_parts_markup_pct` as of this instant, taken **uncapped**, whatever the statute says; the hours are the dealer's `claimed_labor_hours`, also taken uncapped, whatever the flat-rate standard says; and the quantity is `claimed_parts_qty`."
        PRD §3.6: "The markup is the lesser of the dealer's `approved_parts_markup_pct` and the governing statute's `markup_cap_pct`, so a grandfathered markup is finally trimmed to what state law allows."
        PRD §3.6: "In all cases `oem_payable_cents` is `approved_total_cents` less `dealer_participation_cents`, and that is the figure the manufacturer actually pays."

        Design: Difficulty/dual_variant_calc/claim_pricing_provisional_versus_final_variant_divergence
        """
        world = build_grandfathered_brake_claim()

        approved = approve_claim(
            world["claim"]["id"], approved_labor_hours=2.0, approved_parts_qty=3
        )

        assert approved["coverage_type"] == "BASIC"
        assert approved["status"] == "APPROVED"
        assert approved["provisional_labor_amount_cents"] == 20625
        assert approved["provisional_parts_amount_cents"] == 104157
        assert approved["provisional_total_cents"] == 124782
        assert approved["approved_parts_amount_cents"] == 96717
        assert approved["approved_total_cents"] == 117342
        assert (
            approved["provisional_total_cents"] - approved["approved_total_cents"] == 7440
        )
        assert approved["dealer_participation_cents"] == 0
        assert approved["oem_payable_cents"] == 117342

    def test_02_flat_rate_hours_cap_suppresses_the_generous_approved_hours(self):
        """PRD §3.6: "The hours are the lesser of `approved_labor_hours` and the operation's `standard_time_hours`, so flat-rate discipline bites even when the adjudicator was generous."
        PRD §3.6: "Note that the provisional figures are left exactly as they were: after a normal approval the claim carries both stories side by side."

        Design: Difficulty/dual_variant_calc/claim_pricing_provisional_versus_final_variant_divergence
        """
        world = build_grandfathered_brake_claim()

        approved = approve_claim(
            world["claim"]["id"], approved_labor_hours=2.0, approved_parts_qty=3
        )

        # 2.0 approved hours are cut back to the 1.5 standard time: 1.5 * 13750 = 20625,
        # not the 27500 cents that 2.0 hours would have earned.
        assert approved["approved_labor_amount_cents"] == 20625
        assert approved["approved_labor_hours"] == pytest.approx(2.0, abs=0.01)
        # The provisional pass, which used the same 1.5 claimed hours uncapped, is untouched.
        assert approved["provisional_labor_amount_cents"] == 20625
        assert approved["provisional_parts_amount_cents"] == 104157
        assert approved["provisional_total_cents"] == 124782
        # The whole 7440-cent divergence is therefore attributable to the markup cap.
        assert (
            approved["provisional_parts_amount_cents"]
            - approved["approved_parts_amount_cents"]
            == 7440
        )


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

DIAG_OPERATION = {
    "op_code": "D0001-00",
    "description": "Diagnostic time only",
    "standard_time_hours": 2.0,
    "max_time_hours": 2.5,
    "category": "BASIC",
    "requires_causal_part": False,
    "causal_failure_group": None,
    "overlap_group": "DIAG",
}

ELEC_PART = {
    "part_number": "AUD-P1",
    "description": "Electrical harness",
    "dealer_net_cents": 24000,
    "failure_group": "ELEC",
    "return_required": False,
    "retention_days": 0,
}


def build_two_dealer_analytics_world():
    """Two dealers over 100 vehicles each: DX1 with a paid 50000 claim and an unpaid
    20000 claim, DX2 with a single paid 5000 claim."""
    set_clock("2026-05-01T00:00:00Z")
    profile = create_state_law_profile(**CA_PROFILE)
    dealer_terms = {
        "vehicles_in_operation": 100,
        "initial_labor_rate_cents": 10000,
        "initial_parts_markup_pct": 0.25,
    }
    dx1 = create_dealer(
        profile["id"], dealer_code="DX1", name="Analytics Dealer One", **dealer_terms
    )
    dx2 = create_dealer(
        profile["id"], dealer_code="DX2", name="Analytics Dealer Two", **dealer_terms
    )
    vehicle_one = create_vehicle(**{**COVERED_VEHICLE, "vin": "VINX0000000000001"})
    vehicle_two = create_vehicle(**{**COVERED_VEHICLE, "vin": "VINX0000000000002"})
    elec_operation = create_labor_operation(**ELEC_OPERATION)
    diag_operation = create_labor_operation(**DIAG_OPERATION)
    elec_part = create_part(**ELEC_PART)

    dx1_headers = make_dealer_warranty_admin_headers(dx1["id"])
    dx2_headers = make_dealer_warranty_admin_headers(dx2["id"])

    paid_claim = submit_claim(
        {
            "dealer": dx1,
            "vehicle": vehicle_one,
            "operation": elec_operation,
            "part": elec_part,
            "dealer_headers": dx1_headers,
        },
        repair_order_number="RO-X1-1",
        repair_date="2026-04-10",
        odometer_at_repair=20000,
        claimed_labor_hours=2.0,
        claimed_parts_qty=1,
        complaint_text="Customer reports intermittent electrical fault.",
        cause_text="Harness chafed through insulation layer.",
        correction_text="Replaced the electrical harness assembly.",
    )
    approve_claim(paid_claim["id"], approved_labor_hours=2.0, approved_parts_qty=1)
    paid_claim = pay_claim(paid_claim["id"])

    unpaid_claim = submit_claim(
        {
            "dealer": dx1,
            "vehicle": vehicle_one,
            "operation": diag_operation,
            "part": None,
            "dealer_headers": dx1_headers,
        },
        repair_order_number="RO-X1-2",
        repair_date="2026-03-01",
        odometer_at_repair=18000,
        claimed_labor_hours=2.0,
        claimed_parts_qty=0,
        complaint_text="Customer reports dash warning lamp on.",
        cause_text="Diagnostic scan traced a transient sensor code.",
        correction_text="Cleared the code and verified no recurrence.",
    )
    unpaid_claim = approve_claim(
        unpaid_claim["id"], approved_labor_hours=2.0, approved_parts_qty=0
    )

    peer_claim = submit_claim(
        {
            "dealer": dx2,
            "vehicle": vehicle_two,
            "operation": diag_operation,
            "part": None,
            "dealer_headers": dx2_headers,
        },
        repair_order_number="RO-X2-1",
        repair_date="2026-04-10",
        odometer_at_repair=12000,
        claimed_labor_hours=0.5,
        claimed_parts_qty=0,
        complaint_text="Customer reports a faint rattle at idle.",
        cause_text="Diagnostic time only, heat shield loose.",
        correction_text="Retorqued the heat shield fastener.",
    )
    approve_claim(peer_claim["id"], approved_labor_hours=0.5, approved_parts_qty=0)
    peer_claim = pay_claim(peer_claim["id"])

    assert paid_claim["approved_total_cents"] == 50000
    assert unpaid_claim["approved_total_cents"] == 20000
    assert peer_claim["approved_total_cents"] == 5000
    return {"dx1": dx1, "dx2": dx2}


class TestPaidVersusIncurredExpenseBasis:
    def test_03_both_expense_bases_are_reported_side_by_side(self):
        """PRD §3.9: "The paid basis sums `approved_total_cents` over the dealer's claims that are in `APPROVED` and whose `payment_status` is exactly `PAID`, reporting the result as `paid_numerator_cents`; a claim that is approved but not yet paid is invisible on this basis, and a claim later charged back to `DEBITED` drops out of it entirely."
        PRD §3.9: "The incurred basis sums `approved_total_cents` over the dealer's claims that are in `APPROVED` whatever their `payment_status` — `UNPAID`, `PAID`, `DEBITED` and `CREDIT_REINSTATED` all count — reporting the result as `incurred_numerator_cents`."
        PRD §3.9: "Each numerator is then divided by the dealer's `vehicles_in_operation` and rounded half up to whole cents, giving `warranty_expense_per_vehicle_paid_cents` and `warranty_expense_per_vehicle_incurred_cents`."
        PRD §3.9: "Alongside them the response reports `paid_claim_count` and `incurred_claim_count`, the number of claims each basis counted."

        Design: Difficulty/dual_variant_calc/dealer_expense_per_vehicle_paid_versus_incurred_basis_divergence
        """
        world = build_two_dealer_analytics_world()

        report = expense_analytics(world["dx1"]["id"])

        assert report["paid_numerator_cents"] == 50000
        assert report["incurred_numerator_cents"] == 70000
        assert report["warranty_expense_per_vehicle_paid_cents"] == 500
        assert report["warranty_expense_per_vehicle_incurred_cents"] == 700
        assert report["paid_claim_count"] == 1
        assert report["incurred_claim_count"] == 2
        assert report["vehicles_in_operation"] == 100

    def test_04_peer_median_and_outlier_ratio_use_only_the_paid_basis(self):
        """PRD §3.9: "The peer comparison always uses the paid basis and never the incurred one."
        PRD §3.9: "With an even number of peers, it is the mean of the two middle values, rounded half up to whole cents."
        PRD §3.9: "`outlier_ratio` is the dealer's own `warranty_expense_per_vehicle_paid_cents` divided by `peer_median_paid_cents`, rounded half up to four decimal places, and is reported as 0 when the median is 0."
        PRD §3.9: "`outlier_flag` is true exactly when that ratio reaches 1.50 or more — a dealer spending half again what the median dealer spends per vehicle in operation is flagged — with the boundary inclusive."
        PRD §3.9: "The computed flag is not merely reported: it is written back onto the dealer's persisted `outlier_flag`, and when that write actually changes the stored value the dealer's `version` advances by 1."

        Design: Difficulty/dual_variant_calc/dealer_expense_per_vehicle_paid_versus_incurred_basis_divergence
        """
        world = build_two_dealer_analytics_world()

        flagged = expense_analytics(world["dx1"]["id"])

        # The two peers are DX1 at 500 and DX2 at 50: round_half_up((50 + 500) / 2) = 275.
        assert flagged["peer_median_paid_cents"] == 275
        # 500 / 275 = 1.8182 on the paid basis, not 700 / 275 = 2.5455 on the incurred one.
        assert flagged["outlier_ratio"] == pytest.approx(1.8182, abs=0.00001)
        assert flagged["outlier_flag"] is True
        assert get_dealer(world["dx1"]["id"])["outlier_flag"] is True

        peer = expense_analytics(world["dx2"]["id"])
        assert peer["warranty_expense_per_vehicle_paid_cents"] == 50
        assert peer["peer_median_paid_cents"] == 275
        assert peer["outlier_ratio"] == pytest.approx(0.1818, abs=0.00001)
        assert peer["outlier_flag"] is False
