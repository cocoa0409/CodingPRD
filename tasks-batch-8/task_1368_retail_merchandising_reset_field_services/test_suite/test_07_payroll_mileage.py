"""Mileage and travel-time pay: dual mileage variants, tiered travel pay with
pinned per-tier rounding, worker-classification carve-out, and approve-time
recompute-and-freeze."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_store_visit,
    make_scenario,
    setup_submitted_assignment_for_rep,
    submit_mileage_log,
    validate_success,
    visit_store,
)

PA = TEST_USERS["payroll_admin_headers"]


class TestMileagePayVariants:
    def test_mileage_pay_home_based_vs_first_stop_same_inputs(self, api):
        """PRD 3.8: "Under `HOME_BASED` — the standard W-2 commute-offset
        policy — the payable miles are the log's `round_trip_miles` minus twice
        the rep's `home_base_commute_miles` (the ordinary round-trip commute is
        never billable), floored at 0. Under `FIRST_STOP` — the common 1099
        first-stop policy — the payable miles are the `round_trip_miles` minus
        only the `home_to_first_stop_miles` leg, floored at 0; all subsequent
        inter-store and return miles are payable. In either variant,
        `mileage_pay_cents` is the payable miles multiplied by the rep's
        `mileage_rate_cents`, an exact integer-cent figure requiring no
        rounding."

        Design: Difficulty/dual_variant_calc/mileage_pay_home_based_vs_first_stop
        """
        scn = make_scenario(
            num_stores=2, num_reps=2,
            rep_overrides_list=[
                {"full_name": "Home Based Rep", "employment_type": "W2",
                 "home_base_commute_miles": 15, "mileage_rate_cents": 67,
                 "travel_minute_rate_cents": 40, "mileage_policy": "HOME_BASED"},
                {"full_name": "First Stop Rep", "employment_type": "W2",
                 "home_base_commute_miles": 15, "mileage_rate_cents": 67,
                 "travel_minute_rate_cents": 40, "mileage_policy": "FIRST_STOP"},
            ],
        )
        asg_home, _ = visit_store(
            scn, store_idx=0, rep_idx=0,
            on_site=("2026-08-05T09:30:00Z", "2026-08-05T10:15:00Z"),
        )
        asg_first, _ = visit_store(
            scn, store_idx=1, rep_idx=1,
            on_site=("2026-08-05T10:45:00Z", "2026-08-05T11:30:00Z"),
        )
        rep_home, rep_first = scn["reps"]
        log_home = submit_mileage_log(
            rep_home["id"], asg_home["id"],
            round_trip_miles=120, home_to_first_stop_miles=10, drive_minutes=60,
        )
        log_first = submit_mileage_log(
            rep_first["id"], asg_first["id"],
            round_trip_miles=120, home_to_first_stop_miles=10, drive_minutes=60,
        )
        assert log_home["mileage_pay_cents"] == 6030, (
            f"HOME_BASED: max(0, 120 - 2*15) * 67 = 6030, "
            f"got {log_home['mileage_pay_cents']}"
        )
        assert log_first["mileage_pay_cents"] == 7370, (
            f"FIRST_STOP: max(0, 120 - 10) * 67 = 7370, "
            f"got {log_first['mileage_pay_cents']}"
        )
        assert log_home["mileage_pay_cents"] != log_first["mileage_pay_cents"]

    def test_mileage_pay_floored_at_zero_when_commute_exceeds_trip(self, api):
        """PRD 3.8: "Under `HOME_BASED` — the standard W-2 commute-offset
        policy — the payable miles are the log's `round_trip_miles` minus twice
        the rep's `home_base_commute_miles` (the ordinary round-trip commute is
        never billable), floored at 0."

        Design: Difficulty/dual_variant_calc/mileage_pay_home_based_vs_first_stop
        """
        scn, asg, visit = setup_submitted_assignment_for_rep(
            rep_overrides={"home_base_commute_miles": 15, "mileage_rate_cents": 67},
        )
        rep = scn["reps"][0]
        log = submit_mileage_log(
            rep["id"], asg["id"],
            round_trip_miles=20, home_to_first_stop_miles=5, drive_minutes=30,
        )
        assert log["mileage_pay_cents"] == 0, (
            f"payable miles floor at 0: max(0, 20 - 2*15) * 67 = 0, "
            f"got {log['mileage_pay_cents']}"
        )


class TestTravelTimePay:
    def test_travel_time_pay_tiered_150_minutes_w2_vs_c1099(self, api):
        """PRD 3.8: "Travel-time pay is tiered, and it is always 0 for a
        `C1099` rep regardless of minutes driven. For a `W2` rep, the log's
        `drive_minutes` are split into three tiers: the first tier covers the
        initial 60 minutes; the second tier covers the next 60 minutes beyond
        the first hour; the third tier covers every minute beyond 120. The
        first tier is paid straight at the rep's `travel_minute_rate_cents` per
        minute. The second tier is paid at one and a quarter times that rate,
        with the tier's amount rounded half-up to a whole cent. The third tier
        is paid at one and a half times that rate, likewise rounded half-up to
        a whole cent. The travel-time pay is the sum of the three per-tier
        amounts — each tier rounded to whole cents before summing, never
        after."

        Design: Difficulty/combinatorial_formula/travel_time_pay_tiered_nonlinear
        """
        scn = make_scenario(
            num_stores=2, num_reps=2,
            rep_overrides_list=[
                {"full_name": "W2 Traveler", "employment_type": "W2",
                 "home_base_commute_miles": 10, "mileage_rate_cents": 67,
                 "travel_minute_rate_cents": 40, "mileage_policy": "HOME_BASED"},
                {"full_name": "C1099 Traveler", "employment_type": "C1099",
                 "home_base_commute_miles": 10, "mileage_rate_cents": 67,
                 "travel_minute_rate_cents": 40, "mileage_policy": "FIRST_STOP"},
            ],
        )
        asg_w2, _ = visit_store(
            scn, store_idx=0, rep_idx=0,
            on_site=("2026-08-05T09:30:00Z", "2026-08-05T10:15:00Z"),
        )
        asg_1099, _ = visit_store(
            scn, store_idx=1, rep_idx=1,
            on_site=("2026-08-05T10:45:00Z", "2026-08-05T11:30:00Z"),
        )
        rep_w2, rep_1099 = scn["reps"]
        log_w2 = submit_mileage_log(
            rep_w2["id"], asg_w2["id"],
            round_trip_miles=100, home_to_first_stop_miles=10, drive_minutes=150,
        )
        log_1099 = submit_mileage_log(
            rep_1099["id"], asg_1099["id"],
            round_trip_miles=100, home_to_first_stop_miles=10, drive_minutes=150,
        )
        assert log_w2["travel_time_pay_cents"] == 7200, (
            f"60*40 + round_half_up(60*40*1.25) + round_half_up(30*40*1.5) = "
            f"2400+3000+1800 = 7200, got {log_w2['travel_time_pay_cents']}"
        )
        assert log_w2["mileage_pay_cents"] == 5360, (
            f"HOME_BASED: max(0, 100 - 2*10) * 67 = 5360, "
            f"got {log_w2['mileage_pay_cents']}"
        )
        assert log_1099["travel_time_pay_cents"] == 0, (
            f"C1099 reps are never paid travel time, "
            f"got {log_1099['travel_time_pay_cents']}"
        )
        assert log_1099["mileage_pay_cents"] == 6030, (
            f"FIRST_STOP: max(0, 100 - 10) * 67 = 6030, "
            f"got {log_1099['mileage_pay_cents']}"
        )

    def test_travel_time_pay_tier_anchors_45_and_90_minutes(self, api):
        """PRD 3.8: "As concrete anchors: a 45-minute day pays only first-tier
        minutes; a 90-minute day pays 60 first-tier minutes plus 30 second-tier
        minutes at the uplifted rate; a 150-minute day pays 60 first-tier, 60
        second-tier, and 30 third-tier minutes."

        Design: Difficulty/combinatorial_formula/travel_time_pay_tiered_nonlinear
        """
        scn = make_scenario(num_stores=2, num_reps=1)
        rep = scn["reps"][0]  # travel_minute_rate_cents = 40
        asg_1, _ = visit_store(
            scn, store_idx=0,
            window=("2026-08-05T08:00:00Z", "2026-08-05T09:00:00Z"),
            on_site=("2026-08-05T08:05:00Z", "2026-08-05T08:30:00Z"),
        )
        asg_2, _ = visit_store(
            scn, store_idx=1,
            window=("2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z"),
            on_site=("2026-08-05T10:05:00Z", "2026-08-05T10:30:00Z"),
        )
        log_45 = submit_mileage_log(
            rep["id"], asg_1["id"],
            round_trip_miles=50, home_to_first_stop_miles=10, drive_minutes=45,
        )
        log_90 = submit_mileage_log(
            rep["id"], asg_2["id"],
            round_trip_miles=50, home_to_first_stop_miles=10, drive_minutes=90,
        )
        assert log_45["travel_time_pay_cents"] == 1800, (
            f"45 first-tier minutes at 40 cents = 1800, "
            f"got {log_45['travel_time_pay_cents']}"
        )
        assert log_90["travel_time_pay_cents"] == 3900, (
            f"60*40 + round_half_up(30*40*1.25) = 2400+1500 = 3900, "
            f"got {log_90['travel_time_pay_cents']}"
        )


class TestMileageApprovalFreeze:
    def test_mileage_approve_recomputes_and_freezes(self, api):
        """PRD 3.8: "Approval requires the log to be `SUBMITTED` and the owning
        rep to still be `ACTIVE`; it recomputes `mileage_pay_cents` and
        `travel_time_pay_cents` and freezes them, moving the log to
        `APPROVED`."

        Design: Corner/endpoints/mileage_approve_freezes_amounts
        """
        scn, asg, visit = setup_submitted_assignment_for_rep(
            rep_overrides={"home_base_commute_miles": 10, "mileage_rate_cents": 67,
                           "travel_minute_rate_cents": 40},
        )
        rep = scn["reps"][0]
        log = submit_mileage_log(
            rep["id"], asg["id"],
            round_trip_miles=100, home_to_first_stop_miles=10, drive_minutes=60,
        )
        resp = api.approve_mileage_log(log["id"], PA)
        approved = validate_success(resp)
        assert approved["status"] == "APPROVED"
        assert approved["mileage_pay_cents"] == 5360, (
            f"max(0, 100 - 2*10) * 67 = 5360, got {approved['mileage_pay_cents']}"
        )
        assert approved["travel_time_pay_cents"] == 2400, (
            f"60 first-tier minutes at 40 cents = 2400, "
            f"got {approved['travel_time_pay_cents']}"
        )
        fetched = api.get_mileage_log(log["id"], PA)
        frozen = validate_success(fetched)
        assert frozen["mileage_pay_cents"] == 5360
        assert frozen["travel_time_pay_cents"] == 2400
