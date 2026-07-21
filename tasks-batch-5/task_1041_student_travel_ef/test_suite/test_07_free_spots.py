"""Free-spot credit: provisional vs final variants, count boundary, and the paid-in-full
cascade to departure counters and leader credit (queue-A rules 1/4/6)."""
from test_helpers import (
    validate_success, OPERATOR,
    setup_open_departure, setup_enrollment_with_deposit,
    enroll, make_plan, pay,
)


def _enroll_paid_in_full(api, departure_id, name, dob, gender="MALE", price=250000):
    enr = enroll(api, departure_id, traveler_name=name, traveler_dob=dob, traveler_gender=gender)
    plan = make_plan(api, enr["id"], enr["version"], installment_count=1)
    pay(api, plan["id"], price, kind="DEPOSIT")
    return enr


def _enroll_deposit_only(api, departure_id, name, dob, gender="MALE", deposit=30000):
    enr = enroll(api, departure_id, traveler_name=name, traveler_dob=dob, traveler_gender=gender)
    plan = make_plan(api, enr["id"], enr["version"], installment_count=1)
    pay(api, plan["id"], deposit, kind="DEPOSIT")
    return enr


class TestFreeSpotDualVariant:
    """Design: Difficulty/dual_variant_calc/free_spot_provisional_counts_enrolled_vs_final_counts_paid_in_full"""

    def _mixed_departure(self, api):
        ctx = setup_open_departure(api, clock="2026-08-18T00:00:00Z", chaperone_ratio=2,
                                   price_per_traveler_cents=250000)
        _enroll_paid_in_full(api, ctx["departure"]["id"], "A One", "2010-05-01T00:00:00Z")
        _enroll_deposit_only(api, ctx["departure"]["id"], "B Two", "2010-06-01T00:00:00Z", gender="FEMALE")
        return ctx

    def test_provisional_counts_all_non_cancelled_enrollees(self, api):
        """PRD §3.8: "The forward-looking provisional variant, shown while a departure is
        still OPEN, counts every non-cancelled enrollee — those with lifecycle_status of
        PENDING or CONFIRMED — on the assumption that all will pay."
        PRD §3.8: "The credit value of those free spots is the free-spot count multiplied by
        the departure's price_per_traveler_cents."

        Design: Difficulty/dual_variant_calc/free_spot_provisional_counts_enrolled_vs_final_counts_paid_in_full
        """
        ctx = self._mixed_departure(api)
        s = validate_success(api.get_departure_summary(ctx["departure"]["id"], OPERATOR))
        assert s["active_enrollment_count"] == 2
        assert s["provisional_free_spots"] == 1  # 2 // 2
        assert s["provisional_credit_cents"] == 250000

    def test_final_counts_only_paid_in_full(self, api):
        """PRD §3.8: "The final variant, persisted into the departure's free_spots_earned at
        guarantee and recomputed on every payment-in-full flip and every cancellation,
        counts only the paid_in_full_count (enrollments whose payment_status is
        PAID_IN_FULL); it diverges from the provisional figure whenever some enrollees have
        not fully paid."

        Design: Difficulty/dual_variant_calc/free_spot_provisional_counts_enrolled_vs_final_counts_paid_in_full
        """
        ctx = self._mixed_departure(api)
        s = validate_success(api.get_departure_summary(ctx["departure"]["id"], OPERATOR))
        assert s["paid_in_full_count"] == 1
        assert s["final_free_spots"] == 0  # 1 // 2
        assert s["final_credit_cents"] == 0


class TestFreeSpotCountBoundary:
    """Design: Difficulty/boundary_precision_check/free_spot_count_boundary_at_exactly_ratio"""

    def test_paid_count_exactly_at_ratio_yields_one_free_spot(self, api):
        """PRD §3.8: "The number of free spots a departure has earned is the paying count
        divided by the chaperone_ratio, taken as the integer floor, so a full free spot
        appears exactly when the paying count reaches a whole multiple of the ratio."
        PRD §3.8: "The credit value of those free spots is the free-spot count multiplied by
        the departure's price_per_traveler_cents."

        Design: Difficulty/boundary_precision_check/free_spot_count_boundary_at_exactly_ratio
        """
        ctx = setup_open_departure(api, clock="2026-08-18T00:00:00Z", chaperone_ratio=2,
                                   price_per_traveler_cents=250000)
        _enroll_paid_in_full(api, ctx["departure"]["id"], "P1", "2010-05-01T00:00:00Z")
        _enroll_paid_in_full(api, ctx["departure"]["id"], "P2", "2010-05-02T00:00:00Z")
        s = validate_success(api.get_departure_summary(ctx["departure"]["id"], OPERATOR))
        assert s["paid_in_full_count"] == 2
        assert s["final_free_spots"] == 1  # 2 // 2
        assert s["final_credit_cents"] == 250000

    def test_paid_count_one_below_ratio_yields_zero_free_spots(self, api):
        """PRD §3.8: "The number of free spots a departure has earned is the paying count
        divided by the chaperone_ratio, taken as the integer floor, so a full free spot
        appears exactly when the paying count reaches a whole multiple of the ratio."

        Design: Difficulty/boundary_precision_check/free_spot_count_boundary_at_exactly_ratio
        """
        ctx = setup_open_departure(api, clock="2026-08-18T00:00:00Z", chaperone_ratio=2,
                                   price_per_traveler_cents=250000)
        _enroll_paid_in_full(api, ctx["departure"]["id"], "P1", "2010-05-01T00:00:00Z")
        s = validate_success(api.get_departure_summary(ctx["departure"]["id"], OPERATOR))
        assert s["paid_in_full_count"] == 1
        assert s["final_free_spots"] == 0  # 1 // 2


class TestFullPaymentCascade:
    """Design: Difficulty/transitive_cascade/full_payment_cascades_paid_count_free_spots_and_leader_credit_depth3"""

    def _pay_to_full(self, api):
        ctx = setup_enrollment_with_deposit(
            api, clock="2026-08-18T00:00:00Z", deposit_cents=30000,
            dep_overrides={"chaperone_ratio": 1, "price_per_traveler_cents": 250000},
        )
        validate_success(
            api.create_payment({"payment_plan_id": ctx["plan"]["id"], "amount_cents": 220000, "kind": "INSTALLMENT"}, OPERATOR),
            expected_status=201,
        )
        return ctx

    def test_full_payment_flips_status_and_bumps_paid_count(self, api):
        """PRD §3.5: "Reaching full payment also drives the plan ACTIVE → PAID, and that
        flip cascades: it bumps the departure's paid_in_full_count, which in turn recomputes
        the departure's free_spots_earned under the final free-spot rule and the owning
        group leader's free_spot_credit_cents."

        Design: Difficulty/transitive_cascade/full_payment_cascades_paid_count_free_spots_and_leader_credit_depth3
        """
        ctx = self._pay_to_full(api)
        enr = validate_success(api.get_enrollment(ctx["enrollment"]["id"], OPERATOR))
        dep = validate_success(api.get_departure(ctx["departure"]["id"], OPERATOR))
        assert enr["payment_status"] == "PAID_IN_FULL"
        assert dep["paid_in_full_count"] == 1

    def test_cascade_recomputes_free_spots_and_leader_credit(self, api):
        """PRD §3.8: "Whenever a departure's earned free spots change, the owning leader's
        free_spot_credit_cents is recomputed as the sum of the final credit across all of
        that leader's departures."
        PRD §3.8: "The credit value of those free spots is the free-spot count multiplied by
        the departure's price_per_traveler_cents."

        Design: Difficulty/transitive_cascade/full_payment_cascades_paid_count_free_spots_and_leader_credit_depth3
        """
        ctx = self._pay_to_full(api)
        dep = validate_success(api.get_departure(ctx["departure"]["id"], OPERATOR))
        gl = validate_success(api.get_group_leader(ctx["group_leader"]["id"], OPERATOR))
        assert dep["free_spots_earned"] == 1  # 1 // 1 (chaperone_ratio 1)
        assert gl["free_spot_credit_cents"] == 250000
