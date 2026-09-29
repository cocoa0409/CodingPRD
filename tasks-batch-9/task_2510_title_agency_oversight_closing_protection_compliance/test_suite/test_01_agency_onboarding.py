"""Agency registration, the financial review gates and the appointment decision."""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_appointment_status,
    assert_common_fields,
    assert_created_at_ascending,
    assert_defalcation_score,
    assert_escrow_standing,
    assert_fields_equal,
    assert_meta,
    assert_posture,
    create_agency,
    create_agency_payload,
    create_appointment,
    decide_appointment,
    decide_financial_review,
    factories,
    make_agency_principal_headers,
    read_agency,
    submit_financial_review,
    validate_error,
    validate_paginated,
    validate_success,
    verify_license,
)
from test_helpers.fixtures import ANALYST, OFFICER


class TestAgencyRegistration:
    """Registration lands a fully defined but fully restricted row."""

    def test_new_agency_reads_back_with_every_system_default(self, api):
        """A freshly registered agency carries every declared default on read.

        PRD: "A newly created agency lands in a fully defined but fully restricted
        state: `appointment_status` is `PENDING_REVIEW`, `financial_review_status` is
        `NOT_SUBMITTED`, `escrow_standing` is `COMPLIANT`, `defalcation_score` is 0,
        and `oversight_posture` is consequently `RESTRICTED`."

        Design: Corner/entities/retrieval_agency_returns_stored_row_with_system_defaults
        """
        payload = create_agency_payload(
            legal_name="Harbor Title Agency", underwriting_authority_limit_cents=50_000_000
        )
        created = validate_success(api.create_agency(payload, ANALYST), 201)

        fetched = validate_success(api.get_agency(created["id"], ANALYST))

        assert_common_fields(fetched, "agency")
        assert fetched["id"] == created["id"], (
            f"GET returned {fetched['id']}, not the created {created['id']}"
        )
        assert_fields_equal(
            fetched,
            {
                "legal_name": "Harbor Title Agency",
                "tax_id": payload["tax_id"],
                "underwriting_authority_limit_cents": 50_000_000,
                "appointment_status": "PENDING_REVIEW",
                "financial_review_status": "NOT_SUBMITTED",
                "open_critical_finding_count": 0,
                "unreported_policy_count": 0,
                "cpl_outstanding_exposure_cents": 0,
                "unremitted_premium_cents": 0,
                "pending_transfer_count": 0,
                "version": 1,
            },
            "agency",
        )
        assert_escrow_standing(fetched, "COMPLIANT")
        assert_defalcation_score(fetched, 0)
        assert_posture(fetched, "RESTRICTED")
        assert fetched["termination_reason"] is None, (
            f"termination_reason should start null, got {fetched['termination_reason']!r}"
        )
        assert fetched["transferee_agency_id"] is None, (
            "transferee_agency_id should start null, got "
            f"{fetched['transferee_agency_id']!r}"
        )

    def test_create_agency_without_tax_id_is_rejected(self, api):
        """`tax_id` is a required input, so omitting it fails the shape tier.

        PRD: "Every required body field present, of the declared type, within its
        declared enum domain for enum fields, non-negative for `_cents` and `_days`
        integers, and ISO-8601 for date and datetime fields."

        Design: Corner/entities/required_fields_create_agency_without_tax_id_returns_400
        """
        payload = factories.without(
            create_agency_payload(legal_name="Harbor Title Agency"), "tax_id"
        )

        response = api.create_agency(payload, ANALYST)

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        rows, meta = validate_paginated(api.list_agencies(ANALYST))
        assert meta["total_count"] == 0, (
            f"no partial agency row may be written, but the list shows {rows}"
        )

    def test_agency_version_starts_at_one_and_increments_on_a_mutation(self, api):
        """`version` is server-owned: it starts at 1 and advances by one per mutation.

        PRD: "`version` is an integer that starts at 1 on creation and increments by
        exactly 1 on each mutation."

        Design: Corner/entities/system_fields_agency_version_starts_at_one_and_increments_on_mutation
        """
        agency = create_agency(api)
        assert agency["version"] == 1, (
            f"a new agency must be at version 1, got {agency['version']}"
        )

        statement = validate_success(
            api.create_statement(
                factories.create_statement_payload(
                    agency["id"], "2026-07-01", "2026-07-31", agency["version"]
                ),
                make_agency_principal_headers(agency["id"]),
            ),
            201,
        )

        after = read_agency(api, agency["id"])
        assert after["version"] == 2, (
            "creating a remittance statement is a mutation of the agency, so its "
            f"version must read 2, got {after['version']}"
        )
        assert statement["version"] == 1, (
            f"the new statement must be at version 1, got {statement['version']}"
        )
        assert after["updated_at"] >= after["created_at"], (
            "updated_at must be refreshed on mutation, but "
            f"{after['updated_at']} precedes {after['created_at']}"
        )


class TestAgencyListing:
    """The list endpoint pages with a filtered total count."""

    def test_agency_list_pages_report_total_count_and_has_more(self, api):
        """A two-row window over three agencies reports the unwindowed total.

        PRD: "The `meta` block of a list response carries `limit`, `offset`,
        `total_count` and `has_more`, where `total_count` is the size of the filtered
        result set before the page window is applied and `has_more` is true when
        records remain beyond the current window."

        Design: Corner/entities/listing_agencies_paginates_with_total_count_and_has_more
        """
        create_agency(api, legal_name="Agency One")
        create_agency(api, legal_name="Agency Two")
        create_agency(api, legal_name="Agency Three")

        page1, meta1 = validate_paginated(
            api.list_agencies(OFFICER, params={"limit": 2, "offset": 0})
        )
        page2, meta2 = validate_paginated(
            api.list_agencies(OFFICER, params={"limit": 2, "offset": 2})
        )

        assert_meta(meta1, limit=2, offset=0, total_count=3, has_more=True)
        assert len(page1) == 2, f"the first window must hold two rows, got {len(page1)}"
        assert_meta(meta2, limit=2, offset=2, total_count=3, has_more=False)
        assert len(page2) == 1, f"the last window must hold one row, got {len(page2)}"
        assert page1[0]["id"] != page2[0]["id"], (
            "the two windows must not overlap, but both start at "
            f"{page1[0]['id']}"
        )
        assert_created_at_ascending(page1)


class TestAppointmentDecision:
    """The appointment dimension advances only on declared transitions."""

    def test_second_appoint_decision_is_refused(self, api, state_program):
        """`APPOINT` is not idempotent: there is no `APPOINTED` to `APPOINTED` move.

        PRD: "Appointing an agency moves `appointment_status` from `PENDING_REVIEW` to
        `APPOINTED` and demands two things of the agency's current record"

        Design: Corner/state_machines/idempotency_second_appoint_decision_returns_409
        """
        agency = create_agency(api)
        submit_financial_review(api, agency["id"])
        decide_financial_review(api, agency["id"], "ACCEPT")
        appointment = create_appointment(api, agency["id"], state_program["id"])
        verify_license(api, appointment["id"])

        first = decide_appointment(api, agency["id"], "APPOINT")
        assert_appointment_status(first, "APPOINTED")

        response = api.decide_appointment(
            agency["id"], factories.appointment_decision_payload("APPOINT"), ANALYST
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

        after = read_agency(api, agency["id"])
        assert_appointment_status(after, "APPOINTED")
        assert after["version"] == first["version"], (
            "a refused decision must not advance the agency version: "
            f"{first['version']} -> {after['version']}"
        )


class TestRequestLevelRejections:
    """The three request-level errors that need no domain state."""

    def test_request_without_role_headers_is_unauthenticated(self, api):
        """Both identity headers are mandatory on every request, reads included.

        PRD: "If either header is absent, or if `X-User-Role` carries any string
        other than those five, the request is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/errors/unauthenticated_and_malformed_requests_are_rejected_returns_401
        """
        agency = create_agency(api)

        response = api.get_agency(agency["id"], {"Content-Type": "application/json"})

        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    @pytest.mark.parametrize(
        "params",
        [
            {"limit": 0},
            {"limit": 101},
            {"offset": -1},
        ],
    )
    def test_pagination_arguments_outside_their_range_are_rejected(self, api, params):
        """An out-of-range window argument is refused rather than clamped.

        PRD: "A `limit` that is not an integer, or an integer below 1 or above 100,
        and an `offset` that is not an integer or is negative, are both rejected with
        `ERR_INVALID_REQUEST` (HTTP 400) rather than silently clamped."

        Design: Corner/errors/unauthenticated_and_malformed_requests_are_rejected_returns_401
        """
        response = api.list_agencies(OFFICER, params=params)

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    def test_termination_without_a_reason_is_rejected_in_the_shape_tier(self, api):
        """A `TERMINATE` decision missing its reason fails before any state check.

        PRD: "A `termination_reason` of `FOR_CAUSE`, `VOLUNTARY` or `NON_RENEWAL`
        must be present in the body, else `ERR_TERMINATION_REASON_REQUIRED` (HTTP
        400)."

        Design: Corner/errors/unauthenticated_and_malformed_requests_are_rejected_returns_401
        """
        agency = create_agency(api)

        response = api.decide_appointment(
            agency["id"], factories.appointment_decision_payload("TERMINATE"), OFFICER
        )

        validate_error(response, ApiErrorId.ERR_TERMINATION_REASON_REQUIRED.value, 400)

        after = read_agency(api, agency["id"])
        assert_appointment_status(after, "PENDING_REVIEW")

    @pytest.mark.parametrize(
        "path, error_id",
        [
            ("agencies", ApiErrorId.ERR_AGENCY_NOT_FOUND),
            ("state-programs", ApiErrorId.ERR_STATE_PROGRAM_NOT_FOUND),
            ("agency-appointments", ApiErrorId.ERR_AGENCY_APPOINTMENT_NOT_FOUND),
            ("closing-protection-letters", ApiErrorId.ERR_CPL_NOT_FOUND),
            ("policy-files", ApiErrorId.ERR_POLICY_FILE_NOT_FOUND),
            ("remittance-statements", ApiErrorId.ERR_REMITTANCE_STATEMENT_NOT_FOUND),
            ("escrow-accounts", ApiErrorId.ERR_ESCROW_ACCOUNT_NOT_FOUND),
            ("audit-findings", ApiErrorId.ERR_AUDIT_FINDING_NOT_FOUND),
            ("agency-claims", ApiErrorId.ERR_AGENCY_CLAIM_NOT_FOUND),
        ],
    )
    def test_unknown_ids_report_the_resource_specific_not_found(
        self, api, path, error_id
    ):
        """Each path segment reports its own not-found identifier, never a shared one.

        PRD: "an unresolvable agency segment gives `ERR_AGENCY_NOT_FOUND`, a state
        program segment `ERR_STATE_PROGRAM_NOT_FOUND`, an appointment segment
        `ERR_AGENCY_APPOINTMENT_NOT_FOUND`, a closing protection letter segment
        `ERR_CPL_NOT_FOUND`, a policy file segment `ERR_POLICY_FILE_NOT_FOUND`, a
        remittance statement segment `ERR_REMITTANCE_STATEMENT_NOT_FOUND`, an escrow
        account segment `ERR_ESCROW_ACCOUNT_NOT_FOUND`, an escrow audit segment
        `ERR_ESCROW_AUDIT_NOT_FOUND`, an audit finding segment
        `ERR_AUDIT_FINDING_NOT_FOUND`, and an agency claim segment
        `ERR_AGENCY_CLAIM_NOT_FOUND`."

        Design: Corner/errors/unknown_ids_report_the_resource_specific_not_found_returns_404
        """
        response = api._request("GET", f"/{path}/{NON_EXISTENT_UUID}", headers=OFFICER)

        validate_error(response, error_id.value, 404)


class TestAdmissionGates:
    """The financial minimums, the license expiry and the appointment gate."""

    def test_appointment_before_an_accepted_review_reports_the_review_gate(
        self, api, state_program
    ):
        """The financial-review gate answers before the active-appointment gate.

        PRD: "its `financial_review_status` must be `ACCEPTED`, else
        `ERR_FINANCIAL_REVIEW_NOT_ACCEPTED` (HTTP 422), and it must already hold at
        least one appointment in some state whose `status` is `ACTIVE`, else
        `ERR_NO_ACTIVE_APPOINTMENT_IN_STATE` (HTTP 422)."

        Design: Corner/errors/financial_and_licensing_gates_reject_deficient_agencies_returns_422
        """
        agency = create_agency(api)
        create_appointment(api, agency["id"], state_program["id"])

        response = api.decide_appointment(
            agency["id"], factories.appointment_decision_payload("APPOINT"), ANALYST
        )

        validate_error(response, ApiErrorId.ERR_FINANCIAL_REVIEW_NOT_ACCEPTED.value, 422)

    def test_staged_eo_limit_below_the_minimum_is_rejected(self, api):
        """Acceptance reads the staged E&O limit against a hard floor.

        PRD: "The staged errors-and-omissions limit in
        `submitted_eo_policy_limit_cents` must be at least two hundred fifty thousand
        dollars — 25,000,000 cents — and anything below that is rejected with
        `ERR_EO_LIMIT_BELOW_MINIMUM` (HTTP 422)."

        Design: Corner/errors/financial_and_licensing_gates_reject_deficient_agencies_returns_422
        """
        agency = create_agency(api)
        submit_financial_review(api, agency["id"], submitted_eo_policy_limit_cents=24_999_999)

        response = api.decide_financial_review(
            agency["id"], factories.financial_review_decision_payload("ACCEPT"), ANALYST
        )

        validate_error(response, ApiErrorId.ERR_EO_LIMIT_BELOW_MINIMUM.value, 422)
        after = read_agency(api, agency["id"])
        assert after["financial_review_status"] == "SUBMITTED", (
            "a refused acceptance leaves the review at SUBMITTED, got "
            f"{after['financial_review_status']}"
        )

    def test_staged_net_worth_below_the_minimum_is_rejected(self, api):
        """Acceptance reads the staged net worth against its own hard floor.

        PRD: "The staged audited net worth in `submitted_net_worth_cents` must be at
        least fifty thousand dollars — 5,000,000 cents — and anything below that is
        rejected with `ERR_NET_WORTH_BELOW_MINIMUM` (HTTP 422)."

        Design: Corner/errors/financial_and_licensing_gates_reject_deficient_agencies_returns_422
        """
        agency = create_agency(api)
        submit_financial_review(api, agency["id"], submitted_net_worth_cents=4_999_999)

        response = api.decide_financial_review(
            agency["id"], factories.financial_review_decision_payload("ACCEPT"), ANALYST
        )

        validate_error(response, ApiErrorId.ERR_NET_WORTH_BELOW_MINIMUM.value, 422)

    def test_a_license_expiring_on_the_clock_date_is_already_expired(
        self, api, state_program
    ):
        """Verification demands a confirmed expiry strictly after today.

        PRD: "the confirmed `verified_expires_on` must fall strictly after the
        logical clock's current date — a license expiring today is already expired
        for this purpose — else `ERR_LICENSE_EXPIRED` (HTTP 422)"

        Design: Corner/errors/financial_and_licensing_gates_reject_deficient_agencies_returns_422
        """
        agency = create_agency(api)
        submit_financial_review(api, agency["id"], submitted_net_worth_cents=5_000_000)
        accepted = decide_financial_review(api, agency["id"], "ACCEPT")
        assert accepted["financial_review_status"] == "ACCEPTED", (
            "a net worth of exactly 5,000,000 sits at the minimum and is accepted, "
            f"but the review reads {accepted['financial_review_status']}"
        )
        assert accepted["eo_policy_limit_cents"] == 200_000_000, (
            "acceptance mirrors the staged E&O limit onto the effective field, got "
            f"{accepted['eo_policy_limit_cents']}"
        )
        appointment = create_appointment(api, agency["id"], state_program["id"])

        response = api.verify_license(
            appointment["id"],
            factories.license_verification_payload(
                "VERIFY", verified_expires_on="2026-07-31"
            ),
            ANALYST,
        )

        validate_error(response, ApiErrorId.ERR_LICENSE_EXPIRED.value, 422)

    def test_appointment_without_an_active_state_appointment_is_rejected(
        self, api, state_program
    ):
        """An accepted review is not enough: some appointment must be `ACTIVE`.

        PRD: "it must already hold at least one appointment in some state whose
        `status` is `ACTIVE`, else `ERR_NO_ACTIVE_APPOINTMENT_IN_STATE` (HTTP 422)"

        Design: Corner/errors/financial_and_licensing_gates_reject_deficient_agencies_returns_422
        """
        agency = create_agency(api)
        submit_financial_review(api, agency["id"])
        decide_financial_review(api, agency["id"], "ACCEPT")
        appointment = create_appointment(api, agency["id"], state_program["id"])

        response = api.decide_appointment(
            agency["id"], factories.appointment_decision_payload("APPOINT"), ANALYST
        )
        validate_error(response, ApiErrorId.ERR_NO_ACTIVE_APPOINTMENT_IN_STATE.value, 422)

        verified = verify_license(api, appointment["id"])
        assert verified["status"] == "ACTIVE", (
            f"verification must activate the appointment, got {verified['status']}"
        )
        appointed = decide_appointment(api, agency["id"], "APPOINT")
        assert_appointment_status(appointed, "APPOINTED")
        assert_posture(appointed, "OPEN")
