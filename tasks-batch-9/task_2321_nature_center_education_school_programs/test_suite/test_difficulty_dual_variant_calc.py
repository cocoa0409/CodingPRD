"""Depth tests for the two paired calculations the PRD keeps deliberately distinct:
the provisional versus final fee variants on a Booking (PRD §3.8) and the projected
versus realized exposure counters on an AnimalAmbassador (PRD §3.4, §3.7).
"""

from test_helpers import (
    deliver_booking,
    refresh_animal,
    refresh_booking,
    setup_animal_booking_scenario,
    setup_confirmed_booking,
)


class TestBookingFeeProvisionalVersusFinalVariant:
    """The same booking carries two gross fees because the two headcounts can select
    different volume discount bands."""

    def test_provisional_variant_prices_the_planned_thirty_student_headcount(self):
        """PRD §3.8: "The **provisional** variant reads the planned `student_count` and is evaluated when a booking is created, when it is diverted to a rain alternate, and when an outreach equipment manifest is loaded; its result is stored in `provisional_gross_fee_cents`."

        Design: Difficulty/dual_variant_calc/booking_fee_provisional_vs_final_diverges_on_actual_headcount
        """
        scenario = setup_confirmed_booking(student_count=30, chaperone_count=3)
        booking = refresh_booking(scenario["booking"]["id"])

        assert booking["student_count"] == 30
        assert booking["provisional_gross_fee_cents"] == 33300
        # PRD §3.6 initialises net_due_cents to the provisional figure, no aid awarded.
        assert booking["net_due_cents"] == 33300

    def test_final_variant_reprices_the_twenty_eight_student_actual_headcount(self):
        """PRD §3.8: "The **final** variant reads the `actual_student_count` recorded on site and is evaluated at delivery; its result is stored in `final_gross_fee_cents`."

        Design: Difficulty/dual_variant_calc/booking_fee_provisional_vs_final_diverges_on_actual_headcount
        """
        scenario = setup_confirmed_booking(student_count=30, chaperone_count=3)
        deliver_booking(
            scenario["booking"]["id"], actual_student_count=28, actual_chaperone_count=3
        )
        booking = refresh_booking(scenario["booking"]["id"])

        assert booking["final_gross_fee_cents"] == 32788

    def test_the_two_variants_diverge_on_the_same_booking(self):
        """PRD §3.8: "Because the two headcounts can select different discount bands, the final figure is not simply a rescaling of the provisional one."

        Design: Difficulty/dual_variant_calc/booking_fee_provisional_vs_final_diverges_on_actual_headcount
        """
        scenario = setup_confirmed_booking(student_count=30, chaperone_count=3)
        deliver_booking(
            scenario["booking"]["id"], actual_student_count=28, actual_chaperone_count=3
        )
        booking = refresh_booking(scenario["booking"]["id"])

        assert booking["provisional_gross_fee_cents"] == 33300
        assert booking["final_gross_fee_cents"] == 32788
        assert booking["final_gross_fee_cents"] != booking["provisional_gross_fee_cents"]

    def test_final_variant_drives_net_due_and_invoiced_funding(self):
        """PRD §3.7: "Both branches then compute `final_gross_fee_cents` through the final variant of the fee assessment, recompute `net_due_cents` from it, advance `funding_status` to `INVOICED`, transition every aid application of this booking whose status is `APPROVED` or `PARTIALLY_APPROVED` to `DISBURSED`, and recompute the school's `outstanding_balance_cents`."

        Design: Difficulty/dual_variant_calc/booking_fee_provisional_vs_final_diverges_on_actual_headcount
        """
        scenario = setup_confirmed_booking(student_count=30, chaperone_count=3)
        deliver_booking(
            scenario["booking"]["id"], actual_student_count=28, actual_chaperone_count=3
        )
        booking = refresh_booking(scenario["booking"]["id"])

        assert booking["net_due_cents"] == 32788
        assert booking["delivery_status"] == "DELIVERED"
        assert booking["funding_status"] == "INVOICED"


class TestAnimalExposureProjectedVersusRealizedVariant:
    """The forward-looking projected counter and the retrospective realized counter
    are separate books on the same ambassador."""

    def test_projected_variant_reserves_the_scheduled_duration_on_confirmation(self):
        """PRD §3.4: "The **projected** counter, `projected_exposure_minutes_7d`, is forward-looking: it sums the booked offerings' `duration_minutes` over every booking that references this animal, whose `delivery_status` is `CONFIRMED` or `RAIN_DIVERTED`, and whose `start_utc` falls inside that week."

        Design: Difficulty/dual_variant_calc/animal_exposure_projected_vs_realized_diverges_on_contact_minutes
        """
        scenario = setup_animal_booking_scenario(
            student_count=30, chaperone_count=3, confirm=True
        )
        animal = refresh_animal(scenario["animal"]["id"])

        assert scenario["offering"]["duration_minutes"] == 120
        assert animal["projected_exposure_minutes_7d"] == 120
        assert animal["realized_exposure_minutes_7d"] == 0

    def test_realized_variant_records_the_actual_contact_minutes_at_delivery(self):
        """PRD §3.7: "On the animal side, delivery moves exposure from the projected book to the realized one: `realized_exposure_minutes_7d` increases by `actual_contact_minutes` and `projected_exposure_minutes_7d` decreases by the offering's `duration_minutes` when an animal was attached."

        Design: Difficulty/dual_variant_calc/animal_exposure_projected_vs_realized_diverges_on_contact_minutes
        """
        scenario = setup_animal_booking_scenario(
            student_count=30, chaperone_count=3, confirm=True
        )
        deliver_booking(
            scenario["booking"]["id"],
            actual_student_count=30,
            actual_chaperone_count=3,
            actual_contact_minutes=75,
        )
        animal = refresh_animal(scenario["animal"]["id"])

        assert animal["realized_exposure_minutes_7d"] == 75
        assert animal["projected_exposure_minutes_7d"] == 0

    def test_the_two_exposure_counters_diverge_by_the_shortfall_in_contact_time(self):
        """PRD §3.4: "The two diverge whenever on-site contact ran shorter or longer than the scheduled duration, and that divergence is intentional — the realized figure is a welfare reporting number and is **never** used to gate anything."

        Design: Difficulty/dual_variant_calc/animal_exposure_projected_vs_realized_diverges_on_contact_minutes
        """
        scenario = setup_animal_booking_scenario(
            student_count=30, chaperone_count=3, confirm=True
        )
        before = refresh_animal(scenario["animal"]["id"])
        assert before["projected_exposure_minutes_7d"] == 120

        deliver_booking(
            scenario["booking"]["id"],
            actual_student_count=30,
            actual_chaperone_count=3,
            actual_contact_minutes=75,
        )
        after = refresh_animal(scenario["animal"]["id"])

        assert after["realized_exposure_minutes_7d"] == 75
        assert (
            before["projected_exposure_minutes_7d"]
            - after["realized_exposure_minutes_7d"]
            == 45
        )

    def test_posture_after_delivery_follows_the_projected_counter_alone(self):
        """PRD §3.4: "From the posture the system derives `effective_contact_rule`: a `BLOCKED` animal is forced to `NO_PUBLIC_CONTACT`; a `RESTRICTED` animal whose baseline `contact_rule` is `SUPERVISED_TOUCH` is downgraded to `VIEW_ONLY`; in every other case the effective rule equals the baseline `contact_rule`."

        Design: Difficulty/dual_variant_calc/animal_exposure_projected_vs_realized_diverges_on_contact_minutes
        """
        scenario = setup_animal_booking_scenario(
            student_count=30, chaperone_count=3, confirm=True
        )
        deliver_booking(
            scenario["booking"]["id"],
            actual_student_count=30,
            actual_chaperone_count=3,
            actual_contact_minutes=75,
        )
        animal = refresh_animal(scenario["animal"]["id"])

        # 75 realized minutes are welfare reporting only; the projected book is empty,
        # so the ambassador is back to OPEN on its VIEW_ONLY baseline.
        assert animal["realized_exposure_minutes_7d"] == 75
        assert animal["projected_exposure_minutes_7d"] == 0
        assert animal["welfare_posture"] == "OPEN"
        assert animal["effective_contact_rule"] == "VIEW_ONLY"
