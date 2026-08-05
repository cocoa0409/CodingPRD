"""Registration of patients, coverages and laboratories, plus the identity
checks that sit at the top of the refusal ladder."""

from test_helpers import (
    ApiErrorId,
    anonymous_headers,
    assert_coverage,
    assert_money,
    assert_patient,
    fixtures as fx,
)
from test_helpers import (
    UNKNOWN_ARCH_ID,
    UNKNOWN_CASE_ID,
    UNKNOWN_COVERAGE_ID,
    UNKNOWN_LAB_CASE_ID,
    UNKNOWN_PATIENT_ID,
    UNKNOWN_PROSTHESIS_ID,
    UNKNOWN_REFERENCE_ID,
)
from test_helpers import (
    create_case_payload,
    create_coverage_payload,
    create_lab_payload,
    create_patient_payload,
    is_valid_uuid,
    make_lab_technician_headers,
    make_patient_headers,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


class TestPatientRegistration:
    def test_patient_create_returns_uuid_version_one_and_settled_derived_fields(self, api, front_office_headers):
        """PRD §3.1: "The record is minted with three derived fields already settled
        — `write_gate_active` false, `delivered_prosthesis_count` zero, and
        `last_frequency_anchor_at` null — and the server maintains all three from
        then on."
        PRD §2.4: "`version`: an integer that starts at 1 when the row is created
        and increases by exactly 1 on every mutation of that row."
        PRD §2.4: "`id`: a server-minted UUID. It carries no type prefix; it is a
        bare UUID string. Clients never supply it."

        Design: Corner/entities/create_patient_returns_all_fields_and_system_defaults
        """
        fx.set_clock("2026-05-01T00:00:00Z")

        response = api.create_patient(
            create_patient_payload(
                full_name="Anouk Bergstrom", date_of_birth="1950-02-02", phone="555-1000"
            ),
            front_office_headers,
        )
        patient = validate_success(response, 201)

        assert_patient(patient)
        assert is_valid_uuid(patient["id"]), "the id is a bare uuid with no type prefix"
        assert patient["version"] == 1
        assert patient["write_gate_active"] is False
        assert patient["delivered_prosthesis_count"] == 0
        assert patient["last_frequency_anchor_at"] is None
        assert patient["date_of_birth"] == "1950-02-02", (
            "date_of_birth is a plain calendar date echoed exactly as supplied"
        )

    def test_patient_create_without_phone_is_a_schema_failure(self, api, front_office_headers):
        """PRD §3.1: "Everything begins with a patient record, which a `FrontOffice`
        or `PlatformAdmin` operator registers with three pieces of information:
        `full_name`, `date_of_birth`, and `phone`."
        PRD §2.10: "**Rung 7 — request schema and ranges.** Every required input
        field of the endpoint is present, types match, numeric fields lie inside
        their declared ranges, pagination parameters are in bounds, and declared
        uniqueness pairs are free."

        Design: Corner/entities/missing_required_field_on_patient_create_returns_invalid_request
        """
        fx.set_clock("2026-05-01T00:00:00Z")

        response = api.create_patient(
            {"full_name": "Bo Karlsen", "date_of_birth": "1951-03-03"}, front_office_headers
        )
        validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

        rows, meta = validate_paginated(
            api.list_patients(front_office_headers, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0, "no Patient row is created by the refused request"
        assert rows == []


class TestCoverageEnrolment:
    def test_coverage_omitted_optionals_land_on_their_declared_defaults(self, api, front_office_headers):
        """PRD §3.1: "and may supply six further values, each of which has a default
        the server applies when it is omitted: `annual_maximum_amount` defaults to
        1500.00, `coinsurance_major_rate` defaults to 0.50, `waiting_period_days`
        defaults to 180, `replacement_frequency_months` defaults to 60,
        `cob_convention` defaults to `STANDARD`, and `alternate_benefit_enabled`
        defaults to true."
        PRD §3.1: "A newly enrolled coverage starts with `benefit_used_ytd` at 0.00
        and `benefit_remaining` equal to `annual_maximum_amount`, which is what
        establishes the coverage-benefit conservation described in §2.13."

        Design: Corner/entities/coverage_defaults_applied_when_optional_fields_omitted
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        patient = fx.register_patient(
            full_name="Cai Zhou", date_of_birth="1948-04-04", phone="555-1001"
        )

        response = api.create_coverage(
            create_coverage_payload(
                patient["id"],
                carrier_name="Meridian Dental",
                rank="PRIMARY",
                effective_date="2024-01-01T00:00:00Z",
            ),
            front_office_headers,
        )
        coverage = validate_success(response, 201)

        assert_coverage(coverage)
        assert_money(coverage["annual_maximum_amount"], 1500.00, "annual_maximum_amount")
        assert coverage["coinsurance_major_rate"] == 0.50
        assert coverage["waiting_period_days"] == 180
        assert coverage["replacement_frequency_months"] == 60
        assert coverage["cob_convention"] == "STANDARD"
        assert coverage["alternate_benefit_enabled"] is True
        assert_money(coverage["benefit_used_ytd"], 0.00, "benefit_used_ytd")
        assert_money(coverage["benefit_remaining"], 1500.00, "benefit_remaining")

    def test_second_coverage_at_a_rank_the_patient_already_holds_is_refused(self, api, front_office_headers):
        """PRD §3.1: "A patient may hold one coverage at each rank; a second coverage
        at a rank the patient already holds collides with `ERR_COB_RANK_CONFLICT`
        as described at rung 27."
        PRD §2.10: "rung 7 lists the `patient_id`-and-`rank` pair among its
        uniqueness checks (`ERR_VALIDATION`, HTTP 400), and rung 27 restates the
        same condition as a dedicated coordination-of-benefits check
        (`ERR_COB_RANK_CONFLICT`, HTTP 409). Read strictly by ladder order the
        earlier rung would fire and the later one would be unreachable; read by
        specificity the dedicated rung is exactly what its dedicated code exists
        for. This document records the disagreement rather than resolving it."

        Both readings are admitted by the contract, so the assertion accepts either
        declared outcome and pins only that the duplicate is refused and no second
        coverage row survives.

        Design: Corner/validations/duplicate_primary_coverage_rank_is_rejected
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        patient = fx.register_patient(
            full_name="Freja Osei", date_of_birth="1958-10-02", phone="555-1030"
        )
        fx.enrol_coverage(
            patient["id"],
            carrier_name="Meridian Dental",
            rank="PRIMARY",
            effective_date="2024-01-01T00:00:00Z",
        )

        response = api.create_coverage(
            create_coverage_payload(
                patient["id"],
                carrier_name="Harborline Health",
                rank="PRIMARY",
                effective_date="2025-01-01T00:00:00Z",
            ),
            front_office_headers,
        )
        validate_error_is_one_of(
            response,
            [ApiErrorId.ERR_COB_RANK_CONFLICT.value, ApiErrorId.ERR_VALIDATION.value],
        )

        _, meta = validate_paginated(
            api.list_coverages(
                front_office_headers,
                params={"patient_id": patient["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1, "the patient still holds exactly one coverage"


class TestPathAndBodyResolution:
    def test_unknown_patient_path_segment_uses_the_patient_specific_code(self, api, front_office_headers):
        """PRD §2.9: "a `patient_id` that names no patient yields
        `ERR_PATIENT_NOT_FOUND`;"
        PRD §2.10: "**Rung 4 — path existence.** Every resource named by a path
        segment exists, validated left to right, with the per-entity codes of §2.9."

        Design: Corner/entities/patient_not_found_on_read
        """
        fx.set_clock("2026-05-01T00:00:00Z")

        response = api.get_patient(UNKNOWN_PATIENT_ID, front_office_headers)
        validate_error(response, ApiErrorId.ERR_PATIENT_NOT_FOUND.value, 404)

    def test_unknown_coverage_path_segment_uses_the_generic_code(self, api, front_office_headers):
        """PRD §2.9: "a path segment naming a `Coverage`, `DentalLab`,
        `ImpressionRecord`, `TryInMilestone`, `PostDeliveryService`,
        `WarrantyClaim`, `RemakeRequest`, `Predetermination`, `Claim`,
        `PaymentPlan`, or `Installment` that resolves to no row yields
        `ERR_RESOURCE_NOT_FOUND`."

        Design: Corner/entities/coverage_not_found_uses_generic_resource_error
        """
        fx.set_clock("2026-05-01T00:00:00Z")

        response = api.get_coverage(UNKNOWN_COVERAGE_ID, front_office_headers)
        validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, 404)

    def test_case_arch_lab_case_and_prosthesis_each_carry_their_own_not_found_code(self, api, front_office_headers):
        """PRD §2.9: "a `case_id` that names no case yields `ERR_CASE_NOT_FOUND`;"
        PRD §2.9: "a `case_arch_id` that names no arch yields `ERR_ARCH_NOT_FOUND`;"
        PRD §2.9: "a `lab_case_id` that names no lab case yields
        `ERR_LAB_CASE_NOT_FOUND`;"
        PRD §2.9: "a `prosthesis_id` that names no prosthesis yields
        `ERR_PROSTHESIS_NOT_FOUND`;"

        Design: Corner/entities/case_arch_and_lab_case_and_prosthesis_not_found_use_their_own_codes
        """
        fx.set_clock("2026-05-01T00:00:00Z")

        validate_error(
            api.get_case(UNKNOWN_CASE_ID, front_office_headers),
            ApiErrorId.ERR_CASE_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_case_arch(UNKNOWN_ARCH_ID, front_office_headers),
            ApiErrorId.ERR_ARCH_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_lab_case(UNKNOWN_LAB_CASE_ID, front_office_headers),
            ApiErrorId.ERR_LAB_CASE_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_prosthesis(UNKNOWN_PROSTHESIS_ID, front_office_headers),
            ApiErrorId.ERR_PROSTHESIS_NOT_FOUND.value,
            404,
        )

    def test_body_foreign_key_naming_no_row_uses_the_reference_code(self, api, prosthodontist_headers, front_office_headers):
        """PRD §2.9: "A body field naming a row that does not exist — `patient_id`,
        `case_id`, `case_arch_id`, `dental_lab_id`, `prosthesis_id`, `coverage_id`,
        `warranty_claim_id`, `post_delivery_service_id`, `attributed_lab_case_id`,
        `superseded_prosthesis_id`, or `payment_plan_id` — is refused with
        `ERR_REFERENCE_NOT_FOUND` and HTTP 404, which is a different code from the
        path-segment codes above."

        Design: Corner/entities/body_foreign_key_that_names_no_row_is_rejected
        """
        fx.set_clock("2026-05-01T00:00:00Z")

        response = api.create_case(
            create_case_payload(UNKNOWN_REFERENCE_ID, "COMPLETE_DENTURE"), prosthodontist_headers
        )
        validate_error(response, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value, 404)

        _, meta = validate_paginated(
            api.list_cases(front_office_headers, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0, "no case is opened by the refused request"


class TestIdentityLadder:
    def test_request_without_role_header_is_unauthenticated(self, api):
        """PRD §2.1: "If either header is absent, if `X-User-ID` is empty, or if
        `X-User-Role` does not name one of the six declared roles, the request is
        refused with `ERR_UNAUTHENTICATED` and HTTP 401. This is the first check
        the server performs on any request, ahead of everything else including
        resource lookup."

        Design: Corner/validations/missing_user_role_header_returns_unauthenticated
        """
        fx.set_clock("2026-05-01T00:00:00Z")

        response = api.list_patients(anonymous_headers(), params={"limit": 10, "offset": 0})
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    def test_front_office_cannot_register_a_laboratory(self, api, front_office_headers, platform_admin_headers):
        """PRD §3.1: "External laboratories are registered by a `PlatformAdmin`
        alone, because a laboratory is clinic-wide configuration rather than
        anything belonging to a patient."
        PRD §2.1: "When the headers are well-formed but the named role does not
        appear in the authorised-role list of the endpoint being called (§4 carries
        that list per endpoint), the request is refused with `ERR_FORBIDDEN_ROLE`
        and HTTP 403."

        Design: Corner/validations/front_office_cannot_register_a_laboratory
        """
        fx.set_clock("2026-05-01T00:00:00Z")

        response = api.create_lab(
            create_lab_payload(lab_name="Rogue Lab", bench_line_count=3), front_office_headers
        )
        validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

        _, meta = validate_paginated(
            api.list_labs(platform_admin_headers, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0, "no DentalLab row is created by the refused request"

    def test_patient_reading_another_patients_record_is_not_the_owner(self, api):
        """PRD §2.1: "When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the
        acting `Patient`; ownership checks compare the patient reachable from the
        resource to `X-User-ID`."
        PRD §2.1: "On the first four, a `Patient` caller whose `X-User-ID` is not
        the owning patient is refused. On the fifth, a `LabTechnician` whose
        `X-User-ID` differs from the lab case's `dental_lab_id` is refused. In every
        case the refusal is `ERR_NOT_OWNER` with HTTP 403."

        Design: Corner/validations/patient_cannot_read_another_patients_record
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        patient_a = fx.register_patient(
            full_name="Yara Sultana", date_of_birth="1959-02-26", phone="555-1023"
        )
        patient_b = fx.register_patient(
            full_name="Zoltan Kis", date_of_birth="1960-03-27", phone="555-1024"
        )

        refused = api.get_patient(patient_a["id"], make_patient_headers(patient_b["id"]))
        validate_error(refused, ApiErrorId.ERR_NOT_OWNER.value, 403)

        allowed = api.get_patient(patient_a["id"], make_patient_headers(patient_a["id"]))
        own_row = validate_success(allowed, 200)
        assert own_row["id"] == patient_a["id"], "a patient may read its own row"

    def test_lab_technician_cannot_receive_another_laboratorys_case(self, api):
        """PRD §3.5: "**Receiving** is the laboratory's own act, and only a
        `LabTechnician` whose `X-User-ID` equals the lab case's `dental_lab_id` may
        perform it — anyone else's laboratory identity is refused with
        `ERR_NOT_OWNER`."
        PRD §2.1: "Concretely, a laboratory may only receive a lab case that was
        dispatched to it."

        Design: Corner/validations/lab_technician_cannot_receive_another_labs_case
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        patient = fx.register_patient(
            full_name="Aksel Nyberg", date_of_birth="1947-04-28", phone="555-1025"
        )
        lab_a = fx.register_lab(lab_name="Northgate Dental Lab")
        lab_b = fx.register_lab(
            lab_name="Southbank Ceramics",
            bench_line_count=2,
            standard_turnaround_days=12,
            rush_turnaround_days=5,
        )
        case = fx.open_case(patient["id"], "FLEXIBLE_PARTIAL")
        arch = fx.add_arch(case["id"], "MAXILLARY")
        fx.complete_exam(case["id"])
        fx.start_fabrication(arch["id"])
        fx.accepted_impression(arch["id"], "DIGITAL_SCAN", 90)
        fx.walk_all_milestones(arch["id"], "FLEXIBLE_PARTIAL")
        lab_case = fx.draft_lab_case(arch["id"], lab_a["id"])
        fx.dispatch_lab_case(lab_case["id"])

        response = api.receive_lab_case(lab_case["id"], make_lab_technician_headers(lab_b["id"]))
        validate_error(response, ApiErrorId.ERR_NOT_OWNER.value, 403)

        after = fx.read_lab_case(lab_case["id"])
        assert after["lab_status"] == "DISPATCHED"
        assert after["received_at"] is None

    def test_unknown_prosthesis_type_routes_to_the_enum_code(self, api, prosthodontist_headers, front_office_headers):
        """PRD §2.10: "**Rung 8 — enum membership, exhaustively routed.** A value
        outside the declared member set of any of the following fields routes to
        `ERR_INVALID_ENUM` with HTTP 422, **and only these fields do**:"
        PRD §2.10: "   - `prosthesis_type` on `POST /prosthetics/cases`"

        Design: Corner/validations/unknown_prosthesis_type_returns_invalid_enum
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        patient = fx.register_patient(
            full_name="Bettina Voss", date_of_birth="1953-05-29", phone="555-1026"
        )

        response = api.create_case(
            {"patient_id": patient["id"], "prosthesis_type": "GOLD_CROWN"}, prosthodontist_headers
        )
        validate_error(response, ApiErrorId.ERR_INVALID_ENUM.value, 422)

        _, meta = validate_paginated(
            api.list_cases(
                front_office_headers,
                params={"patient_id": patient["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 0, "no case is opened by the refused request"

    def test_prosthodontist_cannot_adjudicate_a_warranty_claim(self, api, prosthodontist_headers):
        """PRD §2.1: "The `ClinicalDirector` is the authorising clinician. It is the
        only role that may adjudicate a warranty fault or decide a remake request,
        and — by design — it is never permitted to decide a remake it itself
        requested."
        PRD §2.10: "**Rung 2 — role authorisation.** The role named by
        `X-User-Role` appears in the authorised-role list of the endpoint being
        called. Failure: `ERR_FORBIDDEN_ROLE`, HTTP 403. Scope: every endpoint."

        Design: Corner/rbac/prosthodontist_cannot_adjudicate_a_warranty_claim
        """
        ctx = fx.setup_delivered_prosthesis(
            patient_overrides={
                "full_name": "Pekka Rinne", "date_of_birth": "1946-08-12", "phone": "555-1040"
            }
        )
        claim = fx.open_warranty_claim(ctx["prosthesis"]["id"], "Sore spot under the flange")

        response = api.adjudicate_warranty_claim(
            claim["id"], {"fault_verdict": "CLINIC_FAULT"}, prosthodontist_headers
        )
        validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

        assert fx.read_warranty_claim(claim["id"])["claim_status"] == "SUBMITTED"
        assert fx.read_prosthesis(ctx["prosthesis"]["id"])["warranty_status"] == "IN_WARRANTY"

    def test_pagination_limit_above_the_maximum_is_a_schema_failure(self, api, front_office_headers):
        """PRD §2.3: "`limit` defaults to 10 when omitted, has a minimum of 1 and a
        maximum of 100. `offset` defaults to 0 when omitted and has a minimum of 0;
        there is no upper bound on it. A `limit` below 1 or above 100, or a negative
        `offset`, is a request-schema failure and is refused with `ERR_VALIDATION`
        and HTTP 400."

        Design: Corner/endpoints/pagination_limit_above_the_maximum_returns_invalid_request
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        fx.register_patient(
            full_name="Jarno Kuusela", date_of_birth="1948-02-06", phone="555-1034"
        )

        refused = api.list_patients(front_office_headers, params={"limit": 500, "offset": 0})
        validate_error(refused, ApiErrorId.ERR_VALIDATION.value, 400)

        rows, meta = validate_paginated(
            api.list_patients(front_office_headers, params={"limit": 100, "offset": 0})
        )
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(rows) == 1
