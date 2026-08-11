"""Junior season leases: age and guardian gates, activation, growth swaps (OCC and
limit), buyout dual valuation, and standing-driven suspension/reinstatement."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    make_customer,
    make_customer_headers,
    make_guardian_customer,
    make_junior_customer,
    make_junior_equipment_item,
    make_equipment_item,
    make_season_lease,
    set_clock,
    setup_active_lease,
    setup_suspended_lease_via_total_loss,
    validate_error,
    validate_success,
)

FD = TEST_USERS["front_desk_headers"]
MGR = TEST_USERS["manager_headers"]


class TestBuyoutDualValuation:
    def _close_lease_after_sixty_days(self, api):
        """Season 2026-11-01..2027-03-31 (150 days), activated 2026-11-01, closed
        2026-12-31 (60 days elapsed)."""
        ctx = setup_active_lease()  # JUNIOR unit priced 30000
        set_clock("2026-12-31T09:00:00Z")
        closed = validate_success(api.close_season_lease(ctx["lease"]["id"], FD))
        return ctx, closed

    def test_straight_line_buyout_uses_season_fraction(self, api):
        """PRD Junior Season Leases: "The straight-line figure,
        `buyout_price_straight_line_cents`, depreciates the unit by half of its value
        spread across the season: the retained-value factor is one minus one-half times
        the fraction of the season elapsed, floored at forty percent, and the price is
        the purchase price times that factor, rounded half-up."

        Design: Difficulty/dual_variant_calc/lease_buyout_straight_line_vs_usage
        """
        _, closed = self._close_lease_after_sixty_days(api)
        # 30000 x max(0.40, 1 - 0.5 x 60/150) = 30000 x 0.8
        assert closed["buyout_price_straight_line_cents"] == 24000
        assert closed["status"] == "SETTLED"

    def test_usage_buyout_diverges_from_straight_line(self, api):
        """PRD Junior Season Leases: "The usage-weighted figure,
        `buyout_price_usage_cents`, ignores season length entirely and depreciates one
        percent of purchase price per day the unit was actually out on the lease, again
        floored at forty percent retained and rounded half-up. The two figures diverge
        on virtually every real lease, and both are stored"

        Design: Difficulty/dual_variant_calc/lease_buyout_straight_line_vs_usage
        """
        ctx, closed = self._close_lease_after_sixty_days(api)
        # 30000 x max(0.40, 1 - 0.01 x 60) = 30000 x 0.4
        assert closed["buyout_price_usage_cents"] == 12000
        assert closed["buyout_price_straight_line_cents"] != closed["buyout_price_usage_cents"]
        unit = validate_success(api.get_equipment_item(ctx["unit"]["id"], FD))
        assert unit["status"] == "AWAITING_INSPECTION"


class TestJuniorAgeBoundary:
    def test_age_twelve_at_season_start_accepted(self, api):
        """PRD Junior Season Leases: "the junior must be at most twelve full years old
        at the season start — a child who turns thirteen on or before
        `season_start_date` is ineligible and rejected with `ERR_JUNIOR_AGE_EXCEEDED`"

        Design: Difficulty/boundary_precision_check/junior_age_boundary_at_season_start
        """
        guardian = make_guardian_customer()
        # Born 2013-11-02: still 12 on 2026-11-01 (turns 13 the day after).
        junior_ok = make_junior_customer(date_of_birth="2013-11-02")
        lease = make_season_lease(junior_ok, guardian)
        assert lease["status"] == "DRAFT"

    def test_age_exactly_thirteen_at_season_start_rejected(self, api):
        """PRD Junior Season Leases: "a child who turns thirteen on or before
        `season_start_date` is ineligible and rejected with `ERR_JUNIOR_AGE_EXCEEDED`"

        Design: Difficulty/boundary_precision_check/junior_age_boundary_at_season_start
        """
        guardian = make_guardian_customer()
        # Born 2013-11-01: turns exactly 13 on 2026-11-01 — one day flips the verdict.
        junior_no = make_junior_customer(date_of_birth="2013-11-01")
        resp = api.create_season_lease(
            {"junior_customer_id": junior_no["id"],
             "guardian_customer_id": guardian["id"],
             "season_start_date": "2026-11-01", "season_end_date": "2027-03-31",
             "package_tier": "JUNIOR_SKI", "deposit_cents": 10000},
            FD,
        )
        validate_error(resp, ApiErrorId.ERR_JUNIOR_AGE_EXCEEDED)


class TestGuardianRules:
    def test_guardian_same_as_junior_or_underage_rejected(self, api):
        """PRD Junior Season Leases: "the guardian must be a different person from the
        junior and at least eighteen at the season start, or creation fails with
        `ERR_GUARDIAN_INVALID`."

        Design: Corner/validations/lease_guardian_invalid_rejected
        """
        junior = make_junior_customer()
        minor = make_customer(date_of_birth="2010-06-01", height_cm=155, weight_kg=50,
                              boot_sole_mm=270, skier_type="TYPE_1")

        def create(guardian_id):
            return api.create_season_lease(
                {"junior_customer_id": junior["id"], "guardian_customer_id": guardian_id,
                 "season_start_date": "2026-11-01", "season_end_date": "2027-03-31",
                 "package_tier": "JUNIOR_SKI", "deposit_cents": 10000},
                FD,
            )

        validate_error(create(junior["id"]), ApiErrorId.ERR_GUARDIAN_INVALID)
        # The second minor is 16 at the 2026-11-01 season start — under 18.
        validate_error(create(minor["id"]), ApiErrorId.ERR_GUARDIAN_INVALID)


class TestActivationRules:
    def test_activate_with_non_junior_tier_rejected(self, api):
        """PRD Junior Season Leases: "A unit failing the tier-or-gear match is rejected
        with `ERR_NOT_JUNIOR_TIER`"

        Design: Corner/validations/lease_activate_non_junior_tier_rejected
        """
        junior = make_junior_customer()
        guardian = make_guardian_customer()
        unit = make_equipment_item(gear_type="SKI", tier="STANDARD", size_label="150cm")
        lease = make_season_lease(junior, guardian)
        resp = api.activate_season_lease(lease["id"], {"equipment_item_id": unit["id"]}, FD)
        validate_error(resp, ApiErrorId.ERR_NOT_JUNIOR_TIER)
        after = validate_success(api.get_season_lease(lease["id"], FD))
        assert after["status"] == "DRAFT"


class TestSwapRules:
    def test_third_swap_rejected_at_limit(self, api):
        """PRD Junior Season Leases: "Kids grow, so the program allows mid-season
        growth swaps — at most two per lease." and "a lease whose `swap_count` has
        reached two rejects further swaps with `ERR_SWAP_LIMIT_EXCEEDED`."

        Design: Corner/validations/third_swap_rejected_swap_limit
        """
        ctx = setup_active_lease()
        lease = ctx["lease"]
        j2 = make_junior_equipment_item(size_label="135cm")
        j3 = make_junior_equipment_item(size_label="140cm")
        j4 = make_junior_equipment_item(size_label="145cm")

        first = validate_success(api.swap_season_lease(
            lease["id"], {"new_equipment_item_id": j2["id"],
                          "expected_season_lease_version": lease["version"]}, FD))
        second = validate_success(api.swap_season_lease(
            lease["id"], {"new_equipment_item_id": j3["id"],
                          "expected_season_lease_version": first["version"]}, FD))
        assert second["swap_count"] == 2

        resp = api.swap_season_lease(
            lease["id"], {"new_equipment_item_id": j4["id"],
                          "expected_season_lease_version": second["version"]}, FD)
        validate_error(resp, ApiErrorId.ERR_SWAP_LIMIT_EXCEEDED)
        after = validate_success(api.get_season_lease(lease["id"], FD))
        assert after["status"] == "ACTIVE"
        assert after["equipment_item_id"] == j3["id"]

    def test_stale_version_swap_rejected(self, api):
        """PRD Optimistic Concurrency Control: "Swapping the leased unit on a junior
        season lease requires the request to carry `expected_season_lease_version`,
        holding the lease `version` the client last observed. A mismatch with the
        lease's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412),
        preventing a swap from binding to a superseded lease state."

        Design: Corner/cross_cutting_layers/occ_lease_swap_stale_version
        """
        ctx = setup_active_lease()
        lease = ctx["lease"]
        j2 = make_junior_equipment_item(size_label="135cm")
        j3 = make_junior_equipment_item(size_label="140cm")

        first = validate_success(api.swap_season_lease(
            lease["id"], {"new_equipment_item_id": j2["id"],
                          "expected_season_lease_version": lease["version"]}, FD))
        assert first["version"] > lease["version"]

        # All business preconditions hold (eligible unit, swap_count 1 < 2), but the
        # version observed before the first swap is stale.
        resp = api.swap_season_lease(
            lease["id"], {"new_equipment_item_id": j3["id"],
                          "expected_season_lease_version": lease["version"]}, FD)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = validate_success(api.get_season_lease(lease["id"], FD))
        assert after["equipment_item_id"] == j2["id"]
        assert after["swap_count"] == 1


class TestStandingDrivenSuspension:
    def test_reinstate_after_standing_recovers(self, api):
        """PRD Damage Assessments: "The customer pays the remainder, moving the
        assessment from `INVOICED` to `PAID` and triggering a standing recompute —
        clearing the last unpaid invoice can lift a customer back out of `BARRED`."
        PRD Junior Season Leases: "Once the customer's standing recovers above
        `BARRED`, a `Manager` may reinstate the lease, moving it from `SUSPENDED` back
        to `ACTIVE`"

        Design: Corner/state_machines/lease_reinstate_after_standing_recovery
        """
        ctx = setup_suspended_lease_via_total_loss()
        junior = ctx["junior"]
        assessment = ctx["assessment"]
        lease = ctx["lease"]

        paid = validate_success(api.pay_damage_assessment(
            assessment["id"], make_customer_headers(junior["id"])))
        assert paid["status"] == "PAID"

        customer = validate_success(api.get_customer(junior["id"], FD))
        # No unpaid invoiced assessment remains and late_return_count is 0.
        assert customer["standing"] == "GOOD_STANDING"
        assert customer["late_return_count"] == 0

        reinstated = validate_success(api.reinstate_season_lease(lease["id"], MGR))
        assert reinstated["status"] == "ACTIVE"
