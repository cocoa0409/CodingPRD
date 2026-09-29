"""Entity surface: creation echoes, read-after-write, pagination, defaults and identity rules."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_agency,
    assert_budget_cycle,
    assert_meta_envelope,
    assert_thin_audit_fields,
    fixtures,
    make_agency_officer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

DOE = {"agency_code": "DOE", "name": "Department of Education", "agency_type": "EXECUTIVE"}
DOH = {"agency_code": "DOH", "name": "Department of Health", "agency_type": "EXECUTIVE"}
DOT_PAYLOAD = {
    "agency_code": "DOT",
    "name": "Department of Transportation",
    "agency_type": "EXECUTIVE",
}


class TestAgencyCreation:
    def test_registering_an_agency_echoes_its_inputs_and_mints_the_audit_set(
        self, api, system_admin_headers
    ):
        """PRD §3.1: "Registering an agency records its `agency_code` — a short statewide code such as `DOH`, between 1 and 12 characters and unique across all agencies — together with its legal `name`, between 1 and 200 characters, and its `agency_type`, one of `EXECUTIVE`, `JUDICIAL`, `LEGISLATIVE`, or `HIGHER_ED`."
        PRD §3.1: "Each agency also carries a derived `federal_compliance_flag`, which starts at `CLEAR`; the rules that move it to `AT_RISK` or `DEFICIENT` are described in §3.8."
        PRD §2.4: "`version` (integer): starts at 1 on creation and increments by exactly 1 on every mutation of the row."
        PRD §4: "Operations that mint a new resource return `201 Created`."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

        Design: Corner/entities/agency_creation_returns_201_with_every_declared_field
        """
        fixtures.register_agency(**DOE)

        response = api.create_agency(DOT_PAYLOAD, system_admin_headers)
        agency = validate_success(response, 201)

        assert response.json()["response_type"] == "object"
        assert_meta_envelope(response.json())
        assert_agency(agency)
        assert agency["agency_code"] == "DOT"
        assert agency["name"] == "Department of Transportation"
        assert agency["agency_type"] == "EXECUTIVE"
        assert agency["federal_compliance_flag"] == "CLEAR"
        assert agency["version"] == 1
        assert agency["id"] and agency["created_at"] and agency["updated_at"]


class TestBudgetCycleRetrieval:
    def test_reading_a_new_cycle_returns_the_stored_row_without_recomputing_it(
        self, api, budget_director_headers
    ):
        """PRD §3.1: "Opening a budget cycle records the `fiscal_year` label — an integer of at least 2000 and at most 2100, unique across cycles — the `fiscal_year_start_date`, and `reserve_balance_cents`, the cash sitting in the budget stabilization reserve, which must be zero or positive and which is the sole funding source for emergency appropriations."
        PRD §3.1: "The `constitutional_reserve_pct` may be supplied and otherwise defaults to five percent expressed as the fraction 0.05; it must be at least 0 and at most 0.5."
        PRD §3.1: "A newly opened cycle sits in `DEVELOPMENT`, its `version` is 1, `balance_certified` is false, `cash_posture` is `NORMAL`, and every computed money figure — `adopted_general_fund_revenue_cents`, `total_recommended_cents`, `required_reserve_cents`, `emergency_granted_cents`, `total_released_cents`, `total_expended_cents`, `total_reverted_cents`, `total_carryforward_cents`, `projected_cumulative_cash_cents` — starts at zero, as does `cash_utilization_pct`."
        PRD §2.4: "`version` (integer): starts at 1 on creation and increments by exactly 1 on every mutation of the row."

        Design: Corner/entities/budget_cycle_retrieval_returns_the_stored_row_unchanged
        """
        created = fixtures.open_budget_cycle(
            fiscal_year=2027,
            fiscal_year_start_date="2026-07-01",
            reserve_balance_cents=500_000_000,
            constitutional_reserve_pct=0.05,
        )

        response = api.get_budget_cycle(created["id"], budget_director_headers)
        cycle = validate_success(response, 200)

        assert response.json()["response_type"] == "object"
        assert_budget_cycle(cycle)
        assert cycle["fiscal_year"] == 2027
        assert cycle["phase"] == "DEVELOPMENT"
        assert cycle["constitutional_reserve_pct"] == 0.05
        assert cycle["reserve_balance_cents"] == 500_000_000
        assert cycle["adopted_general_fund_revenue_cents"] == 0
        assert cycle["required_reserve_cents"] == 0
        assert cycle["total_recommended_cents"] == 0
        assert cycle["balance_certified"] is False
        assert cycle["total_released_cents"] == 0
        assert cycle["total_expended_cents"] == 0
        assert cycle["emergency_granted_cents"] == 0
        assert cycle["cash_posture"] == "NORMAL"
        assert cycle["version"] == 1

        assert validate_success(api.get_budget_cycle(created["id"], budget_director_headers))[
            "version"
        ] == 1


class TestDecisionPackageListing:
    @staticmethod
    def _request_with_twelve_packages():
        ctx = fixtures.setup_development_cycle(agencies=(DOT_PAYLOAD,))
        request = fixtures.create_draft_request(
            ctx["cycle"]["id"], ctx["agency"]["id"], base_budget_cents=1_000_000_000
        )
        for rank in range(1, 13):
            fixtures.attach_package(
                request["id"],
                ctx["agency"]["id"],
                package_type="TECHNICAL",
                priority_rank=rank,
                amount_cents=rank * 1_000_000,
            )
        ctx["request"] = request
        return ctx

    def test_the_default_page_carries_ten_rows_and_the_tail_page_carries_the_rest(self, api):
        """PRD §2.3: "`limit` is the maximum number of rows to return; it defaults to 10, its minimum accepted value is 1, and its maximum accepted value is 100."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of rows matching the filters before the page window is applied and `has_more` indicates whether rows remain beyond the current window."
        PRD §2.3: "`offset` is the number of rows to skip; it defaults to 0 and its minimum accepted value is 0."
        PRD §3.2: "Packages are created in `PROPOSED`."

        Design: Corner/entities/decision_package_listing_paginates_with_the_default_limit_of_ten
        """
        ctx = self._request_with_twelve_packages()
        request_id = ctx["request"]["id"]

        first_response = api.list_decision_packages(
            fixtures.ANALYST, {"agency_request_id": request_id}
        )
        first_rows, first_meta = validate_paginated(first_response)
        assert first_response.json()["response_type"] == "array"
        assert len(first_rows) == 10
        assert first_meta["limit"] == 10
        assert first_meta["offset"] == 0
        assert first_meta["total_count"] == 12
        assert first_meta["has_more"] is True

        tail_rows, tail_meta = validate_paginated(
            api.list_decision_packages(
                fixtures.ANALYST,
                {"agency_request_id": request_id, "limit": 10, "offset": 10},
            )
        )
        assert len(tail_rows) == 2
        assert tail_meta["limit"] == 10
        assert tail_meta["offset"] == 10
        assert tail_meta["total_count"] == 12
        assert tail_meta["has_more"] is False

        for row in first_rows + tail_rows:
            assert row["agency_request_id"] == request_id
            assert row["status"] == "PROPOSED"


class TestUnknownPathIdentifiers:
    def test_each_single_row_get_maps_an_unknown_id_to_its_own_not_found_code(
        self,
        api,
        system_admin_headers,
        budget_director_headers,
        budget_analyst_headers,
        legislative_fiscal_officer_headers,
        state_controller_headers,
    ):
        """PRD §2.7: "Where a path does carry an identifier, the server validates identifiers left to right and rejects on the **first** identifier that resolves to nothing, returning that resource's own not-found code — for example a request naming a non-existent appropriation fails with `ERR_APPROPRIATION_NOT_FOUND` before any body field is examined."
        PRD §2.12: "Every resource named in the path exists, validated left to right — otherwise the matching not-found code (404). Applies to every endpoint with a path identifier."

        Design: Corner/entities/path_id_lookups_with_unknown_ids_return_the_resource_specific_not_found
        """
        fixtures.register_agency(**DOT_PAYLOAD)

        cases = [
            (api.get_agency(NON_EXISTENT_UUID, system_admin_headers), ApiErrorId.ERR_AGENCY_NOT_FOUND),
            (
                api.get_budget_cycle(NON_EXISTENT_UUID, budget_director_headers),
                ApiErrorId.ERR_BUDGET_CYCLE_NOT_FOUND,
            ),
            (
                api.get_agency_request(NON_EXISTENT_UUID, budget_analyst_headers),
                ApiErrorId.ERR_AGENCY_REQUEST_NOT_FOUND,
            ),
            (
                api.get_decision_package(NON_EXISTENT_UUID, budget_analyst_headers),
                ApiErrorId.ERR_DECISION_PACKAGE_NOT_FOUND,
            ),
            (
                api.get_appropriation(NON_EXISTENT_UUID, legislative_fiscal_officer_headers),
                ApiErrorId.ERR_APPROPRIATION_NOT_FOUND,
            ),
            (
                api.get_allotment(NON_EXISTENT_UUID, state_controller_headers),
                ApiErrorId.ERR_ALLOTMENT_NOT_FOUND,
            ),
            (
                api.get_federal_grant(NON_EXISTENT_UUID, budget_analyst_headers),
                ApiErrorId.ERR_FEDERAL_GRANT_NOT_FOUND,
            ),
            (
                api.get_match_commitment(NON_EXISTENT_UUID, budget_analyst_headers),
                ApiErrorId.ERR_MATCH_COMMITMENT_NOT_FOUND,
            ),
        ]

        for response, expected_error in cases:
            validate_error(response, expected_error, 404)
            assert response.json()["response_type"] == "error"


class TestUnknownActionPathIdentifiers:
    def test_action_endpoints_report_not_found_rather_than_an_invalid_state(
        self, api, budget_director_headers, state_controller_headers
    ):
        """PRD §2.12: "Every resource named in the path exists, validated left to right — otherwise the matching not-found code (404). Applies to every endpoint with a path identifier."
        PRD §2.12: "The target row is in a state from which the requested transition is declared — otherwise `ERR_INVALID_STATE` (409). Applies to every action endpoint."
        PRD §2.12: "When more than one rule could reject a request, the outcome is determined by a single global ladder, evaluated top to bottom; the first rule that fails produces the response and no later rule is consulted."

        Design: Corner/entities/action_endpoints_with_unknown_path_ids_return_not_found_before_any_state_check
        """
        fixtures.register_agency(**DOT_PAYLOAD)

        cases = [
            (
                api.adopt_revenue_forecast(NON_EXISTENT_UUID, budget_director_headers, {}),
                ApiErrorId.ERR_REVENUE_FORECAST_NOT_FOUND,
            ),
            (
                api.approve_executive_recommendation(NON_EXISTENT_UUID, budget_director_headers),
                ApiErrorId.ERR_RECOMMENDATION_NOT_FOUND,
            ),
            (
                api.approve_budget_transfer(NON_EXISTENT_UUID, budget_director_headers),
                ApiErrorId.ERR_TRANSFER_NOT_FOUND,
            ),
            (
                api.void_expenditure(
                    NON_EXISTENT_UUID, {"reason": "wrong appropriation"}, state_controller_headers
                ),
                ApiErrorId.ERR_EXPENDITURE_NOT_FOUND,
            ),
        ]

        for response, expected_error in cases:
            validate_error(response, expected_error, 404)
            assert response.json()["data"]["error_id"] != ApiErrorId.ERR_INVALID_STATE


class TestBudgetCycleRequiredFields:
    def test_omitting_fiscal_year_is_a_body_shape_rejection_that_persists_nothing(
        self, api, system_admin_headers
    ):
        """PRD §2.12: "The body is well formed — required fields present, enum members legal, integer fields integral, `limit` within 1 to 100 and `offset` at least 0 — otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint."
        PRD §3.1: "Opening a budget cycle records the `fiscal_year` label — an integer of at least 2000 and at most 2100, unique across cycles — the `fiscal_year_start_date`, and `reserve_balance_cents`, the cash sitting in the budget stabilization reserve, which must be zero or positive and which is the sole funding source for emergency appropriations."
        PRD §5: "`ERR_INVALID_REQUEST` | required body field missing, unknown enum member, non-integer where an integer is required, or limit/offset outside 1..100 / >= 0 (HTTP 400)"

        Design: Corner/entities/budget_cycle_create_without_fiscal_year_returns_invalid_request
        """
        response = api.create_budget_cycle(
            {
                "fiscal_year_start_date": "2026-07-01",
                "reserve_balance_cents": 500_000_000,
                "constitutional_reserve_pct": 0.05,
            },
            system_admin_headers,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

        validate_error(
            api.get_budget_cycle(NON_EXISTENT_UUID, system_admin_headers),
            ApiErrorId.ERR_BUDGET_CYCLE_NOT_FOUND,
            404,
        )


class TestAllotmentDefaults:
    def test_allow_partial_defaults_to_false_so_a_short_ceiling_is_refused(self, api):
        """PRD §3.5: "A `BudgetAnalyst` opens an allotment by supplying `appropriation_id`, the `quarter` it covers (an integer from 1 to 4), the `requested_cents` the agency asks to have released (strictly greater than zero), and optionally `allow_partial`, which defaults to false."
        PRD §3.5: "A new allotment starts in `DRAFT` with `computed_release_cents` at 0, `binding_constraint` null, `released_cents` at 0, and `prepared_by_user_id`, `approved_by_user_id`, and `recall_reason` all null."
        PRD §3.5: "A `GENERAL`-fund line may release 22 percent of its authority in quarter 1 and 26 percent in each of quarters 2, 3, and 4."
        PRD §3.5: "If the ceiling is below `requested_cents` while `allow_partial` is false, preparation is rejected with `ERR_ALLOTMENT_EXCEEDS_CEILING`; with `allow_partial` true the smaller amount is accepted and recorded."

        Design: Corner/entities/allotment_create_omitting_allow_partial_defaults_it_to_false
        """
        ctx = fixtures.setup_execution_cycle()

        allotment = validate_success(
            api.create_allotment(
                {
                    "appropriation_id": ctx["appropriation"]["id"],
                    "quarter": 1,
                    "requested_cents": 500_000_000,
                },
                fixtures.ANALYST,
            ),
            201,
        )
        assert allotment["allow_partial"] is False
        assert allotment["status"] == "DRAFT"
        assert allotment["computed_release_cents"] == 0
        assert allotment["binding_constraint"] is None

        validate_error(
            api.prepare_allotment(allotment["id"], fixtures.ANALYST),
            ApiErrorId.ERR_ALLOTMENT_EXCEEDS_CEILING,
            422,
        )

        after = fixtures.read_allotment(allotment["id"])
        assert after["status"] == "DRAFT"
        assert after["computed_release_cents"] == 0


class TestAgencyRequestComputedTotal:
    def test_the_request_total_is_recomputed_from_the_live_package_set(self, api):
        """PRD §3.2: "A request is created in `DRAFT` with `revision_count` at 0, `last_return_reason` null, and `total_request_cents` equal to `base_budget_cents`."
        PRD §3.2: "Of those, sum the `amount_cents` of every package whose `package_type` is `EXPANSION`, `TECHNICAL`, or `FEDERAL_MATCH` to obtain the additive total, and sum the `amount_cents` of every package whose `package_type` is `REDUCTION` to obtain the subtractive total."
        PRD §3.2: "The request total is `base_budget_cents` plus the additive total minus the subtractive total."
        PRD §3.2: "This figure is recomputed whenever a package is attached to the request, on submission, on acceptance, and on every package disposition change."
        PRD §3.2: "Submission recomputes `total_request_cents` and increments the request's `version` by 1."

        Design: Corner/entities/agency_request_total_request_cents_is_computed_and_client_input_ignored
        """
        ctx = fixtures.setup_development_cycle(agencies=(DOT_PAYLOAD,))
        agency_id = ctx["agency"]["id"]
        officer = make_agency_officer_headers(agency_id)

        request = validate_success(
            api.create_agency_request(
                {
                    "budget_cycle_id": ctx["cycle"]["id"],
                    "agency_id": agency_id,
                    "base_budget_cents": 1_000_000_000,
                },
                officer,
            ),
            201,
        )
        assert request["total_request_cents"] == 1_000_000_000

        fixtures.attach_package(
            request["id"],
            agency_id,
            package_type="TECHNICAL",
            priority_rank=1,
            amount_cents=300_000_000,
        )
        assert fixtures.read_agency_request(request["id"])["total_request_cents"] == 1_300_000_000

        fixtures.attach_package(
            request["id"],
            agency_id,
            package_type="REDUCTION",
            priority_rank=2,
            amount_cents=200_000_000,
        )

        submitted = validate_success(api.submit_agency_request(request["id"], officer), 200)
        assert submitted["total_request_cents"] == 1_100_000_000
        assert submitted["base_budget_cents"] == 1_000_000_000
        assert submitted["status"] == "SUBMITTED"
        assert submitted["revision_count"] == 0


class TestAgencyTypeEnum:
    def test_an_unknown_agency_type_is_rejected_while_a_legal_member_is_accepted(
        self, api, system_admin_headers
    ):
        """PRD §3.1: "Registering an agency records its `agency_code` — a short statewide code such as `DOH`, between 1 and 12 characters and unique across all agencies — together with its legal `name`, between 1 and 200 characters, and its `agency_type`, one of `EXECUTIVE`, `JUDICIAL`, `LEGISLATIVE`, or `HIGHER_ED`."
        PRD §2.12: "The body is well formed — required fields present, enum members legal, integer fields integral, `limit` within 1 to 100 and `offset` at least 0 — otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint."

        Design: Corner/entities/agency_create_with_an_unknown_agency_type_returns_invalid_request
        """
        fixtures.register_agency(**DOE)

        validate_error(
            api.create_agency(
                {
                    "agency_code": "DOT",
                    "name": "Department of Transportation",
                    "agency_type": "QUASI_PUBLIC",
                },
                system_admin_headers,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        accepted = validate_success(
            api.create_agency(
                {
                    "agency_code": "DOT",
                    "name": "Department of Transportation",
                    "agency_type": "HIGHER_ED",
                },
                system_admin_headers,
            ),
            201,
        )
        assert accepted["agency_type"] == "HIGHER_ED"


class TestCommitteeActionImmutability:
    @staticmethod
    def _line_with_a_sequence_two_decrease():
        ctx = fixtures.setup_cycle(
            stop_after="LEGISLATIVE",
            appropriations=(
                {
                    "fund_type": "GENERAL",
                    "program_code": "P100",
                    "introduced_amount_cents": 2_000_000_000,
                    "enact": False,
                },
            ),
        )
        ctx["appropriation"] = ctx["appropriations"]["P100"]
        ctx["second"] = fixtures.record_committee_action(
            ctx["appropriation"]["id"],
            chamber="HOUSE",
            committee_name="Appropriations",
            action_type="DECREASE",
            amount_cents=500_000_000,
            sequence_number=2,
        )
        return ctx

    def test_the_append_only_row_carries_no_version_yet_its_running_balance_is_replayed(
        self, api, legislative_fiscal_officer_headers
    ):
        """PRD §2.4: "Three record types are deliberately thinner because they are either immutable or append-only, and they carry **only** `id` and `created_at` — both `updated_at` and `version` are absent from their representations."
        PRD §2.4: "`CommitteeAction` is append-only from the client's point of view: the server may rewrite its `running_balance_cents` during a replay, but the row exposes no `updated_at` and no `version`."
        PRD §3.4: "The server discards the previous result and replays the appropriation's entire action set from scratch, with no status filter, ordered by `sequence_number` ascending and, for equal sequence numbers, by `created_at` ascending."
        PRD §3.4: "The consequence to design for is that inserting an action with a *lower* `sequence_number` than actions that already exist rewrites the `running_balance_cents` of every later action and can change `committee_balance_cents` for an unchanged set of actions — applying actions in arrival order instead of sequence order would leave earlier running balances untouched and produce a different final balance from the identical inputs."
        PRD §3.4: "`SET` replaces the balance with the action's amount, `INCREASE` adds the amount to the balance, `DECREASE` subtracts the amount from the balance, `RESTORE` resets the balance to the line's `introduced_amount_cents`, and `STRIKE` zeroes the line."

        Design: Corner/entities/committee_action_is_immutable_with_no_version_field_and_no_update_endpoint
        """
        ctx = self._line_with_a_sequence_two_decrease()
        appropriation_id = ctx["appropriation"]["id"]

        before, _meta = validate_paginated(
            api.list_appropriation_committee_actions(
                appropriation_id, legislative_fiscal_officer_headers
            )
        )
        assert len(before) == 1
        assert_thin_audit_fields(before[0])
        assert before[0]["running_balance_cents"] == 1_500_000_000
        assert (
            fixtures.read_appropriation(appropriation_id)["committee_balance_cents"]
            == 1_500_000_000
        )

        validate_success(
            api.create_committee_action(
                {
                    "appropriation_id": appropriation_id,
                    "chamber": "SENATE",
                    "committee_name": "Senate Finance",
                    "action_type": "SET",
                    "amount_cents": 1_000_000_000,
                    "sequence_number": 1,
                },
                legislative_fiscal_officer_headers,
            ),
            201,
        )

        after, _meta = validate_paginated(
            api.list_appropriation_committee_actions(
                appropriation_id, legislative_fiscal_officer_headers
            )
        )
        assert [row["sequence_number"] for row in after] == [1, 2]
        assert after[0]["running_balance_cents"] == 1_000_000_000
        assert after[1]["running_balance_cents"] == 500_000_000
        for row in after:
            assert_thin_audit_fields(row)

        appropriation = fixtures.read_appropriation(appropriation_id)
        assert appropriation["committee_balance_cents"] == 500_000_000
        assert appropriation["introduced_amount_cents"] == 2_000_000_000


class TestBodyForeignKeyOrder:
    def test_the_first_unresolvable_body_reference_in_declaration_order_wins(self, api):
        """PRD §2.7: "Once the path resolves, the references carried in the request body are resolved in the order in which the endpoint declares its inputs, and the first unresolvable reference determines the error: `ERR_AGENCY_NOT_FOUND`, `ERR_BUDGET_CYCLE_NOT_FOUND`, `ERR_REVENUE_FORECAST_NOT_FOUND`, `ERR_AGENCY_REQUEST_NOT_FOUND`, `ERR_DECISION_PACKAGE_NOT_FOUND`, `ERR_RECOMMENDATION_NOT_FOUND`, `ERR_APPROPRIATION_NOT_FOUND`, `ERR_ALLOTMENT_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`, `ERR_EXPENDITURE_NOT_FOUND`, `ERR_FEDERAL_GRANT_NOT_FOUND`, or `ERR_MATCH_COMMITMENT_NOT_FOUND`, each with HTTP 404."
        PRD §2.12: "Every reference in the request body resolves, validated in the endpoint's input declaration order — otherwise the matching not-found code (404). Applies to every creation endpoint carrying reference fields."
        PRD §3.2: "An `AgencyBudgetOfficer` opens the agency's ask by creating a request carrying `budget_cycle_id`, `agency_id`, and `base_budget_cents` — the continuation budget needed to keep current services, which must be strictly greater than zero."
        PRD §3.2: "Within a `DRAFT` request the officer attaches **decision packages**, each a discrete funding proposal."

        Design: Corner/entities/body_fk_references_are_validated_in_declaration_order_and_return_not_found
        """
        ctx = fixtures.setup_development_cycle(agencies=(DOT_PAYLOAD,))
        unknown_officer = make_agency_officer_headers(NON_EXISTENT_UUID)

        validate_error(
            api.create_agency_request(
                {
                    "budget_cycle_id": NON_EXISTENT_UUID,
                    "agency_id": NON_EXISTENT_UUID,
                    "base_budget_cents": 1_000_000_000,
                },
                unknown_officer,
            ),
            ApiErrorId.ERR_BUDGET_CYCLE_NOT_FOUND,
            404,
        )

        validate_error(
            api.create_agency_request(
                {
                    "budget_cycle_id": ctx["cycle"]["id"],
                    "agency_id": NON_EXISTENT_UUID,
                    "base_budget_cents": 1_000_000_000,
                },
                unknown_officer,
            ),
            ApiErrorId.ERR_AGENCY_NOT_FOUND,
            404,
        )

        validate_error(
            api.create_decision_package(
                {
                    "agency_request_id": NON_EXISTENT_UUID,
                    "package_type": "TECHNICAL",
                    "priority_rank": 1,
                    "amount_cents": 1_000_000,
                },
                make_agency_officer_headers(ctx["agency"]["id"]),
            ),
            ApiErrorId.ERR_AGENCY_REQUEST_NOT_FOUND,
            404,
        )

        requests, requests_meta = validate_paginated(api.list_agency_requests(fixtures.ANALYST))
        packages, packages_meta = validate_paginated(
            api.list_decision_packages(fixtures.ANALYST)
        )
        assert requests == [] and requests_meta["total_count"] == 0
        assert packages == [] and packages_meta["total_count"] == 0


class TestProgramCodeUniquenessScope:
    @staticmethod
    def _cycle_with_two_agencies_and_one_line():
        ctx = fixtures.setup_cycle(
            stop_after="LEGISLATIVE",
            agencies=(DOH, DOE),
            appropriations=(
                {
                    "fund_type": "GENERAL",
                    "program_code": "P100",
                    "introduced_amount_cents": 1_000_000_000,
                    "enact": False,
                },
            ),
        )
        ctx["health"] = ctx["agencies"]["DOH"]
        ctx["education"] = ctx["agencies"]["DOE"]
        ctx["appropriation"] = ctx["appropriations"]["P100"]
        return ctx

    def test_the_same_program_code_collides_within_an_agency_and_is_free_across_agencies(
        self, api, legislative_fiscal_officer_headers, system_admin_headers
    ):
        """PRD §3.4: "A `LegislativeFiscalOfficer` introduces each **appropriation** line item into the bill by supplying `budget_cycle_id`, `agency_id`, the `fund_type` the authority is drawn on (`GENERAL`, `FEDERAL`, or `DEDICATED`), a `program_code` of 1 to 32 characters that must be unique within that cycle and agency, and `introduced_amount_cents`, the amount as introduced before any committee touches it, which must be zero or positive."
        PRD §2.12: "Code uniqueness holds: `agency_code` is unique across agencies, `fiscal_year` is unique across cycles, and `program_code` is unique within a `budget_cycle_id` and `agency_id` pair — otherwise `ERR_DUPLICATE_CODE` (409). Applies to `POST /fiscal/agencies`, `POST /fiscal/budget-cycles`, and `POST /fiscal/appropriations`."
        PRD §3.4: "A newly introduced line therefore sits at `PENDING` authority and `UNRELEASED` cash, with `committee_balance_cents` equal to `introduced_amount_cents`, `enacted_amount_cents` at 0, `is_emergency` false, `pre_freeze_cash_status` and `freeze_reason` null, `release_hold` false, and every ledger figure — `transfers_in_cents`, `transfers_out_cents`, `released_cents`, `expended_cents`, `reverted_cents`, `carryforward_cents`, `available_cash_cents`, `available_authority_cents` — at 0."

        Design: Corner/entities/appropriation_program_code_uniqueness_is_scoped_to_cycle_and_agency
        """
        ctx = self._cycle_with_two_agencies_and_one_line()

        validate_error(
            api.create_appropriation(
                {
                    "budget_cycle_id": ctx["cycle"]["id"],
                    "agency_id": ctx["health"]["id"],
                    "fund_type": "DEDICATED",
                    "program_code": "P100",
                    "introduced_amount_cents": 400_000_000,
                },
                legislative_fiscal_officer_headers,
            ),
            ApiErrorId.ERR_DUPLICATE_CODE,
            409,
        )

        sibling = validate_success(
            api.create_appropriation(
                {
                    "budget_cycle_id": ctx["cycle"]["id"],
                    "agency_id": ctx["education"]["id"],
                    "fund_type": "GENERAL",
                    "program_code": "P100",
                    "introduced_amount_cents": 400_000_000,
                },
                legislative_fiscal_officer_headers,
            ),
            201,
        )
        assert sibling["program_code"] == "P100"
        assert sibling["agency_id"] == ctx["education"]["id"]

        validate_error(
            api.create_agency(
                {"agency_code": "DOH", "name": "Duplicate Health", "agency_type": "EXECUTIVE"},
                system_admin_headers,
            ),
            ApiErrorId.ERR_DUPLICATE_CODE,
            409,
        )

        original = fixtures.read_appropriation(ctx["appropriation"]["id"])
        assert original["authority_status"] == "PENDING"
        assert original["committee_balance_cents"] == 1_000_000_000
