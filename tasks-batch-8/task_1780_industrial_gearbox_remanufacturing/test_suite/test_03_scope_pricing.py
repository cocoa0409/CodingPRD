"""Component line pricing: action tiers, rush multiplier, per-line rounding,
scope totals, auto-approval, and the OCC-guarded revision write."""
from test_helpers import (
    ApiErrorId,
    add_decision,
    add_finding,
    assert_component_decision,
    get_order,
    make_customer,
    make_order,
    make_unit,
    setup_order_in_scope_approval,
    setup_order_in_teardown,
    start_teardown,
    validate_error,
    validate_paginated,
    validate_success,
)


def _teardown_order_with_decision(serial, rush, action, labor_hours,
                                  material_cents):
    """One customer/unit/order in TEARDOWN with a single finding+decision."""
    customer = make_customer(legal_name=f"{serial} Co")
    unit = make_unit(customer["id"], serial_number=serial)
    order = make_order(unit["id"], intake_hours=0,
                       quoted_estimate_cents=700_000, rush=rush)
    start_teardown(order["id"])
    add_finding(order["id"], component_code="GEAR_2", condition="CUT_ONLY",
                severity=4, notes="pitting")
    decision = add_decision(order["id"], component_code="GEAR_2",
                            action=action, labor_hours=labor_hours,
                            material_cents=material_cents)
    return order, decision


class TestTieredLaborTimesRushMultiplier:
    def test_rush_multiplier_applies_to_labor_only_cut_new(
            self, api, reman_engineer_headers):
        """PRD §3.3: "Labor is billed per decision at an action-tiered hourly
        rate in cents per hour: `REGRIND` at 8,500, `CUT_NEW` at 14,200,
        `REPLACE_OEM` at 6,000 (labor only — for a replacement the part cost
        rides entirely on `material_cents`), and `REUSE_AS_IS` at 2,500. When
        the order is flagged `rush`, the labor component of every line is
        multiplied by 1.25."

        Design: Difficulty/combinatorial_formula/tiered_labor_rate_times_rush_multiplier_times_hours
        """
        rush_order, rush_decision = _teardown_order_with_decision(
            "GBX-R1", True, "CUT_NEW", 6.5, 450_000)
        normal_order, normal_decision = _teardown_order_with_decision(
            "GBX-N1", False, "CUT_NEW", 6.5, 450_000)

        # round_half_up(6.5 * 14200 * 1.25) = 115375; + 450000 = 565375.
        assert rush_decision["line_total_cents"] == 565_375
        # round_half_up(6.5 * 14200 * 1.0) = 92300; + 450000 = 542300.
        assert normal_decision["line_total_cents"] == 542_300
        # The rush premium lands entirely in labor; material is immune.
        assert (rush_decision["line_total_cents"]
                - normal_decision["line_total_cents"]) == 23_075
        assert_component_decision(rush_decision)
        assert_component_decision(normal_decision)

    def test_rush_multiplier_applies_to_labor_only_reuse_as_is(
            self, api, reman_engineer_headers):
        """PRD §3.3: "When the order is flagged `rush`, the labor component of
        every line is multiplied by 1.25. Each line's `line_total_cents` is
        then: the planned `labor_hours` times the tier rate times the rush
        factor (1.25 when the order is rushed, 1.0 otherwise), rounded
        half-up to integer cents, plus the line's `material_cents`, rounded
        half-up once more".

        Design: Difficulty/combinatorial_formula/tiered_labor_rate_times_rush_multiplier_times_hours
        """
        _, rush_decision = _teardown_order_with_decision(
            "GBX-R2", True, "REUSE_AS_IS", 3.0, 1_000)
        _, normal_decision = _teardown_order_with_decision(
            "GBX-N2", False, "REUSE_AS_IS", 3.0, 1_000)

        # round_half_up(3.0 * 2500 * 1.25) = 9375; + 1000 = 10375.
        assert rush_decision["line_total_cents"] == 10_375
        # round_half_up(3.0 * 2500) = 7500; + 1000 = 8500.
        assert normal_decision["line_total_cents"] == 8_500


class TestRoundPerLineThenSum:
    def test_round_per_line_then_sum_beats_sum_then_round(
            self, api, reman_engineer_headers):
        """PRD §2.9: "each component line is rounded half-up to integer cents
        first, and order-level totals are then the plain sum of those
        already-rounded line values. Summing unrounded lines and rounding
        once at the end produces different cents and is non-conformant."

        Design: Difficulty/combinatorial_formula/per_line_round_then_sum_beats_sum_then_round
        """
        ctx = setup_order_in_teardown(
            serial_number="GBX-RND", quoted_estimate_cents=100_000,
            components=[
                ("PINION_1", "REGRINDABLE", 2, "REGRIND", 1.335, 0),
                ("GEAR_2", "REGRINDABLE", 2, "REGRIND", 2.665, 0),
            ])
        dec1, dec2 = ctx["decisions"]
        # round_half_up(1.335 * 8500) = round_half_up(11347.5) = 11348.
        assert dec1["line_total_cents"] == 11_348
        # round_half_up(2.665 * 8500) = round_half_up(22652.5) = 22653.
        assert dec2["line_total_cents"] == 22_653

        api.submit_scope(ctx["order"]["id"], reman_engineer_headers)
        order = get_order(ctx["order"]["id"])
        # Per-line-then-sum: 11348 + 22653 = 34001. Sum-then-round would
        # give round_half_up(34000.0) = 34000 and is non-conformant.
        assert order["approved_scope_cents"] == 34_001
        assert order["approved_scope_cents"] != 34_000

    def test_round_per_line_then_sum_second_witness(
            self, api, reman_engineer_headers):
        """PRD §2.9: "Where a price is computed from hourly rates and
        multipliers, the rounding rule is fixed: each component line is
        rounded half-up to integer cents first, and order-level totals are
        then the plain sum of those already-rounded line values."

        Design: Difficulty/combinatorial_formula/per_line_round_then_sum_beats_sum_then_round
        """
        ctx = setup_order_in_teardown(
            serial_number="GBX-RN2", quoted_estimate_cents=100_000,
            components=[
                ("PINION_1", "REUSABLE", 1, "REUSE_AS_IS", 1.001, 0),
                ("GEAR_2", "REGRINDABLE", 2, "REGRIND", 0.001, 0),
            ])
        dec1, dec2 = ctx["decisions"]
        # round_half_up(1.001 * 2500) = round_half_up(2502.5) = 2503.
        assert dec1["line_total_cents"] == 2_503
        # round_half_up(0.001 * 8500) = round_half_up(8.5) = 9.
        assert dec2["line_total_cents"] == 9

        api.submit_scope(ctx["order"]["id"], reman_engineer_headers)
        order = get_order(ctx["order"]["id"])
        # 2503 + 9 = 2512; sum-then-round would give round_half_up(2511.0)
        # = 2511.
        assert order["approved_scope_cents"] == 2_512


class TestAutoApprove:
    def test_auto_approve_when_scope_within_estimate(
            self, api, reman_engineer_headers):
        """PRD §3.3: "otherwise — the scope is at or under the estimate — the
        system auto-approves it, driving the order straight `TEARDOWN →
        APPROVED`, flipping every `PENDING` decision to `APPROVED`, adding
        `approved_scope_cents` to the customer's
        `outstanding_approved_cents`, and recomputing `credit_hold`, a fiscal
        footprint identical to an explicit customer approval."

        Design: Corner/calculations/auto_approve_when_scope_within_estimate
        """
        ctx = setup_order_in_teardown(
            serial_number="GBX-AU", quoted_estimate_cents=50_000,
            components=[("PINION_1", "REGRINDABLE", 2, "REGRIND", 2.0, 5_000)])

        data = validate_success(
            api.submit_scope(ctx["order"]["id"], reman_engineer_headers))
        # Scope 22000 (17000 labor + 5000 material) <= estimate 50000.
        assert data["status"] == "APPROVED"
        assert data["approved_scope_cents"] == 22_000

        decisions, _ = validate_paginated(
            api.list_decisions(ctx["order"]["id"], reman_engineer_headers))
        assert len(decisions) == 1
        assert decisions[0]["approval_status"] == "APPROVED"


class TestOccOnReviseScope:
    def test_revise_scope_stale_version_rejected(
            self, api, reman_engineer_headers):
        """PRD §2.7: "The scope-revision write, `POST
        /reman/orders/{orderId}/revise-scope`, requires a non-optional
        `expected_order_version` field carrying the `version` of the
        RemanOrder as the client last observed it. If the order's current
        `version` has advanced beyond that value — for example because
        another revision was submitted in between — the write is rejected
        with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the
        order before revising again."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_revise_scope_rejected
        """
        ctx = setup_order_in_scope_approval(serial_number="GBX-OCC")
        order_id = ctx["order"]["id"]
        observed_version = get_order(order_id)["version"]

        # First revision with the observed version succeeds.
        add_decision(order_id, component_code="PINION_1", action="REGRIND",
                     labor_hours=2.0, material_cents=0)
        data = validate_success(
            api.revise_scope(order_id, observed_version, reman_engineer_headers))
        assert data["approved_scope_cents"] == 17_000  # 2.0h * 8500

        # A second writer posts a replacement decision, then retries the
        # revision with the now-stale observed version.
        add_decision(order_id, component_code="PINION_1", action="REUSE_AS_IS",
                     labor_hours=1.0, material_cents=0)
        resp = api.revise_scope(order_id, observed_version,
                                reman_engineer_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

        # The stale revision did not apply: scope is still the first
        # revision's 17000.
        order = get_order(order_id)
        assert order["approved_scope_cents"] == 17_000
        assert order["status"] == "SCOPE_APPROVAL"
