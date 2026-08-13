"""Permit fee proration variants and rounding order (PRD §3.3)."""
from test_helpers import (
    assert_permit,
    assert_permit_fee_consistency,
    create_allocation,
    create_lot,
    create_patron,
    get_allocation_version,
    make_commuter_headers,
    purchase_permit,
    set_clock,
    validate_success,
)

# Shared term: 2026-08-03 .. 2026-11-22 inclusive = 112 days = exactly 16
# weeks; midterm date 2026-09-28. With the logical clock at 2026-10-05,
# exactly 49 days (7 whole weeks) remain.


class TestProrationPolicyDivergence:
    """Same patron, same base fee (100010), same valid_from (2026-10-05):
    the proration policy alone selects a different fee."""

    def _setup(self):
        patron = create_patron(full_name="Pat A", campus_role="STUDENT",
                               residency="OFF_CAMPUS", primary_commute_mode="DRIVE_ALONE")
        lot = create_lot(lot_code="L1", name="Lot 1")
        alloc_pw = create_allocation(lot["id"], permit_code="PW",
                                     eligible_roles=["STUDENT"], base_fee_cents=100010,
                                     proration_policy="PRORATED_WEEKLY", quota=10)
        alloc_fh = create_allocation(lot["id"], permit_code="FH",
                                     eligible_roles=["STUDENT"], base_fee_cents=100010,
                                     proration_policy="FLAT_HALF_TERM", quota=10)
        set_clock("2026-10-05T00:00:00Z")
        return patron, alloc_pw, alloc_fh

    def test_prorated_weekly_fee_after_midterm(self, api):
        """PRD §3.3.1: "Compute `weekly_rate` as `base_fee_cents` divided by
        `term_weeks`, rounded half-up to the nearest integer cent. **This
        rounding happens before multiplication.**" and "`fee_base_cents` is
        `weekly_rate` multiplied by `weeks_remaining` — an exact integer
        multiply."
        PRD §3.3.3: "`surcharge_cents` is `fee_base_cents` multiplied by
        `0.05`, rounded half-up to the nearest integer cent. The surcharge is
        computed from the already-rounded `fee_base_cents`."

        Design: Difficulty/dual_variant_calc/permit_fee_proration_policy_divergence
        """
        patron, alloc_pw, _ = self._setup()
        resp = api.create_permit(
            {
                "patron_id": patron["id"],
                "allocation_id": alloc_pw["id"],
                "plate_number": "AAA111",
                "valid_from": "2026-10-05",
                "expected_allocation_version": get_allocation_version(alloc_pw["id"]),
            },
            make_commuter_headers(patron["id"]),
        )
        permit = validate_success(resp, 201)
        assert_permit(permit)
        # weekly_rate = round_half_up(100010 / 16) = 6251; 7 weeks remain.
        assert permit["fee_base_cents"] == 43757, (
            f"fee_base must be 6251 * 7 = 43757, got {permit['fee_base_cents']}"
        )
        assert permit["surcharge_cents"] == 2188, (
            f"surcharge must be round_half_up(43757 * 0.05) = 2188, got {permit['surcharge_cents']}"
        )
        assert permit["fee_total_cents"] == 45945, (
            f"fee_total must be 45945, got {permit['fee_total_cents']}"
        )
        assert_permit_fee_consistency(permit)

    def test_flat_half_term_fee_after_midterm_diverges(self, api):
        """PRD §3.3.2: "If `valid_from` is on or before `midterm_date`,
        `fee_base_cents` is `base_fee_cents` in full. Otherwise
        `fee_base_cents` is `base_fee_cents` multiplied by `0.5`, rounded
        half-up to the nearest integer cent." and "Identical inputs under the
        two policies yield different fees — the variants are not
        interchangeable."

        Design: Difficulty/dual_variant_calc/permit_fee_proration_policy_divergence
        """
        patron, alloc_pw, alloc_fh = self._setup()
        pw = purchase_permit(patron["id"], alloc_pw["id"], "AAA111",
                             valid_from="2026-10-05", as_commuter=True)
        fh_resp = api.create_permit(
            {
                "patron_id": patron["id"],
                "allocation_id": alloc_fh["id"],
                "plate_number": "BBB222",
                "valid_from": "2026-10-05",
                "expected_allocation_version": get_allocation_version(alloc_fh["id"]),
            },
            make_commuter_headers(patron["id"]),
        )
        fh = validate_success(fh_resp, 201)
        assert_permit(fh)
        # 2026-10-05 is after the midterm date 2026-09-28 -> half fee.
        assert fh["fee_base_cents"] == 50005, (
            f"fee_base must be round_half_up(100010 * 0.5) = 50005, got {fh['fee_base_cents']}"
        )
        assert fh["surcharge_cents"] == 2500, (
            f"surcharge must be 2500, got {fh['surcharge_cents']}"
        )
        assert fh["fee_total_cents"] == 52505, (
            f"fee_total must be 52505, got {fh['fee_total_cents']}"
        )
        assert pw["fee_total_cents"] != fh["fee_total_cents"], (
            "identical inputs under the two policies must yield different fees"
        )


class TestWeeklyRateRoundingOrder:
    """PRORATED_WEEKLY rounds the weekly rate before multiplying; an exactly
    divisible base is insensitive to the order, a non-divisible base is not."""

    def _setup(self):
        patron = create_patron(full_name="R", campus_role="STUDENT",
                               residency="ON_CAMPUS", primary_commute_mode="CARPOOL")
        lot = create_lot(lot_code="LR", name="Lot R")
        alloc_odd = create_allocation(lot["id"], permit_code="ODD",
                                      eligible_roles=["STUDENT"], base_fee_cents=100010,
                                      proration_policy="PRORATED_WEEKLY", quota=10)
        alloc_even = create_allocation(lot["id"], permit_code="EVEN",
                                       eligible_roles=["STUDENT"], base_fee_cents=100000,
                                       proration_policy="PRORATED_WEEKLY", quota=10)
        set_clock("2026-10-05T00:00:00Z")
        return patron, alloc_odd, alloc_even

    def test_weekly_rate_rounded_before_multiply(self, api):
        """PRD §3.3.1: "Compute `weekly_rate` as `base_fee_cents` divided by
        `term_weeks`, rounded half-up to the nearest integer cent. **This
        rounding happens before multiplication.**" and "`fee_base_cents` is
        `weekly_rate` multiplied by `weeks_remaining` — an exact integer
        multiply."
        PRD §3.3.3: "`surcharge_cents` is `fee_base_cents` multiplied by
        `0.05`, rounded half-up to the nearest integer cent. The surcharge is
        computed from the already-rounded `fee_base_cents`."

        Design: Difficulty/combinatorial_formula/permit_fee_weekly_rate_rounding_order
        """
        patron, alloc_odd, _ = self._setup()
        resp = api.create_permit(
            {
                "patron_id": patron["id"],
                "allocation_id": alloc_odd["id"],
                "plate_number": "R111",
                "valid_from": "2026-10-05",
                "expected_allocation_version": get_allocation_version(alloc_odd["id"]),
            },
            make_commuter_headers(patron["id"]),
        )
        permit = validate_success(resp, 201)
        # round_half_up(100010 / 16) = 6251 FIRST, then 6251 * 7 = 43757
        # (multiply-then-round would give round_half_up(100010*7/16) = 43754).
        assert permit["fee_base_cents"] == 43757, (
            f"round-first order yields 43757, got {permit['fee_base_cents']}"
        )
        assert permit["fee_total_cents"] == 45945, (
            f"surcharge on the rounded base yields total 45945, got {permit['fee_total_cents']}"
        )

    def test_weekly_rate_exact_division_order_insensitive(self, api):
        """PRD §3.3.1: "Compute `weekly_rate` as `base_fee_cents` divided by
        `term_weeks`, rounded half-up to the nearest integer cent. **This
        rounding happens before multiplication.**"
        PRD §2.7: "Every division or percentage evaluation rounds half-up to
        the nearest integer cent — never banker's rounding, never truncation."

        Design: Difficulty/combinatorial_formula/permit_fee_weekly_rate_rounding_order
        """
        patron, _, alloc_even = self._setup()
        resp = api.create_permit(
            {
                "patron_id": patron["id"],
                "allocation_id": alloc_even["id"],
                "plate_number": "R222",
                "valid_from": "2026-10-05",
                "expected_allocation_version": get_allocation_version(alloc_even["id"]),
            },
            make_commuter_headers(patron["id"]),
        )
        permit = validate_success(resp, 201)
        # 100000 / 16 = 6250 exactly; 6250 * 7 = 43750 under either order.
        assert permit["fee_base_cents"] == 43750, (
            f"exact division yields fee_base 43750, got {permit['fee_base_cents']}"
        )
        # round_half_up(43750 * 0.05) = round_half_up(2187.5) = 2188 (half-up).
        assert permit["surcharge_cents"] == 2188, (
            f"half-up surcharge must be 2188, got {permit['surcharge_cents']}"
        )
        assert permit["fee_total_cents"] == 45938, (
            f"fee_total must be 45938, got {permit['fee_total_cents']}"
        )


class TestPermitInitialState:
    def test_permit_purchase_initial_state_and_fee_fields(self, api, admin_headers):
        """PRD §3.3: "When `valid_from` is omitted it defaults to the later of
        the current logical date and the allocation's `term_start`. `valid_to`
        is always the allocation's `term_end` (inclusive) and is set by the
        system." and "On successful purchase the permit is created `ACTIVE`,
        the allocation's `allocated_count` increments by `1`, the allocation's
        `status` is re-evaluated, the allocation's `version` increments, the
        transportation fund's `permit_revenue_cents` increases by
        `fee_paid_cents`, and any applied incentive credit is debited from the
        patron's incentive account."
        PRD §3.5.2: "`refund_cents` is recorded on the permit; before
        cancellation it is null."

        Design: Corner/state_machines/permit_purchase_initial_state_and_fee_fields
        """
        patron = create_patron(full_name="F", campus_role="STUDENT",
                               residency="OFF_CAMPUS", primary_commute_mode="DRIVE_ALONE")
        lot = create_lot(lot_code="LF", name="Lot F")
        allocation = create_allocation(lot["id"], permit_code="GEN",
                                       eligible_roles=["STUDENT"], base_fee_cents=80000,
                                       proration_policy="PRORATED_WEEKLY", quota=5)
        # Clock untouched (2026-08-01, before term start 2026-08-03).
        resp = api.create_permit(
            {
                "patron_id": patron["id"],
                "allocation_id": allocation["id"],
                "plate_number": "F111",
                "expected_allocation_version": allocation["version"],
            },
            admin_headers,
        )
        permit = validate_success(resp, 201)
        assert_permit(permit)
        assert permit["status"] == "ACTIVE", (
            f"a purchased permit starts ACTIVE, got {permit['status']}"
        )
        assert permit["valid_from"] == "2026-08-03", (
            f"valid_from defaults to term_start when it is later than the clock, "
            f"got {permit['valid_from']}"
        )
        assert permit["valid_to"] == "2026-11-22", (
            f"valid_to must be the term_end 2026-11-22, got {permit['valid_to']}"
        )
        # Full 16-week term: weekly 5000 -> base 80000, surcharge 4000.
        assert permit["fee_base_cents"] == 80000
        assert permit["surcharge_cents"] == 4000
        assert permit["fee_total_cents"] == 84000
        assert permit["fee_paid_cents"] == 84000
        assert permit["credit_applied_cents"] == 0
        assert permit["refund_cents"] is None, "refund_cents must be null before cancellation"
