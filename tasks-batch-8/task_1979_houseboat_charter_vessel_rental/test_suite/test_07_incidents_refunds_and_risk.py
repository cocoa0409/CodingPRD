"""Incidents: reportability, resolution legality, the interrupt/resume cycle,
prorated mechanical refunds with pinned rounding, the emergency-maintenance
fleet cascade, and the two renter risk-score variants."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_deposit_invariants,
    charge_amounts,
    checkout_booking,
    confirm_booking,
    countersign_orientation,
    create_booking,
    create_geo_zone,
    create_qualified_renter,
    create_season_rate,
    create_vessel,
    find_charge,
    get_booking,
    get_renter,
    get_single_turn,
    get_vessel,
    inspect_turn_and_settle,
    list_charges,
    list_cleaning_turns,
    list_itineraries,
    list_maintenance_windows,
    put_itinerary,
    report_incident,
    resolve_incident,
    return_booking,
    set_clock,
    setup_checked_out_booking,
    setup_confirmed_booking,
    setup_renter_with_two_resolved_groundings,
    setup_returned_booking,
    sign_all_orientation_items,
    validate_error,
    validate_success,
    waypoint,
)

DS = TEST_USERS["dock_staff_headers"]
MECH = TEST_USERS["mechanic_headers"]


class TestIncidentReporting:
    def test_incident_report_on_held_booking_rejected(self, api):
        """PRD §3.7: "Reporting is only meaningful on an active or completed
        charter: the booking must be in `CHECKED_OUT`, `INTERRUPTED`,
        `RETURNED`, or `CLOSED` (`ERR_INVALID_STATE` otherwise)."

        Design: Corner/state_machines/incident_report_on_held_booking_rejected
        """
        vessel = create_vessel(name="Compact Inc", size_class="COMPACT_36",
                               fuel_tank_capacity_gallons=150)
        create_season_rate(size_class="COMPACT_36", season="PEAK",
                           start_date="2026-06-01", end_date="2026-08-31",
                           nightly_rate_cents=45000, weekly_discount_pct=10)
        renter, headers, _ = create_qualified_renter(
            full_name="Inc Ident", email="inc@x.com", cert_number="C-1312")
        booking = create_booking(vessel["id"], renter, headers,
                                 start_date="2026-08-01", end_date="2026-08-04")
        assert booking["status"] == "HELD"

        # occurred_at equals the default clock 2026-08-01T00:00:00Z: "not
        # after the current logical clock" and on the booking's start_date, so
        # the well-formedness gate passes and the HELD state gate surfaces.
        resp = api.report_incident(
            booking["id"],
            {"incident_type": "DAMAGE", "occurred_at": "2026-08-01T00:00:00Z"},
            headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_incident_resolution_type_mismatch_rejected(self, api):
        """PRD §3.7: "The legal mapping is strict, and any deviation is
        `ERR_INCIDENT_RESOLUTION_MISMATCH`: a `MECHANICAL_FAILURE` resolves as
        `REPAIRED_RESUME` or `REPAIRED_TERMINATE`; a `GROUNDING` resolves only
        as `GROUNDING_CONFIRMED`; a `DAMAGE` resolves only as
        `DAMAGE_ASSESSED`."
        PRD §3.7: "a `MINOR` mechanical failure can never take a `REPAIRED_`
        resolution and, if chargeable, must instead be reported and resolved as
        `DAMAGE`."

        Design: Corner/validations/incident_resolution_type_mismatch_rejected
        """
        ctx = setup_checked_out_booking(start_date="2026-08-20",
                                        end_date="2026-08-24",
                                        zone_code="ZP-MIS")
        booking = ctx["booking"]
        headers = ctx["renter_headers"]
        set_clock("2026-08-21T00:00:00Z")
        damage = report_incident(booking["id"], headers, "DAMAGE",
                                 "2026-08-20T15:00:00Z")
        mech = report_incident(booking["id"], headers, "MECHANICAL_FAILURE",
                               "2026-08-20T16:00:00Z")

        resp = api.resolve_incident(
            damage["id"],
            {"resolution": "REPAIRED_RESUME", "severity": "MAJOR",
             "downtime_days": 1},
            MECH)
        validate_error(resp, ApiErrorId.ERR_INCIDENT_RESOLUTION_MISMATCH, 422)

        resp = api.resolve_incident(
            mech["id"],
            {"resolution": "REPAIRED_RESUME", "severity": "MINOR",
             "downtime_days": 1},
            MECH)
        validate_error(resp, ApiErrorId.ERR_INCIDENT_RESOLUTION_MISMATCH, 422)

        # Both incidents remain REPORTED, the booking stays CHECKED_OUT, and no
        # charge lines are posted beyond the RENTAL line from confirm.
        for record in validate_success(api.list_incidents(booking["id"], DS), 200):
            assert record["status"] == "REPORTED"
        assert get_booking(booking["id"])["status"] == "CHECKED_OUT"
        assert [c["line_type"] for c in list_charges(booking["id"])] == ["RENTAL"]


class TestInterruptResumeCycle:
    def _setup_mechanical_incident(self):
        ctx = setup_checked_out_booking(
            size_class="STANDARD_44", tank=200, vessel_name="Standard Four",
            start_date="2026-08-20", end_date="2026-08-27", party_size=3,
            zone_code="ZP-PADRE")
        assert ctx["booking"]["quoted_total_cents"] == 409500  # 7x65000 - 45500
        set_clock("2026-08-22T12:00:00Z")
        incident = report_incident(ctx["booking"]["id"], ctx["renter_headers"],
                                   "MECHANICAL_FAILURE", "2026-08-22T10:00:00Z")
        return ctx, incident

    def test_repaired_resume_cycles_back_to_checked_out(self, api):
        """PRD §3.7: "`REPAIRED_RESUME` — the repair completes on the water.
        The booking cycles `CHECKED_OUT` → `INTERRUPTED` and back to
        `CHECKED_OUT`, the settlement dimension stays `PROVISIONAL` throughout,
        and a prorated mechanical refund is posted as a single negative
        `MECHANICAL_REFUND` charge: the pinned `quoted_total_cents` times
        `downtime_days` divided by `total_nights`, rounded half up to whole
        cents."

        Design: Difficulty/non_linear_state_machine/booking_interrupt_resume_cycle
        """
        ctx, incident = self._setup_mechanical_incident()

        resolved = resolve_incident(incident["id"], "REPAIRED_RESUME",
                                    severity="MAJOR", downtime_days=2)
        assert resolved["status"] == "RESOLVED"

        booking = get_booking(ctx["booking"]["id"])
        assert booking["status"] == "CHECKED_OUT", (
            "INTERRUPTED is entered and exited by the same resolve"
        )
        assert booking["settlement_status"] == "PROVISIONAL", (
            "the parallel settlement dimension holds through the cycle"
        )
        assert booking["deposit_status"] == "HELD"

        refund = find_charge(list_charges(booking["id"]), "MECHANICAL_REFUND")
        assert refund["amount_cents"] == -117000, (
            f"409500 x 2/7 = 117000 exactly, got {refund['amount_cents']}"
        )
        assert refund["status"] == "POSTED"

    def test_interrupt_resume_cycle_settles_with_refund(self, api):
        """PRD §3.7: "The booking cycles `CHECKED_OUT` → `INTERRUPTED` and back
        to `CHECKED_OUT`, the settlement dimension stays `PROVISIONAL`
        throughout"
        PRD §3.8: "When the net is negative — refunds exceed charges — nothing
        is applied, `deposit_released_cents` equals `deposit_held_cents`, and
        the absolute net is added to `refund_issued_cents`."
        PRD §3.8: "negative refund lines are marked `REFUNDED`."

        Design: Difficulty/non_linear_state_machine/booking_interrupt_resume_cycle
        """
        ctx, incident = self._setup_mechanical_incident()
        resolve_incident(incident["id"], "REPAIRED_RESUME",
                         severity="MAJOR", downtime_days=2)

        # The booking is CHECKED_OUT again, so return and settlement proceed.
        returned = return_booking(ctx["booking"]["id"], "2026-08-25T09:00:00Z",
                                  fuel_gauge_percent=100, pump_out_done=True)
        assert returned["status"] == "RETURNED"
        ctx["turn"] = get_single_turn(ctx["booking"]["id"])
        settled, charges = inspect_turn_and_settle(ctx)

        # cleaning 25000 - mechanical refund 117000 -> net -92000.
        assert settled["final_settlement_cents"] == -92000
        assert settled["status"] == "CLOSED"
        assert settled["settlement_status"] == "FINALIZED"
        assert settled["deposit_status"] == "RELEASED"
        assert settled["deposit_applied_cents"] == 0
        assert settled["deposit_released_cents"] == 200000
        assert settled["refund_issued_cents"] == 92000
        assert_deposit_invariants(settled)
        refund = find_charge(charges, "MECHANICAL_REFUND")
        assert refund["status"] == "REFUNDED"


class TestMechanicalRefundRounding:
    def _setup_terminate_scenario(self):
        ctx = setup_checked_out_booking(
            size_class="LUXE_56", tank=300, berth=8, vessel_name="Luxe Three",
            rates=[("PEAK", "2026-06-01", "2026-08-31", 90000, 10),
                   ("SHOULDER", "2026-09-01", "2026-10-31", 65000, 10)],
            start_date="2026-08-28", end_date="2026-09-12", party_size=4,
            renter_name="Rue Round", renter_email="rue@x.com",
            with_itinerary=True, zone_code="ZP-ANTELOPE",
            itinerary_night="2026-08-28",
            checkout_clock="2026-08-28T09:00:00Z")
        assert ctx["booking"]["quoted_total_cents"] == 1029500
        set_clock("2026-09-07T12:00:00Z")
        incident = report_incident(ctx["booking"]["id"], ctx["renter_headers"],
                                   "MECHANICAL_FAILURE", "2026-09-07T09:30:00Z")
        return ctx, incident

    def test_mechanical_refund_rounds_half_up_per_line(self, api):
        """PRD §3.7: "The booking moves `CHECKED_OUT` → `INTERRUPTED`, and the
        refund covers only full remaining nights: `quoted_total_cents` times
        the nights from the current date to `end_date`, divided by
        `total_nights`, rounded half up — the interruption day itself counts as
        used."
        PRD §3.7: "All of these incident charges sit `POSTED` on the ledger,
        waiting for settlement to reconcile them."

        Design: Difficulty/combinatorial_formula/settlement_refund_line_rounding_order
        """
        ctx, incident = self._setup_terminate_scenario()

        resolve_incident(incident["id"], "REPAIRED_TERMINATE",
                         severity="MAJOR", downtime_days=4)

        booking = get_booking(ctx["booking"]["id"])
        assert booking["status"] == "INTERRUPTED"
        assert booking["settlement_status"] == "PROVISIONAL"

        refund = find_charge(list_charges(ctx["booking"]["id"]), "MECHANICAL_REFUND")
        # round_half_up(1029500 x 5 remaining nights / 15) = 343166.67 -> 343167;
        # truncation would give 343166.
        assert refund["amount_cents"] == -343167
        assert refund["status"] == "POSTED", "awaits settlement reconciliation"

        vessel = get_vessel(ctx["vessel"]["id"])
        assert vessel["status"] == "IN_MAINTENANCE"
        windows = list_maintenance_windows(ctx["vessel"]["id"])
        emergency = [w for w in windows if w["source"] == "INCIDENT_EMERGENCY"]
        assert len(emergency) == 1
        assert emergency[0]["start_date"] == "2026-09-07"
        assert emergency[0]["end_date"] == "2026-09-11"  # current + 4 downtime days
        assert emergency[0]["status"] == "IN_PROGRESS"

    def test_settlement_sums_rounded_lines(self, api):
        """PRD §2.7: "One rounding discipline is pinned across every
        settlement-style computation: each charge line is computed and rounded
        to whole cents first, and any total is then the plain sum of those
        already-rounded lines. The system never sums unrounded components and
        rounds once at the end."
        PRD §3.8: "When the net is negative — refunds exceed charges — nothing
        is applied, `deposit_released_cents` equals `deposit_held_cents`, and
        the absolute net is added to `refund_issued_cents`."

        Design: Difficulty/combinatorial_formula/settlement_refund_line_rounding_order
        """
        ctx, incident = self._setup_terminate_scenario()
        resolve_incident(incident["id"], "REPAIRED_TERMINATE",
                         severity="MAJOR", downtime_days=4)

        returned = return_booking(ctx["booking"]["id"], "2026-09-07T15:00:00Z",
                                  fuel_gauge_percent=100, pump_out_done=True)
        assert returned["status"] == "RETURNED"
        ctx["turn"] = get_single_turn(ctx["booking"]["id"])
        settled, charges = inspect_turn_and_settle(ctx)

        # cleaning 25000 + (-343167 refund); fuel 0 at equal gauges, pump-out 0,
        # late 0 -> net -318167 (summing unrounded parts would give -318166).
        assert settled["final_settlement_cents"] == -318167
        assert settled["refund_issued_cents"] == 318167
        assert settled["deposit_status"] == "RELEASED"
        assert settled["deposit_applied_cents"] == 0
        assert settled["deposit_released_cents"] == 250000
        assert settled["status"] == "CLOSED"
        assert_deposit_invariants(settled)
        refund = find_charge(charges, "MECHANICAL_REFUND")
        assert refund["status"] == "REFUNDED"


class TestEmergencyMaintenanceCascade:
    def _setup_fleet_cascade(self):
        vessel = create_vessel(name="Luxe Seven", size_class="LUXE_56", berth_count=8,
                               fuel_tank_capacity_gallons=300)
        create_season_rate(size_class="LUXE_56", season="PEAK",
                           start_date="2026-06-01", end_date="2026-08-31",
                           nightly_rate_cents=90000, weekly_discount_pct=10)
        renter, headers, _ = create_qualified_renter(
            full_name="Moe Tow", email="moe@x.com", cert_number="C-600",
            cert_issued_on="2026-01-20")
        zone = create_geo_zone(zone_code="ZP-WARM", name="Warm Creek",
                               allowed_size_classes=["LUXE_56"])

        # A: a 10-night charter, confirmed, then checked out on its start day.
        # The length keeps downtime_days=5 legal at the 2026-08-15 resolve
        # date (PRD: downtime_days may not exceed the nights remaining from
        # the current date to end_date; 2026-08-20 - 2026-08-15 = 5).
        a = create_booking(vessel["id"], renter, headers,
                           start_date="2026-08-10", end_date="2026-08-20",
                           party_size=4)
        a = confirm_booking(a["id"], headers)
        put_itinerary(a["id"], headers, [waypoint(zone["id"], "2026-08-10")])
        sign_all_orientation_items(a["id"], headers, "LUXE_56")
        countersign_orientation(a["id"], approved=True)
        set_clock("2026-08-10T09:00:00Z")
        a = checkout_booking(a["id"], fuel_gauge_percent=100, pump_out_done=True)

        # Create E and D at the 2026-08-15 clock so E's 48-hour hold outlives
        # the resolve below (no further clock advance happens after it).
        # E: HELD from A's end-date onward; D: confirmed, adjacent to A. Both
        # start on 2026-08-20 so the emergency window [08-15, 08-20] touches
        # their start edge (closed-interval comparison counts it).
        set_clock("2026-08-15T12:00:00Z")
        e = create_booking(vessel["id"], renter, headers,
                           start_date="2026-08-20", end_date="2026-08-22",
                           party_size=4)
        d = create_booking(vessel["id"], renter, headers,
                           start_date="2026-08-20", end_date="2026-08-23",
                           party_size=4)
        d = confirm_booking(d["id"], headers)
        put_itinerary(d["id"], headers, [waypoint(zone["id"], "2026-08-20")])

        incident = report_incident(a["id"], headers, "MECHANICAL_FAILURE",
                                   "2026-08-15T09:30:00Z")
        return {"vessel": vessel, "renter": renter, "headers": headers,
                "zone": zone, "a": a, "d": d, "e": e, "incident": incident}

    def test_repaired_terminate_interrupts_and_opens_emergency_window(self, api):
        """PRD §3.7: "`REPAIRED_TERMINATE` — the charter cannot continue. The
        booking moves `CHECKED_OUT` → `INTERRUPTED`, and the refund covers only
        full remaining nights: `quoted_total_cents` times the nights from the
        current date to `end_date`, divided by `total_nights`, rounded half up
        — the interruption day itself counts as used. The vessel drops to
        `IN_MAINTENANCE`, and an emergency maintenance window is born already
        `IN_PROGRESS` with `source` `INCIDENT_EMERGENCY`, covering the closed
        interval from the current date through the current date plus
        `downtime_days`."

        Design: Difficulty/transitive_cascade/mechanical_resolution_fleet_cascade
        """
        ctx = self._setup_fleet_cascade()
        # 10 nights x 90000 = 900000 minus one weekly run 7 x 90000 x 10%.
        assert ctx["a"]["quoted_total_cents"] == 837000

        resolve_incident(ctx["incident"]["id"], "REPAIRED_TERMINATE",
                         severity="MAJOR", downtime_days=5)

        a = get_booking(ctx["a"]["id"])
        assert a["status"] == "INTERRUPTED"
        refund = find_charge(list_charges(a["id"]), "MECHANICAL_REFUND")
        # 5 unused nights (2026-08-15 -> 2026-08-20): 837000 x 5/10 = 418500.
        assert refund["amount_cents"] == -418500

        vessel = get_vessel(ctx["vessel"]["id"])
        assert vessel["status"] == "IN_MAINTENANCE"
        windows = list_maintenance_windows(ctx["vessel"]["id"])
        emergency = [w for w in windows if w["source"] == "INCIDENT_EMERGENCY"]
        assert len(emergency) == 1
        assert emergency[0]["status"] == "IN_PROGRESS"
        assert emergency[0]["start_date"] == "2026-08-15"
        assert emergency[0]["end_date"] == "2026-08-20"  # current + 5 days

    def test_emergency_window_cascade_cancels_overlapping_bookings(self, api):
        """PRD §3.7: "That window then behaves like any maintenance conflict:
        every other booking of the vessel in `HELD` or `CONFIRMED` overlapping
        it under closed-interval comparison is cascade-cancelled with
        `cancellation_reason` `VESSEL_MECHANICAL` and the full 100% refund
        treatment."
        PRD §3.9: "System-initiated cancellations — `RENTER_SUSPENDED` from the
        certificate cascade and `VESSEL_MECHANICAL` from the emergency-window
        cascade — always take the 100% path."

        Design: Difficulty/transitive_cascade/mechanical_resolution_fleet_cascade
        """
        ctx = self._setup_fleet_cascade()
        resolve_incident(ctx["incident"]["id"], "REPAIRED_TERMINATE",
                         severity="MAJOR", downtime_days=5)

        d = get_booking(ctx["d"]["id"])
        assert d["status"] == "CANCELLED"
        assert d["cancellation_reason"] == "VESSEL_MECHANICAL"
        assert d["refund_issued_cents"] == 270000, "100% of the 3-night quote"
        assert d["deposit_status"] == "RELEASED"
        assert d["deposit_released_cents"] == 250000
        assert d["deposit_applied_cents"] == 0
        assert_deposit_invariants(d)

        refund_line = find_charge(list_charges(d["id"]), "CANCELLATION_REFUND")
        assert refund_line["amount_cents"] == -270000
        assert refund_line["status"] == "REFUNDED"

        itineraries = list_itineraries(d["id"])
        assert itineraries[0]["status"] == "VOID"
        turns = list_cleaning_turns(d["id"])
        assert turns[0]["status"] == "CANCELLED"

        e = get_booking(ctx["e"]["id"])
        assert e["status"] == "CANCELLED"
        assert e["cancellation_reason"] == "VESSEL_MECHANICAL"
        assert e["refund_issued_cents"] == 0, "a HELD booking paid nothing"
        assert e["deposit_status"] == "RELEASED"
        assert e["deposit_held_cents"] == 0


class TestRenterRiskVariants:
    def test_risk_variants_diverge_after_aging(self, api):
        """PRD §3.3: "`risk_score_lifetime` sums a severity weight — 10 for
        `MINOR`, 25 for `MAJOR`, 60 for `TOTAL_LOSS` — over every resolved
        incident on any of the renter's bookings, with no time window;
        `risk_score_rolling_24m` applies the same sum but only to incidents
        whose `occurred_at` falls on or after the date exactly 24 months before
        the current date, boundary inclusive, so an identical history yields a
        lower score once an old incident ages out."

        Design: Difficulty/dual_variant_calc/renter_risk_lifetime_vs_rolling_window
        """
        ctx = setup_renter_with_two_resolved_groundings()
        profile = get_renter(ctx["renter"]["id"])
        assert profile["risk_score_lifetime"] == 35, (
            "MAJOR 25 + MINOR 10 with no time window; got "
            f"{profile['risk_score_lifetime']}"
        )
        # At the 2026-08-01 evaluation date the 2024-06-12 incident is older
        # than the 2024-08-01 cutoff and drops out of the rolling window.
        assert profile["risk_score_rolling_24m"] == 10, (
            f"only the 2026-07-06 MINOR incident remains, got "
            f"{profile['risk_score_rolling_24m']}"
        )
        assert profile["deposit_multiplier"] == 1.0, (
            "the rolling variant drives the deposit tier: 10 < 20 -> 1.0"
        )

    def test_deposit_uses_rolling_variant_only(self, api):
        """PRD §3.3: "The rolling variant alone drives the deposit tier: a
        rolling score below 20 means a `deposit_multiplier` of 1.0, a score of
        at least 20 but below 50 means 1.5, and a score of 50 or more
        means 2.0."
        PRD §3.4: "The deposit requirement is computed once, at creation, and
        snapshotted into `deposit_required_cents`, never to be recomputed
        afterwards even if the renter's risk score changes later. The base
        depends on size class — 150,000 cents for `COMPACT_36`, 200,000 cents
        for `STANDARD_44`, 250,000 cents for `LUXE_56` — and is multiplied by
        the renter's current `deposit_multiplier` (1.0, 1.5, or 2.0 per the
        rolling-risk tiers of §3.3)."

        Design: Difficulty/dual_variant_calc/renter_risk_lifetime_vs_rolling_window
        """
        ctx = setup_renter_with_two_resolved_groundings()
        booking = create_booking(ctx["vessel"]["id"], ctx["renter"],
                                 ctx["renter_headers"],
                                 start_date="2026-08-20", end_date="2026-08-22")
        # LIFETIME 35 would imply the 1.5 tier (225000); the rolling score of
        # 10 keeps the deposit at the 1.0 base.
        assert booking["deposit_required_cents"] == 150000, (
            f"BASE_DEPOSIT[COMPACT_36] x 1.0; got {booking['deposit_required_cents']}"
        )
