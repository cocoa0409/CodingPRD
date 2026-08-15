"""Health center: medication orders, dose ledger, safety rules, segregation."""
import pytest

from test_helpers import (
    TEST_USERS, api_client,
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_medication_order, assert_medication_administration,
    create_medication_order_payload, create_administration_payload,
    make_nurse_headers, make_dean_headers,
    make_parent, make_student, make_nurse, make_dean,
    make_medication_order, record_administration,
)


def _student_and_nurse(grade=9, gender="MALE"):
    parent = make_parent()
    student = make_student(parent["id"], grade=grade, gender=gender)
    nurse = make_nurse("Nurse One")
    return student, nurse


class TestDoseLedgerBoundary:
    def _setup_two_dose_order(self):
        student, nurse = _student_and_nurse(grade=9, gender="FEMALE")
        order = make_medication_order(
            student["id"], nurse["id"], medication_name="Amoxicillin",
            dose_mg=500, slot="EVENING", doses_total=2, refill_threshold=1,
            prescriber_name="Dr B")
        return student, nurse, order

    def test_low_stock_at_threshold_and_auto_complete_at_zero(self, api):
        """PRD §3.6: "The order's `doses_remaining` counts down from `doses_total`
        as administrations are recorded, and `low_stock` turns true when
        `doses_remaining` falls to or below `refill_threshold` — the boundary is
        inclusive." and "When an administered dose brings `doses_remaining` to
        exactly zero, the order flips itself from `ACTIVE` to `COMPLETED`."

        Design: Difficulty/boundary_precision_check/medication_zero_doses_auto_complete_and_reject
        """
        student, nurse, order = self._setup_two_dose_order()
        record_administration(order["id"], nurse["id"], "2026-09-01")

        mid = validate_success(api.get_medication_order(
            order["id"], make_nurse_headers(nurse["id"])), 200)
        assert mid["doses_remaining"] == 1
        assert mid["low_stock"] is True  # 1 <= refill_threshold 1
        assert mid["status"] == "ACTIVE"

        record_administration(order["id"], nurse["id"], "2026-09-02")
        done = validate_success(api.get_medication_order(
            order["id"], make_nurse_headers(nurse["id"])), 200)
        assert done["doses_remaining"] == 0
        assert done["status"] == "COMPLETED"

    def test_administration_on_completed_order_rejected(self, api):
        """PRD §3.6: "An administration attempted on a `DISCONTINUED` or
        `COMPLETED` order is rejected with `ERR_ORDER_NOT_ACTIVE`."

        Design: Difficulty/boundary_precision_check/medication_zero_doses_auto_complete_and_reject
        """
        student, nurse, order = self._setup_two_dose_order()
        record_administration(order["id"], nurse["id"], "2026-09-01")
        record_administration(order["id"], nurse["id"], "2026-09-02")

        res = api.create_administration(
            order["id"],
            create_administration_payload("2026-09-03", "ADMINISTERED"),
            make_nurse_headers(nurse["id"]))
        validate_error(res, ApiErrorId.ERR_ORDER_NOT_ACTIVE)


class TestHoldSafetyPriority:
    def _setup_held_order_with_logged_dose(self):
        student, nurse = _student_and_nurse(grade=9, gender="MALE")
        order = make_medication_order(
            student["id"], nurse["id"], medication_name="Vitamin D",
            dose_mg=1000, slot="MORNING", doses_total=10, prescriber_name="Dr A")
        record_administration(order["id"], nurse["id"], "2026-09-01")
        get_success_data(api_client.hold_medication_order(
            order["id"], "Prescriber review", make_nurse_headers(nurse["id"])))
        return student, nurse, order

    def test_held_order_duplicate_date_surfaces_hold_error(self, api):
        """PRD §3.6: "An administration attempted while the order sits in `HOLD`
        is rejected with `ERR_MEDICATION_ON_HOLD` — a distinct safety error that
        is evaluated before the duplicate-dose uniqueness check, so that a held
        order always surfaces the hold rather than a referential collision."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_held_order_administration
        """
        student, nurse, order = self._setup_held_order_with_logged_dose()
        res = api.create_administration(
            order["id"],
            create_administration_payload("2026-09-01", "ADMINISTERED"),
            make_nurse_headers(nurse["id"]))
        validate_error(res, ApiErrorId.ERR_MEDICATION_ON_HOLD)

    def test_rejected_held_administration_leaves_order_untouched(self, api):
        """PRD §3.6: "Only `ADMINISTERED` rows decrement `doses_remaining`" and
        "An administration attempted while the order sits in `HOLD` is rejected
        with `ERR_MEDICATION_ON_HOLD`".

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_held_order_administration
        """
        student, nurse, order = self._setup_held_order_with_logged_dose()
        validate_error(
            api.create_administration(
                order["id"],
                create_administration_payload("2026-09-01", "ADMINISTERED"),
                make_nurse_headers(nurse["id"])),
            ApiErrorId.ERR_MEDICATION_ON_HOLD)

        fetched = validate_success(api.get_medication_order(
            order["id"], make_nurse_headers(nurse["id"])), 200)
        assert fetched["status"] == "HOLD"
        assert fetched["doses_remaining"] == 9  # only the first dose decremented


class TestOrderDefaultsAndLedgerFiltering:
    def test_default_refill_threshold_applied(self, api):
        """PRD §3.6: "A nurse opens a `MedicationOrder` for an `ENROLLED` student
        with a `medication_name`, a `dose_mg`, a `slot` of `MORNING`, `NOON`,
        `EVENING`, or `BEDTIME`, a `doses_total` of at least 1, an optional
        `refill_threshold` defaulting to 5, an `is_controlled` flag, and the
        `prescriber_name`." and "The order's `doses_remaining` counts down from
        `doses_total` as administrations are recorded".

        Design: Corner/entities/medication_order_default_refill_threshold_applied
        """
        student, nurse = _student_and_nurse(grade=9, gender="FEMALE")
        res = api.create_medication_order(
            create_medication_order_payload(
                student["id"], medication_name="Ibuprofen", dose_mg=200,
                slot="NOON", doses_total=30, is_controlled=False,
                prescriber_name="Dr C"),
            make_nurse_headers(nurse["id"]))
        order = validate_success(res, 201)
        assert_medication_order(order)
        assert order["refill_threshold"] == 5  # default applied
        assert order["doses_remaining"] == 30
        assert order["low_stock"] is False  # 30 > 5

    def test_refused_administration_does_not_decrement(self, api):
        """PRD §3.6: "Only `ADMINISTERED` rows decrement `doses_remaining`;
        refused and held doses leave the count untouched."

        Design: Corner/calculations/medication_refused_does_not_decrement
        """
        student, nurse = _student_and_nurse(grade=9, gender="MALE")
        order = make_medication_order(
            student["id"], nurse["id"], medication_name="Loratadine", dose_mg=10,
            slot="MORNING", doses_total=3, refill_threshold=0,
            prescriber_name="Dr D")
        record_administration(order["id"], nurse["id"], "2026-09-01",
                              outcome="REFUSED", notes="Student declined")

        fetched = validate_success(api.get_medication_order(
            order["id"], make_nurse_headers(nurse["id"])), 200)
        assert fetched["doses_remaining"] == 3
        assert fetched["status"] == "ACTIVE"
        assert fetched["low_stock"] is False  # 3 > 0


class TestAdministrationRules:
    def test_duplicate_dose_same_date_rejected(self, api):
        """PRD §3.6: "at most one administration per order per `scheduled_date`,
        enforced as `ERR_DOSE_ALREADY_LOGGED`".

        Design: Corner/validations/duplicate_dose_rejected_when_order_active
        """
        student, nurse = _student_and_nurse(grade=9, gender="MALE")
        order = make_medication_order(
            student["id"], nurse["id"], medication_name="Ibuprofen", dose_mg=200,
            slot="EVENING", doses_total=10, prescriber_name="Dr F")
        record_administration(order["id"], nurse["id"], "2026-09-01")

        res = api.create_administration(
            order["id"],
            create_administration_payload("2026-09-01", "ADMINISTERED"),
            make_nurse_headers(nurse["id"]))
        validate_error(res, ApiErrorId.ERR_DOSE_ALREADY_LOGGED)

    def test_controlled_order_requires_distinct_active_witness(self, api):
        """PRD §3.6: "For a controlled order (`is_controlled`), an `ADMINISTERED`
        row must carry a `witness_staff_id` naming an active staff member who is
        not the administering nurse; a missing witness, a witness equal to the
        nurse, or an inactive witness is rejected with `ERR_WITNESS_REQUIRED`."

        Design: Corner/validations/controlled_admin_without_witness_rejected
        """
        student, nurse1 = _student_and_nurse(grade=10, gender="FEMALE")
        nurse2 = make_nurse("Nurse Two")
        controlled = make_medication_order(
            student["id"], nurse1["id"], medication_name="Methylphenidate",
            dose_mg=10, slot="MORNING", doses_total=30, is_controlled=True,
            prescriber_name="Dr E")
        plain = make_medication_order(
            student["id"], nurse1["id"], medication_name="Vitamin C",
            dose_mg=500, slot="MORNING", doses_total=30, is_controlled=False,
            prescriber_name="Dr E")

        # Missing witness on a controlled order.
        res1 = api.create_administration(
            controlled["id"],
            create_administration_payload("2026-09-01", "ADMINISTERED"),
            make_nurse_headers(nurse1["id"]))
        validate_error(res1, ApiErrorId.ERR_WITNESS_REQUIRED)

        # Witness equal to the administering nurse.
        res2 = api.create_administration(
            controlled["id"],
            create_administration_payload("2026-09-01", "ADMINISTERED",
                                          witness_staff_id=nurse1["id"]),
            make_nurse_headers(nurse1["id"]))
        validate_error(res2, ApiErrorId.ERR_WITNESS_REQUIRED)

        # Non-controlled order accepts the same shape without a witness.
        ok = validate_success(api.create_administration(
            plain["id"],
            create_administration_payload("2026-09-01", "ADMINISTERED"),
            make_nurse_headers(nurse1["id"])), 201)
        assert_medication_administration(ok)


class TestOrderUniquenessAndState:
    def test_duplicate_active_order_rejected_until_discontinued(self, api):
        """PRD §3.6: "One active order per student, medication, and slot is the
        limit — a second `ACTIVE` order for the same triple is rejected with
        `ERR_DUPLICATE_ACTIVE_ORDER`." and "Discontinuing — from either `ACTIVE`
        or `HOLD`, or by cascade when the student withdraws — moves the order to
        `DISCONTINUED`."

        Design: Corner/validations/duplicate_active_order_rejected
        """
        student, nurse = _student_and_nurse(grade=9, gender="FEMALE")
        order1 = make_medication_order(
            student["id"], nurse["id"], medication_name="Advil", dose_mg=200,
            slot="MORNING", doses_total=20, prescriber_name="Dr G")

        res = api.create_medication_order(
            create_medication_order_payload(
                student["id"], medication_name="Advil", dose_mg=400,
                slot="MORNING", doses_total=10, prescriber_name="Dr G"),
            make_nurse_headers(nurse["id"]))
        validate_error(res, ApiErrorId.ERR_DUPLICATE_ACTIVE_ORDER)

        validate_success(api.discontinue_medication_order(
            order1["id"], make_nurse_headers(nurse["id"])), 200)
        order2 = validate_success(api.create_medication_order(
            create_medication_order_payload(
                student["id"], medication_name="Advil", dose_mg=400,
                slot="MORNING", doses_total=10, prescriber_name="Dr G"),
            make_nurse_headers(nurse["id"])), 201)
        assert_medication_order(order2)

    def test_resume_from_active_returns_invalid_state(self, api):
        """PRD §3.6: "A nurse may place an `ACTIVE` order on `HOLD` with a
        `reason`, which is recorded as `hold_reason`; resuming returns it to
        `ACTIVE`, clears `hold_reason`, and leaves `doses_remaining` untouched."
        PRD §2.6: "the system check whether the target resource sits in a
        legitimate from-state for the requested transition (`ERR_INVALID_STATE`,
        HTTP 409)".

        Design: Corner/state_machines/medication_resume_from_active_returns_invalid_state
        """
        student, nurse = _student_and_nurse(grade=10, gender="MALE")
        order = make_medication_order(
            student["id"], nurse["id"], medication_name="Cetirizine", dose_mg=10,
            slot="MORNING", doses_total=30, prescriber_name="Dr C")
        assert order["status"] == "ACTIVE"

        res = api.resume_medication_order(order["id"], make_nurse_headers(nurse["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestMedicationRbac:
    def test_dean_cannot_administer_medication(self, api):
        """PRD §2.1: "A request whose role is not in the endpoint's authorized
        list, or that violates the ownership and scoping rules below, is rejected
        with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /reslife/medication-orders/{order_id}/administrations is
        authorized for Nurse only.

        Design: Corner/rbac/dean_cannot_administer_medication_forbidden
        """
        student, nurse = _student_and_nurse(grade=9, gender="FEMALE")
        dean = make_dean("Dean One")
        order = make_medication_order(
            student["id"], nurse["id"], medication_name="Ibuprofen", dose_mg=200,
            slot="NOON", doses_total=10, prescriber_name="Dr H")

        res = api.create_administration(
            order["id"],
            create_administration_payload("2026-09-01", "ADMINISTERED"),
            make_dean_headers(dean["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
