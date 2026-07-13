"""Permit-fee dual variants, the municipal surcharge, and officer billing."""
import test_helpers as th
from test_helpers import validate_success, get_success_data


class TestPermitFeeEstimateVsFinal:
    """The cost-accounting dual variant on the PermitApplication domain."""

    def test_estimate_and_final_diverge_on_denied_rider(self, api):
        """PRD §3.4: "In the ESTIMATE variant, computed at submit and stamped into
        estimated_fee_cents, the included booking count is every RoadClosureBooking for the
        application whose status is PENDING or CONFIRMED, and the included rider counts are
        every rider of each type whose status is REQUESTED or APPROVED — a forward-looking
        figure covering everything the applicant has asked for."
        PRD §3.5: "The FINAL permit fee uses the same six-term subtotal formula from §3.4 but
        with the FINAL input set: the included booking count is only those RoadClosureBooking
        rows for the application now in CONFIRMED status, and the included rider counts use only
        riders in APPROVED status. Denied riders and blocked bookings therefore drop out, and
        the FINAL subtotal generally differs from the ESTIMATE."
        PRD §3.4: "a rider charge equal to 30,000 cents for each included DRONE rider plus
        5,000 cents for each included STILL_PHOTO rider."

        Design: Difficulty/dual_variant_calc/permit_fee_estimate_vs_final
        """
        ctx = th.setup_dual_variant_fee_scenario(api)
        resp = api.issue_application(ctx["app_id"], {"expected_application_version": ctx["issue_version"]},
                                     th.make_coordinator_headers())
        data = validate_success(resp, 200)
        assert data["estimated_fee_cents"] == 204750
        assert data["final_fee_cents"] == 190000
        assert data["estimated_fee_cents"] != data["total_fee_cents"], \
            "denied STILL_PHOTO rider drops out of FINAL, so the variants diverge"

    def test_final_surcharge_total_and_deposit_stamped(self, api):
        """PRD §3.5: "The municipal surcharge is recomputed over the FINAL subtotal using the
        §3.4 tier rule and stamped into municipal_surcharge_cents, and total_fee_cents is
        stamped as final_fee_cents plus municipal_surcharge_cents."
        PRD §3.4: "The rate is 300 basis points when the subtotal is below 100,000 cents,
        500 basis points when the subtotal is at least 100,000 cents but below 300,000 cents,
        and 700 basis points when the subtotal is 300,000 cents or more ..."
        PRD §3.5: "The deposit percentage is 2,500 basis points (25%) when total_fee_cents is
        at least 500,000 cents, and 2,000 basis points (20%) otherwise ..."
        PRD §3.5: "... plus a road-closure bond of 50,000 cents for each RoadClosureBooking
        that is CONFIRMED at issue."

        Design: Difficulty/dual_variant_calc/permit_fee_estimate_vs_final
        """
        ctx = th.setup_dual_variant_fee_scenario(api)
        resp = api.issue_application(ctx["app_id"], {"expected_application_version": ctx["issue_version"]},
                                     th.make_coordinator_headers())
        data = validate_success(resp, 200)
        assert data["municipal_surcharge_cents"] == 9500
        assert data["total_fee_cents"] == 199500
        assert data["deposit_cents"] == 89900


class TestPermitFeeNonlinearCrewAndFlags:
    """Non-linear tiered crew surcharge combined with conditional flags at submit."""

    def _submit_crew60(self, api):
        th.set_clock(api, th.DEFAULT_CLOCK)
        pc = th.make_company(api, legal_name="Gamma Studios", contact_email="ops@gamma.test", primary_contact="Jo Kim")
        seg = th.make_segment(api, segment_code="OAK-200", name="Oak Ave 200", length_m=90)
        app = th.make_application(api, pc["id"], title="Chase", synopsis="Action",
                                  shoot_start_at="2026-06-01T08:00:00Z",
                                  shoot_end_at="2026-06-02T20:00:00Z",
                                  crew_size=60, requires_road_closure=True)
        th.add_location(api, app["id"], pc["id"], address="200 Oak Ave", geo_zone="Z3",
                        requested_start_at="2026-06-01T08:00:00Z",
                        requested_end_at="2026-06-02T20:00:00Z", uses_road_closure=True)
        th.add_booking(api, app["id"], pc["id"], seg["id"],
                       closure_start_at="2026-06-01T08:00:00Z", closure_end_at="2026-06-01T18:00:00Z")
        return get_success_data(api.submit_application(app["id"], {}, th.make_production_company_headers(pc["id"])))

    def test_inclusive_shoot_days_span(self, api):
        """PRD §3.2: "From the two shoot instants the system derives shoot_days, the inclusive
        calendar-day span computed as the date of shoot_end_at minus the date of shoot_start_at,
        plus one."

        Design: Difficulty/combinatorial_formula/permit_fee_nonlinear_crew_and_flags
        """
        data = self._submit_crew60(api)
        assert data["shoot_days"] == 2

    def test_tiered_crew_surcharge_estimate(self, api):
        """PRD §3.4: "a crew surcharge keyed on crew_size: 0 cents when the crew is 15 or fewer,
        20,000 cents when the crew is between 16 and 50 inclusive, 50,000 cents when the crew is
        between 51 and 150 inclusive, and 100,000 cents when the crew exceeds 150;"
        PRD §3.4: "a road-closure charge that is 0 when the application's requires_road_closure
        is false, and otherwise 40,000 cents multiplied by the number of included road-closure
        bookings;"
        PRD §3.4: "The rate is 300 basis points when the subtotal is below 100,000 cents,
        500 basis points when the subtotal is at least 100,000 cents but below 300,000 cents,
        and 700 basis points when the subtotal is 300,000 cents or more ..."

        Design: Difficulty/combinatorial_formula/permit_fee_nonlinear_crew_and_flags
        """
        data = self._submit_crew60(api)
        assert data["estimated_fee_cents"] == 152250


class TestMunicipalSurchargeTierKeying:
    """The surcharge rate is keyed on the pre-surcharge subtotal tier, not the total."""

    def _submit_crew200(self, api):
        th.set_clock(api, th.DEFAULT_CLOCK)
        pc = th.make_company(api, legal_name="Delta Media", contact_email="ops@delta.test", primary_contact="Lee Ng")
        seg_a = th.make_segment(api, segment_code="SEG-A", name="Seg A", length_m=80)
        seg_b = th.make_segment(api, segment_code="SEG-B", name="Seg B", length_m=80)
        seg_c = th.make_segment(api, segment_code="SEG-C", name="Seg C", length_m=80)
        app = th.make_application(api, pc["id"], title="Parade", synopsis="Big",
                                  shoot_start_at="2026-06-01T08:00:00Z",
                                  shoot_end_at="2026-06-03T20:00:00Z",
                                  crew_size=200, requires_road_closure=True)
        th.add_location(api, app["id"], pc["id"], address="1 Plaza", geo_zone="Z4",
                        requested_start_at="2026-06-01T08:00:00Z",
                        requested_end_at="2026-06-03T20:00:00Z", uses_road_closure=True)
        for seg in (seg_a, seg_b, seg_c):
            th.add_booking(api, app["id"], pc["id"], seg["id"],
                           closure_start_at="2026-06-01T08:00:00Z", closure_end_at="2026-06-01T18:00:00Z")
        return get_success_data(api.submit_application(app["id"], {}, th.make_production_company_headers(pc["id"])))

    def test_surcharge_uses_subtotal_tier_value(self, api):
        """PRD §3.4: "Layered on the subtotal is the municipal surcharge, whose rate in basis
        points is selected from the subtotal's tier — not from the post-surcharge total."
        PRD §3.4: "The rate is 300 basis points when the subtotal is below 100,000 cents,
        500 basis points when the subtotal is at least 100,000 cents but below 300,000 cents,
        and 700 basis points when the subtotal is 300,000 cents or more ..."

        Design: Difficulty/combinatorial_formula/municipal_surcharge_tier_keyed_on_subtotal
        """
        data = self._submit_crew200(api)
        assert data["estimated_fee_cents"] == 304500

    def test_surcharge_not_keyed_on_post_surcharge_total(self, api):
        """PRD §3.4: "The evaluation order is pinned: first compute the subtotal, then choose
        the rate, then compute the surcharge, then add it to the subtotal."
        PRD §3.4: "Layered on the subtotal is the municipal surcharge, whose rate in basis
        points is selected from the subtotal's tier — not from the post-surcharge total."

        Design: Difficulty/combinatorial_formula/municipal_surcharge_tier_keyed_on_subtotal
        """
        data = self._submit_crew200(api)
        # 290000 subtotal => 500 bps => 304500. Keying on the post-surcharge total (>=300000)
        # would wrongly select 700 bps and yield 310300.
        assert data["estimated_fee_cents"] == 304500
        assert data["estimated_fee_cents"] != 310300


def test_officer_assignment_billed_cost(api):
    """PRD §3.6: "A new assignment begins in PROPOSED status, and its billed_cost_cents is
    computed at creation as the officer's hourly_rate_cents multiplied by the shift length in
    whole hours, where the shift length is the difference between shift_end_at and
    shift_start_at converted to hours and rounded up to the next whole hour."

    Design: Corner/calculations/officer_assignment_cost_correct_result
    """
    ctx = th.setup_under_review_single_review(api, company_name="Cost Co",
                                              app_overrides={"shoot_start_at": "2026-06-01T06:00:00Z",
                                                             "shoot_end_at": "2026-06-01T20:00:00Z"})
    officer = th.make_officer(api, full_name="Ofc Cost", badge_number="B-C", hourly_rate_cents=8000)
    resp = api.create_officer_assignment(
        {"application_id": ctx["app_id"], "officer_id": officer["id"],
         "shift_start_at": "2026-06-01T08:00:00Z", "shift_end_at": "2026-06-01T12:00:00Z"},
        th.make_coordinator_headers(),
    )
    data = validate_success(resp, 201)
    assert data["billed_cost_cents"] == 32000
