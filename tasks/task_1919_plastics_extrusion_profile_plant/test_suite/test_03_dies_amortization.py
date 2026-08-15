"""Die lifecycle, pinned amortization rates, credits and adjustments (PRD §3.2)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    create_customer, create_profile, create_die, transition_die, qualify_die,
    get_die, plant_base, running_scene, two_mode_dies_scene,
    confirmed_order, activated_assignment, create_line,
    assert_amortization_invariant,
)

PM = TEST_USERS["plant_manager_headers"]
PE = TEST_USERS["process_engineer_headers"]


class TestDieLifecycle:
    def test_retire_from_draft_rejected(self, api):
        """PRD §3.2: "Retirement is reachable from either `IN_SERVICE` or
        `MAINTENANCE`, but only when no assignment referencing the die remains in
        `SCHEDULED` or `ACTIVE` status; `RETIRED` is terminal."
        PRD §3.2: "a request whose target is not a defined transition out of the
        die's current state is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/die_retire_from_draft_rejected
        """
        cust = create_customer()
        prof = create_profile(cust["id"])
        die = create_die(prof["id"])
        resp = api.transition_die(die["id"], {"to": "RETIRED"}, PE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_die(die["id"])["status"] == "DRAFT"

    def test_failed_trial_reverts_to_draft(self, api):
        """PRD §3.2: "From `DRAFT`, a `ProcessEngineer` advances the die to
        `TRIAL`; a failed trial reverts from `TRIAL` back to `DRAFT`, while a
        successful one advances from `TRIAL` to `QUALIFIED`."
        PRD §3.2: "It is the transition into `QUALIFIED` that pins the money: at
        that moment the system fixes `amort_rate_cents_per_m` as
        `tooling_cost_cents` divided by `committed_length_m`, rounded half-up to
        four decimal places, and `amort_rate_cents_per_kg` as
        `tooling_cost_cents` divided by `committed_weight_kg`, rounded half-up to
        four decimal places."

        Design: Corner/state_machines/die_failed_trial_reverts
        """
        cust = create_customer()
        prof = create_profile(cust["id"])
        die = create_die(prof["id"])
        v_before = die["version"]
        transition_die(die["id"], "TRIAL")
        reverted = transition_die(die["id"], "DRAFT")
        assert reverted["status"] == "DRAFT"
        assert reverted["version"] == v_before + 2, (
            "Each die transition increments the version by one")

    def test_failed_trial_loop_then_qualify_pins_rates(self, api):
        """PRD §3.2: "It is the transition into `QUALIFIED` that pins the money:
        at that moment the system fixes `amort_rate_cents_per_m` as
        `tooling_cost_cents` divided by `committed_length_m`, rounded half-up to
        four decimal places, and `amort_rate_cents_per_kg` as
        `tooling_cost_cents` divided by `committed_weight_kg`, rounded half-up to
        four decimal places."

        Design: Difficulty/non_linear_state_machine/die_maintenance_cycle
        """
        cust = create_customer()
        prof = create_profile(cust["id"])
        die = create_die(prof["id"])
        transition_die(die["id"], "TRIAL")
        transition_die(die["id"], "DRAFT")  # failed trial loops back
        transition_die(die["id"], "TRIAL")
        qualified = transition_die(die["id"], "QUALIFIED")
        assert qualified["status"] == "QUALIFIED"
        # 500000 / 10000 m = 50.0000; 500000 / 8000 kg = 62.5000.
        assert qualified["amort_rate_cents_per_m"] == pytest.approx(50.0, abs=1e-6)
        assert qualified["amort_rate_cents_per_kg"] == pytest.approx(62.5, abs=1e-6)

    def test_maintenance_cycle_preserves_pinned_rates(self, api):
        """PRD §3.2: "From then on the `amortization_mode` is locked, and the
        pinned rates survive everything that follows, including the maintenance
        loop."
        PRD §3.2: "A `ProcessEngineer` may move an `IN_SERVICE` die to
        `MAINTENANCE` — only when no assignment referencing it is currently
        `ACTIVE` — and back from `MAINTENANCE` to `IN_SERVICE` when the work is
        done; the two states form a cycle the die may traverse repeatedly."

        Design: Difficulty/non_linear_state_machine/die_maintenance_cycle
        """
        base = plant_base()
        die = qualify_die(create_die(base["prof"]["id"])["id"])
        line = create_line()
        wo = confirmed_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"])
        asg = activated_assignment(wo["id"], die["id"], line["id"])
        die_now = get_die(die["id"])
        assert die_now["status"] == "IN_SERVICE", (
            "First activation of an assignment moves the die QUALIFIED -> IN_SERVICE")
        # Cancel frees the die (no ACTIVE assignment) without reverting IN_SERVICE.
        validate_success(api.cancel_assignment(asg["id"], PE), 200)
        assert get_die(die["id"])["status"] == "IN_SERVICE"

        maintenance = transition_die(die["id"], "MAINTENANCE")
        assert maintenance["status"] == "MAINTENANCE"
        back = transition_die(die["id"], "IN_SERVICE")
        assert back["status"] == "IN_SERVICE"
        assert back["amort_rate_cents_per_m"] == pytest.approx(50.0, abs=1e-6)
        assert back["amort_rate_cents_per_kg"] == pytest.approx(62.5, abs=1e-6)
        assert_amortization_invariant(back)


class TestAmortizationDualMode:
    def test_per_meter_die_credits_by_good_metres(self, api):
        """PRD §3.2: "the raw credit is mode-selected — under `PER_METER`, the
        good length in metres multiplied by `amort_rate_cents_per_m` and rounded
        half-up to whole cents; under `PER_KG`, the good weight `good_weight_kg`
        multiplied by `amort_rate_cents_per_kg` and rounded half-up to whole
        cents, so identical run data can yield a different credit when the actual
        kilograms-per-metre deviate from the committed ratios — and the applied
        credit is the smaller of that raw figure and the die's current
        `remaining_balance_cents`, so a balance is never driven below zero."

        Design: Difficulty/dual_variant_calc/amortization_per_meter_vs_per_kg
        """
        scene = two_mode_dies_scene()
        die_a = get_die(scene["die_a"]["id"])
        # PER_METER: 4000 m x 50.0000 cents/m = 200000.
        assert die_a["amortized_cents"] == 200000
        assert die_a["remaining_balance_cents"] == 300000
        assert_amortization_invariant(die_a)

    def test_per_kg_die_credits_by_good_weight_and_diverges(self, api):
        """PRD §3.2: "the raw credit is mode-selected — under `PER_METER`, the
        good length in metres multiplied by `amort_rate_cents_per_m` and rounded
        half-up to whole cents; under `PER_KG`, the good weight `good_weight_kg`
        multiplied by `amort_rate_cents_per_kg` and rounded half-up to whole
        cents, so identical run data can yield a different credit when the actual
        kilograms-per-metre deviate from the committed ratios — and the applied
        credit is the smaller of that raw figure and the die's current
        `remaining_balance_cents`, so a balance is never driven below zero."

        Design: Difficulty/dual_variant_calc/amortization_per_meter_vs_per_kg
        """
        scene = two_mode_dies_scene()
        die_a = get_die(scene["die_a"]["id"])
        die_b = get_die(scene["die_b"]["id"])
        # PER_KG: 3000 kg x 62.5000 cents/kg = 187500.
        assert die_b["amortized_cents"] == 187500
        assert die_b["remaining_balance_cents"] == 312500
        assert_amortization_invariant(die_b)
        assert die_a["amortized_cents"] != die_b["amortized_cents"], (
            "Identical run data must credit the two modes differently "
            "(actual kg/m 0.75 deviates from committed 0.8)")


class TestAmortizationAdjustments:
    def test_credit_then_compensating_adjustment_preserves_invariant(self, api):
        """PRD §3.2: "The adjustment is added to `amortized_cents` and subtracted
        from `remaining_balance_cents`, and the die's `version` increments by
        one."
        PRD §2.9: "The **amortization invariant** ties a die's two running
        balances to its original tooling cost: after every credit, every manual
        adjustment, and every invoice surcharge, `amortized_cents` plus
        `remaining_balance_cents` equals `tooling_cost_cents` exactly."

        Design: Difficulty/compensating_invariant/amortization_credit_plus_adjustment
        """
        scene = running_scene(samples=2)
        complete = validate_success(api.complete_run(
            scene["run"]["id"],
            {"good_length_mm": 4000000, "good_weight_kg": 3000, "trim_scrap_kg": 50},
            TEST_USERS["line_operator_headers"]), 200)
        die_after_credit = get_die(scene["die"]["id"])
        assert die_after_credit["amortized_cents"] == 200000  # 4000 m x 50.0000
        assert die_after_credit["remaining_balance_cents"] == 300000
        assert_amortization_invariant(die_after_credit)

        resp = api.post_amortization_adjustment(
            scene["die"]["id"],
            {"adjustment_cents": -50000, "reason": "credit memo correction",
             "expected_die_version": die_after_credit["version"]}, PM)
        adjusted = validate_success(resp, 200)
        assert adjusted["amortized_cents"] == 150000
        assert adjusted["remaining_balance_cents"] == 350000
        assert_amortization_invariant(adjusted)

    def test_adjustment_outside_balance_range_rejected(self, api):
        """PRD §3.2: "An adjustment is lawful only while the die is `QUALIFIED`,
        `IN_SERVICE`, or `MAINTENANCE` — against any other status the request is
        rejected with `ERR_INVALID_STATE` — and only while both resulting
        balances stay inside the range from zero to `tooling_cost_cents`,
        inclusive; an adjustment that would push `amortized_cents` or
        `remaining_balance_cents` outside that range is rejected with
        `ERR_BAD_REQUEST`."

        Design: Difficulty/compensating_invariant/amortization_credit_plus_adjustment
        """
        base = plant_base()
        die = qualify_die(create_die(base["prof"]["id"])["id"])
        die = get_die(die["id"])

        negative = api.post_amortization_adjustment(
            die["id"], {"adjustment_cents": -1, "reason": "draw back below zero",
                        "expected_die_version": die["version"]}, PM)
        validate_error(negative, ApiErrorId.ERR_BAD_REQUEST)

        overflow = api.post_amortization_adjustment(
            die["id"], {"adjustment_cents": 500001, "reason": "over-credit",
                        "expected_die_version": die["version"]}, PM)
        validate_error(overflow, ApiErrorId.ERR_BAD_REQUEST)

        die_now = get_die(die["id"])
        assert die_now["amortized_cents"] == 0
        assert die_now["remaining_balance_cents"] == 500000
        ok = api.post_amortization_adjustment(
            die["id"], {"adjustment_cents": 250000, "reason": "partial settlement",
                        "expected_die_version": die_now["version"]}, PM)
        adjusted = validate_success(ok, 200)
        assert adjusted["amortized_cents"] == 250000
        assert adjusted["remaining_balance_cents"] == 250000
        assert_amortization_invariant(adjusted)

    def test_adjustment_with_stale_die_version_rejected(self, api):
        """PRD §2.7: "Posting a manual amortization adjustment against a die
        requires `expected_die_version`, compared against the die's current
        `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_amort_adjust_stale_version
        """
        base = plant_base()
        die = create_die(base["prof"]["id"])
        stale_version = die["version"]
        transition_die(die["id"], "TRIAL")
        transition_die(die["id"], "QUALIFIED")  # version advanced twice

        resp = api.post_amortization_adjustment(
            die["id"], {"adjustment_cents": 1000, "reason": "late tooling supplement",
                        "expected_die_version": stale_version}, PM)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_die(die["id"])["amortized_cents"] == 0, (
            "Rejected adjustment must not change balances")


class TestDieRetrieval:
    def test_get_die_not_found(self, api):
        """PRD §2.8: "Third comes existence: every referenced resource must
        exist, validated left-to-right — path identifiers first, in path order,
        then body-referenced identifiers in the order the request body declares
        them — with the first missing reference surfacing `ERR_NOT_FOUND`."

        Design: Corner/entities/die_get_not_found_returns_404
        """
        resp = api.get_die(NON_EXISTENT_UUID, PM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
