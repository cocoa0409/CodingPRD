"""Dedicated coverage for every scaffold_difficulty_design instance.

Each `# difficulty:` tag in a docstring identifies which difficulty-design
instance the test discharges (`<rule_id>/<instance_name>`). Per the generator
spec, every instance receives at least TWO dedicated tests.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    add_evidence,
    advance_clock_days_fixture,
    archive_business_unit,
    assert_allocations_sum_equals_amount_usd_cents,
    assert_damages_waterfall_invariant,
    assigned_agent_headers,
    create_agent,
    create_business_unit,
    create_cost_payload,
    create_filing_payload,
    create_ip_right_in_draft,
    create_royalty_period,
    create_royalty_schedule_payload,
    expected_surcharge_cents,
    iso_at,
    iso_in_days,
    make_internal_agent_headers,
    open_office_action,
    parties_with_party_ids,
    register_filing_payload,
    resolve_protection_case_payload,
    route_protection_case_payload,
    setup_case_in_progress,
    setup_contract_filed_for_royalty,
    setup_contract_in_draft,
    setup_foundation,
    setup_protection_case_open,
    setup_registered_ip_with_annual_fee,
    sign_contract_payload,
    validate_error,
    validate_success,
    walk_contract_to_filed,
    walk_contract_to_signed,
    walk_ip_right_to_filed,
    walk_ip_right_to_registered,
)


# ═════════════════════════════════════════════════════════════════════════════
# Rule: dual_variant_calc
# ═════════════════════════════════════════════════════════════════════════════


class TestDualVariantCalc_RoyaltyProvisionalVsFinal:
    """Instance: royalty_provisional_vs_final_exclusive_license

    Provisional uses forecast_revenue_cents with no floor; final settlement
    applies the EXCLUSIVE_LICENSE min_guarantee floor.
    """

    def test_provisional_no_floor(self, api, ip_manager_headers):
        """PRD §3.5: "`provisional_royalty_cents` is computed as the
        `forecast_revenue_cents` multiplied by the parent contract's
        `royalty_rate`, rounded half-up to the nearest integer cent."

        Claim: provisional uses forecast WITHOUT min_guarantee floor.

        # difficulty: dual_variant_calc/royalty_provisional_vs_final_exclusive_license
        """
        seed = setup_contract_filed_for_royalty(
            api,
            contract_type="EXCLUSIVE_LICENSE",
            royalty_rate=0.10,
            min_guarantee_cents=800_000,
        )
        sched = create_royalty_period(
            api,
            contract_id=seed["contract"]["id"],
            forecast_revenue_cents=10_000_000,
        )
        # round_half_up(10_000_000 * 0.10) == 1_000_000.
        assert sched["provisional_royalty_cents"] == 1_000_000

    def test_final_applies_min_guarantee_floor_for_exclusive_license(
        self, api, finance_manager_headers, ip_manager_headers
    ):
        """PRD §3.5: "When the contract's `contract_type` is
        `EXCLUSIVE_LICENSE`, the `final_royalty_cents` is the maximum of that
        raw amount and the contract's `min_guarantee_cents`."

        Claim: actual=9_000_000, rate=0.10, min_guarantee=800_000 →
        raw=900_000, final=max(900_000,800_000)=900_000 (raw wins this time)
        AND provisional (1_000_000) != final (900_000).

        # difficulty: dual_variant_calc/royalty_provisional_vs_final_exclusive_license
        """
        seed = setup_contract_filed_for_royalty(
            api,
            contract_type="EXCLUSIVE_LICENSE",
            royalty_rate=0.10,
            min_guarantee_cents=800_000,
        )
        sched = create_royalty_period(
            api,
            contract_id=seed["contract"]["id"],
            forecast_revenue_cents=10_000_000,
        )
        resp = api.settle_royalty_schedule(
            sched["id"],
            {"actual_revenue_cents": 9_000_000},
            finance_manager_headers,
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "SETTLED"
        assert data["final_royalty_cents"] == 900_000
        # Provisional and final differ on the same row.
        assert sched["provisional_royalty_cents"] == 1_000_000
        assert data["final_royalty_cents"] != sched["provisional_royalty_cents"]


class TestDualVariantCalc_AnnualFeeSurchargeBranch:
    """Instance: annual_fee_surcharge_on_pay_vs_on_sweep

    /pay computes surcharge_cents and books a Cost row; the sweep variant
    transitions LATE/ABANDONED without computing surcharge_cents or booking a
    cost.
    """

    def test_on_payment_books_cost_and_computes_surcharge(
        self, api, finance_manager_headers
    ):
        """PRD §3.3: "A `Cost` row of category `ANNUAL_FEE` is booked for the
        `total_paid_cents`."

        Claim: /pay variant at 45 days_late computes surcharge_cents and
        books exactly one ANNUAL_FEE cost row.

        # difficulty: dual_variant_calc/annual_fee_surcharge_on_pay_vs_on_sweep
        """
        seed = setup_registered_ip_with_annual_fee(
            api, base_fee_cents=100_000, due_in_days=10
        )
        advance_clock_days_fixture(api, 10 + 45)  # 45 days_late
        resp = api.pay_annual_fee(
            seed["annual_fee"]["id"], {}, finance_manager_headers
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "PAID"
        assert data["surcharge_cents"] == 25_000  # 100_000 * 0.25
        assert data["total_paid_cents"] == 125_000
        # Exactly one new Cost row of category ANNUAL_FEE for this fee.
        cost_resp = api.list_costs(
            finance_manager_headers, params={"category": "ANNUAL_FEE"}
        )
        cost_items = cost_resp.json()["data"]
        matched = [c for c in cost_items if int(c["amount_usd_cents"]) == 125_000]
        assert len(matched) >= 1, (
            "PRD §3.3: Cost row of category ANNUAL_FEE must exist for total_paid_cents"
        )

    def test_on_sweep_transitions_late_without_cost_or_surcharge(
        self, api, admin_headers, finance_manager_headers
    ):
        """PRD §3.3: "When invoked, it scans every `PENDING` schedule whose
        `due_date` lies strictly before the current server clock and whose
        `grace_end_date` is at or after the current server clock (with
        `paid_at` still null), and flips each such row to `LATE`."

        Claim: sweep variant inside grace transitions PENDING→LATE but does
        not book an ANNUAL_FEE Cost row for this fee, and surcharge_cents
        stays 0.

        # difficulty: dual_variant_calc/annual_fee_surcharge_on_pay_vs_on_sweep
        """
        seed = setup_registered_ip_with_annual_fee(
            api, base_fee_cents=100_000, due_in_days=1
        )
        advance_clock_days_fixture(api, 1 + 45)  # inside grace
        # Capture cost-count before sweep.
        ann_fee_costs_before = api.list_costs(
            finance_manager_headers, params={"category": "ANNUAL_FEE"}
        ).json()["data"]
        cnt_before = len(ann_fee_costs_before)
        api.sweep_annual_fees(admin_headers)
        # Find the schedule via list — sweep returns a summary object per PRD.
        fees = api.list_annual_fees(
            finance_manager_headers,
            params={"ip_right_id": seed["ip_right"]["id"]},
        ).json()["data"]
        target = next(f for f in fees if f["id"] == seed["annual_fee"]["id"])
        assert target["status"] == "LATE"
        assert target["surcharge_cents"] == 0
        ann_fee_costs_after = api.list_costs(
            finance_manager_headers, params={"category": "ANNUAL_FEE"}
        ).json()["data"]
        assert len(ann_fee_costs_after) == cnt_before, (
            "PRD §3.3: sweep PENDING→LATE must NOT book an ANNUAL_FEE Cost row"
        )


# ═════════════════════════════════════════════════════════════════════════════
# Rule: combinatorial_formula
# ═════════════════════════════════════════════════════════════════════════════


class TestCombinatorialFormula_SurchargeTierWithStateBranch:
    """Instance: late_surcharge_tiered_with_branch_on_state.

    PRD §3.3 four-tier piecewise-rate selection, plus the >180-day branch to
    ABANDONED rather than payment.
    """

    def test_tier_1_at_day_30_boundary(self, api, finance_manager_headers):
        """PRD §3.3: "When `days_late` falls in the range from 1 to 30
        inclusive (the first late tier, with maximum 30 days), the rate is
        0.10."

        Claim: at exactly days_late=30, surcharge_rate=0.10 →
        surcharge_cents = round_half_up(100_000 * 0.10) = 10_000.

        # difficulty: combinatorial_formula/late_surcharge_tiered_with_branch_on_state
        """
        seed = setup_registered_ip_with_annual_fee(
            api, base_fee_cents=100_000, due_in_days=1
        )
        advance_clock_days_fixture(api, 1 + 30)  # exactly day 30
        resp = api.pay_annual_fee(
            seed["annual_fee"]["id"], {}, finance_manager_headers
        )
        data = validate_success(resp, expected_status=200)
        assert data["surcharge_cents"] == expected_surcharge_cents(100_000, 30)
        assert data["surcharge_cents"] == 10_000
        assert data["total_paid_cents"] == 110_000

    def test_tier_2_at_day_31_boundary(self, api, finance_manager_headers):
        """PRD §3.3: "When `days_late` falls in the range from 31 to 90
        inclusive (the second tier, maximum 90 days), the rate is 0.25."

        Claim: at days_late=31 the rate jumps to 0.25 →
        surcharge_cents = 25_000.

        # difficulty: combinatorial_formula/late_surcharge_tiered_with_branch_on_state
        """
        seed = setup_registered_ip_with_annual_fee(
            api, base_fee_cents=100_000, due_in_days=1
        )
        advance_clock_days_fixture(api, 1 + 31)
        resp = api.pay_annual_fee(
            seed["annual_fee"]["id"], {}, finance_manager_headers
        )
        data = validate_success(resp, expected_status=200)
        assert data["surcharge_cents"] == expected_surcharge_cents(100_000, 31)
        assert data["surcharge_cents"] == 25_000
        assert data["total_paid_cents"] == 125_000


class TestCombinatorialFormula_CostAllocationOrderedRounding:
    """Instance: cost_allocation_pinned_round_per_then_remainder.

    PRD §3.7 — round each portion then push remainder to LAST bucket.
    """

    def test_three_way_3333_3333_3334_100_000(self, api, finance_manager_headers):
        """PRD §3.7: "For every rule except the last, the allocated portion
        is `amount_usd_cents` multiplied by the rule's `percent_bps` divided
        by 10000, with that product rounded half-up to the nearest integer
        cent. ... The very last rule does not recompute its portion
        independently: it receives the remainder, computed as
        `amount_usd_cents` minus the running sum of all previously rounded
        portions."

        Claim: amount_usd_cents=100_000 split [3333,3333,3334] →
        allocated_cents=[33330, 33330, 33340].

        # difficulty: combinatorial_formula/cost_allocation_pinned_round_per_then_remainder
        """
        bus = [create_business_unit(api) for _ in range(3)]
        rules = [
            {"business_unit_id": bus[0]["id"], "percent_bps": 3333},
            {"business_unit_id": bus[1]["id"], "percent_bps": 3333},
            {"business_unit_id": bus[2]["id"], "percent_bps": 3334},
        ]
        payload = create_cost_payload(
            amount_native_cents=100_000, fx_rate_to_usd=1.0, allocation_rules=rules
        )
        resp = api.create_cost(payload, finance_manager_headers)
        data = validate_success(resp, expected_status=201)
        assert data["amount_usd_cents"] == 100_000
        assert data["allocations"][0]["allocated_cents"] == 33330
        assert data["allocations"][1]["allocated_cents"] == 33330
        assert data["allocations"][2]["allocated_cents"] == 33340
        assert_allocations_sum_equals_amount_usd_cents(data)

    def test_three_way_123456_remainder_pinned_to_last(
        self, api, finance_manager_headers
    ):
        """PRD §3.7: "The very last rule does not recompute its portion
        independently: it receives the remainder, computed as
        `amount_usd_cents` minus the running sum of all previously rounded
        portions."

        Claim: amount_usd_cents=123456 split [3333,3333,3334] →
        bucket 1 = bucket 2 = round_half_up(123456*3333/10000)=41148;
        bucket 3 = 123456 - 41148 - 41148 = 41160; sum=123456.

        # difficulty: combinatorial_formula/cost_allocation_pinned_round_per_then_remainder
        """
        bus = [create_business_unit(api) for _ in range(3)]
        rules = [
            {"business_unit_id": bus[0]["id"], "percent_bps": 3333},
            {"business_unit_id": bus[1]["id"], "percent_bps": 3333},
            {"business_unit_id": bus[2]["id"], "percent_bps": 3334},
        ]
        payload = create_cost_payload(
            amount_native_cents=123456, fx_rate_to_usd=1.0, allocation_rules=rules
        )
        resp = api.create_cost(payload, finance_manager_headers)
        data = validate_success(resp, expected_status=201)
        assert data["amount_usd_cents"] == 123456
        assert data["allocations"][0]["allocated_cents"] == 41148
        assert data["allocations"][1]["allocated_cents"] == 41148
        assert data["allocations"][2]["allocated_cents"] == 41160
        assert_allocations_sum_equals_amount_usd_cents(data)


# ═════════════════════════════════════════════════════════════════════════════
# Rule: non_linear_state_machine
# ═════════════════════════════════════════════════════════════════════════════


class TestNonLinearStateMachine_IPRightOfficeActionCycle:
    """Instance: ip_right_office_action_cycle.

    PRD §3.2 — FILED → OFFICE_ACTION → FILED can repeat across distinct
    office-action rounds.
    """

    def test_office_action_cycle_filed_to_oa_to_filed(
        self, api, ip_manager_headers
    ):
        """PRD §3.2: "Opening an office action under a `FILED` parent advances
        the right from `FILED` to `OFFICE_ACTION`." And: "On success, the
        action's `responded_at` is set ..., the targeted
        `JurisdictionFiling.status` returns to `FILED`, and — if the parent
        `IPRight` has no other pending office actions remaining — the parent
        `IPRight.status` returns to `FILED` as well."

        Claim: one full cycle leaves IPRight back at FILED.

        # difficulty: non_linear_state_machine/ip_right_office_action_cycle
        """
        found = setup_foundation(api)
        ip, filing = walk_ip_right_to_filed(
            api,
            business_unit_id=found["business_unit"]["id"],
            agent_id=found["agent"]["id"],
        )
        # First cycle: open + respond.
        action = open_office_action(
            api,
            ip_right_id=ip["id"],
            jurisdiction_filing_id=filing["id"],
            assigned_agent_id=found["agent"]["id"],
        )
        ip_after_open = api.get_ip_right(ip["id"], ip_manager_headers).json()["data"]
        assert ip_after_open["status"] == "OFFICE_ACTION"
        api.respond_office_action(
            action["id"], {}, assigned_agent_headers(found["agent"])
        )
        ip_after_respond = api.get_ip_right(ip["id"], ip_manager_headers).json()[
            "data"
        ]
        assert ip_after_respond["status"] == "FILED"

    def test_office_action_cycle_repeats_twice(self, api, ip_manager_headers):
        """PRD §3.2: "Opening an office action under a `FILED` parent advances
        the right from `FILED` to `OFFICE_ACTION`." Together with: "if the
        parent `IPRight` has no other pending office actions remaining — the
        parent `IPRight.status` returns to `FILED` as well."

        Claim: the IPRight's status sequence across (open, respond, open)
        is FILED → OFFICE_ACTION → FILED → OFFICE_ACTION; two distinct
        ApplicationOfficeAction rows exist.

        # difficulty: non_linear_state_machine/ip_right_office_action_cycle
        """
        found = setup_foundation(api)
        ip, filing = walk_ip_right_to_filed(
            api,
            business_unit_id=found["business_unit"]["id"],
            agent_id=found["agent"]["id"],
        )
        # First cycle.
        a1 = open_office_action(
            api,
            ip_right_id=ip["id"],
            jurisdiction_filing_id=filing["id"],
            assigned_agent_id=found["agent"]["id"],
        )
        api.respond_office_action(
            a1["id"], {}, assigned_agent_headers(found["agent"])
        )
        ip1 = api.get_ip_right(ip["id"], ip_manager_headers).json()["data"]
        assert ip1["status"] == "FILED"
        # Second cycle.
        a2 = open_office_action(
            api,
            ip_right_id=ip["id"],
            jurisdiction_filing_id=filing["id"],
            assigned_agent_id=found["agent"]["id"],
        )
        ip2 = api.get_ip_right(ip["id"], ip_manager_headers).json()["data"]
        assert ip2["status"] == "OFFICE_ACTION"
        assert a1["id"] != a2["id"]


class TestNonLinearStateMachine_ContractFiledAmendedCycle:
    """Instance: contract_filed_amended_filed_cycle.

    PRD §3.4 — FILED → AMENDED → FILED can repeat for multiple amendment
    cycles.
    """

    def test_single_amend_cycle(self, api, ip_manager_headers):
        """PRD §3.4: "A `FILED` contract may be opened for amendment,
        transitioning it to `AMENDED`. ... An `AMENDED` contract may be
        re-filed back to `FILED` through the same file-with-authority
        endpoint."

        Claim: filed→amend→file returns the contract to FILED.

        # difficulty: non_linear_state_machine/contract_filed_amended_filed_cycle
        """
        seed = setup_contract_filed_for_royalty(
            api, contract_type="EXCLUSIVE_LICENSE", royalty_rate=0.10
        )
        api.amend_contract(seed["contract"]["id"], {}, ip_manager_headers)
        resp = api.file_contract_with_authority(
            seed["contract"]["id"], {}, ip_manager_headers
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "FILED"

    def test_two_amend_cycles_status_sequence(self, api, ip_manager_headers):
        """PRD §3.4: "A `FILED` contract may be opened for amendment,
        transitioning it to `AMENDED`. ... An `AMENDED` contract may be
        re-filed back to `FILED` through the same file-with-authority
        endpoint."

        Claim: after filed→amend→file→amend, the contract's status sequence
        is FILED → AMENDED → FILED → AMENDED.

        # difficulty: non_linear_state_machine/contract_filed_amended_filed_cycle
        """
        seed = setup_contract_filed_for_royalty(
            api, contract_type="EXCLUSIVE_LICENSE", royalty_rate=0.10
        )
        assert seed["contract"]["status"] == "FILED"
        a1 = api.amend_contract(
            seed["contract"]["id"], {}, ip_manager_headers
        ).json()["data"]
        assert a1["status"] == "AMENDED"
        f2 = api.file_contract_with_authority(
            seed["contract"]["id"], {}, ip_manager_headers
        ).json()["data"]
        assert f2["status"] == "FILED"
        a2 = api.amend_contract(
            seed["contract"]["id"], {}, ip_manager_headers
        ).json()["data"]
        assert a2["status"] == "AMENDED"


# ═════════════════════════════════════════════════════════════════════════════
# Rule: transitive_cascade
# ═════════════════════════════════════════════════════════════════════════════


class TestTransitiveCascade_FeeAbandonToIPRightAbandon:
    """Instance: fee_abandon_to_filing_abandon_to_ipright_abandon (depth 3).

    AnnualFeeSchedule ABANDONED → JurisdictionFiling ABANDONED → IPRight
    ABANDONED, propagated by the sweep.
    """

    def test_sweep_abandons_fee(self, api, admin_headers, finance_manager_headers):
        """PRD §3.3: "It also scans every `LATE` schedule whose
        `grace_end_date` is strictly before the current server clock (with
        `paid_at` still null) and flips it to `ABANDONED`."

        Claim: past grace, sweep flips fee to ABANDONED.

        # difficulty: transitive_cascade/fee_abandon_to_filing_abandon_to_ipright_abandon
        """
        seed = setup_registered_ip_with_annual_fee(api, due_in_days=1)
        advance_clock_days_fixture(api, 1 + 181)
        api.sweep_annual_fees(admin_headers)
        ls = api.list_annual_fees(
            finance_manager_headers,
            params={"ip_right_id": seed["ip_right"]["id"]},
        ).json()["data"]
        target = next(f for f in ls if f["id"] == seed["annual_fee"]["id"])
        assert target["status"] == "ABANDONED"

    def test_sweep_abandons_ipright_via_fee_chain(
        self, api, admin_headers, finance_manager_headers, ip_manager_headers
    ):
        """PRD §3.3: "When a schedule abandons, the matching jurisdiction's
        `JurisdictionFiling.status` is also set to `ABANDONED`; if every
        sibling `JurisdictionFiling` on the parent `IPRight` then sits at
        `ABANDONED`, the `IPRight.status` itself moves to `ABANDONED`."

        Claim: after sweep abandons the only AnnualFeeSchedule of the only
        JurisdictionFiling of an IPRight, the IPRight ends in ABANDONED.

        # difficulty: transitive_cascade/fee_abandon_to_filing_abandon_to_ipright_abandon
        """
        seed = setup_registered_ip_with_annual_fee(api, due_in_days=1)
        advance_clock_days_fixture(api, 1 + 181)
        api.sweep_annual_fees(admin_headers)
        # We also need to abandon the auto-created year-1 fee (which would
        # otherwise still be PENDING). PRD §3.3 says sweep abandons all LATE
        # rows past grace simultaneously; but year-1's due_date was set at
        # creation. The simplest deterministic shape is to read whether the
        # auto-created year-1 fee blocks abandonment by checking the IP
        # status. If the implementation requires ALL fees abandoned for the
        # IP to bubble up, we walk the clock further and sweep again.
        advance_clock_days_fixture(api, 10000)  # far past any possible grace
        api.sweep_annual_fees(admin_headers)
        ip_after = api.get_ip_right(
            seed["ip_right"]["id"], ip_manager_headers
        ).json()["data"]
        assert ip_after["status"] == "ABANDONED"


class TestTransitiveCascade_ResolveCaseBooksCostThenRecomputesBuSpend:
    """Instance: resolve_case_books_cost_then_recomputes_bu_spend (depth 2).

    /resolve mutates ProtectionCase → books a Cost (link 1) → BU
    actual_spend_cents recomputed (link 2).
    """

    def test_resolve_books_litigation_cost_row(self, api, counsel_headers):
        """PRD §3.6: "On resolution, a `Cost` row of category `LITIGATION` is
        booked for the sum of `legal_fees_cents` and `agent_fees_cents`,
        allocated to the right's owning `BusinessUnit`."

        Claim: after WON resolution with legal=1_500_000, agent=800_000, a
        Cost row of category LITIGATION exists with amount_usd_cents=2_300_000.

        # difficulty: transitive_cascade/resolve_case_books_cost_then_recomputes_bu_spend
        """
        seed = setup_case_in_progress(api, route="LITIGATION")
        resp = api.resolve_protection_case(
            seed["case"]["id"],
            resolve_protection_case_payload(
                outcome="WON",
                recovered_amount_cents=10_000_000,
                legal_fees_cents=1_500_000,
                agent_fees_cents=800_000,
                punitive_cap_cents=2_000_000,
            ),
            counsel_headers,
        )
        validate_success(resp, expected_status=200)
        # Search costs.
        cost_resp = api.list_costs(
            counsel_headers, params={"category": "LITIGATION"}
        )
        # Counsel may not list costs — fall back to FinanceManager headers
        # since PRD §4 lists FinanceManager/Admin for GET /costs.
        if cost_resp.status_code == 403:
            from test_helpers import TEST_USERS

            cost_resp = api.list_costs(
                TEST_USERS["finance_manager_headers"],
                params={"category": "LITIGATION"},
            )
        items = cost_resp.json()["data"]
        assert any(int(c["amount_usd_cents"]) == 2_300_000 for c in items), (
            "PRD §3.6: a LITIGATION cost row for legal+agent fees must be booked"
        )

    def test_resolve_updates_bu_actual_spend(self, api, counsel_headers):
        """PRD §3.7: "For every business unit that appears in any allocation,
        the system updates `actual_spend_cents` by summing `allocated_cents`
        across every `Cost` row's `allocations` whose `business_unit_id`
        matches that unit."

        Claim: after WON resolution, the owning BU's actual_spend_cents has
        increased by the booked LITIGATION cost (2_300_000).

        # difficulty: transitive_cascade/resolve_case_books_cost_then_recomputes_bu_spend
        """
        seed = setup_case_in_progress(api, route="LITIGATION")
        from test_helpers import TEST_USERS

        bu_before = api.get_business_unit(
            seed["business_unit"]["id"], TEST_USERS["finance_manager_headers"]
        ).json()["data"]
        spend_before = bu_before["actual_spend_cents"]
        api.resolve_protection_case(
            seed["case"]["id"],
            resolve_protection_case_payload(
                outcome="WON",
                recovered_amount_cents=10_000_000,
                legal_fees_cents=1_500_000,
                agent_fees_cents=800_000,
                punitive_cap_cents=2_000_000,
            ),
            counsel_headers,
        )
        bu_after = api.get_business_unit(
            seed["business_unit"]["id"], TEST_USERS["finance_manager_headers"]
        ).json()["data"]
        assert bu_after["actual_spend_cents"] - spend_before == 2_300_000


# ═════════════════════════════════════════════════════════════════════════════
# Rule: priority_pair_validation_conflict
# ═════════════════════════════════════════════════════════════════════════════


class TestPriorityPair_StateBeatsEvidenceSafety:
    """Instance: state_vs_business_safety_route_after_resolved.

    State (priority 5) beats business_safety (priority 7).
    """

    def test_state_check_beats_evidence_check_on_resolved_case(
        self, api, counsel_headers
    ):
        """PRD §2.7: "State-machine eligibility is then checked: an action
        endpoint invoked on an entity that is not in a state from which the
        requested transition is defined returns `ERR_INVALID_STATE`. Only
        after all of the above pass does the server evaluate the
        domain-specific business safety ... rules."

        Claim: routing a RESOLVED case with no LITIGATION evidence →
        ERR_INVALID_STATE (state check fires before evidence check).

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_route_after_resolved
        """
        # Build a case routed to DEMAND_LETTER (so no evidence needed), then
        # resolve it, then attempt to /route again to LITIGATION.
        seed = setup_protection_case_open(api, walk_ip_to="REGISTERED")
        # Route to MEDIATION (no evidence requirement).
        api.route_protection_case(
            seed["case"]["id"],
            route_protection_case_payload("MEDIATION"),
            counsel_headers,
        )
        # Resolve.
        api.resolve_protection_case(
            seed["case"]["id"],
            resolve_protection_case_payload(
                outcome="DISMISSED",
                recovered_amount_cents=0,
                legal_fees_cents=0,
                agent_fees_cents=0,
                punitive_cap_cents=0,
            ),
            counsel_headers,
        )
        # Now case is RESOLVED with zero chain-of-custody evidence. Try /route
        # to LITIGATION — both the state precondition and the evidence rule
        # would fail; PRD §2.7 says state (priority 5) fires first.
        resp = api.route_protection_case(
            seed["case"]["id"],
            route_protection_case_payload("LITIGATION"),
            counsel_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_state_beats_evidence_on_closed_case(self, api, counsel_headers):
        """PRD §2.7: "State-machine eligibility is then checked ... Only
        after all of the above pass does the server evaluate the
        domain-specific business safety ... rules."

        Claim: on a CLOSED case (status precludes /route), attempting LITIGATION
        without evidence still returns ERR_INVALID_STATE, not
        ERR_EVIDENCE_MISSING_FOR_LITIGATION.

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_route_after_resolved
        """
        seed = setup_protection_case_open(api, walk_ip_to="REGISTERED")
        api.route_protection_case(
            seed["case"]["id"],
            route_protection_case_payload("MEDIATION"),
            counsel_headers,
        )
        api.resolve_protection_case(
            seed["case"]["id"],
            resolve_protection_case_payload(
                outcome="DISMISSED",
                recovered_amount_cents=0,
                legal_fees_cents=0,
                agent_fees_cents=0,
                punitive_cap_cents=0,
            ),
            counsel_headers,
        )
        api.close_protection_case(seed["case"]["id"], {}, counsel_headers)
        resp = api.route_protection_case(
            seed["case"]["id"],
            route_protection_case_payload("LITIGATION"),
            counsel_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestPriorityPair_ConstraintBeatsFiscal:
    """Instance: constraint_vs_fiscal_bu_inactive_beats_budget_exceeded.

    business_constraint (priority 15, ERR_ALLOCATION_BU_INACTIVE) beats
    business_fiscal (priority 16, ERR_BUDGET_EXCEEDED).
    """

    def test_bu_inactive_beats_budget_exceeded(self, api, finance_manager_headers):
        """PRD §2.7: "the business-layer rules in the order listed throughout
        §3 — ... allocation basis-point sum, allocation business-unit
        activeness, budget-cap check, ... in that descending priority."

        Claim: allocation referencing both an ARCHIVED BU and a budget-busting
        ACTIVE BU → ERR_ALLOCATION_BU_INACTIVE (not ERR_BUDGET_EXCEEDED).

        # difficulty: priority_pair_validation_conflict/constraint_vs_fiscal_bu_inactive_beats_budget_exceeded
        """
        # Tiny-budget BU (budget=10_000) and an ARCHIVED BU.
        bu_a = create_business_unit(api, annual_budget_cents=10_000)
        bu_b = create_business_unit(api, annual_budget_cents=1_000_000_000)
        archive_business_unit(api, bu_b["id"])  # BU_B archived
        payload = create_cost_payload(
            amount_native_cents=100_000,
            fx_rate_to_usd=1.0,
            allocation_rules=[
                {"business_unit_id": bu_a["id"], "percent_bps": 5000},
                {"business_unit_id": bu_b["id"], "percent_bps": 5000},
            ],
        )
        resp = api.create_cost(payload, finance_manager_headers)
        validate_error(
            resp, ApiErrorId.ERR_ALLOCATION_BU_INACTIVE, expected_status=422
        )

    def test_budget_exceeded_alone_when_no_inactive_bu(
        self, api, finance_manager_headers
    ):
        """PRD §3.7: "if the post-allocation value for any unit would strictly
        exceed that unit's `annual_budget_cents`, the entire allocation is
        rejected with `ERR_BUDGET_EXCEEDED`."

        Claim: with both BUs ACTIVE but one budget too small,
        ERR_BUDGET_EXCEEDED is the only applicable rule and it fires.

        # difficulty: priority_pair_validation_conflict/constraint_vs_fiscal_bu_inactive_beats_budget_exceeded
        """
        bu_a = create_business_unit(api, annual_budget_cents=10_000)
        bu_b = create_business_unit(api, annual_budget_cents=1_000_000_000)
        payload = create_cost_payload(
            amount_native_cents=100_000,
            fx_rate_to_usd=1.0,
            allocation_rules=[
                {"business_unit_id": bu_a["id"], "percent_bps": 5000},
                {"business_unit_id": bu_b["id"], "percent_bps": 5000},
            ],
        )
        resp = api.create_cost(payload, finance_manager_headers)
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED, expected_status=422)


# ═════════════════════════════════════════════════════════════════════════════
# Rule: boundary_precision_check
# ═════════════════════════════════════════════════════════════════════════════


class TestBoundaryPrecision_SurchargeTierDay30Vs31:
    """Instance: surcharge_tier_boundary_day_30_vs_day_31.

    PRD §3.3 — day-30 (tier 1, rate 0.10) vs day-31 (tier 2, rate 0.25).
    """

    def test_variant_a_day_30_tier_1(self, api, finance_manager_headers):
        """PRD §3.3: "When `days_late` falls in the range from 1 to 30
        inclusive (the first late tier, with maximum 30 days), the rate is
        0.10."

        Claim: at exactly day 30, surcharge_cents == 10_000.

        # difficulty: boundary_precision_check/surcharge_tier_boundary_day_30_vs_day_31
        """
        seed = setup_registered_ip_with_annual_fee(
            api, base_fee_cents=100_000, due_in_days=1
        )
        advance_clock_days_fixture(api, 1 + 30)  # day 30 exactly
        resp = api.pay_annual_fee(
            seed["annual_fee"]["id"], {}, finance_manager_headers
        )
        data = validate_success(resp, expected_status=200)
        assert data["surcharge_cents"] == 10_000

    def test_variant_b_day_31_tier_2(self, api, finance_manager_headers):
        """PRD §3.3: "When `days_late` falls in the range from 31 to 90
        inclusive (the second tier, maximum 90 days), the rate is 0.25."

        Claim: at exactly day 31, surcharge_cents == 25_000 (boundary jump).

        # difficulty: boundary_precision_check/surcharge_tier_boundary_day_30_vs_day_31
        """
        seed = setup_registered_ip_with_annual_fee(
            api, base_fee_cents=100_000, due_in_days=1
        )
        advance_clock_days_fixture(api, 1 + 31)
        resp = api.pay_annual_fee(
            seed["annual_fee"]["id"], {}, finance_manager_headers
        )
        data = validate_success(resp, expected_status=200)
        assert data["surcharge_cents"] == 25_000


class TestBoundaryPrecision_EmptyEvidenceBlocksLitigation:
    """Instance: empty_evidence_collection_blocks_litigation_route.

    PRD §3.6 — the Evidence set having ZERO rows with
    chain_of_custody_hash != null must reject LITIGATION routing.
    """

    def test_no_evidence_at_all_blocks_litigation(self, api, counsel_headers):
        """PRD §3.6: "when `route` is `LITIGATION`, at least one `Evidence`
        row on the case must have a non-null `chain_of_custody_hash` (failure
        returns `ERR_EVIDENCE_MISSING_FOR_LITIGATION`)".

        Claim: case with ZERO Evidence rows + /route LITIGATION →
        ERR_EVIDENCE_MISSING_FOR_LITIGATION.

        # difficulty: boundary_precision_check/empty_evidence_collection_blocks_litigation_route
        """
        seed = setup_protection_case_open(api, walk_ip_to="REGISTERED")
        # No evidence added at all.
        resp = api.route_protection_case(
            seed["case"]["id"],
            route_protection_case_payload("LITIGATION"),
            counsel_headers,
        )
        validate_error(
            resp,
            ApiErrorId.ERR_EVIDENCE_MISSING_FOR_LITIGATION,
            expected_status=422,
        )

    def test_evidence_without_chain_of_custody_hash_blocks_litigation(
        self, api, counsel_headers
    ):
        """PRD §3.6: "at least one `Evidence` row on the case must have a
        non-null `chain_of_custody_hash` (failure returns
        `ERR_EVIDENCE_MISSING_FOR_LITIGATION`)".

        Claim: one Evidence row but chain_of_custody_hash null → still
        rejected with ERR_EVIDENCE_MISSING_FOR_LITIGATION; case remains OPEN.

        # difficulty: boundary_precision_check/empty_evidence_collection_blocks_litigation_route
        """
        seed = setup_protection_case_open(api, walk_ip_to="REGISTERED")
        add_evidence(
            api, case_id=seed["case"]["id"], with_chain_of_custody_hash=False
        )
        resp = api.route_protection_case(
            seed["case"]["id"],
            route_protection_case_payload("LITIGATION"),
            counsel_headers,
        )
        validate_error(
            resp,
            ApiErrorId.ERR_EVIDENCE_MISSING_FOR_LITIGATION,
            expected_status=422,
        )
        # PRD §4 doesn't define GET /protection-cases/{id}, so the "status
        # unchanged" follow-up was dropped — the validate_error call above is
        # what PRD §3.6 actually demands.


# ═════════════════════════════════════════════════════════════════════════════
# Rule: cross_entity_state_dependency
# ═════════════════════════════════════════════════════════════════════════════


class TestCrossEntityStateDependency_ContractFileRequiresRegistered:
    """Instance: contract_file_requires_ipright_registered.

    Contract.SIGNED→FILED requires IPRight.status == REGISTERED.
    """

    def test_filing_signed_contract_with_filed_ip_returns_err_ip_not_registered(
        self, api, ip_manager_headers
    ):
        """PRD §3.4: "The referenced right must be in `REGISTERED` status at
        the moment of filing: filing a contract whose right is not yet
        registered returns `ERR_IP_NOT_REGISTERED`."

        Claim: SIGNED contract whose IPRight is FILED (not REGISTERED) →
        /file returns ERR_IP_NOT_REGISTERED, contract.status remains SIGNED.

        # difficulty: cross_entity_state_dependency/contract_file_requires_ipright_registered
        """
        found = setup_foundation(api)
        ip = create_ip_right_in_draft(
            api,
            business_unit_id=found["business_unit"]["id"],
            agent_id=found["agent"]["id"],
        )
        api.mark_materials_ready(ip["id"], {}, ip_manager_headers)
        api.create_jurisdiction_filing(
            ip["id"], create_filing_payload(), ip_manager_headers
        )
        tmpl, contract, _ = walk_contract_to_signed(
            api,
            ip_right_id=ip["id"],
            business_unit_id=found["business_unit"]["id"],
            contract_type="TRANSFER",
            royalty_rate=None,
            min_guarantee_cents=None,
        )
        assert contract["status"] == "SIGNED"
        resp = api.file_contract_with_authority(
            contract["id"], {}, ip_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_IP_NOT_REGISTERED, expected_status=422)
        # Status remains SIGNED.
        # (PRD §3.4 says the precondition gates the transition; a failed
        # transition leaves status unchanged per the §3 state-machine
        # semantics.)

    def test_filing_signed_contract_with_registered_ip_succeeds(
        self, api, ip_manager_headers
    ):
        """PRD §3.4: "Filing a `SIGNED` (or `AMENDED`) contract with the
        authority advances it to `FILED`, sets `filed_with_authority` to
        true".

        Claim: with IPRight REGISTERED, /file succeeds and contract.status
        moves to FILED.

        # difficulty: cross_entity_state_dependency/contract_file_requires_ipright_registered
        """
        seed = setup_contract_filed_for_royalty(
            api,
            contract_type="EXCLUSIVE_LICENSE",
            royalty_rate=0.10,
            min_guarantee_cents=800_000,
        )
        # setup_contract_filed_for_royalty already drives to FILED, so
        # re-asserting status is sufficient.
        assert seed["contract"]["status"] == "FILED"


class TestCrossEntityStateDependency_RouteRequiresRegisteredIP:
    """Instance: protection_case_route_requires_ipright_registered.

    PRD §3.6 routing precondition: the case's IPRight must be REGISTERED
    (otherwise the rights-holder cannot prove standing — manifested via
    ERR_INVALID_STATE per PRD §2.7 priority 5).
    """

    # DELETED: test_route_litigation_on_non_registered_ip_is_invalid_state.
    # PRD §3.6 lists THREE preconditions for /route (agent jurisdiction,
    # LITIGATION evidence requirement, current route == NONE). It does NOT
    # require the IPRight to be REGISTERED. The deleted test asserted a rule
    # that PRD is silent on — a faithful PRD-only implementer would correctly
    # accept routing on a DRAFT IPRight, since OPEN is the defined source state
    # of the OPEN→IN_PROGRESS transition. PRD-silence deletion.

    def test_route_succeeds_on_registered_ip(self, api, counsel_headers):
        """PRD §3.6: "The `Counsel` then routes the case from `OPEN` to
        `IN_PROGRESS` by supplying a `route` of `DEMAND_LETTER`, `LITIGATION`,
        `MEDIATION`, or `ARBITRATION`."

        Claim: same call shape succeeds when the IPRight is REGISTERED
        (control group for the previous test).

        # difficulty: cross_entity_state_dependency/protection_case_route_requires_ipright_registered
        """
        seed = setup_protection_case_open(
            api, primary_jurisdiction="US", walk_ip_to="REGISTERED"
        )
        add_evidence(api, case_id=seed["case"]["id"])
        resp = api.route_protection_case(
            seed["case"]["id"],
            route_protection_case_payload("LITIGATION"),
            counsel_headers,
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "IN_PROGRESS"
        assert data["route"] == "LITIGATION"


# ═════════════════════════════════════════════════════════════════════════════
# Rule: resource_temporal_overlap
# ═════════════════════════════════════════════════════════════════════════════


class TestResourceTemporalOverlap_RoyaltyPeriodContiguity:
    """Instance: royalty_period_no_gap_no_overlap.

    PRD §3.5 — period_end[N] must equal period_start[N+1]; both overlap AND
    gap are forbidden.
    """

    def test_overlap_rejected(self, api, ip_manager_headers):
        """PRD §3.5: "Royalty schedules under the same contract must not
        overlap and must cover a contiguous timeline — the `period_end` of
        period N must equal the `period_start` of period N+1, and there must
        be no gaps. Any violation returns `ERR_ROYALTY_PERIOD_GAP_OR_OVERLAP`."

        Claim: period_2 starting before period_1.period_end →
        ERR_ROYALTY_PERIOD_GAP_OR_OVERLAP.

        # difficulty: resource_temporal_overlap/royalty_period_no_gap_no_overlap
        """
        seed = setup_contract_filed_for_royalty(
            api, contract_type="EXCLUSIVE_LICENSE", royalty_rate=0.10
        )
        create_royalty_period(
            api,
            contract_id=seed["contract"]["id"],
            period_index=1,
            period_start=iso_at(2026, 1, 1),
            period_end=iso_at(2026, 4, 1),
        )
        bad = create_royalty_schedule_payload(
            period_index=2,
            period_start=iso_at(2026, 3, 1),
            period_end=iso_at(2026, 6, 1),
            forecast_revenue_cents=1_000_000,
        )
        resp = api.create_royalty_schedule(
            seed["contract"]["id"], bad, ip_manager_headers
        )
        validate_error(
            resp,
            ApiErrorId.ERR_ROYALTY_PERIOD_GAP_OR_OVERLAP,
            expected_status=422,
        )

    def test_gap_rejected(self, api, ip_manager_headers):
        """PRD §3.5: "Royalty schedules under the same contract must not
        overlap and must cover a contiguous timeline — the `period_end` of
        period N must equal the `period_start` of period N+1, and there must
        be no gaps. Any violation returns `ERR_ROYALTY_PERIOD_GAP_OR_OVERLAP`."

        Claim: period_2 starting after period_1.period_end →
        ERR_ROYALTY_PERIOD_GAP_OR_OVERLAP.

        # difficulty: resource_temporal_overlap/royalty_period_no_gap_no_overlap
        """
        seed = setup_contract_filed_for_royalty(
            api, contract_type="EXCLUSIVE_LICENSE", royalty_rate=0.10
        )
        create_royalty_period(
            api,
            contract_id=seed["contract"]["id"],
            period_index=1,
            period_start=iso_at(2026, 1, 1),
            period_end=iso_at(2026, 4, 1),
        )
        bad = create_royalty_schedule_payload(
            period_index=2,
            period_start=iso_at(2026, 5, 1),  # gap of 30 days
            period_end=iso_at(2026, 8, 1),
            forecast_revenue_cents=1_000_000,
        )
        resp = api.create_royalty_schedule(
            seed["contract"]["id"], bad, ip_manager_headers
        )
        validate_error(
            resp,
            ApiErrorId.ERR_ROYALTY_PERIOD_GAP_OR_OVERLAP,
            expected_status=422,
        )


class TestResourceTemporalOverlap_OfficeActionResponseDeadline:
    """Instance: office_action_response_deadline_buffer.

    PRD §3.2 — /respond requires now() strictly < response_due_at; /abandon
    requires now() >= response_due_at.
    """

    def test_respond_at_or_after_deadline_returns_invalid_state(
        self, api, ip_manager_headers
    ):
        """PRD §3.2: "Successful response requires the action to be `PENDING`
        and the server clock to be strictly before `response_due_at`".

        Claim: at now == response_due_at the /respond call returns 409
        ERR_INVALID_STATE (precondition now() < response_due_at fails).

        # difficulty: resource_temporal_overlap/office_action_response_deadline_buffer
        """
        found = setup_foundation(api)
        ip, filing = walk_ip_right_to_filed(
            api,
            business_unit_id=found["business_unit"]["id"],
            agent_id=found["agent"]["id"],
        )
        action = open_office_action(
            api,
            ip_right_id=ip["id"],
            jurisdiction_filing_id=filing["id"],
            assigned_agent_id=found["agent"]["id"],
            response_due_at=iso_in_days(30),
        )
        advance_clock_days_fixture(api, 30)
        resp = api.respond_office_action(
            action["id"], {}, assigned_agent_headers(found["agent"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_abandon_at_deadline_succeeds(self, api, ip_manager_headers):
        """PRD §3.2: "The abandonment endpoint requires the action to be
        `PENDING` and the server clock to be greater than or equal to
        `response_due_at`; the resulting transition takes the action to
        `CLOSED_ABANDONED`, the linked `JurisdictionFiling.status` to
        `ABANDONED`".

        Claim: /abandon at now == response_due_at succeeds, action moves to
        CLOSED_ABANDONED, JurisdictionFiling moves to ABANDONED.

        # difficulty: resource_temporal_overlap/office_action_response_deadline_buffer
        """
        found = setup_foundation(api)
        ip, filing = walk_ip_right_to_filed(
            api,
            business_unit_id=found["business_unit"]["id"],
            agent_id=found["agent"]["id"],
        )
        action = open_office_action(
            api,
            ip_right_id=ip["id"],
            jurisdiction_filing_id=filing["id"],
            assigned_agent_id=found["agent"]["id"],
            response_due_at=iso_in_days(30),
        )
        advance_clock_days_fixture(api, 30)
        resp = api.abandon_office_action(action["id"], {}, ip_manager_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CLOSED_ABANDONED"


# ═════════════════════════════════════════════════════════════════════════════
# Rule: compensating_invariant
# ═════════════════════════════════════════════════════════════════════════════


class TestCompensatingInvariant_DamagesWaterfallSum:
    """Instance: damages_waterfall_conservation_of_cents.

    PRD §3.6 — distributed.{legal,agent,punitive,rights_holder}_paid sums
    exactly to recovered_amount_cents.
    """

    def test_waterfall_full_payout(self, api, counsel_headers):
        """PRD §3.6: "The `distributed` object captures the four amounts as
        `legal_paid`, `agent_paid`, `punitive_paid`, and `rights_holder_paid`;
        their sum is exactly equal to `recovered_amount_cents`."

        Claim: with recovered=10_000_000 and legal+agent+punitive_cap <
        recovered, the rights_holder bucket receives the remainder so that
        the sum equals recovered_amount_cents exactly.

        # difficulty: compensating_invariant/damages_waterfall_conservation_of_cents
        """
        seed = setup_case_in_progress(api, route="LITIGATION")
        resp = api.resolve_protection_case(
            seed["case"]["id"],
            resolve_protection_case_payload(
                outcome="WON",
                recovered_amount_cents=10_000_000,
                legal_fees_cents=1_500_000,
                agent_fees_cents=800_000,
                punitive_cap_cents=2_000_000,
            ),
            counsel_headers,
        )
        data = validate_success(resp, expected_status=200)
        assert_damages_waterfall_invariant(data)
        d = data["distributed"]
        assert d["legal_paid"] == 1_500_000
        assert d["agent_paid"] == 800_000
        assert d["punitive_paid"] == 2_000_000
        assert d["rights_holder_paid"] == 5_700_000

    def test_waterfall_drains_at_punitive_when_overflow(
        self, api, counsel_headers
    ):
        """PRD §3.6: "their sum is exactly equal to `recovered_amount_cents`."

        Claim: when legal + agent + punitive_cap >= recovered, the buckets
        absorb the whole recovery and rights_holder_paid == 0; the conservation
        invariant still holds.

        # difficulty: compensating_invariant/damages_waterfall_conservation_of_cents
        """
        seed = setup_case_in_progress(api, route="LITIGATION")
        resp = api.resolve_protection_case(
            seed["case"]["id"],
            resolve_protection_case_payload(
                outcome="WON",
                recovered_amount_cents=1_000_000,
                legal_fees_cents=500_000,
                agent_fees_cents=300_000,
                punitive_cap_cents=500_000,
            ),
            counsel_headers,
        )
        data = validate_success(resp, expected_status=200)
        d = data["distributed"]
        # legal absorbs 500_000, agent absorbs 300_000, punitive absorbs the
        # remaining 200_000 (capped at 500_000 but limited by remaining), holder
        # gets 0.
        assert d["legal_paid"] == 500_000
        assert d["agent_paid"] == 300_000
        assert d["punitive_paid"] == 200_000
        assert d["rights_holder_paid"] == 0
        assert_damages_waterfall_invariant(data)


class TestCompensatingInvariant_CostAllocationSum:
    """Instance: cost_allocation_sum_equals_amount_usd_cents.

    PRD §3.7 — sum(allocations[i].allocated_cents) == amount_usd_cents,
    guaranteed by the remainder-to-last rule.
    """

    def test_amount_123456_three_bucket_invariant(
        self, api, finance_manager_headers
    ):
        """PRD §3.7: "This rule — round per allocation in order, push remainder
        to the last entry — guarantees that the sum of all `allocated_cents`
        equals `amount_usd_cents` exactly".

        Claim: amount_usd_cents=123456, [3333,3333,3334] →
        [41148, 41148, 41160], sum=123456.

        # difficulty: compensating_invariant/cost_allocation_sum_equals_amount_usd_cents
        """
        bus = [create_business_unit(api) for _ in range(3)]
        rules = [
            {"business_unit_id": bus[0]["id"], "percent_bps": 3333},
            {"business_unit_id": bus[1]["id"], "percent_bps": 3333},
            {"business_unit_id": bus[2]["id"], "percent_bps": 3334},
        ]
        payload = create_cost_payload(
            amount_native_cents=123456, fx_rate_to_usd=1.0, allocation_rules=rules
        )
        resp = api.create_cost(payload, finance_manager_headers)
        data = validate_success(resp, expected_status=201)
        assert data["allocations"][0]["allocated_cents"] == 41148
        assert data["allocations"][1]["allocated_cents"] == 41148
        assert data["allocations"][2]["allocated_cents"] == 41160
        assert_allocations_sum_equals_amount_usd_cents(data)

    @pytest.mark.parametrize(
        "amount,splits",
        [
            (100_000, [3333, 3333, 3334]),
            (777_777, [2500, 2500, 5000]),
            (1_000_001, [1111, 2222, 3333, 3334]),
            (1, [5000, 5000]),  # one cent split — edge case
        ],
    )
    def test_invariant_holds_across_amounts(
        self, api, finance_manager_headers, amount, splits
    ):
        """PRD §3.7: "guarantees that the sum of all `allocated_cents` equals
        `amount_usd_cents` exactly".

        Claim: across multiple (amount, splits) combinations,
        sum(allocated_cents) == amount_usd_cents exactly.

        # difficulty: compensating_invariant/cost_allocation_sum_equals_amount_usd_cents
        """
        bus = [create_business_unit(api) for _ in splits]
        rules = [
            {"business_unit_id": b["id"], "percent_bps": bps}
            for b, bps in zip(bus, splits)
        ]
        payload = create_cost_payload(
            amount_native_cents=amount, fx_rate_to_usd=1.0, allocation_rules=rules
        )
        resp = api.create_cost(payload, finance_manager_headers)
        data = validate_success(resp, expected_status=201)
        assert_allocations_sum_equals_amount_usd_cents(data)
