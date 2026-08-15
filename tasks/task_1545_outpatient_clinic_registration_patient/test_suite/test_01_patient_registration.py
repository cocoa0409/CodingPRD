"""Patient registration, duplicate prevention, merge, and roster listing."""
import re

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_patient,
    complete_registration_payload,
    create_patient_payload,
    create_policy_for,
    get_success_data,
    merge_patient_payload,
    schedule_appointment,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

REG = TEST_USERS["registrar_headers"]
SUP = TEST_USERS["access_supervisor_headers"]


class TestPatientCreationDefaults:
    def test_patient_create_assigns_mrn_and_default_status(self, api):
        """PRD §3.1: "On acceptance the server mints the patient's `mrn` — the
        literal prefix "MRN" followed by a zero-padded eight-digit sequence —
        which is unique per patient and immutable once assigned, and the record
        enters `PRE_REGISTERED` status."
        PRD §3.1: "`email` is optional, and `language_code` records the
        patient's preferred ISO 639-1 language, defaulting to `en` and later
        driving the interpreter-flag default."

        Design: Corner/entities/patient_create_assigns_mrn_and_default_status
        """
        res = api.create_patient(
            create_patient_payload(
                first_name="Def",
                last_name="Ault",
                date_of_birth="1995-01-05",
                sex_at_birth="F",
                primary_phone="+15551100001",
            ),
            REG,
        )
        patient = validate_success(res, 201)
        assert_patient(patient)
        assert re.fullmatch(r"MRN\d{8}", patient["mrn"]), (
            f"mrn must be 'MRN' + zero-padded 8-digit sequence, got {patient['mrn']!r}"
        )
        assert patient["status"] == "PRE_REGISTERED"
        assert patient["language_code"] == "en"

    def test_patient_get_not_found_returns_404(self, api):
        """PRD §2.9: "the server confirms the existence of each referenced
        identifier in order, and the first identifier that does not resolve to
        an existing resource rejects the request with `ERR_NOT_FOUND` (HTTP 404)
        before any later path segment or body reference is examined."

        Design: Corner/entities/patient_get_not_found_returns_404
        """
        res = api.get_patient(NON_EXISTENT_UUID, REG)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_patient_list_pagination_envelope(self, api):
        """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the response envelope."
        PRD §2.3: "`limit` sets the maximum number of items returned: it
        defaults to 10, with a minimum of 1 and a maximum of 100."

        Design: Corner/entities/patient_list_pagination_envelope
        """
        for i, (sex, dob) in enumerate(
            [("M", "1990-01-01"), ("F", "1990-01-02"), ("X", "1990-01-03")]
        ):
            create_res = api.create_patient(
                create_patient_payload(
                    first_name="Pg",
                    last_name=f"Listee{i}",
                    date_of_birth=dob,
                    sex_at_birth=sex,
                ),
                REG,
            )
            validate_success(create_res, 201)

        res = api.list_patients(REG, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(res)
        body = res.json()
        assert body["response_type"] == "array"
        assert isinstance(meta.get("api_request_id"), str)
        assert isinstance(meta.get("api_request_timestamp"), str)
        assert meta["total_count"] == 3
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["has_more"] is True
        assert len(data) == 2


class TestDuplicatePreventionAndValidation:
    def test_duplicate_patient_rejected_on_demographic_triple(self, api):
        """PRD §3.1: "When an existing patient whose status is anything other
        than `MERGED` matches the newcomer on the exact triple of `first_name`,
        `last_name`, and `date_of_birth`, or matches on `primary_phone` alone,
        the create is rejected with `ERR_DUPLICATE_PATIENT` (HTTP 409)."

        Design: Corner/validations/duplicate_patient_rejected_on_demographic_triple
        """
        first = api.create_patient(
            create_patient_payload(
                first_name="Dup",
                last_name="Licate",
                date_of_birth="1980-12-01",
                sex_at_birth="F",
                primary_phone="+15551400001",
            ),
            REG,
        )
        validate_success(first, 201)

        res = api.create_patient(
            create_patient_payload(
                first_name="Dup",
                last_name="Licate",
                date_of_birth="1980-12-01",
                sex_at_birth="F",
                primary_phone="+15551400099",
            ),
            REG,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_PATIENT)

    def test_missing_primary_phone_rejected(self, api):
        """PRD §2.10: "Independently of that ordering, a request that is
        structurally malformed — a required field missing, a value of the wrong
        type, an unrecognized enumeration value — is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "A `Registrar` opens the patient journey with
        pre-registration, supplying `first_name`, `last_name`, `date_of_birth`
        as an ISO calendar date in YYYY-MM-DD form, `sex_at_birth` as one of
        `M`, `F`, or `X`, and an E.164-formatted `primary_phone`"

        Design: Corner/errors/err_invalid_request_on_missing_required_field
        """
        payload = {
            "first_name": "Mis",
            "last_name": "Sing",
            "date_of_birth": "1990-01-01",
            "sex_at_birth": "M",
        }
        res = api.create_patient(payload, REG)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_interpreter_flag_requires_language_code(self, api):
        """PRD §3.1: "an `INTERPRETER` flag must carry a `language_code`, and
        omitting it is rejected with `ERR_LANGUAGE_REQUIRED` (HTTP 400), while
        other flag types may leave `language_code` null."

        Design: Corner/validations/interpreter_flag_requires_language_code
        """
        patient = get_success_data(
            api.create_patient(
                create_patient_payload(
                    first_name="Lang",
                    last_name="Uage",
                    date_of_birth="1981-01-21",
                    sex_at_birth="M",
                    primary_phone="+15551400002",
                ),
                REG,
            )
        )
        bad = api.create_accommodation_flag(patient["id"], {"flag_type": "INTERPRETER"}, REG)
        validate_error(bad, ApiErrorId.ERR_LANGUAGE_REQUIRED)

        good = api.create_accommodation_flag(
            patient["id"], {"flag_type": "INTERPRETER", "language_code": "es"}, REG
        )
        flag = validate_success(good, 201)
        assert flag["flag_type"] == "INTERPRETER"
        assert flag["language_code"] == "es"


class TestInsurancePolicyValidation:
    def test_priority_rank_conflict_rejected(self, api):
        """PRD §3.2: "Coordination of benefits is expressed through
        `priority_rank`, an integer of at least 1 where 1 designates the
        primary policy and 2 the secondary; the rank must be unique among the
        patient's policies that are not `VOIDED`, otherwise the create fails
        with `ERR_PRIORITY_RANK_CONFLICT` (HTTP 409)."

        Design: Corner/validations/priority_rank_conflict_rejected
        """
        patient = get_success_data(
            api.create_patient(
                create_patient_payload(
                    first_name="Rank",
                    last_name="One",
                    date_of_birth="1982-02-22",
                    sex_at_birth="F",
                    primary_phone="+15551400003",
                ),
                REG,
            )
        )
        first = api.create_insurance_policy(
            {
                "patient_id": patient["id"],
                "payer_id": "PAYER1",
                "member_id": "MRK1",
                "plan_type": "PPO",
                "effective_start": "2026-01-01",
                "priority_rank": 1,
                "deductible_remaining_cents": 0,
                "oop_max_remaining_cents": 500000,
            },
            REG,
        )
        validate_success(first, 201)

        conflict = api.create_insurance_policy(
            {
                "patient_id": patient["id"],
                "payer_id": "PAYER2",
                "member_id": "MRK2",
                "plan_type": "MEDICARE",
                "effective_start": "2026-01-01",
                "priority_rank": 1,
                "deductible_remaining_cents": 0,
                "oop_max_remaining_cents": 500000,
            },
            REG,
        )
        validate_error(conflict, ApiErrorId.ERR_PRIORITY_RANK_CONFLICT)

    def test_invalid_date_range_rejected(self, api):
        """PRD §3.2: "Coverage runs from `effective_start` inclusive through
        `effective_end` inclusive; `effective_end` may be null for open-ended
        coverage, but when present it must not fall before `effective_start`,
        and a violation is rejected with `ERR_INVALID_DATE_RANGE` (HTTP 400)."

        Design: Corner/validations/invalid_date_range_rejected
        """
        patient = get_success_data(
            api.create_patient(
                create_patient_payload(
                    first_name="Date",
                    last_name="Range",
                    date_of_birth="1985-05-25",
                    sex_at_birth="M",
                    primary_phone="+15551400006",
                ),
                REG,
            )
        )
        res = api.create_insurance_policy(
            {
                "patient_id": patient["id"],
                "payer_id": "PAYER1",
                "member_id": "MDR",
                "plan_type": "PPO",
                "effective_start": "2026-06-01",
                "effective_end": "2026-01-01",
                "priority_rank": 1,
                "deductible_remaining_cents": 0,
                "oop_max_remaining_cents": 500000,
            },
            REG,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_DATE_RANGE)


class TestPatientMerge:
    def test_merge_repoints_appointments_to_survivor(self, api):
        """PRD §3.1: "A successful merge stamps the duplicate's
        `duplicate_of_patient_id` with the survivor's id, moves the duplicate
        to the terminal `MERGED` status, increments its `version` by one,
        re-points every appointment of the duplicate in `SCHEDULED`,
        `PRE_CHECKED`, or `READY` to the survivor with clearance recomputed on
        each, re-points every insurance policy of the duplicate to the
        survivor, and re-runs referral matching on the moved appointments."

        Design: Corner/endpoints/merge_repoints_appointments_to_survivor
        """
        # Survivor: REGISTERED.
        survivor = get_success_data(
            api.create_patient(
                create_patient_payload(
                    first_name="Sur",
                    last_name="Vivor",
                    date_of_birth="1980-08-08",
                    sex_at_birth="M",
                    primary_phone="+15551600002",
                ),
                REG,
            )
        )
        get_success_data(
            api.complete_registration(survivor["id"], complete_registration_payload(), REG)
        )
        # Duplicate: distinct demographics so creation is not blocked; the
        # merge precondition only requires a different non-MERGED survivor.
        duplicate = get_success_data(
            api.create_patient(
                create_patient_payload(
                    first_name="Sur",
                    last_name="Vivorr",
                    date_of_birth="1980-08-08",
                    sex_at_birth="M",
                    primary_phone="+15551600003",
                ),
                REG,
            )
        )
        create_policy_for(duplicate["id"])
        appt = schedule_appointment(
            duplicate["id"], scheduled_start="2026-09-20T09:00:00Z", provider_code="DRMG"
        )

        merged = validate_success(
            api.merge_patient(
                duplicate["id"],
                merge_patient_payload(survivor["id"], duplicate["version"]),
                REG,
            ),
            200,
        )
        assert merged["status"] == "MERGED"
        assert merged["duplicate_of_patient_id"] == survivor["id"]

        moved_appt = validate_success(api.get_appointment(appt["id"], REG), 200)
        assert moved_appt["patient_id"] == survivor["id"]

        policies, meta = validate_paginated(api.list_patient_policies(survivor["id"], REG))
        assert meta["total_count"] == 1
        assert len(policies) == 1
        assert policies[0]["patient_id"] == survivor["id"]

    def test_merge_with_stale_patient_version_rejected(self, api):
        """PRD §2.7: "Merging a patient
        (`POST /patient-access/patients/{id}/merge`) requires
        `expected_patient_version`, holding the patient `version` the registrar
        last read."
        PRD §2.7: "In both cases, if the supplied value does not match the
        resource's current `version` — meaning the record has advanced since
        the client's last read, for example because a clearance cascade
        recomputed the appointment after a policy termination or referral
        match — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_merge_stale_patient_version
        """
        survivor = get_success_data(
            api.create_patient(
                create_patient_payload(
                    first_name="Mrg",
                    last_name="Sur",
                    date_of_birth="1988-08-08",
                    sex_at_birth="F",
                    primary_phone="+15551700002",
                ),
                REG,
            )
        )
        get_success_data(
            api.complete_registration(survivor["id"], complete_registration_payload(), REG)
        )
        duplicate = get_success_data(
            api.create_patient(
                create_patient_payload(
                    first_name="Mrg",
                    last_name="Dup",
                    date_of_birth="1989-09-09",
                    sex_at_birth="F",
                    primary_phone="+15551700003",
                ),
                REG,
            )
        )
        stale_version = duplicate["version"]
        # An intervening write advances the duplicate's version.
        get_success_data(
            api.complete_registration(duplicate["id"], complete_registration_payload(), REG)
        )

        res = api.merge_patient(
            duplicate["id"],
            merge_patient_payload(survivor["id"], stale_version),
            REG,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
