"""Collection endpoints, computed reads, phase-gated creates and the response envelope."""

from test_helpers import (
    ApiErrorId,
    assert_meta_envelope,
    assert_two_bases,
    fixtures,
    make_agency_officer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

DOH = {"agency_code": "DOH", "name": "Department of Health", "agency_type": "EXECUTIVE"}
DOT = {"agency_code": "DOT", "name": "Department of Transportation", "agency_type": "EXECUTIVE"}


class TestAgencyRequestListing:
    @staticmethod
    def _three_requests_across_two_cycles_and_two_agencies():
        ctx = fixtures.setup_development_cycle(agencies=(DOH, DOT))
        doh_id = ctx["agencies"]["DOH"]["id"]
        dot_id = ctx["agencies"]["DOT"]["id"]
        first_cycle_id = ctx["cycle"]["id"]
        second_cycle = fixtures.open_budget_cycle(
            fiscal_year=2028, fiscal_year_start_date="2027-07-01"
        )

        first = fixtures.create_draft_request(
            first_cycle_id, doh_id, base_budget_cents=1_000_000_000
        )
        first = fixtures.submit_request(first["id"], doh_id)
        second = fixtures.create_draft_request(
            first_cycle_id, dot_id, base_budget_cents=900_000_000
        )
        third = fixtures.create_draft_request(
            second_cycle["id"], doh_id, base_budget_cents=1_100_000_000
        )

        return {
            "doh_id": doh_id,
            "dot_id": dot_id,
            "first_cycle_id": first_cycle_id,
            "second_cycle_id": second_cycle["id"],
            "first": first,
            "second": second,
            "third": third,
        }

    def test_each_filter_narrows_independently_and_composes_with_the_page_window(
        self, api, budget_analyst_headers
    ):
        """PRD §3.2: "Requests can be listed with optional `budget_cycle_id`, `agency_id`, and `status` filters."
        PRD §2.3: "`limit` is the maximum number of rows to return; it defaults to 10, its minimum accepted value is 1, and its maximum accepted value is 100."
        PRD §2.3: "`offset` is the number of rows to skip; it defaults to 0 and its minimum accepted value is 0."
        PRD §2.3: "Unless a specific listing states otherwise, list endpoints return rows sorted by `created_at` in ascending order."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of rows matching the filters before the page window is applied and `has_more` indicates whether rows remain beyond the current window."
        PRD §3.2: "Submission moves the request `DRAFT → SUBMITTED`."

        Design: Corner/endpoints/agency_request_list_filters_compose_and_paginate_together
        """
        ctx = self._three_requests_across_two_cycles_and_two_agencies()

        rows, meta = validate_paginated(api.list_agency_requests(budget_analyst_headers))
        assert meta["total_count"] == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["has_more"] is False
        assert [row["id"] for row in rows] == [
            ctx["first"]["id"],
            ctx["second"]["id"],
            ctx["third"]["id"],
        ]

        rows, meta = validate_paginated(
            api.list_agency_requests(
                budget_analyst_headers, {"budget_cycle_id": ctx["first_cycle_id"]}
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {ctx["first"]["id"], ctx["second"]["id"]}

        rows, meta = validate_paginated(
            api.list_agency_requests(
                budget_analyst_headers,
                {"budget_cycle_id": ctx["first_cycle_id"], "status": "SUBMITTED"},
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [ctx["first"]["id"]]

        rows, meta = validate_paginated(
            api.list_agency_requests(budget_analyst_headers, {"agency_id": ctx["doh_id"]})
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {ctx["first"]["id"], ctx["third"]["id"]}

        rows, meta = validate_paginated(
            api.list_agency_requests(budget_analyst_headers, {"limit": 1, "offset": 1})
        )
        assert len(rows) == 1
        assert rows[0]["id"] == ctx["second"]["id"]
        assert meta["total_count"] == 3
        assert meta["limit"] == 1
        assert meta["offset"] == 1
        assert meta["has_more"] is True


class TestBalanceSummaryComputedRead:
    def test_both_bases_and_their_delta_are_reported_without_touching_the_row(
        self, api, state_controller_headers, budget_analyst_headers
    ):
        """PRD §3.7: "A read-only balance summary exposes both side by side, reporting `appropriation_id`, `authority_cents` (the current authority figure), `released_cents`, `expended_cents`, `available_cash_cents`, `available_authority_cents`, and `basis_delta_cents`, the last being `available_authority_cents` minus `available_cash_cents`."
        PRD §3.7: "Both start from the same inputs: `expended_cents` is the sum of `amount_cents` over the appropriation's expenditures in status `POSTED`, with `VOIDED` rows excluded; `released_cents` is the sum of `released_cents` over the appropriation's allotments in status `RELEASED`, with `DRAFT`, `PREPARED`, `APPROVED`, `RECALLED`, and `CANCELLED` rows excluded; and current authority is `enacted_amount_cents` plus `transfers_in_cents` minus `transfers_out_cents`."
        PRD §3.7: "The **cash basis**, `available_cash_cents`, is `released_cents` minus `expended_cents`."
        PRD §3.7: "The **authority basis**, `available_authority_cents`, is current authority minus `expended_cents`."
        PRD §4: "Operations that act on an existing resource — every state transition, every recomputation, every read — return `200 OK`."

        Design: Corner/endpoints/balance_summary_exposes_both_bases_and_their_delta_mid_year
        """
        ctx = fixtures.setup_appropriation_with_released_cash(
            requested_cents=440_000_000,
            expenditure_cents=100_000_000,
            appropriation_cents=2_000_000_000,
            quarter=1,
        )
        appropriation_id = ctx["appropriation"]["id"]
        version_before = ctx["appropriation"]["version"]

        officer_response = api.get_appropriation_balance_summary(
            appropriation_id, make_agency_officer_headers(ctx["agency"]["id"])
        )
        officer_summary = validate_success(officer_response, 200)
        controller_response = api.get_appropriation_balance_summary(
            appropriation_id, state_controller_headers
        )
        controller_summary = validate_success(controller_response, 200)

        assert officer_summary["appropriation_id"] == appropriation_id
        assert officer_summary["authority_cents"] == 2_000_000_000
        assert officer_summary["released_cents"] == 440_000_000
        assert officer_summary["expended_cents"] == 100_000_000
        assert officer_summary["available_cash_cents"] == 340_000_000
        assert officer_summary["available_authority_cents"] == 1_900_000_000
        assert officer_summary["basis_delta_cents"] == 1_560_000_000
        assert officer_summary == controller_summary
        assert officer_response.json()["response_type"] == "object"
        assert controller_response.json()["response_type"] == "object"

        after = validate_success(
            api.get_appropriation(appropriation_id, budget_analyst_headers), 200
        )
        assert after["version"] == version_before
        assert_two_bases(after)


class TestEmergencyAppropriationPhaseGate:
    @staticmethod
    def _emergency_payload(cycle_id, agency_id):
        return {
            "budget_cycle_id": cycle_id,
            "agency_id": agency_id,
            "program_code": "E900",
            "requested_amount_cents": 100_000_000,
            "justification": "wildfire response",
        }

    def test_the_same_request_is_refused_in_legislative_and_granted_in_execution(
        self, api, budget_director_headers
    ):
        """PRD §3.7: "When an unbudgeted obligation lands mid-year, a `BudgetDirector` may grant an emergency appropriation out of the stabilization reserve."
        PRD §3.7: "The owning cycle must be in `EXECUTION`, otherwise `ERR_CYCLE_PHASE_INVALID`."
        PRD §3.7: "Emergency rows skip the legislative dimension entirely: the created row is `GENERAL` fund with `is_emergency` set to true, `introduced_amount_cents`, `committee_balance_cents`, and `enacted_amount_cents` all equal to `requested_amount_cents`, `authority_status` already `ENACTED`, and `cash_status` `UNRELEASED`, all in the same creation."
        PRD §3.7: "The cycle's `emergency_granted_cents` — the sum of `enacted_amount_cents` over its appropriations where `is_emergency` is true and `authority_status` is `ENACTED` — is recomputed and the cycle's `version` increments by 1."
        PRD §3.4: "Appropriations can be listed with optional `budget_cycle_id`, `agency_id`, `fund_type`, and `authority_status` filters."

        Design: Corner/endpoints/emergency_appropriation_is_only_available_in_the_execution_phase
        """
        ctx = fixtures.setup_cycle(
            stop_after="LEGISLATIVE",
            reserve_balance_cents=500_000_000,
            appropriations=(
                {
                    "fund_type": "GENERAL",
                    "program_code": "P100",
                    "introduced_amount_cents": 2_000_000_000,
                },
            ),
        )
        cycle_id = ctx["cycle"]["id"]
        payload = self._emergency_payload(cycle_id, ctx["agency"]["id"])

        validate_error(
            api.create_emergency_appropriation(payload, budget_director_headers),
            ApiErrorId.ERR_CYCLE_PHASE_INVALID,
            409,
        )
        rows, meta = validate_paginated(
            api.list_appropriations(budget_director_headers, {"budget_cycle_id": cycle_id})
        )
        assert meta["total_count"] == 1
        assert rows[0]["is_emergency"] is False

        fixtures.advance_phase(cycle_id, "ENACTED")
        fixtures.advance_phase(cycle_id, "EXECUTION")

        emergency = validate_success(
            api.create_emergency_appropriation(payload, budget_director_headers), 201
        )
        assert emergency["fund_type"] == "GENERAL"
        assert emergency["is_emergency"] is True
        assert emergency["authority_status"] == "ENACTED"
        assert emergency["cash_status"] == "UNRELEASED"
        assert emergency["enacted_amount_cents"] == 100_000_000
        assert emergency["introduced_amount_cents"] == 100_000_000
        assert emergency["committee_balance_cents"] == 100_000_000

        _actions, action_meta = validate_paginated(
            api.list_appropriation_committee_actions(emergency["id"], budget_director_headers)
        )
        assert action_meta["total_count"] == 0

        cycle = fixtures.read_budget_cycle(cycle_id)
        assert cycle["emergency_granted_cents"] == 100_000_000

        rows, meta = validate_paginated(
            api.list_appropriations(budget_director_headers, {"budget_cycle_id": cycle_id})
        )
        assert meta["total_count"] == 2
        assert {row["is_emergency"] for row in rows} == {False, True}


class TestResponseEnvelope:
    def test_object_array_and_error_responses_all_carry_a_fresh_meta_block(
        self, api, system_admin_headers, budget_analyst_headers
    ):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
        PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits."
        PRD §2.2: "The `data` field contains the resource object or an array of resource objects."
        PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints."
        PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."
        PRD §2.12: "Code uniqueness holds: `agency_code` is unique across agencies, `fiscal_year` is unique across cycles, and `program_code` is unique within a `budget_cycle_id` and `agency_id` pair — otherwise `ERR_DUPLICATE_CODE` (409)."

        Design: Corner/endpoints/every_response_carries_the_meta_envelope_and_a_response_type
        """
        fixtures.register_agency(
            agency_code="DOE", name="Department of Education", agency_type="EXECUTIVE"
        )

        create_response = api.create_budget_cycle(
            {
                "fiscal_year": 2027,
                "fiscal_year_start_date": "2026-07-01",
                "reserve_balance_cents": 500_000_000,
                "constitutional_reserve_pct": 0.05,
            },
            system_admin_headers,
        )
        cycle = validate_success(create_response, 201)
        create_body = create_response.json()
        assert create_body["response_type"] == "object"
        assert create_body["data"]["id"] == cycle["id"]
        assert_meta_envelope(create_body)

        list_response = api.list_appropriations(
            budget_analyst_headers, {"budget_cycle_id": cycle["id"]}
        )
        rows, meta = validate_paginated(list_response)
        list_body = list_response.json()
        assert list_body["response_type"] == "array"
        assert rows == []
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 0
        assert meta["has_more"] is False
        assert_meta_envelope(list_body)

        error_response = api.create_agency(
            {
                "agency_code": "DOE",
                "name": "Duplicate Department of Education",
                "agency_type": "EXECUTIVE",
            },
            system_admin_headers,
        )
        validate_error(error_response, ApiErrorId.ERR_DUPLICATE_CODE, 409)
        error_body = error_response.json()
        assert error_body["response_type"] == "error"
        assert error_body["data"]["error_id"] == "ERR_DUPLICATE_CODE"
        assert isinstance(error_body["data"]["message"], str)
        assert error_body["data"]["message"] != ""
        assert set(error_body["meta"]) == {"api_request_id", "api_request_timestamp"}
        assert_meta_envelope(error_body)

        request_ids = [
            create_body["meta"]["api_request_id"],
            list_body["meta"]["api_request_id"],
            error_body["meta"]["api_request_id"],
        ]
        assert len(set(request_ids)) == 3


class TestQueryParameterRejections:
    def test_out_of_range_windows_and_an_unknown_enum_are_malformed_requests(
        self, api, budget_analyst_headers
    ):
        """PRD §2.3: "`limit` is the maximum number of rows to return; it defaults to 10, its minimum accepted value is 1, and its maximum accepted value is 100."
        PRD §2.3: "`offset` is the number of rows to skip; it defaults to 0 and its minimum accepted value is 0."
        PRD §2.3: "A `limit` outside the range from 1 to 100 inclusive, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §2.12: "The body is well formed — required fields present, enum members legal, integer fields integral, `limit` within 1 to 100 and `offset` at least 0 — otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint."
        PRD §5: "required body field missing, unknown enum member, non-integer where an integer is required, or limit/offset outside 1..100 / >= 0 (HTTP 400)"

        Design: Corner/errors/pagination_bounds_and_unknown_enum_filters_return_invalid_request
        """
        fixtures.register_agency(**DOT)
        fixtures.open_budget_cycle()

        for params in (
            {"limit": 101},
            {"limit": 0},
            {"offset": -1},
            {"status": "NOT_A_STATUS"},
        ):
            validate_error(
                api.list_agency_requests(budget_analyst_headers, params),
                ApiErrorId.ERR_INVALID_REQUEST,
                400,
            )

        rows, meta = validate_paginated(
            api.list_agency_requests(budget_analyst_headers, {"limit": 100, "offset": 0})
        )
        assert rows == []
        assert meta["limit"] == 100
        assert meta["offset"] == 0
        assert meta["total_count"] == 0
        assert meta["has_more"] is False
