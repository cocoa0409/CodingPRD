"""Surgery outcomes: multi-hop cascades, mortality, immediate consistency."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_coordinator_headers, make_clinic_staff_headers,
    setup_caretaker_with_colony, create_cat, create_partner_clinic,
    create_clinic_day, list_slots, get_day, get_slot, get_voucher, get_cat,
    get_appointment, get_colony, book_appointment, create_voucher,
    drive_cat_to_post_surgery, create_surgery_record_payload,
)


class TestSurgeryCompletionCascade:
    """Difficulty/transitive_cascade/surgery_completion_four_hop_cascade"""

    def test_surviving_surgery_completes_full_cascade(self, api):
        """PRD §3.4: "A surviving outcome — `STERILIZED` or `ALREADY_STERILE` —
        moves the cat from `AT_CLINIC` to `POST_SURGERY` and copies the record's
        markers onto the cat: the cat's `ear_tipped` and `vaccinated_rabies`
        become exactly what the surgeon recorded. The appointment completes
        (`TRAPPED` to `COMPLETED`), its slot is consumed (`BOOKED` to `USED`), the
        day's `booked_count` decrements by one, and a voucher committed on the
        appointment is redeemed (`COMMITTED` to `REDEEMED`)"

        Design: Difficulty/transitive_cascade/surgery_completion_four_hop_cascade
        """
        ct, cth, col = setup_caretaker_with_colony(estimated_population=1)
        cat = create_cat(col, intake_tag="H1", approximate_age_months=24)
        clinic = create_partner_clinic(name="HillVet")
        day = create_clinic_day(clinic, service_date="2026-08-19T00:00:00Z",
                                base_capacity=1, surge_capacity=0)
        slots = list_slots(day)
        v = create_voucher(ct, face_value_cents=8000)
        appt, record, cat_after = drive_cat_to_post_surgery(
            cat, cth, day["id"], slots[0], voucher_id=v["id"],
            trap_date="2026-08-18T00:00:00Z")

        assert cat_after["status"] == "POST_SURGERY"
        assert cat_after["ear_tipped"] is True
        assert cat_after["vaccinated_rabies"] is True
        assert get_appointment(appt["id"])["status"] == "COMPLETED"
        assert get_slot(slots[0]["id"])["status"] == "USED"
        assert get_day(day["id"])["booked_count"] == 0
        assert get_voucher(v["id"])["status"] == "REDEEMED"

    def test_post_surgery_cat_counts_in_denominator_not_numerator(self, api):
        """PRD §2.6: "`sterilized_pct` is the fraction of the colony's resident
        cats whose `status` is `RETURNED` or `COLONY_STERILIZED`."
        A POST_SURGERY cat is resident but not sterilized, so a colony whose only
        cat just completed surgery sits at sterilized_pct 0.

        Design: Difficulty/transitive_cascade/surgery_completion_four_hop_cascade
        """
        ct, cth, col = setup_caretaker_with_colony(estimated_population=1)
        cat = create_cat(col, intake_tag="H2", approximate_age_months=24)
        clinic = create_partner_clinic(name="HillVet2")
        day = create_clinic_day(clinic, service_date="2026-08-19T00:00:00Z",
                                base_capacity=1, surge_capacity=0)
        slots = list_slots(day)
        drive_cat_to_post_surgery(cat, cth, day["id"], slots[0],
                                  trap_date="2026-08-18T00:00:00Z")

        colony = get_colony(col["id"])
        assert colony["sterilized_pct"] == 0, \
            f"POST_SURGERY counts in the denominator but not numerator; got {colony['sterilized_pct']}"


class TestNoShowSweepCascade:
    """Difficulty/transitive_cascade/clinic_day_close_noshow_cascade"""

    def test_close_sweeps_scheduled_appointment_to_no_show(self, api):
        """PRD §3.2: "Closing a day performs the end-of-day sweep: every `BOOKED`
        slot whose appointment still stands `SCHEDULED` is consumed — the slot
        becomes `USED`, the appointment becomes `NO_SHOW`, a voucher committed on
        such an appointment is released back from `COMMITTED` to `ISSUED`, and the
        cat simply remains `AT_LARGE` — while every remaining `OPEN` slot becomes
        `RELEASED` and the day becomes `COMPLETED`."

        Design: Difficulty/transitive_cascade/clinic_day_close_noshow_cascade
        """
        ct, cth, col = setup_caretaker_with_colony(estimated_population=1)
        cat = create_cat(col, intake_tag="Q1", sex="FEMALE", approximate_age_months=24)
        clinic = create_partner_clinic(name="QuarryVet")
        day = create_clinic_day(clinic, service_date="2026-08-05T00:00:00Z",
                                base_capacity=1, surge_capacity=0)
        slots = list_slots(day)
        v = create_voucher(ct, face_value_cents=7000, funding_source="DONATION_FUND")
        appt, _ = book_appointment(cat, slots[0], day["id"], cth,
                                   voucher_id=v["id"], trap_date="2026-08-04T00:00:00Z")

        sh = make_clinic_staff_headers()
        data = validate_success(api.close_clinic_day(day["id"], sh), expected_status=200)
        assert data["status"] == "COMPLETED"
        assert get_appointment(appt["id"])["status"] == "NO_SHOW"
        assert get_slot(slots[0]["id"])["status"] == "USED", \
            "no-show consumes the slot"
        assert get_voucher(v["id"])["status"] == "ISSUED", \
            "voucher released back despite slot consumption"
        assert get_cat(cat["id"])["status"] == "AT_LARGE", \
            "cat untouched by the sweep"

    def test_close_releases_remaining_open_slots(self, api):
        """PRD §3.2: "while every remaining `OPEN` slot becomes `RELEASED` and the
        day becomes `COMPLETED`."

        Design: Difficulty/transitive_cascade/clinic_day_close_noshow_cascade
        """
        ct, cth, col = setup_caretaker_with_colony(estimated_population=1)
        cat = create_cat(col, intake_tag="Q2", approximate_age_months=24)
        clinic = create_partner_clinic(name="QuarryVet2")
        day = create_clinic_day(clinic, service_date="2026-08-05T00:00:00Z",
                                base_capacity=2, surge_capacity=0)
        slots = list_slots(day)
        book_appointment(cat, slots[0], day["id"], cth,
                         trap_date="2026-08-04T00:00:00Z")

        sh = make_clinic_staff_headers()
        get_success_data(api.close_clinic_day(day["id"], sh))
        assert get_slot(slots[1]["id"], headers=sh)["status"] == "RELEASED"


class TestMortalityOutcome:
    def test_died_in_surgery_voids_voucher(self, api):
        """PRD §3.4: "A fatal outcome — `DIED_IN_SURGERY` — moves the cat from
        `AT_CLINIC` to `DECEASED` instead. The appointment still completes and the
        slot is still consumed with the day's `booked_count` decrementing, but a
        committed voucher is voided (`COMMITTED` to `VOIDED`) and no reimbursement
        is made on a mortality."

        Design: Corner/calculations/monthly_cap_excludes_voided_vouchers
        """
        ct, cth, col = setup_caretaker_with_colony(estimated_population=1)
        cat = create_cat(col, intake_tag="V1", approximate_age_months=24)
        clinic = create_partner_clinic(name="VoidVet", voucher_reimbursement_cents=30000)
        day = create_clinic_day(clinic, service_date="2026-08-20T00:00:00Z",
                                base_capacity=1, surge_capacity=0)
        slots = list_slots(day)
        v1 = create_voucher(ct, face_value_cents=25000)
        appt, _ = book_appointment(cat, slots[0], day["id"], cth,
                                   voucher_id=v1["id"], trap_date="2026-08-19T00:00:00Z")
        sh = make_clinic_staff_headers()
        get_success_data(api.mark_trapped(appt["id"], cth))
        get_success_data(api.check_in(appt["id"], sh))
        get_success_data(api.create_surgery_record(
            create_surgery_record_payload(
                appt["id"], ear_tipped=False, rabies_vaccinated=False,
                outcome="DIED_IN_SURGERY"), sh))

        assert get_voucher(v1["id"])["status"] == "VOIDED"
        assert get_cat(cat["id"])["status"] == "DECEASED"

    def test_monthly_cap_excludes_voided_vouchers(self, api):
        """PRD §2.8: "`VOIDED` and `EXPIRED` vouchers do not consume the envelope,
        so a caretaker whose voucher died in surgery can re-issue within the same
        month up to the cap."

        Design: Corner/calculations/monthly_cap_excludes_voided_vouchers
        """
        ct, cth, col = setup_caretaker_with_colony(estimated_population=1)
        cat = create_cat(col, intake_tag="V2", approximate_age_months=24)
        clinic = create_partner_clinic(name="VoidVet2", voucher_reimbursement_cents=30000)
        day = create_clinic_day(clinic, service_date="2026-08-20T00:00:00Z",
                                base_capacity=1, surge_capacity=0)
        slots = list_slots(day)
        v1 = create_voucher(ct, face_value_cents=25000)
        appt, _ = book_appointment(cat, slots[0], day["id"], cth,
                                   voucher_id=v1["id"], trap_date="2026-08-19T00:00:00Z")
        sh = make_clinic_staff_headers()
        get_success_data(api.mark_trapped(appt["id"], cth))
        get_success_data(api.check_in(appt["id"], sh))
        get_success_data(api.create_surgery_record(
            create_surgery_record_payload(
                appt["id"], ear_tipped=False, rabies_vaccinated=False,
                outcome="DIED_IN_SURGERY"), sh))
        assert get_voucher(v1["id"])["status"] == "VOIDED"

        resp = api.create_voucher(
            {"caretaker_id": ct["id"], "face_value_cents": 25000,
             "funding_source": "MUNICIPAL_GRANT"},
            make_coordinator_headers())
        validate_success(resp, expected_status=201)


class TestImmediateConsistency:
    def test_immediate_visibility_of_cascade(self, api):
        """PRD §3.4: "The appointment completes (`TRAPPED` to `COMPLETED`), its
        slot is consumed (`BOOKED` to `USED`), the day's `booked_count` decrements
        by one, and a voucher committed on the appointment is redeemed
        (`COMMITTED` to `REDEEMED`)"
        The redemption is visible in the GET immediately following the surgery
        POST.

        Design: Corner/consistency_model/immediate_visibility_of_cascade
        """
        ct, cth, col = setup_caretaker_with_colony(estimated_population=1)
        cat = create_cat(col, intake_tag="IM1", approximate_age_months=24)
        clinic = create_partner_clinic(name="IMVet", voucher_reimbursement_cents=5000)
        day = create_clinic_day(clinic, service_date="2026-09-01T00:00:00Z",
                                base_capacity=1, surge_capacity=0)
        slots = list_slots(day)
        v = create_voucher(ct, face_value_cents=3000)
        appt, _ = book_appointment(cat, slots[0], day["id"], cth,
                                   voucher_id=v["id"], trap_date="2026-08-31T00:00:00Z")
        sh = make_clinic_staff_headers()
        get_success_data(api.mark_trapped(appt["id"], cth))
        get_success_data(api.check_in(appt["id"], sh))
        validate_success(
            api.create_surgery_record(create_surgery_record_payload(appt["id"]), sh),
            expected_status=201)

        voucher = get_voucher(v["id"])
        assert voucher["status"] == "REDEEMED", \
            "voucher must be REDEEMED immediately after the surgery POST"


class TestCascadeUpdatesUpdatedAt:
    def test_cascade_updates_updated_at(self, api):
        """PRD §2.6: "Recomputation is a mutation of the colony even when the
        numbers do not change — `updated_at` is refreshed and `version`
        increments."

        Design: Corner/cross_cutting_layers/cascade_updates_updated_at
        """
        ct, cth, col = setup_caretaker_with_colony(estimated_population=1)
        col_at_creation = get_colony(col["id"])
        cat = create_cat(col, intake_tag="UP1", approximate_age_months=24)
        clinic = create_partner_clinic(name="UPVet", voucher_reimbursement_cents=5000)
        day = create_clinic_day(clinic, service_date="2026-08-31T00:00:00Z",
                                base_capacity=1, surge_capacity=0)
        slots = list_slots(day)
        appt, _ = book_appointment(cat, slots[0], day["id"], cth,
                                   trap_date="2026-08-30T00:00:00Z")
        sh = make_clinic_staff_headers()
        get_success_data(api.mark_trapped(appt["id"], cth))
        get_success_data(api.check_in(appt["id"], sh))

        ch = make_coordinator_headers()
        get_success_data(api.set_clock("2026-08-31T12:00:00Z", ch))
        get_success_data(api.create_surgery_record(
            create_surgery_record_payload(appt["id"]), sh))

        colony_after = get_colony(col["id"])
        assert colony_after["updated_at"] > col_at_creation["updated_at"], \
            (f"colony updated_at must refresh on the surgery cascade: "
             f"before={col_at_creation['updated_at']} after={colony_after['updated_at']}")
