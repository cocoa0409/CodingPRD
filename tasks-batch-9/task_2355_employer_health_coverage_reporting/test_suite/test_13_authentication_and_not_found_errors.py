"""Header admission, role admission and the per-family not-found codes.

Covers the two admission rungs of PRD §2.1 — a request that omits its auth
headers and a request whose declared role is not listed for the endpoint — and
the single-resource reads of PRD §2.5, where each entity family answers an
unresolvable path identifier with its own 404 code while the append-only ledger
families share the generic one.
"""

from test_helpers import (
    ApiErrorId,
    fixtures,
    make_employee_self_service_headers,
    validate_error,
    validate_paginated,
)

# Path identifiers that resolve to nothing in an empty store.
MISSING_FILING_SEASON_ID = "00000000-0000-0000-0000-0000000000f1"
MISSING_CONTROLLED_GROUP_ID = "00000000-0000-0000-0000-0000000000f2"
MISSING_GROUP_MEMBER_ID = "00000000-0000-0000-0000-0000000000f3"
MISSING_CONSENT_ID = "00000000-0000-0000-0000-0000000000f4"
MISSING_FORM_ID = "00000000-0000-0000-0000-0000000000f5"
MISSING_TRANSMITTAL_ID = "00000000-0000-0000-0000-0000000000f6"
MISSING_TRANSMITTAL_ERROR_ID = "00000000-0000-0000-0000-0000000000f7"
MISSING_PENALTY_NOTICE_ID = "00000000-0000-0000-0000-0000000000f8"
MISSING_HOURS_RECORD_ID = "00000000-0000-0000-0000-0000000000f9"
MISSING_COVERAGE_LINE_ID = "00000000-0000-0000-0000-0000000000fa"


def _employee_for_self_service(api, headers):
    """Hire one employee so an ``EmployeeSelfService`` header can name a real
    Employee id, which is what that role's ``X-User-ID`` is."""
    season = fixtures.create_filing_season(api, headers)
    group = fixtures.create_controlled_group(api, season["id"], headers)
    member = fixtures.create_group_member(api, group["id"], headers=headers)
    return fixtures.create_employee(api, member["id"])


class TestAdmissionRungs:
    def test_filing_season_create_without_auth_headers_is_unauthenticated(
        self, api, compliance_officer_headers
    ):
        """PRD §2.1: "Every request, without exception, must carry two headers:
        `X-User-ID` identifying the acting user and `X-User-Role` naming the
        capacity in which they act. A request that omits either header, sends
        either as an empty value, or names a role this system does not recognise
        is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is
        examined."
        PRD §2.6: "Every mutating endpoint runs one shared ladder from the top
        and returns the **first** rule it violates; lower numbers win."

        Design: Corner/Errors/unauthenticated_write_missing_x_user_header_returns_401
        """
        # The body is also missing three mandatory dates, so a 400 would be the
        # wrong answer: header admission is examined before payload shape.
        response = api.create_filing_season({"tax_year": 2026}, {})

        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)
        assert response.json()["data"]["error_id"] != ApiErrorId.ERR_INVALID_REQUEST, (
            "A header-less create must answer ERR_UNAUTHENTICATED even though "
            "furnishing_deadline_date, filing_deadline_date and tier2_cutoff_date "
            "are all absent from the body"
        )

        _rows, meta = validate_paginated(
            api.list_filing_seasons(compliance_officer_headers, params={"tax_year": 2026})
        )
        assert meta["total_count"] == 0, (
            f"Expected no filing season for tax_year 2026 after the rejected "
            f"unauthenticated create, got total_count {meta['total_count']}"
        )

    def test_benefits_admin_cannot_create_filing_season(
        self, api, benefits_admin_headers, compliance_officer_headers
    ):
        """PRD §2.1: "When the acting role is not among the roles listed for the
        endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."
        PRD §2.1: "A `BenefitsAdmin` owns workforce data: hires, wage updates,
        hours of service, leaves, transfers, terminations, rehires and offers of
        coverage."

        Design: Corner/Errors/forbidden_role_benefits_admin_cannot_create_filing_season
        """
        payload = {
            "tax_year": 2026,
            "furnishing_deadline_date": "2027-03-02",
            "filing_deadline_date": "2027-03-31",
            "tier2_cutoff_date": "2027-08-01",
        }
        response = api.create_filing_season(payload, benefits_admin_headers)

        validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

        _rows, meta = validate_paginated(
            api.list_filing_seasons(compliance_officer_headers, params={"tax_year": 2026})
        )
        assert meta["total_count"] == 0, (
            f"A BenefitsAdmin request refused with ERR_FORBIDDEN_ROLE must create "
            f"no FilingSeason, got total_count {meta['total_count']}"
        )


class TestPathIdentifierNotFound:
    def test_unknown_filing_season_id_returns_season_not_found(
        self, api, compliance_officer_headers
    ):
        """PRD §2.5: "Path identifiers are validated strictly left to right, and
        the first identifier that does not resolve determines the 404 that comes
        back."
        PRD §2.5: "Each family has its own not-found code —
        `ERR_FILING_SEASON_NOT_FOUND`, `ERR_CONTROLLED_GROUP_NOT_FOUND`,
        `ERR_GROUP_MEMBER_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`,
        `ERR_CONSENT_NOT_FOUND`, `ERR_FORM_NOT_FOUND`,
        `ERR_TRANSMITTAL_NOT_FOUND`, `ERR_TRANSMITTAL_ERROR_NOT_FOUND` and
        `ERR_PENALTY_NOTICE_NOT_FOUND` — while the single-row reads of the seven
        append-only ledger families answer with `ERR_RECORD_NOT_FOUND`."

        Design: Corner/Errors/filing_season_path_id_not_found_returns_404
        """
        response = api.get_filing_season(MISSING_FILING_SEASON_ID, compliance_officer_headers)

        validate_error(response, ApiErrorId.ERR_FILING_SEASON_NOT_FOUND, 404)

    def test_unknown_controlled_group_id_returns_group_not_found(
        self, api, compliance_officer_headers
    ):
        """PRD §2.5: "Path identifiers are validated strictly left to right, and
        the first identifier that does not resolve determines the 404 that comes
        back."
        PRD §2.5: "Each family has its own not-found code —
        `ERR_FILING_SEASON_NOT_FOUND`, `ERR_CONTROLLED_GROUP_NOT_FOUND`,
        `ERR_GROUP_MEMBER_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`,
        `ERR_CONSENT_NOT_FOUND`, `ERR_FORM_NOT_FOUND`,
        `ERR_TRANSMITTAL_NOT_FOUND`, `ERR_TRANSMITTAL_ERROR_NOT_FOUND` and
        `ERR_PENALTY_NOTICE_NOT_FOUND` — while the single-row reads of the seven
        append-only ledger families answer with `ERR_RECORD_NOT_FOUND`."

        Design: Corner/Errors/controlled_group_path_id_not_found_returns_404
        """
        response = api.get_controlled_group(
            MISSING_CONTROLLED_GROUP_ID, compliance_officer_headers
        )

        validate_error(response, ApiErrorId.ERR_CONTROLLED_GROUP_NOT_FOUND, 404)

    def test_unknown_group_member_id_returns_member_not_found(
        self, api, compliance_officer_headers
    ):
        """PRD §2.5: "Path identifiers are validated strictly left to right, and
        the first identifier that does not resolve determines the 404 that comes
        back."
        PRD §2.5: "Each family has its own not-found code —
        `ERR_FILING_SEASON_NOT_FOUND`, `ERR_CONTROLLED_GROUP_NOT_FOUND`,
        `ERR_GROUP_MEMBER_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`,
        `ERR_CONSENT_NOT_FOUND`, `ERR_FORM_NOT_FOUND`,
        `ERR_TRANSMITTAL_NOT_FOUND`, `ERR_TRANSMITTAL_ERROR_NOT_FOUND` and
        `ERR_PENALTY_NOTICE_NOT_FOUND` — while the single-row reads of the seven
        append-only ledger families answer with `ERR_RECORD_NOT_FOUND`."

        Design: Corner/Errors/group_member_path_id_not_found_returns_404
        """
        response = api.get_group_member(MISSING_GROUP_MEMBER_ID, compliance_officer_headers)

        validate_error(response, ApiErrorId.ERR_GROUP_MEMBER_NOT_FOUND, 404)

    def test_unknown_consent_id_returns_consent_not_found_for_employee(
        self, api, compliance_officer_headers
    ):
        """PRD §2.5: "Path identifiers are validated strictly left to right, and
        the first identifier that does not resolve determines the 404 that comes
        back."
        PRD §2.5: "Each family has its own not-found code —
        `ERR_FILING_SEASON_NOT_FOUND`, `ERR_CONTROLLED_GROUP_NOT_FOUND`,
        `ERR_GROUP_MEMBER_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`,
        `ERR_CONSENT_NOT_FOUND`, `ERR_FORM_NOT_FOUND`,
        `ERR_TRANSMITTAL_NOT_FOUND`, `ERR_TRANSMITTAL_ERROR_NOT_FOUND` and
        `ERR_PENALTY_NOTICE_NOT_FOUND` — while the single-row reads of the seven
        append-only ledger families answer with `ERR_RECORD_NOT_FOUND`."

        Design: Corner/Errors/consent_path_id_not_found_returns_404
        """
        employee = _employee_for_self_service(api, compliance_officer_headers)

        response = api.get_furnishing_consent(
            MISSING_CONSENT_ID, make_employee_self_service_headers(employee["id"])
        )

        validate_error(response, ApiErrorId.ERR_CONSENT_NOT_FOUND, 404)

    def test_unknown_form_id_returns_form_not_found(self, api, preparer_headers):
        """PRD §2.5: "Path identifiers are validated strictly left to right, and
        the first identifier that does not resolve determines the 404 that comes
        back."
        PRD §2.5: "Each family has its own not-found code —
        `ERR_FILING_SEASON_NOT_FOUND`, `ERR_CONTROLLED_GROUP_NOT_FOUND`,
        `ERR_GROUP_MEMBER_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`,
        `ERR_CONSENT_NOT_FOUND`, `ERR_FORM_NOT_FOUND`,
        `ERR_TRANSMITTAL_NOT_FOUND`, `ERR_TRANSMITTAL_ERROR_NOT_FOUND` and
        `ERR_PENALTY_NOTICE_NOT_FOUND` — while the single-row reads of the seven
        append-only ledger families answer with `ERR_RECORD_NOT_FOUND`."

        Design: Corner/Errors/form_path_id_not_found_returns_404
        """
        response = api.get_form_1095c(MISSING_FORM_ID, preparer_headers)

        validate_error(response, ApiErrorId.ERR_FORM_NOT_FOUND, 404)

    def test_unknown_transmittal_id_returns_transmittal_not_found(
        self, api, filing_agent_headers
    ):
        """PRD §2.5: "Path identifiers are validated strictly left to right, and
        the first identifier that does not resolve determines the 404 that comes
        back."
        PRD §2.5: "Each family has its own not-found code —
        `ERR_FILING_SEASON_NOT_FOUND`, `ERR_CONTROLLED_GROUP_NOT_FOUND`,
        `ERR_GROUP_MEMBER_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`,
        `ERR_CONSENT_NOT_FOUND`, `ERR_FORM_NOT_FOUND`,
        `ERR_TRANSMITTAL_NOT_FOUND`, `ERR_TRANSMITTAL_ERROR_NOT_FOUND` and
        `ERR_PENALTY_NOTICE_NOT_FOUND` — while the single-row reads of the seven
        append-only ledger families answer with `ERR_RECORD_NOT_FOUND`."

        Design: Corner/Errors/transmittal_path_id_not_found_returns_404
        """
        response = api.get_transmittal(MISSING_TRANSMITTAL_ID, filing_agent_headers)

        validate_error(response, ApiErrorId.ERR_TRANSMITTAL_NOT_FOUND, 404)

    def test_unknown_transmittal_error_id_returns_error_row_not_found(
        self, api, preparer_headers
    ):
        """PRD §2.5: "Path identifiers are validated strictly left to right, and
        the first identifier that does not resolve determines the 404 that comes
        back."
        PRD §2.5: "Each family has its own not-found code —
        `ERR_FILING_SEASON_NOT_FOUND`, `ERR_CONTROLLED_GROUP_NOT_FOUND`,
        `ERR_GROUP_MEMBER_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`,
        `ERR_CONSENT_NOT_FOUND`, `ERR_FORM_NOT_FOUND`,
        `ERR_TRANSMITTAL_NOT_FOUND`, `ERR_TRANSMITTAL_ERROR_NOT_FOUND` and
        `ERR_PENALTY_NOTICE_NOT_FOUND` — while the single-row reads of the seven
        append-only ledger families answer with `ERR_RECORD_NOT_FOUND`."

        Design: Corner/Errors/transmittal_error_path_id_not_found_returns_404
        """
        response = api.get_transmittal_error(MISSING_TRANSMITTAL_ERROR_ID, preparer_headers)

        validate_error(response, ApiErrorId.ERR_TRANSMITTAL_ERROR_NOT_FOUND, 404)

    def test_unknown_penalty_notice_id_returns_notice_not_found(
        self, api, compliance_officer_headers
    ):
        """PRD §2.5: "Path identifiers are validated strictly left to right, and
        the first identifier that does not resolve determines the 404 that comes
        back."
        PRD §2.5: "Each family has its own not-found code —
        `ERR_FILING_SEASON_NOT_FOUND`, `ERR_CONTROLLED_GROUP_NOT_FOUND`,
        `ERR_GROUP_MEMBER_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`,
        `ERR_CONSENT_NOT_FOUND`, `ERR_FORM_NOT_FOUND`,
        `ERR_TRANSMITTAL_NOT_FOUND`, `ERR_TRANSMITTAL_ERROR_NOT_FOUND` and
        `ERR_PENALTY_NOTICE_NOT_FOUND` — while the single-row reads of the seven
        append-only ledger families answer with `ERR_RECORD_NOT_FOUND`."

        Design: Corner/Errors/penalty_notice_path_id_not_found_returns_404
        """
        response = api.get_penalty_notice(MISSING_PENALTY_NOTICE_ID, compliance_officer_headers)

        validate_error(response, ApiErrorId.ERR_PENALTY_NOTICE_NOT_FOUND, 404)

    def test_unknown_hours_record_id_returns_generic_record_not_found(
        self, api, benefits_admin_headers
    ):
        """PRD §2.5: "Each family has its own not-found code —
        `ERR_FILING_SEASON_NOT_FOUND`, `ERR_CONTROLLED_GROUP_NOT_FOUND`,
        `ERR_GROUP_MEMBER_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`,
        `ERR_CONSENT_NOT_FOUND`, `ERR_FORM_NOT_FOUND`,
        `ERR_TRANSMITTAL_NOT_FOUND`, `ERR_TRANSMITTAL_ERROR_NOT_FOUND` and
        `ERR_PENALTY_NOTICE_NOT_FOUND` — while the single-row reads of the seven
        append-only ledger families answer with `ERR_RECORD_NOT_FOUND`."
        PRD §2.4: "The remaining seven families are append-only ledger rows and
        carry only `id` and `created_at` — monthly headcounts, measurement
        cycles, hours records, employment events, coverage offers, monthly
        coverage lines and penalty evidence have **no** `updated_at` and **no**
        `version` field at all."

        Design: Corner/Errors/immutable_ledger_row_not_found_returns_404
        """
        response = api.get_hours_record(MISSING_HOURS_RECORD_ID, benefits_admin_headers)

        validate_error(response, ApiErrorId.ERR_RECORD_NOT_FOUND, 404)

    def test_unknown_coverage_line_id_returns_the_same_generic_code(
        self, api, benefits_admin_headers
    ):
        """PRD §2.5: "Each family has its own not-found code —
        `ERR_FILING_SEASON_NOT_FOUND`, `ERR_CONTROLLED_GROUP_NOT_FOUND`,
        `ERR_GROUP_MEMBER_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`,
        `ERR_CONSENT_NOT_FOUND`, `ERR_FORM_NOT_FOUND`,
        `ERR_TRANSMITTAL_NOT_FOUND`, `ERR_TRANSMITTAL_ERROR_NOT_FOUND` and
        `ERR_PENALTY_NOTICE_NOT_FOUND` — while the single-row reads of the seven
        append-only ledger families answer with `ERR_RECORD_NOT_FOUND`."
        PRD §2.4: "The remaining seven families are append-only ledger rows and
        carry only `id` and `created_at` — monthly headcounts, measurement
        cycles, hours records, employment events, coverage offers, monthly
        coverage lines and penalty evidence have **no** `updated_at` and **no**
        `version` field at all."

        Design: Corner/Errors/immutable_ledger_row_not_found_returns_404
        """
        response = api.get_monthly_coverage_line(
            MISSING_COVERAGE_LINE_ID, benefits_admin_headers
        )

        validate_error(response, ApiErrorId.ERR_RECORD_NOT_FOUND, 404)
