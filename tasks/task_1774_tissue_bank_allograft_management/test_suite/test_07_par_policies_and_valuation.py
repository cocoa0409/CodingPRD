"""Par-level policies and inventory valuation: supersession, optimistic
concurrency, replenishment signals, and the FIFO / WEIGHTED_AVERAGE split."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_par_policy,
    issue_unit,
    make_manifest_item,
    release_units,
    setup_accepted_units,
    setup_available_units,
    setup_valuation_population,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
QM = TEST_USERS["quality_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestPolicySupersession:
    def test_policy_create_supersedes_active_with_matching_version(self, api):
        """PRD §3.9: "At most one policy per tissue type is `ACTIVE` at a time:
        creating a policy where one is already active supersedes the incumbent
        — the incumbent moves to the terminal `SUPERSEDED` state with its
        `version` incremented by one, and the newcomer takes over as `ACTIVE`."

        Design: Corner/state_machines/policy_create_supersedes_active_with_matching_version
        """
        p1 = create_par_policy(tissue_type="BONE", par_quantity=2,
                               max_inventory_value_cents=25000)
        assert p1["status"] == "ACTIVE"
        p2 = validate_success(
            api.create_par_policy(
                {
                    "tissue_type": "BONE",
                    "par_quantity": 4,
                    "max_inventory_value_cents": 40000,
                    "expected_current_policy_version": p1["version"],
                },
                ADMIN,
            ),
            201,
        )
        assert p2["status"] == "ACTIVE"
        assert p2["par_quantity"] == 4
        p1_after = validate_success(api.get_par_policy(p1["id"], ADMIN))
        assert p1_after["status"] == "SUPERSEDED"
        assert p1_after["version"] == p1["version"] + 1

    def test_policy_supersede_stale_version_rejected(self, api):
        """PRD §2.7: "Creating a par-level policy (`POST
        /tissue-bank/par-level-policies`) for a tissue type that already has an
        `ACTIVE` policy supersedes that policy, and the request must carry
        `expected_current_policy_version` matching the currently `ACTIVE`
        policy's `version`. A missing `expected_current_policy_version` is
        treated as 0, which matches only when no `ACTIVE` policy exists for
        that tissue type. Any other mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/occ_policy_supersede_stale_version
        """
        p1 = create_par_policy(tissue_type="BONE", par_quantity=2,
                               max_inventory_value_cents=25000)
        updated = validate_success(
            api.update_par_policy(
                p1["id"],
                {"par_quantity": 9,
                 "expected_par_level_policy_version": p1["version"]},
                ADMIN,
            )
        )
        assert updated["version"] == p1["version"] + 1
        # The previously observed version is now stale for a create-supersede.
        resp = api.create_par_policy(
            {
                "tissue_type": "BONE",
                "par_quantity": 4,
                "max_inventory_value_cents": 40000,
                "expected_current_policy_version": p1["version"],
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        # Supersede against the current version succeeds.
        p2 = validate_success(
            api.create_par_policy(
                {
                    "tissue_type": "BONE",
                    "par_quantity": 4,
                    "max_inventory_value_cents": 40000,
                    "expected_current_policy_version": updated["version"],
                },
                ADMIN,
            ),
            201,
        )
        assert p2["status"] == "ACTIVE"
        p1_after = validate_success(api.get_par_policy(p1["id"], ADMIN))
        assert p1_after["status"] == "SUPERSEDED"

    def test_policy_update_stale_version_rejected(self, api):
        """PRD §2.7: "Updating a par-level policy's thresholds (`PUT
        /tissue-bank/par-level-policies/{id}`) requires
        `expected_par_level_policy_version` matching the policy's current
        `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
        The OCC check on all three endpoints is evaluated before any business
        rule of the request."

        Design: Corner/validations/occ_policy_update_stale_version
        """
        p1 = create_par_policy(tissue_type="SOFT_TISSUE", par_quantity=3,
                               max_inventory_value_cents=60000)
        updated = validate_success(
            api.update_par_policy(
                p1["id"],
                {"max_inventory_value_cents": 70000,
                 "expected_par_level_policy_version": p1["version"]},
                ADMIN,
            )
        )
        assert updated["version"] == p1["version"] + 1
        resp = api.update_par_policy(
            p1["id"],
            {"max_inventory_value_cents": 80000,
             "expected_par_level_policy_version": p1["version"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = validate_success(api.get_par_policy(p1["id"], ADMIN))
        assert after["max_inventory_value_cents"] == 70000


class TestParReplenishmentSignals:
    def test_par_on_hand_excludes_quarantined_units(self, api):
        """PRD §3.9: "`on_hand_available` counts only units of the policy's
        tissue type currently `AVAILABLE` — quarantined, reserved, issued, and
        terminal units are all excluded. `deficit` is the larger of zero and
        `par_quantity` minus `on_hand_available`. `needs_reorder` is true only
        when `on_hand_available` is strictly below `par_quantity`; sitting
        exactly at par means no reorder."

        Design: Corner/calculations/par_on_hand_excludes_quarantined_units
        """
        policy = create_par_policy(tissue_type="BONE", par_quantity=2)
        _, _, _, units = setup_accepted_units(
            items=[
                make_manifest_item(serial_number="U-001"),
                make_manifest_item(serial_number="U-002"),
            ]
        )
        # Only U-001 is released; U-002 remains QUARANTINED.
        release_units([units[0]])
        after = validate_success(api.get_par_policy(policy["id"], ADMIN))
        assert after["on_hand_available"] == 1
        assert after["deficit"] == 1
        assert after["needs_reorder"] is True

    def test_par_exactly_met_no_reorder(self, api):
        """PRD §3.9: "`needs_reorder` is true only when `on_hand_available` is
        strictly below `par_quantity`; sitting exactly at par means no
        reorder."
        PRD §3.9: "`deficit` is the larger of zero and `par_quantity` minus
        `on_hand_available`."

        Design: Difficulty/boundary_precision_check/par_level_exactly_met_no_reorder
        """
        policy = create_par_policy(tissue_type="BONE", par_quantity=2)
        _, _, _, units = setup_available_units(
            items=[
                make_manifest_item(serial_number="U-001"),
                make_manifest_item(serial_number="U-002"),
            ]
        )
        after = validate_success(api.get_par_policy(policy["id"], ADMIN))
        assert after["on_hand_available"] == 2
        assert after["deficit"] == 0
        assert after["needs_reorder"] is False

    def test_par_one_below_boundary_triggers_reorder(self, api):
        """PRD §3.9: "`needs_reorder` is true only when `on_hand_available` is
        strictly below `par_quantity`; sitting exactly at par means no
        reorder."
        PRD §3.9: "These figures are recomputed whenever a unit status mutation
        touches the tissue type — excursion and recall cascades, releases,
        reservations, issues, returns, and sweeps all flow through them."

        Design: Difficulty/boundary_precision_check/par_level_exactly_met_no_reorder
        """
        policy = create_par_policy(tissue_type="BONE", par_quantity=2)
        _, _, _, units = setup_available_units(
            items=[
                make_manifest_item(serial_number="U-001"),
                make_manifest_item(serial_number="U-002"),
            ]
        )
        at_par = validate_success(api.get_par_policy(policy["id"], ADMIN))
        assert at_par["on_hand_available"] == 2
        assert at_par["needs_reorder"] is False
        issue_unit(units[0]["id"])
        below = validate_success(api.get_par_policy(policy["id"], ADMIN))
        assert below["on_hand_available"] == 1
        assert below["deficit"] == 1
        assert below["needs_reorder"] is True


class TestInventoryValuation:
    def test_weighted_average_valuation(self, api):
        """PRD §3.9: "The weighted-average method values every on-hand unit at
        the mean cost of the accepted population. The mean is the exact,
        unrounded quotient of the summed `unit_cost_cents` across the whole
        population divided by the population size. For each distinct
        `lot_number` present among the on-hand units, taken in ascending lot
        order, a lot line value is formed by multiplying that unrounded mean by
        the number of on-hand units in the lot and rounding the product half-up
        to two decimal places; `total_value` is the sum of those per-lot line
        values."

        Design: Difficulty/dual_variant_calc/inventory_valuation_fifo_vs_weighted_average_diverge
        """
        setup_valuation_population()
        wa = validate_success(
            api.get_inventory_valuation("BONE", "WEIGHTED_AVERAGE", ADMIN)
        )
        assert wa["on_hand_count"] == 2
        # mean 30004/3 = 10001.333...; per lot line round_half_up(x*1) = 10001.33
        assert wa["total_value"] == pytest.approx(20002.66, abs=0.005)

    def test_fifo_valuation_diverges_from_weighted_average(self, api):
        """PRD §3.9: "The FIFO method instead assumes the oldest accepted stock
        is consumed first. The consumed count is the population size minus
        `on_hand_count`; the population is ordered by `received_at` ascending
        with ties broken by `created_at` ascending — never by `id` — and the
        first units in that order, up to the consumed count, are deemed
        consumed. `total_value` is then the exact integer-cent sum of the
        `unit_cost_cents` of the units that remain."

        Design: Difficulty/dual_variant_calc/inventory_valuation_fifo_vs_weighted_average_diverge
        """
        setup_valuation_population()
        fifo = validate_success(api.get_inventory_valuation("BONE", "FIFO", ADMIN))
        wa = validate_success(
            api.get_inventory_valuation("BONE", "WEIGHTED_AVERAGE", ADMIN)
        )
        assert fifo["on_hand_count"] == 2
        # Oldest unit U-001 consumed first; remaining = 10001 + 10002.
        assert fifo["total_value"] == pytest.approx(20003.00, abs=0.005)
        assert fifo["total_value"] != wa["total_value"]

    def test_per_lot_line_rounding_order_exact(self, api):
        """PRD §3.9: "The order is pinned — round each lot line first, then sum
        — because rounding a single product of the mean times the on-hand count
        yields a different figure whenever receipt costs differ, and that
        alternate order is forbidden."

        Design: Difficulty/combinatorial_formula/inventory_valuation_per_lot_line_rounding_order
        """
        setup_valuation_population()
        wa = validate_success(
            api.get_inventory_valuation("BONE", "WEIGHTED_AVERAGE", ADMIN)
        )
        # Per-lot-line: round_half_up(10001.333..., 2) = 10001.33 per lot,
        # then sum: 10001.33 + 10001.33 = 20002.66.
        assert wa["total_value"] == pytest.approx(20002.66, abs=0.005)

    def test_sum_then_round_order_is_forbidden(self, api):
        """PRD §3.9: "The order is pinned — round each lot line first, then sum
        — because rounding a single product of the mean times the on-hand count
        yields a different figure whenever receipt costs differ, and that
        alternate order is forbidden."

        Design: Difficulty/combinatorial_formula/inventory_valuation_per_lot_line_rounding_order
        """
        setup_valuation_population()
        wa = validate_success(
            api.get_inventory_valuation("BONE", "WEIGHTED_AVERAGE", ADMIN)
        )
        # The forbidden sum-then-round order would yield
        # round_half_up(10001.333... x 2) = 20002.67.
        assert abs(wa["total_value"] - 20002.67) > 0.005
        assert wa["total_value"] == pytest.approx(20002.66, abs=0.005)
