"""Allocation plans: PRO_RATA truncation and remainder distribution,
PRIORITY_TIER waterfall, fulfillment bounds, and plan-level optimistic
concurrency (PRD §2.5, §2.6, §3.7)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_active_formula, create_allocation_plan, add_allocation_entry,
    activate_plan, get_entry, get_plan_version, set_clock,
)


def _plan_with_entries(users, formula_code, profile_code, method, total,
                       entries):
    """ACTIVE formula + DRAFT plan + entries. Returns (scenario, plan, entries)."""
    set_clock(users)
    scenario = create_active_formula(
        users, formula_code=formula_code, profile_code=profile_code)
    plan = create_allocation_plan(users, scenario["formula"]["id"], total, method)
    created = [add_allocation_entry(users, plan["id"], **entry)
               for entry in entries]
    return scenario, plan, created


class TestProRataAllocation:
    def test_pro_rata_allocates_proportionally(self, api, users):
        """PRD §3.7: "`PRO_RATA`. Sum the `requested_kg` across every entry
        currently in `PENDING` status. If the total requested is at most
        `total_available_kg`, every entry is allocated exactly its requested
        quantity. Otherwise, compute the ratio of `total_available_kg` to total
        requested, and process entries in `created_at` ascending order: for
        each entry, multiply its `requested_kg` by the ratio, truncate the
        result down to 3 decimal places (floor at the milligram step), and
        assign that as `allocated_kg`." Ratio 300/600 = 0.5 here.

        Design: Difficulty/dual_variant_calc/allocation_pro_rata_provisional_vs_final
        """
        _scenario, plan, entries = _plan_with_entries(
            users, "IF-FOLLOW-2", "INF-6-12M", "PRO_RATA", 300.000,
            [{"customer_code": "CUST-A", "requested_kg": 100.000},
             {"customer_code": "CUST-B", "requested_kg": 200.000},
             {"customer_code": "CUST-C", "requested_kg": 300.000}])
        activate_plan(users, plan["id"])
        allocated = [get_entry(users, e["id"])["allocated_kg"] for e in entries]
        assert allocated == [50.000, 100.000, 150.000], (
            f"Expected [50.000, 100.000, 150.000], got {allocated}")

    def test_activation_transitions_plan_to_active(self, api, users):
        """PRD §3.7: "Activation — `DRAFT → ACTIVE`, performed by a
        `SUPPLY_CHAIN_PLANNER` — stamps `activated_at` from the logical clock,
        runs the allocation calculation, and populates `allocated_kg` on every
        entry."

        Design: Difficulty/dual_variant_calc/allocation_pro_rata_provisional_vs_final
        """
        _scenario, plan, _entries = _plan_with_entries(
            users, "IF-FOLLOW-2B", "INF-6-12M", "PRO_RATA", 300.000,
            [{"customer_code": "CUST-A", "requested_kg": 100.000}])
        activated = activate_plan(users, plan["id"])
        assert activated["status"] == "ACTIVE"
        assert activated.get("activated_at"), "activated_at must be stamped"


class TestProRataRemainderDistribution:
    def test_remainder_goes_to_first_created_entry(self, api, users):
        """PRD §3.7: "for each entry, multiply its `requested_kg` by the ratio,
        truncate the result down to 3 decimal places (floor at the milligram
        step), and assign that as `allocated_kg`. After the pass, compute the
        remainder as `total_available_kg` minus the sum of all `allocated_kg`
        values, and walk the entries again in `created_at` ascending order,
        adding 0.001 to each entry in turn while the remainder is at least
        0.001." Three equal 100 kg requests over 100 kg truncate to 33.333
        each, leaving a 0.001 remainder granted to the first-created entry.

        Design: Difficulty/combinatorial_formula/pro_rata_allocation_remainder_distribution
        """
        _scenario, plan, entries = _plan_with_entries(
            users, "CEREAL-RICE-1", "CEREAL-6M", "PRO_RATA", 100.000,
            [{"customer_code": "CUST-X", "requested_kg": 100.000},
             {"customer_code": "CUST-Y", "requested_kg": 100.000},
             {"customer_code": "CUST-Z", "requested_kg": 100.000}])
        activate_plan(users, plan["id"])
        allocated = [get_entry(users, e["id"])["allocated_kg"] for e in entries]
        assert allocated == [33.334, 33.333, 33.333], (
            f"Expected [33.334, 33.333, 33.333], got {allocated}")

    def test_allocation_total_conserved(self, api, users):
        """PRD §2.5: "Allocation arithmetic **truncates** intermediate results
        down to 3 decimal places (floor semantics) rather than rounding —
        surplus kilograms are never manufactured by rounding." The allocated
        total never exceeds the available quantity, and the remainder walk
        (PRD §3.7) distributes what truncation left behind, so the total
        allocated equals the available 100.000 kg here.

        Design: Difficulty/combinatorial_formula/pro_rata_allocation_remainder_distribution
        """
        _scenario, plan, entries = _plan_with_entries(
            users, "CEREAL-RICE-2", "CEREAL-6M", "PRO_RATA", 100.000,
            [{"customer_code": "CUST-X", "requested_kg": 100.000},
             {"customer_code": "CUST-Y", "requested_kg": 100.000},
             {"customer_code": "CUST-Z", "requested_kg": 100.000}])
        activate_plan(users, plan["id"])
        total = sum(get_entry(users, e["id"])["allocated_kg"] for e in entries)
        assert abs(total - 100.000) < 1e-9, (
            f"Allocated total must conserve 100.000 kg, got {total}")


class TestPriorityTierWaterfall:
    def _tiered_plan(self, users):
        return _plan_with_entries(
            users, "PUREE-APPLE-1", "PUREE-4M", "PRIORITY_TIER", 250.000,
            [{"customer_code": "HOSP-A", "requested_kg": 100.000, "priority_tier": 1},
             {"customer_code": "RETAIL-B", "requested_kg": 200.000, "priority_tier": 2},
             {"customer_code": "RETAIL-C", "requested_kg": 100.000, "priority_tier": 2},
             {"customer_code": "ONLINE-D", "requested_kg": 50.000, "priority_tier": 3}])

    def test_tier_one_filled_fully_and_unreached_tier_gets_zero(self, api, users):
        """PRD §3.7: "`PRIORITY_TIER`. Walk tiers from 1 to 10 in ascending
        order. ... If `remaining` is at least the tier's total requested,
        allocate every entry in the tier its full `requested_kg` and subtract
        that total from `remaining`, then move to the next tier. ... every
        entry in any higher tier number receives `allocated_kg` of zero."
        Tier 1 (100 kg) is filled from 250 kg; the partial tier 2 consumes the
        remaining 150 kg, leaving tier 3 unreached.

        Design: Difficulty/combinatorial_formula/priority_tier_waterfall_with_partial_tier
        """
        _scenario, plan, entries = self._tiered_plan(users)
        activate_plan(users, plan["id"])
        tier1 = get_entry(users, entries[0]["id"])
        tier3 = get_entry(users, entries[3]["id"])
        assert tier1["allocated_kg"] == 100.000
        assert tier3["allocated_kg"] == 0.000, (
            f"Unreached tier 3 must be allocated 0.000, got {tier3['allocated_kg']}")

    def test_partial_tier_allocated_pro_rata_within_tier(self, api, users):
        """PRD §3.7: "Otherwise, compute the ratio of `remaining` to the tier's
        total requested and apply the same per-entry truncation and 0.001-step
        remainder distribution within the tier (in `created_at` ascending
        order), set `remaining` to zero, and stop". Tier 2 requests 300 kg
        against 150 kg remaining: ratio 0.5 yields 100.000 and 50.000 exactly.

        Design: Difficulty/combinatorial_formula/priority_tier_waterfall_with_partial_tier
        """
        _scenario, plan, entries = self._tiered_plan(users)
        activate_plan(users, plan["id"])
        tier2 = [get_entry(users, entries[1]["id"])["allocated_kg"],
                 get_entry(users, entries[2]["id"])["allocated_kg"]]
        assert tier2 == [100.000, 50.000], (
            f"Expected tier-2 pro-rata [100.000, 50.000], got {tier2}")
        total = sum(get_entry(users, e["id"])["allocated_kg"] for e in entries)
        assert abs(total - 250.000) < 1e-9, (
            f"Allocated total must equal 250.000, got {total}")


class TestFulfillmentBounds:
    def test_fulfillment_exceeding_allocation_rejected(self, api, users):
        """PRD §3.7: "The parent plan must be in `ACTIVE` status, and the
        cumulative `fulfilled_kg` after this record must not exceed the entry's
        `allocated_kg`; otherwise the record is rejected with
        `ERR_FULFILLMENT_EXCEEDS_ALLOCATION` (HTTP 422)." The entry is
        allocated 50.000; a 25.000 record succeeds (leaving the entry
        PARTIALLY_FULFILLED and the plan ACTIVE), and a further 25.001 would
        push the cumulative total to 50.001.

        Design: Corner/state_machines/allocation_entry_idempotent_double_fulfillment_rejected
        """
        _scenario, plan, entries = _plan_with_entries(
            users, "CEREAL-IDEM", "CEREAL-6M", "PRO_RATA", 50.000,
            [{"customer_code": "CUST-IDEM", "requested_kg": 100.000}])
        activate_plan(users, plan["id"])
        entry_id = entries[0]["id"]
        assert get_entry(users, entry_id)["allocated_kg"] == 50.000
        first = api.record_fulfillment(
            entry_id, {"fulfilled_kg": 25.000}, users["scp"]["headers"])
        validate_success(first)
        res = api.record_fulfillment(
            entry_id, {"fulfilled_kg": 25.001}, users["scp"]["headers"])
        validate_error(res, ApiErrorId.ERR_FULFILLMENT_EXCEEDS_ALLOCATION)


class TestPlanOptimisticConcurrency:
    def test_stale_plan_version_rejected_on_activate(self, api, users):
        """PRD §2.6: "Activating an allocation plan requires the request body
        to include `expected_plan_version`, matching the current `version` of
        the target `AllocationPlan`. Because adding or removing an entry
        increments the plan's `version`, this prevents activating a plan whose
        entry list has changed since the client last read it." and "The server
        compares the submitted value against the parent's current `version` and
        rejects the request with `ERR_STALE_VERSION` (HTTP 412) on mismatch".

        Design: Difficulty/concurrency_occ_stale_version/stale_plan_version_on_activate
        """
        _scenario, plan, entries = _plan_with_entries(
            users, "CEREAL-OCC-1", "CEREAL-6M", "PRO_RATA", 100.000,
            [{"customer_code": "CUST-OCC-1", "requested_kg": 50.000}])
        stale_version = get_plan_version(users, plan["id"])
        add_allocation_entry(users, plan["id"], "CUST-OCC-2", 50.000)
        res = api.activate_allocation_plan(
            plan["id"], {"expected_plan_version": stale_version},
            users["scp"]["headers"])
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    def test_entry_creation_increments_plan_version(self, api, users):
        """PRD §3.7: "Every entry creation increments the parent plan's
        `version` by one." (Also PRD §2.7: "Allocation entry mutation cascades
        onto plan version. Every entry added to a plan increments the plan's
        `version` by one".)

        Design: Difficulty/concurrency_occ_stale_version/stale_plan_version_on_activate
        """
        _scenario, plan, _entries = _plan_with_entries(
            users, "CEREAL-OCC-2", "CEREAL-6M", "PRO_RATA", 100.000,
            [{"customer_code": "CUST-OCC-1", "requested_kg": 50.000}])
        before = get_plan_version(users, plan["id"])
        add_allocation_entry(users, plan["id"], "CUST-OCC-2", 50.000)
        after = get_plan_version(users, plan["id"])
        assert after == before + 1, (
            f"Plan version must increment by one per entry: {before} -> {after}")
