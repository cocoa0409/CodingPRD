"""Referral intake: creation validation, defaults, identity forcing, initial state."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, is_valid_uuid,
    NON_EXISTENT_UUID, ApiErrorId,
    create_referral_payload, create_patient_payload,
    create_plan, create_provider, create_patient, set_clock,
    create_referral, get_referral,
    make_referring_provider_headers,
    assert_referral, assert_patient, assert_instant_equals,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["network_admin_headers"]


def _bootstrap_plan_provider_patient():
    plan = create_plan()
    provider = create_provider()
    patient = create_patient(plan["id"])
    return plan, provider, patient


class TestReferralCreationValidation:
    def test_missing_urgency_rejected(self, api):
        """PRD §3.3: "A `ReferringProvider` creates a referral order by posting the
        `patient_id`, the target `specialty` (one of the five enumerated specialties),
        a free-text `diagnosis_code`, an `urgency` of `STAT`, `URGENT`, or `ROUTINE`..."
        PRD §2.7: "Fourth, request shape — required fields present, types valid, enum
        members valid, datetime and date formats well-formed (priority 4,
        `ERR_INVALID_REQUEST`)."

        Design: Corner/entities/referral_create_missing_required_urgency_rejected
        """
        plan, provider, patient = _bootstrap_plan_provider_patient()
        payload = create_referral_payload(patient["id"])
        del payload["urgency"]
        res = api.create_referral(payload, make_referring_provider_headers(provider["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        data, meta = validate_paginated(
            api.list_referrals(make_referring_provider_headers(provider["id"]))
        )
        assert data == [] and meta["total_count"] == 0, (
            "A rejected creation must not persist a referral"
        )

    def test_invalid_urgency_enum_rejected(self, api):
        """PRD §3.3: "an `urgency` of `STAT`, `URGENT`, or `ROUTINE`".
        PRD §2.7: "Fourth, request shape — required fields present, types valid, enum
        members valid, datetime and date formats well-formed (priority 4,
        `ERR_INVALID_REQUEST`)."

        Design: Corner/entities/referral_create_invalid_enum_rejected
        """
        plan, provider, patient = _bootstrap_plan_provider_patient()
        payload = create_referral_payload(patient["id"], urgency="STATT")
        res = api.create_referral(payload, make_referring_provider_headers(provider["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_bogus_patient_reference_not_found(self, api):
        """PRD §2.7: "Fifth, existence: path resource ids are validated left to right,
        then body foreign-key references in their declared input order (priority 5 —
        the 404 family such as `ERR_REFERRAL_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`,
        `ERR_SPECIALIST_NOT_FOUND`, ...)."

        Design: Corner/entities/referral_create_bogus_patient_returns_not_found
        """
        provider = create_provider()
        payload = create_referral_payload(NON_EXISTENT_UUID)
        res = api.create_referral(payload, make_referring_provider_headers(provider["id"]))
        validate_error(res, ApiErrorId.ERR_PATIENT_NOT_FOUND, expected_status=404)


class TestReferralDefaultsAndIdentity:
    def test_defaults_applied_and_provider_identity_forced(self, api):
        """PRD §3.3: "optionally an `insurance_plan_id` (defaulting to the patient's
        own plan when omitted), and optionally an `in_network_preference` flag
        (defaulting to true) documenting the patient's stated network preference."
        PRD §3.3: "The `referring_provider_id` is never accepted from the payload — it
        is set from the caller's `X-User-ID`, so a provider can only author referrals
        under their own identity."
        PRD §3.5: "(the initial value before documentation is `NONE`)".

        Design: Corner/entities/referral_create_defaults_applied
        """
        plan, provider, patient = _bootstrap_plan_provider_patient()
        res = api.create_referral(
            create_referral_payload(patient["id"]),
            make_referring_provider_headers(provider["id"]),
        )
        referral = validate_success(res, 201)
        assert_referral(referral)
        assert referral["in_network_preference"] is True
        assert referral["insurance_plan_id"] == plan["id"], (
            "insurance_plan_id must default to the patient's own plan"
        )
        assert referral["patient_choice_documented"] is False
        assert referral["patient_choice_type"] == "NONE"
        assert referral["referring_provider_id"] == provider["id"], (
            "referring_provider_id is forced from X-User-ID, never from the payload"
        )

    def test_initial_states_on_create(self, api):
        """PRD §3.3: "A new referral begins in `PENDING_TRIAGE` status with
        `auth_status` set to `NOT_EVALUATED`."
        PRD §2.4: "`version`, an integer starting at 1 that increments by exactly 1
        on every mutation of that resource."
        PRD §3.6: "its `ever_scheduled` flag is set true — it is never cleared
        afterward" (on booking; a fresh referral has never been booked).

        Design: Corner/state_machines/referral_initial_states_on_create
        """
        plan, provider, patient = _bootstrap_plan_provider_patient()
        res = api.create_referral(
            create_referral_payload(patient["id"]),
            make_referring_provider_headers(provider["id"]),
        )
        referral = validate_success(res, 201)
        assert referral["status"] == "PENDING_TRIAGE"
        assert referral["auth_status"] == "NOT_EVALUATED"
        assert referral["ever_scheduled"] is False
        assert referral["leaked"] is False
        assert referral["out_of_network"] is False
        assert referral["version"] == 1


class TestReferralRead:
    def test_get_nonexistent_referral_returns_404(self, api):
        """PRD §2.7: "Fifth, existence: path resource ids are validated left to right
        ... (priority 5 — the 404 family such as `ERR_REFERRAL_NOT_FOUND`, ...)".
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/entities/referral_get_not_found_returns_404
        """
        res = api.get_referral(NON_EXISTENT_UUID, COORD)
        validate_error(res, ApiErrorId.ERR_REFERRAL_NOT_FOUND, expected_status=404)
        body = res.json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["data"].get("message"), str) and body["data"]["message"]

    def test_age_days_computed_from_logical_clock(self, api):
        """PRD §3.3: "Every referral read exposes `age_days`, the whole number of
        calendar days between `created_at` and now, computed as the floor of the
        elapsed seconds divided by 86,400 and evaluated fresh at read time in UTC."
        PRD §3.3: "Accepting moves it to `ACCEPTED` and performs three bookkeeping
        steps: `triaged_at` is stamped with the current clock; `sla_due_at` is
        computed as `triaged_at` plus the urgency's service-level window ..."
        (so before accept, sla_due_at is unset).

        Design: Corner/entities/referral_age_days_computed_from_clock
        """
        set_clock("2026-08-01T00:00:00Z")
        plan, provider, patient = _bootstrap_plan_provider_patient()
        referral = create_referral(provider["id"], patient["id"])
        set_clock("2026-08-04T00:00:00Z")

        read = validate_success(api.get_referral(referral["id"], COORD))
        assert read["age_days"] == 3, (
            f"created 2026-08-01, read at 2026-08-04 -> floor(3d) == 3; got {read['age_days']}"
        )
        assert read["sla_due_at"] is None, "sla_due_at is null until the referral is accepted"


class TestPatientRegistration:
    def test_client_supplied_id_ignored_and_clock_default_stamped(self, api):
        """PRD §2.4: "Most persisted resources carry four system-maintained
        properties: `id`, a server-minted UUID with no type prefix; `created_at`, an
        ISO 8601 UTC timestamp with three fractional digits recorded at creation;
        ... and `version`, an integer starting at 1 that increments by exactly 1 on
        every mutation of that resource."
        PRD §2.4: "At startup the clock reads exactly `2026-08-01T00:00:00Z`; it stays
        there until advanced."

        Design: Corner/entities/patient_create_client_id_input_ignored
        """
        plan = create_plan()
        payload = create_patient_payload(plan["id"])
        payload["id"] = "client-supplied"
        res = api.create_patient(payload, ADMIN)
        patient = validate_success(res, 201)
        assert_patient(patient)
        assert patient["id"] != "client-supplied"
        assert is_valid_uuid(patient["id"]), "id must be a server-minted UUID"
        assert patient["version"] == 1
        assert_instant_equals(
            patient["created_at"], "2026-08-01T00:00:00Z",
            label="patient.created_at (logical clock default)",
        )


class TestValidationPriorityOnCreate:
    def test_role_check_beats_shape_on_referral_create(self, api):
        """PRD §2.7: "Second, whether the role is permitted on the endpoint (priority
        2, `ERR_UNAUTHORIZED_ROLE`). ... Fourth, request shape — required fields
        present, types valid, enum members valid, datetime and date formats
        well-formed (priority 4, `ERR_INVALID_REQUEST`)."
        PRD §4: POST /referrals is authorized for ReferringProvider only.

        Design: Corner/validations/role_check_beats_shape_on_referral_create
        """
        plan = create_plan()
        patient = create_patient(plan["id"])
        payload = create_referral_payload(patient["id"])
        del payload["urgency"]  # malformed body, but role check fires first
        res = api.create_referral(payload, COORD)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

    def test_shape_beats_existence_on_referral_create(self, api):
        """PRD §2.7: "Fourth, request shape — required fields present, types valid,
        enum members valid, datetime and date formats well-formed (priority 4,
        `ERR_INVALID_REQUEST`). Fifth, existence: path resource ids are validated left
        to right, then body foreign-key references in their declared input order
        (priority 5 — the 404 family ...)."

        Design: Corner/validations/shape_beats_existence_on_referral_create
        """
        provider = create_provider()
        payload = create_referral_payload(NON_EXISTENT_UUID, urgency="STATT")
        res = api.create_referral(payload, make_referring_provider_headers(provider["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
