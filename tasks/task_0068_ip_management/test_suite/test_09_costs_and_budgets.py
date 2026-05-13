"""Cost-booking, allocation, and budget tests for the IP Management API.

Covers PRD §3.7:
- amount_usd_cents = round_half_up(amount_native_cents * fx_rate_to_usd) (PRD §2.5)
- allocation_rules basis-points validation (sum to 10000) — ERR_ALLOCATION_BPS_INVALID
- ARCHIVED BU rejection — ERR_ALLOCATION_BU_INACTIVE
- Cost allocation per-allocation round-then-remainder rule (PRD §3.7)
- BusinessUnit.actual_spend_cents updated; budget cap → ERR_BUDGET_EXCEEDED
"""

from test_helpers import (
    ApiErrorId,
    archive_business_unit,
    assert_allocations_sum_equals_amount_usd_cents,
    assert_cost,
    create_business_unit,
    create_cost_payload,
    expected_cost_allocations,
    setup_foundation,
    validate_error,
    validate_success,
    walk_ip_right_to_registered,
)


# ─────────────────────────────────────────────────────────────
# FX conversion (PRD §2.5)
# ─────────────────────────────────────────────────────────────


class TestFxConversion:
    """PRD §2.5 amount_usd_cents derivation."""

    def test_amount_usd_cents_round_half_up(self, api, finance_manager_headers):
        """PRD §2.5: "The conversion is computed by multiplying
        `amount_native_cents` by `fx_rate_to_usd` and rounding half-up to
        the nearest cent; `amount_usd_cents` is the result."

        Claim: amount_native_cents=12345, fx=1.5 → amount_usd_cents=18518
        (= round_half_up(12345*1.5)=round_half_up(18517.5)=18518).
        """
        bu = create_business_unit(api)
        payload = create_cost_payload(
            currency="EUR",
            amount_native_cents=12345,
            fx_rate_to_usd=1.5,
            allocation_rules=[{"business_unit_id": bu["id"], "percent_bps": 10000}],
        )
        resp = api.create_cost(payload, finance_manager_headers)
        data = validate_success(resp, expected_status=201)
        assert_cost(data)
        assert data["amount_usd_cents"] == 18518


# ─────────────────────────────────────────────────────────────
# Basis-points validation (PRD §3.7 ERR_ALLOCATION_BPS_INVALID)
# ─────────────────────────────────────────────────────────────


class TestAllocationBpsValidation:
    """PRD §3.7 — sum of percent_bps must be exactly 10000."""

    def test_bps_under_10000_rejected(self, api, finance_manager_headers):
        """PRD §3.7: "The array must be non-empty and the entries'
        `percent_bps` values must sum to exactly 10000; any violation returns
        `ERR_ALLOCATION_BPS_INVALID`."

        Claim: allocation_rules summing to 9999 → ERR_ALLOCATION_BPS_INVALID.
        """
        bu = create_business_unit(api)
        payload = create_cost_payload(
            allocation_rules=[{"business_unit_id": bu["id"], "percent_bps": 9999}],
        )
        resp = api.create_cost(payload, finance_manager_headers)
        validate_error(
            resp, ApiErrorId.ERR_ALLOCATION_BPS_INVALID, expected_status=422
        )

    def test_empty_allocation_rules_rejected(self, api, finance_manager_headers):
        """PRD §3.7: "The array must be non-empty and the entries'
        `percent_bps` values must sum to exactly 10000; any violation returns
        `ERR_ALLOCATION_BPS_INVALID`."

        Claim: allocation_rules=[] → ERR_ALLOCATION_BPS_INVALID.
        """
        payload = create_cost_payload(allocation_rules=[])
        resp = api.create_cost(payload, finance_manager_headers)
        validate_error(
            resp, ApiErrorId.ERR_ALLOCATION_BPS_INVALID, expected_status=422
        )


# ─────────────────────────────────────────────────────────────
# ARCHIVED BU rejection (PRD §3.7)
# ─────────────────────────────────────────────────────────────


class TestArchivedBusinessUnitRejection:
    """PRD §3.7 — every referenced BU must be ACTIVE."""

    def test_archived_bu_in_allocation_rejected(self, api, finance_manager_headers):
        """PRD §3.7: "Every referenced business unit must have `status` equal
        to `ACTIVE`; an allocation targeting an `ARCHIVED` unit returns
        `ERR_ALLOCATION_BU_INACTIVE`."

        Claim: an allocation_rule referencing an ARCHIVED BU →
        ERR_ALLOCATION_BU_INACTIVE.
        """
        bu = create_business_unit(api)
        archive_business_unit(api, bu["id"])
        payload = create_cost_payload(
            allocation_rules=[{"business_unit_id": bu["id"], "percent_bps": 10000}],
        )
        resp = api.create_cost(payload, finance_manager_headers)
        validate_error(
            resp, ApiErrorId.ERR_ALLOCATION_BU_INACTIVE, expected_status=422
        )


# ─────────────────────────────────────────────────────────────
# Round-per-allocation rule (PRD §3.7) — core dual-mode invariant
# ─────────────────────────────────────────────────────────────


class TestAllocationRoundingRule:
    """PRD §3.7 — per-allocation round-half-up, remainder pinned to last."""

    def test_three_way_split_remainder_to_last(self, api, finance_manager_headers):
        """PRD §3.7: "For every rule except the last, the allocated portion
        is `amount_usd_cents` multiplied by the rule's `percent_bps` divided
        by 10000, with that product rounded half-up to the nearest integer
        cent. ... The very last rule does not recompute its portion
        independently: it receives the remainder, computed as
        `amount_usd_cents` minus the running sum of all previously rounded
        portions."

        Claim: amount_usd_cents=100_000 split [3333, 3333, 3334] →
        [33330, 33330, 33340]; remainder 100_000 - 33330 - 33330 == 33340.
        """
        bu_a = create_business_unit(api)
        bu_b = create_business_unit(api)
        bu_c = create_business_unit(api)
        rules = [
            {"business_unit_id": bu_a["id"], "percent_bps": 3333},
            {"business_unit_id": bu_b["id"], "percent_bps": 3333},
            {"business_unit_id": bu_c["id"], "percent_bps": 3334},
        ]
        payload = create_cost_payload(
            amount_native_cents=100_000,
            fx_rate_to_usd=1.0,
            allocation_rules=rules,
        )
        resp = api.create_cost(payload, finance_manager_headers)
        data = validate_success(resp, expected_status=201)
        assert data["amount_usd_cents"] == 100_000
        # Verify per-bucket cents match the PRD's per-allocation-round-then-remainder rule.
        allocs = data["allocations"]
        assert len(allocs) == 3
        assert allocs[0]["allocated_cents"] == 33330
        assert allocs[1]["allocated_cents"] == 33330
        assert allocs[2]["allocated_cents"] == 33340  # remainder
        # And the global conservation invariant (also tested in difficulty file).
        assert_allocations_sum_equals_amount_usd_cents(data)

    def test_allocation_invariant_holds_for_unusual_split(
        self, api, finance_manager_headers
    ):
        """PRD §3.7: "guarantees that the sum of all `allocated_cents` equals
        `amount_usd_cents` exactly".

        Claim: 100_000 split [5000, 2500, 2500] sums to 100_000.
        """
        bus = [create_business_unit(api) for _ in range(3)]
        rules = [
            {"business_unit_id": bus[0]["id"], "percent_bps": 5000},
            {"business_unit_id": bus[1]["id"], "percent_bps": 2500},
            {"business_unit_id": bus[2]["id"], "percent_bps": 2500},
        ]
        payload = create_cost_payload(
            amount_native_cents=100_000, fx_rate_to_usd=1.0, allocation_rules=rules
        )
        resp = api.create_cost(payload, finance_manager_headers)
        data = validate_success(resp, expected_status=201)
        assert_allocations_sum_equals_amount_usd_cents(data)


# ─────────────────────────────────────────────────────────────
# Budget cap (PRD §3.7)
# ─────────────────────────────────────────────────────────────


class TestBudgetCap:
    """PRD §3.7 ERR_BUDGET_EXCEEDED."""

    def test_allocation_above_budget_rejected(self, api, finance_manager_headers):
        """PRD §3.7: "Before committing an allocation, the system simulates
        the resulting `actual_spend_cents` for every affected business unit;
        if the post-allocation value for any unit would strictly exceed that
        unit's `annual_budget_cents`, the entire allocation is rejected with
        `ERR_BUDGET_EXCEEDED`."

        Claim: BU with budget=10_000, posting a Cost of 100_000 fully
        allocated to it → ERR_BUDGET_EXCEEDED.
        """
        tiny_bu = create_business_unit(api, annual_budget_cents=10_000)
        payload = create_cost_payload(
            amount_native_cents=100_000,
            fx_rate_to_usd=1.0,
            allocation_rules=[
                {"business_unit_id": tiny_bu["id"], "percent_bps": 10000}
            ],
        )
        resp = api.create_cost(payload, finance_manager_headers)
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED, expected_status=422)

    def test_bu_actual_spend_reflects_allocations(
        self, api, finance_manager_headers
    ):
        """PRD §3.7: "For every business unit that appears in any allocation,
        the system updates `actual_spend_cents` by summing `allocated_cents`
        across every `Cost` row's `allocations` whose `business_unit_id`
        matches that unit. No status filter is applied — every booked cost
        counts."

        Claim: after booking a Cost wholly allocated to BU, GET
        /business-units/{id} returns actual_spend_cents == amount_usd_cents.
        """
        bu = create_business_unit(api, annual_budget_cents=10_000_000_00)
        payload = create_cost_payload(
            amount_native_cents=250_000,
            fx_rate_to_usd=1.0,
            allocation_rules=[{"business_unit_id": bu["id"], "percent_bps": 10000}],
        )
        api.create_cost(payload, finance_manager_headers)
        bu_after = api.get_business_unit(bu["id"], finance_manager_headers).json()[
            "data"
        ]
        assert bu_after["actual_spend_cents"] == 250_000
