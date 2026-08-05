"""Booking the patient in, the receiving-screening clock and the intake compliance gate."""

from test_helpers import (
    ApiErrorId,
    UNKNOWN_INMATE_ID,
    UNKNOWN_RECORD_ID,
    UNKNOWN_REFERRAL_ID,
    assert_inmate,
    assert_intake_screening,
    assert_same_instant,
    book_inmate_payload,
    fixtures as fx,
    medication_order_payload,
    validate_error,
    validate_success,
)


class TestBookingDefaults:
    def test_booking_initializes_custody_records_balance_and_version(self, api, intake_officer_headers):
        """PRD §3.1: "Booking initializes the row deterministically: `custody_status` is
        `IN_CUSTODY`, `records_state` is `OPEN`, `account_balance_cents` is 0, and
        `version` is 1."

        Design: Corner/entities/inmate_creation_returns_defaults_and_system_fields
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        resp = api.create_inmate(
            book_inmate_payload(
                booking_number="C-2000",
                full_name="Ora Pike",
                facility_code="FAC-01",
                custody_level="MEDIUM",
                booked_at="2026-05-01T00:00:00Z",
            ),
            intake_officer_headers,
        )
        data = validate_success(resp, 201)
        assert_inmate(data)
        assert data["custody_status"] == "IN_CUSTODY"
        assert data["records_state"] == "OPEN"
        assert data["account_balance_cents"] == 0
        assert data["version"] == 1

    def test_booking_defaults_admission_type_and_reads_as_indigent(self, api, intake_officer_headers):
        """PRD §3.1: "`admission_type` says how the patient arrived and defaults to
        `NEW_BOOKING` when omitted, the alternative being `INTER_FACILITY_TRANSFER`."
        PRD §3.1: "because a freshly booked patient has no ledger entries at all, the
        derivation falls back to a zero balance, which is below the indigency threshold,
        so a newly booked inmate always reads as indigent."

        Design: Corner/entities/inmate_creation_returns_defaults_and_system_fields
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        resp = api.create_inmate(
            book_inmate_payload(
                booking_number="C-2000B",
                full_name="Ora Pike",
                booked_at="2026-05-01T00:00:00Z",
            ),
            intake_officer_headers,
        )
        data = validate_success(resp, 201)
        assert data["admission_type"] == "NEW_BOOKING"
        assert data["indigent_flag"] is True

    def test_booking_without_full_name_is_a_payload_failure(self, api, intake_officer_headers):
        """PRD §3.1: "The booking payload carries a `booking_number`, which must be
        non-empty and unique across every inmate ever booked — a repeat is rejected with
        `ERR_DUPLICATE_KEY` (409) — together with the patient's `full_name`, the
        `facility_code` of the holding facility, and a `custody_level` of `MINIMUM`,
        `MEDIUM` or `MAXIMUM`."
        PRD §2.5: "**Payload shape.** Required fields present and non-null, then declared
        JSON types and numeric ranges, then enum membership. The first two yield
        `ERR_VALIDATION` (400); enum membership yields `ERR_INVALID_ENUM` (422)."

        Design: Corner/entities/inmate_missing_required_field_rejected
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        payload = {
            "booking_number": "C-2001",
            "facility_code": "FAC-01",
            "custody_level": "MEDIUM",
            "booked_at": "2026-05-01T00:00:00Z",
        }
        resp = api.create_inmate(payload, intake_officer_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 400)

    def test_booking_with_out_of_set_custody_level_is_an_enum_failure(self, api, intake_officer_headers):
        """PRD §2.5: "Enum membership is checked on every enum-typed field this API
        accepts, which is the full set `custody_level`, `admission_type`, `screening_type`,
        `severity`, `condition_code`, `acuity`, `encounter_type`, `drug_class`,
        `route_mode`, `urgency`, `specialty`, `decision`, `peer_decision`, `outcome`,
        `release_type`, `manner`, `entry_type`, `cancel_reason` and `escort_level`; a value
        outside the field's declared set is `ERR_INVALID_ENUM` even though a missing or
        wrongly-typed value on the same field would have been `ERR_VALIDATION`."

        Design: Corner/entities/inmate_invalid_enum_custody_level_rejected
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        resp = api.create_inmate(
            book_inmate_payload(
                booking_number="C-2002",
                full_name="Pia Quist",
                custody_level="SUPERMAX",
                booked_at="2026-05-01T00:00:00Z",
            ),
            intake_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value, 422)

    def test_repeat_booking_number_is_rejected_as_a_duplicate_key(self, api, intake_officer_headers):
        """PRD §3.1: "The booking payload carries a `booking_number`, which must be
        non-empty and unique across every inmate ever booked — a repeat is rejected with
        `ERR_DUPLICATE_KEY` (409) — together with the patient's `full_name`, the
        `facility_code` of the holding facility, and a `custody_level` of `MINIMUM`,
        `MEDIUM` or `MAXIMUM`."

        Design: Corner/entities/inmate_duplicate_booking_number_rejected
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        fx.book_inmate(
            booking_number="C-2003", full_name="Remy Salas", booked_at="2026-05-01T00:00:00Z"
        )
        resp = api.create_inmate(
            book_inmate_payload(
                booking_number="C-2003",
                full_name="Different Person",
                facility_code="FAC-02",
                custody_level="MINIMUM",
                booked_at="2026-05-01T00:00:00Z",
            ),
            intake_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY.value, 409)


class TestNotFoundFamilies:
    def test_unknown_inmate_id_reports_the_inmate_specific_404(self, api, admin_headers):
        """PRD §2.10: "Path parameters are resolved strictly left to right, and the first
        segment that fails to resolve determines the error, which means an inmate that does
        not exist is reported as `ERR_INMATE_NOT_FOUND` (404) before anything nested under
        that inmate is even looked up."

        Design: Corner/entities/inmate_get_unknown_id_not_found
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        resp = api.get_inmate(UNKNOWN_INMATE_ID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_INMATE_NOT_FOUND.value, 404)

    def test_unknown_medication_order_reports_the_generic_record_404(self, api, provider_headers):
        """PRD §2.10: "Referral-family records — specialty referrals, utilization reviews
        and transport orders — report `ERR_REFERRAL_RECORD_NOT_FOUND` (404) when missing;
        every other sub-resource — intake screenings, chronic-care enrollments, sick-call
        requests, medication orders, medication administrations, co-pay charges, grievances,
        release plans and mortality reviews — reports `ERR_RECORD_NOT_FOUND` (404)."

        Design: Corner/entities/medication_order_unknown_id_record_not_found
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        resp = api.discontinue_medication_order(UNKNOWN_RECORD_ID, provider_headers)
        validate_error(resp, ApiErrorId.ERR_RECORD_NOT_FOUND.value, 404)

    def test_unknown_utilization_review_reports_the_referral_family_404(
        self, api, utilization_reviewer_headers
    ):
        """PRD §2.10: "Referral-family records — specialty referrals, utilization reviews
        and transport orders — report `ERR_REFERRAL_RECORD_NOT_FOUND` (404) when missing;
        every other sub-resource — intake screenings, chronic-care enrollments, sick-call
        requests, medication orders, medication administrations, co-pay charges, grievances,
        release plans and mortality reviews — reports `ERR_RECORD_NOT_FOUND` (404)."

        Design: Corner/entities/specialty_referral_unknown_id_referral_record_not_found
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        resp = api.decide_utilization_review(
            UNKNOWN_REFERRAL_ID, {"decision": "APPROVE"}, utilization_reviewer_headers
        )
        validate_error(resp, ApiErrorId.ERR_REFERRAL_RECORD_NOT_FOUND.value, 404)


class TestIntakeClock:
    def test_receiving_screening_is_still_pending_at_its_due_instant_and_overdue_one_second_later(
        self, api, provider_headers
    ):
        """PRD §3.1: "For a `RECEIVING` screening on a `NEW_BOOKING` patient, `due_at` is
        `booked_at` plus 12 hours."
        PRD §3.1: "The overdue determination is strict. Whenever a `HealthServicesAdmin`
        advances the logical clock, the first sweep step moves every `PENDING` screening
        whose `due_at` falls strictly before the new clock instant into `OVERDUE`; a
        screening whose `due_at` equals the new instant exactly is still on time."

        Design: Corner/state_machines/intake_screening_overdue_sweep_boundary_and_downstream_gate
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2040",
            full_name="Van Willis",
            booked_at="2026-05-01T00:00:00Z",
            admission_type="NEW_BOOKING",
        )
        screening = fx.open_screening(inmate["id"], "RECEIVING")
        assert_intake_screening(screening)
        assert_same_instant(screening["due_at"], "2026-05-01T12:00:00Z", "screening.due_at")

        fx.set_clock("2026-05-01T12:00:00Z")
        at_boundary = fx.read_screening(inmate["id"], screening["id"])
        assert at_boundary["status"] == "PENDING", "due_at == clock is still on time"

        fx.set_clock("2026-05-01T12:00:01Z")
        past_boundary = fx.read_screening(inmate["id"], screening["id"])
        assert past_boundary["status"] == "OVERDUE"
        assert_same_instant(
            past_boundary["due_at"], "2026-05-01T12:00:00Z", "due_at is never recomputed"
        )

    def test_overdue_receiving_screening_gates_medication_ordering(self, api, provider_headers):
        """PRD §3.1: "While an inmate holds any intake screening whose `screening_type` is
        `RECEIVING` and whose status is `OVERDUE`, three operations are refused with
        `ERR_INTAKE_SCREENING_OVERDUE` (422) at rung 11: writing a medication order,
        requesting a specialty referral, and enrolling the patient in chronic care."

        Design: Corner/state_machines/intake_screening_overdue_sweep_boundary_and_downstream_gate
        """
        inmate, screening = fx.setup_inmate_with_overdue_receiving_screening(
            booking_number="C-2041", full_name="Van Willis", admission_type="NEW_BOOKING"
        )
        assert screening["status"] == "OVERDUE"
        resp = api.create_medication_order(
            medication_order_payload(
                inmate["id"],
                fx.inmate_version(inmate["id"]),
                start_date="2026-05-02T00:00:00Z",
                end_date="2026-05-10T00:00:00Z",
            ),
            provider_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INTAKE_SCREENING_OVERDUE.value, 422)

    def test_transfer_restarts_the_receiving_clock_on_the_four_hour_fuse(self, api):
        """PRD §3.1: "For a `RECEIVING` screening on an `INTER_FACILITY_TRANSFER` patient
        the clock also restarts, but on a materially shorter fuse: `booked_at` plus 4 hours,
        because a transferred patient arrives with unknown en-route care."

        Design: Corner/state_machines/intake_transfer_preserves_full_assessment_clock
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2050",
            full_name="Wes Yoon",
            booked_at="2026-05-01T00:00:00Z",
            admission_type="INTER_FACILITY_TRANSFER",
            prior_full_assessment_at="2026-04-20T00:00:00Z",
        )
        screening = fx.open_screening(inmate["id"], "RECEIVING")
        assert_same_instant(screening["due_at"], "2026-05-01T04:00:00Z", "receiving due_at")

    def test_transfer_with_documented_prior_assessment_preserves_the_full_assessment_clock(self, api):
        """PRD §3.1: "But an `INTER_FACILITY_TRANSFER` patient who arrives with a documented
        `prior_full_assessment_at` keeps the sending facility's clock rather than restarting
        it: their `due_at` is `prior_full_assessment_at` plus 14 days."

        Design: Corner/state_machines/intake_transfer_preserves_full_assessment_clock
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2051",
            full_name="Wes Yoon",
            booked_at="2026-05-01T00:00:00Z",
            admission_type="INTER_FACILITY_TRANSFER",
            prior_full_assessment_at="2026-04-20T00:00:00Z",
        )
        screening = fx.open_screening(inmate["id"], "FULL_ASSESSMENT")
        assert_same_instant(
            screening["due_at"], "2026-05-04T00:00:00Z", "full-assessment due_at"
        )

    def test_full_assessment_completed_after_its_deadline_is_flagged_late(self, api, nurse_headers):
        """PRD §3.1: "For a `FULL_ASSESSMENT`, a `NEW_BOOKING` patient — or any patient
        whose `prior_full_assessment_at` is null, regardless of admission type — gets
        `booked_at` plus 14 days."
        PRD §3.1: "Completing sets `completed_at` to the current clock instant and then sets
        `completed_late` by comparing the two: true when `completed_at` is strictly after
        `due_at`, false when `completed_at` is at or before `due_at`."

        Design: Corner/state_machines/intake_screening_disposition_completed_late_flag
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2060",
            full_name="Xan Zhu",
            booked_at="2026-05-01T00:00:00Z",
            admission_type="NEW_BOOKING",
        )
        screening = fx.open_screening(inmate["id"], "FULL_ASSESSMENT")
        assert_same_instant(screening["due_at"], "2026-05-15T00:00:00Z", "due_at")

        fx.set_clock("2026-05-15T00:00:01Z")
        resp = api.dispose_intake_screening(
            screening["id"],
            {"disposition": "COMPLETED", "findings_code": "CHRONIC_CONDITION"},
            nurse_headers,
        )
        data = validate_success(resp, 200)
        assert data["status"] == "COMPLETED"
        assert data["findings_code"] == "CHRONIC_CONDITION"
        assert data["completed_late"] is True
        assert_same_instant(data["completed_at"], "2026-05-15T00:00:01Z", "completed_at")

    def test_completing_a_full_assessment_reanchors_prior_full_assessment_at(self, api, nurse_headers):
        """PRD §3.1: "When the completed instrument was the `FULL_ASSESSMENT`, the parent
        inmate's `prior_full_assessment_at` is set to that same `completed_at`, so a full
        assessment done here becomes the anchor a subsequent transfer would inherit."

        Design: Corner/state_machines/intake_screening_disposition_completed_late_flag
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2061",
            full_name="Xan Zhu",
            booked_at="2026-05-01T00:00:00Z",
            admission_type="NEW_BOOKING",
        )
        screening = fx.open_screening(inmate["id"], "FULL_ASSESSMENT")
        fx.set_clock("2026-05-15T00:00:01Z")
        validate_success(
            api.dispose_intake_screening(
                screening["id"],
                {"disposition": "COMPLETED", "findings_code": "NO_FINDINGS"},
                nurse_headers,
            ),
            200,
        )
        refreshed = fx.read_inmate(inmate["id"])
        assert_same_instant(
            refreshed["prior_full_assessment_at"],
            "2026-05-15T00:00:01Z",
            "inmate.prior_full_assessment_at",
        )
