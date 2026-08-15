"""Salon standing (suspend / reinstate) and tier management (evaluation,
override, OCC guard)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_salon,
    create_delivered_order,
    get_salon,
    make_brand,
    make_compliance_officer_headers,
    make_product,
    make_salon,
    override_salon_tier,
    run_sweep,
    set_clock,
    submit_license,
    validate_error,
    validate_success,
    verify_license,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


class TestSuspendReinstateCycle:
    def test_suspend_sets_manual_reason_and_increments_version(self, api):
        """PRD §3.3: "A `ComplianceOfficer` may manually suspend an `ACTIVE`
        salon (reason `MANUAL`, submitted with a free-text `reason` on the
        request)."

        Design: Difficulty/non_linear_state_machine/salon_suspend_reinstate_cycle
        """
        salon, _ = create_active_salon(legal_name="Salon Y")
        before = get_salon(salon["id"])

        resp = api.suspend_salon(salon["id"], {"reason": "manual audit"}, OFFICER)
        suspended = validate_success(resp, 200)
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "MANUAL"
        assert suspended["version"] == before["version"] + 1, (
            "suspend must increment the salon version by exactly 1")

    def test_reinstate_restores_active_and_clears_reason(self, api):
        """PRD §3.3: "Reinstatement moves a `SUSPENDED` salon back to `ACTIVE`
        and clears `suspension_reason` to null, incrementing `version`."

        Design: Difficulty/non_linear_state_machine/salon_suspend_reinstate_cycle
        """
        salon, _ = create_active_salon(legal_name="Salon Y2")
        before = get_salon(salon["id"])
        validate_success(
            api.suspend_salon(salon["id"], {"reason": "manual audit"}, OFFICER), 200)

        reinstated = validate_success(api.reinstate_salon(salon["id"], OFFICER), 200)
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["suspension_reason"] is None
        assert reinstated["version"] == before["version"] + 2, (
            "suspend + reinstate must advance the salon version by exactly 2")


class TestReinstatePreconditions:
    def test_reinstate_active_salon_rejected(self, api):
        """PRD §3.3: "It is legal only from `SUSPENDED`
        (`ERR_INVALID_ACCOUNT_STATE` otherwise) and only while the salon holds
        at least one `VERIFIED` license whose `valid_until` still lies after
        the logical clock — otherwise `ERR_NO_VALID_LICENSE` (HTTP 409)."

        Design: Corner/state_machines/reinstate_active_salon_rejected
        """
        salon, _ = create_active_salon(legal_name="Salon 14")
        resp = api.reinstate_salon(salon["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_ACCOUNT_STATE)

    def test_reinstate_without_valid_license_rejected(self, api):
        """PRD §3.3: "It is legal only from `SUSPENDED`
        (`ERR_INVALID_ACCOUNT_STATE` otherwise) and only while the salon holds
        at least one `VERIFIED` license whose `valid_until` still lies after
        the logical clock — otherwise `ERR_NO_VALID_LICENSE` (HTTP 409)."

        Design: Corner/state_machines/reinstate_without_valid_license_rejected
        """
        salon, _ = create_active_salon(
            legal_name="Salon 15", valid_until="2026-08-10T00:00:00Z")
        validate_success(
            api.suspend_salon(salon["id"], {"reason": "manual"}, OFFICER), 200)
        set_clock("2026-08-15T00:00:00Z")
        run_sweep()  # expires the license; salon already SUSPENDED

        resp = api.reinstate_salon(salon["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_NO_VALID_LICENSE)
        assert get_salon(salon["id"])["status"] == "SUSPENDED"


class TestTierEvaluationBoundaries:
    def test_tier_evaluation_at_exact_gold_floor_yields_gold(self, api):
        """PRD §3.3: "If `tier_override_active` is true, the tier is left
        untouched; otherwise the tier is derived from the volume — `PLATINUM`
        when the volume is at least 5000000 cents, else `GOLD` when it is at
        least 2000000 cents, else `SILVER` — with inclusive boundaries, so a
        volume of exactly 2000000 cents yields `GOLD`."

        Design: Difficulty/boundary_precision_check/tier_evaluation_at_exact_gold_floor
        """
        salon, _ = create_active_salon(legal_name="Salon X")
        brand = make_brand()
        product = make_product(brand["id"], base_price_cents=20000,
                               weight_grams=100)
        create_delivered_order(
            salon["id"], [{"product_id": product["id"], "quantity": 100}])

        result = validate_success(api.evaluate_tier(salon["id"], ADMIN), 200)
        assert result["trailing_12m_delivered_volume_cents"] == 2000000
        assert result["tier"] == "GOLD", (
            "volume exactly at the 2000000-cent floor yields GOLD (inclusive)")

    def test_tier_evaluation_one_cent_below_gold_floor_yields_silver(self, api):
        """PRD §3.3: "If `tier_override_active` is true, the tier is left
        untouched; otherwise the tier is derived from the volume — `PLATINUM`
        when the volume is at least 5000000 cents, else `GOLD` when it is at
        least 2000000 cents, else `SILVER` — with inclusive boundaries, so a
        volume of exactly 2000000 cents yields `GOLD`."

        Design: Difficulty/boundary_precision_check/tier_evaluation_at_exact_gold_floor
        """
        salon, _ = create_active_salon(legal_name="Salon Y")
        brand = make_brand()
        p1 = make_product(brand["id"], base_price_cents=20000, weight_grams=100)
        p2 = make_product(brand["id"], base_price_cents=19999, weight_grams=10)
        create_delivered_order(salon["id"], [
            {"product_id": p1["id"], "quantity": 99},
            {"product_id": p2["id"], "quantity": 1},
        ])

        result = validate_success(api.evaluate_tier(salon["id"], ADMIN), 200)
        assert result["trailing_12m_delivered_volume_cents"] == 1999999
        assert result["tier"] == "SILVER", (
            "volume one cent below the 2000000-cent floor stays SILVER")


class TestTierOverrideAndWindow:
    def test_tier_override_blocks_evaluation(self, api):
        """PRD §3.3: "While `tier_override_active` holds, evaluate-tier must
        not change the tier."
        PRD §3.3: "The result is stored on
        `trailing_12m_delivered_volume_cents`."

        Design: Corner/calculations/tier_override_blocks_evaluation
        """
        salon, _ = create_active_salon(legal_name="Salon 21")
        override_salon_tier(salon["id"], "PLATINUM")

        result = validate_success(api.evaluate_tier(salon["id"], ADMIN), 200)
        assert result["tier"] == "PLATINUM", (
            "evaluate-tier must not change the tier while the override holds")
        assert result["trailing_12m_delivered_volume_cents"] == 0, (
            "the trailing volume is still refreshed even under an override")

    def test_tier_evaluation_demotes_after_window_slides(self, api):
        """PRD §3.3: "An evaluate-tier run by a `DistributionAdmin` recomputes
        the salon's trailing delivered volume: the sum of `net_merch_cents`
        over the salon's `DELIVERED` orders whose `delivered_at` falls inside
        the trailing 365-day window, both endpoints inclusive, measured
        against the logical clock."

        Design: Corner/calculations/tier_evaluation_demotes_after_window_slides
        """
        salon, _ = create_active_salon(
            legal_name="Salon 22", valid_until="2028-06-01T00:00:00Z")
        brand = make_brand()
        product = make_product(brand["id"], base_price_cents=20000,
                               weight_grams=100)
        create_delivered_order(
            salon["id"], [{"product_id": product["id"], "quantity": 100}])

        first = validate_success(api.evaluate_tier(salon["id"], ADMIN), 200)
        assert first["tier"] == "GOLD"

        # One year and one day later the delivery has left the window.
        set_clock("2027-08-02T00:00:00Z")
        second = validate_success(api.evaluate_tier(salon["id"], ADMIN), 200)
        assert second["tier"] == "SILVER"
        assert second["trailing_12m_delivered_volume_cents"] == 0

    def test_tier_override_stale_version_returns_412(self, api):
        """PRD §2.6: "A tier override on a salon must carry
        `expected_salon_account_version` matching the salon's current
        `version`. If the salon's version has advanced since the caller last
        read it — an evaluate-tier run, a suspension, a cascade — the override
        is based on stale state and is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/tier_override_stale_version_returns_412
        """
        salon, _ = create_active_salon(legal_name="Salon 46")
        observed = get_salon(salon["id"])["version"]

        first = validate_success(api.tier_override_salon(
            salon["id"],
            {"tier": "GOLD", "expected_salon_account_version": observed},
            ADMIN), 200)
        assert first["tier"] == "GOLD"
        assert first["version"] == observed + 1

        resp = api.tier_override_salon(
            salon["id"],
            {"tier": "PLATINUM", "expected_salon_account_version": observed},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_salon(salon["id"])["tier"] == "GOLD", (
            "a stale override must not mutate the tier")
