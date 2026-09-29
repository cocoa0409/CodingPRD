"""Record keeping: creation defaults, single reads, listings and repair-line removal."""

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    assert_applicant,
    assert_program_year,
    assert_work_item,
    assert_work_write_up,
    create_applicant_payload,
    create_bid_payload,
    create_program_year_payload,
    create_work_item_payload,
    is_valid_uuid,
    make_contractor_headers,
    next_email,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    INTAKE,
    PROGRAM_MANAGER,
    REHAB,
    add_work_item,
    build_applicant,
    build_write_up,
    refresh_applicant,
    refresh_solicitation,
    refresh_write_up,
)


class TestProgramYearOpening:
    """A new fiscal cycle materialises its budget buckets on the way in."""

    def test_a_new_program_year_reports_its_derived_budget_buckets(self):
        """The three spent buckets open at zero and the unspent one holds the allocation.

        PRD: "At creation, `committed_amount_cents`, `disbursed_amount_cents` and
        `program_income_balance_cents` are all initialised to zero, and
        `uncommitted_amount_cents` therefore equals `allocation_budget_cents`."

        Design: Corner/entities/program_year_creation_returns_201_with_the_derived_budget_triad
        """
        response = api_client.create_program_year(
            create_program_year_payload(), PROGRAM_MANAGER
        )

        created = validate_success(response, 201)

        assert_program_year(created)
        assert created["fiscal_year"] == 2026
        assert created["ami_median_income_cents"] == 9_000_000
        assert created["allocation_budget_cents"] == 50_000_000
        assert created["uncommitted_amount_cents"] == 50_000_000, (
            "The whole allocation is unspent at creation, got "
            f"{created['uncommitted_amount_cents']}"
        )
        assert created["committed_amount_cents"] == 0
        assert created["disbursed_amount_cents"] == 0
        assert created["program_income_balance_cents"] == 0
        assert created["version"] == 1

    def test_client_supplied_identifiers_and_versions_are_ignored(self):
        """The record's own identity is minted by the program, never by the caller.

        PRD: "Every persisted resource carries a server-minted `id`, which is a
        UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC
        form with three fractional digits."

        Design: Corner/entities/program_year_creation_with_extra_field_id_is_ignored_and_system_fields_are_server_minted
        """
        payload = create_program_year_payload(
            fiscal_year=2027, id="py_client_chosen", version=99
        )

        created = validate_success(
            api_client.create_program_year(payload, PROGRAM_MANAGER), 201
        )

        assert created["id"] != "py_client_chosen", (
            "The caller's chosen identifier must be discarded"
        )
        assert is_valid_uuid(created["id"]), (
            f"The minted identifier is a bare UUID, got {created['id']!r}"
        )
        assert created["version"] == 1, (
            f"Every row starts at version 1, got {created['version']}"
        )
        assert created["created_at"] == created["updated_at"], (
            "Nothing has mutated the row yet, so both stamps agree"
        )


class TestHouseholdRecords:
    """Registration stores declarations verbatim and defers every derived figure."""

    def test_the_single_household_read_returns_the_pre_certification_row(
        self, program_year
    ):
        """Reading a household back never runs the certification arithmetic early.

        PRD: "A newly registered household has `eligibility_status` of `APPLIED`,
        and its `annual_income_cents`, `income_limit_cents`, `ami_percent` and
        `income_category` remain unset until certification runs."

        Design: Corner/entities/applicant_get_by_id_returns_the_stored_row
        """
        registered = build_applicant(program_year["id"], full_name="Odell Marsh")

        fetched = validate_success(
            api_client.get_applicant(registered["id"], REHAB), 200
        )

        assert_applicant(fetched)
        assert fetched["id"] == registered["id"]
        assert fetched["program_year_id"] == program_year["id"]
        assert fetched["full_name"] == "Odell Marsh"
        assert fetched["eligibility_status"] == "APPLIED"
        for deferred in ("annual_income_cents", "income_limit_cents", "ami_percent", "income_category"):
            assert fetched.get(deferred) is None, (
                f"{deferred} stays unset until certification runs, got "
                f"{fetched.get(deferred)}"
            )
        assert fetched["version"] == 1

    def test_the_household_list_reports_the_filtered_total_and_the_next_page(
        self, program_year
    ):
        """Three households read two at a time: the count is the total, not the page.

        PRD: "The `meta` object of a collection response carries `limit`,
        `offset`, `total_count` and `has_more`; `total_count` is the number of
        rows matching the filters before pagination is applied, and `has_more` is
        true when rows remain beyond the current window."

        Design: Corner/entities/applicant_list_paginates_with_total_count_and_has_more
        """
        registered = {
            build_applicant(
                program_year["id"], full_name=name, household_size=size
            )["id"]
            for name, size in (
                ("Applicant One", 4),
                ("Applicant Two", 3),
                ("Applicant Three", 2),
            )
        }

        first_rows, first_meta = validate_paginated(
            api_client.list_applicants(
                INTAKE,
                {"program_year_id": program_year["id"], "limit": 2, "offset": 0},
            )
        )
        second_rows, second_meta = validate_paginated(
            api_client.list_applicants(
                INTAKE,
                {"program_year_id": program_year["id"], "limit": 2, "offset": 2},
            )
        )

        assert len(first_rows) == 2
        assert first_meta["total_count"] == 3, (
            f"Three households match the filter, got {first_meta['total_count']}"
        )
        assert first_meta["has_more"] is True
        assert len(second_rows) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False, (
            "No rows remain beyond the second window"
        )
        assert {row["id"] for row in first_rows + second_rows} == registered, (
            "The two pages together cover every household exactly once"
        )
        unfiltered_rows, unfiltered_meta = validate_paginated(
            api_client.list_applicants(INTAKE)
        )
        assert unfiltered_meta["limit"] == 10, (
            f"The default page size is 10, got {unfiltered_meta['limit']}"
        )
        assert len(unfiltered_rows) == 3

    def test_a_household_without_a_household_size_is_refused_wholesale(
        self, program_year
    ):
        """An omitted required declaration writes no partial household row.

        PRD: "Required fields are present, types and enum members are valid,
        money and count fields are non-negative, and date ranges are ordered —
        otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/create_applicant_missing_required_household_size_returns_invalid_request
        """
        payload = create_applicant_payload(program_year["id"])
        payload.pop("household_size")

        response = api_client.create_applicant(payload, INTAKE)

        validate_error(response, "ERR_INVALID_REQUEST", 400)
        rows, meta = validate_paginated(
            api_client.list_applicants(INTAKE, {"program_year_id": program_year["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0, (
            f"The refused registration stored nothing, got {meta['total_count']} rows"
        )

    def test_a_near_miss_methodology_value_is_refused_rather_than_coerced(
        self, program_year
    ):
        """`PART_5` is not a member of the methodology enumeration and is not repaired.

        PRD: "Required fields are present, types and enum members are valid,
        money and count fields are non-negative, and date ranges are ordered —
        otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/create_applicant_with_invalid_income_calc_method_is_rejected
        """
        validate_error(
            api_client.create_applicant(
                create_applicant_payload(
                    program_year["id"], full_name="Bad Enum", income_calc_method="PART_5"
                ),
                INTAKE,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        validate_error(
            api_client.create_applicant(
                create_applicant_payload(program_year["id"], wage_income_cents=-1),
                INTAKE,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        rows, meta = validate_paginated(
            api_client.list_applicants(INTAKE, {"program_year_id": program_year["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_omitted_optional_declarations_default_to_zero_and_false(
        self, program_year
    ):
        """A wage-only household certifies on its wage alone, with nothing imputed.

        PRD: "Each of `benefit_income_cents`, `actual_asset_income_cents`,
        `household_assets_cents` and `dependents_count` defaults to zero when
        omitted, and `elderly_household` defaults to false."

        PRD: "When household assets are at or below the five-thousand-dollar
        floor, no imputation occurs and the asset income used is
        `actual_asset_income_cents` exactly."

        Design: Corner/entities/applicant_optional_money_and_flag_fields_default_to_zero_and_false
        """
        registered = validate_success(
            api_client.create_applicant(
                {
                    "program_year_id": program_year["id"],
                    "full_name": "Defaults Only",
                    "email": next_email(),
                    "household_size": 4,
                    "income_calc_method": "PART_5_ANNUAL",
                    "wage_income_cents": 4_500_000,
                },
                INTAKE,
            ),
            201,
        )
        assert registered["benefit_income_cents"] == 0
        assert registered["actual_asset_income_cents"] == 0
        assert registered["household_assets_cents"] == 0
        assert registered["dependents_count"] == 0
        assert registered["elderly_household"] is False

        certified = validate_success(
            api_client.verify_income(registered["id"], INTAKE), 200
        )

        assert certified["annual_income_cents"] == 4_500_000, (
            "With no assets declared there is nothing to impute, got "
            f"{certified['annual_income_cents']}"
        )
        assert certified["ami_percent"] == 50.0
        assert certified["income_category"] == "VERY_LOW"
        assert certified["eligibility_status"] == "INCOME_VERIFIED"
        assert refresh_applicant(registered["id"])["annual_income_cents"] == 4_500_000


class TestRepairLineLifecycle:
    """A repair line is computed on the way in and replaced by deletion."""

    def test_a_client_supplied_line_total_is_discarded_for_the_computed_one(
        self, historic_inspected_case
    ):
        """The lead uplift decides the loaded cost; the posted figure is not blended in.

        PRD: "Each line's `protocol_multiplier` starts at 1 and is increased
        **additively** by the uplifts the line triggers: fifteen percent when
        `is_lead_hazard_reduction` is true, and twelve percent when
        `is_historic_sensitive` is true."

        PRD: "The line's `line_total_cents` is `estimated_cost_cents` multiplied
        by that multiplier, rounded half up to whole cents."

        Design: Corner/entities/work_item_line_total_is_computed_and_extra_field_line_total_cents_is_ignored
        """
        write_up = build_write_up(historic_inspected_case["application"]["id"])

        line = validate_success(
            api_client.create_work_item(
                create_work_item_payload(
                    write_up["id"],
                    description="Soffit lead paint stabilisation",
                    category="LEAD_HAZARD_CONTROL",
                    priority_class="HEALTH_SAFETY",
                    estimated_cost_cents=1_000_000,
                    is_lead_hazard_reduction=True,
                    is_historic_sensitive=False,
                    line_total_cents=1,
                ),
                REHAB,
            ),
            201,
        )

        assert_work_item(line)
        assert line["protocol_multiplier"] == 1.15
        assert line["line_total_cents"] == 1_150_000, (
            "The lead uplift loads 1,000,000 up to 1,150,000, got "
            f"{line['line_total_cents']}"
        )
        assert line["estimated_cost_cents"] == 1_000_000
        rolled_up = refresh_write_up(write_up["id"])
        assert rolled_up["work_item_count"] == 1
        assert rolled_up["base_estimate_cents"] == 1_150_000
        assert rolled_up["contingency_cents"] == 115_000
        assert rolled_up["total_estimate_cents"] == 1_265_000

    def test_a_repair_line_carries_no_version_and_is_replaced_by_deletion(
        self, inspected_case
    ):
        """Removing a line answers with no body and pulls the roll-up down with it.

        PRD: "The repair-line resource (`WorkItem`) is the single exception: a
        repair line carries only `id` and `created_at`."

        PRD: "Removal addresses the line by its `work_item_id` and answers 204
        with no body."

        Design: Corner/entities/work_item_is_immutable_carrying_only_id_and_created_at
        """
        write_up = build_write_up(inspected_case["application"]["id"])
        kept = add_work_item(write_up["id"])
        dropped = add_work_item(
            write_up["id"],
            description="Kitchen cabinet replacement",
            category="ACCESSIBILITY",
            priority_class="GENERAL_PROPERTY_IMPROVEMENT",
            estimated_cost_cents=400_000,
        )
        fetched = validate_success(api_client.get_work_item(kept["id"], REHAB), 200)
        assert_work_item(fetched)
        assert "version" not in fetched, "a repair line has no version field"
        assert "updated_at" not in fetched, "a repair line has no updated_at field"

        response = api_client.delete_work_item(dropped["id"], REHAB)

        assert response.status_code == 204, (
            f"Removal answers 204, got {response.status_code}: {response.text}"
        )
        assert not response.content, (
            f"Removal answers with no body, got {response.text!r}"
        )
        rolled_up = refresh_write_up(write_up["id"])
        assert_work_write_up(rolled_up)
        assert rolled_up["work_item_count"] == 1
        assert rolled_up["base_estimate_cents"] == 2_000_000, (
            "The removed 400,000 line leaves the roll-up, got "
            f"{rolled_up['base_estimate_cents']}"
        )
        assert rolled_up["contingency_cents"] == 200_000
        assert rolled_up["total_estimate_cents"] == 2_200_000
        rows, meta = validate_paginated(
            api_client.list_work_items(REHAB, {"write_up_id": write_up["id"]})
        )
        assert [row["id"] for row in rows] == [kept["id"]]
        assert meta["total_count"] == 1
        validate_error(
            api_client.get_work_item(dropped["id"], REHAB),
            "ERR_WORK_ITEM_NOT_FOUND",
            404,
        )


class TestUnresolvableReferences:
    """Every identifier is resolved before the request is allowed to do anything."""

    def test_reading_an_unknown_case_answers_the_case_not_found_identifier(
        self, program_year
    ):
        """A well-formed identifier that matches no case is a 404, not an empty 200.

        PRD: "The 404 error identifier is selected by the entity the unresolved
        segment addresses: `ERR_PROGRAM_YEAR_NOT_FOUND`,
        `ERR_APPLICANT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`,
        `ERR_INSPECTION_NOT_FOUND`, `ERR_WRITE_UP_NOT_FOUND`,
        `ERR_WORK_ITEM_NOT_FOUND`, `ERR_CONTRACTOR_NOT_FOUND`,
        `ERR_SOLICITATION_NOT_FOUND`, `ERR_BID_NOT_FOUND`,
        `ERR_LOAN_NOT_FOUND`, `ERR_DRAW_NOT_FOUND`,
        `ERR_CHANGE_ORDER_NOT_FOUND` or `ERR_COMPLAINT_NOT_FOUND`."

        Design: Corner/entities/get_application_by_unknown_id_returns_not_found
        """
        response = api_client.get_application(NON_EXISTENT_UUID, INTAKE)

        error = validate_error(response, "ERR_APPLICATION_NOT_FOUND", 404)
        assert error["message"].strip(), "The failure carries a readable explanation"
        _, meta = validate_paginated(
            api_client.list_applications(
                INTAKE, {"program_year_id": program_year["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            "A failed read creates nothing, got "
            f"{meta['total_count']} rehabilitation cases"
        )

    def test_a_repair_line_against_an_unknown_write_up_is_not_found(self):
        """The line's parent reference is resolved before its own shape is judged.

        PRD: "Foreign keys supplied in a request body are resolved after path
        identifiers, in the order the keys appear in the endpoint's input list,
        and yield the same 404 identifiers."

        Design: Corner/entities/create_work_item_with_unknown_write_up_id_returns_not_found
        """
        response = api_client.create_work_item(
            create_work_item_payload(
                NON_EXISTENT_UUID,
                description="Orphan line",
                estimated_cost_cents=100_000,
            ),
            REHAB,
        )

        validate_error(response, "ERR_WRITE_UP_NOT_FOUND", 404)
        _, meta = validate_paginated(api_client.list_work_items(REHAB))
        assert meta["total_count"] == 0, (
            f"No repair line survives the refusal, got {meta['total_count']}"
        )

    def test_a_bid_resolves_both_of_its_references(self, bid_open_case):
        """A bid names two independent aggregates, and each one is checked.

        PRD: "Foreign keys supplied in a request body are resolved after path
        identifiers, in the order the keys appear in the endpoint's input list,
        and yield the same 404 identifiers."

        Design: Corner/entities/bid_creation_validates_both_cross_aggregate_foreign_keys
        """
        solicitation_id = bid_open_case["solicitation"]["id"]
        contractor_id = bid_open_case["contractor"]["id"]

        response = api_client.create_bid(
            create_bid_payload(solicitation_id, NON_EXISTENT_UUID),
            make_contractor_headers(NON_EXISTENT_UUID),
        )

        validate_error(response, "ERR_CONTRACTOR_NOT_FOUND", 404)
        solicitation = refresh_solicitation(solicitation_id)
        assert solicitation["bid_count"] == 0
        assert solicitation["status"] == "OPEN"

        mirrored = api_client.create_bid(
            create_bid_payload(NON_EXISTENT_UUID, contractor_id),
            make_contractor_headers(contractor_id),
        )

        validate_error(mirrored, "ERR_SOLICITATION_NOT_FOUND", 404)
        assert refresh_solicitation(solicitation_id)["bid_count"] == 0
