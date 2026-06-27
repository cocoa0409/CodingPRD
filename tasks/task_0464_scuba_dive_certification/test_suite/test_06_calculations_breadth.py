"""Calculation breadth: fill-price baselines and the large-tank boundary,
rental estimate / on-time settlement, weighted completion score, waiver expiry,
and medical-status derivation.

Queue B (Corner): section calculations.
"""
from test_helpers import (
    validate_success, get_success_data,
    make_shop_admin_headers, make_instructor_headers,
    create_diver, create_course, create_instructor, create_enrollment,
    create_session, sign_waiver, create_waiver_cleared_diver, set_clock,
    book_seat, attend_booking, setup_nitrox_certified_diver,
)
from test_helpers import factories as f

ADMIN = make_shop_admin_headers()


class TestFillPrice:
    def test_fill_price_air_baseline(self, api):
        """PRD 3.9: "The base is 1200 cents. An `AIR` fill is priced at the base
        alone."

        Design: Corner/calculations/fill_price_air_baseline
        """
        diver = create_diver(full_name="Air Amy")
        fill = validate_success(
            api.create_fill_service(
                f.create_fill_service_payload(
                    diver["id"], gas="AIR", o2_pct=21, tank_capacity_liters=10
                ), ADMIN,
            ), expected_status=201,
        )
        assert fill["price_cents"] == 1200, fill

    def test_fill_price_large_tank_factor_boundary(self, api):
        """PRD 3.9: "A large-tank factor then applies: if `tank_capacity_liters` is
        greater than 12 the subtotal is multiplied by 1.25, otherwise by 1.0. The
        final `price_cents` is that product rounded half-up to whole cents."
        PRD 3.9: "800 cents when `o2_pct` is at most 32".

        Design: Corner/calculations/fill_price_large_tank_factor_boundary
        """
        diver = setup_nitrox_certified_diver()
        # NITROX32 subtotal = 1200 + 800 = 2000. 12L => factor 1.0 (not > 12) => 2000.
        fill12 = validate_success(
            api.create_fill_service(
                f.create_fill_service_payload(
                    diver["id"], gas="NITROX", o2_pct=32, tank_capacity_liters=12
                ), ADMIN,
            ), expected_status=201,
        )
        # 13L => factor 1.25 => round(2000*1.25) = 2500.
        fill13 = validate_success(
            api.create_fill_service(
                f.create_fill_service_payload(
                    diver["id"], gas="NITROX", o2_pct=32, tank_capacity_liters=13
                ), ADMIN,
            ), expected_status=201,
        )
        assert fill12["price_cents"] == 2000, fill12
        assert fill13["price_cents"] == 2500, fill13


class TestRentalBilling:
    def test_rental_estimated_cost_at_checkout(self, api):
        """PRD 3.8: "The `estimated_cost_cents`, projected forward at checkout
        against the planned return, is the billed days from `checkout_at` to
        `scheduled_return_at` multiplied by the `daily_rate_cents`".

        Design: Corner/calculations/rental_estimated_cost_at_checkout
        """
        set_clock("2026-06-10T09:00:00Z")
        diver = create_diver(full_name="Est Ed")
        rental = validate_success(
            api.create_rental_agreement(
                f.create_rental_agreement_payload(
                    diver["id"], item_description="Computer",
                    daily_rate_cents=5000, deposit_cents=15000,
                    scheduled_return_at="2026-06-13T09:00:00Z",
                ), ADMIN,
            ), expected_status=201,
        )
        assert rental["estimated_cost_cents"] == 15000, rental  # 3 days * 5000
        assert rental["status"] == "ACTIVE", rental

    def test_rental_on_time_full_deposit_refund(self, api):
        """PRD 3.8: "On-time days are the smaller of the actual and estimate day
        counts; late days are the actual day count minus the estimate day count,
        floored at zero."
        PRD 3.8: "the overage is the `actual_cost_cents` minus the
        `estimated_cost_cents`, floored at zero, and the `deposit_refund_cents` is
        the `deposit_cents` minus that overage, floored at zero."

        Design: Corner/calculations/rental_on_time_full_deposit_refund
        """
        set_clock("2026-06-10T09:00:00Z")
        diver = create_diver(full_name="Ontime Ona")
        rental = get_success_data(
            api.create_rental_agreement(
                f.create_rental_agreement_payload(
                    diver["id"], item_description="Lamp",
                    daily_rate_cents=4500, deposit_cents=20000,
                    scheduled_return_at="2026-06-12T09:00:00Z",
                ), ADMIN,
            )
        )
        set_clock("2026-06-11T20:00:00Z")  # still within 2 billed days
        returned = validate_success(
            api.checkin_rental_agreement(rental["id"], {}, ADMIN)
        )
        assert returned["actual_cost_cents"] == 9000, returned  # 2 days * 4500
        assert returned["deposit_refund_cents"] == 20000, returned  # no overage


class TestCompletionScore:
    def test_enrollment_completion_partial_score(self, api):
        """PRD 3.3: "The raw score is the e-learning percentage weighted at 0.2,
        plus the pool fraction expressed as a percentage (the fraction multiplied by
        100) weighted at 0.3, plus the open-water fraction expressed as a percentage
        weighted at 0.5. That raw score is rounded half-up to a whole integer to
        produce `completion_pct`."

        Design: Corner/calculations/enrollment_completion_partial_score
        """
        set_clock("2026-06-01T00:00:00Z")
        course = create_course(
            title="Adv 2OW", course_type="ADVANCED",
            required_pool_sessions=0, required_open_water_sessions=2, price_cents=60000,
        )
        instructor = create_instructor(full_name="Part Inst")
        diver = create_waiver_cleared_diver(full_name="Part Pia")
        session = create_session(
            course["id"], instructor["id"], session_type="OPEN_WATER",
            starts_at="2026-06-04T08:00:00Z", ends_at="2026-06-04T10:00:00Z",
        )
        enr = create_enrollment(diver["id"], course["id"])
        get_success_data(
            api.set_elearning_progress(enr["id"], {"elearning_pct": 100}, ADMIN)
        )
        booking = book_seat(session["id"], enr["id"], session["version"])
        set_clock("2026-06-04T09:00:00Z")
        attend_booking(booking["id"], instructor["id"])
        enr_after = get_success_data(api.get_enrollment(enr["id"], ADMIN))
        assert enr_after["open_water_sessions_attended"] == 1, enr_after
        # raw = 0.2*100 + 0.3*100(no pool req) + 0.5*50(1of2 OW) = 75
        assert enr_after["completion_pct"] == 75, enr_after
        assert enr_after["status"] == "ACTIVE", enr_after


class TestWaiverAndMedical:
    def test_waiver_expiry_365_days(self, api):
        """PRD 3.1: "The server stamps `signed_at` from the logical clock at the
        moment of signing and computes `expires_at` as `signed_at` plus exactly 365
        days. Signing a waiver immediately recomputes the diver's `medical_status`
        from this newly latest waiver: `CLEAR` when `medical_flagged` is false".

        Design: Corner/calculations/waiver_expiry_365_days
        """
        set_clock("2026-06-01T00:00:00Z")
        diver = create_diver(full_name="Wave Wendy")
        waiver = validate_success(
            api.create_waiver(
                f.create_waiver_payload(diver["id"], medical_flagged=False), ADMIN
            ), expected_status=201,
        )
        assert waiver["expires_at"].startswith("2027-06-01T00:00:00"), waiver
        diver_after = get_success_data(api.get_diver(diver["id"], ADMIN))
        assert diver_after["medical_status"] == "CLEAR", diver_after

    def test_medical_flagged_sets_restricted(self, api):
        """PRD 3.1: "Signing a waiver immediately recomputes the diver's
        `medical_status` from this newly latest waiver: `CLEAR` when
        `medical_flagged` is false, `RESTRICTED` when it is true."

        Design: Corner/calculations/medical_flagged_sets_restricted
        """
        set_clock("2026-06-01T00:00:00Z")
        diver = create_diver(full_name="Med Mara")
        validate_success(
            api.create_waiver(
                f.create_waiver_payload(diver["id"], medical_flagged=True), ADMIN
            ), expected_status=201,
        )
        diver_after = get_success_data(api.get_diver(diver["id"], ADMIN))
        assert diver_after["medical_status"] == "RESTRICTED", diver_after
