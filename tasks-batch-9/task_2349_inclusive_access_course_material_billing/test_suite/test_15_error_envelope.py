"""The two highest-precedence rejection families: identity, which is checked before
anything else at all, and body shape, which is checked before any foreign key in the
body is resolved.
"""

from test_helpers import (
    AcademicTermStatus,
    ApiErrorId,
    MISSING_UUID,
    factories,
    fixtures,
    make_role_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

NO_ROLE_HEADER = {"Content-Type": "application/json", "X-User-ID": "pa-1"}
NO_ID_HEADER = {"Content-Type": "application/json", "X-User-Role": "ProgramAdmin"}
UNDECLARED_ROLE = make_role_headers("Bursar", "bo-1")
INVENTED_ROLE = make_role_headers("SuperUser", "root")


class TestIdentityIsCheckedBeforeAnythingElse:
    """Three ways to fail identity, all 401 — never 403 and never a shape error."""

    @staticmethod
    def _planning_term(api):
        fixtures.set_clock(api, "2026-07-05T00:00:00Z")
        return fixtures.create_term(api)["id"]

    def test_an_absent_header_and_an_undeclared_role_are_the_same_failure(
            self, api, program_admin):
        """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of
        the six role names declared below, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/errors_missing_x_user_role_header_returns_unauthenticated
        """
        term_id = self._planning_term(api)

        for headers in (NO_ROLE_HEADER, NO_ID_HEADER, UNDECLARED_ROLE):
            response = api.get_term(term_id, headers)
            validate_error(response, ApiErrorId.UNAUTHENTICATED.value,
                          expected_status=401)

        # The same read succeeds the moment a declared role names itself.
        assert validate_success(api.get_term(term_id, program_admin))["id"] == term_id

    def test_identity_outranks_the_state_gate_and_the_body_shape_gate(
            self, api, program_admin):
        """PRD §2.11: "When several checks could fire on one request, they are
        evaluated in a single global order and the first failure is returned."

        Design: Corner/errors/errors_missing_x_user_role_header_returns_unauthenticated
        """
        term_id = self._planning_term(api)

        response = api.open_term(term_id, NO_ROLE_HEADER)
        validate_error(response, ApiErrorId.UNAUTHENTICATED.value,
                      expected_status=401)
        # A rejected request mutates nothing.
        assert fixtures.read_term(api, term_id)["status"] == \
            AcademicTermStatus.PLANNING.value

        # The body also carries an unknown field, but identity is checked first.
        response = api.create_section(
            factories.section_payload(term_id, unknown_field="x"), INVENTED_ROLE
        )
        validate_error(response, ApiErrorId.UNAUTHENTICATED.value,
                      expected_status=401)

        _, meta = validate_paginated(api.list_term_sections(term_id, program_admin))
        assert meta["total_count"] == 0


class TestBodyShapeIsCheckedBeforeBodyForeignKeys:
    """One rejection code covers unknown fields, enum members and numeric ranges."""

    @staticmethod
    def _open_term_with_an_unpriced_title_and_a_section(api):
        catalog = fixtures.setup_catalog(
            api, setup_clock="2026-07-05T00:00:00Z", bands=(), activate_now=False
        )
        section = fixtures.create_section(api, catalog["term_id"])
        return {
            "term_id": catalog["term_id"],
            "agreement_id": catalog["agreement_id"],
            "agreement_version": catalog["agreement_version"],
            "title_id": catalog["title_id"],
            "section_id": section["id"],
            "section_version": section["version"],
        }

    def test_unknown_fields_bad_enum_members_and_out_of_range_numbers_all_return_400(
            self, api, program_admin, compliance_officer):
        """PRD §2.11: "Request body shape on every write: required fields present,
        types correct, enum members recognized, numeric ranges respected, and unknown
        fields rejected outright — `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/errors/errors_unknown_body_field_returns_invalid_request
        """
        scenario = self._open_term_with_an_unpriced_title_and_a_section(api)

        # An unknown field is not a declared input of POST /adoptions.
        validate_error(
            api.create_adoption(
                factories.adoption_payload(
                    scenario["section_id"], scenario["title_id"],
                    scenario["section_version"], priority_flag=True),
                fixtures.make_faculty_headers("fac-1")),
            ApiErrorId.INVALID_REQUEST.value, expected_status=400,
        )
        # min_enrollment must be at least 1.
        validate_error(
            api.create_pricing_tier(
                scenario["title_id"],
                factories.pricing_tier_payload(min_enrollment=0, max_enrollment=None,
                                               per_student_price_cents=9000),
                program_admin),
            ApiErrorId.INVALID_REQUEST.value, expected_status=400,
        )
        # A reporting state code is exactly two uppercase letters.
        validate_error(
            api.create_disclosure_report(
                factories.disclosure_report_payload(scenario["term_id"], "california"),
                compliance_officer),
            ApiErrorId.INVALID_REQUEST.value, expected_status=400,
        )
        # HEADCOUNT is not a member of the reconciliation method enum.
        validate_error(
            api.create_reconciliation_run(
                factories.reconciliation_run_payload(
                    scenario["agreement_id"], scenario["term_id"],
                    scenario["agreement_version"], publisher_reported_count=1,
                    publisher_reported_amount_cents=8316, method="HEADCOUNT"),
                program_admin),
            ApiErrorId.INVALID_REQUEST.value, expected_status=400,
        )

        for listing in (
            api.list_section_adoptions(scenario["section_id"], program_admin),
            api.list_title_pricing_tiers(scenario["title_id"], program_admin),
            api.list_term_disclosure_reports(scenario["term_id"], compliance_officer),
            api.list_agreement_reconciliation_runs(scenario["agreement_id"],
                                                  program_admin),
        ):
            _, meta = validate_paginated(listing)
            assert meta["total_count"] == 0

        assert fixtures.section_version(api, scenario["section_id"]) == \
            scenario["section_version"]

    def test_a_malformed_body_never_reaches_its_own_foreign_keys(self, api,
                                                                program_admin):
        """PRD §2.11: "Foreign keys supplied in a request body are resolved after the
        path and in a fixed declaration order: `term_id`, then `agreement_id`, then
        `title_id`, then `section_id`, then `student_id`, then `enrollment_id`, then
        `adoption_id`, then `charge_id`, then `supersedes_adoption_id`, then
        `supersedes_run_id`."

        Design: Corner/errors/errors_unknown_body_field_returns_invalid_request
        """
        scenario = self._open_term_with_an_unpriced_title_and_a_section(api)
        owner = fixtures.make_faculty_headers("fac-1")

        # Unknown field plus a title that does not exist: shape wins.
        validate_error(
            api.create_adoption(
                factories.adoption_payload(
                    scenario["section_id"], MISSING_UUID,
                    scenario["section_version"], priority_flag=True),
                owner),
            ApiErrorId.INVALID_REQUEST.value, expected_status=400,
        )

        # With the shape repaired, the very same missing title is now reported.
        validate_error(
            api.create_adoption(
                factories.adoption_payload(
                    scenario["section_id"], MISSING_UUID,
                    scenario["section_version"]),
                owner),
            ApiErrorId.TITLE_NOT_FOUND.value, expected_status=404,
        )

        _, meta = validate_paginated(
            api.list_section_adoptions(scenario["section_id"], program_admin)
        )
        assert meta["total_count"] == 0
