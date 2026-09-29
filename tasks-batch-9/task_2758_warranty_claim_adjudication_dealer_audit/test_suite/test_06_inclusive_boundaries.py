"""Inclusive boundaries and degenerate edges: one unit either side of each threshold."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_claim,
    create_dealer,
    create_labor_operation,
    create_part,
    create_state_law_profile,
    create_vehicle,
    get_claim,
    get_dealer,
    get_success_data,
    issue_findings,
    list_claim_edits,
    list_ledger_entries,
    make_dealer_warranty_admin_headers,
    pay_claim,
    schedule_audit,
    set_clock,
    start_audit,
    submit_claim,
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

BASIC_TERMS = {
    "model_year": 2024,
    "warranty_start_date": "2024-01-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
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

DIAGNOSTIC_NARRATIVE = {
    "complaint_text": "Customer reports a dash warning lamp on.",
    "cause_text": "Diagnostic scan traced a transient sensor code.",
    "correction_text": "Cleared the code and verified no recurrence.",
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

GOODWILL_VEHICLE = {
    "model_year": 2023,
    "warranty_start_date": "2023-06-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
}

GOODWILL_OPERATION = {
    "op_code": "GW-200",
    "description": "Cabin blower motor replacement",
    "standard_time_hours": 1.0,
    "max_time_hours": 1.5,
    "category": "BASIC",
    "requires_causal_part": True,
    "causal_failure_group": "HVAC",
    "overlap_group": "HVAC",
}

GOODWILL_PART = {
    "part_number": "GW-P1",
    "description": "Cabin blower motor",
    "dealer_net_cents": 40000,
    "failure_group": "HVAC",
    "return_required": False,
    "retention_days": 0,
}


def submit_mileage_boundary_claim(odometer_at_repair, repair_order_number):
    """One diagnostic claim on its own vehicle at the given odometer reading."""
    set_clock("2026-05-01T00:00:00Z")
    profile = create_state_law_profile(**CA_PROFILE)
    dealer = create_dealer(
        profile["id"],
        dealer_code="D-B",
        name="Boundary Dealer",
        vehicles_in_operation=100,
        initial_labor_rate_cents=10000,
        initial_parts_markup_pct=0.25,
    )
    vehicle = create_vehicle(**BASIC_TERMS)
    operation = create_labor_operation(**DIAGNOSTIC_OPERATION)
    return submit_claim(
        {
            "dealer": dealer,
            "vehicle": vehicle,
            "operation": operation,
            "part": None,
            "dealer_headers": make_dealer_warranty_admin_headers(dealer["id"]),
        },
        repair_order_number=repair_order_number,
        repair_date="2026-04-10",
        odometer_at_repair=odometer_at_repair,
        claimed_labor_hours=2.0,
        claimed_parts_qty=0,
        **DIAGNOSTIC_NARRATIVE,
    )


def build_audit_with_no_findings():
    """One paid 50,000-cent claim inside an audit period, with no findings attached."""
    set_clock("2026-05-01T00:00:00Z")
    profile = create_state_law_profile(**CA_PROFILE)
    dealer = create_dealer(
        profile["id"],
        dealer_code="D-ZF",
        name="Zero Finding Dealer",
        vehicles_in_operation=100,
        initial_labor_rate_cents=10000,
        initial_parts_markup_pct=0.25,
    )
    vehicle = create_vehicle(**BASIC_TERMS)
    operation = create_labor_operation(**ELEC_OPERATION)
    part = create_part(**ELEC_PART)
    claim = submit_claim(
        {
            "dealer": dealer,
            "vehicle": vehicle,
            "operation": operation,
            "part": part,
            "dealer_headers": make_dealer_warranty_admin_headers(dealer["id"]),
        },
        repair_order_number="RO-ZF-1",
        repair_date="2026-02-15",
        odometer_at_repair=12000,
        claimed_labor_hours=2.0,
        claimed_parts_qty=1,
        **ELEC_NARRATIVE,
    )
    approved = approve_claim(claim["id"], approved_labor_hours=2.0, approved_parts_qty=1)
    assert approved["approved_total_cents"] == 50000
    pay_claim(claim["id"])
    dealer = get_dealer(dealer["id"])
    audit = schedule_audit(
        dealer,
        period_start="2026-01-01",
        period_end="2026-07-01",
        sample_size=1,
        lead_auditor_user_id="auditor-lead-1",
    )
    audit = start_audit(audit["id"])
    return {"dealer": dealer, "claim": claim, "audit": audit}


def build_ceiling_edge_dealers():
    """Two identical CA dealers at 13750, so both petitions compute a 17600 ceiling."""
    set_clock("2026-05-01T00:00:00Z")
    profile = create_state_law_profile(**CA_PROFILE)
    dealers = []
    for code, name in [("D-E1", "Edge Dealer One"), ("D-E2", "Edge Dealer Two")]:
        dealers.append(
            create_dealer(
                profile["id"],
                dealer_code=code,
                name=name,
                vehicles_in_operation=50,
                initial_labor_rate_cents=13750,
                initial_parts_markup_pct=0.30,
            )
        )
    return dealers


def build_goodwill_edge_claim():
    """The 60,000-cent uncovered claim whose derived manager limit is exactly 48,000."""
    set_clock("2026-05-20T00:00:00Z")
    profile = create_state_law_profile(**CA_PROFILE)
    dealer = create_dealer(
        profile["id"],
        dealer_code="D-GW",
        name="Goodwill Dealer",
        vehicles_in_operation=100,
        initial_labor_rate_cents=10000,
        initial_parts_markup_pct=0.25,
    )
    vehicle = create_vehicle(**GOODWILL_VEHICLE)
    operation = create_labor_operation(**GOODWILL_OPERATION)
    part = create_part(**GOODWILL_PART)
    claim = submit_claim(
        {
            "dealer": dealer,
            "vehicle": vehicle,
            "operation": operation,
            "part": part,
            "dealer_headers": make_dealer_warranty_admin_headers(dealer["id"]),
        },
        repair_order_number="RO-GW-1",
        repair_date="2026-05-14",
        odometer_at_repair=39600,
        claimed_labor_hours=1.0,
        claimed_parts_qty=1,
        complaint_text="Customer reports no airflow from the cabin vents.",
        cause_text="Cabin blower motor seized in the housing.",
        correction_text="Replaced the cabin blower motor and verified airflow.",
    )
    assert claim["coverage_type"] == "NONE"
    assert claim["status"] == "SUSPENDED"
    assert claim["provisional_total_cents"] == 60000
    return claim


class TestCoverageMileageBoundary:
    def test_21_an_odometer_exactly_at_the_basic_mileage_limit_is_still_covered(self):
        """PRD §3.3: "Miles used is the claim's `odometer_at_repair` less the vehicle's `in_service_odometer`."
        PRD §3.3: "Otherwise — for a `BASIC`-category operation, and also for a `POWERTRAIN`-category operation that has run past its powertrain limits — basic terms are tested: if the elapsed months are at most `basic_months` and the miles used are at most `basic_miles`, both bounds inclusive, `coverage_type` becomes `BASIC`."

        Design: Difficulty/boundary_precision_check/coverage_mileage_limit_exact_boundary_36000_versus_36001
        """
        claim = submit_mileage_boundary_claim(36000, "RO-B-AT")

        assert claim["coverage_type"] == "BASIC"
        assert claim["status"] == "SUBMITTED"
        assert claim["provisional_total_cents"] == 20000
        assert claim["suspend_edit_count"] == 0
        assert list_claim_edits(claim["id"]) == []

    def test_22_one_mile_past_the_limit_loses_coverage_and_suspends_the_claim(self):
        """PRD §3.3: "If neither test passes, `coverage_type` becomes `NONE`."
        PRD §3.4: "A `NO_COVERAGE` edit fires when the freshly determined `coverage_type` is `NONE`."
        PRD §3.4: "`suspend_edit_count` is then set to the number of edits just appended whose `severity` is `SUSPEND`, and the claim's `status` follows directly: `SUSPENDED` when that count is greater than zero, `SUBMITTED` when it is zero."

        Design: Difficulty/boundary_precision_check/coverage_mileage_limit_exact_boundary_36000_versus_36001
        """
        claim = submit_mileage_boundary_claim(36001, "RO-B-OVER")

        assert claim["coverage_type"] == "NONE"
        assert claim["status"] == "SUSPENDED"
        assert claim["provisional_total_cents"] == 20000, "pricing still runs"
        assert claim["suspend_edit_count"] == 1

        edits = list_claim_edits(claim["id"], params={"edit_code": "NO_COVERAGE"})
        assert len(edits) == 1
        assert edits[0]["severity"] == "SUSPEND"
        assert edits[0]["resolved_at"] is None


class TestZeroFindingAuditFloor:
    def test_23_an_audit_with_no_findings_lands_on_a_zero_rate_and_the_zero_tier(self):
        """PRD §3.8: "The fourth step derives `error_rate`: when the pinned sampled denominator is zero the rate is zero, and otherwise it is `sample_chargeback_cents` divided by `sample_paid_snapshot_cents`, rounded half up to four decimal places."
        PRD §3.8: "The fifth step selects the extrapolation tier from that rate, with both boundaries inclusive on their lower edge: a rate of at least 0.10 gives an `extrapolation_factor` of 1.00, a rate of at least 0.05 but below 0.10 gives 0.50, and anything below 0.05 gives 0.00 — a dealer whose sampled error rate is under five percent is not extrapolated against at all."

        Design: Difficulty/boundary_precision_check/zero_finding_audit_error_rate_and_tier_floor
        """
        world = build_audit_with_no_findings()

        audit = issue_findings(world["audit"]["id"])

        assert audit["status"] == "FINDINGS_ISSUED"
        assert audit["sample_paid_snapshot_cents"] == 0
        assert audit["population_paid_snapshot_cents"] == 50000
        assert audit["error_rate"] == 0.0
        assert audit["extrapolation_factor"] == 0.00, (
            "0.0 is below the 0.05 half tier, so the factor floors at 0.00"
        )
        assert audit["sample_chargeback_cents"] == 0
        assert audit["extrapolated_chargeback_cents"] == 0
        assert audit["total_chargeback_cents"] == 0

    def test_24_the_clean_issue_leaves_the_ledger_and_the_paid_claim_untouched(self):
        """PRD §3.8: "An audit with no findings at all issues perfectly cleanly: every chargeback figure stays 0, no ledger row is appended, and the appeal window opens anyway."
        PRD §2.8: "A dealer's `chargeback_balance_cents` is *defined* as the signed sum of `amount_cents` over every ledger row naming that dealer, and this equality is an invariant that must hold at every observable instant."

        Design: Difficulty/boundary_precision_check/zero_finding_audit_error_rate_and_tier_floor
        """
        world = build_audit_with_no_findings()

        audit = issue_findings(world["audit"]["id"])
        assert audit["appeal_deadline"] is not None

        assert list_ledger_entries(world["dealer"]["id"]) == []
        dealer = get_dealer(world["dealer"]["id"])
        assert dealer["chargeback_balance_cents"] == 0
        assert dealer["status"] == "ACTIVE"

        claim = get_claim(world["claim"]["id"])
        assert claim["payment_status"] == "PAID"
        assert claim["debited_amount_cents"] == 0


class TestStatutoryCeilingInclusiveBoundary:
    def test_25_a_petition_exactly_at_the_derived_ceiling_is_accepted(self):
        """PRD §3.2: "Either way, a requested rate equal to the ceiling is inside it; only a rate strictly above the ceiling is refused, with `ERR_LABOR_RATE_ABOVE_STATUTORY_CEILING`."
        PRD §3.2: "The ceiling itself is written into `statutory_ceiling_cents` at creation and never recomputed thereafter."

        Design: Difficulty/boundary_precision_check/statutory_ceiling_inclusive_boundary_17600_versus_17601
        """
        at_ceiling_dealer, _ = build_ceiling_edge_dealers()

        response = api_client.create_labor_rate_request(
            {
                "dealer_id": at_ceiling_dealer["id"],
                "requested_labor_rate_cents": 17600,
                "requested_parts_markup_pct": 0.30,
                "sample_repair_order_count": 5,
                "sample_median_rate_cents": 17600,
                "effective_date": "2026-06-01",
                "expected_dealer_version": at_ceiling_dealer["version"],
            },
            make_dealer_warranty_admin_headers(at_ceiling_dealer["id"]),
        )
        request = get_success_data(response)

        assert response.status_code == 201
        assert request["statutory_ceiling_cents"] == 17600
        assert request["requested_labor_rate_cents"] == 17600
        assert request["status"] == "SUBMITTED"
        assert (
            get_dealer(at_ceiling_dealer["id"])["approved_labor_rate_cents"] == 13750
        ), "filing a petition never moves the dealer's approved rate"

    def test_26_one_cent_above_the_derived_ceiling_is_refused_and_creates_nothing(self):
        """PRD §2.11: "Requested rate against the statutory ceiling — `ERR_LABOR_RATE_ABOVE_STATUTORY_CEILING`."
        PRD §3.2: "Either way, a requested rate equal to the ceiling is inside it; only a rate strictly above the ceiling is refused, with `ERR_LABOR_RATE_ABOVE_STATUTORY_CEILING`."

        Design: Difficulty/boundary_precision_check/statutory_ceiling_inclusive_boundary_17600_versus_17601
        """
        _, over_ceiling_dealer = build_ceiling_edge_dealers()

        response = api_client.create_labor_rate_request(
            {
                "dealer_id": over_ceiling_dealer["id"],
                "requested_labor_rate_cents": 17601,
                "requested_parts_markup_pct": 0.30,
                "sample_repair_order_count": 5,
                "sample_median_rate_cents": 17600,
                "effective_date": "2026-06-01",
                "expected_dealer_version": over_ceiling_dealer["version"],
            },
            make_dealer_warranty_admin_headers(over_ceiling_dealer["id"]),
        )

        validate_error(response, ApiErrorId.ERR_LABOR_RATE_ABOVE_STATUTORY_CEILING.value)

        rows = get_success_data(
            api_client.list_labor_rate_requests(
                TEST_USERS["warranty_admin_headers"],
                params={"dealer_id": over_ceiling_dealer["id"]},
            )
        )
        assert rows == []


class TestGoodwillManagerLimitBoundary:
    def test_27_a_request_one_cent_above_the_derived_manager_limit_creates_nothing(self):
        """PRD §3.5: "Strictly above `manager_limit_cents` the request is refused outright with `ERR_GOODWILL_LIMIT_EXCEEDED` (HTTP 422) and no authorization is created."
        PRD §3.5: "Separately, a share cap is formed by taking eighty percent of the claim's `provisional_total_cents` and rounding half up to whole cents — goodwill never covers the entire provisional value of a repair."

        Design: Difficulty/boundary_precision_check/goodwill_manager_limit_inclusive_boundary_48000_versus_48001
        """
        claim = build_goodwill_edge_claim()

        response = api_client.create_goodwill_authorization(
            claim["id"],
            {
                "requested_amount_cents": 48001,
                "policy_adjustment_pct": 0.25,
                "justification": "Loyal customer just outside the mileage limit.",
                "expected_claim_version": claim["version"],
            },
            TEST_USERS["claim_adjudicator_headers"],
        )

        validate_error(response, ApiErrorId.ERR_GOODWILL_LIMIT_EXCEEDED.value)

        rows = get_success_data(
            api_client.list_goodwill_authorizations(
                TEST_USERS["warranty_admin_headers"], params={"claim_id": claim["id"]}
            )
        )
        assert rows == []
        assert get_claim(claim["id"])["version"] == claim["version"]

    def test_28_a_request_exactly_at_the_manager_limit_opens_escalated(self):
        """PRD §3.5: "Above that but at or below `manager_limit_cents` it opens `ESCALATED`."
        PRD §3.5: "`manager_limit_cents` is the lesser of the same share cap and the manager base authority of 250,000 cents (2,500 dollars) multiplied by the same decay multiplier and rounded half up to whole cents."
        PRD §3.5: "The larger of those two fractions, rounded half up to four decimal places, is `out_of_warranty_margin_pct`."

        Design: Difficulty/boundary_precision_check/goodwill_manager_limit_inclusive_boundary_48000_versus_48001
        """
        claim = build_goodwill_edge_claim()

        response = api_client.create_goodwill_authorization(
            claim["id"],
            {
                "requested_amount_cents": 48000,
                "policy_adjustment_pct": 0.25,
                "justification": "Loyal customer just outside the mileage limit.",
                "expected_claim_version": claim["version"],
            },
            TEST_USERS["claim_adjudicator_headers"],
        )
        authorization = get_success_data(response)

        assert response.status_code == 201
        assert authorization["status"] == "ESCALATED", (
            "48000 is above the 40000 adjudicator limit and at the 48000 manager limit"
        )
        assert authorization["out_of_warranty_margin_pct"] == 0.1000
        assert authorization["adjudicator_limit_cents"] == 40000
        assert authorization["manager_limit_cents"] == 48000
        assert authorization["approved_amount_cents"] is None

        unchanged = get_claim(claim["id"])
        assert unchanged["status"] == "SUSPENDED"
        assert unchanged["coverage_type"] == "NONE"
