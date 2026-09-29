"""Entity surfaces: creation, retrieval, defaults, computed fields, listing and immutability."""

import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    assertions,
    factories,
    fixtures,
    make_bursar_headers,
    make_compliance_auditor_headers,
    make_partner_account_lead_headers,
    make_provost_headers,
)

DEFAULT_REQUIRED_DOMAINS = [
    "MARKETING",
    "LEAD_GENERATION",
    "ENROLLMENT_COUNSELING",
    "COURSE_DESIGN",
    "STUDENT_ADVISING",
    "ACCESSIBILITY_ACCOMMODATIONS",
]


@pytest.fixture
def clock_at_default(api):
    fixtures.set_clock(api, fixtures.CLOCK_AUG_1)


class TestPartnershipRegistration:
    def test_registration_returns_a_draft_row_with_the_derived_expiry_date(
        self, api, clock_at_default, admin_headers
    ):
        """An 84-month term from 2026-08-01 expires the day before the anniversary.

        PRD: "The server derives `expiry_date` as the day one day before the date that falls
        `term_months` months after `effective_date`, and recomputes it whenever either
        `effective_date` or `term_months` changes."
        PRD: "Most resources additionally carry an `updated_at` timestamp, refreshed on every
        mutation including mutations the server performs on its own initiative, and a `version`
        integer that starts at 1 on creation and increments by one on every mutation."

        Design: Corner/entities/partnership_create_returns_draft_row_with_computed_expiry
        """
        response = api.create_partnership(factories.partnership_payload(), headers=admin_headers)
        partnership = validate_success(response, 201)

        assert partnership["status"] == "DRAFT"
        assert partnership["expiry_date"] == "2033-07-31"
        assert partnership["version"] == 1
        assert partnership["collected_tuition_cents"] == 0
        assertions.assert_logical_instant(partnership["created_at"], fixtures.CLOCK_AUG_1)

    def test_reading_a_partnership_echoes_the_stored_row_as_a_single_object(
        self, api, clock_at_default, provost_headers
    ):
        """The read returns the same row under `response_type` object.

        PRD: "The `response_type` is either "object" for a single resource or "array" for a list
        of resources."
        PRD: "`fee_schedule_monthly_cents`, the flat monthly service fee owed to the partner,
        defaults to 0."

        Design: Corner/entities/partnership_get_returns_the_stored_row
        """
        created = fixtures.register_partnership(api)

        response = api.get_partnership(created["id"], headers=provost_headers)
        stored = validate_success(response, 200)
        assert response.json()["response_type"] == "object"

        assert stored["id"] == created["id"]
        assert stored["university_name"] == "Riverbend State University"
        assert stored["contract_structure"] == "REVENUE_SHARE"
        assert stored["fee_schedule_monthly_cents"] == 0

    def test_registration_without_the_contract_structure_is_refused_and_stores_nothing(
        self, api, clock_at_default, admin_headers
    ):
        """A mandatory input with no documented default cannot be omitted.

        PRD: "The economic model is fixed at registration by `contract_structure`, which is
        either `REVENUE_SHARE` or `FEE_FOR_SERVICE`, and the term is fixed by `term_months`, a
        whole number of months no fewer than 12 and no more than 120, measured from the
        `effective_date` supplied as an ISO calendar date."
        PRD: "The request body carries every required field of the endpoint and no unknown fields;
        every value matches its declared type; every enum-valued field carries a declared member;
        every integer field expressed in cents is zero or greater; every date field parses as an
        ISO date; and the paired date fields are ordered — `period_start` no later than
        `period_end`, `launch_window_start` strictly earlier than `launch_window_end`, and
        `term_start_date` no later than `term_end_date`. Any breach yields `ERR_INVALID_REQUEST`
        (400)."

        Design: Corner/entities/partnership_create_missing_required_contract_structure_invalid_request
        """
        payload = factories.partnership_payload(contract_structure=factories.OMIT)
        response = api.create_partnership(payload, headers=admin_headers)

        validate_error(response, ApiErrorId.INVALID_REQUEST.value, 400)

        _, meta = validate_paginated(api.list_partnerships(headers=admin_headers))
        assert meta["total_count"] == 0


class TestProgramSurface:
    def test_program_list_pages_within_one_partnership_in_creation_order(
        self, api, clock_at_default, provost_headers
    ):
        """Three programs, a page of two, and the count of everything the filter matched.

        PRD: "Every list response reports `limit`, `offset`, `total_count` and `has_more` inside
        the envelope's `meta` object, where `total_count` counts the records matching the
        request's filters before pagination is applied and `has_more` is true exactly when
        records remain beyond the returned page."
        PRD: "Unless a specific endpoint says otherwise, list results are ordered by `created_at`
        ascending."

        Design: Corner/entities/programs_list_paginates_with_total_count_and_has_more
        """
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]
        first = fixtures.create_program(api, ps_id)
        second = fixtures.create_program(api, ps_id, program_name="MSN Online", cip_code="51.3801")
        fixtures.create_program(api, ps_id, program_name="MSIS Online", cip_code="11.0401")

        response = api.list_programs(
            {"partnership_id": ps_id, "limit": 2, "offset": 0}, headers=provost_headers
        )
        rows, meta = validate_paginated(response)

        assert response.json()["response_type"] == "array"
        assertions.assert_pagination_meta(meta, limit=2, offset=0, total_count=3, has_more=True)
        assert [row["id"] for row in rows] == [first["id"], second["id"]]

    def test_reading_an_absent_program_is_a_not_found_error(
        self, api, clock_at_default, provost_headers
    ):
        """An unknown id is an error envelope, not an empty success.

        PRD: "The `Program` named by a path identifier or by a `program_id` in the body exists —
        checked on every program-scoped endpoint and on lead creation — otherwise
        `ERR_PROGRAM_NOT_FOUND` (404)."
        PRD: "The `error_id` is a unique, machine-readable string that identifies the specific
        error."

        Design: Corner/entities/program_get_with_unknown_id_not_found
        """
        fixtures.create_executed_partnership(api)

        response = api.get_program(NON_EXISTENT_UUID, headers=provost_headers)

        validate_error(response, ApiErrorId.PROGRAM_NOT_FOUND.value, 404)
        assert response.json()["response_type"] == "error"

    def test_omitted_optional_arrays_take_their_declared_defaults(self, api, clock_at_default):
        """The six-domain approval list and the partnership's four optional economics.

        PRD: "The optional `required_service_domains` array names the domains that must each be
        assigned before approval, and defaults to `MARKETING`, `LEAD_GENERATION`,
        `ENROLLMENT_COUNSELING`, `COURSE_DESIGN`, `STUDENT_ADVISING` and
        `ACCESSIBILITY_ACCOMMODATIONS`."
        PRD: "`exclusivity_cip_codes` defaults to an empty array.
        `bundled_services_exception_claimed` defaults to false and declares whether the
        partnership claims the bundled-services exception that permits counselor salary
        adjustments not based solely on enrollment counts."
        PRD: "when omitted, the partnership takes the standard ladder of 57.5 percent of the
        partner's share up to $250,000 of contract-year recognised revenue, 48.5 percent from
        there up to $750,000, and 39.5 percent above that."

        Design: Corner/entities/program_create_omitting_optional_arrays_applies_declared_defaults
        """
        partnership = fixtures.create_executed_partnership(
            api,
            university_name="Lakeshore University",
            university_ipeds_id="224999",
            exclusivity_cip_codes=factories.OMIT,
            bundled_services_exception_claimed=factories.OMIT,
        )
        ps_id = partnership["id"]

        program = fixtures.create_program(api, ps_id, required_service_domains=factories.OMIT)
        stored = fixtures.read_partnership(api, ps_id)

        assert program["required_service_domains"] == DEFAULT_REQUIRED_DOMAINS
        assert stored["fee_schedule_monthly_cents"] == 0
        assert stored["exclusivity_cip_codes"] == []
        assert stored["bundled_services_exception_claimed"] is False
        assert stored["revenue_share_tiers"] == [
            {"through_cents": 25000000, "partner_rate": 0.575},
            {"through_cents": 75000000, "partner_rate": 0.485},
            {"through_cents": None, "partner_rate": 0.395},
        ]

    def test_an_undeclared_modality_member_is_refused_before_any_score_is_computed(
        self, api, clock_at_default
    ):
        """`delivery_modality` is a closed enum, so an invented member never reaches the formula.

        PRD: "A proposal names its parent with `partnership_id`, carries a marketed
        `program_name`, a `cip_code` in the six-character `NN.NNNN` discipline-code form, a
        `delivery_modality` of `ASYNCHRONOUS`, `SYNCHRONOUS` or `HYBRID`, and a
        `credential_level` of `CERTIFICATE`, `BACHELORS`, `MASTERS` or `DOCTORATE`."

        Design: Corner/entities/program_create_with_invalid_enum_delivery_modality_rejected
        """
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]

        response = api.create_program(
            factories.program_payload(ps_id, delivery_modality="SELF_PACED"),
            headers=make_partner_account_lead_headers(ps_id),
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value, 400)

        _, meta = validate_paginated(
            api.list_programs({"partnership_id": ps_id}, headers=make_provost_headers())
        )
        assert meta["total_count"] == 0

    def test_a_program_under_an_unknown_partnership_is_a_not_found_error(
        self, api, clock_at_default
    ):
        """Parent existence is checked before scope or state.

        PRD: "The `Partnership` named by a path identifier or by a `partnership_id` in the body
        exists — checked on every partnership-scoped endpoint, on program creation and on counselor
        onboarding — otherwise `ERR_PARTNERSHIP_NOT_FOUND` (404)."
        PRD: "Under an `EXECUTED` partnership, the `PartnerAccountLead` proposes individual
        programs; attempting this under a partnership in any other `status` is refused with
        `ERR_PARTNERSHIP_INVALID_STATE`."

        Design: Corner/entities/program_create_under_unknown_partnership_not_found
        """
        response = api.create_program(
            factories.program_payload(NON_EXISTENT_UUID),
            headers=make_partner_account_lead_headers(NON_EXISTENT_UUID),
        )

        validate_error(response, ApiErrorId.PARTNERSHIP_NOT_FOUND.value, 404)


class TestCounselorAndLedgerRows:
    def test_a_new_counselor_starts_with_zeroed_counters_and_both_dimensions_initial(
        self, api, clock_at_default
    ):
        """Onboarding accepts no compensation input at all.

        PRD: "A new counselor has no plan: `comp_plan_type` is `NONE_ON_FILE`, `annual_base_cents`
        and `variable_component_cents` are 0, `variable_basis` is `NONE`, and both state
        dimensions sit at their initial values — `performance_status` at `NOT_RATED` and
        `incentive_eligibility` at `PENDING_COMPLIANCE_REVIEW`."
        PRD: "Every performance counter — `conversion_rate` at 0.0, `open_pipeline_count`,
        `rated_lead_count`, `enrolled_lead_count`, `sla_breach_count`, `clawback_pending_cents` —
        starts at zero, and `last_review_user_id` is null until the first review is decided."

        Design: Corner/entities/counselor_create_initialises_computed_counters_and_both_state_dimensions
        """
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]

        response = api.create_enrollment_counselor(
            factories.counselor_payload(ps_id), headers=make_partner_account_lead_headers(ps_id)
        )
        counselor = validate_success(response, 201)

        assert counselor["comp_plan_type"] == "NONE_ON_FILE"
        assert counselor["performance_status"] == "NOT_RATED"
        assert counselor["incentive_eligibility"] == "PENDING_COMPLIANCE_REVIEW"
        assert counselor["conversion_rate"] == pytest.approx(0.0, abs=0.0001)
        assert counselor["open_pipeline_count"] == 0
        assert counselor["rated_lead_count"] == 0
        assert counselor["clawback_pending_cents"] == 0
        assert counselor["annual_base_cents"] == 0
        assert counselor["variable_basis"] == "NONE"
        assert counselor["last_review_user_id"] is None

    def test_a_posted_payment_carries_server_set_identity_and_ledger_marker(self, api):
        """The bursar supplies none of `id`, `created_at` or `generated_by`.

        PRD: "Entries carry a `generated_by` marker that the server sets: `BURSAR_POST` for an
        entry a bursar posts by hand, and `WITHDRAWAL_REFUND` for the compensating entry the
        withdrawal cascade creates on its own."
        PRD: "Launch windows, contract expiry, settlement-period elapsing, withdrawal day
        counts, teach-out notice periods and every `..._at` system timestamp are all evaluated
        against this clock."

        Design: Corner/entities/tuition_payment_system_fields_are_server_generated
        """
        context = fixtures.build_launched_program(api)
        lead = fixtures.create_applied_lead(api, context["ps_id"], context["pg_id"], context["co_id"])
        enrollment = fixtures.enroll_lead(api, lead["id"])
        fixtures.set_clock(api, fixtures.CLOCK_SEP_5)

        response = api.create_tuition_payment(
            enrollment["id"],
            factories.tuition_payment_payload(reference_note="Term 1 tuition in full"),
            headers=make_bursar_headers(),
        )
        entry = validate_success(response, 201)

        assert entry["generated_by"] == "BURSAR_POST"
        assert entry["enrollment_id"] == enrollment["id"]
        assertions.assert_logical_instant(entry["created_at"], fixtures.CLOCK_SEP_5)

        stored = fixtures.read_enrollment(api, enrollment["id"])
        assert stored["tuition_charged_cents"] == 562500
        assert stored["collected_cents"] == 562500

    def test_a_tuition_ledger_row_exposes_neither_version_nor_updated_at(self, api):
        """The append-only ledgers are deliberately leaner than the versioned resources.

        PRD: "A tuition ledger entry and a marketing ledger entry are append-only facts, never
        amended after the fact, and therefore carry only `id` and `created_at`: they have no
        `updated_at` field and no `version` field at all, and neither field should appear in
        their response payloads."
        PRD: "Ledger entries are never amended or deleted."

        Design: Corner/entities/tuition_payment_is_immutable_and_carries_no_version_field
        """
        context = fixtures.build_paid_enrollment(api)

        rows, meta = validate_paginated(
            api.list_tuition_payments(
                context["en_id"], {"limit": 10, "offset": 0}, headers=make_compliance_auditor_headers()
            )
        )

        assert meta["total_count"] == 1
        assertions.assert_append_only_entity(rows[0])

    def test_leads_are_reachable_through_both_of_their_foreign_keys(self, api):
        """Neither the program link nor the counselor link is write-only.

        PRD: "Leads may be listed filtered by `program_id`, by `counselor_id` and by `status`."
        PRD: "A lead names the `program_id` it inquired about, the `counselor_id` of the
        counselor who owns it, a `source_channel` of `PAID_SEARCH`, `PAID_SOCIAL`, `ORGANIC`,
        `EMPLOYER_REFERRAL` or `LIST_PURCHASE`, and a `prospect_external_id` that is the
        partner-side prospect identifier and is unique within the program."

        Design: Corner/entities/leads_filtered_by_program_id_reach_the_children_of_that_program
        """
        context = fixtures.build_launched_program(api)
        ps_id, pg_id, co_id = context["ps_id"], context["pg_id"], context["co_id"]
        other_program = fixtures.create_program(
            api, ps_id, program_name="MSN Online", cip_code="51.3801"
        )
        lead = fixtures.create_lead(api, ps_id, pg_id, co_id)
        fixtures.contact_lead(api, ps_id, lead["id"], 6)

        auditor = make_compliance_auditor_headers()
        by_program, program_meta = validate_paginated(
            api.list_leads({"program_id": pg_id, "limit": 10, "offset": 0}, headers=auditor)
        )
        assert program_meta["total_count"] == 1
        assert by_program[0]["id"] == lead["id"]
        assert by_program[0]["program_id"] == pg_id

        by_counselor, counselor_meta = validate_paginated(
            api.list_leads({"counselor_id": co_id, "limit": 10, "offset": 0}, headers=auditor)
        )
        assert counselor_meta["total_count"] == 1
        assert by_counselor[0]["counselor_id"] == co_id

        _, empty_meta = validate_paginated(
            api.list_leads({"program_id": other_program["id"]}, headers=auditor)
        )
        assert empty_meta["total_count"] == 0
