"""Dual-variant calculations: one physical data set, two plan-declared
variants, two observably different outcomes (PRD 3.4, 3.7, 3.9)."""
from test_helpers import (
    add_active_subscription,
    assert_intake,
    assert_invoice,
    complete_stop,
    create_pause,
    create_plan,
    drive_route_to_in_progress,
    find_stop,
    generate_invoice,
    read_pause,
    read_subscription,
    record_intake,
    set_clock,
    setup_active_subscription,
    validate_success,
)
from test_helpers import api_client as _client
from test_helpers.fixtures import ADMIN, create_route


def _setup_dual_basis_pair():
    """Two ACTIVE subscriptions in one zone on identical-money plans that differ
    only in weight_policy; one route driven to IN_PROGRESS with both stops
    COMPLETED at 80 clean items, and one 8800 g intake recorded per stop."""
    ctx = setup_active_subscription(plan_overrides={"tier_code": "STANDARD"})
    plan_w = create_plan(tier_code="STANDARD_W", weight_policy="WEIGHT_BASIS")
    member_b = add_active_subscription(
        ctx, plan=plan_w, customer_overrides={"full_name": "Weight Basis B"}
    )

    route = create_route(ctx["zone"], "2026-08-03")
    stop_a = find_stop(route["id"], ctx["subscription"]["id"])
    stop_b = find_stop(route["id"], member_b["subscription"]["id"])
    route_v = drive_route_to_in_progress(route["id"], "2026-08-03")
    complete_stop(stop_a["id"], route_v, clean_items=80)
    route_v2 = validate_success(_client.get_route(route["id"], ADMIN))["version"]
    complete_stop(stop_b["id"], route_v2, clean_items=80)

    intake_a = record_intake(stop_a["id"], 8800, "NORMAL")
    intake_b = record_intake(stop_b["id"], 8800, "NORMAL")
    return ctx, member_b, intake_a, intake_b


class TestCountVsWeightBasis:
    def test_count_and_weight_basis_verified_counts(self, api):
        """PRD 3.4: "Under `COUNT_BASIS`, `verified_count` simply equals the curbside
        `clean_items_delivered`, and the scale weight only gates `RECONCILED` versus
        `DISPUTED`. Under `WEIGHT_BASIS`, `verified_count` is the `scale_weight_g`
        divided by the per-item expected weight, rounded half-up — so the same intake
        data can yield a different verified count and a different invoice overage
        under the two policies."
        PRD 3.4: "a `MEDIUM` item is expected to come back at 100 grams"

        Design: Difficulty/dual_variant_calc/intake_verified_count_count_vs_weight_basis
        """
        _, _, intake_a, intake_b = _setup_dual_basis_pair()
        assert_intake(intake_a)
        assert_intake(intake_b)
        # 8800 g against an expected 80 x 100 g = 8000 g is variance 10.00: both
        # intakes land RECONCILED; only the verified counts diverge.
        assert intake_a["status"] == "RECONCILED"
        assert intake_b["status"] == "RECONCILED"
        assert intake_a["verified_count"] == 80, (
            f"COUNT_BASIS pins the curbside 80, got {intake_a['verified_count']}"
        )
        assert intake_b["verified_count"] == 88, (
            f"WEIGHT_BASIS derives round_half_up(8800 / 100) = 88, got "
            f"{intake_b['verified_count']}"
        )

    def test_weight_policy_diverges_invoice_overage(self, api):
        """PRD 3.9: "`overage_cents` draws on the subscription's intakes in
        `RECONCILED` or `RESOLVED` whose stop's route date falls inside the half-open
        period: each qualifying intake contributes its `verified_count` minus the
        `weekly_quota`, floored at zero and capped at `overage_cap_items`, and the
        summed items multiply by `overage_rate_cents`."

        Design: Difficulty/dual_variant_calc/intake_verified_count_count_vs_weight_basis
        """
        ctx, member_b, intake_a, intake_b = _setup_dual_basis_pair()
        assert intake_a["verified_count"] == 80
        assert intake_b["verified_count"] == 88

        invoice_a = generate_invoice(ctx["subscription"]["id"])
        invoice_b = generate_invoice(member_b["subscription"]["id"])
        assert_invoice(invoice_a)
        assert_invoice(invoice_b)
        assert invoice_a["overage_cents"] == 0, (
            f"verified 80 == quota 80 bills no overage, got {invoice_a['overage_cents']}"
        )
        assert invoice_a["total_cents"] == 3900
        assert invoice_b["overage_cents"] == 80, (
            f"verified 88 - quota 80 = 8 items x 10 cents = 80, got "
            f"{invoice_b['overage_cents']}"
        )
        assert invoice_b["total_cents"] == 3980, (
            "identical physical data diverges by exactly 80 cents under the two policies"
        )


class TestPauseProrationVariants:
    def _setup_travel_pause(self):
        """ACTIVE ESSENTIAL (3200 cents/week) subscription in a MON/WED/FRI zone,
        then a pause over [2026-08-05, 2026-08-10)."""
        ctx = setup_active_subscription(
            plan_overrides={"tier_code": "ESSENTIAL", "weekly_fee_cents": 3200},
            zone_overrides={
                "zone_code": "Z-TRI",
                "service_weekdays": ["MON", "WED", "FRI"],
            },
        )
        pause = create_pause(
            ctx["subscription"]["id"], "2026-08-05", "2026-08-10",
            ctx["subscription_version"], ctx["customer_headers"],
        )
        ctx["pause"] = pause
        return ctx

    def test_provisional_estimate_charges_whole_week(self, api):
        """PRD 3.7: "`estimated_credit_cents` is the number of distinct
        Monday-to-Sunday billing weeks that the half-open window touches, multiplied
        by the plan's `weekly_fee_cents`. It is deliberately forward-looking — a
        two-service-day pause in a three-day zone on a 3200-cent plan estimates a
        full 3200 because the pause touches one billing week."

        Design: Difficulty/dual_variant_calc/pause_proration_provisional_vs_final
        """
        ctx = self._setup_travel_pause()
        pause = ctx["pause"]
        assert pause["status"] == "SCHEDULED"
        assert pause["estimated_credit_cents"] == 3200, (
            f"PROVISIONAL estimate: one billing week touched x 3200, got "
            f"{pause['estimated_credit_cents']}"
        )

    def test_final_credit_uses_per_day_rounded_lines(self, api):
        """PRD 3.7: "Each paused service day — a date inside the half-open window
        that is one of the zone's `service_weekdays` — contributes one line: the
        plan's `weekly_fee_cents` divided by the zone's `service_days_per_week`,
        rounded half-up to a whole cent. `final_credit_cents` is the sum of those
        already-rounded lines."
        PRD 3.7: "The two-service-day pause above finalizes at 1067 + 1067 = 2134
        cents — never the provisional 3200, and never the sum-then-round 2133, per the
        pinned rounding order of §2.6."

        Design: Difficulty/dual_variant_calc/pause_proration_provisional_vs_final
        """
        ctx = self._setup_travel_pause()
        # Walk the clock through the PRD-pinned transitions: a mid-window set
        # activates the pause (PRD 3.7: the clock's date enters the window),
        # then reaching the end_date completes the now-ACTIVE pause (PRD 3.7).
        set_clock("2026-08-06T00:00:00Z")  # inside [2026-08-05, 2026-08-10)
        assert read_pause(ctx["pause"]["id"])["status"] == "ACTIVE"
        set_clock("2026-08-10T00:00:00Z")  # reach the pause's end_date

        pause = read_pause(ctx["pause"]["id"])
        assert pause["status"] == "COMPLETED"
        assert pause["final_credit_cents"] == 2134, (
            f"FINAL: round_half_up(3200/3) = 1067 per paused service day, twice "
            f"(Wed 08-05, Fri 08-07) = 2134, got {pause['final_credit_cents']}"
        )
        subscription = read_subscription(ctx["subscription"]["id"])
        assert subscription["service_status"] == "ACTIVE", (
            "the subscription resumes when the clock reaches the pause's end_date"
        )
