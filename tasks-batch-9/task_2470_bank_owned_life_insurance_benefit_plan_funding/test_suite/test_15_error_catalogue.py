"""Authentication, the entity-specific not-found family, product closure and consent revocation."""
import pytest
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.fixtures import (
    ANALYST,
    RISK,
    TREASURY,
    draft_purchase_request,
    execute_consent,
    in_force_policy,
    insured_employee,
    onboard_carrier,
    post_valuation,
    register_employee,
    register_product_type,
    submitted_purchase_request,
)


BASALT = {
    "legal_name": "Basalt Life",
    "naic_code": "71028",
    "am_best_rating": "A_PLUS",
    "statutory_surplus_usd": 400_000_000.00,
    "domicile_state": "AL",
}
CINDER = {
    "legal_name": "Cinder Life",
    "naic_code": "71029",
    "am_best_rating": "A_PLUS",
    "statutory_surplus_usd": 400_000_000.00,
    "domicile_state": "AR",
}

FERRIS = {
    "full_name": "Dana Ferris",
    "employee_number": "E-9201",
    "annual_salary_usd": 700_000.00,
    "officer_flag": False,
}
HADDAD = {
    "full_name": "Amir Haddad",
    "employee_number": "E-9301",
    "annual_salary_usd": 600_000.00,
    "officer_flag": False,
}


class TestAuthenticationHeaders:
    def test_an_absent_or_empty_identity_header_fails_before_anything_else(self, api):
        """Both headers are mandatory, and an empty value counts as absent.

        "Every request to every endpoint must carry two headers: `X-User-ID`,
        identifying the acting operator, and `X-User-Role`, naming the role that
        operator is acting under. If either header is absent or present but empty,
        the request fails with `ERR_UNAUTHENTICATED` (HTTP 401) before any other
        processing occurs." The ordering is explicit as well: "Header presence is
        checked first, then role eligibility for the endpoint".

        Design: Corner/errors/missing_x_user_headers_return_unauthenticated
        """
        carrier = onboard_carrier(
            api,
            legal_name="Argus Life",
            naic_code="71027",
            am_best_rating="A",
            statutory_surplus_usd=500_000_000.00,
            domicile_state="KS",
        )

        for headers, description in (
            ({"X-User-Role": "RiskOfficer"}, "no X-User-ID header at all"),
            ({"X-User-ID": "risk-1"}, "no X-User-Role header at all"),
            (
                {"X-User-ID": "", "X-User-Role": "RiskOfficer"},
                "an X-User-ID present but empty",
            ),
        ):
            response = api.get_carrier(carrier["id"], headers)
            body = response.json()
            assert body["response_type"] == "error", description
            error = validate_error(response, "ERR_UNAUTHENTICATED", 401)
            assert error["message"], "the rejection carries a human-readable message"

        unchanged = validate_success(api.get_carrier(carrier["id"], RISK))
        assert unchanged["version"] == 1, "the rejected reads changed nothing"
        assert unchanged["legal_name"] == "Argus Life"


class TestNotFoundFamily:
    def test_each_entity_family_reports_its_own_missing_identifier(self, api):
        """A well-formed identifier that names nothing gets the owning entity's code.

        "a missing carrier reports `ERR_CARRIER_NOT_FOUND`, a missing product type
        `ERR_PRODUCT_TYPE_NOT_FOUND`, a missing employee `ERR_EMPLOYEE_NOT_FOUND`,
        a missing diligence review `ERR_REVIEW_NOT_FOUND`, a missing purchase
        request `ERR_REQUEST_NOT_FOUND`, a missing policy `ERR_POLICY_NOT_FOUND`, a
        missing death benefit claim `ERR_CLAIM_NOT_FOUND`, a missing deferred
        compensation plan `ERR_PLAN_NOT_FOUND`, and a missing disposition analysis
        `ERR_ANALYSIS_NOT_FOUND`. A consent record, a posted statement period, a
        beneficiary allocation, a participant liability, a capital snapshot or a
        risk assessment that cannot be found all report `ERR_RECORD_NOT_FOUND`.
        Every one of these is HTTP 404."

        Design: Corner/errors/unknown_ids_return_the_entity_specific_not_found_error
        """
        cases = (
            (api.get_product_type, "11111111-1111-4111-8111-111111111111",
             "ERR_PRODUCT_TYPE_NOT_FOUND"),
            (api.get_diligence_review, "22222222-2222-4222-8222-222222222222",
             "ERR_REVIEW_NOT_FOUND"),
            (api.get_purchase_request, "33333333-3333-4333-8333-333333333333",
             "ERR_REQUEST_NOT_FOUND"),
            (api.get_policy, "44444444-4444-4444-8444-444444444444",
             "ERR_POLICY_NOT_FOUND"),
            (api.get_death_claim, "55555555-5555-4555-8555-555555555555",
             "ERR_CLAIM_NOT_FOUND"),
            (api.get_nqdc_plan, "66666666-6666-4666-8666-666666666666",
             "ERR_PLAN_NOT_FOUND"),
            (api.get_exchange_analysis, "77777777-7777-4777-8777-777777777777",
             "ERR_ANALYSIS_NOT_FOUND"),
            (api.get_consent_record, "88888888-8888-4888-8888-888888888888",
             "ERR_RECORD_NOT_FOUND"),
            (api.get_employee, "99999999-9999-4999-8999-999999999999",
             "ERR_EMPLOYEE_NOT_FOUND"),
        )
        for read, unknown_id, expected_error in cases:
            validate_error(read(unknown_id, RISK), expected_error, 404)


class TestProductClosureBlocksNewBusiness:
    def test_two_low_yield_statements_close_the_product_and_refuse_clearance(self, api):
        """The streak counter belongs to the product, and closure is terminal.

        "the product's `consecutive_low_yield_count` is incremented by 1 when the
        posting's `net_yield_bps` is **below** 150 basis points, and reset to 0
        otherwise. Sixth, once that count reaches 2 or more, the product is driven
        to `CLOSED_TO_NEW` — from `OPEN` or from `ON_WATCH`, with identical
        treatment on both paths — and the owning carrier's `watch_list_flag` is set
        true". Clearance then requires that "The product type must be in `OPEN` or
        `ON_WATCH`; a product in `CLOSED_TO_NEW` fails with
        `ERR_PRODUCT_CLOSED_TO_NEW` (HTTP 422)."

        Design: Corner/errors/two_low_yield_valuations_close_the_product_and_block_clear_diligence
        """
        context = in_force_policy(
            api,
            carrier_overrides=BASALT,
            product_overrides={
                "product_name": "Basalt GA BOLI",
                "disclosed_me_charge_bps": 20,
            },
            employee_overrides=FERRIS,
            consent_overrides={"consent_form_reference": "CF-9201"},
            request_overrides={
                "single_premium_usd": 2_000_000.00,
                "face_amount_usd": 6_000_000.00,
            },
            policy_overrides={"policy_number": "BS-0001"},
        )
        gallo = insured_employee(
            api,
            employee_overrides={
                "full_name": "Rosa Gallo",
                "employee_number": "E-9202",
                "annual_salary_usd": 650_000.00,
            },
            consent_overrides={"consent_form_reference": "CF-9202"},
        )
        waiting = submitted_purchase_request(
            api,
            context["carrier_id"],
            context["product_type_id"],
            gallo["employee_id"],
            single_premium_usd=1_000_000.00,
            face_amount_usd=3_000_000.00,
            requested_effective_date="2026-08-20T00:00:00Z",
        )
        assert waiting["status"] == "SUBMITTED"

        first = post_valuation(
            api,
            context["policy_id"],
            period_start_date="2026-08-15T00:00:00Z",
            as_of_date="2026-09-15T00:00:00Z",
            credited_interest_usd=30_000.00,
            mortality_expense_charge_usd=15_000.00,
            gross_crediting_rate_bps=150,
        )
        assert first["cash_value_usd"] == pytest.approx(2_015_000.00, abs=0.01)
        assert first["net_yield_bps"] == 75
        assert first["me_charge_bps"] == 75
        assert first["me_drift_bps"] == 55

        watched = validate_success(
            api.get_product_type(context["product_type_id"], RISK)
        )
        assert watched["status"] == "ON_WATCH", "a drift above 25 trips the watch"
        assert watched["consecutive_low_yield_count"] == 1

        second = post_valuation(
            api,
            context["policy_id"],
            period_start_date="2026-09-15T00:00:00Z",
            as_of_date="2026-10-15T00:00:00Z",
            credited_interest_usd=30_000.00,
            mortality_expense_charge_usd=15_000.00,
            gross_crediting_rate_bps=150,
        )
        assert second["cash_value_usd"] == pytest.approx(2_030_000.00, abs=0.01)
        assert second["net_yield_bps"] == 74
        assert second["me_charge_bps"] == 74
        assert second["me_drift_bps"] == 54

        closed = validate_success(api.get_product_type(context["product_type_id"], RISK))
        assert closed["status"] == "CLOSED_TO_NEW"
        assert closed["consecutive_low_yield_count"] == 2

        carrier = validate_success(api.get_carrier(context["carrier_id"], TREASURY))
        assert carrier["watch_list_flag"] is True
        assert carrier["in_force_cash_value_usd"] == pytest.approx(2_030_000.00, abs=0.01)
        assert carrier["concentration_bps"] == 20
        assert carrier["status"] == "AUTHORIZED", "twenty basis points restricts nobody"

        review = validate_success(api.get_diligence_review(context["review_id"], RISK))
        assert review["status"] == "APPROVED", (
            "only files sitting under review are pulled back for more information"
        )

        validate_error(
            api.clear_purchase_request_diligence(waiting["id"], RISK),
            "ERR_PRODUCT_CLOSED_TO_NEW",
            422,
        )
        assert (
            validate_success(api.get_purchase_request(waiting["id"], RISK))["status"]
            == "SUBMITTED"
        )
        assert validate_success(api.get_carrier(context["carrier_id"], TREASURY))[
            "reserved_premium_usd"
        ] == pytest.approx(0.00, abs=0.01)


class TestPartialSurrenderCeiling:
    def test_a_withdrawal_above_the_cash_value_is_refused_before_it_is_priced(self, api):
        """The policy's own cash value is the ceiling on a partial withdrawal.

        "For a partial surrender the requested withdrawal must not exceed the
        policy's `cash_surrender_value_usd`, and an excessive request is rejected
        with `ERR_SURRENDER_EXCEEDS_CASH_VALUE` (HTTP 422)." A withdrawal below the
        ceiling is priced instead: "Under `FIFO_BASIS_FIRST` the withdrawal recovers
        cost basis first, so the `taxable_gain_usd` is the withdrawal minus the
        policy's `cost_basis_usd`, or zero if the basis is the larger", and
        "`surrender_charge_usd` is the gross amount multiplied by the tier's basis
        points divided by ten thousand, rounded half up to 2 decimal places."

        Design: Corner/errors/partial_surrender_above_the_cash_value_is_rejected_then_accepted_below_it
        """
        context = in_force_policy(
            api,
            carrier_overrides=CINDER,
            product_overrides={"product_name": "Cinder GA BOLI"},
            employee_overrides=HADDAD,
            consent_overrides={"consent_form_reference": "CF-9301"},
            request_overrides={
                "single_premium_usd": 1_000_000.00,
                "face_amount_usd": 3_000_000.00,
            },
            policy_overrides={"policy_number": "CD-0001"},
        )
        policy = validate_success(api.get_policy(context["policy_id"], TREASURY))
        assert policy["cash_surrender_value_usd"] == pytest.approx(1_000_000.00, abs=0.01)
        assert policy["policy_year"] == 1
        version = policy["version"]

        validate_error(
            api.create_exchange_analysis(
                {
                    "policy_id": context["policy_id"],
                    "disposition_type": "PARTIAL_SURRENDER",
                    "requested_withdrawal_usd": 1_200_000.00,
                    "expected_policy_version": version,
                },
                TREASURY,
            ),
            "ERR_SURRENDER_EXCEEDS_CASH_VALUE",
            422,
        )
        _rows, meta = validate_paginated(
            api.list_exchange_analyses(TREASURY, params={"policy_id": context["policy_id"]})
        )
        assert meta["total_count"] == 0, "the refused create models nothing"
        untouched = validate_success(api.get_policy(context["policy_id"], TREASURY))
        assert untouched["status"] == "IN_FORCE"
        assert untouched["version"] == version, "the refused create bumps nothing"

        analysis = validate_success(
            api.create_exchange_analysis(
                {
                    "policy_id": context["policy_id"],
                    "disposition_type": "PARTIAL_SURRENDER",
                    "requested_withdrawal_usd": 250_000.00,
                    "expected_policy_version": version,
                },
                TREASURY,
            ),
            201,
        )
        assert analysis["cost_recovery_method"] == "FIFO_BASIS_FIRST"
        assert analysis["taxable_gain_usd"] == pytest.approx(0.00, abs=0.01)
        assert analysis["surrender_charge_usd"] == pytest.approx(15_000.00, abs=0.01), (
            "a first-year contract carries six hundred basis points"
        )
        assert analysis["tax_liability_usd"] == pytest.approx(0.00, abs=0.01)
        assert analysis["net_proceeds_usd"] == pytest.approx(235_000.00, abs=0.01)
        assert analysis["status"] == "DRAFT"
        assert analysis["resulting_policy_id"] is None


class TestRevokedConsentCoverage:
    def test_a_revoked_window_is_reported_as_expired_rather_than_missing(self, api):
        """A signature that was withdrawn is a different failure from no signature.

        Submission requires that "that covering record must not have been revoked,
        and its `coverage_end_date` must not lie before the logical clock; a
        covering record that has been revoked or has expired, or whose window has
        run out under the current clock, fails with `ERR_CONSENT_EXPIRED`."
        Revocation leaves the employee's posture alone here because "if another
        executed record survives, the employee's posture is left alone", so the
        insurable-interest branch of the same priority band cannot be the failure.

        Design: Corner/errors/submit_with_a_revoked_consent_returns_consent_expired
        """
        carrier = onboard_carrier(
            api,
            legal_name="Dune Life",
            naic_code="71030",
            am_best_rating="A",
            statutory_surplus_usd=500_000_000.00,
            domicile_state="NH",
        )
        product = register_product_type(
            api, carrier["id"], product_name="Dune GA BOLI", account_type="GENERAL"
        )
        iyer = register_employee(
            api,
            full_name="Ravi Iyer",
            employee_number="E-9401",
            annual_salary_usd=600_000.00,
        )
        covering = execute_consent(
            api,
            iyer["id"],
            coverage_start_date="2026-08-01T00:00:00Z",
            coverage_end_date="2027-07-31T00:00:00Z",
            consent_form_reference="CF-9401",
        )
        request = draft_purchase_request(
            api,
            carrier["id"],
            product["id"],
            iyer["id"],
            single_premium_usd=1_000_000.00,
            face_amount_usd=3_000_000.00,
            requested_effective_date="2026-09-01T00:00:00Z",
        )
        surviving = execute_consent(
            api,
            iyer["id"],
            coverage_start_date="2027-09-01T00:00:00Z",
            coverage_end_date="2028-08-31T00:00:00Z",
            consent_form_reference="CF-9402",
        )
        revoked = validate_success(api.revoke_consent_record(covering["id"], ANALYST))
        assert revoked["status"] == "REVOKED"
        assert revoked["executed_at"].startswith("2026-08-01T00:00:00"), (
            "the withdrawn record keeps the instant it was signed"
        )
        assert (
            validate_success(api.get_consent_record(surviving["id"], ANALYST))["status"]
            == "EXECUTED"
        )
        assert (
            validate_success(api.get_employee(iyer["id"], ANALYST))[
                "insurable_interest_status"
            ]
            == "ESTABLISHED"
        )

        validate_error(
            api.submit_purchase_request(request["id"], ANALYST), "ERR_CONSENT_EXPIRED", 422
        )

        after = validate_success(api.get_purchase_request(request["id"], ANALYST))
        assert after["status"] == "DRAFT"
        assert after["version"] == 1, (
            "the later window covers no part of the requested effective date"
        )
