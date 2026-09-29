"""Schema validation, declared defaults, computed fields, immutable snapshots and parent references."""
import pytest
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.assertions import assert_immutable_common_fields
from test_helpers.test_users import make_benefits_analyst_headers
from test_helpers.fixtures import (
    ADMIN,
    ANALYST,
    TREASURY,
    file_capital_position,
    onboard_carrier,
    open_diligence_review,
)


class TestProductTypeSchemaValidation:
    def test_registering_a_product_without_a_mec_status_is_a_schema_violation(self, api):
        """`mec_status` has no default, so omitting it is rejected outright.

        A product registration supplies "its `mec_status`", and "`mec_status` is
        either `MEC` or `NON_MEC`, and it is the switch that selects the
        cost-recovery variant used in disposition analysis." Schema validation
        "covers all of the following in one pass: required fields present", and
        "Every one of those failures reports `ERR_INVALID_REQUEST`."

        Design: Corner/entities/product_type_create_missing_mec_status_returns_invalid_request
        """
        carrier = onboard_carrier(
            api,
            legal_name="Fjord Life",
            naic_code="71006",
            am_best_rating="A",
            statutory_surplus_usd=500_000_000.00,
            domicile_state="MT",
        )

        validate_error(
            api.create_product_type(
                {
                    "carrier_id": carrier["id"],
                    "product_name": "Fjord GA BOLI",
                    "account_type": "GENERAL",
                    "disclosed_me_charge_bps": 20,
                    "guaranteed_min_crediting_bps": 100,
                },
                ADMIN,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        items, meta = validate_paginated(
            api.list_product_types(ADMIN, params={"carrier_id": carrier["id"]})
        )
        assert meta["total_count"] == 0, "the rejected registration stores nothing"
        assert items == []

    def test_an_undeclared_account_type_and_a_negative_charge_are_both_refused(self, api):
        """The enum and the non-negativity rule are enforced by the same pass.

        "`account_type` is one of `GENERAL`, `SEPARATE` or `HYBRID`", and "Both
        basis-point inputs must be zero or greater." Schema validation covers
        "enum-valued fields carrying only declared members, USD amounts
        non-negative and carrying at most 2 decimal places, basis-point values
        integral", and "Every one of those failures reports
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/product_type_account_type_rejects_an_undeclared_enum_member
        """
        carrier = onboard_carrier(
            api,
            legal_name="Ivory Life",
            naic_code="71009",
            am_best_rating="A",
            statutory_surplus_usd=500_000_000.00,
            domicile_state="UT",
        )

        validate_error(
            api.create_product_type(
                {
                    "carrier_id": carrier["id"],
                    "product_name": "Ivory Bad Account",
                    "account_type": "MODIFIED_SEPARATE",
                    "mec_status": "NON_MEC",
                    "disclosed_me_charge_bps": 20,
                    "guaranteed_min_crediting_bps": 100,
                },
                ADMIN,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        validate_error(
            api.create_product_type(
                {
                    "carrier_id": carrier["id"],
                    "product_name": "Ivory Negative Charge",
                    "account_type": "GENERAL",
                    "mec_status": "NON_MEC",
                    "disclosed_me_charge_bps": -5,
                    "guaranteed_min_crediting_bps": 100,
                },
                ADMIN,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        _items, meta = validate_paginated(
            api.list_product_types(ADMIN, params={"carrier_id": carrier["id"]})
        )
        assert meta["total_count"] == 0, "neither rejected registration stores a product"


class TestDeclaredDefaults:
    def test_omitted_optional_inputs_fall_back_to_their_declared_defaults(self, api):
        """An omitted optional input is not null; it is the value the contract names.

        A plan takes "optionally the `discount_rate_bps` used by the
        projected-benefit view, which defaults to 500 basis points", and "A new
        plan opens in `ACTIVE` with `accrual_liability_usd`, `pbo_liability_usd`
        and `matched_cash_value_usd` all at 0.00, with `funding_posture` at
        `FUNDED` and `funded_ratio_bps` at 10000, which is the convention for a
        plan with no liabilities at all." An employee takes "optionally
        `officer_flag`, which defaults to false", and "A new employee record
        starts with `insurable_interest_status` at `NOT_ESTABLISHED` and
        `employment_status` at `ACTIVE`."

        Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
        """
        plan = validate_success(
            api.create_nqdc_plan(
                {"plan_name": "Default Rate SERP", "plan_type": "SERP"}, TREASURY
            ),
            201,
        )
        assert plan["discount_rate_bps"] == 500
        assert plan["status"] == "ACTIVE"
        assert plan["accrual_liability_usd"] == pytest.approx(0.00, abs=0.01)
        assert plan["pbo_liability_usd"] == pytest.approx(0.00, abs=0.01)
        assert plan["matched_cash_value_usd"] == pytest.approx(0.00, abs=0.01)
        assert plan["funded_ratio_bps"] == 10000
        assert plan["funding_posture"] == "FUNDED"

        employee = validate_success(
            api.create_employee(
                {
                    "full_name": "Ines Roth",
                    "employee_number": "E-7101",
                    "annual_salary_usd": 300_000.00,
                },
                ANALYST,
            ),
            201,
        )
        assert employee["officer_flag"] is False, "the omitted flag defaults to false"
        assert employee["insurable_interest_status"] == "NOT_ESTABLISHED", (
            "interest is derived later, never at registration"
        )
        assert employee["employment_status"] == "ACTIVE"


class TestComputedDiligenceScore:
    def test_the_score_is_derived_at_submission_and_client_values_are_ignored(self, api):
        """The three components and the weighted score are recomputed server-side.

        "On success the server recomputes `rating_points`, `surplus_points`,
        `concentration_points` and `financial_strength_score` from scratch,
        records the acting `X-User-ID` as `submitted_by_user_id`, and increments
        the file's `version` by 1." A rating of `A` scores 80 points, three
        half-billion-dollar steps of surplus score 30, a carrier at zero
        concentration keeps the full 100 because "this component keeps one decimal
        place", and with "half the weight on `rating_points`, three tenths on
        `surplus_points`, one fifth on `concentration_points`" the weighted total
        rounds to 69.

        Design: Corner/entities/diligence_review_score_is_computed_and_client_values_are_ignored
        """
        file_capital_position(
            api,
            as_of_date="2026-06-30T00:00:00Z",
            tier1_capital_usd=1_000_000_000.00,
            total_assets_usd=12_000_000_000.00,
        )
        carrier = onboard_carrier(
            api,
            legal_name="Granite Life",
            naic_code="71007",
            am_best_rating="A",
            statutory_surplus_usd=1_500_000_000.00,
            domicile_state="ID",
        )
        review = open_diligence_review(
            api, carrier["id"], review_year=2026, financial_strength_score=99
        )
        assert review["info_request_count"] == 0
        assert review["status"] == "DRAFT"

        submitted = validate_success(
            api.submit_diligence_review(
                review["id"], make_benefits_analyst_headers("analyst-9")
            )
        )
        assert submitted["rating_points"] == 80
        assert submitted["surplus_points"] == 30
        assert submitted["concentration_points"] == pytest.approx(100.0, abs=0.01)
        assert submitted["financial_strength_score"] == 69, (
            "the client-supplied score is ignored and the weighted total is recomputed"
        )
        assert submitted["status"] == "UNDER_REVIEW"
        assert submitted["submitted_by_user_id"] == "analyst-9"
        assert submitted["info_request_count"] == 0


class TestCapitalSnapshotImmutability:
    def test_a_filed_snapshot_carries_no_version_and_is_only_superseded(self, api):
        """A snapshot is an append-only record, so it has no version to bump.

        "A filed capital snapshot and a posted carrier statement period are both
        append-only records of something that happened, and neither is ever
        edited after the fact. Both therefore carry only `id` and `created_at`:
        they have no `updated_at` field and no `version` field at all, and no
        operation in this specification mutates either of them." A later filing
        does not overwrite the earlier one, because a calculation "uses **the
        latest snapshot**, defined as the snapshot with the greatest
        `as_of_date`".

        Design: Corner/entities/capital_position_is_immutable_with_no_version_and_no_write_back
        """
        first = file_capital_position(
            api,
            as_of_date="2026-03-31T00:00:00Z",
            tier1_capital_usd=900_000_000.00,
            total_assets_usd=11_000_000_000.00,
        )
        second = file_capital_position(
            api,
            as_of_date="2026-06-30T00:00:00Z",
            tier1_capital_usd=1_000_000_000.00,
            total_assets_usd=12_000_000_000.00,
        )

        fetched = validate_success(api.get_capital_position(first["id"], TREASURY))
        assert_immutable_common_fields(fetched)
        assert fetched["tier1_capital_usd"] == pytest.approx(900_000_000.00, abs=0.01)
        assert fetched["as_of_date"].startswith("2026-03-31")
        assert fetched["recorded_by_user_id"] == "treasury-1", (
            "the server stamps the acting user, not a client-supplied value"
        )

        later = validate_success(api.get_capital_position(second["id"], TREASURY))
        assert_immutable_common_fields(later)
        assert later["tier1_capital_usd"] == pytest.approx(1_000_000_000.00, abs=0.01), (
            "the newer snapshot stands beside the earlier one as the latest denominator"
        )


class TestParentReferenceResolution:
    def test_a_consent_record_for_an_unknown_employee_is_a_missing_employee(self, api):
        """The body's foreign key resolves to the employee-specific 404.

        "Foreign keys supplied in a request body are resolved in the order the
        endpoint declares its input fields, using the same per-entity error
        identifiers", and among those identifiers "a missing employee
        `ERR_EMPLOYEE_NOT_FOUND`". "Every one of these is HTTP 404."

        Design: Corner/entities/consent_record_create_with_unknown_employee_returns_employee_not_found
        """
        validate_error(
            api.create_consent_record(
                {
                    "employee_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d3",
                    "coverage_start_date": "2026-08-01T00:00:00Z",
                    "coverage_end_date": "2027-07-31T00:00:00Z",
                    "consent_form_reference": "CF-0000",
                    "notice_and_consent_version": "NC-2026.1",
                },
                ANALYST,
            ),
            "ERR_EMPLOYEE_NOT_FOUND",
            404,
        )

        items, meta = validate_paginated(api.list_consent_records(ANALYST))
        assert meta["total_count"] == 0, "the refused create stores no consent record"
        assert items == []

    def test_a_request_may_not_name_one_carriers_product_under_another_carrier(self, api):
        """The two references must agree even before any gate is run.

        "Even at draft time the product must belong to the carrier named on the
        same request; a product whose own `carrier_id` differs from the request's
        `carrier_id` is refused with `ERR_PRODUCT_CARRIER_MISMATCH` (HTTP 422)."
        The matching pair is accepted and "A drafted request sits in `DRAFT` with
        `reserved_premium_usd` at 0.00" and "`notice_required` false".

        Design: Corner/entities/purchase_request_naming_another_carriers_product_returns_mismatch
        """
        juniper = onboard_carrier(
            api,
            legal_name="Juniper Life",
            naic_code="71010",
            am_best_rating="A",
            statutory_surplus_usd=500_000_000.00,
            domicile_state="KS",
        )
        kestrel = onboard_carrier(
            api,
            legal_name="Kestrel Life",
            naic_code="71011",
            am_best_rating="A",
            statutory_surplus_usd=500_000_000.00,
            domicile_state="OK",
        )
        juniper_product = validate_success(
            api.create_product_type(
                {
                    "carrier_id": juniper["id"],
                    "product_name": "Juniper GA BOLI",
                    "account_type": "GENERAL",
                    "mec_status": "NON_MEC",
                    "disclosed_me_charge_bps": 20,
                    "guaranteed_min_crediting_bps": 100,
                },
                ADMIN,
            ),
            201,
        )
        kestrel_product = validate_success(
            api.create_product_type(
                {
                    "carrier_id": kestrel["id"],
                    "product_name": "Kestrel GA BOLI",
                    "account_type": "GENERAL",
                    "mec_status": "NON_MEC",
                    "disclosed_me_charge_bps": 20,
                    "guaranteed_min_crediting_bps": 100,
                },
                ADMIN,
            ),
            201,
        )
        employee = validate_success(
            api.create_employee(
                {
                    "full_name": "Omar Vela",
                    "employee_number": "E-7201",
                    "annual_salary_usd": 500_000.00,
                },
                ANALYST,
            ),
            201,
        )

        crossed = {
            "carrier_id": juniper["id"],
            "product_type_id": kestrel_product["id"],
            "employee_id": employee["id"],
            "single_premium_usd": 1_000_000.00,
            "face_amount_usd": 3_000_000.00,
            "requested_effective_date": "2026-08-15T00:00:00Z",
        }
        validate_error(
            api.create_purchase_request(crossed, ANALYST),
            "ERR_PRODUCT_CARRIER_MISMATCH",
            422,
        )

        matched = dict(crossed, product_type_id=juniper_product["id"])
        drafted = validate_success(api.create_purchase_request(matched, ANALYST), 201)
        assert drafted["status"] == "DRAFT"
        assert drafted["reserved_premium_usd"] == pytest.approx(0.00, abs=0.01)
        assert drafted["notice_required"] is False
