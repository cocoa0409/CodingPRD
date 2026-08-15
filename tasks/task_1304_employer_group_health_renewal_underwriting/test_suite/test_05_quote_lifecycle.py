"""Quote creation, OCC, proposal computations, and quote listing."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    api_client,
    create_broker,
    create_case_in_claims_pending,
    create_case_in_rating,
    add_modeled_plan,
    create_plan_design_payload,
    create_buydown_plan_payload,
    create_draft_quote,
    create_proposed_quote,
    create_quote_payload,
    setup_case_with_proposed_quote,
    TEST_USERS,
    make_broker_headers,
)

UW = TEST_USERS["underwriter_headers"]


class TestQuoteCreationGates:
    def test_quote_create_requires_modeled_plan_rejects_then_succeeds(self):
        """PRD section 3.5: "at least one plan design on the case must be in
        `MODELED` status (else `ERR_NO_MODELED_PLAN`)".
        PRD section 3.5: "The quote arrives in `DRAFT` with a server-assigned
        sequential `quote_number` (1, 2, 3, … within the case),
        `negotiation_round` initialized to 0, and `parent_quote_id` empty."

        Design: Difficulty/cross_entity_state_dependency/quote_create_requires_modeled_plan
        """
        broker = create_broker()
        case, _ = create_case_in_rating(broker["id"])
        resp = api_client.create_plan_design(
            case["id"], create_plan_design_payload(), UW
        )
        plan = get_success_data(resp)
        # Plan still DRAFT -> quote creation rejected.
        case_now = get_success_data(api_client.get_case(case["id"], UW))
        resp = api_client.create_quote(
            case["id"],
            create_quote_payload(plan["id"], case_now["version"]),
            UW,
        )
        validate_error(resp, ApiErrorId.ERR_NO_MODELED_PLAN)
        # Once MODELED, the same request succeeds.
        validate_success(api_client.model_plan(plan["id"], UW))
        case_now = get_success_data(api_client.get_case(case["id"], UW))
        resp = api_client.create_quote(
            case["id"],
            create_quote_payload(plan["id"], case_now["version"]),
            UW,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DRAFT"
        assert data["quote_number"] == 1

    def test_quote_create_requires_modeled_plan_error_only(self):
        """PRD section 3.5: "at least one plan design on the case must be in
        `MODELED` status (else `ERR_NO_MODELED_PLAN`)".

        Design: Difficulty/cross_entity_state_dependency/quote_create_requires_modeled_plan
        """
        broker = create_broker()
        case, _ = create_case_in_rating(broker["id"])
        plan = get_success_data(
            api_client.create_plan_design(
                case["id"], create_plan_design_payload(), UW
            )
        )
        case_now = get_success_data(api_client.get_case(case["id"], UW))
        resp = api_client.create_quote(
            case["id"],
            create_quote_payload(plan["id"], case_now["version"]),
            UW,
        )
        validate_error(resp, ApiErrorId.ERR_NO_MODELED_PLAN)
        _quotes, meta = validate_paginated(api_client.list_quotes(case["id"], UW))
        assert meta["total_count"] == 0

    def test_create_quote_before_rating_fails(self):
        """PRD section 3.5: "The case must also be in a quotable posture for the
        first quote — `RATING_IN_PROGRESS` — or the request fails with
        `ERR_CASE_NOT_IN_RATING`."

        Design: Corner/errors/create_quote_before_rating_fails
        """
        broker = create_broker()
        case, _census = create_case_in_claims_pending(broker["id"])
        # Modeling is allowed from CENSUS_RECEIVED onward; the case here has
        # passed through CENSUS_RECEIVED, so a MODELED plan can exist while the
        # case is CLAIMS_PENDING.
        plan = add_modeled_plan(case["id"])
        case_now = get_success_data(api_client.get_case(case["id"], UW))
        resp = api_client.create_quote(
            case["id"],
            create_quote_payload(plan["id"], case_now["version"]),
            UW,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_IN_RATING)
        _quotes, meta = validate_paginated(api_client.list_quotes(case["id"], UW))
        assert meta["total_count"] == 0


class TestQuoteOcc:
    def test_occ_stale_version_on_quote_create(self):
        """PRD section 2.5: "If the case's current `version` no longer matches
        `expected_case_version` — for example because another underwriter created
        a quote in the meantime, which itself advances the case's `version` — the
        request is rejected with `ERR_STALE_VERSION` (HTTP 412) before any
        business logic is evaluated."

        Design: Corner/complexity_layers/occ_stale_version_on_quote_create
        """
        broker = create_broker()
        case, _ = create_case_in_rating(broker["id"])
        plan = add_modeled_plan(case["id"])
        case_now = get_success_data(api_client.get_case(case["id"], UW))
        observed_version = case_now["version"]
        first = api_client.create_quote(
            case["id"],
            create_quote_payload(plan["id"], observed_version),
            UW,
        )
        quote = validate_success(first, expected_status=201)
        assert quote["status"] == "DRAFT"
        # Replay with the same (now stale) version.
        resp = api_client.create_quote(
            case["id"],
            create_quote_payload(
                plan["id"], observed_version, funding_type="LEVEL_FUNDED",
                rate_guarantee_months=18,
            ),
            UW,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        _quotes, meta = validate_paginated(api_client.list_quotes(case["id"], UW))
        assert meta["total_count"] == 1

    def test_quote_creation_increments_case_version(self):
        """PRD section 3.5: "Creating the quote is itself a mutation of the
        parent case: the case's `version` increments by one."

        Design: Corner/complexity_layers/occ_stale_version_on_quote_create
        """
        broker = create_broker()
        case, _ = create_case_in_rating(broker["id"])
        plan = add_modeled_plan(case["id"])
        before = get_success_data(api_client.get_case(case["id"], UW))
        quote = create_draft_quote(case["id"], plan["id"])
        assert quote["status"] == "DRAFT"
        after = get_success_data(api_client.get_case(case["id"], UW))
        assert after["version"] == before["version"] + 1


class TestQuoteInitialState:
    def test_quote_initial_state_on_create(self):
        """PRD section 3.5: "The quote arrives in `DRAFT` with a
        server-assigned sequential `quote_number` (1, 2, 3, … within the case),
        `negotiation_round` initialized to 0, and `parent_quote_id` empty."

        Design: Corner/state_machines/quote_initial_state_on_create
        """
        broker = create_broker()
        case, _ = create_case_in_rating(broker["id"])
        plan = add_modeled_plan(case["id"])
        quote = create_draft_quote(case["id"], plan["id"])
        assert quote["status"] == "DRAFT"
        assert quote["negotiation_round"] == 0
        assert quote.get("parent_quote_id") in (None,)

    def test_quote_numbers_sequential_per_case(self):
        """PRD section 3.5: "The quote arrives in `DRAFT` with a
        server-assigned sequential `quote_number` (1, 2, 3, … within the case),
        `negotiation_round` initialized to 0, and `parent_quote_id` empty."

        Design: Corner/entities/quote_numbers_sequential_per_case
        """
        broker = create_broker()
        case, _ = create_case_in_rating(broker["id"])
        plan = add_modeled_plan(case["id"])
        q1 = create_draft_quote(case["id"], plan["id"])
        q2 = create_draft_quote(
            case["id"], plan["id"], rate_guarantee_months=24
        )
        assert q1["quote_number"] == 1
        assert q2["quote_number"] == 2


class TestProposalComputation:
    def test_pepm_rounded_before_annual_multiplication(self):
        """PRD section 3.5: "On proposal the quoted PEPM, `pepm_rate_cents`,
        is the case's `blended_rate_cents` multiplied by the referenced plan's
        `relativity_factor`, rounded half-up to whole cents."
        PRD section 3.5: "The `annual_premium_cents` is the PEPM times 12 times
        the validated census `enrolled_employees`."

        Design: Difficulty/combinatorial_formula/pepm_rounded_before_annual_multiplication
        """
        broker = create_broker()
        case, _ = create_case_in_rating(broker["id"])
        add_modeled_plan(case["id"])  # reference plan (relativity 1.0)
        resp = api_client.create_plan_design(
            case["id"], create_buydown_plan_payload(), UW
        )
        buydown = get_success_data(resp)
        validate_success(api_client.model_plan(buydown["id"], UW))
        quote = create_proposed_quote(case["id"], buydown["id"])
        # 5338 * 0.8123 = 4336.0574 -> 4336 (rounded first), then * 12 * 400.
        assert quote["pepm_rate_cents"] == 4336
        assert quote["annual_premium_cents"] == 20812800
        assert quote["renewal_increase_pct"] == pytest.approx(-0.1328, abs=1e-9)
        assert quote["broker_commission_cents"] == 832512
        assert quote["commission_disclosure_required"] is False
        assert quote["status"] == "PROPOSED"

    def test_pepm_rounding_order_observable_in_annual_premium(self):
        """PRD section 3.5: "On proposal the quoted PEPM, `pepm_rate_cents`,
        is the case's `blended_rate_cents` multiplied by the referenced plan's
        `relativity_factor`, rounded half-up to whole cents."
        Multiplying the unrounded product (4336.0574) by 4800 would give
        20813076; the PEPM-first rounding rule yields 20812800.

        Design: Difficulty/combinatorial_formula/pepm_rounded_before_annual_multiplication
        """
        broker = create_broker()
        case, _ = create_case_in_rating(broker["id"])
        add_modeled_plan(case["id"])
        buydown = get_success_data(
            api_client.create_plan_design(
                case["id"], create_buydown_plan_payload(), UW
            )
        )
        validate_success(api_client.model_plan(buydown["id"], UW))
        quote = create_proposed_quote(case["id"], buydown["id"])
        assert quote["annual_premium_cents"] == quote["pepm_rate_cents"] * 12 * 400
        assert quote["annual_premium_cents"] == 20812800
        assert quote["annual_premium_cents"] != 20813076

    def test_propose_response_contains_computed_rates(self):
        """PRD section 3.5: "The `renewal_increase_pct` measures the movement
        against the in-force premium: the annual premium minus
        `current_premium_annual`, divided by `current_premium_annual`, rounded
        half-up to four decimal places (the current PEPM baseline being
        `current_premium_annual` divided by 12 divided by
        `enrolled_employees`)."
        PRD section 3.5: "The `broker_commission_cents` is the annual premium
        multiplied by the broker of record's `commission_pct`, rounded half-up
        to whole cents".
        PRD section 2.2: "Unless otherwise noted, operations that create or
        modify a resource will return the created or updated resource object in
        the data field."

        Design: Corner/consistency_model/propose_response_contains_computed_rates
        """
        broker = create_broker()
        case, _ = create_case_in_rating(broker["id"])
        plan = add_modeled_plan(case["id"])
        quote = create_draft_quote(case["id"], plan["id"])
        resp = api_client.propose_quote(quote["id"], UW)
        data = validate_success(resp)
        assert data["pepm_rate_cents"] == 5338
        assert data["annual_premium_cents"] == 25622400
        assert data["renewal_increase_pct"] == pytest.approx(0.0676, abs=1e-9)
        assert data["broker_commission_cents"] == 1024896

    def test_propose_quote_twice_fails(self):
        """PRD section 3.5: "The quote must be `DRAFT` (else
        `ERR_QUOTE_NOT_DRAFT`)".

        Design: Corner/state_machines/propose_quote_twice_fails
        """
        _broker, case, _plan, quote = setup_case_with_proposed_quote()
        resp = api_client.propose_quote(quote["id"], UW)
        validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_DRAFT)
        quote = get_success_data(api_client.get_quote(quote["id"], UW))
        assert quote["status"] == "PROPOSED"
        assert quote["pepm_rate_cents"] == 5338


class TestQuoteListing:
    def test_list_quotes_reverse_reachability(self):
        """PRD section 2.3: "The `meta` object of a list response carries
        `limit`, `offset`, `total_count`, and `has_more`."
        PRD section 4 lists GET /underwriting-cases/{caseId}/quotes "List quotes
        for a case" and GET /quotes/{quoteId} "Get a specific quote", so a quote
        created under a case is reachable both through the case collection and
        by its own id.

        Design: Corner/endpoints/list_quotes_reverse_reachability
        """
        broker = create_broker()
        case, _ = create_case_in_rating(broker["id"])
        plan = add_modeled_plan(case["id"])
        quote = create_draft_quote(case["id"], plan["id"])
        data, meta = validate_paginated(
            api_client.list_quotes(case["id"], TEST_USERS["compliance_headers"])
        )
        assert len(data) == 1
        assert data[0]["id"] == quote["id"]
        assert data[0]["case_id"] == case["id"]
        reread = validate_success(
            api_client.get_quote(quote["id"], make_broker_headers(broker["id"]))
        )
        assert reread["id"] == quote["id"]
