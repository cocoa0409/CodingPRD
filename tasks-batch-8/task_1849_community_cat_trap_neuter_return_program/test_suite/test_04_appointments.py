"""Trapping appointment booking: temporal rules, OCC, ownership, release cycles."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    NON_EXISTENT_UUID,
    make_coordinator_headers, make_clinic_staff_headers,
    setup_caretaker_with_colony, create_caretaker, create_colony, create_cat,
    create_partner_clinic, create_clinic_day, list_slots, get_day, get_slot,
    get_voucher, book_appointment, create_appointment_payload, create_voucher,
    drive_cat_to_post_surgery,
)


class TestTemporalPrecedence:
    """Difficulty/resource_temporal_overlap/trap_date_must_precede_clinic_day_strictly"""

    def test_same_day_trap_date_rejected(self, api):
        """PRD §3.3: "Then the temporal rule: `trap_date` must fall strictly
        before the slot's clinic day `service_date`, else
        `ERR_TEMPORAL_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/trap_date_must_precede_clinic_day_strictly
        """
        ct, cth, col = setup_caretaker_with_colony()
        cat = create_cat(col, intake_tag="TM1", approximate_age_months=24)
        clinic = create_partner_clinic(name="TimeVet")
        day = create_clinic_day(clinic, service_date="2026-08-28T00:00:00Z",
                                base_capacity=1, surge_capacity=0)
        slots = list_slots(day)
        resp = api.create_appointment(
            create_appointment_payload(
                cat["id"], slots[0]["id"], get_day(day["id"])["version"],
                trap_date="2026-08-28T00:00:00Z"),
            cth)
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_CONFLICT, expected_status=422)

    def test_prior_day_trap_date_accepted(self, api):
        """PRD §3.3: "Then the temporal rule: `trap_date` must fall strictly
        before the slot's clinic day `service_date`, else
        `ERR_TEMPORAL_CONFLICT`."
        A trap_date one day before the service date satisfies strict precedence.

        Design: Difficulty/resource_temporal_overlap/trap_date_must_precede_clinic_day_strictly
        """
        ct, cth, col = setup_caretaker_with_colony()
        cat = create_cat(col, intake_tag="TM2", approximate_age_months=24)
        clinic = create_partner_clinic(name="TimeVet2")
        day = create_clinic_day(clinic, service_date="2026-08-28T00:00:00Z",
                                base_capacity=1, surge_capacity=0)
        slots = list_slots(day)
        appt, _ = book_appointment(cat, slots[0], day["id"], cth,
                                   trap_date="2026-08-27T00:00:00Z")
        assert appt["status"] == "SCHEDULED"


class TestBookingDependsOnClinicDayState:
    """Difficulty/cross_entity_state_dependency/appointment_booking_depends_on_clinic_day_state"""

    def test_booking_on_released_slot_after_close_rejected(self, api):
        """PRD §3.2: "Closing a day performs the end-of-day sweep: every `BOOKED`
        slot whose appointment still stands `SCHEDULED` is consumed — the slot
        becomes `USED`, the appointment becomes `NO_SHOW`, a voucher committed on
        such an appointment is released back from `COMMITTED` to `ISSUED`, and the
        cat simply remains `AT_LARGE` — while every remaining `OPEN` slot becomes
        `RELEASED` and the day becomes `COMPLETED`."
        PRD §3.3: "Then state: the slot must stand `OPEN` and its day still
        `SCHEDULED`, else `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/appointment_booking_depends_on_clinic_day_state
        """
        ct, cth, col = setup_caretaker_with_colony()
        cat1 = create_cat(col, intake_tag="G1", approximate_age_months=24)
        cat2 = create_cat(col, intake_tag="G2", sex="FEMALE", approximate_age_months=24)
        clinic = create_partner_clinic(name="GateVet")
        day = create_clinic_day(clinic, service_date="2026-08-06T00:00:00Z",
                                base_capacity=2, surge_capacity=0)
        slots = list_slots(day)
        book_appointment(cat1, slots[0], day["id"], cth,
                         trap_date="2026-08-05T00:00:00Z")
        sh = make_clinic_staff_headers()
        get_success_data(api.close_clinic_day(day["id"], sh))

        assert get_slot(slots[1]["id"], headers=sh)["status"] == "RELEASED"
        resp = api.create_appointment(
            create_appointment_payload(
                cat2["id"], slots[1]["id"], get_day(day["id"])["version"],
                trap_date="2026-08-05T00:00:00Z"),
            cth)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_booking_on_open_slot_of_scheduled_day_accepted(self, api):
        """PRD §3.3: "Then state: the slot must stand `OPEN` and its day still
        `SCHEDULED`, else `ERR_INVALID_STATE`."
        The positive branch: an OPEN slot on a SCHEDULED day admits the booking.

        Design: Difficulty/cross_entity_state_dependency/appointment_booking_depends_on_clinic_day_state
        """
        ct, cth, col = setup_caretaker_with_colony()
        cat = create_cat(col, intake_tag="G3", approximate_age_months=24)
        clinic = create_partner_clinic(name="GateVet2")
        day = create_clinic_day(clinic, service_date="2026-08-06T00:00:00Z",
                                base_capacity=2, surge_capacity=0)
        slots = list_slots(day)
        appt, _ = book_appointment(cat, slots[0], day["id"], cth,
                                   trap_date="2026-08-05T00:00:00Z")
        assert appt["status"] == "SCHEDULED"
        assert get_slot(slots[0]["id"])["status"] == "BOOKED"


class TestStaleVersionOnAppointmentCreate:
    def test_stale_version_on_appointment_create(self, api):
        """PRD §2.9: "Booking a trapping appointment requires the client to submit
        `expected_clinic_day_version`, carrying the `version` of the hosting
        clinic day as the client last observed it; if another booking or release
        has advanced the day's version since that read, the request is rejected
        with `ERR_STALE_VERSION` (HTTP 412), so a client never books against a
        capacity view it has not observed."

        Design: Corner/errors/stale_version_on_appointment_create
        """
        ct, cth, col = setup_caretaker_with_colony()
        cat1 = create_cat(col, intake_tag="ST1", approximate_age_months=24)
        cat2 = create_cat(col, intake_tag="ST2", sex="FEMALE", approximate_age_months=24)
        clinic = create_partner_clinic(name="StaleVet", voucher_reimbursement_cents=5000)
        day = create_clinic_day(clinic, service_date="2026-08-26T00:00:00Z",
                                base_capacity=2, surge_capacity=0)
        slots = list_slots(day)
        stale_version = get_day(day["id"])["version"]

        book_appointment(cat1, slots[0], day["id"], cth,
                         trap_date="2026-08-25T00:00:00Z")

        resp = api.create_appointment(
            create_appointment_payload(
                cat2["id"], slots[1]["id"], stale_version,
                trap_date="2026-08-25T00:00:00Z"),
            cth)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


class TestExistenceBeforeState:
    def test_existence_checked_before_state(self, api):
        """PRD §2.10: "Existence always precedes state: a transition requested
        against a missing resource yields 404, never a state error."

        Design: Corner/validations/existence_checked_before_state
        """
        ct, cth = create_caretaker()
        resp = api.cancel_appointment(NON_EXISTENT_UUID, cth)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestOwnership:
    def test_mark_trapped_by_non_owner_rejected(self, api):
        """PRD §3.3: "the acting caretaker must be the registered caretaker of
        the cat's colony, with a mismatch rejected by `ERR_OWNERSHIP_MISMATCH`"

        Design: Corner/validations/mark_trapped_by_non_owner_rejected
        """
        ct_a, cta_h = create_caretaker(email="owna@x.com")
        ct_b, ctb_h = create_caretaker(email="ownb@x.com")
        col = create_colony(ct_a, name="OA Col")
        cat = create_cat(col, intake_tag="OA1", approximate_age_months=24)
        clinic = create_partner_clinic(name="OwnVet2", voucher_reimbursement_cents=5000)
        day = create_clinic_day(clinic, service_date="2026-08-24T00:00:00Z",
                                base_capacity=1, surge_capacity=0)
        slots = list_slots(day)
        appt, _ = book_appointment(cat, slots[0], day["id"], cta_h,
                                   trap_date="2026-08-23T00:00:00Z")

        resp = api.mark_trapped(appt["id"], ctb_h)
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH, expected_status=403)

    def test_referential_vs_fiscal_on_appointment(self, api):
        """PRD §3.3: "Then ownership: a voucher named on the booking must belong
        to the acting caretaker, else `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."
        PRD §3.3: "Finally the voucher itself must be usable: it must stand
        `ISSUED`, and the clinic hosting the day must accept vouchers, else
        `ERR_VOUCHER_NOT_USABLE` (HTTP 402)."
        Ownership is checked before voucher usability, so a booking committing a
        voucher owned by another caretaker surfaces ERR_OWNERSHIP_MISMATCH even
        when that voucher is also no longer ISSUED.

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_on_appointment
        """
        ct_a, cta_h = create_caretaker(email="an@x.com")
        ct_b, ctb_h = create_caretaker(email="bo@x.com")
        col_a = create_colony(ct_a, name="A Colony")
        cat_a = create_cat(col_a, intake_tag="X1", approximate_age_months=24)
        clinic = create_partner_clinic(name="OwnVet")
        day = create_clinic_day(clinic, service_date="2026-08-21T00:00:00Z",
                                base_capacity=1, surge_capacity=0)
        slot1 = list_slots(day)[0]

        col_b = create_colony(ct_b, name="B Colony")
        cat_b = create_cat(col_b, intake_tag="Y1", sex="FEMALE", approximate_age_months=24)
        v_b = create_voucher(ct_b, face_value_cents=5000)
        day2 = create_clinic_day(clinic, service_date="2026-08-22T00:00:00Z",
                                 base_capacity=1, surge_capacity=0)
        slot2 = list_slots(day2)[0]
        # Drive B's voucher to REDEEMED via a full surgery cycle.
        drive_cat_to_post_surgery(cat_b, ctb_h, day2["id"], slot2,
                                  voucher_id=v_b["id"], trap_date="2026-08-21T00:00:00Z")
        assert get_voucher(v_b["id"])["status"] == "REDEEMED"

        resp = api.create_appointment(
            create_appointment_payload(
                cat_a["id"], slot1["id"], get_day(day["id"])["version"],
                trap_date="2026-08-20T00:00:00Z", voucher_id=v_b["id"]),
            cta_h)
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH, expected_status=403)

    def test_referential_check_fires_for_other_caretakers_issued_voucher(self, api):
        """PRD §3.3: "Then ownership: a voucher named on the booking must belong
        to the acting caretaker, else `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_on_appointment
        """
        ct_a, cta_h = create_caretaker(email="an2@x.com")
        ct_b, ctb_h = create_caretaker(email="bo2@x.com")
        col_a = create_colony(ct_a, name="A2 Colony")
        cat_a = create_cat(col_a, intake_tag="X2", approximate_age_months=24)
        clinic = create_partner_clinic(name="OwnVetB")
        day = create_clinic_day(clinic, service_date="2026-08-21T00:00:00Z",
                                base_capacity=1, surge_capacity=0)
        slot1 = list_slots(day)[0]
        v_b = create_voucher(ct_b, face_value_cents=5000)

        resp = api.create_appointment(
            create_appointment_payload(
                cat_a["id"], slot1["id"], get_day(day["id"])["version"],
                trap_date="2026-08-20T00:00:00Z", voucher_id=v_b["id"]),
            cta_h)
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH, expected_status=403)


class TestVoucherNotUsable:
    def test_voucher_commit_non_issued_rejected(self, api):
        """PRD §3.8: "Commitment happens at booking time per §3.3: the voucher
        must stand `ISSUED` — anything else, or a clinic that does not accept
        vouchers, yields `ERR_VOUCHER_NOT_USABLE`"

        Design: Corner/validations/voucher_commit_non_issued_rejected
        """
        ct, cth, col = setup_caretaker_with_colony()
        cat1 = create_cat(col, intake_tag="NU1", approximate_age_months=24)
        cat2 = create_cat(col, intake_tag="NU2", sex="FEMALE", approximate_age_months=24)
        clinic = create_partner_clinic(name="NUVet", voucher_reimbursement_cents=5000)
        day = create_clinic_day(clinic, service_date="2026-08-25T00:00:00Z",
                                base_capacity=2, surge_capacity=0)
        slots = list_slots(day)
        v1 = create_voucher(ct, face_value_cents=4000)

        drive_cat_to_post_surgery(cat1, cth, day["id"], slots[0],
                                  voucher_id=v1["id"], trap_date="2026-08-24T00:00:00Z")
        assert get_voucher(v1["id"])["status"] == "REDEEMED"

        resp = api.create_appointment(
            create_appointment_payload(
                cat2["id"], slots[1]["id"], get_day(day["id"])["version"],
                trap_date="2026-08-24T00:00:00Z", voucher_id=v1["id"]),
            cth)
        validate_error(resp, ApiErrorId.ERR_VOUCHER_NOT_USABLE, expected_status=402)


class TestVoucherCommitReleaseCycle:
    """Difficulty/non_linear_state_machine/voucher_commit_release_cycle"""

    def test_cancel_releases_voucher_and_slot(self, api):
        """PRD §3.3: "Cancellation releases the slot from `BOOKED` to `RELEASED`,
        decrements the day's `booked_count`, returns a committed voucher from
        `COMMITTED` to `ISSUED`, and marks the appointment `CANCELLED`."

        Design: Difficulty/non_linear_state_machine/voucher_commit_release_cycle
        """
        ct, cth, col = setup_caretaker_with_colony()
        cat = create_cat(col, intake_tag="V1", approximate_age_months=24)
        clinic = create_partner_clinic(name="VetV")
        day = create_clinic_day(clinic, service_date="2026-08-18T00:00:00Z",
                                base_capacity=1, surge_capacity=0)
        slots = list_slots(day)
        v = create_voucher(ct, face_value_cents=9000)
        appt, _ = book_appointment(cat, slots[0], day["id"], cth,
                                   voucher_id=v["id"], trap_date="2026-08-17T00:00:00Z")
        assert get_voucher(v["id"])["status"] == "COMMITTED"

        get_success_data(api.cancel_appointment(appt["id"], cth))

        assert get_voucher(v["id"])["status"] == "ISSUED", \
            "cancellation must return the voucher COMMITTED -> ISSUED"
        assert get_slot(slots[0]["id"])["status"] == "RELEASED"
        assert get_day(day["id"])["booked_count"] == 0

    def test_released_voucher_can_be_committed_again(self, api):
        """PRD §3.8: "Cancellation and the no-show sweep release it back from
        `COMMITTED` to `ISSUED`, and this issue-commit-release cycle may repeat
        any number of times."

        Design: Difficulty/non_linear_state_machine/voucher_commit_release_cycle
        """
        ct, cth, col = setup_caretaker_with_colony()
        cat1 = create_cat(col, intake_tag="VC1", approximate_age_months=24)
        cat2 = create_cat(col, intake_tag="VC2", approximate_age_months=26)
        clinic = create_partner_clinic(name="VetCycle")
        day = create_clinic_day(clinic, service_date="2026-08-18T00:00:00Z",
                                base_capacity=2, surge_capacity=0)
        slots = list_slots(day)
        v = create_voucher(ct, face_value_cents=9000)

        appt1, _ = book_appointment(cat1, slots[0], day["id"], cth,
                                    voucher_id=v["id"], trap_date="2026-08-17T00:00:00Z")
        get_success_data(api.cancel_appointment(appt1["id"], cth))
        assert get_voucher(v["id"])["status"] == "ISSUED"
        # Cancellation moved slots[0] from BOOKED to RELEASED (PRD §3.3), and
        # booking requires an OPEN slot (PRD §3.3), so the cycle repeats on the
        # day's still-OPEN slot.
        appt2, _ = book_appointment(cat2, slots[1], day["id"], cth,
                                    voucher_id=v["id"], trap_date="2026-08-17T00:00:00Z")
        assert appt2["status"] == "SCHEDULED"
        assert get_voucher(v["id"])["status"] == "COMMITTED", \
            "released voucher must be committable again"


class TestBookedCountConservation:
    """Difficulty/compensating_invariant/clinic_day_booked_count_conservation"""

    def test_book_then_cancel_leaves_booked_count_at_zero(self, api):
        """PRD §2.7: "`booked_count` increments by one when a slot is booked and
        decrements by one when a surgery is completed or an appointment is
        cancelled."

        Design: Difficulty/compensating_invariant/clinic_day_booked_count_conservation
        """
        ct, cth, col = setup_caretaker_with_colony()
        cat = create_cat(col, intake_tag="B1", approximate_age_months=24)
        clinic = create_partner_clinic(name="BalVet")
        day = create_clinic_day(clinic, service_date="2026-08-29T00:00:00Z",
                                base_capacity=2, surge_capacity=0)
        slots = list_slots(day)
        appt, _ = book_appointment(cat, slots[0], day["id"], cth,
                                   trap_date="2026-08-28T00:00:00Z")
        assert get_day(day["id"])["booked_count"] == 1

        get_success_data(api.cancel_appointment(appt["id"], cth))
        assert get_day(day["id"])["booked_count"] == 0, \
            "book's +1 must be exactly compensated by cancel's -1"

    def test_booked_count_matches_booked_slot_count(self, api):
        """PRD §2.7: "A clinic day is created with `base_capacity` normal surgery
        slots plus `surge_capacity` additional slots held for the spring kitten
        season; `booked_count` tracks how many of the day's slots currently stand
        `BOOKED`."

        Design: Difficulty/compensating_invariant/clinic_day_booked_count_conservation
        """
        ct, cth, col = setup_caretaker_with_colony()
        cat = create_cat(col, intake_tag="B2", approximate_age_months=24)
        clinic = create_partner_clinic(name="BalVet2")
        day = create_clinic_day(clinic, service_date="2026-08-29T00:00:00Z",
                                base_capacity=2, surge_capacity=0)
        slots = list_slots(day)
        appt, _ = book_appointment(cat, slots[0], day["id"], cth,
                                   trap_date="2026-08-28T00:00:00Z")
        get_success_data(api.cancel_appointment(appt["id"], cth))

        day_after = get_day(day["id"])
        slots_after = list_slots(day_after)
        booked = [s for s in slots_after if s["status"] == "BOOKED"]
        assert len(booked) == day_after["booked_count"] == 0


class TestInvalidTransitions:
    def test_cancel_completed_appointment_invalid(self, api):
        """PRD §3.3: "A caretaker may also cancel an appointment, but only while
        it stands `SCHEDULED` and only for a cat of their own colony"
        PRD §2.10: "then state-transition legality (a transition that does not
        exist from the entity's current state is rejected with
        `ERR_INVALID_STATE`, HTTP 409)"

        Design: Corner/state_machines/cancel_completed_appointment_invalid
        """
        ct, cth, col = setup_caretaker_with_colony()
        cat = create_cat(col, intake_tag="TC1", approximate_age_months=24)
        clinic = create_partner_clinic(name="TermVet", voucher_reimbursement_cents=5000)
        day = create_clinic_day(clinic, service_date="2026-08-14T00:00:00Z",
                                base_capacity=1, surge_capacity=0)
        slots = list_slots(day)
        appt, _, _ = drive_cat_to_post_surgery(cat, cth, day["id"], slots[0],
                                               trap_date="2026-08-13T00:00:00Z")

        resp = api.cancel_appointment(appt["id"], cth)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_slot(slots[0]["id"])["status"] == "USED", \
            "no slot side effects may fire on a rejected cancel"

    def test_double_mark_trapped_idempotency_error(self, api):
        """PRD §3.3: "a repeated or out-of-turn confirmation fails with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/double_mark_trapped_idempotency_error
        """
        ct, cth, col = setup_caretaker_with_colony()
        cat = create_cat(col, intake_tag="ID1", approximate_age_months=24)
        clinic = create_partner_clinic(name="IdemVet", voucher_reimbursement_cents=5000)
        day = create_clinic_day(clinic, service_date="2026-08-18T00:00:00Z",
                                base_capacity=1, surge_capacity=0)
        slots = list_slots(day)
        appt, _ = book_appointment(cat, slots[0], day["id"], cth,
                                   trap_date="2026-08-17T00:00:00Z")
        get_success_data(api.mark_trapped(appt["id"], cth))

        resp = api.mark_trapped(appt["id"], cth)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
