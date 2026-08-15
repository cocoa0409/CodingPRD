"""Rehabilitation plans, practitioner care appointments, and OCC on plans."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    appointment_payload, rehabilitation_plan_payload,
    make_veterinarian_headers, make_farrier_headers,
    intake_horse, get_horse, complete_medical_pass, clear_active_protocol,
    release_horse, register_vet, register_farrier, create_rehab_plan,
    book_appointment, setup_released_horse, setup_application_home_check_passed,
)

INTAKE = TEST_USERS["intake_headers"]
DIRECTOR = TEST_USERS["director_headers"]


class TestPractitionerBufferOverlap:
    def test_appointment_14_min_gap_rejected(self):
        """PRD §3.2: "against every existing `REQUESTED` or `CONFIRMED` appointment
        of the same practitioner, the new half-open interval may neither overlap
        nor sit closer than fifteen minutes away — back-to-back slots with a
        fifteen-minute-or-longer gap are fine, anything tighter fails with
        `ERR_APPOINTMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/practitioner_half_open_buffer_overlap
        """
        vet_id = register_vet()
        horse = intake_horse()  # QUARANTINE: VET_EXAM bookings permitted
        book_appointment(horse["id"], vet_id, service_type="VET_EXAM",
                         scheduled_start="2026-08-02T09:00:00Z",
                         scheduled_end="2026-08-02T10:00:00Z")
        resp = api_client.create_care_service_appointment(
            appointment_payload(horse["id"], vet_id, service_type="VET_EXAM",
                                scheduled_start="2026-08-02T10:14:00Z",
                                scheduled_end="2026-08-02T11:00:00Z"),
            INTAKE)
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_OVERLAP, 422)

    def test_appointment_15_min_gap_accepted(self):
        """PRD §3.2: "against every existing `REQUESTED` or `CONFIRMED` appointment
        of the same practitioner, the new half-open interval may neither overlap
        nor sit closer than fifteen minutes away — back-to-back slots with a
        fifteen-minute-or-longer gap are fine, anything tighter fails with
        `ERR_APPOINTMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/practitioner_half_open_buffer_overlap
        """
        vet_id = register_vet()
        horse = intake_horse()
        book_appointment(horse["id"], vet_id, service_type="VET_EXAM",
                         scheduled_start="2026-08-02T09:00:00Z",
                         scheduled_end="2026-08-02T10:00:00Z")
        ok = validate_success(api_client.create_care_service_appointment(
            appointment_payload(horse["id"], vet_id, service_type="VET_EXAM",
                                scheduled_start="2026-08-02T10:15:00Z",
                                scheduled_end="2026-08-02T11:00:00Z"),
            INTAKE), 201)
        assert ok["status"] == "REQUESTED"


class TestPractitionerDeactivationCascade:
    def test_practitioner_deactivation_cancels_appointments(self):
        """PRD §3.2: "Deactivating a practitioner — flipping `active` from true to
        false, which the same update endpoint can do alongside `name` changes —
        immediately cancels every appointment of theirs still in `REQUESTED` or
        `CONFIRMED`, with `cancellation_reason` recorded as
        `PRACTITIONER_INACTIVE`."

        Design: Corner/state_machines/practitioner_deactivation_cancels_appointments
        """
        farrier_id = register_farrier()
        bundle = setup_released_horse("REHABILITATION",
                                      {"name": "H", "sex": "GELDING", "age_years": 9})
        horse = bundle["horse"]
        farrier_headers = make_farrier_headers(farrier_id)

        a1 = book_appointment(horse["id"], farrier_id, service_type="FARRIER_TRIM",
                              scheduled_start="2026-08-16T09:00:00Z",
                              scheduled_end="2026-08-16T09:45:00Z")
        get_success_data(api_client.confirm_care_service_appointment(
            a1["id"], farrier_headers))
        a1_done = get_success_data(api_client.complete_care_service_appointment(
            a1["id"], {"actual_cost_cents": 4500}, farrier_headers))
        assert a1_done["status"] == "COMPLETED"
        assert a1_done["billing_status"] == "BILLED"

        a2 = book_appointment(horse["id"], farrier_id, service_type="FARRIER_SHOEING",
                              scheduled_start="2026-08-18T09:00:00Z",
                              scheduled_end="2026-08-18T10:00:00Z")
        get_success_data(api_client.confirm_care_service_appointment(
            a2["id"], farrier_headers))

        a3 = book_appointment(horse["id"], farrier_id, service_type="FARRIER_TRIM",
                              scheduled_start="2026-08-20T09:00:00Z",
                              scheduled_end="2026-08-20T09:45:00Z")

        get_success_data(api_client.patch_practitioner(
            farrier_id, {"active": False}, DIRECTOR))

        a1_after = validate_success(
            api_client.get_care_service_appointment(a1["id"], INTAKE))
        assert a1_after["status"] == "COMPLETED", "terminal rows untouched"
        for appt_id in (a2["id"], a3["id"]):
            after = validate_success(
                api_client.get_care_service_appointment(appt_id, INTAKE))
            assert after["status"] == "CANCELLED"
            assert after["cancellation_reason"] == "PRACTITIONER_INACTIVE"


class TestRehabPlanGatingAndFeeBonus:
    def test_plan_completion_blocked_by_open_appointment(self):
        """PRD §3.2: "Completion (`ACTIVE` → `COMPLETED`) is refused while any
        appointment linked to the plan through `rehab_plan_id` remains `REQUESTED`
        or `CONFIRMED` — surfaced as `ERR_PLAN_HAS_OPEN_APPOINTMENTS`."

        Design: Corner/state_machines/rehab_plan_visit_gating_and_fee_bonus
        """
        vet_id = register_vet()
        bundle = setup_released_horse(
            "REHABILITATION",
            {"name": "H", "sex": "GELDING", "age_years": 9,
             "body_condition_score": 4, "training_level": "TRAINED_RIDDEN"},
            vet_id=vet_id)
        horse = bundle["horse"]
        plan = create_rehab_plan(horse["id"], vet_id, goals="weight gain",
                                 target_body_condition_score=6, planned_weeks=8)
        get_success_data(api_client.activate_rehabilitation_plan(
            plan["id"], make_veterinarian_headers(vet_id)))
        appt = book_appointment(
            horse["id"], vet_id, service_type="VET_PROCEDURE",
            scheduled_start="2026-08-16T09:00:00Z",
            scheduled_end="2026-08-16T10:00:00Z", rehab_plan_id=plan["id"])
        get_success_data(api_client.confirm_care_service_appointment(
            appt["id"], make_veterinarian_headers(vet_id)))

        resp = api_client.complete_rehabilitation_plan(
            plan["id"], make_veterinarian_headers(vet_id))
        validate_error(resp, ApiErrorId.ERR_PLAN_HAS_OPEN_APPOINTMENTS, 422)

    def test_visit_credit_and_rehab_fee_bonus(self):
        """PRD §3.2: "A plan's `completed_visit_count` starts at 0 and climbs by
        one each time a linked appointment completes."
        PRD §3.4: "then adds a 5000-cent rehabilitation bonus if and only if the
        horse has a rehabilitation plan in `COMPLETED`."

        Design: Corner/state_machines/rehab_plan_visit_gating_and_fee_bonus
        """
        vet_id = register_vet()
        bundle = setup_released_horse(
            "REHABILITATION",
            {"name": "H", "sex": "GELDING", "age_years": 9,
             "body_condition_score": 4, "training_level": "TRAINED_RIDDEN"},
            vet_id=vet_id)
        horse = bundle["horse"]
        plan = create_rehab_plan(horse["id"], vet_id, goals="weight gain",
                                 target_body_condition_score=6, planned_weeks=8)
        get_success_data(api_client.activate_rehabilitation_plan(
            plan["id"], make_veterinarian_headers(vet_id)))
        appt = book_appointment(
            horse["id"], vet_id, service_type="VET_PROCEDURE",
            scheduled_start="2026-08-16T09:00:00Z",
            scheduled_end="2026-08-16T10:00:00Z", rehab_plan_id=plan["id"])
        get_success_data(api_client.confirm_care_service_appointment(
            appt["id"], make_veterinarian_headers(vet_id)))

        done = get_success_data(api_client.complete_care_service_appointment(
            appt["id"], {"actual_cost_cents": 7500},
            make_veterinarian_headers(vet_id)))
        assert done["billing_status"] == "BILLED"

        plan_after = get_success_data(api_client.get_rehabilitation_plan(
            plan["id"], make_veterinarian_headers(vet_id)))
        assert plan_after["completed_visit_count"] == 1

        completed = get_success_data(api_client.complete_rehabilitation_plan(
            plan["id"], make_veterinarian_headers(vet_id)))
        assert completed["status"] == "COMPLETED"

        graduated = get_success_data(api_client.graduate_rehabilitation(
            horse["id"], make_veterinarian_headers(vet_id)))
        assert graduated["status"] == "ADOPTABLE"

        # Fee: 85000 (age 9) + 15000 (TRAINED_RIDDEN) + 5000 (rehab bonus).
        app_bundle = setup_application_home_check_passed(
            horse_bundle={"horse": get_horse(horse["id"]), "vet_id": vet_id},
            pickup="2026-08-25T00:00:00Z")
        approved = validate_success(api_client.approve_application(
            app_bundle["application"]["id"], TEST_USERS["officer_2_headers"]))
        assert approved["quoted_fee_cents"] == 105000


class TestBookingGates:
    def test_quarantine_service_restriction(self):
        """PRD §3.2: "While the horse is `QUARANTINE`, only `VET_EXAM` may be
        booked, else `ERR_QUARANTINE_SERVICE_RESTRICTED`."

        Design: Corner/validations/quarantine_service_restriction
        """
        vet_id = register_vet()
        farrier_id = register_farrier()
        horse = intake_horse()
        resp = api_client.create_care_service_appointment(
            appointment_payload(horse["id"], farrier_id,
                                service_type="FARRIER_TRIM",
                                scheduled_start="2026-08-02T09:00:00Z",
                                scheduled_end="2026-08-02T09:45:00Z"),
            INTAKE)
        validate_error(resp, ApiErrorId.ERR_QUARANTINE_SERVICE_RESTRICTED, 422)

        ok = validate_success(api_client.create_care_service_appointment(
            appointment_payload(horse["id"], vet_id, service_type="VET_EXAM",
                                scheduled_start="2026-08-02T10:00:00Z",
                                scheduled_end="2026-08-02T10:45:00Z"),
            INTAKE), 201)
        assert ok["status"] == "REQUESTED"

    def test_service_specialty_mismatch(self):
        """PRD §3.2: "The service family must match the practitioner's specialty —
        the veterinary services `VET_EXAM`, `VET_PROCEDURE`, and `DENTAL` require
        a `VETERINARIAN`, while `FARRIER_TRIM` and `FARRIER_SHOEING` require a
        `FARRIER` — else `ERR_SERVICE_SPECIALTY_MISMATCH`."

        Design: Corner/errors/service_specialty_mismatch
        """
        bundle = setup_released_horse("REHABILITATION",
                                      {"sex": "GELDING", "age_years": 9})
        vet_id = bundle["vet_id"]
        resp = api_client.create_care_service_appointment(
            appointment_payload(bundle["horse"]["id"], vet_id,
                                service_type="FARRIER_TRIM",
                                scheduled_start="2026-08-16T09:00:00Z",
                                scheduled_end="2026-08-16T09:45:00Z"),
            INTAKE)
        validate_error(resp, ApiErrorId.ERR_SERVICE_SPECIALTY_MISMATCH, 422)


class TestRehabPlanOptimisticConcurrency:
    def test_occ_rehab_plan_stale_version(self):
        """PRD §2.6: "If the supplied value does not equal the horse's current
        `version` at the moment of the write, the request is rejected as stale
        with `ERR_STALE_HORSE_VERSION` (HTTP 412): the caller's view predates the
        latest plan supersession — or some other horse mutation — and must be
        refreshed before retrying."
        PRD §3.2: "Creating the new plan supersedes whichever of the horse's
        existing plans sits in `DRAFT` or `ACTIVE`, moving it to `SUPERSEDED`, and
        bumps the horse's `version`; the new plan itself begins in `DRAFT`."

        Design: Corner/cross_cutting_layers/occ_rehab_plan_stale_version
        """
        vet_id = register_vet()
        bundle = setup_released_horse("REHABILITATION",
                                      {"age_years": 9, "body_condition_score": 4},
                                      vet_id=vet_id)
        horse = get_horse(bundle["horse"]["id"])
        vet_headers = make_veterinarian_headers(vet_id)
        stale_version = horse["version"]

        plan_a = get_success_data(api_client.create_rehabilitation_plan(
            rehabilitation_plan_payload(horse["id"], stale_version,
                                        goals="plan A", planned_weeks=8),
            vet_headers))

        resp = api_client.create_rehabilitation_plan(
            rehabilitation_plan_payload(horse["id"], stale_version,
                                        goals="plan B stale", planned_weeks=6),
            vet_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_HORSE_VERSION, 412)

        fresh_version = get_horse(horse["id"])["version"]
        plan_b = get_success_data(api_client.create_rehabilitation_plan(
            rehabilitation_plan_payload(horse["id"], fresh_version,
                                        goals="plan B fresh", planned_weeks=6),
            vet_headers))
        assert plan_b["status"] == "DRAFT"

        plan_a_after = get_success_data(
            api_client.get_rehabilitation_plan(plan_a["id"], vet_headers))
        assert plan_a_after["status"] == "SUPERSEDED"
