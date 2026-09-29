"""Entity contracts: what a create response carries, what the declared defaults
are, which bodies are malformed, and which foreign keys must resolve."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_common_fields
from test_helpers.fixtures import (
    determine_withdrawal_event,
    file_certified_valuations,
    file_contribution_record,
    get_employer,
    get_plan,
    register_controlled_group,
    register_employer,
    register_plan,
    report_withdrawal_event,
)
from test_helpers.test_users import (
    FUND_ADMINISTRATOR_HEADERS,
    PLAN_ACTUARY_HEADERS,
    PLAN_TRUSTEE_HEADERS,
)
from test_helpers.types import CoveredWorkStatus, Industry, ReportedCause

UNKNOWN_ID = "00000000-0000-0000-0000-0000000000ff"
UNKNOWN_PLAN_ID = "00000000-0000-0000-0000-0000000000a1"
UNKNOWN_GROUP_ID = "00000000-0000-0000-0000-0000000000b2"


class TestPlanRegistrationShape:
    def test_a_new_plan_reports_every_declared_field_and_both_counters_at_zero(self, api):
        """The create response itself carries the policy choices as filed and the two
        server-maintained counters at zero.

        PRD 3.1: "Two counters on the plan are maintained by the server and start at 0.
        `employer_count` is the number of employers registered under the plan, counted
        regardless of their withdrawal status."

        Design: Corner/entities/plan_creation_returns_every_declared_field_with_zeroed_counters
        """
        payload = {
            "name": "Stagehands Local 22 Pension Fund",
            "industry": "ENTERTAINMENT",
            "allocation_method": "ROLLING_5",
            "de_minimis_variant": "PLAN_ELECTED_HIGH",
            "interest_rate_bps": 650,
            "unattributable_uvb_cents": 25_000_000,
            "mass_withdrawal_declared": True,
        }
        plan = validate_success(api.create_plan(payload, FUND_ADMINISTRATOR_HEADERS), 201)

        assert plan["name"] == "Stagehands Local 22 Pension Fund"
        assert plan["industry"] == "ENTERTAINMENT"
        assert plan["allocation_method"] == "ROLLING_5"
        assert plan["de_minimis_variant"] == "PLAN_ELECTED_HIGH"
        assert plan["interest_rate_bps"] == 650
        assert plan["unattributable_uvb_cents"] == 25_000_000
        assert plan["mass_withdrawal_declared"] is True
        assert plan["employer_count"] == 0
        assert plan["issued_assessment_count"] == 0

        assert_common_fields(plan)
        assert plan["version"] == 1
        assert plan["created_at"].startswith("2026-08-01T00:00:00")
        assert plan["updated_at"].startswith("2026-08-01T00:00:00")

    def test_a_plan_filed_with_only_its_required_fields_takes_the_declared_defaults(self, api):
        """Omitting the policy choices yields GENERAL, PRESUMPTIVE and STATUTORY rather than
        any other plausible election.

        PRD 3.1: "The `allocation_method` records which statutory method the plan has adopted
        for allocating unfunded vested benefits and is one of `PRESUMPTIVE`,
        `MODIFIED_PRESUMPTIVE`, `ROLLING_5` or `DIRECT_ATTRIBUTION`, defaulting to
        `PRESUMPTIVE`."

        Design: Corner/entities/plan_creation_omitting_optional_fields_applies_the_declared_defaults
        """
        plan = validate_success(
            api.create_plan(
                {"name": "Bakery Drivers Joint Pension Trust", "interest_rate_bps": 700},
                FUND_ADMINISTRATOR_HEADERS,
            ),
            201,
        )

        assert plan["industry"] == "GENERAL"
        assert plan["allocation_method"] == "PRESUMPTIVE"
        assert plan["de_minimis_variant"] == "STATUTORY"
        assert plan["unattributable_uvb_cents"] == 0
        assert plan["mass_withdrawal_declared"] is False
        assert plan["employer_count"] == 0
        assert plan["issued_assessment_count"] == 0

    def test_an_industry_outside_the_closed_enumeration_is_malformed(self, api):
        """MARITIME is not one of the four declared classifications, so the registration is
        refused and no plan is stored.

        PRD 3.1: "The `industry` classification selects the withdrawal-determination rule set
        and is one of `GENERAL`, `CONSTRUCTION`, `ENTERTAINMENT` or `TRUCKING`, defaulting to
        `GENERAL` when omitted."

        Design: Corner/entities/plan_creation_with_an_unknown_industry_value_is_rejected
        """
        response = api.create_plan(
            {"name": "Maritime Trades Fund", "industry": "MARITIME", "interest_rate_bps": 700},
            FUND_ADMINISTRATOR_HEADERS,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value, 400)

        _data, meta = validate_paginated(api.list_employers(FUND_ADMINISTRATOR_HEADERS))
        assert meta["total_count"] == 0


class TestEmployerRegistrationContract:
    def test_an_employer_filed_without_an_ein_is_malformed(self, api):
        """The nine-digit identification number is required outright, so its absence is a
        body-shape rejection and not a uniqueness one.

        PRD 3.1: "It carries a `legal_name` of 1 to 200 characters and an `ein` of exactly
        nine digits which must be unique across every employer in the system — a repeat is
        rejected with `ERR_DUPLICATE_EIN`."

        Design: Corner/entities/employer_creation_missing_required_ein_returns_invalid_request
        """
        plan = register_plan(api)
        group = register_controlled_group(api)

        response = api.create_employer(
            {
                "plan_id": plan["id"],
                "controlled_group_id": group["id"],
                "legal_name": "Meridian Steel Erectors LLC",
                "obligation_start_year": 2021,
            },
            FUND_ADMINISTRATOR_HEADERS,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value, 400)

        _data, meta = validate_paginated(
            api.list_employers(FUND_ADMINISTRATOR_HEADERS, {"plan_id": plan["id"]})
        )
        assert meta["total_count"] == 0
        assert get_plan(api, plan["id"])["employer_count"] == 0

    def test_reading_an_employer_returns_every_stored_registration_field(self, api):
        """The direct-attribution inputs and the initial posture fields all come back on the
        read path.

        PRD 3.1: "On registration the employer's `status` is `CONTRIBUTING`, its
        `outstanding_liability_cents` is 0, its `version` is 1, its `obligation_end_year` is
        null, its `ceased_cba_count` is 0, its `credit_watch` is false and its
        `delinquency_strikes` is 0, and the plan's `employer_count` rises by one."

        Design: Corner/entities/employer_retrieval_returns_the_stored_registration_fields
        """
        plan = register_plan(api)
        group = register_controlled_group(api)
        created = register_employer(
            api,
            plan["id"],
            group["id"],
            legal_name="Meridian Steel Erectors LLC",
            obligation_start_year=2021,
            cba_count=3,
            directly_attributed_vested_benefits_cents=500_000_000,
            directly_attributed_assets_cents=200_000_000,
        )

        employer = validate_success(
            api.get_employer(created["id"], PLAN_TRUSTEE_HEADERS), 200
        )
        assert employer["plan_id"] == plan["id"]
        assert employer["controlled_group_id"] == group["id"]
        assert employer["legal_name"] == "Meridian Steel Erectors LLC"
        assert employer["ein"] == created["ein"]
        assert len(employer["ein"]) == 9
        assert employer["obligation_start_year"] == 2021
        assert employer["covered_work_status"] == "PERFORMING"
        assert employer["cba_count"] == 3
        assert employer["directly_attributed_vested_benefits_cents"] == 500_000_000
        assert employer["directly_attributed_assets_cents"] == 200_000_000
        assert employer["status"] == "CONTRIBUTING"
        assert employer["outstanding_liability_cents"] == 0
        assert employer["credit_watch"] is False
        assert employer["delinquency_strikes"] == 0
        assert employer["ceased_cba_count"] == 0
        assert employer["obligation_end_year"] is None
        assert employer["version"] == 1

    def test_reading_an_unknown_employer_id_is_a_not_found(self, api):
        """A real employer exists alongside the probe, so the rejection has to come from path
        resolution rather than from an empty table.

        PRD 2.4: "Each identifier has its own not-found code: `plan_id` yields
        `ERR_PLAN_NOT_FOUND`, `controlled_group_id` yields `ERR_CONTROLLED_GROUP_NOT_FOUND`,
        `employer_id` yields `ERR_EMPLOYER_NOT_FOUND`"

        Design: Corner/entities/employer_get_by_unknown_id_returns_not_found
        """
        plan = register_plan(api)
        group = register_controlled_group(api)
        real = register_employer(api, plan["id"], group["id"])

        response = api.get_employer(UNKNOWN_ID, FUND_ADMINISTRATOR_HEADERS)
        validate_error(response, ApiErrorId.EMPLOYER_NOT_FOUND.value, 404)

        assert get_employer(api, real["id"])["id"] == real["id"]

    def test_an_employer_naming_an_unknown_plan_reports_the_plans_not_found_code(self, api):
        """The controlled group resolves and the plan does not, so the body foreign-key pass
        reports the plan's own code.

        PRD 2.9: "**Body foreign-key existence.** Every foreign key carried in the request
        body resolves, checked in the order the fields are declared for that endpoint,
        yielding the matching 404 code."

        Design: Corner/entities/employer_creation_with_an_unknown_plan_id_returns_not_found
        """
        group = register_controlled_group(api)

        response = api.create_employer(
            factories.employer_payload(
                UNKNOWN_PLAN_ID, group["id"], legal_name="Orphan Fabricators Inc"
            ),
            FUND_ADMINISTRATOR_HEADERS,
        )
        validate_error(response, ApiErrorId.PLAN_NOT_FOUND.value, 404)

        _data, meta = validate_paginated(api.list_employers(FUND_ADMINISTRATOR_HEADERS))
        assert meta["total_count"] == 0


class TestContributionRecordContract:
    def test_an_inverted_plan_year_interval_is_malformed_and_bumps_nothing(self, api):
        """A record running from 2025 back to 2021 is refused on its shape, so no row is
        stored and the employer's concurrency token is untouched.

        PRD 3.3: "Each record names an `employer_id` and covers a closed interval of plan
        years from `plan_year_start` to `plan_year_end`, both between 1900 and 2200 inclusive
        and with the end no earlier than the start."

        Design: Corner/entities/contribution_record_with_an_inverted_plan_year_interval_is_rejected
        """
        plan = register_plan(api)
        group = register_controlled_group(api)
        employer = register_employer(api, plan["id"], group["id"], obligation_start_year=2021)

        response = api.create_contribution_record(
            factories.contribution_record_payload(employer["id"], 2025, 2021, employer["version"]),
            FUND_ADMINISTRATOR_HEADERS,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value, 400)

        _data, meta = validate_paginated(
            api.list_contribution_records(
                FUND_ADMINISTRATOR_HEADERS, {"employer_id": employer["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert get_employer(api, employer["id"])["version"] == 1

    def test_the_stamped_employer_version_is_the_one_the_filing_produced(self, api):
        """The second filing sends version 2 and is stamped with version 3, the value the
        write itself created.

        PRD 3.3: "The filing increments the employer's `version` by one and stamps the
        resulting value onto the new record as `employer_version_at_apply`."

        Design: Corner/entities/contribution_record_system_fields_stamp_the_employer_version_at_apply
        """
        plan = register_plan(api)
        group = register_controlled_group(api)
        employer = register_employer(api, plan["id"], group["id"], obligation_start_year=2021)

        file_contribution_record(
            api,
            employer["id"],
            2016,
            2020,
            contribution_base_units=100_000,
            contribution_amount_cents=100_000_000,
            contribution_rate_cents_per_cbu=400,
        )
        sent_version = get_employer(api, employer["id"])["version"]
        assert sent_version == 2

        record = file_contribution_record(
            api,
            employer["id"],
            2021,
            2025,
            expected_employer_version=sent_version,
            contribution_base_units=250_000,
            contribution_amount_cents=250_000_000,
            contribution_rate_cents_per_cbu=1_000,
        )

        assert record["employer_version_at_apply"] == 3
        assert record["status"] == "CERTIFIED"
        assert record["supersedes_record_id"] is None
        assert record["version"] == 1
        assert record["created_at"].startswith("2026-08-01T00:00:00")
        assert get_employer(api, employer["id"])["version"] == 3


class TestComputedAndListedFields:
    def test_the_valuation_listing_counts_the_filtered_set_not_the_page(self, api):
        """Three valuations across two pages of two report total_count 3 throughout, and
        has_more falls to false only on the short second page.

        PRD 2.3: "Every list response carries `limit`, `offset`, `total_count` and `has_more`
        inside the `meta` object of the envelope."

        Design: Corner/entities/valuation_listing_paginates_with_total_count_and_has_more
        """
        plan = register_plan(api)
        file_certified_valuations(api, plan["id"], years=(2021, 2022, 2023))

        first_rows, first_meta = validate_paginated(
            api.list_plan_year_valuations(
                PLAN_ACTUARY_HEADERS, {"plan_id": plan["id"], "limit": 2, "offset": 0}
            )
        )
        assert len(first_rows) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0

        second_rows, second_meta = validate_paginated(
            api.list_plan_year_valuations(
                PLAN_ACTUARY_HEADERS, {"plan_id": plan["id"], "limit": 2, "offset": 2}
            )
        )
        assert len(second_rows) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert second_meta["offset"] == 2

        years = [row["plan_year"] for row in first_rows + second_rows]
        assert sorted(years) == [2021, 2022, 2023]

    def test_the_rules_variant_is_fixed_from_the_plans_industry_at_creation(self, api):
        """A construction plan's event is born carrying CONSTRUCTION_RULES, and keeps it
        through determination.

        PRD 3.4: "On creation the event's `status` is `REPORTED`, its `determined_type` is
        `NONE`, and its `rules_variant` is fixed from the plan's `industry`: a
        `CONSTRUCTION` plan yields `CONSTRUCTION_RULES`, an `ENTERTAINMENT` plan yields
        `ENTERTAINMENT_RULES`, and every other industry — including both `GENERAL` and
        `TRUCKING` — yields `GENERAL_RULES`."

        Design: Corner/entities/withdrawal_event_computed_rules_variant_follows_the_plan_industry
        """
        plan = register_plan(api, industry=Industry.CONSTRUCTION.value)
        group = register_controlled_group(api)
        employer = register_employer(
            api,
            plan["id"],
            group["id"],
            obligation_start_year=2021,
            covered_work_status=CoveredWorkStatus.PERFORMING.value,
            cba_count=1,
        )
        file_certified_valuations(api, plan["id"], years=(2025,))

        reported = report_withdrawal_event(
            api,
            employer["id"],
            reported_cause=ReportedCause.COVERED_WORK_CEASED.value,
        )
        assert reported["rules_variant"] == "CONSTRUCTION_RULES"
        assert reported["status"] == "REPORTED"
        assert reported["determined_type"] == "NONE"
        assert reported["partial_withdrawal_fraction"] == pytest.approx(0.0, abs=0.0001)
        assert reported["determined_at"] is None

        determined = determine_withdrawal_event(api, reported["id"])
        assert determined["rules_variant"] == "CONSTRUCTION_RULES"
        assert determined["determined_type"] == "COMPLETE"
        assert determined["partial_withdrawal_fraction"] == pytest.approx(1.0, abs=0.0001)
        assert determined["status"] == "COMPLETE_DETERMINED"
        assert determined["determined_at"].startswith("2026-08-01T00:00:00")

        employer_after = get_employer(api, employer["id"])
        assert employer_after["status"] == "COMPLETE_WITHDRAWN"
        assert employer_after["obligation_end_year"] == 2026

    def test_an_asset_sale_naming_an_unknown_buyer_group_reports_the_groups_not_found_code(
        self, api
    ):
        """The seller resolves and the buying group does not, so the second foreign key's own
        code comes back.

        PRD 2.4: "The same codes serve foreign keys carried in a request body;
        `buyer_controlled_group_id` resolves against controlled groups and
        `seller_employer_id` against employers, and `supersedes_record_id` against
        contribution records."

        Design: Corner/entities/asset_sale_with_an_unknown_buyer_controlled_group_returns_not_found
        """
        plan = register_plan(api)
        group = register_controlled_group(api)
        employer = register_employer(api, plan["id"], group["id"], obligation_start_year=2021)

        response = api.create_asset_sale_transaction(
            factories.asset_sale_payload(
                employer["id"],
                UNKNOWN_GROUP_ID,
                closing_date="2026-05-01T00:00:00Z",
                purchase_price_cents=300_000_000,
                bond_amount_cents=30_000_000,
                buyer_assumes_contribution_obligation=True,
                workforce_continuity_pct=0.8,
                asset_continuity_pct=0.6,
                customer_continuity_pct=0.6,
            ),
            FUND_ADMINISTRATOR_HEADERS,
        )
        validate_error(response, ApiErrorId.CONTROLLED_GROUP_NOT_FOUND.value, 404)

        _data, meta = validate_paginated(
            api.list_asset_sale_transactions(
                FUND_ADMINISTRATOR_HEADERS, {"seller_employer_id": employer["id"]}
            )
        )
        assert meta["total_count"] == 0
