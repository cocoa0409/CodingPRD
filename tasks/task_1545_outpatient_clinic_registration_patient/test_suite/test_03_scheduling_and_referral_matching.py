"""Scheduling: derived fields, provider-slot overlap, referral matching, OCC edits."""
from test_helpers import (
    ApiErrorId,
    assert_appointment,
    create_patient_payload,
    create_policy_for,
    create_referral_for,
    create_registered_patient,
    get_success_data,
    schedule_appointment,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

REG = TEST_USERS["registrar_headers"]


class TestAppointmentDerivedFields:
    def test_appointment_derived_fields_on_create(self, api):
        """PRD §3.4: "New appointments enter `SCHEDULED`, and a freshly booked
        visit carries zeroed financials —
        `estimated_patient_responsibility_cents` and `amount_collected_cents`
        both at 0 — with `late_minutes` at 0 until check-in, `auth_satisfied`
        false unless the initial derivation already satisfies it, and
        `registration_gate` beginning at `BLOCKED` until that first clearance
        computation resolves it."
        PRD §3.5: "Third, a referral is needed when the patient's primary
        policy — the non-`VOIDED` policy with `priority_rank` 1 — has a
        `plan_type` of `HMO` or `EPO`."

        Design: Corner/entities/appointment_derived_fields_ignore_client_input
        """
        patient = create_registered_patient(
            first_name="Cmp",
            last_name="Uted",
            date_of_birth="1992-02-02",
            sex_at_birth="M",
            primary_phone="+15551100005",
        )
        create_policy_for(patient["id"], plan_type="HMO")

        res = api.create_appointment(
            {
                "patient_id": patient["id"],
                "department_code": "CARD",
                "procedure_code": "99213",
                "scheduled_start": "2026-08-30T09:00:00Z",
                "duration_minutes": 30,
                "visit_type": "ESTABLISHED",
                "provider_code": "DRZ",
            },
            REG,
        )
        appt = validate_success(res, 201)
        assert_appointment(appt)
        # HMO primary policy with no referral matched -> gate BLOCKED.
        assert appt["registration_gate"] == "BLOCKED"
        assert appt["amount_collected_cents"] == 0
        assert appt["estimated_patient_responsibility_cents"] == 0
        # ESTABLISHED visit needs no authorization -> derivation satisfied.
        assert appt["auth_satisfied"] is True
        assert appt["late_minutes"] == 0
        assert appt["status"] == "SCHEDULED"


class TestProviderSlotOverlap:
    """PRD §3.4 half-open interval overlap protection per provider_code."""

    def _book_first_slot(self, api):
        set_clock("2026-08-01T00:00:00Z")
        p1 = get_success_data(
            api.create_patient(
                create_patient_payload(
                    first_name="Ov",
                    last_name="One",
                    date_of_birth="1986-06-16",
                    sex_at_birth="M",
                    primary_phone="+15559000001",
                ),
                REG,
            )
        )
        a1 = schedule_appointment(
            p1["id"],
            scheduled_start="2026-08-27T09:00:00Z",
            duration_minutes=30,
            provider_code="DRX",
        )
        p2 = get_success_data(
            api.create_patient(
                create_patient_payload(
                    first_name="Ov",
                    last_name="Two",
                    date_of_birth="1987-07-17",
                    sex_at_birth="F",
                    primary_phone="+15559000002",
                ),
                REG,
            )
        )
        return p1, p2, a1

    def test_provider_touching_intervals_do_not_overlap(self, api):
        """PRD §3.4: "Two appointments that are both live — each in
        `SCHEDULED`, `PRE_CHECKED`, `READY`, `ARRIVED`, or `IN_ROOM` — may not
        overlap for the same `provider_code`, where an appointment occupies the
        interval from its `scheduled_start` up to but not including its
        `scheduled_start` plus `duration_minutes`."
        PRD §3.4: "Intervals that merely touch, one beginning exactly when the
        other ends, do not overlap."

        Design: Difficulty/resource_temporal_overlap/provider_slot_touching_intervals_do_not_overlap
        """
        _, p2, _ = self._book_first_slot(api)
        res = api.create_appointment(
            {
                "patient_id": p2["id"],
                "department_code": "ORTHO",
                "procedure_code": "99213",
                "scheduled_start": "2026-08-27T09:30:00Z",
                "duration_minutes": 30,
                "visit_type": "ESTABLISHED",
                "provider_code": "DRX",
            },
            REG,
        )
        appt = validate_success(res, 201)
        assert appt["scheduled_start"].startswith("2026-08-27T09:30")

    def test_provider_one_minute_overlap_rejected(self, api):
        """PRD §3.4: "A colliding booking is rejected with
        `ERR_PROVIDER_DOUBLE_BOOKED` (HTTP 409), and the overlap check is
        evaluated before temporal sanity: a slot that collides surfaces
        `ERR_PROVIDER_DOUBLE_BOOKED` even when its start would also fail the
        date rule."

        Design: Difficulty/resource_temporal_overlap/provider_slot_touching_intervals_do_not_overlap
        """
        _, p2, _ = self._book_first_slot(api)
        res = api.create_appointment(
            {
                "patient_id": p2["id"],
                "department_code": "ORTHO",
                "procedure_code": "99213",
                "scheduled_start": "2026-08-27T09:29:00Z",
                "duration_minutes": 30,
                "visit_type": "ESTABLISHED",
                "provider_code": "DRX",
            },
            REG,
        )
        validate_error(res, ApiErrorId.ERR_PROVIDER_DOUBLE_BOOKED)


class TestReferralMatching:
    def _hmo_patient_with_card_referral(self, api):
        set_clock("2026-08-01T00:00:00Z")
        patient = create_registered_patient(
            first_name="Win",
            last_name="Dow",
            date_of_birth="1988-08-18",
            sex_at_birth="F",
            primary_phone="+15559000003",
        )
        create_policy_for(patient["id"], plan_type="HMO", payer_id="PAYERH", member_id="MW")
        referral = create_referral_for(
            patient["id"],
            referring_provider_npi="NPI888",
            specialty_code="CARD",
            procedure_code="99213",
            visits_authorized=5,
            valid_from="2026-08-01",
            valid_until="2026-08-31",
        )
        return patient, referral

    def test_referral_matches_on_valid_until_date(self, api):
        """PRD §3.3: "The candidate set for an appointment comprises the
        patient's `OPEN` referrals whose `specialty_code` equals the
        appointment's `department_code`, whose `procedure_code` equals the
        appointment's `procedure_code`, whose validity window contains the
        appointment's scheduled date — `valid_from` on or before that date and
        `valid_until` on or after it — and which still show `visits_consumed`
        below `visits_authorized`."

        Design: Difficulty/resource_temporal_overlap/referral_validity_date_window_inclusive
        """
        patient, referral = self._hmo_patient_with_card_referral(api)
        res = api.create_appointment(
            {
                "patient_id": patient["id"],
                "referring_provider_npi": "NPI888",
                "department_code": "CARD",
                "procedure_code": "99213",
                "scheduled_start": "2026-08-31T09:00:00Z",
                "duration_minutes": 30,
                "visit_type": "ESTABLISHED",
                "provider_code": "DRP",
            },
            REG,
        )
        appt = validate_success(res, 201)
        assert appt["referral_id"] == referral["id"]

    def test_referral_day_after_valid_until_stays_unmatched(self, api):
        """PRD §3.3: "An empty candidate set is not an error — `referral_id`
        simply stays null, though the clearance gate may remain `BLOCKED` as a
        consequence."
        PRD §3.5: "when demographics, authorization, and referral are not all
        satisfied, `registration_gate` is `BLOCKED`"

        Design: Difficulty/resource_temporal_overlap/referral_validity_date_window_inclusive
        """
        patient, _ = self._hmo_patient_with_card_referral(api)
        res = api.create_appointment(
            {
                "patient_id": patient["id"],
                "referring_provider_npi": "NPI888",
                "department_code": "CARD",
                "procedure_code": "99213",
                "scheduled_start": "2026-09-01T09:00:00Z",
                "duration_minutes": 30,
                "visit_type": "ESTABLISHED",
                "provider_code": "DRQ",
            },
            REG,
        )
        appt = validate_success(res, 201)
        assert appt["referral_id"] is None
        assert appt["registration_gate"] == "BLOCKED"

    def test_referral_matching_prefers_npi_match(self, api):
        """PRD §3.3: "Candidates are ranked lexicographically: a referral whose
        `referring_provider_npi` matches the appointment's
        `referring_provider_npi` outranks one that does not; ties break toward
        the earliest `valid_until`; remaining ties break toward the oldest
        `created_at`."

        Design: Corner/calculations/referral_matching_prefers_npi_then_earliest_expiry
        """
        patient = create_registered_patient(
            first_name="Mat",
            last_name="Ch",
            date_of_birth="1993-03-13",
            sex_at_birth="M",
            primary_phone="+15551300007",
        )
        r1 = create_referral_for(
            patient["id"],
            referring_provider_npi="NPI555",
            specialty_code="CARD",
            procedure_code="99213",
            visits_authorized=3,
            valid_from="2026-08-01",
            valid_until="2026-09-30",
        )
        create_referral_for(
            patient["id"],
            referring_provider_npi="NPI666",
            specialty_code="CARD",
            procedure_code="99213",
            visits_authorized=3,
            valid_from="2026-08-01",
            valid_until="2026-08-20",
        )
        res = api.create_appointment(
            {
                "patient_id": patient["id"],
                "referring_provider_npi": "NPI555",
                "department_code": "CARD",
                "procedure_code": "99213",
                "scheduled_start": "2026-08-15T09:00:00Z",
                "duration_minutes": 30,
                "visit_type": "ESTABLISHED",
                "provider_code": "DRMT",
            },
            REG,
        )
        appt = validate_success(res, 201)
        assert appt["referral_id"] == r1["id"]


class TestAppointmentOccEdit:
    def test_patch_appointment_stale_version_rejected(self, api):
        """PRD §2.7: "Rescheduling or editing an appointment
        (`PATCH /patient-access/appointments/{id}`) requires the request body
        to carry `expected_appointment_version`, holding the appointment
        `version` the client last observed."
        PRD §2.7: "In both cases, if the supplied value does not match the
        resource's current `version` — meaning the record has advanced since
        the client's last read, for example because a clearance cascade
        recomputed the appointment after a policy termination or referral
        match — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_patch_appointment_stale_version
        """
        patient = get_success_data(
            api.create_patient(
                create_patient_payload(
                    first_name="Occ",
                    last_name="One",
                    date_of_birth="1987-07-07",
                    sex_at_birth="M",
                    primary_phone="+15551700001",
                ),
                REG,
            )
        )
        appt = schedule_appointment(
            patient["id"], scheduled_start="2026-09-25T09:00:00Z", provider_code="DROC"
        )
        v1 = appt["version"]
        updated = validate_success(
            api.update_appointment(
                appt["id"],
                {"expected_appointment_version": v1, "duration_minutes": 45},
                REG,
            ),
            200,
        )
        v2 = updated["version"]

        stale = api.update_appointment(
            appt["id"],
            {"expected_appointment_version": v2 - 1, "duration_minutes": 60},
            REG,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        ok = validate_success(
            api.update_appointment(
                appt["id"],
                {"expected_appointment_version": v2, "duration_minutes": 60},
                REG,
            ),
            200,
        )
        assert ok["duration_minutes"] == 60
